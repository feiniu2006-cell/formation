"""Direct sampling core helpers for formation source tables."""

import contextlib
import os
import random
import re
import shutil
import subprocess
import tempfile
import time
from types import SimpleNamespace

import pandas as pd

from formation_tool.core import formation_defaults
from formation_tool.core import runtime_context_sync
from formation_tool.sampling import direct_sampling_runner
from formation_tool.sampling import sampling_task_state
from formation_tool.sampling import sampling_table_utils
from formation_tool.utils import log_utils
from formation_tool.utils.task_utils import TaskCancelled

print = log_utils.emit

SAMPLE_ID_RANDOM_RANGE_ATTEMPTS = 8
SAMPLE_ID_RANDOM_RANGE_MAX_ATTEMPTS = 20
SAMPLE_ID_RANDOM_RANGE_MAX_CANDIDATES_PER_QUERY = 20000
SAMPLE_ID_FETCH_CHUNK_SIZE = formation_defaults.DEFAULT_SAMPLE_ID_FETCH_CHUNK_SIZE
SAMPLE_ROW_WRITE_CHUNK_SIZE = 20
SAMPLE_TABLE_COPY_CHUNK_SIZE = 1000
MYSQL_DUMP_IMPORT_RETRIES = 5
SAMPLING_DETAILED_LOG = False
SAMPLING_INCREMENT_DB = formation_defaults.DEFAULT_SAMPLING_INCREMENT_DB
SLOW_REBATE_SUMMARY_LIMIT = 5
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


class SamplingFieldMismatchError(RuntimeError):
    user_dialog_title = "补充采样字段不一致"

    def __init__(self, message):
        super().__init__(message)
        self.user_dialog_message = str(message)


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


def is_sampling_detailed_log_enabled():
    return bool(globals().get('SAMPLING_DETAILED_LOG', False))


def print_sampling_detail(message=""):
    if is_sampling_detailed_log_enabled():
        print(message)


