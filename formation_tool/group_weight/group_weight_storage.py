"""group_weight table storage helpers."""

from formation_tool.utils import log_utils

print = log_utils.emit


def create_group_weight_table_if_needed(conn, table_name, *, quote_identifier):
    """按约定结构创建 group_weight 表。"""
    table_ref = quote_identifier(table_name, "group_weight表名")
    with conn.cursor() as cur:
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {table_ref} (
              `id` bigint UNSIGNED NOT NULL AUTO_INCREMENT,
              `game_type` int NULL DEFAULT NULL,
              `group_id` int NULL DEFAULT NULL,
              `rebate` bigint NOT NULL DEFAULT 0,
              `weight` int NULL DEFAULT NULL,
              PRIMARY KEY (`id`) USING BTREE
            ) ENGINE = InnoDB
              CHARACTER SET = utf8mb4
              COLLATE = utf8mb4_general_ci
              ROW_FORMAT = Dynamic
        """)


def replace_group_weight_rows_atomically(conn, table_name, rows, db_name, *, deps):
    """先写临时 group_weight 表，校验通过后再替换正式表。"""
    staging_table = deps.make_staging_table_name(table_name, 'tmp')
    try:
        deps.drop_table_if_exists(conn, staging_table)
        deps.create_group_weight_table_if_needed(conn, staging_table)
        staging_ref = deps.quote_identifier(staging_table, "临时group_weight表名")
        with conn.cursor() as cur:
            cur.executemany(
                f"""
                INSERT INTO {staging_ref} (`game_type`, `group_id`, `rebate`, `weight`)
                VALUES (%s, %s, %s, %s)
                """,
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


def normalize_group_weight_rows(rows):
    """排序 group_weight 结果，并拦截重复 game_type/group_id/rebate。"""
    normalized = []
    seen = set()
    duplicates = []
    for game_type, group_id, rebate, weight in rows:
        row = (int(game_type), int(group_id), int(rebate), int(weight))
        key = row[:3]
        if key in seen:
            duplicates.append(key)
        seen.add(key)
        normalized.append(row)
    if duplicates:
        preview = sorted(set(duplicates))[:20]
        suffix = "..." if len(set(duplicates)) > 20 else ""
        raise ValueError(
            "group_weight 存在重复 game_type/group_id/rebate，"
            f"请检查购买局/ex局 game_type 或规则重叠：{preview}{suffix}"
        )
    return sorted(normalized, key=lambda item: (item[0], item[1], item[2], item[3]))


def read_rebate_config_values(conn, table_name, *, quote_identifier):
    """读取已生成采样配置表中的 rebate 列。"""
    table_ref = quote_identifier(table_name, "采样配置表名")
    with conn.cursor() as cur:
        cur.execute(f"SELECT DISTINCT `rebate` FROM {table_ref} ORDER BY `rebate`")
        return [int(row[0]) for row in cur.fetchall() if row[0] is not None]


def verify_group_weight_zero_rebate_rows(write_conn, table_name, rows, *, deps):
    """写入后校验需要反推 rebate=0 的类型是否落表。"""
    zero_check_types = (1, 2, 6, 7, 8)
    table_ref = deps.quote_identifier(table_name, "group_weight表名")
    with write_conn.cursor() as cur:
        for check_type in zero_check_types:
            expected_rows = sum(
                1 for game_type, _group_id, rebate, weight in rows
                if game_type == check_type and rebate == 0 and weight > 0
            )
            cur.execute(
                f"SELECT COUNT(*) FROM {table_ref} WHERE `game_type` = %s AND `rebate` = 0",
                (check_type,),
            )
            actual_rows = int(cur.fetchone()[0])
            mode_name = deps.game_type_names.get(str(check_type), f"game_type={check_type}")
            print(f"{mode_name} rebate=0 校验：预期写入 {expected_rows} 条，实际表内 {actual_rows} 条")
            if expected_rows != actual_rows:
                print(f"  ⚠ {mode_name} rebate=0 写入数量不一致，请检查数据库写入结果")

