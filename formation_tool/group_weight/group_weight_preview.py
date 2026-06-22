"""group_weight preview text calculation."""

from formation_tool.group_weight.group_weight_logic import (
    build_independent_group_weight_rows_for_group,
    build_rebate_weight_pairs,
    build_special_group_weight_rows_for_group,
    calculate_weighted_rtp,
    format_weighted_rtp,
    get_ex_display_target_rtp,
    infer_special_zero_weight,
    should_infer_zero_rebate,
)
from formation_tool.core import runtime_context_sync


def configure(**values):
    """Inject runtime context shared with group_weight_builder."""
    runtime_context_sync.configure_module_globals(globals(), values)


def count_preview_write_rows(group_rows, skipped_zero, skipped_rebate_zero):
    row_count = len(group_rows) + int(skipped_zero)
    if skipped_rebate_zero > 0 and not any(int(row[2]) == 0 for row in group_rows):
        row_count += 1
    return row_count


def collect_group_weight_preview_warnings(displayed_modes, preview_rebates, preview_status):
    """返回 group_weight 弹窗中需要提示的缺表/空表信息，并按源采样表去重。"""
    warnings = []
    seen_sources = set()
    for mode in displayed_modes:
        if mode == BUY_GROUP_MODE and not BUY_GROUP_ENABLED:
            continue
        source_mode = get_group_weight_rebate_source_mode(mode)
        if source_mode in seen_sources:
            continue
        seen_sources.add(source_mode)
        if preview_rebates.get(source_mode):
            continue
        warnings.append(
            preview_status.get(
                source_mode,
                f"{get_group_weight_mode_name(mode)}：未读取到状态",
            )
        )
    return warnings


def build_original_normal_group_weight_preview(
    group_id,
    sampled_rebates,
    current_rules,
    rules_by_mode,
    parse_errors,
    preview_rebates,
    formation_exists,
    *,
    special_has_zero_for_config=False,
    special_target_rtp=None,
    special_target_error=None,
    zero_rebate_inference_modes=None,
):
    """普通局预览：按免费/特殊触发贡献反推 rebate=0 权重。"""
    normal_should_infer = should_infer_zero_rebate(
        '1',
        sampled_rebates,
        zero_rebate_inference_modes,
    )
    normal_pairs, skipped_zero, skipped_rebate_zero = build_rebate_weight_pairs(
        sampled_rebates,
        current_rules,
        exclude_rebate_zero=normal_should_infer,
    )
    if parse_errors.get('2') or parse_errors.get('3'):
        return f"特殊局/免费局配置错误: {parse_errors.get('2') or parse_errors.get('3')}"

    special_should_infer = should_infer_zero_rebate(
        '2',
        preview_rebates.get('2', []),
        zero_rebate_inference_modes,
    )
    special_pairs, _, _ = build_rebate_weight_pairs(
        preview_rebates.get('2', []),
        rules_by_mode.get('2', []),
        exclude_rebate_zero=special_should_infer,
    )
    free_pairs, _, _ = build_rebate_weight_pairs(
        preview_rebates.get('3', []),
        rules_by_mode.get('3', []),
    )
    special_enabled = formation_exists.get('2', False) and bool(special_pairs)
    free_enabled = formation_exists.get('3', False) and bool(free_pairs)
    if special_should_infer and special_target_error:
        return special_target_error
    try:
        _special_zero, special_actual_rtp = infer_special_zero_weight(
            special_pairs,
            special_should_infer,
            special_target_rtp,
        )
        special_rtp = special_actual_rtp or 0
        free_rtp = calculate_weighted_rtp(free_pairs) or 0
        group_rows, group_info = build_normal_group_weight_rows_for_group(
            group_id,
            normal_pairs,
            free_rtp,
            free_enabled,
            special_rtp,
            special_enabled,
            infer_zero_rebate=normal_should_infer,
        )
    except ValueError as e:
        return str(e)
    row_count = count_preview_write_rows(group_rows, skipped_zero, skipped_rebate_zero)
    return (
        f"普通目标={format_weighted_rtp(group_info['normal_target_rtp'])}，"
        f"反推0权重={group_info['zero_weight']}，"
        f"实际={format_weighted_rtp(group_info['actual_normal_rtp'])}，"
        f"将写入 {row_count} 行"
        f"（非0参与 {len(normal_pairs)} 个，跳过0权重 {skipped_zero} 个"
        f"，采样表0 {skipped_rebate_zero} 个）"
    )


