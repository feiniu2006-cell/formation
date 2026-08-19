"""Runner for generating group_weight data."""

from formation_tool.group_weight import group_weight_pair_sets
from formation_tool.utils import log_utils

print = log_utils.emit


def connect_group_weight_databases(read_db_name, write_db_name, *, deps):
    """连接 group_weight 读取库和写入库。"""
    read_conn = deps.connect_to_database(read_db_name)
    if not read_conn:
        print(f"无法连接配置库 {read_db_name}，生成 group_weight 终止")
        return None, None

    write_conn = deps.connect_to_database(write_db_name)
    if not write_conn:
        deps.close_safely(read_conn)
        print(f"无法连接目标库 {write_db_name}，生成 group_weight 终止")
        return None, None
    return read_conn, write_conn


def build_group_weight_generation_context(*, deps):
    """Build the runtime context for one group_weight generation run."""
    formation_exists = deps.get_group_weight_formation_exists()
    active_modes = deps.get_active_group_weight_modes(formation_exists)
    return {
        'read_db_name': deps.get_config_db(),
        'write_db_name': deps.get_final_db(),
        'table_name': deps.get_group_weight_table_name(),
        'formation_exists': formation_exists,
        'active_modes': active_modes,
        'ex_modes_enabled': [
            mode for mode in deps.ex_group_modes
            if formation_exists.get(mode, False)
        ],
    }


def build_demo_group_weight_generation_context(*, deps):
    """Build the runtime context for one demo group_weight generation run."""
    formation_exists = deps.get_group_weight_formation_exists()
    active_modes = deps.get_active_group_weight_modes(formation_exists)
    return {
        'read_db_name': deps.get_config_db(),
        'write_db_name': deps.get_final_db(),
        'table_name': deps.get_demo_group_weight_table_name(),
        'formation_exists': formation_exists,
        'active_modes': active_modes,
        'demo': True,
    }


def load_group_weight_generation_data(read_conn, context, *, deps):
    """Load selected rebate values and convert them to weighted rebate pairs."""
    rebates_by_mode, mode_exists = deps.load_group_weight_rebates_for_modes(
        read_conn,
        context['active_modes'],
        context['read_db_name'],
    )
    mode_pairs = deps.build_group_weight_pairs_for_modes(
        context['active_modes'],
        rebates_by_mode,
    )
    return rebates_by_mode, mode_exists, mode_pairs


def build_normalized_group_weight_generation_rows(
    formation_exists,
    rebates_by_mode,
    mode_exists,
    mode_pairs,
    *,
    deps,
):
    """Build and validate group_weight rows before writing."""
    rows = deps.build_group_weight_rows_from_loaded_data(
        formation_exists,
        rebates_by_mode,
        mode_exists,
        mode_pairs,
    )
    if rows is None:
        return None
    try:
        return deps.normalize_group_weight_rows(rows)
    except ValueError as exc:
        deps.print_group_weight_validation_failed(exc)
        return None


def build_group_weight_rows_for_write(context, rebates_by_mode, mode_exists, rows, *, deps):
    """Merge final weight=0 write-only rows right before replacing the table."""
    supplemental_rows = deps.build_group_weight_zero_weight_write_rows(
        context.get('active_modes') or [],
        rebates_by_mode,
        mode_exists,
        rows,
    )
    if not supplemental_rows:
        return rows
    try:
        return deps.normalize_group_weight_rows(list(rows) + list(supplemental_rows))
    except ValueError as exc:
        deps.print_group_weight_validation_failed(exc)
        return None


def collect_group_weight_generation_warnings(context, rebates_by_mode, mode_exists, mode_pairs, rows):
    """Collect non-blocking risks before replacing the final group_weight table."""
    warnings = []
    active_modes = context.get('active_modes') or []
    if not rows:
        warnings.append("没有可写入的 group_weight 行")
    for mode in active_modes:
        if not mode_exists.get(mode, False):
            warnings.append(f"模式 {mode} 对应的采样配置表不存在")
            continue
        if not rebates_by_mode.get(mode):
            warnings.append(f"模式 {mode} 的采样配置表为空或没有已选 rebate")
            continue
        if not group_weight_pair_sets.mode_has_any_pairs(mode_pairs, mode) and not rows:
            warnings.append(f"模式 {mode} 按当前权重规则匹配后没有可写入的 rebate")
    return warnings


