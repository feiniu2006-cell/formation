"""Standalone bad slot formation data cleaner.

This tool is intentionally separate from formation_tool. It reads database
connection settings from ../db_config.py, but it does not import or modify any
formation_tool runtime/configuration code.
"""

from __future__ import annotations

import queue
import re
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox, ttk
import tkinter as tk

import mysql.connector


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from db_config import DATABASE_CONFIGS, DB_RETRY_DELAY, MAX_DB_RETRIES  # noqa: E402


SQL_IDENTIFIER_RE = re.compile(r"^[0-9A-Za-z_$-]+$")
DEFAULT_DB_CONNECT_TIMEOUT_SECONDS = 20
DEFAULT_DB_QUERY_TIMEOUT_SECONDS = 3600


def validate_identifier(value: str, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label}不能为空")
    if len(text) > 64:
        raise ValueError(f"{label}长度不能超过 64 个字符: {text}")
    if not SQL_IDENTIFIER_RE.fullmatch(text):
        raise ValueError(f"{label}包含非法字符: {text}")
    return text


def quote_identifier(value: str, label: str = "SQL标识符") -> str:
    return f"`{validate_identifier(value, label)}`"


def parse_field_list(text: str, label: str) -> list[str]:
    fields = [item.strip() for item in str(text or "").split(",") if item.strip()]
    if not fields:
        raise ValueError(f"{label}不能为空")
    return [validate_identifier(field, f"{label}字段") for field in fields]


def parse_non_negative_int(text: str, label: str) -> int:
    try:
        value = int(str(text).strip())
    except ValueError:
        raise ValueError(f"{label}必须是整数: {text}") from None
    if value < 0:
        raise ValueError(f"{label}不能小于 0: {value}")
    return value


def parse_positive_int(text: str, label: str) -> int:
    value = parse_non_negative_int(text, label)
    if value <= 0:
        raise ValueError(f"{label}必须大于 0: {value}")
    return value


def normalize_suffix(text: str) -> str:
    suffix = validate_identifier(text, "表后缀").lstrip("_")
    if not suffix:
        raise ValueError("表后缀不能为空")
    return suffix


def build_table_name(vendor: str, game_id: str, suffix: str) -> str:
    vendor = validate_identifier(vendor, "厂商")
    game_id = validate_identifier(game_id, "游戏编号")
    suffix = normalize_suffix(suffix)
    return validate_identifier(f"{vendor}_{game_id}_{suffix}", "表名")


def make_backup_table_name(table_name: str) -> str:
    suffix = f"_bad_backup_{time.strftime('%Y%m%d_%H%M%S')}_{int(time.time() * 1000) % 1000:03d}"
    max_base_len = max(1, 64 - len(suffix))
    return validate_identifier(f"{table_name[:max_base_len]}{suffix}", "备份表名")


def token_count_expr(field: str, target_value: int) -> str:
    """Return exact token count expression for comma separated integer strings.

    The expression wraps each token with `|`, and uses doubled delimiters between
    adjacent tokens so values like 10/11 are not counted as target token 1.
    Example: "1,11,1" -> "|1||11||1|", then count "|1|".
    """
    field_sql = quote_identifier(field, "字段名")
    normalized = (
        "CONCAT('|', "
        f"REPLACE(REPLACE(COALESCE(CAST({field_sql} AS CHAR), ''), ' ', ''), ',', '||'), "
        "'|')"
    )
    pattern = f"|{int(target_value)}|"
    return (
        f"((CHAR_LENGTH({normalized}) "
        f"- CHAR_LENGTH(REPLACE({normalized}, '{pattern}', ''))) / {len(pattern)})"
    )


def sum_token_count_expr(fields: list[str], target_value: int) -> str:
    if not fields:
        return "0"
    return " + ".join(token_count_expr(field, target_value) for field in fields)


def build_reason_expr(rules: list[tuple[str, str]]) -> str:
    parts = [
        f"IF(({condition}), {sql_literal(label)}, NULL)"
        for label, condition in rules
    ]
    return f"CONCAT_WS(', ', {', '.join(parts)})"


def sql_literal(text: str) -> str:
    return "'" + str(text).replace("\\", "\\\\").replace("'", "\\'") + "'"


def make_temp_table_name(prefix: str) -> str:
    safe_prefix = validate_identifier(prefix, "临时表前缀")
    return validate_identifier(
        f"{safe_prefix}_{int(time.time() * 1000) % 1000000}_{threading.get_ident() % 10000}",
        "临时表名",
    )


@dataclass
class CleanerConfig:
    db_key: str
    table_name: str
    scatter_fields: list[str]
    wild_fields: list[str]
    scatter_game0_threshold: int
    scatter_game_positive_threshold: int
    scatter_sort0_threshold: int
    scatter_sort_positive_threshold: int
    scatter_no_game_id_threshold: int
    wild_threshold: int
    max_game_id: int
    max_sort: int
    sample_limit: int
    batch_size: int
    backup_before_delete: bool
    enable_scatter_game0: bool
    enable_scatter_game_positive: bool
    enable_scatter_sort0: bool
    enable_scatter_sort_positive: bool
    enable_scatter_no_game_id: bool
    enable_wild: bool
    enable_game_id: bool
    enable_sort: bool
    has_game_id: bool = True
    has_sort: bool = True