def build_ex_normal_group_weight_preview(
    group_id,
    sampled_rebates,
    current_rules,
    rules_by_mode,
    parse_errors,
    preview_rebates,
    formation_exists,
    ex_multiplier,
    ex_target_rtps=None,
    zero_rebate_inference_modes=None,
):
    """ex普通局预览：ex特殊独立反推，ex免费静态计算，再反推 ex普通。"""
    normal_should_infer = should_infer_zero_rebate(
        '6',
        sampled_rebates,
        zero_rebate_inference_modes,
    )
    normal_pairs, skipped_zero, skipped_rebate_zero = build_rebate_weight_pairs(
        sampled_rebates,
        current_rules,
        exclude_rebate_zero=normal_should_infer,
    )
    if parse_errors.get('7') or parse_errors.get('8'):
        return f"ex特殊局/ex免费局配置错误: {parse_errors.get('7') or parse_errors.get('8')}"

    ex_special_should_infer = should_infer_zero_rebate(
        '7',
        preview_rebates.get('7', []),
        zero_rebate_inference_modes,
    )
    ex_special_pairs, _, special_zero_count = build_rebate_weight_pairs(
        preview_rebates.get('7', []),
        rules_by_mode.get('7', []),
        exclude_rebate_zero=ex_special_should_infer,
    )
    ex_free_pairs, _, _free_zero_count = build_rebate_weight_pairs(
        preview_rebates.get('8', []),
        rules_by_mode.get('8', []),
        exclude_rebate_zero=False,
    )
    ex_special_enabled = formation_exists.get('7', False) and bool(ex_special_pairs)
    ex_free_enabled = formation_exists.get('8', False) and bool(ex_free_pairs)
    special_display_target = get_ex_display_target_rtp(
        group_id,
        7,
        ex_target_rtps,
        target_rtp_getter=get_group_target_rtp_ratio,
    )
    _special_rows, special_info = build_independent_group_weight_rows_for_group(
        group_id,
        7,
        ex_special_pairs,
        ex_special_should_infer,
        special_display_target * ex_multiplier,
        display_divisor=ex_multiplier,
    )
    ex_free_rtp = calculate_weighted_rtp(ex_free_pairs) or 0
    try:
        group_rows, group_info = build_normal_group_weight_rows_for_group(
            group_id,
            normal_pairs,
            ex_free_rtp,
            ex_free_enabled,
            special_info['actual_rtp'] or 0,
            ex_special_enabled,
            game_type=6,
            target_multiplier=ex_multiplier,
            display_divisor=ex_multiplier,
            infer_zero_rebate=normal_should_infer,
        )
    except ValueError as e:
        return str(e)
    row_count = count_preview_write_rows(group_rows, skipped_zero, skipped_rebate_zero)
    return (
        f"ex普通目标={format_weighted_rtp(group_info['normal_target_rtp'])}，"
        f"ex倍数={format_weighted_rtp(ex_multiplier)}，"
        f"反推0权重={group_info['zero_weight']}，"
        f"实际={format_weighted_rtp(group_info['actual_normal_rtp'])}，"
        f"最终RTP={format_weighted_rtp(group_info['display_rtp'])}，"
        f"将写入 {row_count} 行"
        f"（非0参与 {len(normal_pairs)} 个，跳过0权重 {skipped_zero} 个"
        f"，采样表0 {skipped_rebate_zero} 个）"
    )


def build_special_group_weight_preview(
    group_id,
    sampled_rebates,
    rtp_pairs,
    skipped_zero,
    skipped_rebate_zero,
    *,
    special_target_rtp=None,
    special_target_error=None,
    should_infer_zero=False,
):
    """特殊局预览：存在 rebate=0 时按手填目标 RTP 反推0权重。"""
    if should_infer_zero and special_target_error:
        return special_target_error
    zero_weight, current_rtp = infer_special_zero_weight(
        rtp_pairs,
        should_infer_zero,
        special_target_rtp if should_infer_zero else None,
    )
    row_count = count_preview_write_rows(
        build_special_group_weight_rows_for_group(
            group_id,
            rtp_pairs,
            zero_weight,
        ),
        skipped_zero,
        skipped_rebate_zero,
    )
    return (
        f"{format_weighted_rtp(current_rtp)}，反推0权重={zero_weight}，将写入 {row_count} 行"
        f"（已选rebate {len(sampled_rebates)} 个，非0参与 {len(rtp_pairs)} 个，"
        f"跳过0权重 {skipped_zero} 个，采样表0 {skipped_rebate_zero} 个）"
    )


