"""EX mode group_weight generation."""

from formation_tool.group_weight.group_weight_logic import (
    build_independent_group_weight_rows_for_group,
    build_normal_group_weight_rows_for_group,
    calculate_weighted_rtp,
    format_weighted_rtp,
    should_infer_zero_rebate,
)
from formation_tool.group_weight import group_weight_row_helpers
from formation_tool.group_weight import group_weight_pair_sets
from formation_tool.core import runtime_context_sync
from formation_tool.utils import log_utils

print = log_utils.emit


def configure(**values):
    runtime_context_sync.configure_module_globals(globals(), values)


def should_skip_group_weight_mode_data(game_type, mode_exists, rebates_by_mode):
    """检查某个 group_weight 模式是否缺少可用采样配置数据。"""
    mode_name = GAME_TYPE_NAMES[game_type]
    if not mode_exists[game_type]:
        print(f"\n[{mode_name}] 没有对应采样配置表，跳过")
        return True
    if not rebates_by_mode[game_type]:
        print(f"\n[{mode_name}] 采样配置表没有数据，跳过")
        return True
    return False


def log_ex_independent_group_weight_result(game_type, mode_infos, has_zero, mode_rows):
    mode_name = GAME_TYPE_NAMES[game_type]
    for group_id in WEIGHT_GROUP_IDS:
        info = mode_infos[int(group_id)]
        print(
            f"  group_id={group_id} 目标RTP={format_weighted_rtp(info['base_target_rtp'])}，"
            f"反推目标={format_weighted_rtp(info['target_rtp'])}，"
            f"rebate=0 weight={info['zero_weight']}，"
            f"实际RTP={format_weighted_rtp(info['actual_rtp'])}，"
            f"最终RTP={format_weighted_rtp(info['display_rtp'])}"
        )
    print(
        f"\n[{mode_name}] ex倍数={format_weighted_rtp(EX_GROUP_MULTIPLIER)}，"
        f"rebate=0 {'存在' if has_zero else '不存在'}，准备写入 {mode_rows} 行"
    )


def append_ex_independent_group_weight_modes(rows, formation_exists, rebates_by_mode, mode_exists, mode_pairs):
    """写入需要独立目标反推的 ex 模式，并返回每个 group_id 的 RTP 信息。"""
    ex_info_by_mode = {mode: {} for mode in EX_INDEPENDENT_GROUP_WEIGHT_MODES}
    for game_type in EX_INDEPENDENT_GROUP_WEIGHT_MODES:
        if not formation_exists.get(game_type, False):
            continue
        if should_skip_group_weight_mode_data(game_type, mode_exists, rebates_by_mode):
            continue

        has_zero = group_weight_row_helpers.has_rebate_zero(rebates_by_mode[game_type])
        should_infer = should_infer_zero_rebate(
            game_type,
            rebates_by_mode[game_type],
            globals().get('ZERO_REBATE_INFERENCE_MODES', set()),
        )
        mode_rows, ex_info_by_mode[game_type] = group_weight_row_helpers.append_independent_ex_group_rows(
            rows,
            game_type,
            mode_pairs[game_type],
            should_infer,
        )
        log_ex_independent_group_weight_result(
            game_type,
            ex_info_by_mode[game_type],
            has_zero,
            mode_rows,
        )
    return ex_info_by_mode


def append_ex_free_group_weight_mode(rows, formation_exists, rebates_by_mode, mode_exists, mode_pairs, ex_info_by_mode):
    """写入 ex免费局；和普通免费局一样按配置静态写入，不反推 rebate=0。"""
    game_type = '8'
    ex_info_by_mode.setdefault(game_type, {})
    if not formation_exists.get(game_type, False):
        return
    if should_skip_group_weight_mode_data(game_type, mode_exists, rebates_by_mode):
        return

    mode_rows = group_weight_row_helpers.append_static_group_weight_rows(
        rows,
        get_group_weight_write_game_type(game_type),
        mode_pairs[game_type],
    )
    for group_id in WEIGHT_GROUP_IDS:
        group_pairs = group_weight_pair_sets.get_pairs_for_mode_group(mode_pairs, game_type, group_id)
        game_rtp = calculate_weighted_rtp(group_pairs)
        display_rtp = None if game_rtp is None else game_rtp / float(EX_GROUP_MULTIPLIER)
        ex_info_by_mode[game_type][int(group_id)] = {
            'actual_rtp': game_rtp,
            'display_rtp': display_rtp,
            'zero_weight': 0,
        }
    print(
        f"\n[{GAME_TYPE_NAMES[game_type]}] RTP按分组规则计算，"
        f"ex倍数={format_weighted_rtp(EX_GROUP_MULTIPLIER)}，"
        f"按静态权重写入，不反推 rebate=0，准备写入 {mode_rows} 行"
    )


