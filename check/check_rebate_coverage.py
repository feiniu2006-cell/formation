# ================== 配置区域 ==================
import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import argparse
import contextlib
import json
import queue
import re
import threading
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

import mysql.connector

from db_config import DATABASE_CONFIGS


APP_SETTINGS_FILE_NAME = 'formation_tool_settings.json'
ROOM_MODE_TABLE = 'room_mode'

# process_formation_slots_way_combined.py 的当前表设计：
# 1/2/3 是原始三类局，6/7/8 是 ex 三类局；99/98 分别复用免费局/ex免费局。
SAMPLE_MODE_DEFS = {
    '1': {'name': '普通局',   'suffix': 'formation'},
    '2': {'name': '特殊局',   'suffix': 'special_formation'},
    '3': {'name': '免费局',   'suffix': 'free_formation'},
    '6': {'name': 'ex普通局', 'suffix': 'ex_formation'},
    '7': {'name': 'ex特殊局', 'suffix': 'ex_special_formation'},
    '8': {'name': 'ex免费局', 'suffix': 'ex_free_formation'},
}

GROUP_WEIGHT_MODE_DEFS = {
    '1':  {'name': '普通局',   'source_mode': '1', 'write_game_type': 1},
    '2':  {'name': '特殊局',   'source_mode': '2', 'write_game_type': 2},
    '3':  {'name': '免费局',   'source_mode': '3', 'write_game_type': 3},
    '6':  {'name': 'ex普通局', 'source_mode': '6', 'write_game_type': 6},
    '7':  {'name': 'ex特殊局', 'source_mode': '7', 'write_game_type': 7},
    '8':  {'name': 'ex免费局', 'source_mode': '8', 'write_game_type': 8},
    '98': {'name': 'ex购买局', 'source_mode': '8', 'write_game_type': 98},
    '99': {'name': '购买局',   'source_mode': '3', 'write_game_type': 99},
}

DEFAULT_RUNTIME = {
    'vendor': '',
    'game_id': '',
    'source_db': 'DB1',
    'final_db': 'DB1',
    'config_db': 'MY',
}
VENDOR_OPTIONS = ('jili', 'pg', 'vg')

BUY_MODE = '99'
EX_BUY_MODE = '98'
BUY_LIKE_MODES = {BUY_MODE, EX_BUY_MODE}
DEFAULT_BUY_SOURCE_SUFFIX = 'free_formation'
DEFAULT_EX_BUY_SOURCE_SUFFIX = 'ex_free_formation'

EXTERNAL_CONFIG_SOURCE = None
EXTERNAL_CONFIG_LOAD_ERROR = None


# ================== 配置加载 ==================

def project_root():
    return Path(__file__).resolve().parent.parent


def formation_tool_dir():
    return project_root() / 'formation_tool'


def report_dir():
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def external_config_candidates():
    candidates = []
    if getattr(sys, 'frozen', False):
        candidates.append(Path(sys.executable).resolve().with_name('db_config.json'))
    candidates.append(project_root() / 'db_config.json')
    candidates.append(Path.cwd() / 'db_config.json')

    unique = []
    seen = set()
    for path in candidates:
        key = str(path).lower()
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def normalize_external_db_configs(data):
    if not isinstance(data, dict):
        raise ValueError("配置文件必须是 JSON 对象")
    configs = data.get('DATABASE_CONFIGS')
    if configs is None:
        configs = {
            key: value for key, value in data.items()
            if isinstance(value, dict)
        }
    if not isinstance(configs, dict) or not configs:
        raise ValueError("配置文件中未找到 DATABASE_CONFIGS")

    merged = dict(DATABASE_CONFIGS)
    for db_name, cfg in configs.items():
        if not isinstance(cfg, dict):
            raise ValueError(f"{db_name} 的配置必须是对象")
        normalized = dict(merged.get(db_name, {}))
        normalized.update(cfg)
        if 'port' in normalized:
            normalized['port'] = int(normalized['port'])
        merged[db_name] = normalized
    return merged


def load_external_database_config():
    """与 formation 工具一致：优先读取项目/exe 同目录 db_config.json。"""
    global DATABASE_CONFIGS, EXTERNAL_CONFIG_SOURCE, EXTERNAL_CONFIG_LOAD_ERROR

    for path in external_config_candidates():
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding='utf-8-sig'))
            DATABASE_CONFIGS = normalize_external_db_configs(data)
            EXTERNAL_CONFIG_SOURCE = str(path)
            EXTERNAL_CONFIG_LOAD_ERROR = None
            return
        except Exception as e:
            EXTERNAL_CONFIG_LOAD_ERROR = f"{path}: {e}"
            return


load_external_database_config()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def safe_settings_name(value):
    text = str(value).strip()
    return re.sub(r'[^0-9A-Za-z_.-]+', '_', text) or 'default'


