"""Load rebate_count values used by group_weight preview and generation."""

from formation_tool.utils import log_utils

print = log_utils.emit


def build_preview_modes(group_weight_modes, extra_buy_groups, *, make_extra_buy_mode):
    modes = list(group_weight_modes)
    modes.extend(make_extra_buy_mode(group['game_type']) for group in extra_buy_groups)
    return modes


def load_group_weight_preview_rebates(*, deps, buy_enabled=None):
    """Load rebate values for the group_weight dialog preview."""
    config_db = deps.get_config_db()
    if buy_enabled is None:
        buy_enabled = deps.has_any_buy_group()
    preview_modes = deps.build_preview_modes()
    result = {mode: [] for mode in preview_modes}
    status = {}
    formation_exists = deps.get_group_weight_formation_exists()
    conn = deps.connect_to_database(config_db)
    if not conn:
        for mode in preview_modes:
            status[mode] = f"无法连接配置库 {config_db}"
        return result, status

    try:
        for mode in preview_modes:
            if mode == deps.buy_group_mode and not buy_enabled:
                status[mode] = "购买局：未启用"
                continue
            if mode == deps.ex_purchase_mode and not deps.get_ex_buy_group_enabled():
                status[mode] = "ex购买局：未启用"
                continue
            if not formation_exists.get(mode, False):
                check_error = deps.get_source_formation_check_error_for_mode(mode)
                if check_error:
                    status[mode] = f"{deps.get_group_weight_mode_name(mode)}：formation 检测失败，{check_error}"
                else:
                    status[mode] = f"{deps.get_group_weight_mode_name(mode)}：未检测到对应 formation"
                continue
            rebate_table = deps.get_group_weight_rebate_table_name(mode)
            mode_name = deps.get_group_weight_mode_name(mode)
            try:
                if not deps.table_exists_exact(conn, rebate_table):
                    status[mode] = f"{mode_name}：没有对应表 {config_db}.{rebate_table}"
                    continue
                rebates = deps.read_rebate_config_values(conn, rebate_table)
                result[mode] = rebates
                if rebates:
                    status[mode] = f"{mode_name}：{rebate_table} 已读取 {len(rebates)} 个 rebate"
                else:
                    status[mode] = f"{mode_name}：{config_db}.{rebate_table} 没有数据"
            except Exception as e:
                status[mode] = f"{mode_name}：读取 {rebate_table} 失败: {e}"
        return result, status
    finally:
        deps.close_safely(conn)


def get_group_weight_rules_for_mode(mode, *, deps):
    if deps.is_extra_buy_mode(mode):
        extra_group = deps.get_extra_buy_group_by_mode(mode) or {}
        return extra_group.get('rules', deps.default_buy_group_weight_rules())
    return deps.get_group_weight_rules().get(mode, [])


def load_group_weight_rebates_for_modes(conn, active_modes, read_db_name, *, deps):
    """Load rebate_count values for a group_weight generation run."""
    all_modes = list(dict.fromkeys(list(deps.group_weight_modes) + list(active_modes)))
    rebates_by_mode = {mode: [] for mode in all_modes}
    mode_exists = {mode: False for mode in all_modes}

    for game_type in active_modes:
        deps.check_cancelled()
        mode_name = deps.get_group_weight_mode_name(game_type)
        rebate_table = deps.get_group_weight_rebate_table_name(game_type)
        rules = get_group_weight_rules_for_mode(game_type, deps=deps)
        print(f"\n[{mode_name}] 读取 {read_db_name}.{rebate_table}，区间规则 {len(rules)} 条")
        if not deps.table_exists_exact(conn, rebate_table):
            print(f"  没有对应表：{read_db_name}.{rebate_table}")
            continue
        mode_exists[game_type] = True
        try:
            rebates_by_mode[game_type] = deps.read_rebate_config_values(conn, rebate_table)
        except Exception as e:
            print(f"  读取失败，按不存在处理: {e}")
            mode_exists[game_type] = False
            rebates_by_mode[game_type] = []
            continue
        if rebates_by_mode[game_type]:
            print(f"  已读取 {len(rebates_by_mode[game_type])} 个已选 rebate")
        else:
            print(f"  表存在但没有数据：{read_db_name}.{rebate_table}")

    return rebates_by_mode, mode_exists
