"""Demo group_weight row generation."""

from formation_tool.group_weight.group_weight_logic import (
    build_independent_group_weight_rows_for_group,
    build_rebate_weight_pairs,
    build_zero_weight_rebate_pairs,
    calculate_weighted_rtp,
    format_weighted_rtp,
    has_rebate_zero,
    should_infer_zero_rebate,
    should_infer_zero_rebate_for_modes,
)


DEMO_GROUP_ID = 0


def _mode_key(mode):
    return str(mode)


def _rules_for_mode(mode, rules_by_mode, deps):
    mode = _mode_key(mode)
    if deps.is_extra_buy_mode(mode):
        return (
            (rules_by_mode or {}).get(mode)
            or (rules_by_mode or {}).get(deps.buy_group_mode)
            or deps.default_buy_group_weight_rules()
        )
    return (rules_by_mode or {}).get(mode, [])


def _target_for_mode(mode, target_rtps, deps):
    mode = _mode_key(mode)
    target_rtps = target_rtps or {}
    raw_value = target_rtps.get(mode)
    if raw_value is None and deps.is_extra_buy_mode(mode):
        raw_value = target_rtps.get(deps.buy_group_mode)
    if raw_value is None:
        raw_value = deps.default_demo_target_rtps().get(mode)
    if raw_value is None and deps.is_extra_buy_mode(mode):
        raw_value = deps.default_demo_target_rtps().get(deps.buy_group_mode)
    return None if raw_value is None else float(raw_value)


def _target_multiplier_for_mode(mode, deps):
    role = deps.get_group_weight_rtp_role(mode)
    if role == 'ex_buy':
        return float(deps.get_buy_group_multiplier_for_mode(mode)) * float(deps.get_ex_group_multiplier())
    if role == 'buy':
        return float(deps.get_buy_group_multiplier_for_mode(mode))
    if role in ('ex_normal', 'ex_independent'):
        return float(deps.get_ex_group_multiplier())
    return 1.0


def _should_infer_zero_rebate_for_mode(mode, rebates, zero_rebate_modes, deps):
    candidates = [mode]
    try:
        candidates.append(deps.get_group_weight_write_game_type(mode))
    except (AttributeError, KeyError, TypeError, ValueError):
        pass
    if should_infer_zero_rebate_for_modes(candidates, rebates, zero_rebate_modes):
        return True
    return should_infer_zero_rebate(mode, rebates, zero_rebate_modes)


def _preview_status_message(preview_status, mode):
    status = (preview_status or {}).get(mode, "")
    if isinstance(status, dict):
        if status and not status.get('exists', True):
            return status.get('message') or "sampling config table does not exist"
        return status.get('message') or ""
    return str(status or "")


def build_demo_group_weight_rows_for_mode(mode, rebates, rules, target_rtps, zero_rebate_modes, *, deps):
    """Build demo group_weight rows for one mode with group_id fixed to 0."""
    should_infer = _should_infer_zero_rebate_for_mode(mode, rebates, zero_rebate_modes, deps)
    pairs, skipped_zero, skipped_rebate_zero = build_rebate_weight_pairs(
        rebates,
        rules,
        exclude_rebate_zero=should_infer,
    )
    zero_pairs = build_zero_weight_rebate_pairs(rebates, rules)
    if should_infer:
        zero_pairs = [(rebate, weight) for rebate, weight in zero_pairs if int(rebate) != 0]

    write_game_type = deps.get_group_weight_write_game_type(mode)
    # A target RTP is only meaningful when rebate=0 is inferred.  Otherwise the
    # configured weights determine the actual RTP directly.
    target_rtp = _target_for_mode(mode, target_rtps, deps) if should_infer else None
    multiplier = _target_multiplier_for_mode(mode, deps)
    if should_infer and target_rtp is None:
        raise ValueError(f"{deps.get_group_weight_mode_name(mode)} rebate=0 inference needs demo target RTP")

    rows, info = build_independent_group_weight_rows_for_group(
        DEMO_GROUP_ID,
        write_game_type,
        pairs,
        should_infer,
        None if target_rtp is None else target_rtp * multiplier,
        display_divisor=multiplier,
    )
    rows.extend(
        (int(write_game_type), DEMO_GROUP_ID, int(rebate), int(weight))
        for rebate, weight in zero_pairs
    )
    info.update({
        'mode': _mode_key(mode),
        'write_game_type': int(write_game_type),
        'display_target_rtp': target_rtp,
        'multiplier': multiplier,
        'skipped_zero': skipped_zero,
        'skipped_rebate_zero': skipped_rebate_zero,
        'should_infer': should_infer,
        'has_zero': has_rebate_zero(rebates),
        'row_count': len(rows),
    })
    if not should_infer:
        info['actual_rtp'] = calculate_weighted_rtp(pairs)
        info['display_rtp'] = None if info['actual_rtp'] is None else info['actual_rtp'] / multiplier
    return rows, info


