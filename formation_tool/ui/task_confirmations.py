"""Dangerous task confirmation message builders."""


def normalize_task_modes(modes, game_configs):
    if modes in (None, "all"):
        return list(game_configs)
    return [str(mode) for mode in modes if str(mode) in game_configs]


def build_mode_target_lines(modes, table_key, *, get_game_configs):
    game_configs = get_game_configs()
    lines = []
    for mode in normalize_task_modes(modes, game_configs):
        config = game_configs.get(mode)
        if not config:
            continue
        table_info = config["table_config"].get(table_key, {})
        lines.append(f"  - {config['name']}: {table_info.get('database')}.{table_info.get('name')}")
    return lines


def build_dangerous_task_confirmation(title, preflight, *, deps):
    """Return a confirmation message for write/replace tasks, or None."""
    if not preflight:
        return None
    kind = preflight.get("kind")
    runtime = deps.get_runtime_state()
    if kind == "rebate_config":
        lines = [
            f"即将生成并替换当前游戏的采样配置表：{title}",
            "",
            *build_mode_target_lines(preflight.get("modes"), "REBATE_CONFIG_TABLE", get_game_configs=deps.get_game_configs),
            "",
            "继续后会使用临时表安全替换对应 count 表。",
        ]
        return "\n".join(lines)
    if kind == "sampling":
        append_mode = deps.get_sampling_append_mode()
        action = "追加写入目标阵型表" if append_mode else "清空/替换目标阵型表"
        lines = [
            f"即将执行采样并{action}：{title}",
            "",
            *build_mode_target_lines(preflight.get("modes"), "FINAL_TABLE", get_game_configs=deps.get_game_configs),
        ]
        if append_mode:
            lines.append("")
            lines.append("追加模式下，如新采样 id 与旧数据冲突，会自动改写新数据 id。")
        else:
            lines.append("")
            lines.append("当前不是追加模式，正式表会被新采样结果替换。")
        return "\n".join(lines)
    if kind == "group_weight":
        table_name = f"{runtime['vendor']}_{runtime['game_id']}_group_weight"
        return (
            "即将生成并替换 group_weight 表：\n\n"
            f"  - {runtime['final_db']}.{table_name}\n\n"
            "继续后会用当前权重规则和采样配置重新生成。"
        )
    if kind == "common_config":
        return (
            "即将写入当前游戏的通用配置表。\n\n"
            f"目标库：{runtime['final_db']}\n\n"
            "会写入特殊局/免费局触发权重和下注配置等通用配置。"
        )
    return None
