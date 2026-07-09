"""Original 1/2/3 mode group_weight generation."""

from formation_tool.group_weight.group_weight_logic import (
    build_independent_group_weight_rows_for_group,
    build_normal_group_weight_rows_for_group,
    calculate_weighted_rtp,
    format_weighted_rtp,
    infer_special_zero_weight,
    should_infer_zero_rebate,
)
from formation_tool.group_weight import group_weight_row_helpers
from formation_tool.core import runtime_context_sync
from formation_tool.utils import log_utils

print = log_utils.emit


def configure(**values):
    runtime_context_sync.configure_module_globals(globals(), values)


def prepare_original_trigger_rtp_context(rebates_by_mode, mode_exists, mode_pairs):
    """准备原模式普通局反推需要的特殊/免费局 RTP 和触发状态。"""
    special_has_zero = group_weight_row_helpers.has_rebate_zero(rebates_by_mode['2'])
    special_should_infer = should_infer_zero_rebate(
        '2',
        rebates_by_mode['2'],
        globals().get('ZERO_REBATE_INFERENCE_MODES', set()),
    )
    special_enabled = mode_exists['2'] and bool(mode_pairs['2'])
    free_enabled = mode_exists['3'] and bool(mode_pairs['3'])
    special_zero_weight, special_actual_rtp = infer_special_zero_weight(
        mode_pairs['2'],
        special_should_infer,
        SPECIAL_GROUP_TARGET_RTP,
    )
    special_rtp = special_actual_rtp or 0
    free_rtp = calculate_weighted_rtp(mode_pairs['3']) or 0
    return {
        'special_enabled': special_enabled,
        'free_enabled': free_enabled,
        'special_has_zero': special_has_zero,
        'special_should_infer': special_should_infer,
        'special_zero_weight': special_zero_weight,
        'special_rtp': special_rtp,
        'free_rtp': free_rtp,
    }


def log_original_trigger_rtp_context(context):
    """输出原模式特殊/免费局 RTP 摘要。"""
    print(
        f"\n特殊局RTP={format_weighted_rtp(context['special_rtp'])}，"
        f"rebate=0 {'存在' if context['special_has_zero'] else '不存在'}，"
        f"反推{'开启' if context['special_should_infer'] else '关闭'}，"
        f"反推0权重={context['special_zero_weight']}，"
        f"触发配置{'有效' if context['special_enabled'] else '无效/不存在'}"
    )
    print(
        f"免费局RTP={format_weighted_rtp(context['free_rtp'])}，触发配置"
        f"{'有效' if context['free_enabled'] else '无效/不存在'}"
    )


def append_original_normal_group_weight_rows(rows, rebates_by_mode, mode_exists, mode_pairs, trigger_context):
    """写入原普通局，按目标 RTP 反推 rebate=0 权重。"""
    game_type = '1'
    if not mode_exists[game_type]:
        print("\n[普通局] 没有对应采样配置表，跳过普通局 group_weight")
        return 0
    if not rebates_by_mode[game_type]:
        print("\n[普通局] 采样配置表没有数据，跳过普通局 group_weight")
        return 0

    normal_should_infer = should_infer_zero_rebate(
        game_type,
        rebates_by_mode[game_type],
        globals().get('ZERO_REBATE_INFERENCE_MODES', set()),
    )
    print(f"[普通局] rebate=0 反推：{'开启' if normal_should_infer else '关闭'}")
    independent_rtp = game_type in {str(mode) for mode in globals().get('INDEPENDENT_RTP_MODES', set())}
    if independent_rtp:
        print("[普通局] 独立计算RTP：开启，RTP目标=当前组，不扣除特殊局/免费局触发贡献")
    normal_rows = 0
    for group_id in WEIGHT_GROUP_IDS:
        check_cancelled()
        try:
            if independent_rtp:
                group_rows, group_info = build_independent_group_weight_rows_for_group(
                    group_id,
                    get_group_weight_write_game_type(game_type),
                    mode_pairs[game_type],
                    normal_should_infer,
                    get_group_target_rtp_ratio(group_id),
                )
            else:
                group_rows, group_info = build_normal_group_weight_rows_for_group(
                    group_id,
                    mode_pairs[game_type],
                    trigger_context['free_rtp'],
                    trigger_context['free_enabled'],
                    trigger_context['special_rtp'],
                    trigger_context['special_enabled'],
                    infer_zero_rebate=normal_should_infer,
                )
        except ValueError as e:
            print(f"  ⚠ {e}，跳过 group_id={group_id}")
            continue

        rows.extend(group_rows)
        normal_rows += len(group_rows)
        if independent_rtp:
            print(
                f"  group_id={group_info['group_id']} "
                f"目标RTP={format_weighted_rtp(group_info['target_rtp'])}，"
                f"rebate=0 weight={group_info['zero_weight']}，"
                f"普通实际RTP={format_weighted_rtp(group_info['actual_rtp'])}"
            )
        else:
            print(
                f"  group_id={group_info['group_id']} "
                f"目标总RTP={format_weighted_rtp(get_group_target_rtp_ratio(group_info['group_id']))}，"
                f"免费触发={group_info['free_rate']:.4f}，特殊触发={group_info['special_rate']:.4f}，"
                f"普通目标RTP={format_weighted_rtp(group_info['normal_target_rtp'])}，"
                f"rebate=0 weight={group_info['zero_weight']}，"
                f"普通实际RTP={format_weighted_rtp(group_info['actual_normal_rtp'])}"
            )
    print(f"  普通局准备写入 {normal_rows} 行")
    return normal_rows