def build_ex_independent_group_weight_preview(
    current_mode,
    group_id,
    sampled_rebates,
    rtp_pairs,
    skipped_zero,
    skipped_rebate_zero,
    ex_multiplier,
    ex_target_rtps=None,
    should_infer_zero=False,
):
    """独立 ex 模式预览：每个 group_id 独立按目标 RTP * ex倍数反推。"""
    display_target = get_ex_display_target_rtp(
        group_id,
        current_mode,
        ex_target_rtps,
        target_rtp_getter=get_group_target_rtp_ratio,
    )
    target_rtp = display_target * ex_multiplier
    group_rows, ex_info = build_independent_group_weight_rows_for_group(
        group_id,
        int(current_mode),
        rtp_pairs,
        should_infer_zero,
        target_rtp,
        display_divisor=ex_multiplier,
    )
    row_count = count_preview_write_rows(group_rows, skipped_zero, skipped_rebate_zero)
    return (
        f"目标={format_weighted_rtp(display_target)}，"
        f"反推目标={format_weighted_rtp(target_rtp)}，"
        f"ex倍数={format_weighted_rtp(ex_multiplier)}，"
        f"反推0权重={ex_info['zero_weight']}，"
        f"实际={format_weighted_rtp(ex_info['actual_rtp'])}，"
        f"最终RTP={format_weighted_rtp(ex_info['display_rtp'])}，"
        f"将写入 {row_count} 行"
        f"（已选rebate {len(sampled_rebates)} 个，非0参与 {len(rtp_pairs)} 个，"
        f"跳过0权重 {skipped_zero} 个，采样表0 {skipped_rebate_zero} 个）"
    )


