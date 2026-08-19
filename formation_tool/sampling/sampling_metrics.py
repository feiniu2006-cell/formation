"""Timing and detail-log helpers for direct sampling."""

import time

from formation_tool.utils import log_utils

print = log_utils.emit

SAMPLING_TIMING_KEYS = (
    'id_query_seconds',
    'row_read_seconds',
    'row_write_seconds',
    'id_remap_seconds',
    'rebate_seconds',
)
SAMPLING_COUNTER_KEYS = (
    'random_range_attempts',
    'random_range_returned_ids',
    'random_range_added_ids',
    'random_range_duplicate_ids',
    'full_scan_fallback_count',
    'sparse_shortcut_count',
)
SLOW_REBATE_SUMMARY_LIMIT = 5


def new_sampling_timing():
    timing = {key: 0.0 for key in SAMPLING_TIMING_KEYS}
    timing.update({key: 0 for key in SAMPLING_COUNTER_KEYS})
    timing.update({
        'rebate_count': 0,
        'row_count': 0,
        'rebate_details': [],
        'full_scan_fallback_rebates': [],
    })
    return timing


def add_sampling_timing(timing, key, elapsed):
    if timing is not None:
        timing[key] = float(timing.get(key, 0.0)) + float(elapsed)


def add_sampling_counter(timing, key, value=1):
    if timing is not None:
        timing[key] = int(timing.get(key, 0)) + int(value)


def is_sampling_detailed_log_enabled(detailed_log_enabled=False):
    return bool(detailed_log_enabled)


def print_sampling_detail(message="", *, detailed_log_enabled=False, print_func=None):
    if is_sampling_detailed_log_enabled(detailed_log_enabled):
        (print_func or print)(message)


def print_sampling_timing_summary(timing, *, detailed_log_enabled=False, print_func=None):
    if not timing:
        return
    emit = print_func or print
    detail = lambda message="": print_sampling_detail(
        message,
        detailed_log_enabled=detailed_log_enabled,
        print_func=emit,
    )
    emit(
        f"\n采样性能汇总：rebate数 {int(timing.get('rebate_count', 0))}，"
        f"写入行数 {int(timing.get('row_count', 0))}，"
        f"rebate循环 {timing.get('rebate_seconds', 0.0):.2f} 秒"
    )
    emit(
        f"  阶段耗时：查ID {timing.get('id_query_seconds', 0.0):.2f} 秒，"
        f"读完整行 {timing.get('row_read_seconds', 0.0):.2f} 秒，"
        f"写临时表 {timing.get('row_write_seconds', 0.0):.2f} 秒，"
        f"append改ID {timing.get('id_remap_seconds', 0.0):.2f} 秒"
    )
    random_returned = int(timing.get('random_range_returned_ids', 0))
    random_added = int(timing.get('random_range_added_ids', 0))
    random_duplicates = int(timing.get('random_range_duplicate_ids', 0))
    hit_rate = (random_added / random_returned * 100.0) if random_returned else 0.0
    detail(
        f"  随机范围候选：尝试 {int(timing.get('random_range_attempts', 0))} 次，"
        f"返回 {random_returned} 个，新增 {random_added} 个，"
        f"重复 {random_duplicates} 个，新增率 {hit_rate:.1f}%"
    )
    fallback_rebates = timing.get('full_scan_fallback_rebates') or []
    if fallback_rebates:
        preview = ', '.join(str(value) for value in fallback_rebates[:8])
        if len(fallback_rebates) > 8:
            preview += ', ...'
        emit(f"  全量 DISTINCT fallback：{len(fallback_rebates)} 个 rebate ({preview})")
    else:
        detail("  全量 DISTINCT fallback：0 个 rebate")
    details = sorted(
        timing.get('rebate_details') or [],
        key=lambda item: item.get('total_seconds', 0.0),
        reverse=True,
    )
    if details and is_sampling_detailed_log_enabled(detailed_log_enabled):
        emit(f"  最慢rebate Top {min(len(details), SLOW_REBATE_SUMMARY_LIMIT)}：")
        for item in details[:SLOW_REBATE_SUMMARY_LIMIT]:
            emit(
                f"    rebate={item.get('rebate')} 总耗时 {item.get('total_seconds', 0.0):.2f} 秒，"
                f"行数={int(item.get('row_count', 0))}，"
                f"查ID={item.get('id_query_seconds', 0.0):.2f}，"
                f"读行={item.get('row_read_seconds', 0.0):.2f}，"
                f"写入={item.get('row_write_seconds', 0.0):.2f}，"
                f"改ID={item.get('id_remap_seconds', 0.0):.2f}，"
                f"随机尝试={int(item.get('random_range_attempts', 0))}，"
                f"fallback={'是' if int(item.get('full_scan_fallback_count', 0)) else '否'}"
            )


def snapshot_sampling_timing(timing):
    if timing is None:
        return {}
    snapshot = {key: float(timing.get(key, 0.0)) for key in SAMPLING_TIMING_KEYS}
    snapshot.update({key: int(timing.get(key, 0)) for key in SAMPLING_COUNTER_KEYS})
    return snapshot


def record_rebate_timing(timing, start, row_count=0, target_rebate=None, before=None):
    if timing is None:
        return
    total_seconds = time.perf_counter() - start
    add_sampling_timing(timing, 'rebate_seconds', total_seconds)
    timing['rebate_count'] = int(timing.get('rebate_count', 0)) + 1
    timing['row_count'] = int(timing.get('row_count', 0)) + int(row_count or 0)
    before = before or {}
    detail = {
        'rebate': target_rebate,
        'row_count': int(row_count or 0),
        'total_seconds': total_seconds,
    }
    for key in ('id_query_seconds', 'row_read_seconds', 'row_write_seconds', 'id_remap_seconds'):
        detail[key] = float(timing.get(key, 0.0)) - float(before.get(key, 0.0))
    for key in SAMPLING_COUNTER_KEYS:
        detail[key] = int(timing.get(key, 0)) - int(before.get(key, 0))
    timing.setdefault('rebate_details', []).append(detail)
