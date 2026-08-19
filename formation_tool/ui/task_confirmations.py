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
        temp_db = getattr(deps, "get_sampling_temp_db", lambda: "")()
        increment_db = getattr(deps, "get_sampling_increment_db", lambda: "")()
        auto_sync = bool(getattr(deps, "get_sampling_auto_sync_to_target", lambda: False)())
        append_mode = bool(preflight.get("append_mode"))
        action = f"写入中转库 {temp_db} 正式表"
        if append_mode:
            action = f"读取目标库旧正式表，保留旧 id 后补充写入中转库 {temp_db} 正式表"
        lines = [
            f"即将执行采样并{action}：{title}",
            "",
            *build_mode_target_lines(preflight.get("modes"), "FINAL_TABLE", get_game_configs=deps.get_game_configs),
        ]
        if append_mode:
            lines.extend([
                "",
                "补充采样会先复制目标库旧数据到中转库并保留原始 id；新采样数据 id 从旧表最大 id + 1 开始连续分配。",
            ])
        if append_mode:
            lines.append(f"本次新增数据会单独写入增量库：{increment_db}")
        if auto_sync:
            lines.extend([
                "",
                "本次采样完成后会自动把中转库正式表镜像到目标库。",
            ])
        else:
            lines.extend([
                "",
                "本次采样完成后目标库不会变化；需要同步时请手动点击“镜像到目标库”。",
            ])
        return "\n".join(lines)
    if kind == "sampling_temp_mirror":
        temp_db = getattr(deps, "get_sampling_temp_db", lambda: "")()
        final_db = runtime.get("final_db")
        lines = [
            "即将把采样中转库中的正式表镜像到目标库：",
            "",
            f"  - 中转库：{temp_db}",
            f"  - 目标库：{final_db}",
            "",
            "继续后会扫描当前游戏在中转库中已存在的采样正式表，并安全替换目标库同名正式表。",
        ]
        return "\n".join(lines)
    if kind == "sampling_temp_sync":
        items = list(preflight.get("items") or [])
        lines = [
            "即将把采样临时库中的正式表同步到目标库：",
            "",
        ]
        for item in items:
            lines.append(
                f"  - {item.get('source_db')}.{item.get('table_name')} -> "
                f"{item.get('target_db')}.{item.get('table_name')} "
                f"({int(item.get('row_count') or 0)} 行)"
            )
        lines.extend([
            "",
            "继续后会使用目标库临时表安全替换目标库正式表。",
        ])
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
    if kind == "demo_common_config":
        db_name = runtime.get("weight_config_db") or runtime.get("config_db")
        return (
            "即将写入 demo 通用表配置：\n\n"
            f"目标库：{db_name}\n\n"
            "会写入 game_group_special_weight_config / game_group_free_game_config 的 group_id=0 行。"
        )
    return None
