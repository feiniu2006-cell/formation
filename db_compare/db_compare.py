#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compare selected MySQL tables between two database configurations."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import queue
import runpy
import sys
import threading
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Generator, Iterable

import mysql.connector
from mysql.connector import Error

try:
    import tkinter as tk
    from tkinter import messagebox, scrolledtext, ttk
except ImportError:
    tk = None
    messagebox = None
    scrolledtext = None
    ttk = None


CONFIG_FILE_NAME = "db_config.example.json"
DEFAULT_SOURCE_KEY = "DB1"
DEFAULT_TARGET_KEY = "waiwang"
DEFAULT_BATCH_SIZE = 1000
DEFAULT_SAMPLE_LIMIT = 20
CANCELLED_EXIT_CODE = 130


class CompareCancelled(RuntimeError):
    """Raised when the user requests the running comparison to stop."""


def check_cancelled(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise CompareCancelled("用户已停止对比任务。")


@dataclass(frozen=True)
class TablePair:
    source_table: str
    target_table: str


@dataclass
class CompareResult:
    pair: TablePair
    same: bool
    issues: list[str]


class QueueWriter:
    def __init__(self, log_queue: queue.Queue):
        self.log_queue = log_queue

    def write(self, message: str) -> int:
        if message:
            self.log_queue.put(message)
        return len(message)

    def flush(self) -> None:
        pass


def get_app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def write_result_report(content: str) -> Path:
    reports_dir = get_app_dir() / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / "db_compare_result.json"
    report_path.write_text(content, encoding="utf-8")
    return report_path


def load_database_configs() -> dict[str, dict[str, Any]]:
    config_path = get_app_dir() / CONFIG_FILE_NAME
    if config_path.is_file():
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"配置文件不是有效 JSON: {config_path}\n{exc}") from exc
        configs = payload.get("DATABASE_CONFIGS", payload)
    else:
        project_config = get_app_dir().parent / "db_config.py"
        if not project_config.is_file():
            raise RuntimeError(
                f"找不到数据库配置。请在 {config_path} 放置 JSON 配置，"
                f"或确认项目根目录存在 db_config.py。"
            )
        namespace = runpy.run_path(str(project_config))
        configs = namespace.get("DATABASE_CONFIGS")

    if not isinstance(configs, dict) or not configs:
        raise RuntimeError("数据库配置为空或格式错误。")
    return configs


def require_db_config(configs: dict[str, dict[str, Any]], key: str) -> dict[str, Any]:
    config = configs.get(key)
    if not isinstance(config, dict):
        raise RuntimeError(f"数据库配置不存在: {key}")
    missing = [field for field in ("host", "user", "password", "database") if not config.get(field)]
    if missing:
        raise RuntimeError(f"{key} 缺少必要字段: {', '.join(missing)}")
    return dict(config)


def parse_table_pairs(raw_tables: str) -> list[TablePair]:
    pairs: list[TablePair] = []
    for raw_part in raw_tables.replace("；", ",").replace(";", ",").split(","):
        part = raw_part.strip()
        if not part:
            continue
        if ":" in part:
            left, right = [item.strip() for item in part.split(":", 1)]
        else:
            left = right = part
        if not left or not right:
            raise RuntimeError(f"表名格式错误: {part}")
        pairs.append(TablePair(left, right))
    if not pairs:
        raise RuntimeError("请至少输入一张表名。")
    return pairs


def quote_identifier(name: str) -> str:
    if not name or "\x00" in name:
        raise RuntimeError(f"非法表名: {name!r}")
    return "`" + name.replace("`", "``") + "`"


def connect_database(config: dict[str, Any]):
    return mysql.connector.connect(
        host=config["host"],
        port=int(config.get("port", 3306)),
        user=config["user"],
        password=config["password"],
        database=config["database"],
        charset="utf8mb4",
        autocommit=True,
        use_pure=True,
    )