def build_demo_group_weight_rows(
    active_modes,
    rebates_by_mode,
    mode_exists,
    rules_by_mode,
    target_rtps,
    zero_rebate_modes,
    *,
    deps,
):
    rows = []
    infos = {}
    for mode in active_modes:
        mode = _mode_key(mode)
        if not mode_exists.get(mode, False) or not rebates_by_mode.get(mode):
            continue
        mode_rows, info = build_demo_group_weight_rows_for_mode(
            mode,
            rebates_by_mode.get(mode, []),
            _rules_for_mode(mode, rules_by_mode, deps),
            target_rtps,
            zero_rebate_modes,
            deps=deps,
        )
        rows.extend(mode_rows)
        infos[mode] = info
    return rows, infos


def build_demo_group_weight_preview_text(
    current_mode,
    _group_id,
    rules_by_mode,
    parse_errors,
    preview_rebates,
    preview_status,
    _formation_exists,
    *,
    target_rtps=None,
    zero_rebate_inference_modes=None,
    deps,
    **_kwargs,
):
    mode = _mode_key(current_mode)
    if parse_errors.get(mode):
        return parse_errors[mode]
    rebates = (preview_rebates or {}).get(mode, [])
    if not rebates:
        return _preview_status_message(preview_status, mode) or "sampling config is empty"
    rows, info = build_demo_group_weight_rows_for_mode(
        mode,
        rebates,
        _rules_for_mode(mode, rules_by_mode, deps),
        target_rtps,
        zero_rebate_inference_modes or set(),
        deps=deps,
    )
    parts = [
        "group_id=0",
        f"game_type={info['write_game_type']}",
        f"rows={len(rows)}",
    ]
    if info.get('display_target_rtp') is not None:
        parts.append(f"targetRTP={format_weighted_rtp(info['display_target_rtp'])}")
    if info.get('display_rtp') is not None:
        parts.append(f"实际RTP={format_weighted_rtp(info['display_rtp'])}")
    if info.get('should_infer'):
        parts.append(f"rebate0_weight={info.get('zero_weight', 0)}")
    return ", ".join(parts)


def build_demo_group_weight_preview_points(
    current_mode,
    _group_id,
    rules_by_mode,
    parse_errors,
    preview_rebates,
    _preview_status,
    _formation_exists,
    *,
    target_rtps=None,
    zero_rebate_inference_modes=None,
    deps,
    **_kwargs,
):
    mode = _mode_key(current_mode)
    if parse_errors.get(mode):
        return []
    rebates = (preview_rebates or {}).get(mode, [])
    if not rebates:
        return []
    rows, _info = build_demo_group_weight_rows_for_mode(
        mode,
        rebates,
        _rules_for_mode(mode, rules_by_mode, deps),
        target_rtps,
        zero_rebate_inference_modes or set(),
        deps=deps,
    )
    return [(int(rebate), int(weight)) for _game_type, _group_id, rebate, weight in rows]