def append_ex_normal_group_weight_mode(rows, formation_exists, rebates_by_mode, mode_exists, mode_pairs, ex_info_by_mode):
    """写入 ex普通局。"""
    game_type = '6'
    if not formation_exists.get(game_type, False):
        return
    mode_name = GAME_TYPE_NAMES[game_type]
    if should_skip_group_weight_mode_data(game_type, mode_exists, rebates_by_mode):
        return

    mode_rows = 0
    normal_should_infer = should_infer_zero_rebate(
        game_type,
        rebates_by_mode[game_type],
        globals().get('ZERO_REBATE_INFERENCE_MODES', set()),
    )
    independent_rtp = game_type in {str(mode) for mode in globals().get('INDEPENDENT_RTP_MODES', set())}
    if independent_rtp:
        print(
            f"\n[{mode_name}] 独立计算RTP：开启，最终RTP目标=当前组，"
            f"反推目标按 ex倍数 {format_weighted_rtp(EX_GROUP_MULTIPLIER)} 折算"
        )
    for group_id in WEIGHT_GROUP_IDS:
        group_id = int(group_id)
        normal_pairs = group_weight_pair_sets.get_pairs_for_mode_group(mode_pairs, game_type, group_id)
        ex_special_pairs = group_weight_pair_sets.get_pairs_for_mode_group(mode_pairs, '7', group_id)
        ex_free_pairs = group_weight_pair_sets.get_pairs_for_mode_group(mode_pairs, '8', group_id)
        ex_special_enabled = mode_exists['7'] and bool(ex_special_pairs)
        ex_free_enabled = mode_exists['8'] and bool(ex_free_pairs)
        ex_special_rtp = (ex_info_by_mode['7'].get(group_id) or {}).get('actual_rtp') or 0
        ex_free_rtp = (ex_info_by_mode['8'].get(group_id) or {}).get('actual_rtp') or 0
        try:
            if independent_rtp:
                group_rows, group_info = build_independent_group_weight_rows_for_group(
                    group_id,
                    get_group_weight_write_game_type(game_type),
                    normal_pairs,
                    normal_should_infer,
                    get_group_target_rtp_ratio(group_id) * EX_GROUP_MULTIPLIER,
                    display_divisor=EX_GROUP_MULTIPLIER,
                )
            else:
                group_rows, group_info = build_normal_group_weight_rows_for_group(
                    group_id,
                    normal_pairs,
                    ex_free_rtp,
                    ex_free_enabled,
                    ex_special_rtp,
                    ex_special_enabled,
                    game_type=6,
                    target_multiplier=EX_GROUP_MULTIPLIER,
                    display_divisor=EX_GROUP_MULTIPLIER,
                    infer_zero_rebate=normal_should_infer,
                )
        except ValueError as e:
            print(f"  ⚠ {e}，跳过 group_id={group_id}")
            continue
        rows.extend(group_rows)
        mode_rows += len(group_rows)
        if independent_rtp:
            print(
                f"  group_id={group_info['group_id']} "
                f"目标RTP={format_weighted_rtp(get_group_target_rtp_ratio(group_info['group_id']))}，"
                f"ex反推目标={format_weighted_rtp(group_info['target_rtp'])}，"
                f"rebate=0 weight={group_info['zero_weight']}，"
                f"实际RTP={format_weighted_rtp(group_info['actual_rtp'])}，"
                f"最终RTP={format_weighted_rtp(group_info['display_rtp'])}"
            )
        else:
            print(
                f"  group_id={group_info['group_id']} "
                f"目标总RTP={format_weighted_rtp(get_group_target_rtp_ratio(group_info['group_id']))}，"
                f"ex反推总目标={format_weighted_rtp(get_group_target_rtp_ratio(group_info['group_id']) * EX_GROUP_MULTIPLIER)}，"
                f"ex免费触发={group_info['free_rate']:.4f}，ex特殊触发={group_info['special_rate']:.4f}，"
                f"ex普通目标RTP={format_weighted_rtp(group_info['normal_target_rtp'])}，"
                f"rebate=0 weight={group_info['zero_weight']}，"
                f"实际RTP={format_weighted_rtp(group_info['actual_normal_rtp'])}，"
                f"最终RTP={format_weighted_rtp(group_info['display_rtp'])}"
            )
    print(f"  {mode_name}准备写入 {mode_rows} 行")