class DatabaseInspector:
    def __init__(self, label: str, config: dict[str, Any]):
        self.label = label
        self.config = config
        self.connection = None

    def connect(self) -> None:
        self.connection = connect_database(self.config)

    def close(self) -> None:
        if self.connection:
            self.connection.close()

    def table_exists(self, table_name: str) -> bool:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM information_schema.tables
                WHERE table_schema = %s AND table_name = %s
                """,
                (self.config["database"], table_name),
            )
            return cursor.fetchone()[0] > 0

    def list_tables(self) -> list[dict[str, Any]]:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT table_name, table_rows
                FROM information_schema.tables
                WHERE table_schema = %s
                  AND table_type = 'BASE TABLE'
                ORDER BY table_name
                """,
                (self.config["database"],),
            )
            return list(cursor.fetchall())

    def get_columns(self, table_name: str) -> list[dict[str, Any]]:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT,
                       COLUMN_KEY, EXTRA, CHARACTER_SET_NAME, COLLATION_NAME
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                ORDER BY ORDINAL_POSITION
                """,
                (self.config["database"], table_name),
            )
            return list(cursor.fetchall())

    def get_primary_key_columns(self, table_name: str) -> list[str]:
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT COLUMN_NAME
                FROM information_schema.key_column_usage
                WHERE table_schema = %s
                  AND table_name = %s
                  AND constraint_name = 'PRIMARY'
                ORDER BY ORDINAL_POSITION
                """,
                (self.config["database"], table_name),
            )
            return [str(row["COLUMN_NAME"]) for row in cursor.fetchall()]

    def count_rows(self, table_name: str) -> int:
        with self.connection.cursor() as cursor:
            cursor.execute(f"SELECT COUNT(*) FROM {quote_identifier(table_name)}")
            return int(cursor.fetchone()[0])

    def iter_rows(
        self,
        table_name: str,
        columns: list[str],
        order_columns: list[str],
        batch_size: int,
        limit: int | None = None,
        descending: bool = False,
        cancel_event: threading.Event | None = None,
    ) -> Generator[tuple[Any, ...], None, None]:
        check_cancelled(cancel_event)
        select_columns = ", ".join(quote_identifier(column) for column in columns)
        direction = " DESC" if descending else ""
        order_clause = ", ".join(f"{quote_identifier(column)}{direction}" for column in order_columns)
        sql = f"SELECT {select_columns} FROM {quote_identifier(table_name)} ORDER BY {order_clause}"
        if limit is not None:
            sql += f" LIMIT {max(0, int(limit))}"
        cursor = self.connection.cursor(raw=False, buffered=False)
        try:
            cursor.execute(sql)
            while True:
                check_cancelled(cancel_event)
                rows = cursor.fetchmany(batch_size)
                if not rows:
                    break
                for row in rows:
                    check_cancelled(cancel_event)
                    yield tuple(row)
        finally:
            try:
                if getattr(cursor, "with_rows", False):
                    cursor.fetchall()
            except Error:
                reset = getattr(cursor, "reset", None)
                if callable(reset):
                    with contextlib.suppress(Exception):
                        reset()
            with contextlib.suppress(Exception):
                cursor.close()


