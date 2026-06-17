"""Pure rebate_count configuration row-building logic."""


def _noop():
    pass


def _is_missing(value):
    return value is None or value != value


def _resolve_detail_print_fn(print_fn, detail_print_fn):
    return print_fn if detail_print_fn is None else detail_print_fn


def normalize_rebate_config_rows(rows, mode_name):
    """Sort generated rebate_count rows and reject duplicate rebate values."""
    normalized = []
    seen = {}
    duplicates = []
    for rebate, count in rows:
        rebate = int(rebate)
        count = int(count)
        if rebate in seen:
            duplicates.append(rebate)
        seen[rebate] = count
        normalized.append((rebate, count))
    if duplicates:
        preview = sorted(set(duplicates))[:20]
        suffix = "..." if len(set(duplicates)) > 20 else ""
        raise ValueError(f"{mode_name} 采样规则产生重复 rebate：{preview}{suffix}")
    return sorted(normalized, key=lambda item: item[0])


def get_count_for_rebate(rebate, rules):
    """Return the configured count for a rebate, or None when no rule matches."""
    for rule in rules:
        if 'rebate' in rule and rule['rebate'] == rebate:
            return rule['count']
        if 'rebate_min' in rule and rule['rebate_min'] <= rebate <= rule['rebate_max']:
            return rule['count']
    return None


def get_rule_for_rebate(rebate, rules):
    """Return the full rule that matches a rebate, or None when no rule matches."""
    for rule in rules:
        if 'rebate' in rule and rule['rebate'] == rebate:
            return rule
        if 'rebate_min' in rule and rule['rebate_min'] <= rebate <= rule['rebate_max']:
            return rule
    return None


def build_direct_rebate_config_rows(stats_df, *, check_cancelled=_noop, print_fn=print):
    """Low-volume mode: write queried rebate/total directly as count."""
    print_fn(f"{'rebate':>12}  {'total':>10}  {'count':>10}  备注")
    print_fn("-" * 50)
    result_rows = []
    for row in stats_df[['rebate', 'total']].itertuples(index=False):
        check_cancelled()
        if _is_missing(row.rebate):
            continue
        rebate = int(row.rebate)
        total = int(row.total)
        if total <= 0:
            continue
        print_fn(f"{rebate:>12}  {total:>10}  {total:>10}  直接写入")
        result_rows.append((rebate, total))
    return result_rows


def normalize_direct_count_tier_limits(tiers):
    """Normalize and validate direct-count tier cap rules."""
    normalized = []
    for index, rule in enumerate(tiers or [], start=1):
        if not isinstance(rule, dict):
            raise ValueError(f"直接计数阶梯第 {index} 行必须是对象")
        has_exact = 'rebate' in rule and str(rule.get('rebate')).strip() != ''
        has_range = (
            'rebate_min' in rule and str(rule.get('rebate_min')).strip() != ''
            or 'rebate_max' in rule and str(rule.get('rebate_max')).strip() != ''
        )
        if has_exact and has_range:
            raise ValueError(f"直接计数阶梯第 {index} 行不能同时填写 rebate 和区间")
        if not has_exact and not has_range:
            raise ValueError(f"直接计数阶梯第 {index} 行必须填写 rebate 或 rebate_min/rebate_max")
        if 'count' not in rule or str(rule.get('count')).strip() == '':
            raise ValueError(f"直接计数阶梯第 {index} 行 count 不能为空")
        try:
            count = int(rule['count'])
        except (TypeError, ValueError):
            raise ValueError(f"直接计数阶梯第 {index} 行 count 必须是整数: {rule.get('count')}") from None
        if count <= 0:
            raise ValueError(f"直接计数阶梯第 {index} 行 count 必须大于 0: {count}")

        if has_exact:
            try:
                rebate = int(rule['rebate'])
            except (TypeError, ValueError):
                raise ValueError(f"直接计数阶梯第 {index} 行 rebate 必须是整数: {rule.get('rebate')}") from None
            if rebate < 0:
                raise ValueError(f"直接计数阶梯第 {index} 行 rebate 不能小于 0: {rebate}")
            normalized.append({'rebate': rebate, 'count': count})
            continue

        if 'rebate_min' not in rule or 'rebate_max' not in rule:
            raise ValueError(f"直接计数阶梯第 {index} 行区间必须同时填写 rebate_min 和 rebate_max")
        try:
            rebate_min = int(rule['rebate_min'])
            rebate_max = int(rule['rebate_max'])
        except (TypeError, ValueError):
            raise ValueError(f"直接计数阶梯第 {index} 行 rebate_min/rebate_max 必须是整数") from None
        if rebate_min < 0 or rebate_max < 0:
            raise ValueError(f"直接计数阶梯第 {index} 行 rebate 区间不能小于 0")
        if rebate_min > rebate_max:
            raise ValueError(f"直接计数阶梯第 {index} 行 rebate_min 不能大于 rebate_max")
        normalized.append({'rebate_min': rebate_min, 'rebate_max': rebate_max, 'count': count})

    sortable = []
    for rule in normalized:
        if 'rebate' in rule:
            sortable.append((rule['rebate'], rule['rebate'], rule))
        else:
            sortable.append((rule['rebate_min'], rule['rebate_max'], rule))
    sortable.sort(key=lambda item: (item[0], item[1]))

    previous_end = None
    for start, end, _rule in sortable:
        if previous_end is not None and start <= previous_end:
            raise ValueError(f"直接计数阶梯区间存在重叠，冲突位置: {start}")
        previous_end = end
    return [rule for _start, _end, rule in sortable]


