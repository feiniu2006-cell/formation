"""SQL identifier and table-name helpers for the formation tool."""

import os
import re
import time


SQL_IDENTIFIER_RE = re.compile(r'^[0-9A-Za-z_$-]+$')


def validate_sql_identifier(identifier, label="SQL标识符"):
    """校验动态 SQL 标识符，避免表名/库名拼接出危险 SQL。"""
    text = str(identifier).strip()
    if not text:
        raise ValueError(f"{label}不能为空")
    if len(text) > 64:
        raise ValueError(f"{label}长度不能超过 64 个字符: {text}")
    if not SQL_IDENTIFIER_RE.fullmatch(text):
        raise ValueError(f"{label}包含非法字符: {text}")
    return text


def quote_identifier(identifier, label="SQL标识符"):
    """校验并引用 MySQL 标识符。"""
    text = validate_sql_identifier(identifier, label)
    return f"`{text}`"


def make_staging_table_name(base_table_name, label='tmp'):
    """生成不超过 MySQL 表名长度限制的临时表名。"""
    base_table_name = validate_sql_identifier(base_table_name, "临时表基准名")
    label = validate_sql_identifier(label, "临时表标签")
    suffix = f"_{label}_{os.getpid()}_{int(time.time() * 1000) % 1000000}"
    max_base_len = max(1, 64 - len(suffix))
    return f"{str(base_table_name)[:max_base_len]}{suffix}"


def chunked(values, size=500):
    values = list(values)
    for start in range(0, len(values), size):
        yield values[start:start + size]

