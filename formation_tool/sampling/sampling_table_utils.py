"""Table and validation helpers for direct sampling."""

import contextlib
import re

from formation_tool.core import runtime_context_sync
from formation_tool.utils import log_utils

print = log_utils.emit


def configure(**values):
    """Inject runtime callbacks owned by sampling_core/main script."""
    runtime_context_sync.configure_module_globals(globals(), values)


def create_table_like_source(final_conn, source_conn, table_config, target_table_name):
    """在目标库创建与源表相同结构的空表，不复制数据。"""
    source_table_name = get_table_name('SOURCE_TABLE', table_config)
    src_cfg = get_db_config_by_name(get_table_database('SOURCE_TABLE', table_config))
    dst_cfg = get_db_config_by_name(get_table_database('FINAL_TABLE', table_config))
    source_ref = quote_identifier(source_table_name, "源表名")
    target_ref = quote_identifier(target_table_name, "目标表名")
    if (src_cfg['host'], src_cfg['port']) == (dst_cfg['host'], dst_cfg['port']):
        src_schema_ref = quote_identifier(src_cfg['database'], "源库 schema")
        with final_conn.cursor() as cur:
            cur.execute(f"CREATE TABLE {target_ref} LIKE {src_schema_ref}.{source_ref}")
        return

    with source_conn.cursor() as cur:
        cur.execute(f"SHOW CREATE TABLE {source_ref}")
        row = cur.fetchone()
    if not row:
        raise RuntimeError(f"源表不存在或无法读取结构: {source_table_name}")
    create_sql = re.sub(
        r'^CREATE TABLE `[^`]+`',
        f'CREATE TABLE {target_ref}',
        row[1],
        count=1,
        flags=re.IGNORECASE,
    )
    with final_conn.cursor() as cur:
        cur.execute(create_sql)


def create_final_table_like_source(final_conn, source_conn, table_config):
    """在目标库创建与源表相同结构的正式空表。"""
    create_table_like_source(
        final_conn,
        source_conn,
        table_config,
        get_table_name('FINAL_TABLE', table_config),
    )


def is_same_physical_table(table_config):
    """判断源表和目标表是否指向同一张物理 MySQL 表。"""
    try:
        src_cfg = get_db_config_by_name(get_table_database('SOURCE_TABLE', table_config))
        dst_cfg = get_db_config_by_name(get_table_database('FINAL_TABLE', table_config))
    except ValueError:
        return False
    return (
        str(src_cfg.get('host')).lower(),
        int(src_cfg.get('port')),
        str(src_cfg.get('database')).lower(),
        get_table_name('SOURCE_TABLE', table_config).lower(),
    ) == (
        str(dst_cfg.get('host')).lower(),
        int(dst_cfg.get('port')),
        str(dst_cfg.get('database')).lower(),
        get_table_name('FINAL_TABLE', table_config).lower(),
    )


def get_table_columns(conn, table_name):
    """返回表列定义 [(Field, Type, Null, Extra), ...]；表不存在则返回 None。"""
    try:
        table_ref = quote_identifier(table_name, "表名")
        with conn.cursor() as cur:
            cur.execute(f"DESCRIBE {table_ref}")
            return [(row[0], row[1], row[2], row[5]) for row in cur.fetchall()]
    except Exception:
        return None


def same_table_structure(source_conn, final_conn, source_table, final_table):
    """比较源表与目标表列结构是否一致。"""
    src = get_table_columns(source_conn, source_table)
    dst = get_table_columns(final_conn, final_table)
    return src is not None and dst is not None and src == dst


def normalize_column_type_for_append(column_type):
    """补充采样结构校验用：忽略长度/精度，只保留基础类型和修饰符。"""
    text = str(column_type or "").strip().lower()
    text = re.sub(r'\s+', ' ', text)
    match = re.match(r'^([a-z]+)(\([^)]*\))?(.*)$', text)
    if not match:
        return text
    base_type, _length, suffix = match.groups()
    if base_type in {'enum', 'set'}:
        return text
    return f"{base_type}{suffix}".strip()