def get_direct_count_tier_limit_for_rebate(rebate, count_limits):
    """Return direct-count mode cap for one rebate from direct_count_tiers."""
    if not count_limits:
        return None
    for rule in count_limits.get('direct_count_tiers') or ():
        if 'rebate' in rule and int(rule['rebate']) == int(rebate):
            return int(rule['count'])
        if (
            'rebate_min' in rule
            and 'rebate_max' in rule
            and int(rule['rebate_min']) <= int(rebate) <= int(rule['rebate_max'])
        ):
            return int(rule['count'])
    return None


def apply_direct_count_tier_limits_to_rows(
    rows,
    count_limits=None,
    label="采样配置",
    *,
    print_fn=print,
    detail_print_fn=None,
):
    """Apply rebate-dependent caps for low-volume direct-count mode."""
    if not count_limits or not count_limits.get('direct_count_tiers'):
        return rows

    detail_print_fn = _resolve_detail_print_fn(print_fn, detail_print_fn)
    limited_rows = []
    truncated_count = 0
    for rebate, count in rows:
        rebate = int(rebate)
        count = int(count)
        tier_limit = get_direct_count_tier_limit_for_rebate(rebate, count_limits)
        if tier_limit is not None and tier_limit > 0 and count > tier_limit:
            truncated_count += 1
            detail_print_fn(
                f"  {label} 直接计数阶梯：rebate={rebate}，"
                f"{count} -> {tier_limit}（上限 {tier_limit}）"
            )
            count = tier_limit
        limited_rows.append((rebate, count))
    if truncated_count:
        print_fn(f"  {label} 直接计数阶梯共截断 {truncated_count} 条 rebate 配置")
    return limited_rows