def build_buy_group_weight_preview(
    current_mode,
    group_id,
    sampled_rebates,
    rtp_pairs,
    skipped_zero,
    skipped_rebate_zero,
    buy_multiplier,
    ex_multiplier,
    should_infer_zero=False,
):
    """购买局类预览：按购买倍数折算显示 RTP。"""
    current_rtp = calculate_weighted_rtp(rtp_pairs)
    if current_mode == BUY_GROUP_MODE:
        write_game_type = get_group_weight_write_game_type(current_mode)
        multiplier = float(buy_multiplier)
        if should_infer_zero:
            target_rtp = get_group_target_rtp_ratio(group_id) * multiplier
            group_rows, group_info = build_independent_group_weight_rows_for_group(
                group_id,
                write_game_type,
                rtp_pairs,
                True,
                target_rtp,
                display_divisor=multiplier,
            )
            row_count = count_preview_write_rows(group_rows, skipped_zero, skipped_rebate_zero)
            return (
                f"目标={format_weighted_rtp(get_group_target_rtp_ratio(group_id))}，"
                f"反推目标={format_weighted_rtp(target_rtp)}，game_type={write_game_type}，"
                f"购买倍数={format_weighted_rtp(multiplier)}，"
                f"反推0权重={group_info['zero_weight']}，"
                f"实际={format_weighted_rtp(group_info['actual_rtp'])}，"
                f"显示RTP={format_weighted_rtp(group_info['display_rtp'])}，"
                f"将写入 {row_count} 行"
                f"（已选rebate {len(sampled_rebates)} 个，非0参与 {len(rtp_pairs)} 个，"
                f"跳过0权重 {skipped_zero} 个，采样表0 {skipped_rebate_zero} 个）"
            )
        display_rtp = None if current_rtp is None else current_rtp / buy_multiplier
        return (
            f"{format_weighted_rtp(current_rtp)}，game_type={write_game_type}，"
            f"购买倍数={format_weighted_rtp(buy_multiplier)}，"
            f"显示RTP={format_weighted_rtp(display_rtp)}"
            f"（已选rebate {len(sampled_rebates)} 个，参与 {len(rtp_pairs)} 个，"
            f"跳过0权重 {skipped_zero} 个）"
        )
    if current_mode == EX_PURCHASE_MODE:
        write_game_type = get_group_weight_write_game_type(current_mode)
        combined_multiplier = float(buy_multiplier) * float(ex_multiplier)
        if should_infer_zero:
            target_rtp = get_group_target_rtp_ratio(group_id) * combined_multiplier
            group_rows, group_info = build_independent_group_weight_rows_for_group(
                group_id,
                write_game_type,
                rtp_pairs,
                True,
                target_rtp,
                display_divisor=combined_multiplier,
            )
            row_count = count_preview_write_rows(group_rows, skipped_zero, skipped_rebate_zero)
            return (
                f"目标={format_weighted_rtp(get_group_target_rtp_ratio(group_id))}，"
                f"反推目标={format_weighted_rtp(target_rtp)}，game_type={write_game_type}，"
                f"购买倍数={format_weighted_rtp(buy_multiplier)}，"
                f"ex倍数={format_weighted_rtp(ex_multiplier)}，"
                f"实际倍数={format_weighted_rtp(combined_multiplier)}，"
                f"反推0权重={group_info['zero_weight']}，"
                f"实际={format_weighted_rtp(group_info['actual_rtp'])}，"
                f"显示RTP={format_weighted_rtp(group_info['display_rtp'])}，"
                f"将写入 {row_count} 行"
                f"（已选rebate {len(sampled_rebates)} 个，非0参与 {len(rtp_pairs)} 个，"
                f"跳过0权重 {skipped_zero} 个，采样表0 {skipped_rebate_zero} 个）"
            )
        display_rtp = None if current_rtp is None else current_rtp / combined_multiplier
        return (
            f"{format_weighted_rtp(current_rtp)}，game_type={write_game_type}，"
            f"购买倍数={format_weighted_rtp(buy_multiplier)}，"
            f"ex倍数={format_weighted_rtp(ex_multiplier)}，"
            f"实际倍数={format_weighted_rtp(combined_multiplier)}，"
            f"显示RTP={format_weighted_rtp(display_rtp)}"
            f"（已选rebate {len(sampled_rebates)} 个，参与 {len(rtp_pairs)} 个，"
            f"跳过0权重 {skipped_zero} 个）"
        )
    if is_extra_buy_mode(current_mode):
        extra_group = get_extra_buy_group_by_mode(current_mode) or {}
        write_game_type = get_extra_buy_game_type(current_mode)
        multiplier = float(extra_group.get('multiplier', buy_multiplier))
        if should_infer_zero:
            target_rtp = get_group_target_rtp_ratio(group_id) * multiplier
            group_rows, group_info = build_independent_group_weight_rows_for_group(
                group_id,
                write_game_type,
                rtp_pairs,
                True,
                target_rtp,
                display_divisor=multiplier,
            )
            row_count = count_preview_write_rows(group_rows, skipped_zero, skipped_rebate_zero)
            return (
                f"目标={format_weighted_rtp(get_group_target_rtp_ratio(group_id))}，"
                f"反推目标={format_weighted_rtp(target_rtp)}，game_type={write_game_type}，"
                f"购买倍数={format_weighted_rtp(multiplier)}，"
                f"反推0权重={group_info['zero_weight']}，"
                f"实际={format_weighted_rtp(group_info['actual_rtp'])}，"
                f"显示RTP={format_weighted_rtp(group_info['display_rtp'])}，"
                f"将写入 {row_count} 行"
                f"（已选rebate {len(sampled_rebates)} 个，非0参与 {len(rtp_pairs)} 个，"
                f"跳过0权重 {skipped_zero} 个，采样表0 {skipped_rebate_zero} 个）"
            )
        display_rtp = None if current_rtp is None else current_rtp / multiplier
        return (
            f"{format_weighted_rtp(current_rtp)}，game_type={write_game_type}，"
            f"购买倍数={format_weighted_rtp(multiplier)}，"
            f"显示RTP={format_weighted_rtp(display_rtp)}"
            f"（已选rebate {len(sampled_rebates)} 个，参与 {len(rtp_pairs)} 个，"
            f"跳过0权重 {skipped_zero} 个）"
        )
    return None


