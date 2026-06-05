"""Common MySQL table operations used by the formation tool."""


def drop_table_if_exists(conn, table_name, *, quote_identifier):
    table_ref = quote_identifier(table_name, "表名")
    with conn.cursor() as cur:
        cur.execute(f"DROP TABLE IF EXISTS {table_ref}")


def count_table_rows(conn, table_name, *, quote_identifier):
    table_ref = quote_identifier(table_name, "表名")
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {table_ref}")
        return int(cur.fetchone()[0] or 0)


def get_table_max_id(conn, table_name, *, quote_identifier):
    table_ref = quote_identifier(table_name, "表名")
    with conn.cursor() as cur:
        cur.execute(f"SELECT COALESCE(MAX(`id`), 0) FROM {table_ref}")
        return int(cur.fetchone()[0] or 0)


def copy_table_rows(conn, source_table, target_table, *, quote_identifier):
    """复制整张表数据，要求两张表结构一致。"""
    source_ref = quote_identifier(source_table, "源表名")
    target_ref = quote_identifier(target_table, "目标表名")
    with conn.cursor() as cur:
        cur.execute(f"INSERT INTO {target_ref} SELECT * FROM {source_ref}")
        return cur.rowcount


def get_existing_ids(conn, table_name, ids, *, quote_identifier, chunked):
    """查询 table_name 中已经存在的 id。"""
    ids = [int(value) for value in ids]
    existing = set()
    if not ids:
        return existing
    table_ref = quote_identifier(table_name, "表名")
    with conn.cursor() as cur:
        for batch in chunked(ids):
            placeholders = ','.join(['%s'] * len(batch))
            cur.execute(
                f"SELECT DISTINCT `id` FROM {table_ref} WHERE `id` IN ({placeholders})",
                tuple(batch),
            )
            existing.update(int(row[0]) for row in cur.fetchall() if row[0] is not None)
    return existing


def replace_table_with_staging(
    conn,
    staging_table,
    target_table,
    db_name,
    *,
    quote_identifier,
    make_staging_table_name,
    drop_table_if_exists,
    table_exists_exact,
    print_fn=print,
):
    """用 staging 表替换 target 表；target 已存在时保留到备份表，替换成功后删除备份。"""
    backup_table = make_staging_table_name(target_table, 'bak')
    drop_table_if_exists(conn, backup_table)
    target_exists = table_exists_exact(conn, target_table)
    staging_ref = quote_identifier(staging_table, "临时表名")
    target_ref = quote_identifier(target_table, "目标表名")
    backup_ref = quote_identifier(backup_table, "备份表名")
    with conn.cursor() as cur:
        if target_exists:
            cur.execute(
                f"RENAME TABLE {target_ref} TO {backup_ref}, "
                f"{staging_ref} TO {target_ref}"
            )
        else:
            cur.execute(f"RENAME TABLE {staging_ref} TO {target_ref}")
    conn.commit()

    if target_exists:
        try:
            drop_table_if_exists(conn, backup_table)
            conn.commit()
        except Exception as e:
            print_fn(f"  ⚠ 新表已生效，但旧备份表 {db_name}.{backup_table} 删除失败: {e}")