def append_ex_buy_group_weight_mode(rows, formation_exists, rebates_by_mode, mode_exists, mode_pairs):
    """写入 ex购买局。"""
    game_type = EX_PURCHASE_MODE
    if not EX_BUY_GROUP_ENABLED or not formation_exists.get(game_type, False):
        return
    mode_name = GAME_TYPE_NAMES[game_type]
    if should_skip_group_weight_mode_data(game_type, mode_exists, rebates_by_mode):
        return

    combined_multiplier = BUY_GROUP_MULTIPLIER * EX_GROUP_MULTIPLIER
    should_infer = should_infer_zero_rebate(
        game_type,
        rebates_by_mode[game_type],
        globals().get('ZERO_REBATE_INFERENCE_MODES', set()),
    )
    if should_infer:
        mode_rows, _infos = group_weight_row_helpers.append_targeted_buy_like_group_weight_rows(
            rows,
            get_group_weight_write_game_type(game_type),
            mode_pairs[game_type],
            combined_multiplier,
        )
        print(
            f"\n[{mode_name}] rebate=0 反推开启，game_type={get_group_weight_write_game_type(game_type)}，"
            f"购买倍数={format_weighted_rtp(BUY_GROUP_MULTIPLIER)}，"
            f"ex倍数={format_weighted_rtp(EX_GROUP_MULTIPLIER)}，"
            f"实际倍数={format_weighted_rtp(combined_multiplier)}，准备写入 {mode_rows} 行"
        )
    else:
        mode_rows, game_rtp, display_rtp = group_weight_row_helpers.append_buy_like_group_weight_rows(
            rows,
            get_group_weight_write_game_type(game_type),
            mode_pairs[game_type],
            combined_multiplier,
        )
        print(
            f"\n[{mode_name}] RTP={format_weighted_rtp(game_rtp)}，game_type={get_group_weight_write_game_type(game_type)}，"
            f"购买倍数={format_weighted_rtp(BUY_GROUP_MULTIPLIER)}，"
            f"ex倍数={format_weighted_rtp(EX_GROUP_MULTIPLIER)}，"
            f"实际倍数={format_weighted_rtp(combined_multiplier)}，"
            f"显示RTP={format_weighted_rtp(display_rtp)}，准备写入 {mode_rows} 行"
        )


def append_ex_group_weight_modes(rows, formation_exists, rebates_by_mode, mode_exists, mode_pairs):
    """写入 ex特殊/ex免费/ex普通/ex购买局。"""
    ex_info_by_mode = append_ex_independent_group_weight_modes(
        rows,
        formation_exists,
        rebates_by_mode,
        mode_exists,
        mode_pairs,
    )
    append_ex_free_group_weight_mode(
        rows,
        formation_exists,
        rebates_by_mode,
        mode_exists,
        mode_pairs,
        ex_info_by_mode,
    )
    append_ex_normal_group_weight_mode(
        rows,
        formation_exists,
        rebates_by_mode,
        mode_exists,
        mode_pairs,
        ex_info_by_mode,
    )
    append_ex_buy_group_weight_mode(
        rows,
        formation_exists,
        rebates_by_mode,
        mode_exists,
        mode_pairs,
    )