def default_settings_candidates():
    candidates = []
    if getattr(sys, 'frozen', False):
        candidates.append(Path(sys.executable).resolve().with_name(APP_SETTINGS_FILE_NAME))
    candidates.append(formation_tool_dir() / APP_SETTINGS_FILE_NAME)
    candidates.append(Path.cwd() / APP_SETTINGS_FILE_NAME)
    return candidates


def find_settings_path(explicit_path=None):
    if explicit_path:
        path = Path(explicit_path)
        return path if path.is_file() else None
    for path in default_settings_candidates():
        if path.is_file():
            return path
    return None


def profile_settings_path(base_dir, vendor, game_id):
    filename = f"{safe_settings_name(vendor)}_{safe_settings_name(game_id)}.json"
    return Path(base_dir) / 'formation_tool_settings' / filename


@dataclass
class RuntimeConfig:
    vendor: str
    game_id: str
    source_db: str
    final_db: str
    config_db: str
    settings_path: Path | None = None
    profile_path: Path | None = None

    @property
    def table_prefix(self):
        return f'{self.vendor}_{self.game_id}_'

    @property
    def group_weight_table(self):
        return f'{self.table_prefix}group_weight'


@dataclass
class BuyGroupOptions:
    buy_source_suffix: str = DEFAULT_BUY_SOURCE_SUFFIX
    ex_buy_source_suffix: str = DEFAULT_EX_BUY_SOURCE_SUFFIX
    # extra_buy_groups: list of {'game_type': int, 'source_suffix': str}
    extra_buy_groups: list = None

    def __post_init__(self):
        if self.extra_buy_groups is None:
            self.extra_buy_groups = []

    def get_source_suffix(self, mode):
        """返回指定 mode 对应的阵型表后缀。mode 为字符串。"""
        mode = str(mode)
        if mode == BUY_MODE:
            return self.buy_source_suffix or DEFAULT_BUY_SOURCE_SUFFIX
        if mode == EX_BUY_MODE:
            return self.ex_buy_source_suffix or DEFAULT_EX_BUY_SOURCE_SUFFIX
        # extra_buy 动态 game_type
        for g in self.extra_buy_groups:
            if str(g.get('game_type', '')) == mode:
                return g.get('source_suffix') or DEFAULT_BUY_SOURCE_SUFFIX
        return None


def load_buy_group_options(profile_path, settings_path):
    """从配置文件的 group_weight_options 读取购买局 source_suffix 配置。"""
    opts = BuyGroupOptions()
    for path in (profile_path, settings_path):
        if path is None:
            continue
        try:
            data = read_json(path)
        except Exception:
            continue
        gw_opts = data.get('group_weight_options') if isinstance(data, dict) else None
        if not isinstance(gw_opts, dict):
            continue
        if 'buy_source_suffix' in gw_opts and gw_opts['buy_source_suffix']:
            opts.buy_source_suffix = str(gw_opts['buy_source_suffix']).strip()
        if 'ex_buy_source_suffix' in gw_opts and gw_opts['ex_buy_source_suffix']:
            opts.ex_buy_source_suffix = str(gw_opts['ex_buy_source_suffix']).strip()
        raw_extra = gw_opts.get('extra_buy_groups')
        if isinstance(raw_extra, list):
            parsed = []
            for item in raw_extra:
                if not isinstance(item, dict):
                    continue
                try:
                    game_type = int(item['game_type'])
                except (KeyError, TypeError, ValueError):
                    continue
                source_suffix = str(item.get('source_suffix') or DEFAULT_BUY_SOURCE_SUFFIX).strip()
                parsed.append({'game_type': game_type, 'source_suffix': source_suffix})
            if parsed:
                opts.extra_buy_groups = parsed
        break  # 优先用 profile_path，找到就停
    return opts


def merge_runtime(runtime, data):
    if not isinstance(data, dict):
        return runtime
    for key, value in data.get('runtime', {}).items():
        if key in runtime and value is not None:
            runtime[key] = str(value).strip()
    return runtime


def load_runtime_config(args):
    runtime = dict(DEFAULT_RUNTIME)
    settings_path = None
    if not getattr(args, 'ignore_settings', False) and args.settings:
        settings_path = find_settings_path(args.settings)
        if settings_path is None:
            raise ValueError(f"配置文件不存在: {args.settings}")
    profile_path = None

    if settings_path:
        data = read_json(settings_path)
        merge_runtime(runtime, data)

        vendor = runtime.get('vendor', '').strip()
        game_id = runtime.get('game_id', '').strip()
        if vendor and game_id:
            candidate = profile_settings_path(settings_path.parent, vendor, game_id)
            if candidate.is_file():
                profile_path = candidate
                profile_data = read_json(candidate)
                merge_runtime(runtime, profile_data)

    for key in ('vendor', 'game_id', 'source_db', 'final_db', 'config_db'):
        value = getattr(args, key, None)
        if value is not None:
            runtime[key] = str(value).strip()

    return RuntimeConfig(
        vendor=runtime['vendor'],
        game_id=runtime['game_id'],
        source_db=runtime['source_db'],
        final_db=runtime['final_db'],
        config_db=runtime['config_db'],
        settings_path=settings_path,
        profile_path=profile_path,
    )


