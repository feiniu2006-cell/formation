"""Direct sampling core helpers for formation source tables."""

import contextlib
import random
import time
from types import SimpleNamespace

import pandas as pd

from formation_tool.core import runtime_context_sync
from formation_tool.sampling import direct_sampling_runner
from formation_tool.sampling import sampling_task_state
from formation_tool.sampling import sampling_table_utils
from formation_tool.utils import log_utils
from formation_tool.utils.task_utils import TaskCancelled

print = log_utils.emit

SAMPLE_ID_RANDOM_RANGE_ATTEMPTS = 8
SAMPLE_ID_RANDOM_RANGE_MAX_CANDIDATES_PER_QUERY = 20000


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
    """解析采样 where_clause 中的结束字段占位符，并做结束字段完整性校验。"""
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
        validate_end_field_integrity(source_conn, source_table_name, end_field_for_validation)
    return {**sample_conditions, 'where_clause': where_tpl}


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
    return config_df


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
    expected_prefix = [end_field, 'rebate', 'id'] if end_field else ['rebate', 'id']
    has_composite_index = any(
        columns[:len(expected_prefix)] == expected_prefix
        for columns in lower_indexes.values()
    )
    if has_id_index or has_composite_index:
        used = [
            f"{name}({', '.join(index_columns[name])})"
            for name, columns in lower_indexes.items()
            if columns[:1] == ['id'] or columns[:len(expected_prefix)] == expected_prefix
        ]
        print(f"实际采样读取索引检查通过：{source_table_name}，可用索引：{'; '.join(used)}")
        return

    print(f"实际采样读取索引风险：{source_table_name} 未检测到适合读取完整行的索引。")
    print("  当前读取完整行会使用：原采样条件 AND id IN (...)")
    if end_field:
        print(
            f"  建议添加复合索引：ALTER TABLE {source_table_name} "
            f"ADD INDEX idx_{end_field}_rebate_id (`{end_field}`, `rebate`, `id`);"
        )
    print(
        f"  或添加单列id索引：ALTER TABLE {source_table_name} "
        "ADD INDEX idx_id (`id`);"
    )


def select_sample_ids_for_rebate(
    *,
    source_engine,
    source_db_name,
    source_table_ref,
    sample_conditions,
    target_rebate,
    sample_size,
):
    """查询并抽取一组需要采样的 id。"""
    id_query = f"""
    SELECT DISTINCT id
    FROM {source_table_ref}
    WHERE {sample_conditions['where_clause'].format(target_rebate=target_rebate)}
    """
    id_df = sql_with_retry(
        lambda: pd.read_sql_query(id_query, source_engine),
        f"查询采样ID (rebate={target_rebate})",
    )
    check_cancelled()
    print(f"从 {source_db_name} 查询到 {len(id_df)} 个符合条件的ID (rebate={target_rebate})")

    if len(id_df) > sample_size:
        sampled_ids = id_df.sample(
            n=sample_size,
            random_state=sample_conditions['random_seed'],
        )['id'].tolist()
        print(f"随机抽取 {sample_size} 个ID")
    else:
        sampled_ids = id_df['id'].tolist()
        print(f"ID数量不足，使用全部 {len(id_df)} 个ID")
    return [int(value) for value in sampled_ids]


def _sample_ids_from_candidates(candidate_ids, sample_size, random_seed):
    candidate_ids = sorted({int(value) for value in candidate_ids})
    if len(candidate_ids) <= sample_size:
        return candidate_ids
    rng = random.Random(str(random_seed))
    return rng.sample(candidate_ids, sample_size)


def _select_sample_ids_with_full_scan(
    *,
    source_engine,
    source_db_name,
    source_table_ref,
    where_clause,
    target_rebate,
    sample_size,
    random_seed,
):
    """Fallback: query all matching distinct ids and sample in Python."""
    start = time.perf_counter()
    id_query = f"""
    SELECT DISTINCT `id`
    FROM {source_table_ref}
    WHERE {where_clause}
    """
    id_df = sql_with_retry(
        lambda: pd.read_sql_query(id_query, source_engine),
        f"全量查询采样ID (rebate={target_rebate})",
    )
    check_cancelled()
    print(
        f"从 {source_db_name} 全量查询到 {len(id_df)} 个符合条件的ID "
        f"(rebate={target_rebate})，耗时 {time.perf_counter() - start:.2f} 秒"
    )

    sampled_ids = _sample_ids_from_candidates(id_df['id'].tolist(), sample_size, random_seed)
    if len(id_df) > sample_size:
        print(f"随机抽取 {sample_size} 个ID")
    else:
        print(f"ID数量不足，使用全部 {len(sampled_ids)} 个ID")
    return sampled_ids