def select_smooth_rebate_bucket_rows(
    rule,
    bucket_rows,
    limit_min,
    limit_max,
    *,
    check_cancelled=_noop,
    print_fn=print,
    detail_print_fn=None,
):
    """Select rebate rows from a range rule using smooth buckets."""
    detail_print_fn = _resolve_detail_print_fn(print_fn, detail_print_fn)
    selected_rows = []
    n_buckets = rule['smooth_buckets']
    r_min = rule['rebate_min']
    r_max = rule['rebate_max']
    bkt_width = (r_max - r_min + 1) / n_buckets
    per_bucket = max(1, limit_max // n_buckets)
    sub_buckets = {}
    for rebate, total, actual in bucket_rows:
        idx = min(int((rebate - r_min) / bkt_width), n_buckets - 1)
        sub_buckets.setdefault(idx, []).append((rebate, total, actual))

    available = len(bucket_rows)
    if available < limit_min:
        print_fn(f"  警告：该范围可用 rebate 数量 ({available}) 不足下限 ({limit_min})，取全部可用")

    for sub_idx in range(n_buckets):
        check_cancelled()
        sub_rows = sub_buckets.get(sub_idx, [])
        if not sub_rows:
            continue
        sub_rows_sorted = sorted(sub_rows, key=lambda item: item[0])
        n_rows = len(sub_rows_sorted)
        if n_rows <= per_bucket:
            selected = sub_rows_sorted
        else:
            step = (n_rows - 1) / (per_bucket - 1) if per_bucket > 1 else 0
            indices = [round(i * step) for i in range(per_bucket)]
            selected = [sub_rows_sorted[i] for i in indices]
        sub_start = int(r_min + sub_idx * bkt_width)
        sub_end = int(r_min + (sub_idx + 1) * bkt_width) - 1
        for rebate, total, actual in selected:
            note = f"截断({total})->{actual}" if rule['count'] > total else ""
            print_fn(f"{rebate:>12}  {total:>10}  {actual:>10}  [子区{sub_start}~{sub_end}] {note}")
            selected_rows.append((rebate, actual))
    return selected_rows


def select_limited_rebate_bucket_rows(
    rule,
    bucket_rows,
    limit_min,
    limit_max,
    *,
    check_cancelled=_noop,
    print_fn=print,
    detail_print_fn=None,
):
    """Select rebate rows from a range rule by total desc, capped by rebate_limit_max."""
    detail_print_fn = _resolve_detail_print_fn(print_fn, detail_print_fn)
    selected_rows = []
    rows = sorted(bucket_rows, key=lambda item: (-item[1], item[0]))
    available = len(rows)
    if available < limit_min:
        print_fn(f"  警告：该范围可用 rebate 数量 ({available}) 不足下限 ({limit_min})，取全部可用")
    take = min(available, limit_max)
    selected = rows[:take]
    skipped = rows[take:]
    for rebate, total, actual in selected:
        check_cancelled()
        note = f"截断({total})->{actual}" if rule['count'] > total else ""
        print_fn(f"{rebate:>12}  {total:>10}  {actual:>10}  {note}")
        selected_rows.append((rebate, actual))
    for rebate, total, _actual in skipped:
        detail_print_fn(f"{rebate:>12}  {total:>10}  {'---':>10}  超出 rebate_limit_max 跳过")
    return selected_rows


def build_rule_based_rebate_config_rows(
    stats_df,
    rules,
    *,
    check_cancelled=_noop,
    print_fn=print,
    detail_print_fn=None,
):
    """Convert rebate distribution rows into rebate_count rows by configured rules."""
    detail_print_fn = _resolve_detail_print_fn(print_fn, detail_print_fn)
    print_fn(f"{'rebate':>12}  {'total':>10}  {'count':>10}  备注")
    print_fn("-" * 50)
    range_buckets = {}
    result_rows = []

    for row in stats_df[['rebate', 'total']].itertuples(index=False):
        check_cancelled()
        rebate = int(row.rebate)
        total = int(row.total)
        rule = get_rule_for_rebate(rebate, rules)
        if rule is None:
            detail_print_fn(f"{rebate:>12}  {total:>10}  {'---':>10}  跳过")
            continue
        min_total = rule.get('min_total', 0)
        if total < min_total:
            detail_print_fn(f"{rebate:>12}  {total:>10}  {'---':>10}  数据量不足 min_total({min_total})，跳过")
            continue
        count = rule['count']
        actual = min(count, total)
        if 'rebate_limit_max' in rule:
            rule_id = id(rule)
            range_buckets.setdefault(rule_id, {'rule': rule, 'rows': []})
            range_buckets[rule_id]['rows'].append((rebate, total, actual))
        else:
            note = f"截断({total})->{actual}" if count > total else ""
            print_fn(f"{rebate:>12}  {total:>10}  {actual:>10}  {note}")
            result_rows.append((rebate, actual))

    for bucket in range_buckets.values():
        check_cancelled()
        rule = bucket['rule']
        limit_min = rule.get('rebate_limit_min', 0)
        limit_max = rule['rebate_limit_max']
        if 'smooth_buckets' in rule:
            result_rows.extend(
                select_smooth_rebate_bucket_rows(
                    rule,
                    bucket['rows'],
                    limit_min,
                    limit_max,
                    check_cancelled=check_cancelled,
                    print_fn=print_fn,
                    detail_print_fn=detail_print_fn,
                )
            )
        else:
            result_rows.extend(
                select_limited_rebate_bucket_rows(
                    rule,
                    bucket['rows'],
                    limit_min,
                    limit_max,
                    check_cancelled=check_cancelled,
                    print_fn=print_fn,
                    detail_print_fn=detail_print_fn,
                )
            )
    return result_rows


def get_rebate_config_count_limit_for_rebate(rebate, count_limits):
    """Return generated rebate_count count cap by rebate type."""
    if not count_limits:
        return None
    rebate = int(rebate)
    if rebate == 0:
        return count_limits.get('rebate_zero')
    if rebate > 0:
        return count_limits.get('rebate_positive')
    return None


def apply_rebate_config_count_limit(rebate, count, count_limits=None):
    """Apply generated rebate_count count cap for a single rebate row."""
    count = int(count)
    limit = get_rebate_config_count_limit_for_rebate(rebate, count_limits)
    if limit is None:
        return count, None
    limit = int(limit)
    if limit <= 0 or count <= limit:
        return count, None
    return limit, limit


def get_rebate_config_max_rebate(count_limits):
    """Return the maximum rebate allowed in generated rebate_count rows."""
    if not count_limits:
        return None
    max_rebate = count_limits.get('max_rebate')
    if max_rebate is None or str(max_rebate).strip() == '':
        return None
    return int(max_rebate)


def _normalize_rule_rebate_ranges(rules, max_rebate=None):
    ranges = []
    for rule in rules or []:
        if 'rebate' in rule:
            start = end = int(rule['rebate'])
        elif 'rebate_min' in rule and 'rebate_max' in rule:
            start = int(rule['rebate_min'])
            end = int(rule['rebate_max'])
        else:
            continue
        if max_rebate is not None:
            end = min(end, int(max_rebate))
        if start > end:
            continue
        ranges.append((start, end))
    if not ranges:
        return []

    ranges.sort()
    merged = []
    for start, end in ranges:
        if not merged or start > merged[-1][1] + 1:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [(start, end) for start, end in merged]


def build_rebate_sql_filter(rules=None, count_limits=None, *, include_rule_ranges=True):
    """Build an SQL predicate that limits rebate stats to useful rebate values."""
    max_rebate = get_rebate_config_max_rebate(count_limits)
    if not include_rule_ranges:
        if max_rebate is None:
            return None
        return f"`rebate` <= {int(max_rebate)}"

    ranges = _normalize_rule_rebate_ranges(rules, max_rebate=max_rebate)
    if not ranges:
        if max_rebate is None:
            return None
        return "1=0"

    clauses = []
    for start, end in ranges:
        if start == end:
            clauses.append(f"`rebate` = {start}")
        else:
            clauses.append(f"`rebate` BETWEEN {start} AND {end}")
    if len(clauses) == 1:
        return clauses[0]
    return "(" + " OR ".join(clauses) + ")"


def apply_rebate_config_max_rebate_to_rows(
    rows,
    count_limits=None,
    label="采样配置",
    *,
    print_fn=print,
    detail_print_fn=None,
):
    """Drop generated rebate_count rows whose rebate exceeds the configured max rebate."""
    max_rebate = get_rebate_config_max_rebate(count_limits)
    if max_rebate is None:
        return rows

    detail_print_fn = _resolve_detail_print_fn(print_fn, detail_print_fn)
    kept_rows = []
    skipped_count = 0
    for rebate, count in rows:
        rebate = int(rebate)
        if rebate > max_rebate:
            skipped_count += 1
            detail_print_fn(f"  {label} rebate上限：rebate={rebate} > {max_rebate}，跳过")
            continue
        kept_rows.append((rebate, int(count)))
    if skipped_count:
        print_fn(f"  {label} rebate 上限共跳过 {skipped_count} 条配置")
    return kept_rows


def apply_rebate_config_count_limits_to_rows(
    rows,
    count_limits=None,
    label="采样配置",
    *,
    print_fn=print,
    detail_print_fn=None,
):
    """Apply generated rebate_count max-rebate and count caps."""
    if not count_limits:
        return rows

    detail_print_fn = _resolve_detail_print_fn(print_fn, detail_print_fn)
    rows = apply_rebate_config_max_rebate_to_rows(
        rows,
        count_limits,
        label,
        print_fn=print_fn,
        detail_print_fn=detail_print_fn,
    )
    limited_rows = []
    truncated_count = 0
    for rebate, count in rows:
        limited_count, applied_limit = apply_rebate_config_count_limit(rebate, count, count_limits)
        if applied_limit is not None:
            truncated_count += 1
            detail_print_fn(
                f"  {label} count上限：rebate={int(rebate)}，"
                f"{int(count)} -> {limited_count}（上限 {applied_limit}）"
            )
        limited_rows.append((int(rebate), int(limited_count)))
    if truncated_count:
        print_fn(f"  {label} count 上限共截断 {truncated_count} 条 rebate 配置")
    return limited_rows