def validate_runtime_config(config):
    missing = []
    if not config.vendor:
        missing.append('vendor')
    if not config.game_id:
        missing.append('game_id')
    if not config.final_db:
        missing.append('final_db')
    if missing:
        raise ValueError(
            "缺少运行配置: "
            + ', '.join(missing)
            + "。请在界面填写，或用命令行参数指定。"
        )

    for label, db_name in (
        ('源库', config.source_db),
        ('目标库', config.final_db),
        ('配置库', config.config_db),
    ):
        if db_name and db_name not in DATABASE_CONFIGS:
            raise ValueError(f"{label}配置不存在: {db_name}，可选数据库: {list(DATABASE_CONFIGS.keys())}")


# ================== 数据库工具 ==================

def quote_identifier(name):
    return '`' + str(name).replace('`', '``') + '`'


def connect_to_db(db_name):
    cfg = dict(DATABASE_CONFIGS[db_name])
    cfg.setdefault('use_pure', True)
    return mysql.connector.connect(**cfg)


def get_columns(cursor, table_name):
    """返回表的所有列名集合，表不存在返回 None。"""
    cursor.execute(
        "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s",
        (table_name,),
    )
    rows = cursor.fetchall()
    return {row[0] for row in rows} if rows else None


def table_exists(cursor, table_name):
    cursor.execute(
        "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s",
        (table_name,),
    )
    return cursor.fetchone()[0] > 0


def detect_rebate_field(cursor, table_name):
    """找含 rebate 的字段，优先精确匹配 rebate。"""
    cols = get_columns(cursor, table_name)
    if not cols:
        return None
    rebate_cols = [c for c in cols if 'rebate' in c.lower()]
    if not rebate_cols:
        return None
    return 'rebate' if 'rebate' in rebate_cols else sorted(rebate_cols)[0]


def detect_end_condition(cursor, table_name):
    """检测 game_end / is_end 字段，返回 WHERE 条件片段。"""
    cols = get_columns(cursor, table_name) or set()
    if 'game_end' in cols:
        return f"{quote_identifier('game_end')} = 1"
    if 'is_end' in cols:
        return f"{quote_identifier('is_end')} = 1"
    return '1=1'


def normalize_rebate(value):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def normalize_rebate_rows(rows):
    values = set()
    for row in rows:
        value = normalize_rebate(row[0])
        if value is not None:
            values.add(value)
    return values


def fetch_formation_rebates(cursor, table_name, field):
    condition = detect_end_condition(cursor, table_name)
    cursor.execute(
        f"SELECT DISTINCT {quote_identifier(field)} "
        f"FROM {quote_identifier(table_name)} WHERE {condition}"
    )
    return normalize_rebate_rows(cursor.fetchall())


def placeholders(values):
    return ', '.join(['%s'] * len(values))


def fetch_weight_rebates(cursor, table_name, field, game_types):
    cursor.execute(
        f"SELECT DISTINCT {quote_identifier(field)} "
        f"FROM {quote_identifier(table_name)} "
        f"WHERE {quote_identifier('game_type')} IN ({placeholders(game_types)})",
        tuple(game_types),
    )
    return normalize_rebate_rows(cursor.fetchall())


def count_weight_rows(cursor, table_name, game_type):
    cursor.execute(
        f"SELECT COUNT(*) FROM {quote_identifier(table_name)} "
        f"WHERE {quote_identifier('game_type')} = %s",
        (int(game_type),),
    )
    return int(cursor.fetchone()[0])


def fetch_weight_game_types(cursor, table_name):
    cursor.execute(
        f"SELECT DISTINCT {quote_identifier('game_type')} "
        f"FROM {quote_identifier(table_name)} ORDER BY {quote_identifier('game_type')}"
    )
    values = []
    for (value,) in cursor.fetchall():
        if value is not None:
            values.append(str(int(value)))
    return values


# ================== 核对逻辑 ==================

def formation_table_name(config, mode, buy_opts=None):
    """返回 mode 对应的阵型表名。购买局类型使用 buy_opts 中的 source_suffix。"""
    if mode in BUY_LIKE_MODES or (buy_opts and buy_opts.get_source_suffix(mode) is not None):
        if buy_opts:
            suffix = buy_opts.get_source_suffix(mode)
            if suffix:
                return f'{config.table_prefix}{suffix}'
    if mode in SAMPLE_MODE_DEFS:
        suffix = SAMPLE_MODE_DEFS[mode]['suffix']
        return f'{config.table_prefix}{suffix}'
    return None