def _query_limited_distinct_ids(source_engine, source_table_ref, where_clause, target_rebate, limit):
    start = time.perf_counter()
    query = f"""
    SELECT DISTINCT `id`
    FROM {source_table_ref}
    WHERE {where_clause}
    LIMIT {int(limit)}
    """
    id_df = sql_with_retry(
        lambda: pd.read_sql_query(query, source_engine),
        f"稀疏rebate探测 (rebate={target_rebate})",
    )
    print(
        f"稀疏rebate探测耗时：{time.perf_counter() - start:.2f} 秒，"
        f"最多检查 {int(limit)} 个，返回 {len(id_df)} 个 (rebate={target_rebate})"
    )
    return [int(value) for value in id_df['id'].tolist()]


def _query_sample_id_range(source_engine, source_table_ref, where_clause, target_rebate):
    start = time.perf_counter()
    range_query = f"""
    SELECT MIN(`id`) AS min_id, MAX(`id`) AS max_id
    FROM {source_table_ref}
    WHERE {where_clause}
    """
    range_df = sql_with_retry(
        lambda: pd.read_sql_query(range_query, source_engine),
        f"查询采样ID范围 (rebate={target_rebate})",
    )
    elapsed = time.perf_counter() - start
    if range_df.empty:
        print(f"采样ID范围查询耗时：{elapsed:.2f} 秒，未查询到范围")
        return None, None
    min_id = range_df.iloc[0].get('min_id')
    max_id = range_df.iloc[0].get('max_id')
    if pd.isna(min_id) or pd.isna(max_id):
        print(f"采样ID范围查询耗时：{elapsed:.2f} 秒，未查询到范围")
        return None, None
    min_id = int(min_id)
    max_id = int(max_id)
    print(
        f"采样ID范围查询耗时：{elapsed:.2f} 秒，"
        f"rebate={target_rebate}, id范围={min_id}~{max_id}"
    )
    return min_id, max_id


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
):
    if sample_size <= 0 or min_id is None or max_id is None:
        return []

    rng = random.Random(f"{random_seed}:{target_rebate}:{sample_size}")
    per_query_limit = min(
        max(sample_size * 3, 500),
        SAMPLE_ID_RANDOM_RANGE_MAX_CANDIDATES_PER_QUERY,
    )
    candidate_ids = set()
    total_start = time.perf_counter()

    for attempt in range(1, SAMPLE_ID_RANDOM_RANGE_ATTEMPTS + 1):
        check_cancelled()
        start_id = rng.randint(int(min_id), int(max_id))
        query = f"""
        SELECT DISTINCT `id`
        FROM {source_table_ref}
        WHERE ({where_clause}) AND `id` >= {start_id}
        ORDER BY `id`
        LIMIT {per_query_limit}
        """
        start = time.perf_counter()
        id_df = sql_with_retry(
            lambda: pd.read_sql_query(query, source_engine),
            f"随机范围查询采样ID (rebate={target_rebate}, 第{attempt}次)",
        )
        elapsed = time.perf_counter() - start
        before = len(candidate_ids)
        candidate_ids.update(int(value) for value in id_df['id'].tolist())
        added = len(candidate_ids) - before
        print(
            f"  随机范围第 {attempt}/{SAMPLE_ID_RANDOM_RANGE_ATTEMPTS} 次："
            f"起点id={start_id}，返回 {len(id_df)} 个，新增 {added} 个，"
            f"累计 {len(candidate_ids)} 个，耗时 {elapsed:.2f} 秒"
        )
        if len(candidate_ids) >= sample_size:
            break

    print(
        f"随机范围候选ID查询总耗时：{time.perf_counter() - total_start:.2f} 秒，"
        f"候选 {len(candidate_ids)} 个"
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
    )
    if len(sparse_probe_ids) <= sample_size:
        print(
            f"rebate={target_rebate} 可用ID数量不超过采样数，"
            f"直接使用全部 {len(sparse_probe_ids)} 个ID"
        )
        print(f"采样ID选择总耗时：{time.perf_counter() - total_start:.2f} 秒 (rebate={target_rebate})")
        return _sample_ids_from_candidates(sparse_probe_ids, sample_size, random_seed)

    min_id, max_id = _query_sample_id_range(
        source_engine,
        source_table_ref,
        where_clause,
        target_rebate,
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
        )
    else:
        sampled_ids = _sample_ids_from_candidates(candidate_ids, sample_size, random_seed)
        print(
            f"从 {source_db_name} 随机范围候选 {len(candidate_ids)} 个ID中"
            f"抽取 {len(sampled_ids)} 个 (rebate={target_rebate})"
        )

    print(f"采样ID选择总耗时：{time.perf_counter() - total_start:.2f} 秒 (rebate={target_rebate})")
    return [int(value) for value in sampled_ids]


