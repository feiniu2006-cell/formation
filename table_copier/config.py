# -*- coding: utf-8 -*-
"""
table_copier 的配置文件。

这里主要负责三件事：
1. 提供业务库和映射库连接配置。
2. 维护表复制相关的后缀规则。
3. 从 `room_copy` 表动态加载运行时映射。
"""

import os
import sys

import mysql.connector
from mysql.connector import Error

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from db_config import DATABASE_CONFIGS

# ==================== 数据库连接配置 ====================
DATABASE_CONFIG = DATABASE_CONFIGS["DB1"]  # 业务数据库
MAPPING_DB_CONFIG = DATABASE_CONFIGS["MY"]  # 映射配置库，room_copy 表位于此库

# ==================== 表复制规则 ====================
# 如果 COPY_TABLE_SUFFIXES 为空列表，则复制前缀命中的全部表。
# 如果配置了后缀，则只复制这些后缀结尾的表。
COPY_TABLE_SUFFIXES = [
    "_group_weight",
    "_formation",
    "_free_formation",
    "_special_formation",
    # "_personal_rebate_profile",
    # "_bet_history",
]

# 这些后缀只复制结构，不复制数据。
STRUCTURE_ONLY_SUFFIXES = [
    # "_bet_history",
    # "_group_weight",
    # "_formation",
    # "_free_formation",
    # "_special_formation",
    # "_personal_rebate_profile",
]

# 这些后缀的目标表如果已经存在，则直接跳过，不删除旧表。
SKIP_IF_EXISTS_SUFFIXES = [
    # "_group_weight",
    # "_personal_rebate_profile",
    # "_formation",
    # "_free_formation",
    # "_special_formation",
    # "_bet_history",
    # "_log_table",
    # "_temp_table",
]

# ==================== 运行时映射说明 ====================
# 每条映射可以只做其中一种操作，也可以两种都做：
# 1. 表前缀复制：
#    {
#        "source_prefix": "vg_3013",
#        "target_prefixes": ["vg_3041", "vg_3042"]
#    }
#
# 2. 公共表数据替换：
#    {
#        "source_room_id": 3013,
#        "target_room_ids": [3041, 3042],
#        "other_rules": {"type_id": {"target": 2}}
#    }
#
# 3. 同时包含两类操作：
#    {
#        "source_prefix": "vg_3013",
#        "target_prefixes": ["vg_3041"],
#        "source_room_id": 3013,
#        "target_room_ids": [3041],
#        "other_rules": {"type_id": {"target": 2}}
#    }
#
# 说明：
# - type_id 是目标侧规则，只用于公共表清理保护和写入改值；
# - type_id 不参与源数据筛选。


def _split_to_list(value):
    """把逗号或分号分隔的值拆成列表。"""
    if value is None:
        return []

    if isinstance(value, (int, float)):
        return [value]

    text = str(value).strip()
    if not text:
        return []

    normalized = text.replace("，", ",").replace("；", ",").replace(";", ",")
    return [part.strip() for part in normalized.split(",") if part.strip()]


def load_mappings_from_db():
    """
    从映射库的 room_copy 表加载运行时映射。

    字段约定：
    - source_prefix: 源表前缀
    - target_prefixes: 目标表前缀列表，支持逗号分隔
    - source_room_id: 源 room_id
    - target_room_ids: 目标 room_id 列表，支持逗号分隔
    - type_id: 目标 type_id，会映射到 other_rules.type_id.target
    - on-off: 是否启用该条映射
    """
    mappings = []
    conn = None
    cursor = None

    try:
        conn = mysql.connector.connect(
            host=MAPPING_DB_CONFIG["host"],
            port=MAPPING_DB_CONFIG.get("port", 3306),
            user=MAPPING_DB_CONFIG["user"],
            password=MAPPING_DB_CONFIG["password"],
            database=MAPPING_DB_CONFIG["database"],
            charset="utf8mb4",
        )
        cursor = conn.cursor(dictionary=True)

        query = """
        SELECT
            source_prefix,
            target_prefixes,
            source_room_id,
            target_room_ids,
            type_id,
            `on-off` AS on_off
        FROM room_copy
        WHERE `on-off` = 1
        """
        cursor.execute(query)
        rows = cursor.fetchall()

        for row in rows:
            mapping = {}

            source_prefix = row.get("source_prefix")
            target_prefixes = [str(value) for value in _split_to_list(row.get("target_prefixes"))]
            source_room_id = row.get("source_room_id")
            type_id = row.get("type_id")

            target_room_ids = []
            for value in _split_to_list(row.get("target_room_ids")):
                try:
                    target_room_ids.append(int(value))
                except (TypeError, ValueError):
                    continue

            if source_prefix:
                mapping["source_prefix"] = str(source_prefix)
            if target_prefixes:
                mapping["target_prefixes"] = target_prefixes

            if source_room_id is not None:
                mapping["source_room_id"] = int(source_room_id)
            if target_room_ids:
                mapping["target_room_ids"] = target_room_ids

            other_rules = {}
            if type_id is not None:
                other_rules["type_id"] = {"target": int(type_id)}
            if other_rules:
                mapping["other_rules"] = other_rules

            has_table_copy = bool(mapping.get("source_prefix") and mapping.get("target_prefixes"))
            has_replacement = bool(
                mapping.get("source_room_id") is not None and mapping.get("target_room_ids")
            )
            if has_table_copy or has_replacement:
                mappings.append(mapping)

    except Error as exc:
        print(f"从 room_copy 读取 MAPPINGS 失败: {exc}")
    finally:
        try:
            if cursor:
                cursor.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass

    return mappings


# 运行时动态加载映射配置
MAPPINGS = load_mappings_from_db()

# 需要做公共表数据替换的表
TABLES_WITH_DATA_REPLACEMENT = [
    "game_bet_amount_config",
    "game_room_base_config",
    "game_room_element_config",
    "game_room_group_config",
    "game_room_win_line_config",
    "game_group_free_game_config",
    "game_group_special_weight_config",
]