def build_static_group_weight_preview(sampled_rebates, rtp_pairs, skipped_zero):
    """普通静态权重页签预览。"""
    current_rtp = calculate_weighted_rtp(rtp_pairs)
    return (
        f"{format_weighted_rtp(current_rtp)}"
        f"（已选rebate {len(sampled_rebates)} 个，参与 {len(rtp_pairs)} 个，"
        f"跳过0权重 {skipped_zero} 个）"
    )


def build_ex_static_group_weight_preview(sampled_rebates, rtp_pairs, skipped_zero, ex_multiplier):
    """ex静态权重页签预览：显示配置 RTP 和按 ex 倍数折算后的最终 RTP。"""
    current_rtp = calculate_weighted_rtp(rtp_pairs)
    display_rtp = None if current_rtp is None else current_rtp / float(ex_multiplier)
    return (
        f"{format_weighted_rtp(current_rtp)}，"
        f"ex倍数={format_weighted_rtp(ex_multiplier)}，"
        f"最终RTP={format_weighted_rtp(display_rtp)}"
        f"（已选rebate {len(sampled_rebates)} 个，参与 {len(rtp_pairs)} 个，"
        f"跳过0权重 {skipped_zero} 个）"
    )


def get_group_weight_preview_source_mode(current_mode):
    """返回预览读取已采样 rebate 时使用的源模式。"""
    return get_group_weight_rebate_source_mode(current_mode)


def build_group_weight_preview_context(
    current_mode,
    group_id,
    rules_by_mode,
    parse_errors,
    preview_rebates,
    preview_status,
    formation_exists,
    *,
    special_has_zero_for_config=False,
    special_target_rtp=None,
    special_target_error=None,
    buy_multiplier=1,
    ex_multiplier=1,
    ex_target_rtps=None,
    zero_rebate_inference_modes=None,
    buy_enabled=True,
):
    """组装 group_weight 预览所需上下文；message 表示可直接返回的提示文案。"""
    if current_mode == BUY_GROUP_MODE and not buy_enabled:
        return {'message': "购买局未启用，确认后不会写入购买局数据"}
    if parse_errors.get(current_mode):
        return {'message': parse_errors[current_mode]}

    source_mode = get_group_weight_preview_source_mode(current_mode)
    sampled_rebates = preview_rebates.get(source_mode, [])
    if not sampled_rebates:
        return {'message': preview_status.get(source_mode, "未读取到已选 rebate")}

    return {
        'message': None,
        'current_mode': current_mode,
        'group_id': group_id,
        'role': get_group_weight_rtp_role(current_mode),
        'sampled_rebates': sampled_rebates,
        'current_rules': rules_by_mode.get(current_mode, []),
        'rules_by_mode': rules_by_mode,
        'parse_errors': parse_errors,
        'preview_rebates': preview_rebates,
        'formation_exists': formation_exists,
        'special_has_zero_for_config': special_has_zero_for_config,
        'special_target_rtp': special_target_rtp,
        'special_target_error': special_target_error,
        'buy_multiplier': buy_multiplier,
        'ex_multiplier': ex_multiplier,
        'ex_target_rtps': dict(ex_target_rtps or {}),
        'zero_rebate_inference_modes': set(
            globals().get('ZERO_REBATE_INFERENCE_MODES', set())
            if zero_rebate_inference_modes is None
            else zero_rebate_inference_modes
        ),
    }


def build_group_weight_preview_pair_context(context):
    """为普通非复合预览模式生成 rebate/weight pair 信息。"""
    should_infer_zero = should_infer_zero_rebate(
        context['current_mode'],
        context['sampled_rebates'],
        context['zero_rebate_inference_modes'],
    )
    rtp_pairs, skipped_zero, skipped_rebate_zero = build_rebate_weight_pairs(
        context['sampled_rebates'],
        context['current_rules'],
        exclude_rebate_zero=should_infer_zero,
    )
    enriched = dict(context)
    enriched.update({
        'rtp_pairs': rtp_pairs,
        'skipped_zero': skipped_zero,
        'skipped_rebate_zero': skipped_rebate_zero,
        'should_infer_zero': should_infer_zero,
    })
    return enriched