def read_sample_rows_by_ids(source_engine, source_table_ref, id_batch, target_rebate, sample_conditions=None):
    """按 id 分块读取源表完整行。"""
    id_text = ','.join(str(int(value)) for value in id_batch)
    where_parts = [f"`id` IN ({id_text})"]
    if sample_conditions is not None:
        where_parts.insert(
            0,
            f"({sample_conditions['where_clause'].format(target_rebate=target_rebate)})",
        )
    where_clause = " AND ".join(where_parts)
    query = f"""
    SELECT *
    FROM {source_table_ref}
    WHERE {where_clause}
    """
    start = time.perf_counter()
    df = sql_with_retry(
        lambda: pd.read_sql_query(query, source_engine),
        f"提取采样数据 (rebate={target_rebate})",
    )
    print(
        f"读取完整采样行耗时：{time.perf_counter() - start:.2f} 秒，"
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


def write_sample_chunk_to_staging(current_df, final_engine, staging_table_name, target_rebate):
    start = time.perf_counter()
    sql_with_retry(
        lambda: current_df.to_sql(staging_table_name, final_engine, if_exists='append', index=False),
        f"写入数据 (rebate={target_rebate})",
    )
    print(
        f"写入临时表耗时：{time.perf_counter() - start:.2f} 秒，"
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
    sample_conditions,
    append_mode,
    id_mapping,
    next_id_state,
):
    """分块提取采样行并写入临时表，避免超长 IN 查询和过大 DataFrame。"""
    total_start = time.perf_counter()
    totals = {'row_count': 0, 'changed_pair_count': 0, 'changed_row_count': 0}
    batches = list(chunked(sampled_ids, SAMPLE_ID_FETCH_CHUNK_SIZE))
    if len(batches) > 1:
        print(f"采样ID较多，将按 {SAMPLE_ID_FETCH_CHUNK_SIZE} 个ID/批分 {len(batches)} 批提取写入")

    for batch_index, id_batch in enumerate(batches, start=1):
        check_cancelled()
        current_df = read_sample_rows_by_ids(
            source_engine,
            source_table_ref,
            id_batch,
            target_rebate,
            sample_conditions,
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
            print(
                f"追加模式id冲突处理耗时：{time.perf_counter() - start:.2f} 秒，"
                f"冲突id={changed_pair_count}，改写行={changed_row_count}"
            )
            totals['changed_pair_count'] += changed_pair_count
            totals['changed_row_count'] += changed_row_count

        write_sample_chunk_to_staging(
            current_df,
            final_engine,
            staging_table_name,
            target_rebate,
        )
        totals['row_count'] += len(current_df)
        if append_mode:
            final_conn = refresh_connection_read_view(final_conn, final_db_name, "目标库")
        if len(batches) > 1:
            print(f"  第 {batch_index}/{len(batches)} 批写入 {len(current_df)} 条，累计 {totals['row_count']} 条")

    print(f"从 {source_db_name} 提取到 {totals['row_count']} 条数据")
    print(f"采样行读取+写入总耗时：{time.perf_counter() - total_start:.2f} 秒 (rebate={target_rebate})")
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
):
    """按一条 rebate_count 配置采样并写入临时目标表。"""
    total_start = time.perf_counter()
    target_rebate = row['rebate']
    sample_size = int(row['count'])

    print(f"\n处理 rebate={target_rebate}, 采样数量={sample_size}...")
    print(get_sample_description(target_rebate, sample_conditions))
    source_table_ref = quote_identifier(source_table_name, "源表名")
    validate_sql_identifier(staging_table_name, "临时目标表名")

    sampled_ids = select_sample_ids_for_rebate(
        source_engine=source_engine,
        source_db_name=source_db_name,
        source_table_ref=source_table_ref,
        sample_conditions=sample_conditions,
        target_rebate=target_rebate,
        sample_size=sample_size,
    )
    if not sampled_ids:
        print(f"没有找到 rebate={target_rebate} 的数据")
        return 0, 0, 0, final_conn

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
        sample_conditions=sample_conditions,
        append_mode=append_mode,
        id_mapping=id_mapping,
        next_id_state=next_id_state,
    )
    if totals['row_count'] <= 0:
        print(f"没有提取到 rebate={target_rebate} 的数据")
        return 0, totals['changed_pair_count'], totals['changed_row_count'], final_conn

    print(f"成功写入 {totals['row_count']} 条数据到临时表 {final_db_name}.{staging_table_name} (rebate={target_rebate})")
    print(f"rebate={target_rebate} 单项采样总耗时：{time.perf_counter() - total_start:.2f} 秒")
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
    totals = dict(initial_totals or {
        'sampled_count': 0,
        'remapped_id_count': 0,
        'remapped_row_count': 0,
    })
    completed_rebates = sampling_task_state.completed_rebate_set(task_state or {})
    for _, row in config_df.iterrows():
        check_cancelled()
        target_rebate = int(row['rebate'])
        if target_rebate in completed_rebates:
            print(f"跳过已完成的 rebate={target_rebate}，继续恢复采样")
            continue
        sampled_count, changed_pair_count, changed_row_count, final_conn = sample_rebate_to_staging(
            row,
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
        )
        totals['sampled_count'] += sampled_count
        totals['remapped_id_count'] += changed_pair_count
        totals['remapped_row_count'] += changed_row_count
        if task_state is not None:
            sampling_task_state.record_completed_rebate(
                task_state,
                staging_state,
                rebate=target_rebate,
                sample_size=int(row['count']),
                sampled_count=sampled_count,
                changed_pair_count=changed_pair_count,
                changed_row_count=changed_row_count,
            )
            completed_rebates.add(target_rebate)
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
