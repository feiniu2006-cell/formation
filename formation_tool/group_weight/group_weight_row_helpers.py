"""Shared row builders used by group_weight mode modules."""

from formation_tool.group_weight.group_weight_logic import (
    build_independent_group_weight_rows_for_group,
    build_special_group_weight_rows_for_group,
    calculate_weighted_rtp,
    get_ex_display_target_rtp,
)
from formation_tool.group_weight import group_weight_pair_sets
from formation_tool.core import runtime_context_sync


def configure(**values):
    runtime_context_sync.configure_module_globals(globals(), values)


def append_static_group_weight_rows(rows, write_game_type, pairs):
    """把同一套 rebate/weight 写入全部 group_id，返回新增行数。"""
    mode_rows = 0
    write_game_type = int(write_game_type)
    for group_id in WEIGHT_GROUP_IDS:
        group_pairs = group_weight_pair_sets.get_pairs_for_group(pairs, group_id)
        game_rows = [
            (write_game_type, int(group_id), int(rebate), int(weight))
            for rebate, weight in group_pairs
        ]
        rows.extend(game_rows)
        mode_rows += len(game_rows)
    return mode_rows


def append_buy_like_group_weight_rows(rows, write_game_type, pairs, multiplier):
    """写入购买局类 group_weight 行，并返回写入数量与 RTP 信息。"""
    mode_rows = append_static_group_weight_rows(rows, write_game_type, pairs)
    first_pairs = (
        group_weight_pair_sets.get_pairs_for_group(pairs, WEIGHT_GROUP_IDS[0])
        if WEIGHT_GROUP_IDS
        else []
    )
    game_rtp = calculate_weighted_rtp(first_pairs)
    display_rtp = None if game_rtp is None else game_rtp / float(multiplier)
    return mode_rows, game_rtp, display_rtp


def append_targeted_buy_like_group_weight_rows(rows, write_game_type, pairs, multiplier):
    """Write buy-like rows while inferring rebate=0 per RTP group target."""
    mode_rows = 0
    infos = {}
    write_game_type = int(write_game_type)
    multiplier = float(multiplier)
    for group_id in WEIGHT_GROUP_IDS:
        group_id = int(group_id)
        base_target_rtp = get_group_target_rtp_ratio(group_id)
        group_pairs = group_weight_pair_sets.get_pairs_for_group(pairs, group_id)
        game_rows, info = build_independent_group_weight_rows_for_group(
            group_id,
            write_game_type,
            group_pairs,
            True,
            base_target_rtp * multiplier,
            display_divisor=multiplier,
        )
        info['base_target_rtp'] = base_target_rtp
        info['multiplier'] = multiplier
        infos[group_id] = info
        rows.extend(game_rows)
        mode_rows += len(game_rows)
    return mode_rows, infos


def append_special_group_weight_rows(rows, write_game_type, pairs, zero_weight):
    """写入需要把 rebate=0 放第一条的局类型，返回新增行数。"""
    mode_rows = 0
    for group_id in WEIGHT_GROUP_IDS:
        group_pairs = group_weight_pair_sets.get_pairs_for_group(pairs, group_id)
        game_rows = build_special_group_weight_rows_for_group(
            group_id,
            group_pairs,
            zero_weight,
            game_type=write_game_type,
        )
        rows.extend(game_rows)
        mode_rows += len(game_rows)
    return mode_rows


def append_independent_ex_group_rows(rows, game_type, pairs, has_zero):
    """写入独立 RTP 反推的 ex 模式，返回新增行数和每组 RTP 信息。"""
    mode_rows = 0
    infos = {}
    for group_id in WEIGHT_GROUP_IDS:
        group_pairs = group_weight_pair_sets.get_pairs_for_group(pairs, group_id)
        display_target_rtp = get_ex_display_target_rtp(
            group_id,
            game_type,
            EX_GROUP_TARGET_RTPS,
            target_rtp_getter=get_group_target_rtp_ratio,
        )
        target_rtp = display_target_rtp * EX_GROUP_MULTIPLIER
        game_rows, info = build_independent_group_weight_rows_for_group(
            group_id,
            int(game_type),
            group_pairs,
            has_zero,
            target_rtp,
            display_divisor=EX_GROUP_MULTIPLIER,
        )
        info['base_target_rtp'] = display_target_rtp
        infos[int(group_id)] = info
        rows.extend(game_rows)
        mode_rows += len(game_rows)
    return mode_rows, infos


def has_rebate_zero(rebates):
    """采样配置中是否包含 rebate=0。"""
    return any(int(value) == 0 for value in rebates)
