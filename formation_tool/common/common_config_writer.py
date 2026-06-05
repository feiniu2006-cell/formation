"""Writers for per-game common configuration tables."""
import math

from formation_tool.utils import log_utils


def write_weight_config(deps, table_name, columns, rows, db_name, room_id, type_id=None):
    """Replace rows for the current room/type only when data changed."""
    conn = deps.connect_to_database(db_name)
    if not conn:
        print(f"无法连接 {db_name}，写入终止")
        return False
    try:
        table_ref = deps.quote_identifier(table_name, "权重配置表名")
        col_list = ', '.join(deps.quote_identifier(c, "字段名") for c in columns)
        where_sql = "`room_id` = %s"
        where_params = [room_id]
        if type_id is not None and 'type_id' in columns:
            where_sql += " AND `type_id` = %s"
            where_params.append(type_id)

        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {col_list} FROM {table_ref} WHERE {where_sql}",
                tuple(where_params),
            )
            existing = set(tuple(row) for row in cur.fetchall())
        new_set = set(tuple(row) for row in rows)
        if existing == new_set:
            print(f"当前游戏数据未变化，跳过写入 {db_name}.{table_name}")
            return 'skipped'

        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {table_ref} WHERE {where_sql}", tuple(where_params))
            deleted = cur.rowcount
            if deleted > 0:
                scope = f"room_id={room_id}"
                if type_id is not None and 'type_id' in columns:
                    scope += f", type_id={type_id}"
                print(f"已删除 {db_name}.{table_name} 中 {scope} 的 {deleted} 条旧数据")
            placeholders = ', '.join(['%s'] * len(columns))
            cur.executemany(
                f"INSERT INTO {table_ref} ({col_list}) VALUES ({placeholders})",
                rows,
            )
        conn.commit()
        log_utils.print_write_complete(len(rows), f"{db_name}.{table_name}")
        return True
    except Exception as exc:
        deps.print_step_error("写入失败", exc)
        deps.rollback_safely(conn)
        return False
    finally:
        deps.close_safely(conn)


