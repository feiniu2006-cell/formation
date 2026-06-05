"""Shared log formatting helpers for formation tool scripts."""

import traceback

_LOG_WRITER = print


def set_log_writer(writer):
    """Set the callable used by emit(); mainly useful for tests and UI bridges."""
    global _LOG_WRITER
    _LOG_WRITER = writer or print


def reset_log_writer():
    """Restore stdout logging."""
    set_log_writer(print)


def emit(message=""):
    """Write one log line through the configured log sink."""
    _LOG_WRITER(str(message))


def section(title):
    return f"\n=== {title} ==="


def print_section(title):
    emit(section(title))


def status_label(result, *, skipped_value=None):
    if result is None or result == skipped_value:
        return "跳过"
    return "成功" if result else "失败"


def print_result_summary(title, items, *, name_getter=None, skipped_value=None):
    print_section(title)
    for key, result in items.items():
        label = name_getter(key) if name_getter else key
        emit(f"  {label}: {status_label(result, skipped_value=skipped_value)}")


def print_write_complete(count, target):
    emit(f"写入完成：{count} 条 -> {target}")


def print_no_group_weight_rows():
    emit("没有可写入的 group_weight 数据，已跳过写入")


def print_group_weight_validation_failed(error):
    emit(f"group_weight 数据校验失败：{error}")


def print_replace_with_staging_notice(target):
    emit(f"正在使用临时表安全替换：{target}")


def print_step_error(label, error, *, include_trace=False):
    emit(f"{label}: {error}")
    if include_trace:
        emit(traceback.format_exc())
