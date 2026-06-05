#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库表复制工具。

支持两类操作：
1. 按表前缀复制一组表的结构和数据。
2. 按 room_id 复制公共配置表的数据，并按规则改写目标字段。

当前脚本默认走统一流程：对每条映射配置依次执行表复制和数据替换。
"""

import argparse
import contextlib
import json
import queue
import sys
import threading
from typing import Dict, List

import mysql.connector
from mysql.connector import Error

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext, ttk
except ImportError:
    tk = None
    filedialog = None
    messagebox = None
    scrolledtext = None
    ttk = None

from config import (
    COPY_TABLE_SUFFIXES,
    DATABASE_CONFIG,
    MAPPINGS,
    MAPPING_DB_CONFIG,
    SKIP_IF_EXISTS_SUFFIXES,
    STRUCTURE_ONLY_SUFFIXES,
    TABLES_WITH_DATA_REPLACEMENT,
    load_mappings_from_db,
)


def build_data_replacement_config_for_mapping(mapping: Dict) -> Dict[str, Dict]:
    """
    根据单条映射生成完整的数据替换配置。

    返回格式示例：
    {
        "game_room_base_config": {
            "room_id": {"source": 1001},
            "type_id": {"target": 2},
        }
    }
    """
    config: Dict[str, Dict] = {}
    source_room_id = mapping["source_room_id"]
    other_rules = mapping.get("other_rules", {})

    for table in TABLES_WITH_DATA_REPLACEMENT:
        rules = {"room_id": {"source": source_room_id}}
        rules.update(other_rules)
        config[table] = rules

    return config


def expand_replacement_for_target(mapping: Dict, target_room_id: int) -> Dict[str, Dict]:
    """
    基于映射配置和目标 room_id 生成一份完整的替换配置。

    这里会把 room_id.target 注入到每张公共表的替换规则中。
    """
    base_config = build_data_replacement_config_for_mapping(mapping)

    for table, rules in base_config.items():
        table_rules = dict(rules)
        room_rule = dict(table_rules.get("room_id", {}))
        room_rule["target"] = target_room_id
        table_rules["room_id"] = room_rule
        base_config[table] = table_rules

    return base_config


class DatabaseTableCopier:
    """数据库表复制器。"""

    def __init__(self, config: Dict):
        self.config = config
        self.connection = None
        self.cursor = None

    def connect(self) -> bool:
        """连接数据库。"""
        try:
            self.connection = mysql.connector.connect(
                host=self.config["host"],
                port=self.config.get("port", 3306),
                user=self.config["user"],
                password=self.config["password"],
                database=self.config["database"],
                charset="utf8mb4",
                autocommit=False,
            )
            self.cursor = self.connection.cursor()
            print(
                f"成功连接数据库: "
                f"{self.config['host']}:{self.config.get('port', 3306)}/{self.config['database']}"
            )
            return True
        except Error as exc:
            print(f"数据库连接失败: {exc}")
            return False

    def disconnect(self) -> None:
        """关闭数据库连接。"""
        if self.cursor:
            self.cursor.close()
        if self.connection:
            self.connection.close()
        print("数据库连接已关闭")

    def get_tables_with_prefix(self, prefix: str) -> List[str]:
        """
        获取指定前缀的表名列表。

        匹配规则：
        1. 表名与前缀完全相同。
        2. 如果前缀本身不以下划线结尾，则要求表名在此前缀后紧跟一个下划线。
        3. 如果前缀本身已经以下划线结尾，则只要求表名以该前缀开头。

        这样 `pg_3` 不会误匹配到 `pg_33_xxx`。
        """
        try:
            if prefix.endswith("_"):
                query = """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = %s
                  AND (
                      table_name = %s
                      OR LEFT(table_name, CHAR_LENGTH(%s)) = %s
                  )
                ORDER BY table_name
                """
                params = (self.config["database"], prefix, prefix, prefix)
            else:
                query = """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = %s
                  AND (
                      table_name = %s
                      OR (
                          LEFT(table_name, CHAR_LENGTH(%s)) = %s
                          AND SUBSTRING(table_name, CHAR_LENGTH(%s) + 1, 1) = '_'
                      )
                  )
                ORDER BY table_name
                """
                params = (self.config["database"], prefix, prefix, prefix, prefix)

            self.cursor.execute(query, params)
            tables = [row[0] for row in self.cursor.fetchall()]
            print(f"找到 {len(tables)} 张以 '{prefix}' 开头的表: {tables}")
            return tables
        except Error as exc:
            print(f"查询表列表失败: {exc}")
            return []

    def table_exists(self, table_name: str) -> bool:
        """检查表是否存在。"""
        try:
            query = """
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_schema = %s
              AND table_name = %s
            """
            self.cursor.execute(query, (self.config["database"], table_name))
            return self.cursor.fetchone()[0] > 0
        except Error as exc:
            print(f"检查表是否存在失败: {exc}")
            return False

    def copy_table_structure(self, source_table: str, target_table: str) -> bool:
        """
        复制表结构。

        如果目标表已经存在：
        - 命中 SKIP_IF_EXISTS_SUFFIXES 时直接跳过；
        - 否则删除后按源表结构重建。
        """
        try:
            if not self.table_exists(source_table):
                print(f"源表不存在，跳过结构复制: {source_table}")
                return False

            if self.table_exists(target_table):
                should_skip = any(
                    target_table.endswith(suffix) for suffix in SKIP_IF_EXISTS_SUFFIXES
                )
                if should_skip:
                    print(f"目标表已存在且命中跳过规则，跳过: {target_table}")
                    return False

                print(f"目标表已存在，先删除后重建: {target_table}")
                self.cursor.execute(f"DROP TABLE `{target_table}`")

            self.cursor.execute(f"CREATE TABLE `{target_table}` LIKE `{source_table}`")
            self.connection.commit()
            print(f"结构复制成功: {source_table} -> {target_table}")
            return True
        except Error as exc:
            print(f"结构复制失败: {source_table} -> {target_table}: {exc}")
            self.connection.rollback()
            return False

    def copy_table_data(self, source_table: str, target_table: str) -> bool:
        """复制整张表的数据。"""
        try:
            if not self.table_exists(source_table):
                print(f"源表不存在，跳过数据复制: {source_table}")
                return False

            if not self.table_exists(target_table):
                print(f"目标表不存在，跳过数据复制: {target_table}")
                return False

            query = f"INSERT INTO `{target_table}` SELECT * FROM `{source_table}`"
            self.cursor.execute(query)
            affected_rows = self.cursor.rowcount
            self.connection.commit()
            print(f"数据复制成功: {source_table} -> {target_table}，影响 {affected_rows} 行")
            return True
        except Error as exc:
            print(f"数据复制失败: {source_table} -> {target_table}: {exc}")
            self.connection.rollback()
            return False

    def get_auto_increment_columns(self, table_name: str) -> List[str]:
        """获取表中的自增字段列表。"""
        try:
            self.cursor.execute(f"DESCRIBE `{table_name}`")
            columns_info = self.cursor.fetchall()
            auto_increment_columns = []

            for column_info in columns_info:
                column_name = column_info[0]
                extra = column_info[5] if len(column_info) > 5 else ""
                if "auto_increment" in extra.lower():
                    auto_increment_columns.append(column_name)

            return auto_increment_columns
        except Error as exc:
            print(f"获取表 {table_name} 的自增字段失败: {exc}")
            return []

    def copy_table_data_with_replacement(
        self,
        source_table: str,
        target_table: str,
        replacement_config: Dict,
        manage_transaction: bool = True,
    ) -> bool:
        """
        按替换规则复制数据。

        注意：
        - `room_id.target` 用于确定目标侧清理范围；
        - 如果表里存在 `type_id`，则会额外要求 `type_id.target`，避免误删同 room_id 的其他类型数据；
        - `type_id` 只用于目标侧清理保护和写入改值，不参与源数据筛选。
        """
        try:
            if not self.table_exists(source_table):
                print(f"源表不存在: {source_table}")
                return False

            if not self.table_exists(target_table):
                print(f"目标表不存在: {target_table}")
                return False

            if not isinstance(replacement_config, dict):
                print("替换配置格式无效，跳过本次复制")
                return False

            self.cursor.execute(f"DESCRIBE `{source_table}`")
            columns = [row[0] for row in self.cursor.fetchall()]

            delete_conditions = []
            delete_params = []

            target_room_rule = replacement_config.get("room_id")
            if not (target_room_rule and "target" in target_room_rule):
                print("缺少 room_id.target，无法安全清理目标数据")
                return False

            delete_conditions.append("`room_id` = %s")
            delete_params.append(target_room_rule["target"])

            if "type_id" in columns:
                target_type_rule = replacement_config.get("type_id")
                if not (target_type_rule and "target" in target_type_rule):
                    print(
                        f"表 {target_table} 包含 type_id，但缺少 type_id.target，"
                        "为避免误删其他类型数据，已跳过"
                    )
                    return False
                delete_conditions.append("`type_id` = %s")
                delete_params.append(target_type_rule["target"])

            delete_sql = f"DELETE FROM `{target_table}` WHERE " + " AND ".join(delete_conditions)
            self.cursor.execute(delete_sql, tuple(delete_params))
            deleted_rows = self.cursor.rowcount
            print(
                f"已清理目标旧数据: {target_table}，条件为 "
                f"{' AND '.join(delete_conditions)}，删除 {deleted_rows} 行"
            )

            auto_increment_columns = self.get_auto_increment_columns(source_table)
            if auto_increment_columns:
                print(f"检测到自增字段: {auto_increment_columns}")

            select_parts = []
            select_params = []
            where_conditions = []
            where_params = []

            for column in columns:
                quoted_column = f"`{column}`"

                if column in replacement_config:
                    rule = replacement_config[column]
                    if "target" not in rule:
                        print(f"字段 {column} 缺少 target 配置")
                        if manage_transaction:
                            self.connection.rollback()
                        return False

                    select_parts.append(f"%s AS {quoted_column}")
                    select_params.append(rule["target"])

                    if column == "type_id":
                        continue

                    if "source" in rule:
                        where_conditions.append(f"{quoted_column} = %s")
                        where_params.append(rule["source"])
                elif column in auto_increment_columns:
                    select_parts.append(f"NULL AS {quoted_column}")
                else:
                    select_parts.append(quoted_column)

            select_clause = ", ".join(select_parts)
            where_clause = " AND ".join(where_conditions) if where_conditions else "1=1"
            query_params = tuple(select_params + where_params)

            query = f"""
            INSERT INTO `{target_table}`
            SELECT {select_clause}
            FROM `{source_table}`
            WHERE {where_clause}
            """

            print(f"开始执行替换复制: {source_table} -> {target_table}")
            self.cursor.execute(query, query_params)
            affected_rows = self.cursor.rowcount

            if affected_rows <= 0:
                if manage_transaction:
                    self.connection.rollback()
                print(
                    f"未插入任何数据，已回滚本次替换复制: "
                    f"{source_table} -> {target_table}"
                )
                return False

            if manage_transaction:
                self.connection.commit()

            print(f"替换复制成功: {source_table} -> {target_table}，写入 {affected_rows} 行")
            return True
        except Error as exc:
            print(f"替换复制失败: {source_table} -> {target_table}: {exc}")
            if manage_transaction:
                self.connection.rollback()
            return False

    def copy_tables(
        self,
        source_prefix: str,
        target_prefix: str,
        structure_only_suffixes: List[str] = None,
        data_replacement_config: Dict = None,
    ) -> Dict[str, int]:
        """
        复制指定前缀下的所有目标表。

        支持：
        - 只复制结构；
        - 复制结构和数据；
        - 复制结构后，对数据做字段替换。
        """
        results = {
            "total_found": 0,
            "structure_copied": 0,
            "data_copied": 0,
            "skipped": 0,
            "failed": 0,
        }

        structure_only_suffixes = structure_only_suffixes or []
        data_replacement_config = data_replacement_config or {}

        all_source_tables = self.get_tables_with_prefix(source_prefix)
        results["total_found"] = len(all_source_tables)

        if not all_source_tables:
            print(f"未找到以 '{source_prefix}' 开头的表")
            return results

        if COPY_TABLE_SUFFIXES:
            source_tables = []
            for source_table in all_source_tables:
                table_suffix = source_table[len(source_prefix):]
                if any(table_suffix.endswith(suffix) for suffix in COPY_TABLE_SUFFIXES):
                    source_tables.append(source_table)
            print(
                f"根据 COPY_TABLE_SUFFIXES 从 {len(all_source_tables)} 张表中筛出 "
                f"{len(source_tables)} 张需要复制的表"
            )
        else:
            source_tables = all_source_tables

        print(f"开始复制，共 {len(source_tables)} 张表")
        print(f"允许复制的后缀: {COPY_TABLE_SUFFIXES if COPY_TABLE_SUFFIXES else '全部'}")
        print(f"仅复制结构的后缀: {structure_only_suffixes}")
        if data_replacement_config:
            print(f"启用数据替换的表: {list(data_replacement_config.keys())}")

        for source_table in source_tables:
            table_suffix = source_table[len(source_prefix):]
            target_table = f"{target_prefix}{table_suffix}"
            should_copy_data = table_suffix not in structure_only_suffixes
            needs_replacement = source_table in data_replacement_config

            copy_mode = "仅复制结构"
            if should_copy_data:
                copy_mode = "结构 + 数据替换" if needs_replacement else "结构 + 数据"

            print(f"处理表: {source_table} -> {target_table} ({copy_mode})")

            if not self.copy_table_structure(source_table, target_table):
                results["skipped"] += 1
                continue

            results["structure_copied"] += 1

            if not should_copy_data:
                print(f"仅复制结构完成: {source_table} -> {target_table}")
                continue

            if needs_replacement:
                ok = self.copy_table_data_with_replacement(
                    source_table,
                    target_table,
                    data_replacement_config[source_table],
                )
            else:
                ok = self.copy_table_data(source_table, target_table)

            if ok:
                results["data_copied"] += 1
            else:
                results["failed"] += 1

        return results

    def copy_tables_data_replacement(self, data_replacement_config: Dict) -> Dict[str, int]:
        """对公共表执行同表数据替换复制。"""
        results = {
            "total_tables": len(data_replacement_config),
            "data_copied": 0,
            "skipped": 0,
            "failed": 0,
        }

        if not data_replacement_config:
            print("没有可执行的数据替换配置")
            return results

        print(f"开始执行数据替换，共 {len(data_replacement_config)} 张表")

        for table, replacement_config in data_replacement_config.items():
            print(f"处理公共表: {table}")
            print(f"  替换配置: {replacement_config}")

            if not self.table_exists(table):
                print(f"表不存在，跳过: {table}")
                results["skipped"] += 1
                continue

            if self.copy_table_data_with_replacement(table, table, replacement_config):
                results["data_copied"] += 1
            else:
                results["failed"] += 1

        return results


def load_config(config_file: str) -> Dict:
    """从 JSON 文件加载数据库配置。"""
    try:
        with open(config_file, "r", encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        print(f"配置文件不存在: {config_file}")
        sys.exit(1)
    except json.JSONDecodeError as exc:
        print(f"配置文件格式错误: {exc}")
        sys.exit(1)


def describe_mapping(mapping: Dict) -> str:
    """生成单条映射的简短说明。"""
    info_parts = []

    source_prefix = mapping.get("source_prefix")
    target_prefixes = mapping.get("target_prefixes") or []
    if source_prefix and target_prefixes:
        info_parts.append(f"表前缀: {source_prefix} -> {', '.join(target_prefixes)}")

    source_room_id = mapping.get("source_room_id")
    target_room_ids = mapping.get("target_room_ids") or []
    if source_room_id is not None and target_room_ids:
        info_parts.append(f"room_id: {source_room_id} -> {', '.join(map(str, target_room_ids))}")

    return " | ".join(info_parts) if info_parts else "无可执行映射"


def show_unified_menu() -> None:
    """显示统一流程菜单。"""
    print("\n" + "=" * 60)
    print("                 数据库表复制工具")
    print("=" * 60)
    print("1. 执行统一流程")
    print("   依次执行表复制和 room_id 数据替换")
    print("0. 退出")
    print("=" * 60)


def get_unified_user_choice() -> int:
    """读取统一流程菜单输入。"""
    while True:
        try:
            choice = input("\n请输入选项 (0-1): ").strip()
            if choice in {"0", "1"}:
                return int(choice)
            print("无效输入，请输入 0 或 1")
        except KeyboardInterrupt:
            print("\n\n程序已退出")
            sys.exit(0)
        except Exception:
            print("输入错误，请重新输入")


def execute_mappings_workflow(
    copier: DatabaseTableCopier,
    mappings: List[Dict],
    enable_table_copy: bool = True,
    enable_data_replacement: bool = True,
) -> Dict[str, Dict[str, int]]:
    """按指定映射执行表复制和数据替换。"""
    print("=== 开始执行统一流程 ===")
    print(f"执行表前缀复制: {'是' if enable_table_copy else '否'}")
    print(f"执行公共表数据替换: {'是' if enable_data_replacement else '否'}")

    copy_totals = {
        "total_found": 0,
        "structure_copied": 0,
        "data_copied": 0,
        "skipped": 0,
        "failed": 0,
    }
    replacement_totals = {
        "total_tables": 0,
        "data_copied": 0,
        "skipped": 0,
        "failed": 0,
    }
    processed_mappings = 0

    if not mappings:
        print("未加载到任何映射配置")
        return {
            "processed_mappings": {"count": processed_mappings},
            "copy_totals": copy_totals,
            "replacement_totals": replacement_totals,
        }

    for index, mapping in enumerate(mappings, start=1):
        has_table_copy = bool(mapping.get("source_prefix") and mapping.get("target_prefixes"))
        has_replacement = bool(
            mapping.get("source_room_id") is not None and mapping.get("target_room_ids")
        )
        should_copy_tables = enable_table_copy and has_table_copy
        should_replace_data = enable_data_replacement and has_replacement

        if not (should_copy_tables or should_replace_data):
            print(f"\n[映射 {index}] 跳过：没有可执行内容")
            continue

        processed_mappings += 1
        print(f"\n[映射 {index}] {describe_mapping(mapping)}")
        print("-" * 60)

        if should_copy_tables:
            source_prefix = mapping["source_prefix"]
            for target_prefix in mapping["target_prefixes"]:
                print(f"\n-> 开始复制表前缀: {source_prefix} -> {target_prefix}")
                results = copier.copy_tables(
                    source_prefix=source_prefix,
                    target_prefix=target_prefix,
                    structure_only_suffixes=STRUCTURE_ONLY_SUFFIXES,
                )
                print(
                    "   结果: "
                    f"找到={results['total_found']}，"
                    f"结构成功={results['structure_copied']}，"
                    f"数据成功={results['data_copied']}，"
                    f"跳过={results['skipped']}，"
                    f"失败={results['failed']}"
                )

                copy_totals["total_found"] += results["total_found"]
                copy_totals["structure_copied"] += results["structure_copied"]
                copy_totals["data_copied"] += results["data_copied"]
                copy_totals["skipped"] += results["skipped"]
                copy_totals["failed"] += results["failed"]

        if should_replace_data:
            source_room_id = mapping["source_room_id"]
            for target_room_id in mapping["target_room_ids"]:
                print(f"\n-> 开始替换公共表数据: room_id {source_room_id} -> {target_room_id}")
                replacement_config = expand_replacement_for_target(mapping, target_room_id)
                results = copier.copy_tables_data_replacement(replacement_config)
                print(
                    "   结果: "
                    f"表数={results['total_tables']}，"
                    f"成功={results['data_copied']}，"
                    f"跳过={results['skipped']}，"
                    f"失败={results['failed']}"
                )

                replacement_totals["total_tables"] += results["total_tables"]
                replacement_totals["data_copied"] += results["data_copied"]
                replacement_totals["skipped"] += results["skipped"]
                replacement_totals["failed"] += results["failed"]

    print("\n" + "=" * 60)
    print("=== 统一流程执行完成 ===")
    print(f"处理的映射数量: {processed_mappings}")
    print(
        "表复制汇总: "
        f"找到={copy_totals['total_found']}，"
        f"结构成功={copy_totals['structure_copied']}，"
        f"数据成功={copy_totals['data_copied']}，"
        f"跳过={copy_totals['skipped']}，"
        f"失败={copy_totals['failed']}"
    )
    print(
        "数据替换汇总: "
        f"表数={replacement_totals['total_tables']}，"
        f"成功={replacement_totals['data_copied']}，"
        f"跳过={replacement_totals['skipped']}，"
        f"失败={replacement_totals['failed']}"
    )
    print("=" * 60)

    return {
        "processed_mappings": {"count": processed_mappings},
        "copy_totals": copy_totals,
        "replacement_totals": replacement_totals,
    }


def execute_unified_workflow(copier: DatabaseTableCopier) -> Dict[str, Dict[str, int]]:
    """按统一流程执行全部映射的表复制和数据替换。"""
    return execute_mappings_workflow(copier, MAPPINGS)


class QueueWriter:
    """把 print 输出转发到 GUI 日志队列。"""

    def __init__(self, log_queue: queue.Queue):
        self.log_queue = log_queue

    def write(self, message: str) -> int:
        if message:
            self.log_queue.put(message)
        return len(message)

    def flush(self) -> None:
        pass


class TableCopierApp:
    """数据库表复制工具的窗口界面。"""

    def __init__(self, root, runtime_config: Dict, config_path: str = None):
        self.root = root
        self.runtime_config = runtime_config
        self.config_path = config_path
        self.mappings = list(MAPPINGS)
        self.worker_thread = None
        self.log_queue = queue.Queue()
        self.ui_queue = queue.Queue()
        self.action_buttons = []

        self.copy_tables_var = tk.BooleanVar(value=True)
        self.replace_data_var = tk.BooleanVar(value=True)
        self.db_info_var = tk.StringVar()
        self.mapping_info_var = tk.StringVar()
        self.rule_info_var = tk.StringVar()
        self.status_var = tk.StringVar(value="就绪")

        self.root.title("游戏玩法数据复制工具")
        self.root.geometry("1120x760")
        self.root.minsize(960, 640)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()
        self._update_header_info()
        self._populate_mapping_tree()
        self._process_queues()

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        main = ttk.Frame(self.root, padding=12)
        main.grid(row=0, column=0, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(2, weight=1)
        main.rowconfigure(3, weight=1)

        title = ttk.Label(main, text="游戏玩法数据复制工具", font=("Microsoft YaHei UI", 16, "bold"))
        title.grid(row=0, column=0, sticky="w")

        info_frame = ttk.LabelFrame(main, text="连接与规则", padding=10)
        info_frame.grid(row=1, column=0, sticky="ew", pady=(10, 8))
        info_frame.columnconfigure(0, weight=1)

        ttk.Label(info_frame, textvariable=self.db_info_var, wraplength=980).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(info_frame, textvariable=self.mapping_info_var, wraplength=980).grid(
            row=1, column=0, sticky="w", pady=(4, 0)
        )
        ttk.Label(info_frame, textvariable=self.rule_info_var, wraplength=980).grid(
            row=2, column=0, sticky="w", pady=(4, 0)
        )

        option_frame = ttk.Frame(info_frame)
        option_frame.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        ttk.Checkbutton(
            option_frame,
            text="复制前缀表",
            variable=self.copy_tables_var,
        ).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(
            option_frame,
            text="替换公共表数据",
            variable=self.replace_data_var,
        ).grid(row=0, column=1, sticky="w", padx=(20, 0))

        button_frame = ttk.Frame(info_frame)
        button_frame.grid(row=4, column=0, sticky="ew", pady=(10, 0))

        self.test_button = ttk.Button(button_frame, text="测试业务库连接", command=self._test_connection)
        self.test_button.grid(row=0, column=0, sticky="w")
        self.action_buttons.append(self.test_button)

        self.refresh_button = ttk.Button(button_frame, text="刷新映射配置", command=self._refresh_mappings)
        self.refresh_button.grid(row=0, column=1, sticky="w", padx=(8, 0))
        self.action_buttons.append(self.refresh_button)

        self.config_button = ttk.Button(button_frame, text="选择业务库配置", command=self._choose_config_file)
        self.config_button.grid(row=0, column=2, sticky="w", padx=(8, 0))
        self.action_buttons.append(self.config_button)

        self.run_selected_button = ttk.Button(
            button_frame,
            text="执行选中映射",
            command=self._execute_selected,
        )
        self.run_selected_button.grid(row=0, column=3, sticky="w", padx=(20, 0))
        self.action_buttons.append(self.run_selected_button)

        self.run_all_button = ttk.Button(button_frame, text="执行全部映射", command=self._execute_all)
        self.run_all_button.grid(row=0, column=4, sticky="w", padx=(8, 0))
        self.action_buttons.append(self.run_all_button)

        ttk.Button(button_frame, text="清空日志", command=self._clear_log).grid(
            row=0, column=5, sticky="w", padx=(20, 0)
        )

        mapping_frame = ttk.LabelFrame(main, text="映射配置", padding=8)
        mapping_frame.grid(row=2, column=0, sticky="nsew", pady=(0, 8))
        mapping_frame.columnconfigure(0, weight=1)
        mapping_frame.rowconfigure(0, weight=1)

        columns = ("index", "table_copy", "room_copy", "type_id")
        self.mapping_tree = ttk.Treeview(
            mapping_frame,
            columns=columns,
            show="headings",
            selectmode="extended",
            height=10,
        )
        self.mapping_tree.heading("index", text="序号")
        self.mapping_tree.heading("table_copy", text="表前缀复制")
        self.mapping_tree.heading("room_copy", text="room_id 替换")
        self.mapping_tree.heading("type_id", text="目标 type_id")
        self.mapping_tree.column("index", width=60, anchor="center", stretch=False)
        self.mapping_tree.column("table_copy", width=380, anchor="w")
        self.mapping_tree.column("room_copy", width=300, anchor="w")
        self.mapping_tree.column("type_id", width=120, anchor="center", stretch=False)

        y_scroll = ttk.Scrollbar(mapping_frame, orient="vertical", command=self.mapping_tree.yview)
        self.mapping_tree.configure(yscrollcommand=y_scroll.set)
        self.mapping_tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")

        log_frame = ttk.LabelFrame(main, text="执行日志", padding=8)
        log_frame.grid(row=3, column=0, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            height=14,
            wrap="word",
            state="disabled",
            font=("Consolas", 10),
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")

        status_bar = ttk.Label(main, textvariable=self.status_var, anchor="w")
        status_bar.grid(row=4, column=0, sticky="ew", pady=(8, 0))

    def _update_header_info(self) -> None:
        db_port = self.runtime_config.get("port", 3306)
        config_source = self.config_path or "内置 DATABASE_CONFIGS['DB1']"
        self.db_info_var.set(
            f"业务库: {self.runtime_config['host']}:{db_port}/"
            f"{self.runtime_config['database']}    配置来源: {config_source}"
        )

        mapping_port = MAPPING_DB_CONFIG.get("port", 3306)
        self.mapping_info_var.set(
            f"映射库: {MAPPING_DB_CONFIG['host']}:{mapping_port}/"
            f"{MAPPING_DB_CONFIG['database']}    当前加载映射: {len(self.mappings)} 条"
        )

        copy_suffixes = ", ".join(COPY_TABLE_SUFFIXES) if COPY_TABLE_SUFFIXES else "全部"
        structure_only = ", ".join(STRUCTURE_ONLY_SUFFIXES) if STRUCTURE_ONLY_SUFFIXES else "无"
        exists_rule = (
            f"命中 {', '.join(SKIP_IF_EXISTS_SUFFIXES)} 时跳过"
            if SKIP_IF_EXISTS_SUFFIXES
            else "目标表存在时删除后重建"
        )
        self.rule_info_var.set(
            f"复制后缀: {copy_suffixes}    仅复制结构: {structure_only}    已存在处理: {exists_rule}"
        )

    def _populate_mapping_tree(self) -> None:
        self.mapping_tree.delete(*self.mapping_tree.get_children())

        for index, mapping in enumerate(self.mappings, start=1):
            source_prefix = mapping.get("source_prefix")
            target_prefixes = mapping.get("target_prefixes") or []
            if source_prefix and target_prefixes:
                table_copy = f"{source_prefix} -> {', '.join(target_prefixes)}"
            else:
                table_copy = "-"

            source_room_id = mapping.get("source_room_id")
            target_room_ids = mapping.get("target_room_ids") or []
            if source_room_id is not None and target_room_ids:
                room_copy = f"{source_room_id} -> {', '.join(map(str, target_room_ids))}"
            else:
                room_copy = "-"

            type_rule = mapping.get("other_rules", {}).get("type_id", {}).get("target")
            type_text = str(type_rule) if type_rule is not None else "-"

            self.mapping_tree.insert(
                "",
                "end",
                iid=str(index - 1),
                values=(index, table_copy, room_copy, type_text),
            )

        if self.mappings:
            first_item = self.mapping_tree.get_children()[0]
            self.mapping_tree.selection_set(first_item)
            self.mapping_tree.focus(first_item)

    def _get_selected_mappings(self) -> List[Dict]:
        selected = []
        for item_id in self.mapping_tree.selection():
            try:
                index = int(item_id)
            except ValueError:
                continue
            if 0 <= index < len(self.mappings):
                selected.append(self.mappings[index])
        return selected

    def _append_log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _set_action_buttons_state(self, state: str) -> None:
        for button in self.action_buttons:
            button.configure(state=state)

    def _process_queues(self) -> None:
        while True:
            try:
                message = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self._append_log(message)

        while True:
            try:
                event = self.ui_queue.get_nowait()
            except queue.Empty:
                break

            event_type = event[0]
            if event_type == "task_done":
                _, title, success = event
                self._set_action_buttons_state("normal")
                self.status_var.set(f"{title}完成" if success else f"{title}失败")
            elif event_type == "mappings_loaded":
                _, mappings = event
                global MAPPINGS
                MAPPINGS = mappings
                self.mappings = list(mappings)
                self._update_header_info()
                self._populate_mapping_tree()

        self.root.after(120, self._process_queues)

    def _start_logged_task(self, title: str, task_func) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showwarning("任务正在执行", "当前任务还没结束，请稍后再操作。")
            return

        self._set_action_buttons_state("disabled")
        self.status_var.set(f"{title}中...")

        self.worker_thread = threading.Thread(
            target=self._run_logged_task,
            args=(title, task_func),
            daemon=True,
        )
        self.worker_thread.start()

    def _run_logged_task(self, title: str, task_func) -> None:
        writer = QueueWriter(self.log_queue)
        success = True
        try:
            with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
                print(f"\n=== {title}开始 ===")
                result = task_func()
                if result is False:
                    success = False
                print(f"=== {title}结束 ===\n")
        except Exception as exc:
            success = False
            self.log_queue.put(f"\n{title}异常: {exc}\n")
        finally:
            self.ui_queue.put(("task_done", title, success))

    def _test_connection(self) -> None:
        runtime_config = dict(self.runtime_config)

        def task() -> bool:
            copier = DatabaseTableCopier(runtime_config)
            try:
                if copier.connect():
                    print("业务库连接测试成功")
                    return True

                print("业务库连接测试失败")
                return False
            finally:
                copier.disconnect()

        self._start_logged_task("测试业务库连接", task)

    def _refresh_mappings(self) -> None:
        def task() -> bool:
            print("正在从 room_copy 读取映射配置...")
            mappings = load_mappings_from_db()
            print(f"映射配置读取完成，共 {len(mappings)} 条")
            self.ui_queue.put(("mappings_loaded", mappings))
            return True

        self._start_logged_task("刷新映射配置", task)

    def _choose_config_file(self) -> None:
        file_path = filedialog.askopenfilename(
            title="选择业务库 JSON 配置",
            filetypes=[("JSON 配置", "*.json"), ("所有文件", "*.*")],
        )
        if not file_path:
            return

        try:
            with open(file_path, "r", encoding="utf-8") as file:
                config = json.load(file)
            for key in ("host", "user", "password", "database"):
                if key not in config:
                    raise ValueError(f"缺少字段: {key}")
        except Exception as exc:
            messagebox.showerror("配置文件错误", f"无法读取配置文件:\n{exc}")
            return

        self.runtime_config = config
        self.config_path = file_path
        self._update_header_info()
        self._append_log(f"已切换业务库配置: {file_path}\n")

    def _execute_selected(self) -> None:
        self._execute_mappings(self._get_selected_mappings(), "执行选中映射")

    def _execute_all(self) -> None:
        self._execute_mappings(list(self.mappings), "执行全部映射")

    def _execute_mappings(self, mappings: List[Dict], title: str) -> None:
        enable_table_copy = bool(self.copy_tables_var.get())
        enable_data_replacement = bool(self.replace_data_var.get())

        if not mappings:
            messagebox.showwarning("没有映射", "请先选择至少一条映射配置。")
            return

        if not (enable_table_copy or enable_data_replacement):
            messagebox.showwarning("没有操作", "请至少勾选一种操作。")
            return

        warning_parts = [f"将执行 {len(mappings)} 条映射。"]
        if enable_table_copy:
            warning_parts.append("表前缀复制会在目标表已存在时删除后重建，除非配置了跳过后缀。")
        if enable_data_replacement:
            warning_parts.append("公共表数据替换会先清理目标 room_id/type_id 的旧数据，再插入新数据。")
        warning_parts.append("确定继续执行吗？")

        if not messagebox.askyesno("确认执行", "\n\n".join(warning_parts), icon="warning"):
            return

        runtime_config = dict(self.runtime_config)
        mappings_to_run = list(mappings)

        def task() -> bool:
            copier = DatabaseTableCopier(runtime_config)
            try:
                if not copier.connect():
                    print("业务库连接失败，任务终止")
                    return False

                print(
                    f"当前业务库: {runtime_config['host']}:{runtime_config.get('port', 3306)}/"
                    f"{runtime_config['database']}"
                )
                execute_mappings_workflow(
                    copier,
                    mappings_to_run,
                    enable_table_copy=enable_table_copy,
                    enable_data_replacement=enable_data_replacement,
                )
                return True
            finally:
                copier.disconnect()

        self._start_logged_task(title, task)

    def _on_close(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showwarning("任务正在执行", "当前任务还没结束，请等待执行完成后再关闭窗口。")
            return
        self.root.destroy()


def run_gui(runtime_config: Dict, config_path: str = None) -> None:
    """打开窗口界面。"""
    if tk is None:
        print("当前 Python 环境不可用 Tkinter，已切换为命令行模式")
        run_cli(runtime_config)
        return

    root = tk.Tk()
    TableCopierApp(root, runtime_config, config_path=config_path)
    root.mainloop()


def run_cli(runtime_config: Dict) -> None:
    """运行旧版命令行菜单。"""
    print("使用命令行模式")

    copier = DatabaseTableCopier(runtime_config)

    try:
        if not copier.connect():
            sys.exit(1)

        print("\n当前运行配置:")
        print(
            f"  数据库: {runtime_config['host']}:"
            f"{runtime_config.get('port', 3306)}/{runtime_config['database']}"
        )
        print("  映射配置:")
        if not MAPPINGS:
            print("    未加载到映射配置")
        else:
            for index, mapping in enumerate(MAPPINGS, start=1):
                print(f"    [{index}] {describe_mapping(mapping)}")

        while True:
            show_unified_menu()
            choice = get_unified_user_choice()

            if choice == 0:
                print("\n程序已退出")
                break

            print("\n开始执行统一流程...")
            execute_unified_workflow(copier)

            while True:
                continue_choice = input("\n是否继续执行其他任务？(y/n): ").strip().lower()
                if continue_choice in {"y", "yes"}:
                    break
                if continue_choice in {"n", "no"}:
                    print("\n程序已退出")
                    return
                print("请输入 y 或 n")
    except KeyboardInterrupt:
        print("\n\n程序已退出")
    except Exception as exc:
        print(f"程序执行出错: {exc}")
        sys.exit(1)
    finally:
        copier.disconnect()


def main() -> None:
    """脚本入口。"""
    parser = argparse.ArgumentParser(description="数据库表复制工具")
    parser.add_argument("--config", "-c", help="JSON 配置文件路径，可选")
    parser.add_argument("--cli", action="store_true", help="使用命令行菜单")
    args = parser.parse_args()

    if args.config:
        runtime_config = load_config(args.config)
        print(f"使用外部配置文件: {args.config}")
    else:
        runtime_config = DATABASE_CONFIG
        print("使用内置数据库配置")

    if args.cli:
        run_cli(runtime_config)
    else:
        run_gui(runtime_config, config_path=args.config)


if __name__ == "__main__":
    main()
