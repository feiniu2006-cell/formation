"""Shared row builders used by group_weight mode modules."""

from formation_tool.group_weight.group_weight_logic import (
    build_independent_group_weight_rows_for_group,
    build_special_group_weight_rows_for_group,
    calculate_weighted_rtp,
)
from formation_tool.core import runtime_context_sync


def configure(**values):
    runtime_context_sync.configure_module_globals(globals(), values)


def append_static_group_weight_rows(rows, write_game_type, pairs):
    """把同一套 rebate/weight 写入全部 group_id，返回新增行数。"""
    mode_rows = 0
    write_game_type = int(write_game_type)
    for group_id in WEIGHT_GROUP_IDS:
        game_rows = [
            (write_game_type, int(group_id), int(rebate), int(weight))
            for rebate, weight in pairs
        ]
        rows.extend(game_rows)
        mode_rows += len(game_rows)
    return mode_rows


def append_buy_like_group_weight_rows(rows, write_game_type, pairs, multiplier):
    """写入购买局类 group_weight 行，并返回写入数量与 RTP 信息。"""
    mode_rows = append_static_group_weight_rows(rows, write_game_type, pairs)
    game_rtp = calculate_weighted_rtp(pairs)
    display_rtp = None if game_rtp is None else game_rtp / float(multiplier)
    return mode_rows, game_rtp, display_rtp


def append_special_group_weight_rows(rows, write_game_type, pairs, zero_weight):
    """写入需要把 rebate=0 放第一条的局类型，返回新增行数。"""
    mode_rows = 0
    for group_id in WEIGHT_GROUP_IDS:
        game_rows = build_special_group_weight_rows_for_group(
            group_id,
            pairs,
            zero_weight,
            game_type=write_game_type,
        )
        rows.extend(game_rows)
        mode_rows += len(game_rows)
    return mode_rows


def append_independent_ex_group_rows(rows, game_type, pairs, has_zero):
    """写入 ex特殊/ex免费这类独立 RTP 模式，返回新增行数和每组 RTP 信息。"""
    mode_rows = 0
    infos = {}
    for group_id in WEIGHT_GROUP_IDS:
        target_rtp = get_group_target_rtp_ratio(group_id) * EX_GROUP_MULTIPLIER
        game_rows, info = build_independent_group_weight_rows_for_group(
            group_id,
            int(game_type),
            pairs,
            has_zero,
            target_rtp,
            display_divisor=EX_GROUP_MULTIPLIER,
        )
        info['base_target_rtp'] = get_group_target_rtp_ratio(group_id)
        infos[int(group_id)] = info
        rows.extend(game_rows)
        mode_rows += len(game_rows)
    return mode_rows, infos


def has_rebate_zero(rebates):
    """采样配置中是否包含 rebate=0。"""
    return any(int(value) == 0 for value in rebates)