def mode_sort_key(mode):
    return int(mode)


def parse_modes(text):
    if not text:
        return None
    modes = [item.strip() for item in str(text).split(',') if item.strip()]
    unknown = [mode for mode in modes if mode not in GROUP_WEIGHT_MODE_DEFS]
    if unknown:
        raise ValueError(f"未知模式: {', '.join(unknown)}")
    return tuple(sorted(set(modes), key=mode_sort_key))


def build_modes_to_check(weight_cursor, formation_cursor, config, weight_table,
                         explicit_modes=None, buy_opts=None):
    # 标准模式的 formation 表是否存在
    formation_exists = {
        mode: table_exists(formation_cursor, formation_table_name(config, mode, buy_opts))
        for mode in SAMPLE_MODE_DEFS
    }
    # 购买局使用 buy_opts 中配置的 suffix，额外检查对应表是否存在
    if buy_opts:
        for buy_mode in (BUY_MODE, EX_BUY_MODE):
            tname = formation_table_name(config, buy_mode, buy_opts)
            if tname:
                formation_exists[buy_mode] = table_exists(formation_cursor, tname)
        for g in buy_opts.extra_buy_groups:
            mode = str(g['game_type'])
            tname = f"{config.table_prefix}{g['source_suffix']}"
            formation_exists[mode] = table_exists(formation_cursor, tname)

    observed_modes = set(fetch_weight_game_types(weight_cursor, weight_table))

    # 已知模式 = GROUP_WEIGHT_MODE_DEFS + extra_buy_groups 的 game_type
    known_modes = set(GROUP_WEIGHT_MODE_DEFS)
    if buy_opts:
        for g in buy_opts.extra_buy_groups:
            known_modes.add(str(g['game_type']))

    supported_observed = observed_modes & known_modes
    if explicit_modes:
        supported_observed &= set(explicit_modes)
    modes = sorted(supported_observed, key=mode_sort_key)
    unsupported_modes = sorted(observed_modes - known_modes, key=int)
    return modes, formation_exists, unsupported_modes


def check_single_game(config, weight_db_name, formation_db_name, explicit_modes=None, buy_opts=None):
    """
    返回 (results, unsupported_modes)。
    results 每项是 dict，status:
      ok | missing | no_game | no_formation_table | no_rebate_field | unsupported_weight_type
    """
    weight_conn = connect_to_db(weight_db_name)
    formation_conn = weight_conn if formation_db_name == weight_db_name else connect_to_db(formation_db_name)
    weight_cursor = weight_conn.cursor()
    formation_cursor = formation_conn.cursor()

    try:
        weight_table = config.group_weight_table
        if not table_exists(weight_cursor, weight_table):
            return ([{
                'mode': None,
                'label': weight_table,
                'status': 'no_game',
                'missing': [],
                'total': 0,
                'formation_table': None,
            }], [])

        weight_rebate_field = detect_rebate_field(weight_cursor, weight_table)
        if weight_rebate_field is None:
            return ([{
                'mode': None,
                'label': weight_table,
                'status': 'no_rebate_field',
                'missing': [],
                'total': 0,
                'formation_table': None,
            }], [])

        modes, formation_exists, unsupported_modes = build_modes_to_check(
            weight_cursor,
            formation_cursor,
            config,
            weight_table,
            explicit_modes=explicit_modes,
            buy_opts=buy_opts,
        )

        results = []
        for mode in modes:
            if mode in GROUP_WEIGHT_MODE_DEFS:
                mode_def = GROUP_WEIGHT_MODE_DEFS[mode]
                name = mode_def['name']
                game_type = mode_def['write_game_type']
                source_mode = mode_def['source_mode']
                # 购买局用 buy_opts 覆盖 source_mode 推导的表名
                if mode in BUY_LIKE_MODES and buy_opts:
                    formation_table = formation_table_name(config, mode, buy_opts)
                else:
                    formation_table = formation_table_name(config, source_mode, buy_opts)
            else:
                # extra_buy 动态模式
                game_type = int(mode)
                name = f'购买局(game_type={game_type})'
                formation_table = formation_table_name(config, mode, buy_opts)

            label = f"{name} game_type={game_type} → {formation_table}"
            rebates_a = fetch_weight_rebates(weight_cursor, weight_table, weight_rebate_field, [game_type])

            if not rebates_a:
                continue

            if not formation_exists.get(mode):
                results.append({
                    'mode': mode,
                    'label': label,
                    'status': 'no_formation_table',
                    'missing': [],
                    'total': len(rebates_a),
                    'formation_table': formation_table,
                })
                continue

            formation_rebate_field = detect_rebate_field(formation_cursor, formation_table)
            if formation_rebate_field is None:
                results.append({
                    'mode': mode,
                    'label': label,
                    'status': 'no_rebate_field',
                    'missing': [],
                    'total': 0,
                    'formation_table': formation_table,
                })
                continue

            rebates_b = fetch_formation_rebates(formation_cursor, formation_table, formation_rebate_field)
            missing = sorted(rebates_a - rebates_b)
            results.append({
                'mode': mode,
                'label': label,
                'status': 'missing' if missing else 'ok',
                'missing': missing,
                'total': len(rebates_a),
                'formation_table': formation_table,
            })

        for mode in unsupported_modes:
            results.append({
                'mode': mode,
                'label': f"未知 game_type={mode}",
                'status': 'unsupported_weight_type',
                'missing': [],
                'total': count_weight_rows(weight_cursor, weight_table, int(mode)),
                'formation_table': None,
            })

        return results, unsupported_modes
    finally:
        weight_cursor.close()
        formation_cursor.close()
        if formation_conn is not weight_conn:
            formation_conn.close()
        weight_conn.close()