def print_group_weight_generation_warnings(warnings):
    if not warnings:
        return
    print("\ngroup_weight 写入前风险提示：")
    for warning in warnings:
        print(f"- {warning}")


def write_group_weight_generation_rows(write_conn, context, rows, *, deps):
    """Write normalized group_weight rows to the final database."""
    if not rows:
        return 0
    target = f"{context['write_db_name']}.{context['table_name']}"
    deps.print_replace_with_staging_notice(target)
    written = deps.replace_group_weight_rows_atomically(
        write_conn,
        context['table_name'],
        rows,
        context['write_db_name'],
    )
    deps.print_write_complete(written, target)
    return written


def _read_existing_demo_trigger_rows(conn, table_name, columns, room_id, type_id, group_id, *, deps):
    table_ref = deps.quote_identifier(table_name, "trigger weight table")
    col_list = ', '.join(deps.quote_identifier(column, "trigger weight column") for column in columns)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {col_list}
            FROM {table_ref}
            WHERE `room_id` = %s AND `type_id` = %s AND `group_id` = %s
            """,
            (room_id, type_id, group_id),
        )
        return set(tuple(row) for row in cur.fetchall())


def _replace_demo_trigger_rows(conn, db_name, table_name, columns, row, *, deps):
    room_id = row[0]
    type_id = row[1]
    group_id = row[2]
    existing = _read_existing_demo_trigger_rows(
        conn,
        table_name,
        columns,
        room_id,
        type_id,
        group_id,
        deps=deps,
    )
    if existing == {tuple(row)}:
        print(f"{db_name}.{table_name} demo trigger group_id=0 unchanged, skipped")
        return 'skipped'

    table_ref = deps.quote_identifier(table_name, "trigger weight table")
    col_list = ', '.join(deps.quote_identifier(column, "trigger weight column") for column in columns)
    placeholders = ', '.join(['%s'] * len(columns))
    with conn.cursor() as cur:
        cur.execute(
            f"DELETE FROM {table_ref} WHERE `room_id` = %s AND `type_id` = %s AND `group_id` = %s",
            (room_id, type_id, group_id),
        )
        cur.execute(
            f"INSERT INTO {table_ref} ({col_list}) VALUES ({placeholders})",
            tuple(row),
        )
    conn.commit()
    deps.print_write_complete(1, f"{db_name}.{table_name} group_id=0")
    return True


def write_demo_trigger_weight_config(*, deps):
    """Write demo trigger weights into normal trigger config tables for group_id=0."""
    formation_exists = deps.get_group_weight_formation_exists()
    has_special = bool(formation_exists.get('2', False))
    has_free = bool(formation_exists.get('3', False))
    if not has_special and not has_free:
        print("Demo trigger config skipped: neither special nor free game formation exists")
        return True

    db_name = deps.get_weight_config_db()
    conn = deps.connect_to_database(db_name)
    if not conn:
        print(f"Unable to connect {db_name}, demo trigger weight write stopped")
        return False

    room_id = int(deps.game_id)
    type_id = int(deps.weight_type_id)
    group_id = 0
    special_weight = int(deps.special_weight_by_last_digit.get(0, 0))
    free_weight = int(deps.free_weight_by_last_digit.get(0, 0))
    try:
        print("\nWriting demo trigger weights to normal trigger config tables (group_id=0)...")
        special_result = True
        if has_special:
            special_result = _replace_demo_trigger_rows(
                conn,
                db_name,
                deps.special_weight_table,
                ['room_id', 'type_id', 'group_id', 'weight'],
                (room_id, type_id, group_id, special_weight),
                deps=deps,
            )
        else:
            print("Demo special trigger config skipped: special formation does not exist")

        free_result = True
        if has_free:
            free_result = _replace_demo_trigger_rows(
                conn,
                db_name,
                deps.free_game_config_table,
                ['room_id', 'type_id', 'group_id', 'weight', 'weight2', 'weight3'],
                (room_id, type_id, group_id, free_weight, 0, 0),
                deps=deps,
            )
        else:
            print("Demo free trigger config skipped: free formation does not exist")
        return special_result is not False and free_result is not False
    except Exception as exc:
        deps.print_step_error("write demo trigger weights failed", exc)
        deps.rollback_safely(conn)
        return False
    finally:
        deps.close_safely(conn)


def generate_group_weight_config(*, deps):
    """根据已生成的 rebate_count 配置表生成当前游戏的 group_weight 表。"""
    deps.check_cancelled()
    context = deps.build_group_weight_generation_context()
    deps.print_group_weight_generation_summary(context)

    read_conn, write_conn = deps.connect_group_weight_databases(
        context['read_db_name'],
        context['write_db_name'],
    )
    if not read_conn or not write_conn:
        return False

    try:
        rebates_by_mode, mode_exists, mode_pairs = deps.load_group_weight_generation_data(
            read_conn,
            context,
        )
        rows = deps.build_normalized_group_weight_generation_rows(
            context['formation_exists'],
            rebates_by_mode,
            mode_exists,
            mode_pairs,
        )
        if rows is None:
            return False
        rows = build_group_weight_rows_for_write(
            context,
            rebates_by_mode,
            mode_exists,
            rows,
            deps=deps,
        )
        if rows is None:
            return False
        if not rows:
            deps.print_no_group_weight_rows()

        print_group_weight_generation_warnings(
            collect_group_weight_generation_warnings(
                context,
                rebates_by_mode,
                mode_exists,
                mode_pairs,
                rows,
            )
        )
        deps.write_group_weight_generation_rows(write_conn, context, rows)
        deps.verify_group_weight_zero_rebate_rows(write_conn, context['table_name'], rows)
        return True
    except Exception as e:
        deps.print_step_error("生成 group_weight 失败", e)
        deps.rollback_safely(write_conn)
        return False
    finally:
        deps.close_safely(read_conn)
        deps.close_safely(write_conn)


def generate_demo_group_weight_config(*, deps):
    """Generate the demo group_weight table from rebate_count config tables."""
    deps.check_cancelled()
    context = deps.build_demo_group_weight_generation_context()
    print(
        f"\n生成演示用 group_weight：读取 {context['read_db_name']}，"
        f"写入 {context['write_db_name']}.{context['table_name']}"
    )

    read_conn, write_conn = deps.connect_group_weight_databases(
        context['read_db_name'],
        context['write_db_name'],
    )
    if not read_conn or not write_conn:
        return False

    try:
        rebates_by_mode, mode_exists = deps.load_group_weight_rebates_for_modes(
            read_conn,
            context['active_modes'],
            context['read_db_name'],
        )
        rows, infos = deps.build_demo_group_weight_rows(
            context['active_modes'],
            rebates_by_mode,
            mode_exists,
            deps.get_demo_group_weight_rules(),
            deps.get_demo_group_weight_target_rtps(),
            deps.get_demo_zero_rebate_inference_modes(),
        )
        rows = deps.normalize_group_weight_rows(rows)
        if not rows:
            deps.print_no_group_weight_rows()
        for mode, info in infos.items():
            print(
                f"[演示用 {mode}] game_type={info['write_game_type']}，group_id=0，"
                f"目标RTP={info.get('display_target_rtp')}，写入{info['row_count']}行"
            )
        deps.write_group_weight_generation_rows(write_conn, context, rows)
        deps.verify_group_weight_zero_rebate_rows(write_conn, context['table_name'], rows)
        return True
    except Exception as e:
        deps.print_step_error("生成演示用 group_weight 失败", e)
        deps.rollback_safely(write_conn)
        return False
    finally:
        deps.close_safely(read_conn)
        deps.close_safely(write_conn)

