"""Direct sampling core helpers for formation source tables."""

import contextlib
import random
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
SAMPLE_ROW_WRITE_CHUNK_SIZE = 100
SAMPLING_DETAILED_LOG = False
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
validate_table_config = sampling_table_utils.validate_table_config
get_sample_description = sampling_table_utils.get_sample_description
remap_conflicting_sample_ids = sampling_table_utils.remap_conflicting_sample_ids
check_source_table_exists = sampling_table_utils.check_source_table_exists
detect_end_field = sampling_table_utils.detect_end_field
detect_end_field_optional = sampling_table_utils.detect_end_field_optional
validate_end_field_integrity = sampling_table_utils.validate_end_field_integrity


def run_single_game(game_config):
    """执行单个游戏模式采样。"""
    table_config = game_config['table_config']
    sample_conditions = game_config['sample_conditions']
    source_table_name = get_table_name('SOURCE_TABLE', table_config)

    print(f"\n{'=' * 50}")
    print(f"开始处理：{game_config['name']}")

    if not check_source_table_exists(table_config):
        print(f"源表 {source_table_name} 不存在，跳过 {game_config['name']}")
        return False

    if not validate_table_config(table_config):
        print("配置验证失败，跳过")
        return False

    try:
        return bool(direct_sample_from_source(table_config, sample_conditions))
    except TaskCancelled:
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

    if end_field_for_validation:
        print(f"  数据完整性校验将按已采样ID执行（字段：{end_field_for_validation}）")
    return {
        **sample_conditions,
        'where_clause': where_tpl,
        'end_field_for_validation': end_field_for_validation,
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


def format_changed_pairs_preview(changed_pairs, limit=8):
    preview = ', '.join(f"{old}->{new}" for old, new in changed_pairs[:limit])
    if len(changed_pairs) > limit:
        preview += ', ...'
    return preview


def remap_sample_chunk_for_append_mode(
    current_df,
    *,
    final_conn,
    final_db_name,
    staging_table_name,
    id_mapping,
    next_id_state,
):
    """追加模式下处理单个采样块的 id 冲突。"""
    final_conn = refresh_connection_read_view(final_conn, final_db_name, "目标库")
    current_df, changed_row_count, changed_pairs = remap_conflicting_sample_ids(
        current_df,
        final_conn,
        staging_table_name,
        id_mapping,
        next_id_state,
    )
    if changed_pairs:
        print(
            f"追加模式：发现 {len(changed_pairs)} 个采样 id 与旧数据冲突，"
            f"已改写 {changed_row_count} 行 id：{format_changed_pairs_preview(changed_pairs)}"
        )
    return current_df, len(changed_pairs), changed_row_count, final_conn


def _make_sample_row_write_method(total_rows, target_rebate):
    total_batches = max(1, (int(total_rows) + SAMPLE_ROW_WRITE_CHUNK_SIZE - 1) // SAMPLE_ROW_WRITE_CHUNK_SIZE)
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
            f"  开始写入临时表批次 {batch_index}/{total_batches}："
            f"本批 {len(rows)} 行，已完成 {before_rows}/{total_rows} (rebate={target_rebate})"
        )
        start = time.perf_counter()
        result = conn.execute(table.table.insert(), rows)
        elapsed = time.perf_counter() - start
        state['written_rows'] += len(rows)
        print_sampling_detail(
            f"  完成写入临时表批次 {batch_index}/{total_batches}："
            f"本批 {len(rows)} 行，累计 {state['written_rows']}/{total_rows}，耗时 {elapsed:.2f} 秒 "
            f"(rebate={target_rebate})"
        )
        check_cancelled()
        rowcount = getattr(result, 'rowcount', None)
        if isinstance(rowcount, int) and rowcount >= 0:
            return rowcount
        return len(rows)

    return write_method


def write_sample_chunk_to_staging(current_df, final_engine, staging_table_name, target_rebate, *, timing=None):
    start = time.perf_counter()
    row_count = len(current_df)
    total_batches = max(1, (row_count + SAMPLE_ROW_WRITE_CHUNK_SIZE - 1) // SAMPLE_ROW_WRITE_CHUNK_SIZE)
    print_sampling_detail(
        f"准备写入临时表：行数={row_count}，"
        f"批次={total_batches}，每批最多 {SAMPLE_ROW_WRITE_CHUNK_SIZE} 行 (rebate={target_rebate})"
    )
    sql_with_retry(
        lambda: current_df.to_sql(
            staging_table_name,
            final_engine,
            if_exists='append',
            index=False,
            chunksize=SAMPLE_ROW_WRITE_CHUNK_SIZE,
            method=_make_sample_row_write_method(row_count, target_rebate),
        ),
        f"写入数据 (rebate={target_rebate})",
    )
    elapsed = time.perf_counter() - start
    add_sampling_timing(timing, 'row_write_seconds', elapsed)
    print_sampling_detail(
        f"写入临时表耗时：{elapsed:.2f} 秒，"
        f"行数={len(current_df)} (rebate={target_rebate})"
    )


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
    return {
        'source_db_name': get_table_database('SOURCE_TABLE', table_config),
        'final_db_name': get_table_database('FINAL_TABLE', table_config),
        'config_db_name': get_table_database('REBATE_CONFIG_TABLE', table_config),
        'source_table_name': get_table_name('SOURCE_TABLE', table_config),
        'final_table_name': get_table_name('FINAL_TABLE', table_config),
        'rebate_config_table_name': get_table_name('REBATE_CONFIG_TABLE', table_config),
    }


def reject_same_physical_sampling_table(table_config, names):
    """拦截源表和目标表相同导致的误覆盖风险。"""
    if not is_same_physical_table(table_config):
        return False
    print(
        f"源表和目标表指向同一张物理表 {names['source_db_name']}.{names['source_table_name']}，"
        "为避免误覆盖源数据，采样终止。"
    )
    return True


def prepare_direct_sampling_staging(source_conn, final_conn, table_config, names, append_mode):
    """创建直接采样临时表，并在追加模式下复制旧数据。"""
    final_db_name = names['final_db_name']
    final_table_name = names['final_table_name']
    source_table_name = names['source_table_name']
    staging_table_name = None
    try:
        final_conn.ping(reconnect=True, attempts=MAX_DB_RETRIES, delay=DB_RETRY_DELAY)
        staging_table_name = make_staging_table_name(final_table_name, 'tmp')
        drop_table_if_exists(final_conn, staging_table_name)
        create_table_like_source(
            final_conn,
            source_conn,
            table_config,
            staging_table_name,
        )
        final_conn.commit()

        staging_state = {
            'staging_table_name': staging_table_name,
            'base_existing_count': 0,
            'id_mapping': {},
            'next_id_state': [1],
        }
        final_table_exists = table_exists_exact(final_conn, final_table_name)
        if append_mode and final_table_exists:
            if not same_table_structure(source_conn, final_conn, source_table_name, final_table_name):
                print(
                    f"追加写入要求目标表结构与源表一致；"
                    f"{final_db_name}.{final_table_name} 结构不同，目标表未替换"
                )
                drop_table_if_exists(final_conn, staging_table_name)
                final_conn.commit()
                staging_state['staging_table_name'] = None
                return None
            print(f"采样写入模式：不清空追加。正在复制旧数据到临时表 {final_db_name}.{staging_table_name}...")
            copy_table_rows(final_conn, final_table_name, staging_table_name)
            final_conn.commit()
            staging_state['base_existing_count'] = count_table_rows(final_conn, staging_table_name)
            staging_state['next_id_state'][0] = get_table_max_id(final_conn, staging_table_name) + 1
            print(
                f"已复制旧数据 {staging_state['base_existing_count']} 条；"
                f"如本次采样 id 与旧数据冲突，将从 {staging_state['next_id_state'][0]} 起分配新 id。"
            )
            return staging_state

        if append_mode:
            print(f"采样写入模式：不清空追加；正式表 {final_table_name} 不存在，本次按新表写入。")
        elif final_table_exists:
            structure_text = (
                "结构一致"
                if same_table_structure(source_conn, final_conn, source_table_name, final_table_name)
                else "结构不同，将以源表结构替换"
            )
            print(
                f"采样写入模式：清空后写入。已创建临时目标表 {final_db_name}.{staging_table_name}；"
                f"正式表 {final_table_name} 存在，{structure_text}，采样成功后整体替换。"
            )
        else:
            print(
                f"采样写入模式：清空后写入。已创建临时目标表 {final_db_name}.{staging_table_name}；"
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
            final_db_name=names['final_db_name'],
            staging_table_name=staging_state['staging_table_name'],
            source_db_name=names['source_db_name'],
            source_table_name=names['source_table_name'],
            sample_conditions=sample_conditions,
            append_mode=append_mode,
            id_mapping=staging_state['id_mapping'],
            next_id_state=staging_state['next_id_state'],
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
    if not staging_table_name:
        print("检测到历史采样状态，但状态文件没有记录临时表，本次重新采样")
        return None

    final_conn = ensure_database_connection(final_conn, names['final_db_name'], "目标库")
    if not table_exists_exact(final_conn, staging_table_name):
        print(f"检测到历史采样状态，但临时表 {names['final_db_name']}.{staging_table_name} 不存在，本次重新采样")
        return None

    totals = sampling_task_state.totals_from_state(state)
    expected_count = staging_state['base_existing_count'] + totals['sampled_count']
    actual_count = count_table_rows(final_conn, staging_table_name)
    if actual_count != expected_count:
        print(
            f"检测到历史采样状态，但临时表行数不匹配：预期 {expected_count}，实际 {actual_count}，本次重新采样"
        )
        return None

    completed_count = len(sampling_task_state.completed_rebate_set(state))
    print(
        f"检测到可恢复采样任务：临时表 {names['final_db_name']}.{staging_table_name}，"
        f"已完成 {completed_count} 个 rebate，已写入 {totals['sampled_count']} 行，将继续剩余采样"
    )
    return staging_state, totals


def mark_sampling_task_completed(task_state, success):
    sampling_task_state.mark_completed(task_state, success=success)


def mark_sampling_task_failed(task_state, error):
    sampling_task_state.mark_failed(task_state, error)


def finalize_direct_sampling_staging(final_conn, names, staging_state, totals, append_mode):
    """校验临时表写入数量，并用临时表替换正式表。"""
    final_db_name = names['final_db_name']
    final_table_name = names['final_table_name']
    staging_table_name = staging_state['staging_table_name']
    total_sampled_count = totals['sampled_count']
    base_existing_count = staging_state['base_existing_count']
    final_conn = ensure_database_connection(final_conn, final_db_name, "目标库")
    if total_sampled_count <= 0:
        print(f"\n本次未采样到任何数据，目标表 {final_db_name}.{final_table_name} 未替换")
        drop_table_if_exists(final_conn, staging_table_name)
        final_conn.commit()
        staging_state['staging_table_name'] = None
        return False, final_conn

    print("\n采样循环已完成，正在校验临时表并准备替换正式表...")
    final_conn = refresh_connection_read_view(final_conn, final_db_name, "目标库")
    staging_count = count_table_rows(final_conn, staging_table_name)
    expected_staging_count = base_existing_count + total_sampled_count
    if staging_count != expected_staging_count:
        raise RuntimeError(f"临时目标表写入数量不一致：预期 {expected_staging_count}，实际 {staging_count}")
    if append_mode:
        print(
            f"\n追加采样写入临时表完成：旧数据 {base_existing_count} 条，"
            f"新增 {total_sampled_count} 条，临时表共 {staging_count} 条；"
            f"改写冲突 id {totals['remapped_id_count']} 个、影响 {totals['remapped_row_count']} 行。"
        )
    else:
        print(f"\n采样写入临时表完成：{staging_count} 条。")
    print(f"正在替换正式表 {final_db_name}.{final_table_name}...")
    replace_table_with_staging(
        final_conn,
        staging_table_name,
        final_table_name,
        final_db_name,
    )
    staging_state['staging_table_name'] = None
    if append_mode:
        print(
            f"采样处理完成！保留旧数据 {base_existing_count} 条，"
            f"本次追加 {total_sampled_count} 条到 {final_db_name}.{final_table_name}"
        )
    else:
        print(f"采样处理完成！总共写入 {total_sampled_count} 条数据到 {final_db_name}.{final_table_name}")
    return True, final_conn


def cleanup_direct_sampling_failure(error, final_conn, names, staging_state, total_sampled_count):
    """采样失败时清理或保留临时表。"""
    if not staging_state or not staging_state.get('staging_table_name'):
        return final_conn
    staging_table_name = staging_state['staging_table_name']
    if isinstance(error, TaskCancelled) or total_sampled_count <= 0:
        with contextlib.suppress(Exception):
            final_conn = ensure_database_connection(final_conn, names['final_db_name'], "目标库")
            drop_table_if_exists(final_conn, staging_table_name)
            final_conn.commit()
            print(f"已清理临时目标表：{staging_table_name}")
        return final_conn

    target_text = (
        f"{names['final_db_name']}.{names['final_table_name']}"
        if names.get('final_db_name') and names.get('final_table_name')
        else "目标表"
    )
    print(
        f"目标表 {target_text} 未替换；已写入 {total_sampled_count} 条数据的临时表 "
        f"{names['final_db_name']}.{staging_table_name} 已保留，可检查后手动恢复。"
    )
    return final_conn


def direct_sample_from_source(table_config, sample_conditions):
    """从源数据直接采样并写入目标表。"""
    deps = SimpleNamespace(
        check_cancelled=check_cancelled,
        get_direct_sampling_names=get_direct_sampling_names,
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
        sample_config_rows_to_staging=sample_config_rows_to_staging,
        finalize_direct_sampling_staging=finalize_direct_sampling_staging,
        cleanup_direct_sampling_failure=cleanup_direct_sampling_failure,
        print_step_error=print_step_error,
        close_safely=close_safely,
    )
    return direct_sampling_runner.direct_sample_from_source(
        table_config,
        sample_conditions,
        deps=deps,
    )
