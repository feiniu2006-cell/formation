"""Pure group_weight RTP and row-building logic."""

import math


def get_group_weight_for_rebate(rebate, rules):
    """Return the configured weight for one rebate value."""
    weight = 0
    for rule in sorted(rules, key=lambda item: item['rebate_min']):
        if rebate < rule['rebate_min']:
            break
        weight = rule['weight']
    return weight


def calculate_weighted_rtp(rebate_weight_pairs):
    """Calculate sum((rebate / 1000) * weight / total_weight)."""
    total_weight = 0
    weighted_sum = 0
    for rebate, weight in rebate_weight_pairs:
        weight = int(weight)
        if weight <= 0:
            continue
        total_weight += weight
        weighted_sum += (int(rebate) / 1000) * weight
    if total_weight <= 0:
        return None
    return weighted_sum / total_weight


def calculate_weighted_sum_and_total(rebate_weight_pairs):
    total_weight = 0
    weighted_sum = 0
    for rebate, weight in rebate_weight_pairs:
        weight = int(weight)
        if weight <= 0:
            continue
        total_weight += weight
        weighted_sum += (int(rebate) / 1000) * weight
    return weighted_sum, total_weight


def build_rebate_weight_pairs(rebates, rules, *, exclude_rebate_zero=False):
    pairs = []
    skipped_zero_weight = 0
    skipped_rebate_zero = 0
    for rebate in sorted({int(value) for value in rebates}):
        if exclude_rebate_zero and rebate == 0:
            skipped_rebate_zero += 1
            continue
        weight = get_group_weight_for_rebate(rebate, rules)
        if weight <= 0:
            skipped_zero_weight += 1
            continue
        pairs.append((rebate, int(weight)))
    return pairs, skipped_zero_weight, skipped_rebate_zero


def infer_zero_rebate_weight(nonzero_pairs, target_rtp):
    """Infer rebate=0 weight with ceiling rounding."""
    if target_rtp <= 0:
        return None
    weighted_sum, total_weight = calculate_weighted_sum_and_total(nonzero_pairs)
    if weighted_sum <= 0 or total_weight <= 0:
        return 0
    return max(0, math.ceil(weighted_sum / target_rtp - total_weight))


def build_special_group_weight_rows_for_group(group_id, special_pairs, zero_weight, game_type=2):
    group_id = int(group_id)
    game_type = int(game_type)
    rows = []
    if zero_weight > 0:
        rows.append((game_type, group_id, 0, int(zero_weight)))
    rows.extend((game_type, group_id, int(rebate), int(weight)) for rebate, weight in special_pairs)
    return rows


def infer_special_zero_weight(special_pairs, special_has_zero, target_rtp):
    if not special_has_zero:
        return 0, calculate_weighted_rtp(special_pairs)
    if target_rtp is None:
        raise ValueError("special mode has rebate=0; special target RTP is required")
    zero_weight = infer_zero_rebate_weight(special_pairs, target_rtp)
    if zero_weight is None:
        zero_weight = 0
    actual_pairs = list(special_pairs)
    if zero_weight > 0:
        actual_pairs.append((0, zero_weight))
    return int(zero_weight), calculate_weighted_rtp(actual_pairs)


def build_independent_group_weight_rows_for_group(
    group_id,
    game_type,
    pairs,
    has_zero,
    target_rtp,
    *,
    display_divisor=1,
):
    group_id = int(group_id)
    game_type = int(game_type)
    display_divisor = float(display_divisor)
    zero_weight = infer_zero_rebate_weight(pairs, target_rtp) if has_zero else 0
    if zero_weight is None:
        zero_weight = 0

    rows = []
    if zero_weight > 0:
        rows.append((game_type, group_id, 0, int(zero_weight)))
    rows.extend((game_type, group_id, int(rebate), int(weight)) for rebate, weight in pairs)

    actual_pairs = list(pairs)
    if zero_weight > 0:
        actual_pairs.append((0, zero_weight))
    actual_rtp = calculate_weighted_rtp(actual_pairs)

    return rows, {
        'group_id': group_id,
        'target_rtp': target_rtp,
        'zero_weight': int(zero_weight),
        'actual_rtp': actual_rtp,
        'display_rtp': None if actual_rtp is None else actual_rtp / display_divisor,
    }


def build_normal_group_weight_rows_for_group(
    group_id,
    normal_pairs,
    free_rtp,
    free_enabled,
    special_rtp,
    special_enabled,
    *,
    free_rate_getter,
    special_rate_getter,
    target_rtp_getter,
    game_type=1,
    target_multiplier=1,
    display_divisor=1,
):
    group_id = int(group_id)
    game_type = int(game_type)
    display_divisor = float(display_divisor)
    free_rate = free_rate_getter(group_id, free_enabled)
    special_rate = special_rate_getter(group_id, special_enabled)
    denominator = 1 - free_rate - special_rate
    if denominator <= 0:
        raise ValueError(
            f"group_id={group_id} normal probability is invalid: "
            f"1 - {free_rate} - {special_rate} = {denominator}"
        )
    total_target_rtp = target_rtp_getter(group_id) * float(target_multiplier)
    normal_target_rtp = (
        total_target_rtp
        - (free_rtp or 0) * free_rate
        - (special_rtp or 0) * special_rate
    ) / denominator
    zero_weight = infer_zero_rebate_weight(normal_pairs, normal_target_rtp)
    if zero_weight is None:
        zero_weight = 0

    rows = []
    if zero_weight > 0:
        rows.append((game_type, group_id, 0, int(zero_weight)))
    rows.extend((game_type, group_id, int(rebate), int(weight)) for rebate, weight in normal_pairs)

    actual_pairs = list(normal_pairs)
    if zero_weight > 0:
        actual_pairs.append((0, zero_weight))
    actual_normal_rtp = calculate_weighted_rtp(actual_pairs)

    return rows, {
        'group_id': group_id,
        'free_rate': free_rate,
        'special_rate': special_rate,
        'normal_target_rtp': normal_target_rtp,
        'zero_weight': int(zero_weight),
        'actual_normal_rtp': actual_normal_rtp,
        'display_rtp': None if actual_normal_rtp is None else actual_normal_rtp / display_divisor,
    }


def build_ex_group_weight_rows_for_group(
    group_id,
    ex_pairs,
    ex_has_zero,
    ex_game_type,
    ex_multiplier=1,
    *,
    target_rtp_getter,
):
    base_target_rtp = target_rtp_getter(group_id)
    target_rtp = base_target_rtp * float(ex_multiplier)
    rows, info = build_independent_group_weight_rows_for_group(
        group_id,
        ex_game_type,
        ex_pairs,
        ex_has_zero,
        target_rtp,
        display_divisor=ex_multiplier,
    )
    info['base_target_rtp'] = base_target_rtp
    info['multiplier'] = float(ex_multiplier)
    return rows, info


def format_weighted_rtp(value):
    if value is None:
        return "N/A"
    return f"{value:.4f}".rstrip('0').rstrip('.')