def append_compatible_column_signature(columns):
    if columns is None:
        return None
    return [
        (str(field), normalize_column_type_for_append(column_type))
        for field, column_type, _null, _extra in columns
    ]


def compare_table_structure_for_append(source_columns, final_columns):
    """Describe append compatibility while ignoring length/Null/Extra metadata."""
    if source_columns is None or final_columns is None:
        return {
            'compatible': False,
            'unreadable': True,
            'missing_in_target': [],
            'extra_in_target': [],
            'type_mismatches': [],
            'order_mismatch': False,
        }

    source_signature = append_compatible_column_signature(source_columns)
    final_signature = append_compatible_column_signature(final_columns)
    source_map = {str(name).lower(): (str(name), column_type) for name, column_type in source_signature}
    final_map = {str(name).lower(): (str(name), column_type) for name, column_type in final_signature}
    source_names = [str(name).lower() for name, _column_type in source_signature]
    final_names = [str(name).lower() for name, _column_type in final_signature]

    missing_keys = [name for name in source_names if name not in final_map]
    extra_keys = [name for name in final_names if name not in source_map]
    type_mismatches = []
    for key in source_names:
        if key not in final_map:
            continue
        source_name, source_type = source_map[key]
        final_name, final_type = final_map[key]
        if source_type != final_type:
            type_mismatches.append({
                'field': source_name,
                'source_type': source_type,
                'target_type': final_type,
                'target_field': final_name,
            })

    order_mismatch = not missing_keys and not extra_keys and source_names != final_names
    return {
        'compatible': not missing_keys and not extra_keys and not type_mismatches and not order_mismatch,
        'unreadable': False,
        'missing_in_target': [source_map[key][0] for key in missing_keys],
        'extra_in_target': [final_map[key][0] for key in extra_keys],
        'type_mismatches': type_mismatches,
        'order_mismatch': order_mismatch,
    }


def same_table_structure_for_append(source_conn, final_conn, source_table, final_table):
    """补充采样只要求字段名和基础类型一致，不要求长度、Null、Extra 完全一致。"""
    comparison = compare_table_structure_for_append(
        get_table_columns(source_conn, source_table),
        get_table_columns(final_conn, final_table),
    )
    return comparison['compatible']


def validate_table_config(table_config):
    """验证采样表配置完整性。"""
    print("正在验证表配置...")
    required_tables = ['SOURCE_TABLE', 'FINAL_TABLE', 'REBATE_CONFIG_TABLE']
    for table_key in required_tables:
        if table_key not in table_config:
            print(f"错误：缺少表配置 {table_key}")
            return False
        table_info = table_config[table_key]
        if 'name' not in table_info or 'database' not in table_info:
            print(f"错误：表配置 {table_key} 缺少必要字段")
            return False
        db_name = table_info['database']
        if db_name not in DATABASE_CONFIGS:
            print(f"错误：表 {table_key} 的数据库配置无效: {db_name}")
            print(f"可用数据库: {list(DATABASE_CONFIGS.keys())}")
            return False
        try:
            validate_sql_identifier(table_info['name'], f"{table_key} 表名")
        except ValueError as e:
            print(f"错误：{e}")
            return False
    print("表配置验证通过")
    return True


def get_sample_description(target_rebate, sample_conditions):
    """动态生成采样条件描述。"""
    where_clause = sample_conditions['where_clause'].format(target_rebate=target_rebate)
    return f"采样条件: {where_clause}"


