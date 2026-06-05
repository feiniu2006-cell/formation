"""Storage helpers for rebate_count sampling configuration tables."""

from formation_tool.utils import log_utils

print = log_utils.emit


def create_rebate_config_table_if_needed(conn, table_name, *, quote_identifier):
    table_ref = quote_identifier(table_name, "采样配置表名")
    with conn.cursor() as cur:
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {table_ref} (
                `rebate` int NULL DEFAULT NULL,
                `count`  int NULL DEFAULT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)


def replace_rebate_config_rows_atomically(conn, table_name, rows, db_name, *, deps):
    staging_table = deps.make_staging_table_name(table_name, 'tmp')
    try:
        deps.drop_table_if_exists(conn, staging_table)
        deps.create_rebate_config_table_if_needed(conn, staging_table)
        staging_ref = deps.quote_identifier(staging_table, "临时采样配置表名")
        with conn.cursor() as cur:
            if rows:
                cur.executemany(
                    f"INSERT INTO {staging_ref} (`rebate`, `count`) VALUES (%s, %s)",
                    rows,
                )
        conn.commit()

        staging_count = deps.count_table_rows(conn, staging_table)
        if staging_count != len(rows):
            raise RuntimeError(
                f"临时表写入数量不一致：预期 {len(rows)}，实际 {staging_count}"
            )

        deps.replace_table_with_staging(conn, staging_table, table_name, db_name)
        return staging_count
    except Exception:
        deps.rollback_safely(conn)
        with deps.suppress_exceptions():
            deps.drop_table_if_exists(conn, staging_table)
            conn.commit()
        raise


def write_rebate_config_rows(table_config, config_tbl, config_db_name, result_rows, *, deps):
    config_conn = None
    try:
        config_conn = deps.connect_by_table('REBATE_CONFIG_TABLE', table_config)
        if not config_conn:
            print(f"无法连接 {config_db_name}，写入终止")
            return False
        written = deps.replace_rebate_config_rows_atomically(
            config_conn,
            config_tbl,
            result_rows,
            config_db_name,
        )
        deps.print_write_complete(written, f"{config_db_name}.{config_tbl}")
        return True
    except Exception as exc:
        deps.print_step_error("写入失败", exc)
        deps.rollback_safely(config_conn)
        return False
    finally:
        deps.close_safely(config_conn)