def normalize_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        return {"__bytes__": bytes(value).hex()}
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def row_fingerprint(row: tuple[Any, ...]) -> str:
    payload = [normalize_value(value) for value in row]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def table_digest(
    inspector: DatabaseInspector,
    table_name: str,
    columns: list[str],
    order_columns: list[str],
    batch_size: int,
    limit: int | None = None,
    descending: bool = False,
    cancel_event: threading.Event | None = None,
) -> str:
    digest = hashlib.sha256()
    for row in inspector.iter_rows(
        table_name,
        columns,
        order_columns,
        batch_size,
        limit=limit,
        descending=descending,
        cancel_event=cancel_event,
    ):
        digest.update(row_fingerprint(row).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def choose_identity_columns(column_names: list[str], primary_key: list[str]) -> list[str]:
    if primary_key:
        return primary_key
    id_column = next((column for column in column_names if column.lower() == "id"), None)
    return [id_column] if id_column else []


def identity_prefix_matches(
    source: DatabaseInspector,
    target: DatabaseInspector,
    pair: TablePair,
    identity_columns: list[str],
    prefix_count: int,
    batch_size: int,
    cancel_event: threading.Event | None = None,
) -> bool:
    if prefix_count <= 0:
        return True
    source_digest = table_digest(
        source,
        pair.source_table,
        identity_columns,
        identity_columns,
        batch_size,
        limit=prefix_count,
        cancel_event=cancel_event,
    )
    target_digest = table_digest(
        target,
        pair.target_table,
        identity_columns,
        identity_columns,
        batch_size,
        limit=prefix_count,
        cancel_event=cancel_event,
    )
    return source_digest == target_digest


def identity_suffix_matches(
    source: DatabaseInspector,
    target: DatabaseInspector,
    pair: TablePair,
    identity_columns: list[str],
    suffix_count: int,
    batch_size: int,
    cancel_event: threading.Event | None = None,
) -> bool:
    if suffix_count <= 0:
        return True
    source_digest = table_digest(
        source,
        pair.source_table,
        identity_columns,
        identity_columns,
        batch_size,
        limit=suffix_count,
        descending=True,
        cancel_event=cancel_event,
    )
    target_digest = table_digest(
        target,
        pair.target_table,
        identity_columns,
        identity_columns,
        batch_size,
        limit=suffix_count,
        descending=True,
        cancel_event=cancel_event,
    )
    return source_digest == target_digest


def compare_columns(left_columns: list[dict[str, Any]], right_columns: list[dict[str, Any]]) -> list[str]:
    issues: list[str] = []
    left_names = [row["COLUMN_NAME"] for row in left_columns]
    right_names = [row["COLUMN_NAME"] for row in right_columns]
    if left_names != right_names:
        issues.append("表结构不同（字段不一致）")
    return issues


def compare_table(
    source: DatabaseInspector,
    target: DatabaseInspector,
    pair: TablePair,
    *,
    structure_only: bool,
    quick_compare: bool,
    batch_size: int,
    cancel_event: threading.Event | None = None,
) -> CompareResult:
    check_cancelled(cancel_event)
    issues: list[str] = []

    source_exists = source.table_exists(pair.source_table)
    check_cancelled(cancel_event)
    target_exists = target.table_exists(pair.target_table)
    if not source_exists or not target_exists:
        if not source_exists:
            issues.append(f"源表不存在: {pair.source_table}")
        if not target_exists:
            issues.append(f"目标表不存在: {pair.target_table}")
        return CompareResult(pair, False, issues)

    source_columns = source.get_columns(pair.source_table)
    check_cancelled(cancel_event)
    target_columns = target.get_columns(pair.target_table)
    structure_issues = compare_columns(source_columns, target_columns)
    issues.extend(structure_issues)

    if structure_only:
        return CompareResult(pair, not issues, issues)

    column_names = [str(row["COLUMN_NAME"]) for row in source_columns]
    primary_key: list[str] = []
    target_primary_key: list[str] = []
    identity_columns: list[str] = []
    if not structure_issues:
        primary_key = source.get_primary_key_columns(pair.source_table)
        target_primary_key = target.get_primary_key_columns(pair.target_table)
        if primary_key == target_primary_key:
            identity_columns = choose_identity_columns(column_names, primary_key)

    source_count = source.count_rows(pair.source_table)
    check_cancelled(cancel_event)
    target_count = target.count_rows(pair.target_table)
    if source_count != target_count:
        if structure_issues:
            return CompareResult(pair, False, issues)
        if primary_key != target_primary_key:
            issues.append("ID不同（主键定义不同）")
            return CompareResult(pair, False, issues)
        if identity_columns:
            shared_count = min(source_count, target_count)
            added_count = abs(source_count - target_count)
            if identity_prefix_matches(
                source,
                target,
                pair,
                identity_columns,
                shared_count,
                batch_size,
                cancel_event=cancel_event,
            ):
                if target_count > source_count:
                    issues.append(
                        f"目标表后面新增数据（新增 {added_count} 行，前 {shared_count} 个ID相同）"
                    )
                else:
                    issues.append(
                        f"源表后面新增数据（新增 {added_count} 行，前 {shared_count} 个ID相同）"
                    )
            elif identity_suffix_matches(
                source,
                target,
                pair,
                identity_columns,
                shared_count,
                batch_size,
                cancel_event=cancel_event,
            ):
                if target_count > source_count:
                    issues.append(
                        f"目标表前面新增数据（新增 {added_count} 行，后 {shared_count} 个ID相同）"
                    )
                else:
                    issues.append(
                        f"源表前面新增数据（新增 {added_count} 行，后 {shared_count} 个ID相同）"
                    )
            else:
                issues.append(
                    f"ID不同（按 {', '.join(identity_columns)} 判断；源表 {source_count} 行，目标表 {target_count} 行）"
                )
        else:
            issues.append(
                f"数据量不同（源表 {source_count} 行，目标表 {target_count} 行；未找到主键或 id 字段，无法判断是否新增）"
            )
        return CompareResult(pair, False, issues)

    if structure_issues:
        return CompareResult(pair, False, issues)

    if primary_key != target_primary_key:
        issues.append("ID不同（主键定义不同）")
        return CompareResult(pair, False, issues)
    else:
        identity_columns = choose_identity_columns(column_names, primary_key)
        order_columns = identity_columns or column_names

    if not column_names:
        return CompareResult(pair, not issues, issues)

    if identity_columns:
        source_id_digest = table_digest(
            source,
            pair.source_table,
            identity_columns,
            identity_columns,
            batch_size,
            cancel_event=cancel_event,
        )
        target_id_digest = table_digest(
            target,
            pair.target_table,
            identity_columns,
            identity_columns,
            batch_size,
            cancel_event=cancel_event,
        )
        if source_id_digest != target_id_digest:
            issues.append(f"ID不同（按 {', '.join(identity_columns)} 判断）")
            return CompareResult(pair, False, issues)
    elif quick_compare:
        issues.append("无法快速对比ID（未找到主键或 id 字段）")
        return CompareResult(pair, False, issues)

    if quick_compare:
        return CompareResult(pair, not issues, issues)

    source_digest = table_digest(
        source,
        pair.source_table,
        column_names,
        order_columns,
        batch_size,
        cancel_event=cancel_event,
    )
    target_digest = table_digest(
        target,
        pair.target_table,
        column_names,
        order_columns,
        batch_size,
        cancel_event=cancel_event,
    )
    if source_digest != target_digest:
        if identity_columns:
            issues.append("数据内容不同（ID一致，字段值不同）")
        else:
            issues.append("数据内容不同（未找到主键或 id 字段）")

    return CompareResult(pair, not issues, issues)


def get_difference_type(issue: str) -> str:
    if "源表不存在" in issue or "目标表不存在" in issue:
        return "表不存在"
    if "表结构不同" in issue:
        return "表结构不同"
    if "目标表后面新增数据" in issue:
        return "目标表后面新增数据"
    if "源表后面新增数据" in issue:
        return "源表后面新增数据"
    if "目标表前面新增数据" in issue:
        return "目标表前面新增数据"
    if "源表前面新增数据" in issue:
        return "源表前面新增数据"
    if "数据量不同" in issue:
        return "数据量不同"
    if "ID不同" in issue:
        return "ID不同"
    if "无法快速对比ID" in issue:
        return "无法快速对比ID"
    if "数据内容不同" in issue:
        return "数据内容不同"
    return "其他不同"


def result_table_label(result: CompareResult) -> str:
    if result.pair.source_table == result.pair.target_table:
        return result.pair.source_table
    return f"{result.pair.source_table} -> {result.pair.target_table}"


def result_issue_label(result: CompareResult, issue: str | None = None) -> str:
    table_label = result_table_label(result)
    if issue:
        return f"{table_label}：{issue}"
    return table_label


def build_compare_report(
    args: argparse.Namespace,
    results: list[CompareResult],
) -> dict[str, Any]:
    different_by_type: dict[str, list[str]] = {
        "表不存在": [],
        "表结构不同": [],
        "目标表后面新增数据": [],
        "源表后面新增数据": [],
        "目标表前面新增数据": [],
        "源表前面新增数据": [],
        "数据量不同": [],
        "ID不同": [],
        "无法快速对比ID": [],
        "数据内容不同": [],
        "其他不同": [],
    }
    same_tables = []

    for result in results:
        if result.same:
            same_tables.append(result_table_label(result))
            continue

        issue_by_type = {}
        for issue in result.issues:
            difference_type = get_difference_type(issue)
            issue_by_type.setdefault(difference_type, issue)
        if not issue_by_type:
            issue_by_type["其他不同"] = None

        for difference_type, issue in issue_by_type.items():
            different_by_type.setdefault(difference_type, []).append(
                result_issue_label(result, issue)
            )

    different_by_type = {
        difference_type: tables
        for difference_type, tables in different_by_type.items()
        if tables
    }

    return {
        "summary": {
            "total": len(results),
            "same": len(same_tables),
            "different": len(results) - len(same_tables),
        },
        "一致": same_tables,
        "不一致": different_by_type,
    }


def compare_and_build_report(
    args: argparse.Namespace,
    cancel_event: threading.Event | None = None,
) -> tuple[int, dict[str, Any]]:
    configs = load_database_configs()
    source_config = require_db_config(configs, args.source_key)
    target_config = require_db_config(configs, args.target_key)
    pairs = parse_table_pairs(args.tables)

    source = DatabaseInspector(args.source_key, source_config)
    target = DatabaseInspector(args.target_key, target_config)
    if cancel_event is not None:
        setattr(cancel_event, "db_inspectors", (source, target))
    try:
        check_cancelled(cancel_event)
        source.connect()
        check_cancelled(cancel_event)
        target.connect()

        results = []
        for pair in pairs:
            check_cancelled(cancel_event)
            results.append(
                compare_table(
                    source,
                    target,
                    pair,
                    structure_only=args.structure_only,
                    quick_compare=args.quick_compare,
                    batch_size=args.batch_size,
                    cancel_event=cancel_event,
                )
            )
    finally:
        source.close()
        target.close()
        if cancel_event is not None:
            with contextlib.suppress(Exception):
                delattr(cancel_event, "db_inspectors")

    report = build_compare_report(args, results)
    return_code = 0 if report["summary"]["different"] == 0 else 2
    return return_code, report


def run_compare(args: argparse.Namespace) -> int:
    return_code, report = compare_and_build_report(args)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return return_code


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="数据库对比工具")
    parser.add_argument("--source-key", default=DEFAULT_SOURCE_KEY, help="源数据库配置名")
    parser.add_argument("--target-key", default=DEFAULT_TARGET_KEY, help="目标数据库配置名")
    parser.add_argument("--tables", default="", help="要对比的表，逗号分隔，支持 source:target")
    parser.add_argument("--structure-only", action="store_true", help="只对比表结构，不对比数据")
    parser.add_argument("--full-compare", action="store_true", help="完整对比字段值内容；默认只快速对比行数和ID")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="逐行读取批量大小")
    parser.add_argument("--sample-limit", type=int, default=DEFAULT_SAMPLE_LIMIT, help=argparse.SUPPRESS)
    parser.add_argument("--cli", action="store_true", help="使用命令行模式")
    args = parser.parse_args(argv)
    if args.batch_size <= 0:
        parser.error("--batch-size 必须大于 0")
    args.quick_compare = not args.full_compare
    return args