def remap_conflicting_sample_ids(df, conn, staging_table, id_mapping, next_id_state):
    """追加采样时，遇到和旧数据冲突的 id 就给本次采样整组换新 id。"""
    if 'id' not in df.columns:
        raise ValueError("追加写入模式要求源表包含 id 字段")

    source_ids = sorted(int(value) for value in df['id'].dropna().unique())
    if not source_ids:
        return df, 0, []

    unmapped_ids = [source_id for source_id in source_ids if source_id not in id_mapping]
    conflicting_ids = get_existing_ids(conn, staging_table, unmapped_ids)
    non_conflicting_ids = set(unmapped_ids) - conflicting_ids
    reserved_targets = set(id_mapping.values()) | non_conflicting_ids
    changed_sources = []

    next_id = int(next_id_state[0])
    for source_id in unmapped_ids:
        if source_id in conflicting_ids:
            while next_id in reserved_targets:
                next_id += 1
            id_mapping[source_id] = next_id
            reserved_targets.add(next_id)
            changed_sources.append((source_id, next_id))
            next_id += 1
        else:
            id_mapping[source_id] = source_id
            reserved_targets.add(source_id)

    current_targets = [int(id_mapping[source_id]) for source_id in source_ids]
    if current_targets:
        next_id = max(next_id, max(current_targets) + 1)
    next_id_state[0] = next_id

    if not any(id_mapping[source_id] != source_id for source_id in source_ids):
        return df, 0, []

    remapped_df = df.copy()
    remapped_df['id'] = remapped_df['id'].map(lambda value: id_mapping[int(value)])
    changed_row_count = int(remapped_df['id'].ne(df['id']).sum())
    return remapped_df, changed_row_count, changed_sources


def check_source_table_exists(table_config):
    """检查源表是否存在。"""
    source_table_name = get_table_name('SOURCE_TABLE', table_config)
    conn = None
    try:
        conn = connect_by_table('SOURCE_TABLE', table_config)
        if not conn:
            return False
        return table_exists_exact(conn, source_table_name)
    except Exception:
        return False
    finally:
        close_safely(conn)


def detect_end_field(conn, table_name):
    """优先检测 game_end 字段，其次 is_end，均不存在返回 None。"""
    try:
        table_ref = quote_identifier(table_name, "表名")
        with conn.cursor() as cur:
            cur.execute(f"DESCRIBE {table_ref}")
            columns = {row[0] for row in cur.fetchall()}
        if 'game_end' in columns:
            return 'game_end'
        if 'is_end' in columns:
            return 'is_end'
        return None
    except Exception:
        return None


def detect_end_field_optional(conn, table_name):
    """优先 game_end，其次 is_end，均不存在返回空字符串。"""
    field = detect_end_field(conn, table_name)
    return f" AND {field} = 1" if field else ""


def validate_end_field_integrity(conn, table_name, end_field):
    """校验每个 id 下 end_field=1 的行数是否恰好为 1。"""
    print(f"  正在校验 {table_name} 数据完整性（每个 id 的 {end_field}=1 行数应等于 1）...")
    table_ref = quote_identifier(table_name, "表名")
    end_field_ref = quote_identifier(end_field, "结束字段名")
    with conn.cursor(dictionary=True) as cur:
        cur.execute(
            f"SELECT id, COUNT(CASE WHEN {end_field_ref}=1 THEN 1 END) AS end_cnt "
            f"FROM {table_ref} GROUP BY id HAVING end_cnt <> 1"
        )
        bad_rows = cur.fetchall()

    if not bad_rows:
        print(f"  校验通过：所有 id 均有且只有 1 条 {end_field}=1 的数据")
        return

    no_end = [row['id'] for row in bad_rows if row['end_cnt'] == 0]
    multi_end = [row['id'] for row in bad_rows if row['end_cnt'] > 1]

    lines = [f"数据完整性校验失败（表：{table_name}，字段：{end_field}）："]
    if multi_end:
        preview = multi_end[:10]
        lines.append(
            f"  存在多条 {end_field}=1 的 id 共 {len(multi_end)} 个：{preview}"
            + ("..." if len(multi_end) > 10 else "")
        )
    if no_end:
        preview = no_end[:10]
        lines.append(
            f"  缺少 {end_field}=1 的 id 共 {len(no_end)} 个：{preview}"
            + ("..." if len(no_end) > 10 else "")
        )
    raise ValueError('\n'.join(lines))