@dataclass
class QueryResult:
    problem_rows: int
    problem_ids: int
    delete_rows: int
    reason_counts: dict[str, int]
    samples: list[dict]


class BadDataCleanerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Slot 问题数据查询/清理工具")
        self.root.geometry("1180x820")
        self.root.minsize(1000, 680)
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.last_config: CleanerConfig | None = None
        self.last_result: QueryResult | None = None
        self.worker_running = False

        self._build_variables()
        self._build_ui()
        self._poll_log_queue()

    def _build_variables(self):
        db_keys = list(DATABASE_CONFIGS)
        default_db = "DB1" if "DB1" in db_keys else (db_keys[0] if db_keys else "")
        self.db_var = tk.StringVar(value=default_db)
        self.vendor_var = tk.StringVar(value="pg")
        self.game_id_var = tk.StringVar(value="")
        self.suffix_var = tk.StringVar(value="free_formation")
        self.scatter_fields_var = tk.StringVar(value="orl,torl,borl,formation")
        self.wild_fields_var = tk.StringVar(value="orl,torl,borl,formation")
        self.scatter_game0_threshold_var = tk.StringVar(value="4")
        self.scatter_game_positive_threshold_var = tk.StringVar(value="3")
        self.scatter_sort0_threshold_var = tk.StringVar(value="4")
        self.scatter_sort_positive_threshold_var = tk.StringVar(value="3")
        self.scatter_no_game_id_threshold_var = tk.StringVar(value="3")
        self.wild_threshold_var = tk.StringVar(value="6")
        self.max_game_id_var = tk.StringVar(value="20")
        self.max_sort_var = tk.StringVar(value="10")
        self.sample_limit_var = tk.StringVar(value="100")
        self.batch_size_var = tk.StringVar(value="500")
        self.backup_before_delete_var = tk.BooleanVar(value=True)
        self.enable_scatter_game0_var = tk.BooleanVar(value=True)
        self.enable_scatter_game_positive_var = tk.BooleanVar(value=True)
        self.enable_scatter_sort0_var = tk.BooleanVar(value=True)
        self.enable_scatter_sort_positive_var = tk.BooleanVar(value=True)
        self.enable_scatter_no_game_id_var = tk.BooleanVar(value=True)
        self.enable_wild_var = tk.BooleanVar(value=True)
        self.enable_game_id_var = tk.BooleanVar(value=True)
        self.enable_sort_var = tk.BooleanVar(value=True)
        self.summary_var = tk.StringVar(value="尚未查询")

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=10)
        main.grid(row=0, column=0, sticky="nsew")
        self.root.rowconfigure(0, weight=1)
        self.root.columnconfigure(0, weight=1)
        main.rowconfigure(4, weight=1)
        main.columnconfigure(0, weight=1)

        config = ttk.LabelFrame(main, text="目标表")
        config.grid(row=0, column=0, sticky="ew")
        for col in range(8):
            config.columnconfigure(col, weight=1 if col in (1, 3, 5) else 0)

        ttk.Label(config, text="数据库").grid(row=0, column=0, sticky="w", padx=(8, 4), pady=6)
        ttk.Combobox(
            config,
            textvariable=self.db_var,
            values=list(DATABASE_CONFIGS),
            state="readonly",
            width=18,
        ).grid(row=0, column=1, sticky="ew", padx=(0, 12), pady=6)
        ttk.Label(config, text="厂商").grid(row=0, column=2, sticky="w", padx=(8, 4), pady=6)
        ttk.Entry(config, textvariable=self.vendor_var, width=12).grid(row=0, column=3, sticky="ew", padx=(0, 12), pady=6)
        ttk.Label(config, text="游戏编号").grid(row=0, column=4, sticky="w", padx=(8, 4), pady=6)
        ttk.Entry(config, textvariable=self.game_id_var, width=16).grid(row=0, column=5, sticky="ew", padx=(0, 12), pady=6)
        ttk.Label(config, text="表后缀").grid(row=0, column=6, sticky="w", padx=(8, 4), pady=6)
        ttk.Entry(config, textvariable=self.suffix_var, width=22).grid(row=0, column=7, sticky="ew", padx=(0, 8), pady=6)

        rules = ttk.LabelFrame(main, text="问题规则")
        rules.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        for col in range(8):
            rules.columnconfigure(col, weight=1 if col in (1, 3, 5, 7) else 0)

        ttk.Label(rules, text="Scatter字段").grid(row=0, column=0, sticky="w", padx=(8, 4), pady=6)
        ttk.Entry(rules, textvariable=self.scatter_fields_var, width=28).grid(row=0, column=1, columnspan=3, sticky="ew", padx=(0, 12), pady=6)
        ttk.Label(rules, text="Wild字段").grid(row=0, column=4, sticky="w", padx=(8, 4), pady=6)
        ttk.Entry(rules, textvariable=self.wild_fields_var, width=28).grid(row=0, column=5, columnspan=3, sticky="ew", padx=(0, 8), pady=6)

        ttk.Checkbutton(
            rules,
            text="game_id=0 时 Scatter >",
            variable=self.enable_scatter_game0_var,
        ).grid(row=1, column=0, sticky="w", padx=(8, 4), pady=6)
        ttk.Entry(rules, textvariable=self.scatter_game0_threshold_var, width=10).grid(row=1, column=1, sticky="w", padx=(0, 12), pady=6)
        ttk.Checkbutton(
            rules,
            text="game_id>0 时 Scatter >",
            variable=self.enable_scatter_game_positive_var,
        ).grid(row=1, column=2, sticky="w", padx=(8, 4), pady=6)
        ttk.Entry(rules, textvariable=self.scatter_game_positive_threshold_var, width=10).grid(row=1, column=3, sticky="w", padx=(0, 12), pady=6)
        ttk.Checkbutton(
            rules,
            text="Wild >",
            variable=self.enable_wild_var,
        ).grid(row=1, column=4, sticky="w", padx=(8, 4), pady=6)
        ttk.Entry(rules, textvariable=self.wild_threshold_var, width=10).grid(row=1, column=5, sticky="w", padx=(0, 12), pady=6)

        ttk.Checkbutton(
            rules,
            text="无game_id时 Scatter >",
            variable=self.enable_scatter_no_game_id_var,
        ).grid(row=2, column=0, sticky="w", padx=(8, 4), pady=6)
        ttk.Entry(rules, textvariable=self.scatter_no_game_id_threshold_var, width=10).grid(row=2, column=1, sticky="w", padx=(0, 12), pady=6)
        ttk.Checkbutton(
            rules,
            text="game_id >",
            variable=self.enable_game_id_var,
        ).grid(row=2, column=2, sticky="w", padx=(8, 4), pady=6)
        ttk.Entry(rules, textvariable=self.max_game_id_var, width=10).grid(row=2, column=3, sticky="w", padx=(0, 12), pady=6)
        ttk.Checkbutton(
            rules,
            text="sort >",
            variable=self.enable_sort_var,
        ).grid(row=2, column=4, sticky="w", padx=(8, 4), pady=6)
        ttk.Entry(rules, textvariable=self.max_sort_var, width=10).grid(row=2, column=5, sticky="w", padx=(0, 12), pady=6)
        ttk.Checkbutton(
            rules,
            text="sort=0 时 Scatter >",
            variable=self.enable_scatter_sort0_var,
        ).grid(row=3, column=0, sticky="w", padx=(8, 4), pady=6)
        ttk.Entry(rules, textvariable=self.scatter_sort0_threshold_var, width=10).grid(row=3, column=1, sticky="w", padx=(0, 12), pady=6)
        ttk.Checkbutton(
            rules,
            text="sort>0 时 Scatter >",
            variable=self.enable_scatter_sort_positive_var,
        ).grid(row=3, column=2, sticky="w", padx=(8, 4), pady=6)
        ttk.Entry(rules, textvariable=self.scatter_sort_positive_threshold_var, width=10).grid(row=3, column=3, sticky="w", padx=(0, 12), pady=6)
        ttk.Label(rules, text="样例行数").grid(row=4, column=0, sticky="w", padx=(8, 4), pady=6)
        ttk.Entry(rules, textvariable=self.sample_limit_var, width=10).grid(row=4, column=1, sticky="w", padx=(0, 12), pady=6)
        ttk.Label(rules, text="删除批量id").grid(row=4, column=2, sticky="w", padx=(8, 4), pady=6)
        ttk.Entry(rules, textvariable=self.batch_size_var, width=10).grid(row=4, column=3, sticky="w", padx=(0, 8), pady=6)

        action = ttk.Frame(main)
        action.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        action.columnconfigure(5, weight=1)
        self.query_button = ttk.Button(action, text="查询问题数据", command=self.query_bad_data)
        self.query_button.grid(row=0, column=0, padx=(0, 8))
        self.delete_button = ttk.Button(action, text="删除问题id全部数据", command=self.delete_bad_data, state="disabled")
        self.delete_button.grid(row=0, column=1, padx=(0, 8))
        ttk.Checkbutton(
            action,
            text="删除前备份命中id组",
            variable=self.backup_before_delete_var,
        ).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(action, text="清空日志", command=self.clear_log).grid(row=0, column=3, padx=(0, 8))
        ttk.Button(action, text="退出", command=self.root.destroy).grid(row=0, column=4, padx=(0, 8))
        ttk.Label(action, textvariable=self.summary_var, foreground="#555555").grid(row=0, column=5, sticky="e")

        samples_frame = ttk.LabelFrame(main, text="命中样例")
        samples_frame.grid(row=3, column=0, sticky="nsew", pady=(10, 0))
        samples_frame.rowconfigure(0, weight=1)
        samples_frame.columnconfigure(0, weight=1)
        self.samples = ttk.Treeview(
            samples_frame,
            columns=("id", "game_id", "sort", "scatter", "wild", "reason"),
            show="headings",
            height=8,
        )
        for col, title, width in (
            ("id", "id", 120),
            ("game_id", "game_id", 80),
            ("sort", "sort", 70),
            ("scatter", "Scatter数量", 110),
            ("wild", "Wild数量", 100),
            ("reason", "命中原因", 520),
        ):
            self.samples.heading(col, text=title)
            self.samples.column(col, width=width, anchor="w")
        self.samples.grid(row=0, column=0, sticky="nsew")
        sample_scroll = ttk.Scrollbar(samples_frame, orient="vertical", command=self.samples.yview)
        sample_scroll.grid(row=0, column=1, sticky="ns")
        self.samples.configure(yscrollcommand=sample_scroll.set)

        log_frame = ttk.LabelFrame(main, text="运行日志")
        log_frame.grid(row=4, column=0, sticky="nsew", pady=(10, 0))
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)
        self.log_text = tk.Text(log_frame, wrap="word", height=12)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=log_scroll.set)

    def parse_config(self) -> CleanerConfig:
        db_key = self.db_var.get().strip()
        if db_key not in DATABASE_CONFIGS:
            raise ValueError(f"未知数据库配置: {db_key}")
        config = CleanerConfig(
            db_key=db_key,
            table_name=build_table_name(
                self.vendor_var.get(),
                self.game_id_var.get(),
                self.suffix_var.get(),
            ),
            scatter_fields=parse_field_list(self.scatter_fields_var.get(), "Scatter字段"),
            wild_fields=parse_field_list(self.wild_fields_var.get(), "Wild字段"),
            scatter_game0_threshold=parse_non_negative_int(self.scatter_game0_threshold_var.get(), "Scatter(game_id=0)阈值"),
            scatter_game_positive_threshold=parse_non_negative_int(self.scatter_game_positive_threshold_var.get(), "Scatter(game_id>0)阈值"),
            scatter_sort0_threshold=parse_non_negative_int(self.scatter_sort0_threshold_var.get(), "Scatter(sort=0)阈值"),
            scatter_sort_positive_threshold=parse_non_negative_int(self.scatter_sort_positive_threshold_var.get(), "Scatter(sort>0)阈值"),
            scatter_no_game_id_threshold=parse_non_negative_int(self.scatter_no_game_id_threshold_var.get(), "Scatter(无game_id)阈值"),
            wild_threshold=parse_non_negative_int(self.wild_threshold_var.get(), "Wild阈值"),
            max_game_id=parse_non_negative_int(self.max_game_id_var.get(), "game_id最大值"),
            max_sort=parse_non_negative_int(self.max_sort_var.get(), "sort最大值"),
            sample_limit=parse_positive_int(self.sample_limit_var.get(), "样例行数"),
            batch_size=parse_positive_int(self.batch_size_var.get(), "删除批量id"),
            backup_before_delete=bool(self.backup_before_delete_var.get()),
            enable_scatter_game0=bool(self.enable_scatter_game0_var.get()),
            enable_scatter_game_positive=bool(self.enable_scatter_game_positive_var.get()),
            enable_scatter_sort0=bool(self.enable_scatter_sort0_var.get()),
            enable_scatter_sort_positive=bool(self.enable_scatter_sort_positive_var.get()),
            enable_scatter_no_game_id=bool(self.enable_scatter_no_game_id_var.get()),
            enable_wild=bool(self.enable_wild_var.get()),
            enable_game_id=bool(self.enable_game_id_var.get()),
            enable_sort=bool(self.enable_sort_var.get()),
        )
        if not any((
            config.enable_scatter_game0,
            config.enable_scatter_game_positive,
            config.enable_scatter_sort0,
            config.enable_scatter_sort_positive,
            config.enable_scatter_no_game_id,
            config.enable_wild,
            config.enable_game_id,
            config.enable_sort,
        )):
            raise ValueError("至少需要启用一条问题规则")
        return config

    def connect(self, db_key: str):
        db_config = dict(DATABASE_CONFIGS[db_key])
        db_config.setdefault("connection_timeout", DEFAULT_DB_CONNECT_TIMEOUT_SECONDS)
        db_config.setdefault("read_timeout", DEFAULT_DB_QUERY_TIMEOUT_SECONDS)
        db_config.setdefault("write_timeout", DEFAULT_DB_QUERY_TIMEOUT_SECONDS)
        db_config.setdefault("use_pure", True)
        last_error = None
        for attempt in range(1, int(MAX_DB_RETRIES) + 1):
            try:
                self.log(
                    f"连接数据库 {db_key} {db_config['host']}:{db_config['port']} "
                    f"(第{attempt}次，read_timeout={db_config['read_timeout']}秒)..."
                )
                conn = mysql.connector.connect(**db_config)
                self.log(f"数据库连接成功：{db_key}")
                return conn
            except Exception as exc:
                last_error = exc
                self.log(f"数据库连接失败：{exc}")
                if attempt < int(MAX_DB_RETRIES):
                    time.sleep(int(DB_RETRY_DELAY))
        raise RuntimeError(f"无法连接数据库 {db_key}: {last_error}")

    def validate_table_columns(self, cursor, cfg: CleanerConfig):
        table_sql = quote_identifier(cfg.table_name, "表名")
        cursor.execute(f"SHOW COLUMNS FROM {table_sql}")
        columns = set()
        for row in cursor.fetchall():
            if isinstance(row, dict):
                columns.add(row.get("Field"))
            else:
                columns.add(row[0])
        columns.discard(None)
        if not columns:
            raise ValueError(f"表不存在或没有字段: {cfg.table_name}")

        cfg.has_game_id = "game_id" in columns
        cfg.has_sort = "sort" in columns
        required = {"id"}
        if not cfg.has_game_id:
            disabled_game_rules = []
            if cfg.enable_scatter_game0:
                disabled_game_rules.append("game_id=0 Scatter")
                cfg.enable_scatter_game0 = False
            if cfg.enable_scatter_game_positive:
                disabled_game_rules.append("game_id>0 Scatter")
                cfg.enable_scatter_game_positive = False
            if cfg.enable_game_id:
                disabled_game_rules.append("game_id上限")
                cfg.enable_game_id = False
            if disabled_game_rules:
                self.log(
                    "[WARN] 当前表不存在 game_id 字段，已忽略依赖 game_id 的规则："
                    + "、".join(disabled_game_rules)
                )
        if not cfg.has_sort:
            disabled_sort_rules = []
            if cfg.enable_scatter_sort0:
                disabled_sort_rules.append("sort=0 Scatter")
                cfg.enable_scatter_sort0 = False
            if cfg.enable_scatter_sort_positive:
                disabled_sort_rules.append("sort>0 Scatter")
                cfg.enable_scatter_sort_positive = False
            if cfg.enable_sort:
                disabled_sort_rules.append("sort上限")
                cfg.enable_sort = False
            if disabled_sort_rules:
                self.log(
                    "[WARN] 当前表不存在 sort 字段，已忽略依赖 sort 的规则："
                    + "、".join(disabled_sort_rules)
                )
        scatter_missing = [field for field in cfg.scatter_fields if field not in columns]
        wild_missing = [field for field in cfg.wild_fields if field not in columns]
        if scatter_missing:
            self.log(f"[WARN] Scatter字段不存在，已忽略：{', '.join(scatter_missing)}")
        if wild_missing:
            self.log(f"[WARN] Wild字段不存在，已忽略：{', '.join(wild_missing)}")
        cfg.scatter_fields = [field for field in cfg.scatter_fields if field in columns]
        cfg.wild_fields = [field for field in cfg.wild_fields if field in columns]
        if (
            cfg.enable_scatter_game0
            or cfg.enable_scatter_game_positive
            or cfg.enable_scatter_sort0
            or cfg.enable_scatter_sort_positive
            or cfg.enable_scatter_no_game_id
        ) and not cfg.scatter_fields:
            self.log("[WARN] 没有可用的 Scatter 字段，本次 Scatter 规则不会命中")
        if cfg.enable_wild and not cfg.wild_fields:
            self.log("[WARN] 没有可用的 Wild 字段，本次 Wild 规则不会命中")
        missing = sorted(required - columns)
        if missing:
            raise ValueError(f"{cfg.table_name} 缺少字段: {', '.join(missing)}")

    def build_rule_conditions(self, cfg: CleanerConfig, scatter_term: str, wild_term: str):
        rules: list[tuple[str, str]] = []
        if cfg.enable_scatter_game0:
            rules.append((
                f"Scatter(game_id=0)>{cfg.scatter_game0_threshold}",
                f"({quote_identifier('game_id')} = 0 AND ({scatter_term}) > {cfg.scatter_game0_threshold})",
            ))
        if cfg.enable_scatter_game_positive:
            rules.append((
                f"Scatter(game_id>0)>{cfg.scatter_game_positive_threshold}",
                f"({quote_identifier('game_id')} > 0 AND ({scatter_term}) > {cfg.scatter_game_positive_threshold})",
            ))
        if cfg.enable_scatter_sort0:
            rules.append((
                f"Scatter(sort=0)>{cfg.scatter_sort0_threshold}",
                f"({quote_identifier('sort')} = 0 AND ({scatter_term}) > {cfg.scatter_sort0_threshold})",
            ))
        if cfg.enable_scatter_sort_positive:
            rules.append((
                f"Scatter(sort>0)>{cfg.scatter_sort_positive_threshold}",
                f"({quote_identifier('sort')} > 0 AND ({scatter_term}) > {cfg.scatter_sort_positive_threshold})",
            ))
        if cfg.enable_scatter_no_game_id and not cfg.has_game_id:
            rules.append((
                f"Scatter(无game_id)>{cfg.scatter_no_game_id_threshold}",
                f"(({scatter_term}) > {cfg.scatter_no_game_id_threshold})",
            ))
        if cfg.enable_wild:
            rules.append((
                f"Wild>{cfg.wild_threshold}",
                f"(({wild_term}) > {cfg.wild_threshold})",
            ))
        if cfg.enable_game_id:
            rules.append((
                f"game_id>{cfg.max_game_id}",
                f"({quote_identifier('game_id')} > {cfg.max_game_id})",
            ))
        if cfg.enable_sort:
            rules.append((
                f"sort>{cfg.max_sort}",
                f"({quote_identifier('sort')} > {cfg.max_sort})",
            ))
        return rules

    def build_query_parts(self, cfg: CleanerConfig):
        scatter_expr = sum_token_count_expr(cfg.scatter_fields, 1)
        wild_expr = sum_token_count_expr(cfg.wild_fields, 0)
        rules = self.build_rule_conditions(cfg, scatter_expr, wild_expr)
        where_sql = " OR ".join(f"({condition})" for _label, condition in rules)
        reason_sql = build_reason_expr(rules)
        return scatter_expr, wild_expr, rules, where_sql, reason_sql

    def build_alias_query_parts(self, cfg: CleanerConfig):
        rules = self.build_rule_conditions(
            cfg,
            quote_identifier("scatter_count"),
            quote_identifier("wild_count"),
        )
        where_sql = " OR ".join(f"({condition})" for _label, condition in rules)
        reason_sql = build_reason_expr(rules)
        return rules, where_sql, reason_sql

    def run_query(self, cfg: CleanerConfig) -> QueryResult:
        conn = self.connect(cfg.db_key)
        try:
            cursor = conn.cursor(dictionary=True)
            self.validate_table_columns(cursor, cfg)
            table_sql = quote_identifier(cfg.table_name, "表名")
            scatter_expr, wild_expr, rules, where_sql, reason_sql = self.build_query_parts(cfg)
            if not rules:
                raise ValueError("当前表没有可执行的问题规则，请启用 Wild/sort 规则或无game_id Scatter规则")

            self.log("")
            self.log("=== 查询问题数据 ===")
            self.log(f"表：{cfg.db_key}.{cfg.table_name}")
            self.log(f"Scatter字段：{', '.join(cfg.scatter_fields)}，目标值=1")
            self.log(f"Wild字段：{', '.join(cfg.wild_fields)}，目标值=0")
            self.log("启用规则：" + "；".join(label for label, _condition in rules))

            alias_rules, alias_where_sql, alias_reason_sql = self.build_alias_query_parts(cfg)
            tmp_rows = quote_identifier(make_temp_table_name("tmp_bad_rows"), "临时命中表")
            tmp_ids = quote_identifier(make_temp_table_name("tmp_bad_ids"), "临时id表")
            game_id_source = quote_identifier("game_id") if cfg.has_game_id else "NULL"
            sort_source = quote_identifier("sort") if cfg.has_sort else "NULL"
            rule_columns = ", ".join(
                f"IF(({condition}), 1, 0) AS {quote_identifier(f'rule_{idx}')}"
                for idx, (_label, condition) in enumerate(alias_rules)
            )
            rule_columns_sql = f", {rule_columns}" if rule_columns else ""

            self.set_summary_async("查询中：正在扫描原表...")
            self.log("正在扫描原表并生成临时命中表；大表这里可能需要等待...")
            start = time.perf_counter()
            cursor.execute(
                f"CREATE TEMPORARY TABLE {tmp_rows} AS "
                f"SELECT {quote_identifier('id')}, {quote_identifier('game_id')}, {quote_identifier('sort')}, "
                f"{quote_identifier('scatter_count')}, {quote_identifier('wild_count')}, "
                f"{alias_reason_sql} AS {quote_identifier('reason')}"
                f"{rule_columns_sql} "
                f"FROM ("
                f"  SELECT {quote_identifier('id')}, {game_id_source} AS {quote_identifier('game_id')}, "
                f"  {sort_source} AS {quote_identifier('sort')}, "
                f"  ({scatter_expr}) AS {quote_identifier('scatter_count')}, "
                f"  ({wild_expr}) AS {quote_identifier('wild_count')} "
                f"  FROM {table_sql}"
                f") AS scanned "
                f"WHERE {alias_where_sql}"
            )
            self.log(f"临时命中表生成完成，耗时 {time.perf_counter() - start:.2f} 秒")

            self.set_summary_async("查询中：正在生成问题id...")
            self.log("正在生成临时问题id表...")
            start = time.perf_counter()
            cursor.execute(f"CREATE TEMPORARY TABLE {tmp_ids} (id BIGINT PRIMARY KEY) ENGINE=InnoDB")
            cursor.execute(
                f"INSERT IGNORE INTO {tmp_ids} (id) "
                f"SELECT DISTINCT {quote_identifier('id')} FROM {tmp_rows}"
            )
            self.log(f"临时问题id表生成完成，耗时 {time.perf_counter() - start:.2f} 秒")

            self.set_summary_async("查询中：正在统计数量...")
            self.log("正在统计问题行数、问题id数、预计删除行数...")
            cursor.execute(f"SELECT COUNT(*) AS problem_rows FROM {tmp_rows}")
            problem_rows = int((cursor.fetchone() or {}).get("problem_rows") or 0)
            cursor.execute(f"SELECT COUNT(*) AS problem_ids FROM {tmp_ids}")
            problem_ids = int((cursor.fetchone() or {}).get("problem_ids") or 0)
            cursor.execute(
                f"SELECT COUNT(*) AS delete_rows "
                f"FROM {table_sql} AS src INNER JOIN {tmp_ids} AS bad "
                f"ON src.{quote_identifier('id')} = bad.id"
            )
            delete_rows = int((cursor.fetchone() or {}).get("delete_rows") or 0)

            self.log("正在统计各规则命中id数...")
            reason_counts = {}
            for idx, (label, _condition) in enumerate(alias_rules):
                cursor.execute(
                    f"SELECT COUNT(DISTINCT {quote_identifier('id')}) AS cnt "
                    f"FROM {tmp_rows} WHERE {quote_identifier(f'rule_{idx}')} = 1"
                )
                reason_counts[label] = int((cursor.fetchone() or {}).get("cnt") or 0)

            self.set_summary_async("查询中：正在读取样例...")
            self.log("正在读取命中样例...")
            cursor.execute(
                f"SELECT {quote_identifier('id')} AS id, "
                f"{quote_identifier('game_id')} AS game_id, "
                f"{quote_identifier('sort')} AS sort, "
                f"{quote_identifier('scatter_count')} AS scatter_count, "
                f"{quote_identifier('wild_count')} AS wild_count, "
                f"{quote_identifier('reason')} AS reason "
                f"FROM {tmp_rows} "
                f"ORDER BY {quote_identifier('id')}, {quote_identifier('game_id')}, {quote_identifier('sort')} "
                f"LIMIT {int(cfg.sample_limit)}"
            )
            samples = list(cursor.fetchall())
            result = QueryResult(problem_rows, problem_ids, delete_rows, reason_counts, samples)

            self.log(f"问题行数：{problem_rows}")
            self.log(f"问题id数：{problem_ids}")
            self.log(f"按id组预计删除行数：{delete_rows}")
            for label, count in reason_counts.items():
                self.log(f"  {label}：{count} 个 id")
            if samples:
                self.log(f"已读取命中样例：{len(samples)} 行")
            else:
                self.log("未命中问题数据")
            return result
        finally:
            conn.close()

    def create_backup_table(self, cursor, cfg: CleanerConfig, bad_ids_table: str) -> str:
        table_sql = quote_identifier(cfg.table_name, "表名")
        backup_name = make_backup_table_name(cfg.table_name)
        backup_sql = quote_identifier(backup_name, "备份表名")
        self.log(f"创建备份表：{cfg.db_key}.{backup_name}")
        cursor.execute(f"CREATE TABLE {backup_sql} LIKE {table_sql}")
        cursor.execute(
            f"INSERT INTO {backup_sql} "
            f"SELECT src.* FROM {table_sql} AS src "
            f"INNER JOIN {bad_ids_table} AS bad ON src.{quote_identifier('id')} = bad.id"
        )
        self.log(f"备份完成：{cursor.rowcount} 行 -> {backup_name}")
        return backup_name

    def run_delete(self, cfg: CleanerConfig):
        conn = self.connect(cfg.db_key)
        try:
            cursor = conn.cursor(buffered=True)
            self.validate_table_columns(cursor, cfg)
            table_sql = quote_identifier(cfg.table_name, "表名")
            scatter_expr, wild_expr, _rules, _where_sql, _reason_sql = self.build_query_parts(cfg)
            _alias_rules, alias_where_sql, _alias_reason_sql = self.build_alias_query_parts(cfg)
            if not _alias_rules:
                raise ValueError("当前表没有可执行的问题规则，请启用 Wild/sort 规则或无game_id Scatter规则")
            tmp_ids = quote_identifier(make_temp_table_name("tmp_bad_ids"), "临时id表")
            game_id_source = quote_identifier("game_id") if cfg.has_game_id else "NULL"
            sort_source = quote_identifier("sort") if cfg.has_sort else "NULL"

            self.log("")
            self.log("=== 删除问题id全部数据 ===")
            self.log(f"表：{cfg.db_key}.{cfg.table_name}")

            self.set_summary_async("删除中：正在扫描问题id...")
            self.log("正在扫描原表并生成临时问题id表；大表这里可能需要等待...")
            start = time.perf_counter()
            cursor.execute(f"CREATE TEMPORARY TABLE {tmp_ids} (id BIGINT PRIMARY KEY) ENGINE=InnoDB")
            cursor.execute(
                f"INSERT IGNORE INTO {tmp_ids} (id) "
                f"SELECT DISTINCT {quote_identifier('id')} "
                f"FROM ("
                f"  SELECT {quote_identifier('id')}, {game_id_source} AS {quote_identifier('game_id')}, "
                f"  {sort_source} AS {quote_identifier('sort')}, "
                f"  ({scatter_expr}) AS {quote_identifier('scatter_count')}, "
                f"  ({wild_expr}) AS {quote_identifier('wild_count')} "
                f"  FROM {table_sql}"
                f") AS scanned "
                f"WHERE {alias_where_sql}"
            )
            self.log(f"临时问题id表生成完成，耗时 {time.perf_counter() - start:.2f} 秒")
            cursor.execute(f"SELECT COUNT(*) FROM {tmp_ids}")
            pending_ids = int((cursor.fetchone() or [0])[0] or 0)
            self.log(f"待删除问题id：{pending_ids} 个")
            if pending_ids <= 0:
                self.log("没有需要删除的问题id")
                return 0, 0

            if cfg.backup_before_delete:
                self.set_summary_async("删除中：正在备份...")
                self.create_backup_table(cursor, cfg, tmp_ids)
                conn.commit()
            else:
                self.log("已关闭删除前备份")

            cursor.execute(f"SELECT id FROM {tmp_ids} ORDER BY id")
            self.set_summary_async("删除中：正在分批删除...")
            deleted_rows = 0
            deleted_ids = 0
            batch_no = 0
            while True:
                id_rows = cursor.fetchmany(cfg.batch_size)
                if not id_rows:
                    break
                ids = [row[0] for row in id_rows]
                placeholders = ", ".join(["%s"] * len(ids))
                delete_cursor = conn.cursor()
                delete_cursor.execute(
                    f"DELETE FROM {table_sql} WHERE {quote_identifier('id')} IN ({placeholders})",
                    ids,
                )
                conn.commit()
                batch_no += 1
                deleted_ids += len(ids)
                deleted_rows += int(delete_cursor.rowcount or 0)
                delete_cursor.close()
                self.log(
                    f"删除批次 {batch_no}：id {len(ids)} 个，行 {deleted_rows} 累计，"
                    f"已处理id {deleted_ids}"
                )

            self.log(f"删除完成：共删除 id {deleted_ids} 个，行 {deleted_rows} 条")
            return deleted_ids, deleted_rows
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            conn.close()

    def query_bad_data(self):
        if self.worker_running:
            return
        try:
            cfg = self.parse_config()
        except ValueError as exc:
            messagebox.showerror("配置错误", str(exc), parent=self.root)
            return
        self.last_config = None
        self.last_result = None
        self.delete_button.configure(state="disabled")
        self.summary_var.set("查询中：准备连接数据库...")
        self.set_running(True)
        self.clear_samples()
        threading.Thread(target=self._query_worker, args=(cfg,), daemon=True).start()

    def _query_worker(self, cfg: CleanerConfig):
        try:
            result = self.run_query(cfg)
        except Exception as exc:
            self.log(f"查询失败：{exc}")
            self.log(traceback.format_exc())
            self.root.after(0, lambda: self.summary_var.set("查询失败"))
        else:
            self.last_config = cfg
            self.last_result = result
            self.root.after(0, lambda: self.show_query_result(result))
        finally:
            self.root.after(0, lambda: self.set_running(False))

    def delete_bad_data(self):
        if self.worker_running:
            return
        cfg = self.last_config
        result = self.last_result
        if cfg is None or result is None:
            messagebox.showwarning("请先查询", "请先点击“查询问题数据”，确认命中数量后再删除。", parent=self.root)
            return
        if result.problem_ids <= 0:
            messagebox.showinfo("没有问题数据", "当前查询没有命中问题 id。", parent=self.root)
            return
        message = (
            f"将从 {cfg.db_key}.{cfg.table_name} 删除问题 id 的全部数据。\n\n"
            f"问题行数：{result.problem_rows}\n"
            f"问题id数：{result.problem_ids}\n"
            f"预计删除行数：{result.delete_rows}\n"
            f"删除前备份：{'开启' if cfg.backup_before_delete else '关闭'}\n\n"
            "是否继续？"
        )
        if not messagebox.askyesno("确认删除", message, parent=self.root):
            return
        self.summary_var.set("删除中：准备连接数据库...")
        self.set_running(True)
        threading.Thread(target=self._delete_worker, args=(cfg,), daemon=True).start()

    def _delete_worker(self, cfg: CleanerConfig):
        try:
            deleted_ids, deleted_rows = self.run_delete(cfg)
        except Exception as exc:
            self.log(f"删除失败：{exc}")
            self.log(traceback.format_exc())
            self.root.after(0, lambda: self.summary_var.set("删除失败"))
        else:
            self.last_result = None
            self.root.after(0, lambda: self.delete_button.configure(state="disabled"))
            self.root.after(0, lambda: self.summary_var.set(f"删除完成：id {deleted_ids} 个，行 {deleted_rows} 条"))
        finally:
            self.root.after(0, lambda: self.set_running(False))

    def show_query_result(self, result: QueryResult):
        self.clear_samples()
        for item in result.samples:
            self.samples.insert(
                "",
                "end",
                values=(
                    item.get("id"),
                    item.get("game_id"),
                    item.get("sort"),
                    int(item.get("scatter_count") or 0),
                    int(item.get("wild_count") or 0),
                    item.get("reason") or "",
                ),
            )
        self.summary_var.set(
            f"问题行 {result.problem_rows}，问题id {result.problem_ids}，预计删除 {result.delete_rows} 行"
        )
        self.delete_button.configure(state="normal" if result.problem_ids > 0 else "disabled")

    def clear_samples(self):
        for item in self.samples.get_children():
            self.samples.delete(item)

    def set_running(self, running: bool):
        self.worker_running = bool(running)
        state = "disabled" if running else "normal"
        self.query_button.configure(state=state)
        if running:
            self.delete_button.configure(state="disabled")
        elif self.last_result and self.last_result.problem_ids > 0:
            self.delete_button.configure(state="normal")

    def log(self, message: str):
        self.log_queue.put(str(message))

    def set_summary_async(self, text: str):
        self.root.after(0, lambda value=str(text): self.summary_var.set(value))

    def _poll_log_queue(self):
        try:
            while True:
                message = self.log_queue.get_nowait()
                self.log_text.insert("end", message + "\n")
                self.log_text.see("end")
        except queue.Empty:
            pass
        self.root.after(100, self._poll_log_queue)

    def clear_log(self):
        self.log_text.delete("1.0", "end")


def main():
    root = tk.Tk()
    BadDataCleanerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