def build_normal_preview_from_context(context):
    return build_original_normal_group_weight_preview(
        context['group_id'],
        context['sampled_rebates'],
        context['current_rules'],
        context['rules_by_mode'],
        context['parse_errors'],
        context['preview_rebates'],
        context['formation_exists'],
        special_has_zero_for_config=context['special_has_zero_for_config'],
        special_target_rtp=context['special_target_rtp'],
        special_target_error=context['special_target_error'],
        zero_rebate_inference_modes=context['zero_rebate_inference_modes'],
    )


def build_ex_normal_preview_from_context(context):
    return build_ex_normal_group_weight_preview(
        context['group_id'],
        context['sampled_rebates'],
        context['current_rules'],
        context['rules_by_mode'],
        context['parse_errors'],
        context['preview_rebates'],
        context['formation_exists'],
        context['ex_multiplier'],
        context['ex_target_rtps'],
        context['zero_rebate_inference_modes'],
    )


def build_special_preview_from_context(context):
    return build_special_group_weight_preview(
        context['group_id'],
        context['sampled_rebates'],
        context['rtp_pairs'],
        context['skipped_zero'],
        context['skipped_rebate_zero'],
        special_target_rtp=context['special_target_rtp'],
        special_target_error=context['special_target_error'],
        should_infer_zero=context['should_infer_zero'],
    )


def build_ex_independent_preview_from_context(context):
    return build_ex_independent_group_weight_preview(
        context['current_mode'],
        context['group_id'],
        context['sampled_rebates'],
        context['rtp_pairs'],
        context['skipped_zero'],
        context['skipped_rebate_zero'],
        context['ex_multiplier'],
        context['ex_target_rtps'],
        context['should_infer_zero'],
    )


def build_buy_preview_from_context(context):
    return build_buy_group_weight_preview(
        context['current_mode'],
        context['group_id'],
        context['sampled_rebates'],
        context['rtp_pairs'],
        context['skipped_zero'],
        context['skipped_rebate_zero'],
        context['buy_multiplier'],
        context['ex_multiplier'],
        context['should_infer_zero'],
    )


def build_static_preview_from_context(context):
    if context['current_mode'] in EX_GROUP_MODES:
        return build_ex_static_group_weight_preview(
            context['sampled_rebates'],
            context['rtp_pairs'],
            context['skipped_zero'],
            context['ex_multiplier'],
        )
    return build_static_group_weight_preview(
        context['sampled_rebates'],
        context['rtp_pairs'],
        context['skipped_zero'],
    )


def build_group_weight_preview_by_role(context):
    """按 rtp_role 分发当前页签的预览计算。"""
    role = context['role']
    if role == 'normal':
        return build_normal_preview_from_context(context)
    if role == 'ex_normal':
        return build_ex_normal_preview_from_context(context)

    pair_context = build_group_weight_preview_pair_context(context)
    if role == 'special':
        return build_special_preview_from_context(pair_context)
    if role == 'ex_independent':
        return build_ex_independent_preview_from_context(pair_context)
    if role in ('buy', 'ex_buy'):
        return build_buy_preview_from_context(pair_context)
    return build_static_preview_from_context(pair_context)


def build_group_weight_preview_text(
    current_mode,
    group_id,
    rules_by_mode,
    parse_errors,
    preview_rebates,
    preview_status,
    formation_exists,
    *,
    special_has_zero_for_config=False,
    special_target_rtp=None,
    special_target_error=None,
    buy_multiplier=1,
    ex_multiplier=1,
    ex_target_rtps=None,
    zero_rebate_inference_modes=None,
    buy_enabled=True,
):
    """计算 group_weight 弹窗当前页的 RTP 预览文案。"""
    context = build_group_weight_preview_context(
        current_mode,
        group_id,
        rules_by_mode,
        parse_errors,
        preview_rebates,
        preview_status,
        formation_exists,
        special_has_zero_for_config=special_has_zero_for_config,
        special_target_rtp=special_target_rtp,
        special_target_error=special_target_error,
        buy_multiplier=buy_multiplier,
        ex_multiplier=ex_multiplier,
        ex_target_rtps=ex_target_rtps,
        zero_rebate_inference_modes=zero_rebate_inference_modes,
        buy_enabled=buy_enabled,
    )
    if context['message']:
        return context['message']
    return build_group_weight_preview_by_role(context)