def table_exists_exact(conn, table_name, *, validate_sql_identifier):
    """Check whether table_name exists in the connected database."""
    table_name = validate_sql_identifier(table_name, "表名")
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = DATABASE()
              AND table_name = %s
            LIMIT 1
            """,
            (table_name,),
        )
        return cur.fetchone() is not None


def check_final_table_exists(deps, table_name):
    """Check whether a FINAL_DB table exists."""
    conn = deps.connect_to_database(deps.final_db)
    if not conn:
        return False
    try:
        return table_exists_exact(
            conn,
            table_name,
            validate_sql_identifier=deps.validate_sql_identifier,
        )
    except Exception:
        return False
    finally:
        deps.close_safely(conn)


def build_last_digit_weight_rows(room_id, type_id, group_ids, weight_by_last_digit, *, include_free_columns=False):
    rows = []
    print(f"{'group_id':>10}  {'weight':>8}")
    print("-" * 25)
    for group_id in group_ids:
        last_digit = group_id % 10
        weight = weight_by_last_digit.get(last_digit)
        if weight is None:
            print(f"  [WARN] group_id={group_id} 个位={last_digit} 无匹配权重配置，跳过")
            continue
        print(f"{group_id:>10}  {weight:>8}")
        if include_free_columns:
            rows.append((room_id, type_id, group_id, weight, 0, 0))
        else:
            rows.append((room_id, type_id, group_id, weight))
    return rows


def write_special_weight_config(deps):
    """Write game_group_special_weight_config for the current game."""
    room_id = int(deps.game_id)
    formation_table = f'{deps.game_table_prefix}special_formation'
    print(f"\n{'='*50}")
    print(f"正在生成 {deps.special_weight_table} 写入数据（room_id={room_id}）...")
    if not check_final_table_exists(deps, formation_table):
        print(f"  [WARN] {deps.final_db} 中未找到 {formation_table}，跳过写入 {deps.special_weight_table}")
        return 'skipped'
    rows = build_last_digit_weight_rows(
        room_id,
        deps.weight_type_id,
        deps.weight_group_ids,
        deps.special_weight_by_last_digit,
    )
    if not rows:
        print("无可写入数据")
        return False
    return write_weight_config(
        deps,
        deps.special_weight_table,
        ['room_id', 'type_id', 'group_id', 'weight'],
        rows,
        deps.weight_config_db,
        room_id,
        deps.weight_type_id,
    )


def write_free_game_config(deps):
    """Write game_group_free_game_config for the current game."""
    room_id = int(deps.game_id)
    formation_table = f'{deps.game_table_prefix}free_formation'
    print(f"\n{'='*50}")
    print(f"正在生成 {deps.free_game_config_table} 写入数据（room_id={room_id}）...")
    if not check_final_table_exists(deps, formation_table):
        print(f"  [WARN] {deps.final_db} 中未找到 {formation_table}，跳过写入 {deps.free_game_config_table}")
        return 'skipped'
    rows = build_last_digit_weight_rows(
        room_id,
        deps.weight_type_id,
        deps.weight_group_ids,
        deps.free_weight_by_last_digit,
        include_free_columns=True,
    )
    if not rows:
        print("无可写入数据")
        return False
    return write_weight_config(
        deps,
        deps.free_game_config_table,
        ['room_id', 'type_id', 'group_id', 'weight', 'weight2', 'weight3'],
        rows,
        deps.weight_config_db,
        room_id,
        deps.weight_type_id,
    )


def parse_number_list(text, label):
    """Parse a comma-separated numeric list."""
    values = [float(item.strip()) for item in str(text).split(',') if item.strip()]
    if not values:
        raise ValueError(f"{label} 不能为空")
    return values


def read_room_base_bet_config(conn, source_table, room_id, type_id, *, quote_identifier):
    """Read room base bet config for the current room/type."""
    source_table_ref = quote_identifier(source_table, "房间基础配置表名")
    with conn.cursor(dictionary=True) as cur:
        cur.execute(
            f"""
            SELECT type_id, bet_amount, bet_rate, win_line
            FROM {source_table_ref}
            WHERE room_id = %s AND type_id = %s
            """,
            (room_id, type_id),
        )
        return cur.fetchone()


def calculate_bet_amount_values(base_row):
    """Calculate game_bet_amount_config values from room base config."""
    type_id = int(base_row['type_id'])
    bet_amounts = parse_number_list(base_row['bet_amount'], "bet_amount")
    bet_rates = parse_number_list(base_row['bet_rate'], "bet_rate")
    win_line = float(base_row['win_line'])

    print(f"  bet_amount : {bet_amounts}")
    print(f"  bet_rate   : {bet_rates}")
    print(f"  win_line   : {win_line}")

    values = set()
    for bet_amount in bet_amounts:
        for bet_rate in bet_rates:
            raw = round(bet_amount * bet_rate * win_line * 1000, 8)
            values.add(math.ceil(raw))
    sorted_values = sorted(values)
    print(f"\n计算结果（共 {len(sorted_values)} 个档位）: {sorted_values}")
    return type_id, sorted_values


def read_existing_bet_amount_set(conn, table_name, room_id, type_id, *, quote_identifier):
    """Read existing bet amount rows for comparison."""
    table_ref = quote_identifier(table_name, "押注配置表名")
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT type_id, bet_amount FROM {table_ref} WHERE room_id = %s AND type_id = %s",
            (room_id, type_id),
        )
        return set(tuple(row) for row in cur.fetchall())


def replace_bet_amount_rows(conn, db_name, table_name, room_id, type_id, sorted_values, *, quote_identifier):
    """Replace current room/type bet amount rows."""
    table_ref = quote_identifier(table_name, "押注配置表名")
    rows = [(room_id, type_id, value) for value in sorted_values]
    with conn.cursor() as cur:
        cur.execute(
            f"DELETE FROM {table_ref} WHERE room_id = %s AND type_id = %s",
            (room_id, type_id),
        )
        deleted = cur.rowcount
        if deleted > 0:
            print(
                f"已删除 {db_name}.{table_name} 中 room_id={room_id}, "
                f"type_id={type_id} 的 {deleted} 条旧数据"
            )
        cur.executemany(
            f"INSERT INTO {table_ref} (room_id, type_id, bet_amount) VALUES (%s, %s, %s)",
            rows,
        )
    conn.commit()
    log_utils.print_write_complete(len(rows), f"{db_name}.{table_name}")


def write_bet_amount_config(deps):
    """Read game_room_base_config and write calculated game_bet_amount_config rows."""
    room_id = int(deps.game_id)
    db_name = deps.weight_config_db
    table_name = deps.bet_amount_table
    source_table = 'game_room_base_config'

    print(f"\n{'='*50}")
    print(
        f"正在从 {db_name}.{source_table} 读取当前游戏押注配置"
        f"（room_id={room_id}, type_id={deps.weight_type_id}）..."
    )

    conn = deps.connect_to_database(db_name)
    if not conn:
        print(f"无法连接 {db_name}，写入终止")
        return False
    try:
        base_row = read_room_base_bet_config(
            conn,
            source_table,
            room_id,
            deps.weight_type_id,
            quote_identifier=deps.quote_identifier,
        )
        if not base_row:
            print(
                f"在 {source_table} 中未找到 room_id={room_id}, "
                f"type_id={deps.weight_type_id} 的数据，写入终止"
            )
            return False

        type_id, sorted_values = calculate_bet_amount_values(base_row)
        existing = read_existing_bet_amount_set(
            conn,
            table_name,
            room_id,
            deps.weight_type_id,
            quote_identifier=deps.quote_identifier,
        )
        if existing == set((type_id, value) for value in sorted_values):
            print(f"数据无变化，跳过写入（共 {len(sorted_values)} 个档位）")
            return 'skipped'

        replace_bet_amount_rows(
            conn,
            db_name,
            table_name,
            room_id,
            type_id,
            sorted_values,
            quote_identifier=deps.quote_identifier,
        )
        return True
    except Exception as exc:
        print(f"写入失败: {exc}")
        deps.rollback_safely(conn)
        return False
    finally:
        deps.close_safely(conn)