def print_sampling_timing_summary(timing):
    if not timing:
        return
    print(
        f"\n采样性能汇总：rebate数 {int(timing.get('rebate_count', 0))}，"
        f"写入行数 {int(timing.get('row_count', 0))}，"
        f"rebate循环 {timing.get('rebate_seconds', 0.0):.2f} 秒"
    )
    print(
        f"  阶段耗时：查ID {timing.get('id_query_seconds', 0.0):.2f} 秒，"
        f"读完整行 {timing.get('row_read_seconds', 0.0):.2f} 秒，"
        f"写临时表 {timing.get('row_write_seconds', 0.0):.2f} 秒，"
        f"append改ID {timing.get('id_remap_seconds', 0.0):.2f} 秒"
    )
    random_returned = int(timing.get('random_range_returned_ids', 0))
    random_added = int(timing.get('random_range_added_ids', 0))
    random_duplicates = int(timing.get('random_range_duplicate_ids', 0))
    hit_rate = (random_added / random_returned * 100.0) if random_returned else 0.0
    print_sampling_detail(
        f"  随机范围候选：尝试 {int(timing.get('random_range_attempts', 0))} 次，"
        f"返回 {random_returned} 个，新增 {random_added} 个，"
        f"重复 {random_duplicates} 个，新增率 {hit_rate:.1f}%"
    )
    fallback_rebates = timing.get('full_scan_fallback_rebates') or []
    if fallback_rebates:
        preview = ', '.join(str(value) for value in fallback_rebates[:8])
        if len(fallback_rebates) > 8:
            preview += ', ...'
        print(f"  全量 DISTINCT fallback：{len(fallback_rebates)} 个 rebate ({preview})")
    else:
        print_sampling_detail("  全量 DISTINCT fallback：0 个 rebate")
    details = sorted(
        timing.get('rebate_details') or [],
        key=lambda item: item.get('total_seconds', 0.0),
        reverse=True,
    )
    if details and is_sampling_detailed_log_enabled():
        print(f"  最慢rebate Top {min(len(details), SLOW_REBATE_SUMMARY_LIMIT)}：")
        for item in details[:SLOW_REBATE_SUMMARY_LIMIT]:
            print(
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


def configure(**values):
    """Inject the explicit runtime context owned by the main formation script."""
    runtime_context_sync.configure_module_globals(
        globals(),
        values,
        runtime_context_sync.SAMPLING_CORE_CONTEXT_KEYS,
        'sampling_core context',
    )
    sampling_table_utils.configure(**values)


create_table_like_source = sampling_table_utils.create_table_like_source
create_final_table_like_source = sampling_table_utils.create_final_table_like_source
is_same_physical_table = sampling_table_utils.is_same_physical_table
get_table_columns = sampling_table_utils.get_table_columns
same_table_structure = sampling_table_utils.same_table_structure
same_table_structure_for_append = sampling_table_utils.same_table_structure_for_append
compare_table_structure_for_append = sampling_table_utils.compare_table_structure_for_append
validate_table_config = sampling_table_utils.validate_table_config
get_sample_description = sampling_table_utils.get_sample_description
remap_conflicting_sample_ids = sampling_table_utils.remap_conflicting_sample_ids
check_source_table_exists = sampling_table_utils.check_source_table_exists
detect_end_field = sampling_table_utils.detect_end_field
detect_end_field_optional = sampling_table_utils.detect_end_field_optional
validate_end_field_integrity = sampling_table_utils.validate_end_field_integrity


def run_single_game(game_config, *, append_mode=False):
    """执行单个游戏模式采样。"""
    table_config = game_config['table_config']
    sample_conditions = game_config['sample_conditions']
    source_table_name = get_table_name('SOURCE_TABLE', table_config)

    print(f"\n{'=' * 50}")
    action_name = "补充采样" if append_mode else "采样"
    print(f"开始处理：{game_config['name']}（{action_name}）")

    if not check_source_table_exists(table_config):
        print(f"源表 {source_table_name} 不存在，跳过 {game_config['name']}")
        return False

    if not validate_table_config(table_config):
        print("配置验证失败，跳过")
        return False

    try:
        return bool(direct_sample_from_source(table_config, sample_conditions, append_mode=append_mode))
    except (TaskCancelled, SamplingFieldMismatchError):
        raise
    except Exception as e:
        print(f"处理过程中出现错误: {e}")
        return False


def resolve_direct_sample_conditions(source_conn, table_config, sample_conditions):
    """解析采样 where_clause 中的结束字段占位符；完整性校验延后到已采样 id 上执行。"""
    where_tpl = sample_conditions['where_clause']
    if not any(pattern in where_tpl for pattern in ('{end_field}', '{end_field_opt}')):
        return sample_conditions

    source_table_name = get_table_name('SOURCE_TABLE', table_config)
    end_field_for_validation = None
    if '{end_field}' in where_tpl:
        end_field = detect_end_field(source_conn, source_table_name)
        if end_field is None:
            print(f"  {source_table_name} 中未找到 game_end 或 is_end 字段，视为表不存在，跳过")
            return None
        where_tpl = where_tpl.replace('{end_field}', end_field)
        print(f"  检测到结束条件字段：{end_field}")
        end_field_for_validation = end_field
    if '{end_field_opt}' in where_tpl:
        end_field_opt = detect_end_field_optional(source_conn, source_table_name)
        where_tpl = where_tpl.replace('{end_field_opt}', end_field_opt)
        end_text = (
            'game_end = 1'
            if 'game_end' in end_field_opt
            else 'is_end = 1'
            if 'is_end' in end_field_opt
            else '无'
        )
        print(f"  结束条件：{end_text}")
        if 'game_end' in end_field_opt:
            end_field_for_validation = 'game_end'
        elif 'is_end' in end_field_opt:
            end_field_for_validation = 'is_end'

    require_game_id_zero_for_validation = False
    if end_field_for_validation:
        source_columns = get_table_columns(source_conn, source_table_name) or []
        source_column_names = {str(column[0]).lower() for column in source_columns}
        require_game_id_zero_for_validation = (
            end_field_for_validation == 'game_end'
            and 'game_id' in source_column_names
        )
        validation_fields = end_field_for_validation
        if require_game_id_zero_for_validation:
            validation_fields += "，并要求每个id包含game_id=0"
        print(f"  数据完整性校验将按已采样ID执行（{validation_fields}）")
    return {
        **sample_conditions,
        'where_clause': where_tpl,
        'end_field_for_validation': end_field_for_validation,
        'require_game_id_zero_for_validation': require_game_id_zero_for_validation,
    }


def _preview_values(values, limit=5):
    values = list(values)
    items = [repr(value) for value in values[:limit]]
    if len(values) > limit:
        items.append('...')
    return ', '.join(items)


def _sampling_config_label(config_db_name, rebate_config_table_name):
    if config_db_name:
        return f"{config_db_name}.{rebate_config_table_name}"
    return str(rebate_config_table_name)


def _coerce_sampling_config_int_column(config_df, column, table_label):
    numeric = pd.to_numeric(config_df[column], errors='coerce')
    bool_mask = config_df[column].map(lambda value: isinstance(value, bool))
    invalid_mask = numeric.isna() | bool_mask | (numeric % 1 != 0)
    if invalid_mask.any():
        bad_values = config_df.loc[invalid_mask, column].tolist()
        raise ValueError(f"{table_label} 采样配置字段 {column} 必须是整数，异常值：{_preview_values(bad_values)}")
    return numeric.astype('int64')


def normalize_sampling_config_df(config_df, config_db_name=None, rebate_config_table_name='rebate_count'):
    """Validate and normalize rebate/count sampling config rows before sampling."""
    table_label = _sampling_config_label(config_db_name, rebate_config_table_name)
    required_columns = {'rebate', 'count'}
    missing = sorted(required_columns - set(config_df.columns))
    if missing:
        raise ValueError(f"{table_label} 采样配置缺少字段：{', '.join(missing)}")

    normalized = config_df[['rebate', 'count']].copy()
    normalized['rebate'] = _coerce_sampling_config_int_column(normalized, 'rebate', table_label)
    normalized['count'] = _coerce_sampling_config_int_column(normalized, 'count', table_label)

    negative_rebates = normalized.loc[normalized['rebate'] < 0, 'rebate'].tolist()
    if negative_rebates:
        raise ValueError(f"{table_label} 采样配置 rebate 不能小于 0：{_preview_values(negative_rebates)}")

    non_positive_counts = normalized.loc[normalized['count'] <= 0, 'count'].tolist()
    if non_positive_counts:
        raise ValueError(f"{table_label} 采样配置 count 必须大于 0：{_preview_values(non_positive_counts)}")

    duplicate_rebates = sorted(set(normalized.loc[normalized['rebate'].duplicated(keep=False), 'rebate'].tolist()))
    if duplicate_rebates:
        raise ValueError(f"{table_label} 采样配置 rebate 重复：{_preview_values(duplicate_rebates)}")

    return normalized


def load_sampling_config_df(config_engine, config_db_name, rebate_config_table_name):
    """读取 rebate_count 采样配置。"""
    print(f"正在从 {config_db_name}.{rebate_config_table_name} 加载采样配置...")
    rebate_config_table_ref = quote_identifier(rebate_config_table_name, "采样配置表名")
    config_df = pd.read_sql_query(
        f"SELECT `rebate`, `count` FROM {rebate_config_table_ref}",
        config_engine,
    )
    print(f"加载了 {len(config_df)} 条采样配置")
    if config_df.empty:
        print(f"{config_db_name}.{rebate_config_table_name} 没有采样配置数据，目标表未替换")
        return None
    return normalize_sampling_config_df(config_df, config_db_name, rebate_config_table_name)


def _cursor_rows_as_dicts(cur):
    columns = [desc[0] for desc in (cur.description or [])]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def _load_table_index_columns(conn, table_name):
    table_ref = quote_identifier(table_name, "源表名")
    with conn.cursor() as cur:
        cur.execute(f"SHOW INDEX FROM {table_ref}")
        rows = _cursor_rows_as_dicts(cur)
    index_columns = {}
    for row in rows:
        key_name = row.get('Key_name')
        column_name = row.get('Column_name')
        seq = row.get('Seq_in_index')
        if not key_name or not column_name:
            continue
        index_columns.setdefault(str(key_name), []).append((int(seq or 0), str(column_name)))
    return {
        key: [column for _seq, column in sorted(values)]
        for key, values in index_columns.items()
    }


def _detect_sampling_end_field(where_clause):
    text = str(where_clause or '').lower()
    if 'game_end' in text:
        return 'game_end'
    if 'is_end' in text:
        return 'is_end'
    return None


def warn_sampling_read_index(source_conn, source_table_name, sample_conditions):
    """Warn when complete-row sampling reads may miss useful indexes."""
    where_clause = sample_conditions.get('where_clause', '')
    end_field = _detect_sampling_end_field(where_clause)
    index_columns = _load_table_index_columns(source_conn, source_table_name)
    lower_indexes = {
        name: [column.lower() for column in columns]
        for name, columns in index_columns.items()
    }
    has_id_index = any(columns[:1] == ['id'] for columns in lower_indexes.values())
    id_select_prefixes = [['rebate', 'id']]
    if end_field:
        id_select_prefixes.insert(0, [end_field, 'rebate', 'id'])
    has_id_select_index = any(
        any(columns[:len(prefix)] == prefix for prefix in id_select_prefixes)
        for columns in lower_indexes.values()
    )
    if has_id_index and has_id_select_index:
        used = [
            f"{name}({', '.join(index_columns[name])})"
            for name, columns in lower_indexes.items()
            if columns[:1] == ['id']
            or any(columns[:len(prefix)] == prefix for prefix in id_select_prefixes)
        ]
        print(f"实际采样读取索引检查通过：{source_table_name}，可用索引：{'; '.join(used)}")
        return

    print(f"实际采样读取索引风险：{source_table_name} 索引不完整。")
    print("  当前流程会先按 rebate/结束条件挑选ID，再使用 id IN (...) 读取完整ID组。")
    if not has_id_select_index and end_field:
        print(
            f"  建议添加挑ID复合索引：ALTER TABLE {source_table_name} "
            f"ADD INDEX idx_{end_field}_rebate_id (`{end_field}`, `rebate`, `id`);"
        )
    if not has_id_select_index:
        print(
            f"  或添加挑ID复合索引：ALTER TABLE {source_table_name} "
            "ADD INDEX idx_rebate_id (`rebate`, `id`);"
        )
    if not has_id_index:
        print(
            f"  建议添加完整组读取索引：ALTER TABLE {source_table_name} "
            "ADD INDEX idx_id (`id`);"
        )


def _sample_ids_from_candidates(candidate_ids, sample_size, random_seed):
    candidate_ids = sorted({int(value) for value in candidate_ids})
    if len(candidate_ids) <= sample_size:
        return candidate_ids
    rng = random.Random(str(random_seed))
    return rng.sample(candidate_ids, sample_size)


def _query_int_column(source_engine, query):
    with source_engine.connect() as conn:
        result = conn.exec_driver_sql(query)
        return [int(row[0]) for row in result if row[0] is not None]


def _query_single_row(source_engine, query):
    with source_engine.connect() as conn:
        result = conn.exec_driver_sql(query)
        return result.fetchone()


def _select_sample_ids_with_full_scan(
    *,
    source_engine,
    source_db_name,
    source_table_ref,
    where_clause,
    target_rebate,
    sample_size,
    random_seed,
    timing=None,
):
    """Fallback: query all matching distinct ids and sample in Python."""
    add_sampling_counter(timing, 'full_scan_fallback_count')
    if timing is not None:
        timing.setdefault('full_scan_fallback_rebates', []).append(int(target_rebate))
    start = time.perf_counter()
    id_query = f"""
    SELECT DISTINCT `id`
    FROM {source_table_ref}
    WHERE {where_clause}
    """
    ids = sql_with_retry(
        lambda: _query_int_column(source_engine, id_query),
        f"全量查询采样ID (rebate={target_rebate})",
    )
    elapsed = time.perf_counter() - start
    add_sampling_timing(timing, 'id_query_seconds', elapsed)
    check_cancelled()
    print_sampling_detail(
        f"从 {source_db_name} 全量查询到 {len(ids)} 个符合条件的ID "
        f"(rebate={target_rebate})，耗时 {elapsed:.2f} 秒"
    )

    sampled_ids = _sample_ids_from_candidates(ids, sample_size, random_seed)
    if len(ids) > sample_size:
        print_sampling_detail(f"随机抽取 {sample_size} 个ID")
    else:
        print_sampling_detail(f"ID数量不足，使用全部 {len(sampled_ids)} 个ID")
    return sampled_ids


def _query_limited_distinct_ids(source_engine, source_table_ref, where_clause, target_rebate, limit, *, timing=None):
    start = time.perf_counter()
    query = f"""
    SELECT DISTINCT `id`
    FROM {source_table_ref}
    WHERE {where_clause}
    LIMIT {int(limit)}
    """
    ids = sql_with_retry(
        lambda: _query_int_column(source_engine, query),
        f"稀疏rebate探测 (rebate={target_rebate})",
    )
    elapsed = time.perf_counter() - start
    add_sampling_timing(timing, 'id_query_seconds', elapsed)
    print_sampling_detail(
        f"稀疏rebate探测耗时：{elapsed:.2f} 秒，"
        f"最多检查 {int(limit)} 个，返回 {len(ids)} 个 (rebate={target_rebate})"
    )
    return ids


def _query_sample_id_range(source_engine, source_table_ref, where_clause, target_rebate, *, timing=None):
    start = time.perf_counter()
    range_query = f"""
    SELECT MIN(`id`) AS min_id, MAX(`id`) AS max_id
    FROM {source_table_ref}
    WHERE {where_clause}
    """
    range_row = sql_with_retry(
        lambda: _query_single_row(source_engine, range_query),
        f"查询采样ID范围 (rebate={target_rebate})",
    )
    elapsed = time.perf_counter() - start
    add_sampling_timing(timing, 'id_query_seconds', elapsed)
    if not range_row:
        print_sampling_detail(f"采样ID范围查询耗时：{elapsed:.2f} 秒，未查询到范围")
        return None, None
    min_id = range_row[0]
    max_id = range_row[1]
    if pd.isna(min_id) or pd.isna(max_id):
        print_sampling_detail(f"采样ID范围查询耗时：{elapsed:.2f} 秒，未查询到范围")
        return None, None
    min_id = int(min_id)
    max_id = int(max_id)
    print_sampling_detail(
        f"采样ID范围查询耗时：{elapsed:.2f} 秒，"
        f"rebate={target_rebate}, id范围={min_id}~{max_id}"
    )
    return min_id, max_id


def _random_range_attempt_limit(sample_size):
    sample_size = int(sample_size)
    if sample_size <= 200:
        return SAMPLE_ID_RANDOM_RANGE_ATTEMPTS
    if sample_size <= 1000:
        return 10
    if sample_size <= 5000:
        return 12
    if sample_size <= 20000:
        return 16
    return SAMPLE_ID_RANDOM_RANGE_MAX_ATTEMPTS


def _random_range_per_query_limit(sample_size, attempt):
    base_limit = max(int(sample_size) * 3, 500)
    scale = 1 + max(0, int(attempt) - SAMPLE_ID_RANDOM_RANGE_ATTEMPTS) // 4
    return min(base_limit * scale, SAMPLE_ID_RANDOM_RANGE_MAX_CANDIDATES_PER_QUERY)


def _query_candidate_ids_from_random_ranges(
    *,
    source_engine,
    source_table_ref,
    where_clause,
    target_rebate,
    sample_size,
    random_seed,
    min_id,
    max_id,
    timing=None,
):
    if sample_size <= 0 or min_id is None or max_id is None:
        return []

    rng = random.Random(f"{random_seed}:{target_rebate}:{sample_size}")
    attempt_limit = _random_range_attempt_limit(sample_size)
    candidate_ids = set()
    returned_total = 0
    duplicate_total = 0
    total_start = time.perf_counter()

    for attempt in range(1, attempt_limit + 1):
        check_cancelled()
        start_id = rng.randint(int(min_id), int(max_id))
        per_query_limit = _random_range_per_query_limit(sample_size, attempt)
        query = f"""
        SELECT DISTINCT `id`
        FROM {source_table_ref}
        WHERE ({where_clause}) AND `id` >= {start_id}
        ORDER BY `id`
        LIMIT {per_query_limit}
        """
        start = time.perf_counter()
        ids = sql_with_retry(
            lambda: _query_int_column(source_engine, query),
            f"随机范围查询采样ID (rebate={target_rebate}, 第{attempt}次)",
        )
        elapsed = time.perf_counter() - start
        add_sampling_timing(timing, 'id_query_seconds', elapsed)
        before = len(candidate_ids)
        candidate_ids.update(ids)
        added = len(candidate_ids) - before
        duplicates = max(len(ids) - added, 0)
        returned_total += len(ids)
        duplicate_total += duplicates
        add_sampling_counter(timing, 'random_range_attempts')
        add_sampling_counter(timing, 'random_range_returned_ids', len(ids))
        add_sampling_counter(timing, 'random_range_added_ids', added)
        add_sampling_counter(timing, 'random_range_duplicate_ids', duplicates)
        print_sampling_detail(
            f"  随机范围第 {attempt}/{attempt_limit} 次："
            f"起点id={start_id}，返回 {len(ids)} 个，新增 {added} 个，"
            f"重复 {duplicates} 个，累计 {len(candidate_ids)} 个，"
            f"limit={per_query_limit}，耗时 {elapsed:.2f} 秒"
        )
        if len(candidate_ids) >= sample_size:
            break

    added_total = len(candidate_ids)
    hit_rate = (added_total / returned_total * 100.0) if returned_total else 0.0
    print_sampling_detail(
        f"随机范围候选ID查询总耗时：{time.perf_counter() - total_start:.2f} 秒，"
        f"返回 {returned_total} 个，候选 {added_total} 个，"
        f"重复 {duplicate_total} 个，新增率 {hit_rate:.1f}%"
    )
    return list(candidate_ids)


def select_sample_ids_for_rebate(
    *,
    source_engine,
    source_db_name,
    source_table_ref,
    sample_conditions,
    target_rebate,
    sample_size,
    timing=None,
):
    """Query and sample ids for one rebate, preferring random id-range probes."""
    sample_size = int(sample_size)
    if sample_size <= 0:
        return []

    total_start = time.perf_counter()
    where_clause = sample_conditions['where_clause'].format(target_rebate=target_rebate)
    random_seed = sample_conditions['random_seed']

    sparse_probe_ids = _query_limited_distinct_ids(
        source_engine,
        source_table_ref,
        where_clause,
        target_rebate,
        sample_size + 1,
        timing=timing,
    )
    if len(sparse_probe_ids) <= sample_size:
        add_sampling_counter(timing, 'sparse_shortcut_count')
        print_sampling_detail(
            f"rebate={target_rebate} 可用ID数量不超过采样数，"
            f"直接使用全部 {len(sparse_probe_ids)} 个ID"
        )
        print_sampling_detail(
            f"采样ID选择总耗时：{time.perf_counter() - total_start:.2f} 秒 (rebate={target_rebate})"
        )
        return _sample_ids_from_candidates(sparse_probe_ids, sample_size, random_seed)

    min_id, max_id = _query_sample_id_range(
        source_engine,
        source_table_ref,
        where_clause,
        target_rebate,
        timing=timing,
    )
    candidate_ids = _query_candidate_ids_from_random_ranges(
        source_engine=source_engine,
        source_table_ref=source_table_ref,
        where_clause=where_clause,
        target_rebate=target_rebate,
        sample_size=sample_size,
        random_seed=random_seed,
        min_id=min_id,
        max_id=max_id,
        timing=timing,
    )

    if len(candidate_ids) < sample_size:
        print(
            f"随机范围候选ID不足：需要 {sample_size} 个，当前 {len(candidate_ids)} 个；"
            "回退到全量 DISTINCT id 查询"
        )
        sampled_ids = _select_sample_ids_with_full_scan(
            source_engine=source_engine,
            source_db_name=source_db_name,
            source_table_ref=source_table_ref,
            where_clause=where_clause,
            target_rebate=target_rebate,
            sample_size=sample_size,
            random_seed=random_seed,
            timing=timing,
        )
    else:
        sampled_ids = _sample_ids_from_candidates(candidate_ids, sample_size, random_seed)
        print_sampling_detail(
            f"从 {source_db_name} 随机范围候选 {len(candidate_ids)} 个ID中"
            f"抽取 {len(sampled_ids)} 个 (rebate={target_rebate})"
        )

    print_sampling_detail(f"采样ID选择总耗时：{time.perf_counter() - total_start:.2f} 秒 (rebate={target_rebate})")
    return [int(value) for value in sampled_ids]


def _format_sampled_id_preview(ids, limit=10):
    ids = list(ids)
    preview = ', '.join(str(value) for value in ids[:limit])
    if len(ids) > limit:
        preview += ', ...'
    return f"[{preview}]"


def _query_sampled_end_counts(source_engine, source_table_ref, end_field_ref, id_batch):
    id_text = ','.join(str(int(value)) for value in id_batch)
    query = f"""
    SELECT `id`, COUNT(CASE WHEN {end_field_ref}=1 THEN 1 END) AS end_cnt
    FROM {source_table_ref}
    WHERE `id` IN ({id_text})
    GROUP BY `id`
    """
    with source_engine.connect() as conn:
        result = conn.exec_driver_sql(query)
        return [
            {'id': int(row[0]), 'end_cnt': int(row[1] or 0)}
            for row in result
        ]


def validate_sampled_ids_end_field_integrity(
    source_engine,
    source_table_ref,
    source_table_name,
    end_field,
    sampled_ids,
    *,
    target_rebate=None,
):
    """校验已采样 id 下 end_field=1 的行数是否恰好为 1。"""
    if not end_field:
        return
    expected_ids = sorted({int(value) for value in sampled_ids})
    expected_id_set = set(expected_ids)
    if not expected_ids:
        return

    total_start = time.perf_counter()
    end_field_ref = quote_identifier(end_field, "结束字段名")
    label_suffix = f" (rebate={target_rebate})" if target_rebate is not None else ""
    print_sampling_detail(
        f"  按已采样ID校验 {source_table_name} 数据完整性："
        f"id数={len(expected_ids)}，字段={end_field}{label_suffix}"
    )

    no_end = []
    multi_end = []
    seen_ids = set()
    for id_batch in chunked(expected_ids, SAMPLE_ID_FETCH_CHUNK_SIZE):
        check_cancelled()
        rows = sql_with_retry(
            lambda batch=tuple(id_batch): _query_sampled_end_counts(
                source_engine,
                source_table_ref,
                end_field_ref,
                batch,
            ),
            f"校验采样ID结束行{label_suffix}",
        )
        for row in rows:
            source_id = int(row['id'])
            if source_id not in expected_id_set:
                continue
            seen_ids.add(source_id)
            end_count = int(row.get('end_cnt') or 0)
            if end_count == 0:
                no_end.append(source_id)
            elif end_count > 1:
                multi_end.append(source_id)

    missing_ids = sorted(expected_id_set - seen_ids)
    no_end.extend(missing_ids)
    if no_end or multi_end:
        lines = [
            f"数据完整性校验失败（表：{source_table_name}，字段：{end_field}，仅检查已采样ID）："
        ]
        if multi_end:
            lines.append(
                f"  存在多条 {end_field}=1 的 id 共 {len(multi_end)} 个："
                f"{_format_sampled_id_preview(multi_end)}"
            )
        if no_end:
            lines.append(
                f"  缺少 {end_field}=1 的 id 共 {len(no_end)} 个："
                f"{_format_sampled_id_preview(no_end)}"
            )
        raise ValueError('\n'.join(lines))

    print_sampling_detail(
        f"  已采样ID完整性校验通过：{len(expected_ids)} 个 id，"
        f"耗时 {time.perf_counter() - total_start:.2f} 秒{label_suffix}"
    )


def read_sample_rows_by_ids(source_engine, source_table_ref, id_batch, target_rebate, *, timing=None):
    """按 id 读取源表全部行（不叠加采样条件，确保取到一个 id 下的所有数据）。"""
    id_text = ','.join(str(int(value)) for value in id_batch)
    query = f"""
    SELECT *
    FROM {source_table_ref}
    WHERE `id` IN ({id_text})
    """
    start = time.perf_counter()
    df = sql_with_retry(
        lambda: pd.read_sql_query(query, source_engine),
        f"提取采样数据 (rebate={target_rebate})",
    )
    elapsed = time.perf_counter() - start
    add_sampling_timing(timing, 'row_read_seconds', elapsed)
    print_sampling_detail(
        f"读取完整采样行耗时：{elapsed:.2f} 秒，"
        f"id数={len(id_batch)}，行数={len(df)} (rebate={target_rebate})"
    )
    return df


def validate_sample_rows_have_game_id_zero(
    current_df,
    expected_ids,
    source_table_name,
    *,
    required=False,
    target_rebate=None,
):
    """免费局类数据必须包含每个已采样 id 的 game_id=0 起始局。"""
    if not required:
        return
    required_columns = {'id', 'game_id'}
    missing_columns = sorted(required_columns - set(current_df.columns))
    if missing_columns:
        raise ValueError(
            f"数据完整性校验失败（表：{source_table_name}）："
            f"缺少字段 {', '.join(missing_columns)}，无法检查 game_id=0"
        )

    expected_id_set = {int(value) for value in expected_ids}
    id_values = pd.to_numeric(current_df['id'], errors='coerce')
    game_id_values = pd.to_numeric(current_df['game_id'], errors='coerce')
    ids_with_game_zero = {
        int(value)
        for value in id_values[game_id_values.eq(0)].dropna().unique()
    }
    missing_game_zero = sorted(expected_id_set - ids_with_game_zero)
    if not missing_game_zero:
        return

    label_suffix = f"，rebate={target_rebate}" if target_rebate is not None else ""
    raise ValueError(
        f"数据完整性校验失败（表：{source_table_name}{label_suffix}）："
        f"已采样 id 中有 {len(missing_game_zero)} 个缺少 game_id=0 起始局："
        f"{_format_sampled_id_preview(missing_game_zero)}。"
        "这些行在源表中已经缺失，本次未写入中转表。"
    )


def format_changed_pairs_preview(changed_pairs, limit=8):
    preview = ', '.join(f"{old}->{new}" for old, new in changed_pairs[:limit])
    if len(changed_pairs) > limit:
        preview += ', ...'
    return preview


def remap_sample_ids_to_append_sequence(current_df, *, id_mapping, next_id_state):
    """追加模式下给本次采样的 id 整组分配新 id，接在旧数据之后。"""
    if 'id' not in current_df.columns:
        raise ValueError("追加写入模式要求源表包含 id 字段")

    source_ids = sorted(int(value) for value in current_df['id'].dropna().unique())
    if not source_ids:
        return current_df, 0, 0, []

    assigned_pairs = []
    next_id = int(next_id_state[0])
    for source_id in source_ids:
        if source_id in id_mapping:
            continue
        id_mapping[source_id] = next_id
        assigned_pairs.append((source_id, next_id))
        next_id += 1
    next_id_state[0] = next_id

    remapped_df = current_df.copy()
    remapped_df['id'] = remapped_df['id'].map(lambda value: id_mapping[int(value)])
    changed_row_count = int(remapped_df['id'].ne(current_df['id']).sum())
    return remapped_df, len(assigned_pairs), changed_row_count, assigned_pairs


def remap_sample_chunk_for_append_mode(
    current_df,
    *,
    final_conn,
    final_db_name,
    staging_table_name,
    id_mapping,
    next_id_state,
):
    """追加模式下处理单个采样块的 id 重排。"""
    current_df, changed_pair_count, changed_row_count, changed_pairs = remap_sample_ids_to_append_sequence(
        current_df,
        id_mapping=id_mapping,
        next_id_state=next_id_state,
    )
    if changed_pairs:
        print(
            f"追加模式：为 {changed_pair_count} 个采样 id 分配新 id，"
            f"已改写 {changed_row_count} 行：{format_changed_pairs_preview(changed_pairs)}"
        )
    return current_df, changed_pair_count, changed_row_count, final_conn


def _format_write_context(target_rebate=None, log_context=None):
    if log_context:
        return str(log_context)
    return f"rebate={target_rebate}"


def _make_sample_row_write_method(
    total_rows,
    target_rebate,
    chunk_size=None,
    *,
    log_context=None,
    table_label="临时表",
):
    if chunk_size is None:
        chunk_size = globals().get('SAMPLE_ROW_WRITE_CHUNK_SIZE', 1)
    chunk_size = max(1, int(chunk_size))
    total_batches = max(1, (int(total_rows) + chunk_size - 1) // chunk_size)
    context_text = _format_write_context(target_rebate, log_context)
    state = {
        'batch_index': 0,
        'written_rows': 0,
    }

    def write_method(table, conn, keys, data_iter):
        rows = [dict(zip(keys, row)) for row in data_iter]
        if not rows:
            return 0

        state['batch_index'] += 1
        batch_index = state['batch_index']
        before_rows = state['written_rows']
        print_sampling_detail(
            f"  开始写入{table_label}批次 {batch_index}/{total_batches}："
            f"本批 {len(rows)} 行，已完成 {before_rows}/{total_rows} ({context_text})"
        )
        start = time.perf_counter()
        result = conn.execute(table.table.insert(), rows)
        elapsed = time.perf_counter() - start
        state['written_rows'] += len(rows)
        print_sampling_detail(
            f"  完成写入{table_label}批次 {batch_index}/{total_batches}："
            f"本批 {len(rows)} 行，累计 {state['written_rows']}/{total_rows}，耗时 {elapsed:.2f} 秒 "
            f"({context_text})"
        )
        check_cancelled()
        rowcount = getattr(result, 'rowcount', None)
        if isinstance(rowcount, int) and rowcount >= 0:
            return rowcount
        return len(rows)

    return write_method


def _dispose_engine_safely(engine):
    with contextlib.suppress(Exception):
        engine.dispose()


def _next_sample_row_write_chunk_size(chunk_size):
    chunk_size = max(1, int(chunk_size))
    if chunk_size > 20:
        return 20
    if chunk_size > 5:
        return 5
    if chunk_size > 1:
        return 1
    return 1


def _write_dataframe_to_staging_once(
    current_df,
    final_engine,
    staging_table_name,
    target_rebate,
    chunk_size,
    *,
    log_context=None,
    table_label="临时表",
):
    row_count = len(current_df)
    chunk_size = max(1, int(chunk_size))
    with final_engine.begin() as conn:
        current_df.to_sql(
            staging_table_name,
            conn,
            if_exists='append',
            index=False,
            chunksize=chunk_size,
            method=_make_sample_row_write_method(
                row_count,
                target_rebate,
                chunk_size,
                log_context=log_context,
                table_label=table_label,
            ),
        )


def write_dataframe_to_staging_with_retry(
    current_df,
    final_engine,
    staging_table_name,
    target_rebate=None,
    *,
    operation_label=None,
    log_context=None,
    table_label="临时表",
):
    label = operation_label or f"写入数据 (rebate={target_rebate})"
    max_retries = int(globals().get('MAX_DB_RETRIES', 1) or 1)
    retry_delay = int(globals().get('DB_RETRY_DELAY', 0) or 0)
    chunk_size = max(1, int(globals().get('SAMPLE_ROW_WRITE_CHUNK_SIZE', 1) or 1))
    for attempt in range(1, max_retries + 1):
        check_cancelled()
        try:
            _write_dataframe_to_staging_once(
                current_df,
                final_engine,
                staging_table_name,
                target_rebate,
                chunk_size,
                log_context=log_context,
                table_label=table_label,
            )
            if attempt > 1:
                print(f"{label} 第{attempt}次重试成功")
            return
        except Exception as e:
            print(f"{label}失败 (第{attempt}次): {e}")
            _dispose_engine_safely(final_engine)
            if attempt < max_retries:
                next_chunk_size = _next_sample_row_write_chunk_size(chunk_size)
                chunk_note = (
                    f"下次写入批次降为 {next_chunk_size}，"
                    if next_chunk_size < chunk_size
                    else ""
                )
                chunk_size = next_chunk_size
                print(f"已回滚并重建写入连接，{chunk_note}等待{retry_delay}秒后重试...")
                interruptible_sleep(retry_delay)
            else:
                raise


def write_sample_chunk_to_staging(
    current_df,
    final_engine,
    staging_table_name,
    target_rebate,
    *,
    timing=None,
    table_label="临时表",
):
    start = time.perf_counter()
    row_count = len(current_df)
    total_batches = max(1, (row_count + SAMPLE_ROW_WRITE_CHUNK_SIZE - 1) // SAMPLE_ROW_WRITE_CHUNK_SIZE)
    print_sampling_detail(
        f"准备写入临时表：行数={row_count}，"
        f"批次={total_batches}，每批最多 {SAMPLE_ROW_WRITE_CHUNK_SIZE} 行 (rebate={target_rebate})"
    )
    write_dataframe_to_staging_with_retry(
        current_df,
        final_engine,
        staging_table_name,
        target_rebate,
        table_label=table_label,
    )
    elapsed = time.perf_counter() - start
    add_sampling_timing(timing, 'row_write_seconds', elapsed)
    print_sampling_detail(
        f"写入临时表耗时：{elapsed:.2f} 秒，"
        f"行数={len(current_df)} (rebate={target_rebate})"
    )


def copy_table_between_engines(source_engine, target_engine, source_table_name, target_table_name, *, label):
    source_ref = quote_identifier(source_table_name, "复制源表名")
    query = f"SELECT * FROM {source_ref}"
    copied_rows = 0
    chunk_index = 0
    print(f"{label}：开始分块复制 {source_table_name} -> {target_table_name}")
    for chunk in pd.read_sql_query(query, source_engine, chunksize=SAMPLE_TABLE_COPY_CHUNK_SIZE):
        check_cancelled()
        chunk_index += 1
        if chunk.empty:
            continue
        write_dataframe_to_staging_with_retry(
            chunk,
            target_engine,
            target_table_name,
            operation_label=f"{label}：写入复制分块 {chunk_index}",
            log_context=f"{label}，复制分块 {chunk_index}",
            table_label="目标表",
        )
        copied_rows += len(chunk)
        print_sampling_detail(f"{label}：已复制 {copied_rows} 行")
    print(f"{label}：完成复制 {copied_rows} 行")
    return copied_rows


def find_mysql_cli_executable(executable_name):
    """Find mysql/mysqldump without requiring users to type the full path."""
    names = [executable_name]
    if not executable_name.lower().endswith('.exe'):
        names.append(f"{executable_name}.exe")

    candidates = []
    for name in names:
        found = shutil.which(name)
        if found:
            candidates.append(found)

    for env_key in ('ProgramFiles', 'ProgramFiles(x86)'):
        base_dir = os.environ.get(env_key)
        if not base_dir:
            continue
        for version in ('8.4', '8.0', '5.7'):
            for name in names:
                candidates.append(os.path.join(base_dir, 'MySQL', f'MySQL Server {version}', 'bin', name))

    for path in candidates:
        if path and os.path.exists(path):
            return path
    raise RuntimeError(f"未找到 {executable_name}，请确认 MySQL Client 已安装并加入 PATH")


def mysql_cli_env(db_config):
    env = os.environ.copy()
    password = db_config.get('password')
    if password:
        env['MYSQL_PWD'] = str(password)
    return env


def mysql_cli_common_args(executable_path, db_config):
    return [
        executable_path,
        f"--host={db_config['host']}",
        f"--port={int(db_config['port'])}",
        f"--user={db_config['user']}",
        "--protocol=TCP",
        "--default-character-set=utf8mb4",
    ]


def decode_cli_output(value):
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode('utf-8', errors='replace').strip()
    return str(value).strip()


def run_mysql_cli_command(args, *, env, label, input_path=None):
    input_file = None
    try:
        if input_path:
            input_file = open(input_path, 'rb')
        completed = subprocess.run(
            args,
            stdin=input_file,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            check=False,
        )
    finally:
        if input_file is not None:
            input_file.close()

    if completed.returncode != 0:
        stdout_text = decode_cli_output(completed.stdout)
        stderr_text = decode_cli_output(completed.stderr)
        detail = stderr_text or stdout_text or "无错误输出"
        raise RuntimeError(f"{label}失败，退出码 {completed.returncode}：{detail[-2000:]}")
    return completed


def dump_mysql_table_data(source_db_config, source_table_name, dump_path, *, label):
    mysqldump_path = find_mysql_cli_executable('mysqldump')
    args = mysql_cli_common_args(mysqldump_path, source_db_config) + [
        "--column-statistics=0",
        "--single-transaction",
        "--quick",
        "--skip-lock-tables",
        "--no-create-info",
        "--skip-triggers",
        "--skip-add-locks",
        "--skip-comments",
        "--compact",
        "--hex-blob",
        f"--result-file={dump_path}",
        source_db_config['database'],
        source_table_name,
    ]
    env = mysql_cli_env(source_db_config)
    try:
        return run_mysql_cli_command(args, env=env, label=label)
    except RuntimeError as exc:
        if "column-statistics" not in str(exc):
            raise
        retry_args = [arg for arg in args if arg != "--column-statistics=0"]
        return run_mysql_cli_command(retry_args, env=env, label=label)


def backticked_identifier_bytes(table_name):
    return f"`{table_name}`".encode('utf-8')


def rewrite_dump_table_name(dump_path, import_path, source_table_name, target_table_name):
    source_token = backticked_identifier_bytes(source_table_name)
    target_token = backticked_identifier_bytes(target_table_name)
    with open(dump_path, 'rb') as source_file, open(import_path, 'wb') as target_file:
        for line in source_file:
            target_file.write(line.replace(source_token, target_token))


def import_mysql_dump_file(target_db_config, import_path, *, label):
    mysql_path = find_mysql_cli_executable('mysql')
    args = mysql_cli_common_args(mysql_path, target_db_config) + [
        f"--database={target_db_config['database']}",
        "--binary-mode",
    ]
    return run_mysql_cli_command(
        args,
        env=mysql_cli_env(target_db_config),
        label=label,
        input_path=import_path,
    )


def dump_import_table_between_databases(
    source_db_config,
    target_db_config,
    source_table_name,
    target_table_name,
    *,
    label,
    reprepare_target=None,
):
    temp_dir = tempfile.mkdtemp(prefix='formation_mysql_dump_')
    dump_path = os.path.join(temp_dir, 'source.sql')
    import_path = os.path.join(temp_dir, 'target.sql')
    try:
        max_retries = max(1, int(globals().get('MYSQL_DUMP_IMPORT_RETRIES', MYSQL_DUMP_IMPORT_RETRIES) or 1))
        retry_delay = int(globals().get('DB_RETRY_DELAY', 0) or 0)
        for attempt in range(1, max_retries + 1):
            check_cancelled()
            try:
                with contextlib.suppress(Exception):
                    os.remove(dump_path)
                print(f"{label}：使用 mysqldump 导出 {source_table_name} (第 {attempt}/{max_retries} 次)")
                dump_mysql_table_data(
                    source_db_config,
                    source_table_name,
                    dump_path,
                    label=f"{label} dump导出",
                )
                if attempt > 1:
                    print(f"{label}：第 {attempt} 次重试导出成功")
                break
            except Exception as exc:
                if attempt >= max_retries:
                    raise
                print(f"{label}：dump导出失败 (第{attempt}次)：{exc}")
                print(f"等待{retry_delay}秒后重试...")
                interruptible_sleep(retry_delay)
        check_cancelled()
        rewrite_dump_table_name(dump_path, import_path, source_table_name, target_table_name)
        for attempt in range(1, max_retries + 1):
            check_cancelled()
            if attempt > 1 and callable(reprepare_target):
                reprepare_target()
            try:
                print(f"{label}：导入到目标临时表 {target_table_name} (第 {attempt}/{max_retries} 次)")
                import_mysql_dump_file(
                    target_db_config,
                    import_path,
                    label=f"{label} dump导入",
                )
                if attempt > 1:
                    print(f"{label}：第 {attempt} 次重试导入成功")
                return True
            except Exception as exc:
                if attempt >= max_retries:
                    raise
                print(f"{label}：dump导入失败 (第{attempt}次)：{exc}")
                print(f"等待{retry_delay}秒后重试...")
                interruptible_sleep(retry_delay)
        return False
    finally:
        with contextlib.suppress(Exception):
            shutil.rmtree(temp_dir)


def fetch_and_write_sample_rows_in_chunks(
    sampled_ids,
    *,
    source_engine,
    final_engine,
    final_conn,
    final_db_name,
    staging_table_name,
    source_db_name,
    source_table_ref,
    target_rebate,
    append_mode,
    id_mapping,
    next_id_state,
    increment_engine=None,
    increment_staging_table_name=None,
    require_game_id_zero=False,
    timing=None,
):
    """分块提取采样行并写入临时表，避免超长 IN 查询和过大 DataFrame。"""
    total_start = time.perf_counter()
    totals = {'row_count': 0, 'changed_pair_count': 0, 'changed_row_count': 0}
    batches = list(chunked(sampled_ids, SAMPLE_ID_FETCH_CHUNK_SIZE))
    if len(batches) > 1:
        print_sampling_detail(f"采样ID较多，将按 {SAMPLE_ID_FETCH_CHUNK_SIZE} 个ID/批分 {len(batches)} 批提取写入")

    for batch_index, id_batch in enumerate(batches, start=1):
        check_cancelled()
        current_df = read_sample_rows_by_ids(
            source_engine,
            source_table_ref,
            id_batch,
            target_rebate,
            timing=timing,
        )
        check_cancelled()
        if current_df.empty:
            print(f"  第 {batch_index}/{len(batches)} 批未提取到数据，跳过")
            continue

        validate_sample_rows_have_game_id_zero(
            current_df,
            id_batch,
            source_table_ref,
            required=require_game_id_zero,
            target_rebate=target_rebate,
        )

        if append_mode:
            start = time.perf_counter()
            current_df, changed_pair_count, changed_row_count, final_conn = remap_sample_chunk_for_append_mode(
                current_df,
                final_conn=final_conn,
                final_db_name=final_db_name,
                staging_table_name=staging_table_name,
                id_mapping=id_mapping,
                next_id_state=next_id_state,
            )
            elapsed = time.perf_counter() - start
            add_sampling_timing(timing, 'id_remap_seconds', elapsed)
            print_sampling_detail(
                f"追加模式id冲突处理耗时：{elapsed:.2f} 秒，"
                f"冲突id={changed_pair_count}，改写行={changed_row_count}"
            )
            totals['changed_pair_count'] += changed_pair_count
            totals['changed_row_count'] += changed_row_count

        write_sample_chunk_to_staging(
            current_df,
            final_engine,
            staging_table_name,
            target_rebate,
            timing=timing,
        )
        if increment_engine is not None and increment_staging_table_name:
            write_sample_chunk_to_staging(
                current_df,
                increment_engine,
                increment_staging_table_name,
                target_rebate,
                timing=timing,
                table_label="增量临时表",
            )
        totals['row_count'] += len(current_df)
        if append_mode:
            final_conn = refresh_connection_read_view(final_conn, final_db_name, "目标库")
        if len(batches) > 1:
            print_sampling_detail(f"  第 {batch_index}/{len(batches)} 批写入 {len(current_df)} 条，累计 {totals['row_count']} 条")

    print_sampling_detail(f"从 {source_db_name} 提取到 {totals['row_count']} 条数据")
    print_sampling_detail(f"采样行读取+写入总耗时：{time.perf_counter() - total_start:.2f} 秒 (rebate={target_rebate})")
    return totals, final_conn


def sample_rebate_to_staging(
    row,
    *,
    source_engine,
    final_engine,
    final_conn,
    final_db_name,
    staging_table_name,
    source_db_name,
    source_table_name,
    sample_conditions,
    append_mode,
    id_mapping,
    next_id_state,
    increment_engine=None,
    increment_staging_table_name=None,
    timing=None,
):
    """按一条 rebate_count 配置采样并写入临时目标表。"""
    total_start = time.perf_counter()
    target_rebate = row['rebate']
    sample_size = int(row['count'])
    timing_before = snapshot_sampling_timing(timing)

    print_sampling_detail(f"\n处理 rebate={target_rebate}, 采样数量={sample_size}...")
    print_sampling_detail(get_sample_description(target_rebate, sample_conditions))
    source_table_ref = quote_identifier(source_table_name, "源表名")
    validate_sql_identifier(staging_table_name, "临时目标表名")

    sampled_ids = select_sample_ids_for_rebate(
        source_engine=source_engine,
        source_db_name=source_db_name,
        source_table_ref=source_table_ref,
        sample_conditions=sample_conditions,
        target_rebate=target_rebate,
        sample_size=sample_size,
        timing=timing,
    )
    if not sampled_ids:
        print(f"没有找到 rebate={target_rebate} 的数据")
        record_rebate_timing(timing, total_start, target_rebate=target_rebate, before=timing_before)
        return 0, 0, 0, final_conn

    validate_sampled_ids_end_field_integrity(
        source_engine,
        source_table_ref,
        source_table_name,
        sample_conditions.get('end_field_for_validation'),
        sampled_ids,
        target_rebate=target_rebate,
    )

    totals, final_conn = fetch_and_write_sample_rows_in_chunks(
        sampled_ids,
        source_engine=source_engine,
        final_engine=final_engine,
        final_conn=final_conn,
        final_db_name=final_db_name,
        staging_table_name=staging_table_name,
        source_db_name=source_db_name,
        source_table_ref=source_table_ref,
        target_rebate=target_rebate,
        append_mode=append_mode,
        id_mapping=id_mapping,
        next_id_state=next_id_state,
        increment_engine=increment_engine,
        increment_staging_table_name=increment_staging_table_name,
        require_game_id_zero=sample_conditions.get('require_game_id_zero_for_validation', False),
        timing=timing,
    )
    if totals['row_count'] <= 0:
        print(f"没有提取到 rebate={target_rebate} 的数据")
        record_rebate_timing(timing, total_start, target_rebate=target_rebate, before=timing_before)
        return 0, totals['changed_pair_count'], totals['changed_row_count'], final_conn

    print_sampling_detail(
        f"rebate={target_rebate} 完成：采样ID {len(sampled_ids)}/{sample_size}，"
        f"写入 {totals['row_count']} 行，耗时 {time.perf_counter() - total_start:.2f} 秒"
    )
    record_rebate_timing(
        timing,
        total_start,
        totals['row_count'],
        target_rebate=target_rebate,
        before=timing_before,
    )
    return totals['row_count'], totals['changed_pair_count'], totals['changed_row_count'], final_conn


def get_direct_sampling_names(table_config):
    """汇总直接采样流程使用到的库名和表名。"""
    final_db_name = get_table_database('FINAL_TABLE', table_config)
    staging_db_name = get_sampling_staging_db_name(final_db_name)
    return {
        'source_db_name': get_table_database('SOURCE_TABLE', table_config),
        'final_db_name': final_db_name,
        'staging_db_name': staging_db_name,
        'increment_db_name': get_sampling_increment_db_name(),
        'config_db_name': get_table_database('REBATE_CONFIG_TABLE', table_config),
        'source_table_name': get_table_name('SOURCE_TABLE', table_config),
        'final_table_name': get_table_name('FINAL_TABLE', table_config),
        'rebate_config_table_name': get_table_name('REBATE_CONFIG_TABLE', table_config),
    }


def get_sampling_increment_db_name():
    return str(globals().get('SAMPLING_INCREMENT_DB') or '').strip()


def get_sampling_staging_db_name(final_db_name):
    if bool(globals().get('SAMPLING_USE_TEMP_DB', False)):
        return str(globals().get('SAMPLING_TEMP_DB') or final_db_name)
    return final_db_name


def get_sampling_staging_table_config(table_config):
    staging_config = {
        key: dict(value) if isinstance(value, dict) else value
        for key, value in dict(table_config).items()
    }
    if 'FINAL_TABLE' in staging_config:
        staging_config['FINAL_TABLE'] = dict(staging_config['FINAL_TABLE'])
        staging_config['FINAL_TABLE']['database'] = get_sampling_staging_db_name(
            staging_config['FINAL_TABLE'].get('database')
        )
    return staging_config


def get_sampling_increment_table_config(table_config):
    increment_db_name = get_sampling_increment_db_name()
    if not increment_db_name:
        return None
    return get_table_config_with_final_database(table_config, increment_db_name)


def get_table_config_with_final_database(table_config, database):
    updated = {
        key: dict(value) if isinstance(value, dict) else value
        for key, value in dict(table_config).items()
    }
    if 'FINAL_TABLE' in updated:
        updated['FINAL_TABLE'] = dict(updated['FINAL_TABLE'])
        updated['FINAL_TABLE']['database'] = database
    return updated


def get_table_column_names(conn, table_name):
    columns = get_table_columns(conn, table_name)
    if columns is None:
        return None
    return [str(column[0]) for column in columns]


def build_append_structure_mismatch_message(
    source_db_name,
    source_table_name,
    final_db_name,
    final_table_name,
    comparison,
):
    lines = [
        "补充采样已停止，源表与旧目标表的字段结构不兼容。",
        f"源表：{source_db_name}.{source_table_name}",
        f"旧目标表：{final_db_name}.{final_table_name}",
    ]
    if comparison.get('unreadable'):
        lines.append("无法读取其中一张表的字段结构，请检查表是否存在及 DESCRIBE 权限。")
    missing = comparison.get('missing_in_target') or []
    extra = comparison.get('extra_in_target') or []
    mismatches = comparison.get('type_mismatches') or []
    if missing:
        lines.append(f"旧目标表缺少字段：{', '.join(missing)}")
    if extra:
        lines.append(f"旧目标表多出字段：{', '.join(extra)}")
    if mismatches:
        lines.append("基础类型不一致：")
        lines.extend(
            f"  {item['field']}：源表={item['source_type']}，旧目标表={item['target_type']}"
            for item in mismatches
        )
    if comparison.get('order_mismatch'):
        lines.append("字段顺序不一致。")
    lines.append("字段长度、Null 和 Extra 属性不会参与本项兼容判断。")
    lines.append("正式表未替换，请先修正旧目标表字段后再执行补充采样。")
    return '\n'.join(lines)


def get_table_game_id_zero_stats(conn, table_name, columns=None):
    """Return game_id=0 row/id counts, or None when the table has no game_id."""
    columns = columns if columns is not None else get_table_column_names(conn, table_name)
    normalized_columns = {str(column).lower() for column in (columns or [])}
    if 'game_id' not in normalized_columns:
        return None

    table_ref = quote_identifier(table_name, "game_id=0校验表名")
    distinct_id_expr = "COUNT(DISTINCT `id`)" if 'id' in normalized_columns else "0"
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*), {distinct_id_expr} "
            f"FROM {table_ref} WHERE `game_id` = 0"
        )
        row = cur.fetchone()
    return {
        'row_count': int((row or (0, 0))[0] or 0),
        'id_count': int((row or (0, 0))[1] or 0),
    }


def validate_game_id_zero_stats_preserved(expected, actual, operation_label):
    if expected is None:
        return
    if actual == expected:
        return
    expected = expected or {'row_count': 0, 'id_count': 0}
    actual = actual or {'row_count': 0, 'id_count': 0}
    raise RuntimeError(
        f"{operation_label}导致 game_id=0 数据数量不一致："
        f"处理前 {expected['row_count']} 行/{expected['id_count']} 个id，"
        f"处理后 {actual['row_count']} 行/{actual['id_count']} 个id；"
        "已停止补充采样，正式表未替换"
    )


def prepare_staging_table_like_source(staging_conn, source_conn, staging_table_config, staging_table_name):
    drop_table_if_exists(staging_conn, staging_table_name)
    create_table_like_source(
        staging_conn,
        source_conn,
        staging_table_config,
        staging_table_name,
    )
    staging_conn.commit()


def prepare_increment_sampling_staging(source_conn, increment_conn, table_config, names):
    increment_db_name = names.get('increment_db_name') or get_sampling_increment_db_name()
    if not increment_db_name:
        return None
    increment_table_name = names['final_table_name']
    increment_staging_table_name = make_staging_table_name(increment_table_name, 'increment_tmp')
    increment_table_config = get_table_config_with_final_database(table_config, increment_db_name)
    prepare_staging_table_like_source(
        increment_conn,
        source_conn,
        increment_table_config,
        increment_staging_table_name,
    )
    print(
        f"补充采样增量库已准备：本次新增数据将写入 {increment_db_name}.{increment_staging_table_name}，"
        f"成功后替换 {increment_db_name}.{increment_table_name}"
    )
    return {
        'increment_db_name': increment_db_name,
        'increment_table_name': increment_table_name,
        'increment_staging_table_name': increment_staging_table_name,
    }


def prepare_staging_table_like_existing(source_conn, source_table_name, target_conn, target_table_name):
    drop_table_if_exists(target_conn, target_table_name)
    create_table_like_existing(
        source_conn,
        source_table_name,
        target_conn,
        target_table_name,
    )
    target_conn.commit()


def copy_existing_final_table_to_append_staging(
    *,
    source_conn,
    final_target_conn,
    staging_conn,
    staging_table_config,
    staging_table_name,
    final_db_name,
    staging_db_name,
    final_table_name,
):
    if staging_db_name == final_db_name:
        copy_table_rows(staging_conn, final_table_name, staging_table_name)
        staging_conn.commit()
        return

    def reprepare_target():
        prepare_staging_table_like_existing(
            final_target_conn,
            final_table_name,
            staging_conn,
            staging_table_name,
        )

    dump_import_table_between_databases(
        get_db_config_by_name(final_db_name),
        get_db_config_by_name(staging_db_name),
        final_table_name,
        staging_table_name,
        label="复制旧目标表到采样临时库",
        reprepare_target=reprepare_target,
    )


def reject_same_physical_sampling_table(table_config, names):
    """拦截源表和目标表相同导致的误覆盖风险。"""
    if not is_same_physical_table(table_config):
        return False
    print(
        f"源表和目标表指向同一张物理表 {names['source_db_name']}.{names['source_table_name']}，"
        "为避免误覆盖源数据，采样终止。"
    )
    return True


def prepare_direct_sampling_staging(
    source_conn,
    final_conn,
    table_config,
    names,
    append_mode,
    *,
    final_target_conn=None,
    staging_table_config=None,
    final_engine=None,
    staging_engine=None,
):
    """创建直接采样临时表，并在追加模式下复制旧数据。"""
    final_db_name = names['final_db_name']
    staging_db_name = names.get('staging_db_name') or final_db_name
    final_table_name = names['final_table_name']
    source_table_name = names['source_table_name']
    final_target_conn = final_target_conn or final_conn
    staging_table_config = staging_table_config or table_config
    staging_table_name = None
    try:
        final_conn.ping(reconnect=True, attempts=MAX_DB_RETRIES, delay=DB_RETRY_DELAY)
        staging_table_name = make_staging_table_name(final_table_name, 'tmp')
        final_table_exists = table_exists_exact(final_target_conn, final_table_name)
        if append_mode and final_table_exists:
            append_structure_comparison = compare_table_structure_for_append(
                get_table_columns(source_conn, source_table_name),
                get_table_columns(final_target_conn, final_table_name),
            )
            if not append_structure_comparison['compatible']:
                message = build_append_structure_mismatch_message(
                    names['source_db_name'],
                    source_table_name,
                    final_db_name,
                    final_table_name,
                    append_structure_comparison,
                )
                print(message)
                raise SamplingFieldMismatchError(message)
            prepare_staging_table_like_existing(
                final_target_conn,
                final_table_name,
                final_conn,
                staging_table_name,
            )
        else:
            prepare_staging_table_like_source(
                final_conn,
                source_conn,
                staging_table_config,
                staging_table_name,
            )

        staging_state = {
            'staging_table_name': staging_table_name,
            'staging_db_name': staging_db_name,
            'base_existing_count': 0,
            'id_mapping': {},
            'next_id_state': [1],
        }
        if append_mode and final_table_exists:
            source_game_id_zero_stats = get_table_game_id_zero_stats(
                final_target_conn,
                final_table_name,
            )
            print(
                f"采样写入模式：补充采样。正在复制旧目标表 "
                f"{final_db_name}.{final_table_name} 到中转临时表 {staging_db_name}.{staging_table_name}..."
            )
            copy_existing_final_table_to_append_staging(
                source_conn=source_conn,
                final_target_conn=final_target_conn,
                staging_conn=final_conn,
                staging_table_config=staging_table_config,
                staging_table_name=staging_table_name,
                final_db_name=final_db_name,
                staging_db_name=staging_db_name,
                final_table_name=final_table_name,
            )
            staging_state['base_existing_count'] = count_table_rows(final_conn, staging_table_name)
            copied_game_id_zero_stats = get_table_game_id_zero_stats(final_conn, staging_table_name)
            validate_game_id_zero_stats_preserved(
                source_game_id_zero_stats,
                copied_game_id_zero_stats,
                "旧目标表复制到中转库",
            )
            if copied_game_id_zero_stats is not None:
                print(
                    "旧目标表 game_id=0 数据复制校验通过："
                    f"{copied_game_id_zero_stats['row_count']} 行/"
                    f"{copied_game_id_zero_stats['id_count']} 个id"
                )
            old_max_id = get_table_max_id(final_conn, staging_table_name)
            staging_state['next_id_state'][0] = int(old_max_id) + 1
            print(
                f"旧目标表复制完成：{staging_state['base_existing_count']} 行；"
                f"旧数据 id 保持不变，当前最大 id={old_max_id}；"
                f"新采样数据将从 id={staging_state['next_id_state'][0]} 起继续分配。"
            )
            return staging_state

        if append_mode:
            print(f"采样写入模式：补充采样；正式表 {final_db_name}.{final_table_name} 不存在，本次按新表写入。")
        elif final_table_exists:
            structure_text = (
                "结构一致"
                if same_table_structure(source_conn, final_target_conn, source_table_name, final_table_name)
                else "结构不同，将以源表结构替换"
            )
            print(
                f"采样写入模式：清空后写入。已创建临时目标表 {staging_db_name}.{staging_table_name}；"
                f"正式表 {final_table_name} 存在，{structure_text}，采样成功后整体替换。"
            )
        else:
            print(
                f"采样写入模式：清空后写入。已创建临时目标表 {staging_db_name}.{staging_table_name}；"
                f"正式表 {final_table_name} 不存在，采样成功后创建。"
            )
        return staging_state
    except Exception:
        if staging_table_name:
            with contextlib.suppress(Exception):
                drop_table_if_exists(final_conn, staging_table_name)
                final_conn.commit()
                print(f"临时目标表准备失败，已清理：{staging_table_name}")
        raise


def sample_config_rows_to_staging(
    config_df,
    *,
    names,
    sample_conditions,
    source_engine,
    final_engine,
    final_conn,
    staging_state,
    append_mode,
    task_state=None,
    initial_totals=None,
    increment_engine=None,
    increment_staging_table_name=None,
):
    """执行 rebate_count 采样循环并写入临时表。"""
    config_df = normalize_sampling_config_df(
        config_df,
        names.get('config_db_name'),
        names.get('rebate_config_table_name', 'rebate_count'),
    )
    totals = dict(initial_totals or {
        'sampled_count': 0,
        'remapped_id_count': 0,
        'remapped_row_count': 0,
    })
    timing = new_sampling_timing()
    completed_rebates = sampling_task_state.completed_rebate_set(task_state or {})
    config_rows = list(config_df[['rebate', 'count']].itertuples(index=False))
    total_requested_count = sum(int(row.count) for row in config_rows)
    print(
        f"采样配置汇总：rebate项 {len(config_rows)} 个，"
        f"count合计 {total_requested_count}，已完成 {len(completed_rebates)} 个"
    )
    for row_index, row in enumerate(config_rows, start=1):
        check_cancelled()
        target_rebate = int(row.rebate)
        if target_rebate in completed_rebates:
            print(f"跳过已完成的 rebate={target_rebate} ({row_index}/{len(config_rows)})，继续恢复采样")
            continue
        row_data = {
            'rebate': target_rebate,
            'count': int(row.count),
        }
        print(f"采样进度：{row_index}/{len(config_rows)}，rebate={target_rebate}")
        sampled_count, changed_pair_count, changed_row_count, final_conn = sample_rebate_to_staging(
            row_data,
            source_engine=source_engine,
            final_engine=final_engine,
            final_conn=final_conn,
            final_db_name=names.get('staging_db_name', names['final_db_name']),
            staging_table_name=staging_state['staging_table_name'],
            source_db_name=names['source_db_name'],
            source_table_name=names['source_table_name'],
            sample_conditions=sample_conditions,
            append_mode=append_mode,
            id_mapping=staging_state['id_mapping'],
            next_id_state=staging_state['next_id_state'],
            increment_engine=increment_engine,
            increment_staging_table_name=increment_staging_table_name,
            timing=timing,
        )
        totals['sampled_count'] += sampled_count
        totals['remapped_id_count'] += changed_pair_count
        totals['remapped_row_count'] += changed_row_count
        if task_state is not None:
            sampling_task_state.record_completed_rebate(
                task_state,
                staging_state,
                rebate=target_rebate,
                sample_size=row_data['count'],
                sampled_count=sampled_count,
                changed_pair_count=changed_pair_count,
                changed_row_count=changed_row_count,
            )
            completed_rebates.add(target_rebate)
    print_sampling_timing_summary(timing)
    return totals, final_conn


def build_sampling_task_identity(names, sample_conditions, append_mode):
    return sampling_task_state.build_sampling_identity(names, sample_conditions, append_mode)


def load_sampling_task_state(identity):
    state = sampling_task_state.load_state(identity)
    if not state or state.get('status') not in {'running', 'failed'}:
        return None
    return state


def start_sampling_task_state(identity, staging_state, config_df):
    state = sampling_task_state.new_state(
        identity,
        staging_state,
        config_row_count=len(config_df),
    )
    sampling_task_state.save_state(state)
    print(f"采样任务状态已记录：{state['_path']}")
    return state


def try_resume_direct_sampling_staging(final_conn, names, state):
    staging_state = sampling_task_state.build_staging_state_from_saved(state)
    staging_table_name = staging_state.get('staging_table_name')
    staging_db_name = staging_state.get('staging_db_name') or names.get('staging_db_name') or names['final_db_name']
    if staging_db_name != (names.get('staging_db_name') or names['final_db_name']):
        print(
            f"检测到历史采样状态，但临时库不匹配：状态={staging_db_name}，"
            f"当前={names.get('staging_db_name') or names['final_db_name']}，本次重新采样"
        )
        return None
    staging_state['staging_db_name'] = staging_db_name
    if not staging_table_name:
        print("检测到历史采样状态，但状态文件没有记录临时表，本次重新采样")
        return None

    final_conn = ensure_database_connection(final_conn, staging_db_name, "采样临时库")
    if not table_exists_exact(final_conn, staging_table_name):
        print(f"检测到历史采样状态，但临时表 {staging_db_name}.{staging_table_name} 不存在，本次重新采样")
        return None

    totals = sampling_task_state.totals_from_state(state)
    expected_count = staging_state['base_existing_count'] + totals['sampled_count']
    actual_count = count_table_rows(final_conn, staging_table_name)
    if actual_count != expected_count:
        print(
            f"检测到历史采样状态，但临时表行数不匹配：预期 {expected_count}，实际 {actual_count}，本次重新采样"
        )
        return None

    increment_db_name = staging_state.get('increment_db_name')
    increment_staging_table_name = staging_state.get('increment_staging_table_name')
    if names.get('increment_db_name') and increment_db_name and increment_staging_table_name:
        increment_conn = connect_to_database(increment_db_name)
        try:
            if not increment_conn:
                print(f"检测到历史采样状态，但无法连接增量库 {increment_db_name}，本次重新采样")
                return None
            if not table_exists_exact(increment_conn, increment_staging_table_name):
                print(
                    f"检测到历史采样状态，但增量临时表 "
                    f"{increment_db_name}.{increment_staging_table_name} 不存在，本次重新采样"
                )
                return None
            increment_count = count_table_rows(increment_conn, increment_staging_table_name)
            if increment_count != totals['sampled_count']:
                print(
                    f"检测到历史采样状态，但增量临时表行数不匹配：预期 {totals['sampled_count']}，"
                    f"实际 {increment_count}，本次重新采样"
                )
                return None
        finally:
            close_safely(increment_conn)

    completed_count = len(sampling_task_state.completed_rebate_set(state))
    print(
        f"检测到可恢复采样任务：临时表 {staging_db_name}.{staging_table_name}，"
        f"已完成 {completed_count} 个 rebate，已写入 {totals['sampled_count']} 行，将继续剩余采样"
    )
    return staging_state, totals


def mark_sampling_task_completed(task_state, success):
    sampling_task_state.mark_completed(task_state, success=success)


def mark_sampling_task_failed(task_state, error):
    sampling_task_state.mark_failed(task_state, error)


def finalize_direct_sampling_staging(
    final_conn,
    names,
    staging_state,
    totals,
    append_mode,
    *,
    source_conn=None,
    table_config=None,
    staging_conn=None,
    staging_engine=None,
    final_engine=None,
    increment_conn=None,
):
    """校验临时表写入数量，并用临时表替换正式表。"""
    final_db_name = names['final_db_name']
    staging_db_name = names.get('staging_db_name') or final_db_name
    final_table_name = names['final_table_name']
    staging_table_name = staging_state['staging_table_name']
    total_sampled_count = totals['sampled_count']
    base_existing_count = staging_state['base_existing_count']
    staging_conn = staging_conn or final_conn
    if total_sampled_count <= 0:
        target_db_name = staging_db_name if staging_db_name != final_db_name else final_db_name
        print(f"\n本次未采样到任何数据，目标表 {target_db_name}.{final_table_name} 未替换")
        drop_table_if_exists(staging_conn, staging_table_name)
        staging_conn.commit()
        staging_state['staging_table_name'] = None
        cleanup_increment_sampling_staging(staging_state, increment_conn=increment_conn)
        return False, final_conn

    print("\n采样循环已完成，正在校验临时表并准备替换正式表...")
    staging_conn = refresh_connection_read_view(staging_conn, staging_db_name, "采样临时库")
    staging_count = count_table_rows(staging_conn, staging_table_name)
    expected_staging_count = base_existing_count + total_sampled_count
    if staging_count != expected_staging_count:
        raise RuntimeError(f"临时目标表写入数量不一致：预期 {expected_staging_count}，实际 {staging_count}")
    if append_mode:
        print(
            f"\n追加采样写入临时表完成：旧数据 {base_existing_count} 条，"
            f"新增 {total_sampled_count} 条，临时表共 {staging_count} 条；"
            f"为新采样数据分配新 id {totals['remapped_id_count']} 个、改写 {totals['remapped_row_count']} 行。"
        )
    else:
        print(f"\n采样写入临时表完成：{staging_count} 条。")

    replace_staging_table_name = staging_table_name
    if staging_db_name != final_db_name:
        print(
            f"正在将采样临时表 {staging_db_name}.{staging_table_name} "
            f"转为临时库正式表 {staging_db_name}.{final_table_name}..."
        )
        replace_table_with_staging(
            staging_conn,
            staging_table_name,
            final_table_name,
            staging_db_name,
        )
        staging_state['staging_table_name'] = None
        staging_conn = refresh_connection_read_view(staging_conn, staging_db_name, "采样临时库")
        temp_final_count = count_table_rows(staging_conn, final_table_name)
        if temp_final_count != staging_count:
            raise RuntimeError(
                f"临时库正式表数量不一致：临时表 {staging_count}，正式表 {temp_final_count}"
            )
        print(
            f"采样处理完成！已写入临时库正式表 {staging_db_name}.{final_table_name}，"
            f"共 {temp_final_count} 条；目标库 {final_db_name}.{final_table_name} 尚未同步。"
        )
        finalize_increment_sampling_staging(
            staging_state,
            increment_conn=increment_conn,
            expected_rows=total_sampled_count,
        )
        return True, final_conn

    final_conn = ensure_database_connection(final_conn, final_db_name, "目标库")
    print(f"正在替换正式表 {final_db_name}.{final_table_name}...")
    replace_table_with_staging(
        final_conn,
        replace_staging_table_name,
        final_table_name,
        final_db_name,
    )
    staging_state['staging_table_name'] = None
    if staging_db_name != final_db_name:
        with contextlib.suppress(Exception):
            drop_table_if_exists(staging_conn, staging_table_name)
            staging_conn.commit()
    if append_mode:
        print(
            f"采样处理完成！保留旧数据 {base_existing_count} 条，"
            f"本次追加 {total_sampled_count} 条到 {final_db_name}.{final_table_name}"
        )
    else:
        print(f"采样处理完成！总共写入 {total_sampled_count} 条数据到 {final_db_name}.{final_table_name}")
    finalize_increment_sampling_staging(
        staging_state,
        increment_conn=increment_conn,
        expected_rows=total_sampled_count,
    )
    return True, final_conn


def finalize_increment_sampling_staging(staging_state, *, increment_conn=None, expected_rows=0):
    increment_db_name = staging_state.get('increment_db_name')
    increment_table_name = staging_state.get('increment_table_name')
    increment_staging_table_name = staging_state.get('increment_staging_table_name')
    if not increment_db_name or not increment_table_name or not increment_staging_table_name:
        return
    own_conn = None
    try:
        if increment_conn is None:
            own_conn = connect_to_database(increment_db_name)
            increment_conn = own_conn
        if not increment_conn:
            raise RuntimeError(f"无法连接增量库 {increment_db_name}")
        increment_conn = refresh_connection_read_view(increment_conn, increment_db_name, "增量库")
        increment_count = count_table_rows(increment_conn, increment_staging_table_name)
        if increment_count != int(expected_rows or 0):
            raise RuntimeError(
                f"增量临时表数量不一致：预期 {int(expected_rows or 0)}，实际 {increment_count}"
            )
        replace_table_with_staging(
            increment_conn,
            increment_staging_table_name,
            increment_table_name,
            increment_db_name,
        )
        staging_state['increment_staging_table_name'] = None
        print(f"补充采样增量数据已写入：{increment_db_name}.{increment_table_name}，共 {increment_count} 条")
    finally:
        if own_conn is not None:
            close_safely(own_conn)


def cleanup_increment_sampling_staging(staging_state, *, increment_conn=None):
    increment_db_name = staging_state.get('increment_db_name')
    increment_staging_table_name = staging_state.get('increment_staging_table_name')
    if not increment_db_name or not increment_staging_table_name:
        return
    own_conn = None
    try:
        if increment_conn is None:
            own_conn = connect_to_database(increment_db_name)
            increment_conn = own_conn
        if increment_conn:
            drop_table_if_exists(increment_conn, increment_staging_table_name)
            increment_conn.commit()
            staging_state['increment_staging_table_name'] = None
    finally:
        if own_conn is not None:
            close_safely(own_conn)


def create_table_like_existing(source_conn, source_table_name, target_conn, target_table_name):
    """Create an empty target table with the same structure as an existing source table."""
    source_ref = quote_identifier(source_table_name, "source table")
    target_ref = quote_identifier(target_table_name, "target table")
    with source_conn.cursor() as cur:
        cur.execute(f"SHOW CREATE TABLE {source_ref}")
        row = cur.fetchone()
    if not row:
        raise RuntimeError(f"source table does not exist or cannot read structure: {source_table_name}")
    create_sql = re.sub(
        r'^CREATE TABLE `[^`]+`',
        f'CREATE TABLE {target_ref}',
        row[1],
        count=1,
        flags=re.IGNORECASE,
    )
    with target_conn.cursor() as cur:
        cur.execute(create_sql)


def sync_sampling_temp_table_to_target(table_config, names=None):
    """Copy the completed formal sampling table from staging DB to target DB."""
    names = dict(names or get_direct_sampling_names(table_config))
    final_db_name = names['final_db_name']
    staging_db_name = names.get('staging_db_name') or final_db_name
    final_table_name = names['final_table_name']
    if staging_db_name == final_db_name:
        print(f"采样临时库与目标库相同，无需额外同步：{final_db_name}.{final_table_name}")
        return True

    source_conn = None
    staging_conn = None
    final_conn = None
    replace_staging_table_name = None
    try:
        source_conn = object()
        if not source_conn:
            print(f"无法建立 {names['source_db_name']} 连接，目标库同步终止")
            return False

        staging_table_config = get_table_config_with_final_database(table_config, staging_db_name)
        final_table_config = get_table_config_with_final_database(table_config, final_db_name)
        staging_conn = connect_by_table('FINAL_TABLE', staging_table_config)
        if not staging_conn:
            print(f"无法建立采样临时库 {staging_db_name} 连接，目标库同步终止")
            return False
        final_conn = connect_by_table('FINAL_TABLE', final_table_config)
        if not final_conn:
            print(f"无法建立目标库 {final_db_name} 连接，目标库同步终止")
            return False

        if not table_exists_exact(staging_conn, final_table_name):
            print(f"采样临时库正式表不存在：{staging_db_name}.{final_table_name}，目标库未同步")
            return False

        staging_count = count_table_rows(staging_conn, final_table_name)
        replace_staging_table_name = make_staging_table_name(final_table_name, 'tmp_sync')
        print(
            f"正在从采样临时库正式表 {staging_db_name}.{final_table_name} "
            f"同步到目标库 {final_db_name}.{replace_staging_table_name}..."
        )

        def prepare_target_sync_table():
            nonlocal final_conn
            final_conn = ensure_database_connection(final_conn, final_db_name, "目标库")
            drop_table_if_exists(final_conn, replace_staging_table_name)
            create_table_like_existing(
                staging_conn,
                final_table_name,
                final_conn,
                replace_staging_table_name,
            )
            final_conn.commit()

        prepare_target_sync_table()
        dump_import_table_between_databases(
            get_db_config_by_name(staging_db_name),
            get_db_config_by_name(final_db_name),
            final_table_name,
            replace_staging_table_name,
            label="同步采样正式表到目标库",
            reprepare_target=prepare_target_sync_table,
        )
        final_conn = refresh_connection_read_view(final_conn, final_db_name, "目标库")
        final_staging_count = count_table_rows(final_conn, replace_staging_table_name)
        if final_staging_count != staging_count:
            raise RuntimeError(
                f"同步目标库临时表数量不一致：临时库 {staging_count}，"
                f"目标库 {final_staging_count}"
            )

        print(f"正在替换目标库正式表 {final_db_name}.{final_table_name}...")
        replace_table_with_staging(
            final_conn,
            replace_staging_table_name,
            final_table_name,
            final_db_name,
        )
        replace_staging_table_name = None
        print(
            f"目标库同步完成！已写入 {staging_count} 条数据到 "
            f"{final_db_name}.{final_table_name}"
        )
        return True
    except Exception:
        if final_conn is not None and replace_staging_table_name:
            with contextlib.suppress(Exception):
                drop_table_if_exists(final_conn, replace_staging_table_name)
                final_conn.commit()
        raise
    finally:
        close_safely(source_conn)
        close_safely(staging_conn)
        close_safely(final_conn)


def cleanup_direct_sampling_failure(error, final_conn, names, staging_state, total_sampled_count, *, staging_conn=None):
    """采样失败时清理或保留临时表。"""
    if not staging_state or not staging_state.get('staging_table_name'):
        return final_conn
    staging_table_name = staging_state['staging_table_name']
    staging_db_name = staging_state.get('staging_db_name') or names.get('staging_db_name') or names['final_db_name']
    staging_conn = staging_conn or final_conn
    if isinstance(error, TaskCancelled) or total_sampled_count <= 0:
        with contextlib.suppress(Exception):
            staging_conn = ensure_database_connection(staging_conn, staging_db_name, "采样临时库")
            drop_table_if_exists(staging_conn, staging_table_name)
            staging_conn.commit()
            print(f"已清理临时目标表：{staging_db_name}.{staging_table_name}")
        return final_conn

    target_text = (
        f"{names['final_db_name']}.{names['final_table_name']}"
        if names.get('final_db_name') and names.get('final_table_name')
        else "目标表"
    )
    print(
        f"目标表 {target_text} 未替换；已写入 {total_sampled_count} 条数据的临时表 "
        f"{staging_db_name}.{staging_table_name} 已保留，可检查后手动恢复。"
    )
    return final_conn


def direct_sample_from_source(table_config, sample_conditions, *, append_mode=False):
    """从源数据直接采样并写入目标表。"""
    deps = SimpleNamespace(
        check_cancelled=check_cancelled,
        get_direct_sampling_names=get_direct_sampling_names,
        get_sampling_staging_table_config=get_sampling_staging_table_config,
        get_sampling_increment_table_config=get_sampling_increment_table_config,
        reject_same_physical_sampling_table=reject_same_physical_sampling_table,
        connect_by_table=connect_by_table,
        resolve_direct_sample_conditions=resolve_direct_sample_conditions,
        warn_sampling_read_index=warn_sampling_read_index,
        get_engine_by_table=get_engine_by_table,
        load_sampling_config_df=load_sampling_config_df,
        get_append_mode=lambda: SAMPLING_APPEND_MODE,
        build_sampling_task_identity=build_sampling_task_identity,
        load_sampling_task_state=load_sampling_task_state,
        start_sampling_task_state=start_sampling_task_state,
        try_resume_direct_sampling_staging=try_resume_direct_sampling_staging,
        mark_sampling_task_completed=mark_sampling_task_completed,
        mark_sampling_task_failed=mark_sampling_task_failed,
        prepare_direct_sampling_staging=prepare_direct_sampling_staging,
        prepare_increment_sampling_staging=prepare_increment_sampling_staging,
        sample_config_rows_to_staging=sample_config_rows_to_staging,
        finalize_direct_sampling_staging=finalize_direct_sampling_staging,
        sync_sampling_temp_table_to_target=sync_sampling_temp_table_to_target,
        cleanup_direct_sampling_failure=cleanup_direct_sampling_failure,
        print_step_error=print_step_error,
        close_safely=close_safely,
    )
    return direct_sampling_runner.direct_sample_from_source(
        table_config,
        sample_conditions,
        deps=deps,
        append_mode=append_mode,
    )