# ================== 旧 room_mode 批量兼容入口 ==================

def load_room_modes(config_db_name):
    conn = connect_to_db(config_db_name)
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            f"SELECT room_id, vendor, type1, type2, type3, type4 "
            f"FROM {quote_identifier(ROOM_MODE_TABLE)} WHERE enabled = 1 ORDER BY room_id"
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


def extract_legacy_modes(row):
    # 直接读取 type1-4 字段的值作为 game_type，支持 1/2/3/6/7/8/98/99 等所有模式
    modes = []
    seen = set()
    for n in range(1, 5):
        raw = row.get(f'type{n}')
        if not raw:
            continue
        try:
            mode = str(int(raw))
        except (TypeError, ValueError):
            continue
        if mode in GROUP_WEIGHT_MODE_DEFS and mode not in seen:
            seen.add(mode)
            modes.append(mode)
    return tuple(sorted(modes, key=mode_sort_key))


def run_legacy_room_mode_check(args):
    config_db = args.config_db or DEFAULT_RUNTIME['config_db']
    check_db = args.check_db or args.final_db or DEFAULT_RUNTIME['final_db']
    print("=== rebate 覆盖核对（旧 room_mode 批量兼容模式）===")
    print(f"读取配置库 [{config_db}].{ROOM_MODE_TABLE}，核对库 [{check_db}]")

    room_modes = load_room_modes(config_db)
    if not room_modes:
        print(f"[警告] {ROOM_MODE_TABLE} 表中无启用记录。")
        return

    all_results = {}
    for row in room_modes:
        config = RuntimeConfig(
            vendor=str(row['vendor']).strip(),
            game_id=str(row['room_id']).strip(),
            source_db=check_db,
            final_db=check_db,
            config_db=config_db,
        )
        modes = extract_legacy_modes(row)
        label = f'{config.vendor}_{config.game_id}'
        print(f"\n{'-' * 60}")
        print(f"游戏: {label}  模式: {', '.join(modes) or '无'}")
        results, _ = check_single_game(config, check_db, check_db, explicit_modes=modes)
        all_results[label] = results

    return write_report(all_results, check_db, check_db, legacy=True)


# ================== 输出 ==================

def format_missing(values, limit=200):
    if len(values) <= limit:
        return str(values)
    preview = values[:limit]
    return f"{preview} ...（其余 {len(values) - limit} 个已省略）"


