"""Default and extra buy group_weight generation."""

from formation_tool.group_weight.group_weight_logic import build_rebate_weight_pairs, format_weighted_rtp
from formation_tool.group_weight import group_weight_row_helpers
from formation_tool.core import runtime_context_sync
from formation_tool.utils import log_utils

print = log_utils.emit


def configure(**values):
    runtime_context_sync.configure_module_globals(globals(), values)


def append_extra_buy_group_weight_rows(rows, source_rebates, extra_buy):
    """额外购买局：复用配置的源 rebate_count，并使用自己的 game_type、倍数和权重规则。"""
    write_game_type = int(extra_buy['game_type'])
    multiplier = float(extra_buy['multiplier'])
    pairs, skipped_zero, skipped_rebate_zero = build_rebate_weight_pairs(
        source_rebates,
        extra_buy.get('rules', GROUP_WEIGHT_RULES.get(BUY_GROUP_MODE, [])),
    )
    if not pairs:
        return {
            'write_game_type': write_game_type,
            'multiplier': multiplier,
            'pairs': pairs,
            'skipped_zero': skipped_zero,
            'skipped_rebate_zero': skipped_rebate_zero,
            'mode_rows': 0,
            'rtp': None,
            'display_rtp': None,
        }

    mode_rows, game_rtp, display_rtp = group_weight_row_helpers.append_buy_like_group_weight_rows(
        rows,
        write_game_type,
        pairs,
        multiplier,
    )
    return {
        'write_game_type': write_game_type,
        'multiplier': multiplier,
        'pairs': pairs,
        'skipped_zero': skipped_zero,
        'skipped_rebate_zero': skipped_rebate_zero,
        'mode_rows': mode_rows,
        'rtp': game_rtp,
        'display_rtp': display_rtp,
    }


def append_buy_group_weight_modes(rows, rebates_by_mode, mode_exists, mode_pairs):
    """Write the default buy group and extra buy groups."""
    if BUY_GROUP_ENABLED:
        game_type = BUY_GROUP_MODE
        mode_name_getter = globals().get('get_group_weight_mode_name')
        mode_name = (
            mode_name_getter(game_type)
            if callable(mode_name_getter)
            else GAME_TYPE_NAMES[game_type]
        )
        write_game_type = get_group_weight_write_game_type(game_type)
        if not mode_exists.get(game_type, False):
            print(f"\n[{mode_name}] 没有对应采样配置表，跳过")
        elif not rebates_by_mode.get(game_type):
            print(f"\n[{mode_name}] 采样配置表没有数据，跳过")
        else:
            mode_rows, game_rtp, display_rtp = group_weight_row_helpers.append_buy_like_group_weight_rows(
                rows,
                write_game_type,
                mode_pairs[game_type],
                BUY_GROUP_MULTIPLIER,
            )
            print(
                f"\n[{mode_name}] RTP={format_weighted_rtp(game_rtp)}，game_type={write_game_type}，"
                f"购买倍数={format_weighted_rtp(BUY_GROUP_MULTIPLIER)}，"
                f"显示RTP={format_weighted_rtp(display_rtp)}，准备写入 {mode_rows} 行"
            )

    for extra_buy in EXTRA_BUY_GROUPS:
        source_mode = make_extra_buy_mode(extra_buy['game_type'])
        write_game_type = int(extra_buy['game_type'])
        if not mode_exists.get(source_mode, False):
            print(f"\n[额外购买局 game_type={write_game_type}] 没有对应采样配置表，跳过")
            continue
        if not rebates_by_mode.get(source_mode):
            print(f"\n[额外购买局 game_type={write_game_type}] 采样配置表没有数据，跳过")
            continue
        extra_info = append_extra_buy_group_weight_rows(
            rows,
            rebates_by_mode[source_mode],
            extra_buy,
        )
        if not extra_info['pairs']:
            print(f"\n[额外购买局 game_type={write_game_type}] 没有可写入的非0权重 rebate，跳过")
            continue
        print(
            f"\n[额外购买局 game_type={write_game_type}] "
            f"RTP={format_weighted_rtp(extra_info['rtp'])}，"
            f"购买倍数={format_weighted_rtp(extra_info['multiplier'])}，"
            f"显示RTP={format_weighted_rtp(extra_info['display_rtp'])}，"
            f"跳过 weight=0 的 rebate {extra_info['skipped_zero']} 个，准备写入 {extra_info['mode_rows']} 行"
        )
