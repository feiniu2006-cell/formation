"""Console/status message builders for group_weight generation."""

from formation_tool.utils import log_utils

print = log_utils.emit


def build_generation_summary_lines(context, *, deps):
    """Build the console summary shown before writing group_weight rows."""
    read_db_name = context['read_db_name']
    write_db_name = context['write_db_name']
    table_name = context['table_name']
    formation_exists = context['formation_exists']
    ex_modes_enabled = context['ex_modes_enabled']

    lines = [
        f"\n=== 生成 group_weight：{write_db_name}.{table_name} ===",
        f"读取采样配置：{read_db_name}；写入 group_weight：{write_db_name}",
        "说明：购买局 RTP 独立计算；普通局按免费/特殊触发贡献反推 rebate=0 的 weight",
    ]

    if deps.buy_group_enabled:
        source_suffix = deps.buy_group_source_suffix
        write_game_type = deps.get_group_weight_write_game_type(deps.buy_group_mode)
        if formation_exists.get(deps.buy_group_mode, False):
            lines.append(
                f"购买局：已开启，game_type={write_game_type}，source={source_suffix}，"
                f"读取 {read_db_name}.{deps.get_group_weight_rebate_table_name(deps.buy_group_mode)}"
            )
        else:
            lines.append(f"购买局：已开启，但未检测到 source={source_suffix}，跳过 game_type={write_game_type}")
    else:
        lines.append(
            f"购买局：已关闭，跳过 game_type={deps.get_group_weight_write_game_type(deps.buy_group_mode)}"
        )

    for item in deps.extra_buy_groups:
        mode = deps.make_extra_buy_mode(item['game_type'])
        source_suffix = item.get('source_suffix', deps.buy_group_source_suffix)
        if formation_exists.get(mode, False):
            lines.append(
                f"额外购买局：game_type={item['game_type']}，倍数={deps.format_weighted_rtp(item['multiplier'])}，"
                f"source={source_suffix}，读取 {read_db_name}.{deps.get_group_weight_rebate_table_name(mode)}"
            )
        else:
            lines.append(
                f"额外购买局：game_type={item['game_type']} 已配置，"
                f"但未检测到 source={source_suffix}，跳过"
            )

    if deps.ex_buy_group_enabled:
        lines.append(
            f"ex购买局：已开启，读取 {read_db_name}.{deps.get_group_weight_rebate_table_name(deps.ex_purchase_mode)}，"
            f"生成 game_type={deps.get_group_weight_write_game_type(deps.ex_purchase_mode)}"
        )
    else:
        lines.append(
            f"ex购买局：已关闭，跳过 game_type={deps.get_group_weight_write_game_type(deps.ex_purchase_mode)}"
        )

    if ex_modes_enabled:
        lines.append(
            f"ex模式：检测到 {', '.join(deps.game_type_names[mode] for mode in ex_modes_enabled)}，"
            f"ex倍数={deps.format_weighted_rtp(deps.ex_group_multiplier)}，"
            f"ex购买局倍数={deps.format_weighted_rtp(deps.buy_group_multiplier * deps.ex_group_multiplier)}"
        )
    else:
        lines.append("ex模式：未检测到 ex_formation/ex_special_formation/ex_free_formation，跳过")
    return lines


def print_generation_summary(context, *, deps):
    for line in build_generation_summary_lines(context, deps=deps):
        print(line)