def should_skip_original_static_mode(game_type, rebates_by_mode, mode_exists):
    """检查原特殊/免费局是否缺少可写入数据。"""
    mode_name = GAME_TYPE_NAMES[game_type]
    if not mode_exists[game_type]:
        print(f"\n[{mode_name}] 没有对应采样配置表，跳过")
        return True
    if not rebates_by_mode[game_type]:
        print(f"\n[{mode_name}] 采样配置表没有数据，跳过")
        return True
    return False


def append_original_special_group_weight_rows(rows, rebates_by_mode, mode_exists, mode_pairs, trigger_context):
    """写入原特殊局 group_weight。"""
    game_type = '2'
    if should_skip_original_static_mode(game_type, rebates_by_mode, mode_exists):
        return 0
    mode_rows = group_weight_row_helpers.append_special_group_weight_rows(
        rows,
        get_group_weight_write_game_type(game_type),
        mode_pairs[game_type],
        trigger_context['special_zero_weight'],
    )
    print(
        f"\n[{GAME_TYPE_NAMES[game_type]}] RTP={format_weighted_rtp(trigger_context['special_rtp'])}，"
        f"准备写入 {mode_rows} 行"
    )
    return mode_rows


def append_original_free_group_weight_rows(rows, rebates_by_mode, mode_exists, mode_pairs, trigger_context):
    """写入原免费局 group_weight。"""
    game_type = '3'
    if should_skip_original_static_mode(game_type, rebates_by_mode, mode_exists):
        return 0
    mode_rows = group_weight_row_helpers.append_static_group_weight_rows(
        rows,
        get_group_weight_write_game_type(game_type),
        mode_pairs[game_type],
    )
    print(
        f"\n[{GAME_TYPE_NAMES[game_type]}] RTP={format_weighted_rtp(trigger_context['free_rtp'])}，"
        f"准备写入 {mode_rows} 行"
    )
    return mode_rows


def append_original_group_weight_modes(rows, rebates_by_mode, mode_exists, mode_pairs):
    """写入原模式普通/特殊/免费局，返回 False 表示配置错误。"""
    try:
        trigger_context = prepare_original_trigger_rtp_context(
            rebates_by_mode,
            mode_exists,
            mode_pairs,
        )
    except ValueError as e:
        print(f"\n[特殊局] {e}")
        return False

    log_original_trigger_rtp_context(trigger_context)
    append_original_normal_group_weight_rows(
        rows,
        rebates_by_mode,
        mode_exists,
        mode_pairs,
        trigger_context,
    )
    append_original_special_group_weight_rows(
        rows,
        rebates_by_mode,
        mode_exists,
        mode_pairs,
        trigger_context,
    )
    append_original_free_group_weight_rows(
        rows,
        rebates_by_mode,
        mode_exists,
        mode_pairs,
        trigger_context,
    )
    return True