class DbCompareApp:
    def __init__(self, root, initial_args: argparse.Namespace):
        self.root = root
        self.initial_args = initial_args
        self.worker_thread = None
        self.cancel_event: threading.Event | None = None
        self.log_queue = queue.Queue()
        self.ui_queue = queue.Queue()
        self.controls = []

        configs = load_database_configs()
        config_keys = sorted(configs.keys())
        self.source_key_var = tk.StringVar(value=initial_args.source_key if initial_args.source_key in configs else config_keys[0])
        self.target_key_var = tk.StringVar(value=initial_args.target_key if initial_args.target_key in configs else config_keys[-1])
        self.tables_var = tk.StringVar(value=initial_args.tables)
        self.filter_var = tk.StringVar()
        self.structure_only_var = tk.BooleanVar(value=initial_args.structure_only)
        self.quick_compare_var = tk.BooleanVar(value=getattr(initial_args, "quick_compare", True))
        self.batch_size_var = tk.StringVar(value=str(initial_args.batch_size))
        self.status_var = tk.StringVar(value="就绪")
        self.source_tables: list[dict[str, Any]] = []

        self.root.title("数据库对比工具")
        self.root.geometry("980x700")
        self.root.minsize(820, 560)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui(config_keys)
        self._process_queues()

    def _build_ui(self, config_keys: list[str]) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        main = ttk.Frame(self.root, padding=12)
        main.grid(row=0, column=0, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(2, weight=1)
        main.rowconfigure(3, weight=1)

        ttk.Label(main, text="数据库对比工具", font=("Microsoft YaHei UI", 16, "bold")).grid(
            row=0, column=0, sticky="w"
        )

        form = ttk.LabelFrame(main, text="对比设置", padding=10)
        form.grid(row=1, column=0, sticky="ew", pady=(10, 8))
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=1)

        ttk.Label(form, text="源库").grid(row=0, column=0, sticky="w")
        source_combo = ttk.Combobox(form, textvariable=self.source_key_var, values=config_keys, state="readonly", width=18)
        source_combo.grid(row=0, column=1, sticky="w", padx=(8, 24))
        source_combo.bind("<<ComboboxSelected>>", lambda _event: self._clear_table_list())
        self.controls.append(source_combo)

        ttk.Label(form, text="目标库").grid(row=0, column=2, sticky="w")
        target_combo = ttk.Combobox(form, textvariable=self.target_key_var, values=config_keys, state="readonly", width=18)
        target_combo.grid(row=0, column=3, sticky="w", padx=(8, 0))
        self.controls.append(target_combo)

        ttk.Label(form, text="批量行数").grid(row=1, column=0, sticky="w", pady=(10, 0))
        batch_entry = ttk.Entry(form, textvariable=self.batch_size_var, width=18)
        batch_entry.grid(row=1, column=1, sticky="w", padx=(8, 24), pady=(10, 0))
        self.controls.append(batch_entry)

        structure_check = ttk.Checkbutton(form, text="只对比表结构", variable=self.structure_only_var)
        structure_check.grid(row=2, column=0, columnspan=4, sticky="w", pady=(10, 0))
        self.controls.append(structure_check)

        quick_check = ttk.Checkbutton(form, text="快速对比（只检查行数和ID）", variable=self.quick_compare_var)
        quick_check.grid(row=3, column=0, columnspan=4, sticky="w", pady=(8, 0))
        self.controls.append(quick_check)

        button_bar = ttk.Frame(form)
        button_bar.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(12, 0))
        self.scan_button = ttk.Button(button_bar, text="扫描源库表", command=self._start_scan_tables)
        self.scan_button.grid(row=0, column=0, sticky="w")
        self.compare_button = ttk.Button(button_bar, text="开始对比", command=self._start_compare)
        self.compare_button.grid(row=0, column=1, sticky="w", padx=(8, 0))
        self.stop_button = ttk.Button(button_bar, text="停止", command=self._stop_current_task, state="disabled")
        self.stop_button.grid(row=0, column=2, sticky="w", padx=(8, 0))
        ttk.Button(button_bar, text="全选", command=self._select_all_tables).grid(row=0, column=3, sticky="w", padx=(8, 0))
        ttk.Button(button_bar, text="取消选择", command=self._clear_table_selection).grid(row=0, column=4, sticky="w", padx=(8, 0))
        ttk.Button(button_bar, text="清空日志", command=self._clear_log).grid(row=0, column=5, sticky="w", padx=(8, 0))
        self.progress = ttk.Progressbar(button_bar, mode="indeterminate", length=180)
        self.progress.grid(row=0, column=6, sticky="w", padx=(16, 0))

        table_frame = ttk.LabelFrame(main, text="源库表清单", padding=8)
        table_frame.grid(row=2, column=0, sticky="nsew", pady=(0, 8))
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(1, weight=1)

        filter_bar = ttk.Frame(table_frame)
        filter_bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        filter_bar.columnconfigure(1, weight=1)
        ttk.Label(filter_bar, text="筛选").grid(row=0, column=0, sticky="w")
        filter_entry = ttk.Entry(filter_bar, textvariable=self.filter_var)
        filter_entry.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        filter_entry.bind("<KeyRelease>", lambda _event: self._populate_table_tree())
        self.controls.append(filter_entry)

        columns = ("table_name", "table_rows")
        self.table_tree = ttk.Treeview(
            table_frame,
            columns=columns,
            show="headings",
            selectmode="extended",
            height=10,
        )
        self.table_tree.heading("table_name", text="表名")
        self.table_tree.heading("table_rows", text="估算行数")
        self.table_tree.column("table_name", width=560, anchor="w")
        self.table_tree.column("table_rows", width=120, anchor="e", stretch=False)
        table_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.table_tree.yview)
        self.table_tree.configure(yscrollcommand=table_scroll.set)
        self.table_tree.grid(row=1, column=0, sticky="nsew")
        table_scroll.grid(row=1, column=1, sticky="ns")

        log_frame = ttk.LabelFrame(main, text="执行日志", padding=8)
        log_frame.grid(row=3, column=0, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            height=16,
            wrap="word",
            state="disabled",
            font=("Consolas", 10),
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")

        ttk.Label(main, textvariable=self.status_var, anchor="w").grid(row=4, column=0, sticky="ew", pady=(8, 0))

    def _collect_args(self) -> argparse.Namespace | None:
        try:
            batch_size = int(self.batch_size_var.get().strip())
        except ValueError:
            messagebox.showerror("参数错误", "批量行数必须是整数。")
            return None
        if batch_size <= 0:
            messagebox.showerror("参数错误", "批量行数必须大于 0。")
            return None

        args = argparse.Namespace(**vars(self.initial_args))
        args.source_key = self.source_key_var.get().strip()
        args.target_key = self.target_key_var.get().strip()
        selected_tables = self._get_selected_tables()
        if not selected_tables:
            messagebox.showwarning("未选择表", "请先扫描源库表，并选择至少一张要对比的表。")
            return None
        args.tables = ",".join(selected_tables)
        args.structure_only = bool(self.structure_only_var.get())
        args.quick_compare = bool(self.quick_compare_var.get())
        args.batch_size = batch_size
        args.cli = True
        return args

    def _clear_table_list(self) -> None:
        self.source_tables = []
        if hasattr(self, "table_tree"):
            self.table_tree.delete(*self.table_tree.get_children())
        self.status_var.set("源库已切换，请重新扫描表。")

    def _get_filter_keywords(self) -> list[str]:
        filter_text = self.filter_var.get().strip().lower()
        for separator in ("，", ",", "；", ";", "\n", "\t"):
            filter_text = filter_text.replace(separator, " ")
        return [keyword for keyword in filter_text.split(" ") if keyword]

    def _populate_table_tree(self) -> None:
        self.table_tree.delete(*self.table_tree.get_children())
        keywords = self._get_filter_keywords()
        for row in self.source_tables:
            table_name = str(row.get("table_name") or row.get("TABLE_NAME") or "")
            table_name_lower = table_name.lower()
            if keywords and not all(keyword in table_name_lower for keyword in keywords):
                continue
            table_rows = row.get("table_rows")
            if table_rows is None:
                table_rows = row.get("TABLE_ROWS")
            row_text = "" if table_rows is None else str(table_rows)
            self.table_tree.insert("", "end", iid=table_name, values=(table_name, row_text))

    def _get_selected_tables(self) -> list[str]:
        return [str(item_id) for item_id in self.table_tree.selection()]

    def _select_all_tables(self) -> None:
        self.table_tree.selection_set(self.table_tree.get_children())

    def _clear_table_selection(self) -> None:
        self.table_tree.selection_remove(self.table_tree.selection())

    def _append_log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _set_busy(self, busy: bool, cancellable: bool = False) -> None:
        self.scan_button.configure(state="disabled" if busy else "normal")
        self.compare_button.configure(state="disabled" if busy else "normal")
        self.stop_button.configure(state="normal" if busy and cancellable else "disabled")
        for control in self.controls:
            try:
                control.configure(state="disabled" if busy else ("readonly" if isinstance(control, ttk.Combobox) else "normal"))
            except tk.TclError:
                pass
        if busy:
            self.progress.start(12)
            self.status_var.set("正在对比...")
        else:
            self.progress.stop()
            self.cancel_event = None

    def _stop_current_task(self) -> None:
        if self.cancel_event is not None and not self.cancel_event.is_set():
            self.cancel_event.set()
            for inspector in getattr(self.cancel_event, "db_inspectors", ()):
                with contextlib.suppress(Exception):
                    inspector.close()
            self.stop_button.configure(state="disabled")
            self.status_var.set("正在停止...")

    def _start_scan_tables(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showwarning("任务正在执行", "当前任务还没有结束。")
            return
        source_key = self.source_key_var.get().strip()
        self._set_busy(True, cancellable=False)
        self.status_var.set("正在扫描源库表...")
        self.worker_thread = threading.Thread(target=self._run_scan_worker, args=(source_key,), daemon=True)
        self.worker_thread.start()

    def _run_scan_worker(self, source_key: str) -> None:
        return_code = 1
        tables: list[dict[str, Any]] = []
        try:
            configs = load_database_configs()
            source_config = require_db_config(configs, source_key)
            inspector = DatabaseInspector(source_key, source_config)
            try:
                inspector.connect()
                tables = inspector.list_tables()
                return_code = 0
            finally:
                inspector.close()
        except Exception as exc:
            self.log_queue.put(f"扫描源库表失败: {exc}\n")
            return_code = 1
        finally:
            self.ui_queue.put(("tables_loaded", return_code, tables, source_key))

    def _start_compare(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showwarning("任务正在执行", "当前对比任务还没有结束。")
            return
        args = self._collect_args()
        if args is None:
            return
        self.cancel_event = threading.Event()
        cancel_event = self.cancel_event
        self._set_busy(True, cancellable=True)
        self.worker_thread = threading.Thread(target=self._run_compare_worker, args=(args, cancel_event), daemon=True)
        self.worker_thread.start()

    def _run_compare_worker(self, args: argparse.Namespace, cancel_event: threading.Event | None) -> None:
        return_code = 1
        report_path = None
        report = None
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                return_code, report = compare_and_build_report(args, cancel_event=cancel_event)
        except CompareCancelled as exc:
            report = {
                "summary": {
                    "total": 0,
                    "same": 0,
                    "different": 0,
                },
                "一致": [],
                "不一致": {
                    "已停止": [str(exc)]
                },
            }
            return_code = CANCELLED_EXIT_CODE
        except Exception as exc:
            if cancel_event is not None and cancel_event.is_set():
                report = {
                    "summary": {
                        "total": 0,
                        "same": 0,
                        "different": 0,
                    },
                    "一致": [],
                    "不一致": {
                        "已停止": ["用户已停止对比任务。"]
                    },
                }
                return_code = CANCELLED_EXIT_CODE
            else:
                report = {
                    "summary": {
                        "total": 0,
                        "same": 0,
                        "different": 0,
                    },
                    "一致": [],
                    "不一致": {
                        "执行异常": [str(exc)]
                    },
                }
                return_code = 1
        finally:
            try:
                report_content = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
                report_path = write_result_report(report_content)
                self.log_queue.put(report_content)
                self.log_queue.put(f"结果文件: {report_path}\n")
            except Exception as exc:
                self.log_queue.put(f"对比结果文件输出失败: {exc}\n")
            self.ui_queue.put(("done", return_code, str(report_path) if report_path else ""))

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
            if event_type == "done":
                _, return_code, report_path = event
                self._set_busy(False)
                if return_code == 0:
                    self.status_var.set("对比完成：全部一致")
                    messagebox.showinfo("对比完成", f"指定表全部一致。\n\n结果文件:\n{report_path}")
                elif return_code == CANCELLED_EXIT_CODE:
                    self.status_var.set("对比已停止")
                    messagebox.showwarning("对比已停止", f"对比任务已停止。\n\n结果文件:\n{report_path}")
                elif return_code == 2:
                    self.status_var.set("对比完成：存在差异")
                    messagebox.showwarning("存在差异", f"指定表存在差异。\n\n结果文件:\n{report_path}")
                else:
                    self.status_var.set("对比失败")
                    messagebox.showerror("对比失败", f"数据库对比失败，请查看执行日志。\n\n结果文件:\n{report_path}")
            elif event_type == "tables_loaded":
                _, return_code, tables, source_key = event
                self._set_busy(False)
                if return_code == 0:
                    self.source_tables = list(tables)
                    self._populate_table_tree()
                    self.status_var.set(f"{source_key} 扫描完成：{len(self.source_tables)} 张表")
                else:
                    self.status_var.set("扫描源库表失败")
                    messagebox.showerror("扫描失败", "扫描源库表失败，请查看执行日志。")

        self.root.after(100, self._process_queues)

    def _on_close(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showwarning("任务正在执行", "当前对比任务还没有结束，请等待完成后再关闭窗口。")
            return
        self.root.destroy()


def run_gui(initial_args: argparse.Namespace) -> int:
    if tk is None:
        print("当前 Python 环境不可用 Tkinter，已切换到命令行模式。")
        return run_compare(initial_args)
    root = tk.Tk()
    try:
        DbCompareApp(root, initial_args)
    except RuntimeError as exc:
        messagebox.showerror("配置错误", str(exc))
        root.destroy()
        return 1
    root.mainloop()
    return 0


def main(argv: list[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    args = parse_args(raw_args)
    if args.cli:
        if not args.tables:
            raise RuntimeError("命令行模式必须通过 --tables 指定表名。")
        return run_compare(args)
    return run_gui(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"数据库对比失败: {exc}", file=sys.stderr)
        raise SystemExit(1)
    except Error as exc:
        print(f"数据库连接或查询失败: {exc}", file=sys.stderr)
        raise SystemExit(1)