def write_report(all_results, weight_db_name, formation_db_name, legacy=False):
    ok_games = []
    issue_games = []
    for game_label, results in all_results.items():
        issues = [item for item in results if item['status'] != 'ok']
        if issues:
            issue_games.append((game_label, issues))
        else:
            ok_games.append(game_label)

    def out(text=''):
        print(text)

    out(f"{'=' * 60}")
    out(f"核对结果汇总  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    out(f"权重库: {weight_db_name}；阵型库: {formation_db_name}")
    out(f"{'=' * 60}")

    for game_label, issues in issue_games:
        out(f"\n【{game_label}】")
        for item in issues:
            label = item['label']
            status = item['status']
            missing = item['missing']
            total = item['total']
            if status == 'no_game':
                out(f"  [不存在] 权重表 {label} 不存在，该游戏尚未部署 group_weight")
            elif status == 'no_formation_table':
                out(f"  [错误] {label}  — 阵型表不存在（group_weight 有 {total} 个 rebate 未被覆盖）")
            elif status == 'no_rebate_field':
                out(f"  [错误] {label}  — 未找到 rebate 字段")
            elif status == 'unsupported_weight_type':
                out(f"  [错误] {label}  — 当前检查脚本不支持该 game_type，表中有 {total} 行")
            elif status == 'missing':
                out(f"  [缺失] {label}  — 权重表共 {total} 个 rebate，缺失 {len(missing)} 个:")
                out(f"         {format_missing(missing)}")

    out(f"\n{'-' * 60}")
    if ok_games:
        out(f"核对通过（{len(ok_games)} 个）: {', '.join(ok_games)}")
        if not issue_games:
            out("未发现阵型缺漏：group_weight 中所有 rebate 均已被对应最终阵型表覆盖。")
    if issue_games:
        out(f"存在问题（{len(issue_games)} 个）: {', '.join(g for g, _ in issue_games)}")
    if not ok_games and not issue_games:
        out("没有可核对的游戏。")
    out(f"{'=' * 60}")
    return None


def build_arg_parser():
    parser = argparse.ArgumentParser(
        description="按 formation 工具当前设计核对 group_weight rebate 是否被最终阵型表覆盖。"
    )
    parser.add_argument('--settings', help='可选：读取指定 formation_tool_settings.json 路径')
    parser.add_argument('--vendor', help='厂商/表前缀，例如 jili')
    parser.add_argument('--game-id', dest='game_id', help='游戏编号，例如 110')
    parser.add_argument('--source-db', dest='source_db', help=f"源库，仅用于展示/参数完整性；默认 {DEFAULT_RUNTIME['source_db']}")
    parser.add_argument('--final-db', dest='final_db', help=f"目标库；默认 {DEFAULT_RUNTIME['final_db']}")
    parser.add_argument('--config-db', dest='config_db', help=f"采样配置库；默认 {DEFAULT_RUNTIME['config_db']}")
    parser.add_argument('--weight-db', help='group_weight 所在库；默认使用 final_db')
    parser.add_argument('--formation-db', help='最终阵型表所在库；默认使用 final_db')
    parser.add_argument('--modes', help='只在 group_weight 已存在的 game_type 中筛选，例如 1,2,3,6,7,8,98,99')
    parser.add_argument('--all-room-mode', action='store_true', help='兼容旧版：从 room_mode 批量读取游戏')
    parser.add_argument('--check-db', help='旧版 room_mode 批量模式下的核对库')
    return parser


def make_args_namespace(**overrides):
    values = {
        'settings': None,
        'vendor': None,
        'game_id': None,
        'source_db': None,
        'final_db': None,
        'config_db': None,
        'weight_db': None,
        'formation_db': None,
        'modes': None,
        'all_room_mode': False,
        'check_db': None,
        'ignore_settings': False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class QueueWriter:
    def __init__(self, log_queue):
        self.log_queue = log_queue

    def write(self, text):
        if text:
            self.log_queue.put(('log', text))

    def flush(self):
        pass


class RebateCoverageApp:
    def __init__(self, root):
        self.root = root
        self.root.title("rebate 覆盖核对")
        self.root.geometry("980x720")
        self.root.minsize(880, 620)

        self.running = False
        self.worker = None
        self.log_queue = queue.Queue()

        self.vendor_var = tk.StringVar()
        self.game_id_var = tk.StringVar()
        self.source_db_var = tk.StringVar()
        self.final_db_var = tk.StringVar()
        self.config_db_var = tk.StringVar()
        self.weight_db_var = tk.StringVar()
        self.formation_db_var = tk.StringVar()
        self.check_db_var = tk.StringVar()
        self.legacy_mode_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="就绪")

        self.config_widgets = []
        self.readonly_widgets = set()
        self.action_buttons = []

        self.build_ui()
        self.reset_manual_defaults()
        self.poll_log_queue()

    def build_ui(self):
        container = ttk.Frame(self.root, padding=12)
        container.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(2, weight=1)

        config_frame = ttk.LabelFrame(container, text="运行配置", padding=10)
        config_frame.grid(row=0, column=0, sticky="ew")
        config_frame.columnconfigure(1, weight=1)

        db_names = sorted(DATABASE_CONFIGS)
        self.add_combo(config_frame, 0, 0, "厂商", self.vendor_var, VENDOR_OPTIONS, state="readonly")
        self.add_entry(config_frame, 0, 2, "游戏编号", self.game_id_var)
        self.add_combo(config_frame, 0, 4, "源库", self.source_db_var, db_names)
        self.add_combo(config_frame, 1, 0, "目标库", self.final_db_var, db_names)
        self.add_combo(config_frame, 1, 2, "配置库", self.config_db_var, db_names)
        self.add_combo(config_frame, 1, 4, "权重库", self.weight_db_var, db_names)
        self.add_combo(config_frame, 2, 0, "阵型库", self.formation_db_var, db_names)
        self.add_combo(config_frame, 2, 2, "旧版核对库", self.check_db_var, db_names)

        option_frame = ttk.Frame(config_frame)
        option_frame.grid(row=3, column=0, columnspan=8, sticky="ew", pady=(6, 0))
        ttk.Checkbutton(option_frame, text="旧 room_mode 批量", variable=self.legacy_mode_var).grid(row=0, column=0, sticky="w")
        self.config_widgets.extend(option_frame.winfo_children())

        button_frame = ttk.Frame(container)
        button_frame.grid(row=1, column=0, sticky="ew", pady=(10, 8))
        button_frame.columnconfigure(4, weight=1)
        run_button = ttk.Button(button_frame, text="开始核对", command=self.start_check)
        clear_button = ttk.Button(button_frame, text="清空日志", command=self.clear_log)
        open_button = ttk.Button(button_frame, text="打开程序目录", command=self.open_report_dir)
        reset_button = ttk.Button(button_frame, text="重置默认", command=self.reset_manual_defaults)
        run_button.grid(row=0, column=0, sticky="w")
        reset_button.grid(row=0, column=1, sticky="w", padx=(8, 0))
        clear_button.grid(row=0, column=2, sticky="w", padx=(8, 0))
        open_button.grid(row=0, column=3, sticky="w", padx=(8, 0))
        self.action_buttons = [run_button, clear_button, open_button, reset_button]

        log_frame = ttk.LabelFrame(container, text="运行日志", padding=8)
        log_frame.grid(row=2, column=0, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log_text = scrolledtext.ScrolledText(log_frame, wrap="word", height=18, state="disabled")
        self.log_text.grid(row=0, column=0, sticky="nsew")

        status_frame = ttk.Frame(container)
        status_frame.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        status_frame.columnconfigure(0, weight=1)
        ttk.Label(status_frame, textvariable=self.status_var).grid(row=0, column=0, sticky="w")
        self.progress = ttk.Progressbar(status_frame, mode="indeterminate", length=160)
        self.progress.grid(row=0, column=1, sticky="e")

    def add_entry(self, parent, row, col, label, variable):
        ttk.Label(parent, text=label).grid(row=row, column=col, sticky="w", padx=(0, 8), pady=4)
        entry = ttk.Entry(parent, textvariable=variable, width=18)
        entry.grid(row=row, column=col + 1, sticky="ew", padx=(0, 14), pady=4)
        self.config_widgets.append(entry)
        parent.columnconfigure(col + 1, weight=1)
        return entry

    def add_combo(self, parent, row, col, label, variable, values, state="normal"):
        ttk.Label(parent, text=label).grid(row=row, column=col, sticky="w", padx=(0, 8), pady=4)
        combo = ttk.Combobox(parent, textvariable=variable, values=values, width=16, state=state)
        combo.grid(row=row, column=col + 1, sticky="ew", padx=(0, 14), pady=4)
        self.config_widgets.append(combo)
        if state == "readonly":
            self.readonly_widgets.add(combo)
        parent.columnconfigure(col + 1, weight=1)
        return combo

    def reset_manual_defaults(self):
        self.vendor_var.set(VENDOR_OPTIONS[0])
        self.game_id_var.set("")
        self.source_db_var.set(DEFAULT_RUNTIME['source_db'])
        self.final_db_var.set(DEFAULT_RUNTIME['final_db'])
        self.config_db_var.set(DEFAULT_RUNTIME['config_db'])
        self.weight_db_var.set(DEFAULT_RUNTIME['final_db'])
        self.formation_db_var.set(DEFAULT_RUNTIME['final_db'])
        self.check_db_var.set(DEFAULT_RUNTIME['final_db'])
        self.legacy_mode_var.set(False)
        self.status_var.set("请手动填写游戏编号后开始核对")

    def collect_args(self):
        def none_if_blank(value):
            text = str(value).strip()
            return text or None

        return make_args_namespace(
            settings=None,
            vendor=none_if_blank(self.vendor_var.get()),
            game_id=none_if_blank(self.game_id_var.get()),
            source_db=none_if_blank(self.source_db_var.get()),
            final_db=none_if_blank(self.final_db_var.get()),
            config_db=none_if_blank(self.config_db_var.get()),
            weight_db=none_if_blank(self.weight_db_var.get()),
            formation_db=none_if_blank(self.formation_db_var.get()),
            modes=None,
            all_room_mode=bool(self.legacy_mode_var.get()),
            check_db=none_if_blank(self.check_db_var.get()),
            ignore_settings=True,
        )

    def start_check(self):
        if self.running:
            messagebox.showinfo("正在运行", "当前核对还没有结束。")
            return
        try:
            args = self.collect_args()
            parse_modes(args.modes)
        except Exception as e:
            messagebox.showerror("配置错误", str(e))
            return

        self.running = True
        self.status_var.set("核对中...")
        self.progress.start(12)
        self.set_running_state(True)
        self.append_log(f"\n=== 开始核对 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        self.worker = threading.Thread(target=self.worker_main, args=(args,), daemon=True)
        self.worker.start()

    def worker_main(self, args):
        writer = QueueWriter(self.log_queue)
        ok = True
        error = None
        with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
            try:
                run_configured_check(args)
            except Exception:
                ok = False
                error = traceback.format_exc()
                print(error)
        self.log_queue.put(('done', ok, error))

    def poll_log_queue(self):
        try:
            while True:
                item = self.log_queue.get_nowait()
                if item[0] == 'log':
                    self.append_log(item[1])
                elif item[0] == 'done':
                    _, ok, error = item
                    self.finish_task(ok, error)
        except queue.Empty:
            pass
        self.root.after(100, self.poll_log_queue)

    def append_log(self, text):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def clear_log(self):
        if self.running:
            messagebox.showinfo("正在运行", "核对运行中暂不能清空日志。")
            return
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def finish_task(self, ok, error):
        self.running = False
        self.progress.stop()
        self.set_running_state(False)
        self.status_var.set("核对完成" if ok else "核对失败")
        if error:
            messagebox.showerror("核对失败", "核对失败，详情请查看运行日志。")

    def set_running_state(self, running):
        for widget in self.config_widgets:
            try:
                if running:
                    widget.configure(state="disabled")
                else:
                    widget.configure(state="readonly" if widget in self.readonly_widgets else "normal")
            except tk.TclError:
                pass
        for button in self.action_buttons:
            try:
                button.configure(state="disabled" if running else "normal")
            except tk.TclError:
                pass

    def open_report_dir(self):
        target = report_dir()
        target.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(target))
        except Exception as e:
            messagebox.showerror("打开失败", str(e))


def run_gui():
    root = tk.Tk()
    RebateCoverageApp(root)
    root.mainloop()


def run_configured_check(args):
    if args.all_room_mode:
        return run_legacy_room_mode_check(args)

    config = load_runtime_config(args)
    validate_runtime_config(config)
    explicit_modes = parse_modes(args.modes)

    weight_db_name = args.weight_db or config.final_db
    formation_db_name = args.formation_db or config.final_db
    for label, db_name in (('权重库', weight_db_name), ('阵型库', formation_db_name)):
        if db_name not in DATABASE_CONFIGS:
            raise ValueError(f"{label}配置不存在: {db_name}，可选数据库: {list(DATABASE_CONFIGS.keys())}")

    print("=== rebate 覆盖核对（formation 工具当前设计）===")
    print(f"游戏: {config.vendor}_{config.game_id}")
    print(f"源库={config.source_db or '-'}，目标库={config.final_db}，配置库={config.config_db}")
    print(f"核对 group_weight: {weight_db_name}.{config.group_weight_table}")
    print(f"核对最终阵型库: {formation_db_name}")
    print("核对依据: group_weight 表中实际存在的 game_type")
    if config.settings_path:
        print(f"基础配置: {config.settings_path}")
    if config.profile_path:
        print(f"房间配置: {config.profile_path}")
    if EXTERNAL_CONFIG_SOURCE:
        print(f"数据库配置来源: 外部文件 {EXTERNAL_CONFIG_SOURCE}")
    elif EXTERNAL_CONFIG_LOAD_ERROR:
        print(f"外部数据库配置加载失败，使用内置配置: {EXTERNAL_CONFIG_LOAD_ERROR}")

    buy_opts = load_buy_group_options(config.profile_path, config.settings_path)
    if buy_opts.buy_source_suffix != DEFAULT_BUY_SOURCE_SUFFIX:
        print(f"购买局阵型源表后缀: {buy_opts.buy_source_suffix}")
    if buy_opts.extra_buy_groups:
        for g in buy_opts.extra_buy_groups:
            print(f"额外购买局 game_type={g['game_type']} 阵型源表后缀: {g['source_suffix']}")

    label = f'{config.vendor}_{config.game_id}'
    results, _ = check_single_game(config, weight_db_name, formation_db_name, explicit_modes, buy_opts)

    all_results = {label: results}
    return write_report(all_results, weight_db_name, formation_db_name)


def cli_main(argv=None):
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        run_configured_check(args)
    except Exception:
        e = sys.exc_info()[1]
        print(f"[错误] {e}")
        print(traceback.format_exc())


def main():
    cli_main()


if __name__ == '__main__':
    if len(sys.argv) == 1:
        run_gui()
    elif sys.argv[1] == '--gui':
        run_gui()
    elif sys.argv[1] == '--cli':
        cli_main(sys.argv[2:])
    else:
        cli_main()
