"""Runtime preflight checks before long-running formation tasks."""

from __future__ import annotations

from dataclasses import dataclass, field
import re

from formation_tool.utils import log_utils


@dataclass
class PreflightReport:
    """Collected preflight messages for one task."""

    title: str
    fatal_errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)

    @property
    def ok(self):
        return not self.fatal_errors

    def add_fatal(self, message):
        self.fatal_errors.append(str(message))

    def add_warning(self, message):
        self.warnings.append(str(message))

    def add_info(self, message):
        self.info.append(str(message))


def emit_preflight_report(report):
    """Print a concise preflight report to the current log sink."""
    log_utils.print_section(f"运行前预检查：{report.title}")
    for message in report.info:
        log_utils.emit(f"  [OK] {message}")
    for message in report.warnings:
        log_utils.emit(f"  [警告] {message}")
    for message in report.fatal_errors:
        log_utils.emit(f"  [失败] {message}")
    if report.ok:
        suffix = f"，警告 {len(report.warnings)} 项" if report.warnings else ""
        log_utils.emit(f"预检查通过{suffix}")
    else:
        log_utils.emit(f"预检查失败，已中断任务；失败 {len(report.fatal_errors)} 项")


def _normalize_modes(modes, game_configs):
    if modes in (None, "all"):
        return list(game_configs)
    return [str(mode) for mode in modes if str(mode) in game_configs]


def _safe_count_rows(conn, table_name, deps):
    try:
        return deps.count_table_rows(conn, table_name)
    except Exception as exc:
        raise RuntimeError(f"读取 {table_name} 行数失败：{exc}") from exc


def _check_selected_database_names(report, runtime, database_configs):
    for label, key in (("源库", "source_db"), ("目标库", "final_db"), ("配置库", "config_db")):
        db_name = runtime.get(key)
        if not db_name:
            report.add_fatal(f"{label}未选择")
        elif db_name not in database_configs:
            report.add_fatal(f"{label} {db_name} 不在当前数据库配置中")


def _check_runtime_identity(report, runtime):
    if not str(runtime.get("vendor") or "").strip():
        report.add_fatal("厂商不能为空")
    if not str(runtime.get("game_id") or "").strip():
        report.add_fatal("游戏编号不能为空")


def _check_trigger_weights(report, deps):
    weights = deps.get_trigger_weights()
    for label, key in (
        ("特殊局0", "special_0"),
        ("特殊局1", "special_1"),
        ("免费局0", "free_0"),
        ("免费局1", "free_1"),
    ):
        try:
            value = int(weights.get(key))
        except (TypeError, ValueError):
            report.add_fatal(f"{label}触发权重必须是整数：{weights.get(key)!r}")
            continue
        if value < 0:
            report.add_fatal(f"{label}触发权重不能小于 0：{value}")
        elif value > 10000:
            report.add_fatal(f"{label}触发权重不能大于 10000：{value}")
    report.add_info("触发权重配置格式已检查")


def _check_rule_configs(report, deps):
    try:
        deps.validate_rebate_rules(deps.get_rebate_rules())
        report.add_info("采样规则格式已检查")
    except Exception as exc:
        report.add_fatal(f"采样规则配置错误：{exc}")

    try:
        deps.validate_group_weight_rules(deps.get_group_weight_rules())
        report.add_info("group_weight 权重规则格式已检查")
    except Exception as exc:
        report.add_fatal(f"group_weight 权重规则配置错误：{exc}")


def _check_positive_number(report, label, value):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        report.add_fatal(f"{label}必须是数字：{value!r}")
        return None
    if parsed <= 0:
        report.add_fatal(f"{label}必须大于 0：{value}")
    return parsed


def _check_source_suffix(report, label, value):
    text = str(value or "").strip()
    if not text:
        report.add_fatal(f"{label}不能为空")
        return
    if not re.fullmatch(r"[0-9A-Za-z_]+", text):
        report.add_fatal(f"{label}只能包含英文、数字、下划线：{text}")


def _check_buy_groups(report, deps):
    groups = list(deps.get_buy_groups() or [])
    enabled_groups = [group for group in groups if group.get("enabled", True)]
    seen_game_types = {}
    reserved_game_types = {1, 2, 3, 6, 7, 8, 98}
    for idx, group in enumerate(enabled_groups, start=1):
        try:
            game_type = int(group.get("game_type"))
        except (TypeError, ValueError):
            report.add_fatal(f"购买局第 {idx} 行类型必须是整数：{group.get('game_type')!r}")
            continue
        if game_type in reserved_game_types:
            report.add_fatal(f"购买局类型 {game_type} 与内置局类型冲突")
        if game_type in seen_game_types:
            report.add_fatal(f"购买局类型重复：{game_type}，第 {seen_game_types[game_type]} 行和第 {idx} 行")
        seen_game_types[game_type] = idx
        _check_positive_number(report, f"购买局{game_type}倍数", group.get("multiplier"))
        _check_source_suffix(report, f"购买局{game_type}阵型后缀", group.get("source_suffix"))

    _check_positive_number(report, "ex倍数", deps.get_ex_group_multiplier())
    special_target = deps.get_special_group_target_rtp()
    if special_target is not None:
        _check_positive_number(report, "特殊局目标RTP", special_target)
    report.add_info(
        f"购买局配置已检查：启用 {len(enabled_groups)} 个"
        if enabled_groups else "购买局配置已检查：未启用购买局"
    )


def _check_config_values(report, runtime, deps):
    _check_runtime_identity(report, runtime)
    _check_trigger_weights(report, deps)
    _check_rule_configs(report, deps)
    _check_buy_groups(report, deps)


def _connect_required_databases(report, db_names, deps):
    connections = {}
    for db_name in sorted(set(db_names)):
        if not db_name:
            continue
        try:
            conn = deps.connect_to_database(db_name)
            if not conn:
                report.add_fatal(f"无法连接数据库 {db_name}")
                continue
            connections[db_name] = conn
            report.add_info(f"数据库连接可用：{db_name}")
        except Exception as exc:
            report.add_fatal(f"连接数据库 {db_name} 失败：{exc}")
    return connections


def _close_connections(connections, deps):
    for conn in connections.values():
        deps.close_safely(conn)


def _collect_table_databases(game_configs, modes):
    db_names = set()
    for mode in modes:
        config = game_configs.get(mode)
        if not config:
            continue
        for table_info in config.get("table_config", {}).values():
            if isinstance(table_info, dict) and table_info.get("database"):
                db_names.add(table_info["database"])
    return db_names


def _check_source_tables(report, modes, game_configs, formation_exists, deps, *, missing_is_warning=False):
    for mode in modes:
        config = game_configs.get(mode)
        if not config:
            report.add_fatal(f"未找到局类型 {mode} 的表配置")
            continue
        if formation_exists.get(mode, False):
            source_table = deps.get_table_name("SOURCE_TABLE", config["table_config"])
            report.add_info(f"{config['name']} 源表存在：{source_table}")
            continue
        check_error = deps.get_source_formation_check_error(mode)
        if check_error:
            message = f"{config['name']} 源表检测失败：{check_error}"
        else:
            source_db = deps.get_table_database("SOURCE_TABLE", config["table_config"])
            source_table = deps.get_table_name("SOURCE_TABLE", config["table_config"])
            message = f"{config['name']} 未检测到源表：{source_db}.{source_table}"
        if missing_is_warning:
            report.add_warning(f"{message}，全部采样将跳过该局")
        else:
            report.add_fatal(message)

def _check_sampling_config_tables(report, modes, game_configs, connections, deps):
    for mode in modes:
        config = game_configs.get(mode)
        if not config:
            continue
        table_config = config["table_config"]
        config_db = deps.get_table_database("REBATE_CONFIG_TABLE", table_config)
        config_table = deps.get_table_name("REBATE_CONFIG_TABLE", table_config)
        conn = connections.get(config_db)
        if conn is None:
            report.add_fatal(f"{config['name']} 无法检查采样配置表，配置库未连接：{config_db}")
            continue
        try:
            if not deps.table_exists_exact(conn, config_table):
                report.add_fatal(f"{config['name']} 缺少采样配置表：{config_db}.{config_table}")
                continue
            row_count = _safe_count_rows(conn, config_table, deps)
        except Exception as exc:
            report.add_fatal(f"{config['name']} 采样配置表检查失败：{config_db}.{config_table}，{exc}")
            continue
        if row_count <= 0:
            report.add_fatal(f"{config['name']} 采样配置表为空：{config_db}.{config_table}")
        else:
            report.add_info(f"{config['name']} 采样配置表可用：{config_db}.{config_table}，{row_count} 行")


def _check_group_weight_rebate_tables(report, active_modes, context, connections, deps):
    config_db = context["read_db_name"]
    conn = connections.get(config_db)
    if conn is None:
        report.add_fatal(f"group_weight 无法检查采样配置表，配置库未连接：{config_db}")
        return
    for mode in active_modes:
        mode_name = deps.get_group_weight_mode_name(mode)
        table_name = deps.get_group_weight_rebate_table_name(mode)
        try:
            if not deps.table_exists_exact(conn, table_name):
                report.add_fatal(f"{mode_name} 缺少采样配置表：{config_db}.{table_name}")
                continue
            row_count = _safe_count_rows(conn, table_name, deps)
        except Exception as exc:
            report.add_fatal(f"{mode_name} 采样配置表检查失败：{config_db}.{table_name}，{exc}")
            continue
        if row_count <= 0:
            report.add_fatal(f"{mode_name} 采样配置表为空：{config_db}.{table_name}")
        else:
            report.add_info(f"{mode_name} 采样配置表可用：{config_db}.{table_name}，{row_count} 行")


def preflight_rebate_config(report, metadata, deps):
    game_configs = deps.get_game_configs()
    modes = _normalize_modes(metadata.get("modes"), game_configs)
    if not modes:
        report.add_fatal("没有可生成采样配置的局类型")
        return
    connections = _connect_required_databases(report, _collect_table_databases(game_configs, modes), deps)
    try:
        formation_exists = deps.get_sampling_formation_exists()
        _check_source_tables(report, modes, game_configs, formation_exists, deps)
    finally:
        _close_connections(connections, deps)


def preflight_sampling(report, metadata, deps):
    game_configs = deps.get_game_configs()
    modes = _normalize_modes(metadata.get("modes"), game_configs)
    if not modes:
        report.add_fatal("没有可采样的局类型")
        return
    all_modes_requested = metadata.get("modes") in (None, "all")
    connections = _connect_required_databases(report, _collect_table_databases(game_configs, modes), deps)
    try:
        formation_exists = deps.get_sampling_formation_exists()
        existing_modes = [mode for mode in modes if formation_exists.get(mode, False)]
        _check_source_tables(
            report,
            modes,
            game_configs,
            formation_exists,
            deps,
            missing_is_warning=all_modes_requested,
        )
        if all_modes_requested and not existing_modes:
            report.add_fatal("全部采样未检测到任何可采样源表")
        _check_sampling_config_tables(report, existing_modes, game_configs, connections, deps)
    finally:
        _close_connections(connections, deps)

def preflight_group_weight(report, _metadata, deps):
    formation_exists = deps.get_group_weight_formation_exists()
    active_modes = deps.get_active_group_weight_modes(formation_exists)
    if not active_modes:
        report.add_fatal("没有检测到可生成 group_weight 的局类型")
        return
    context = deps.build_group_weight_generation_context()
    connections = _connect_required_databases(report, {context["read_db_name"], context["write_db_name"]}, deps)
    try:
        _check_group_weight_rebate_tables(report, active_modes, context, connections, deps)
        report.add_info(f"group_weight 目标表：{context['write_db_name']}.{context['table_name']}")
    finally:
        _close_connections(connections, deps)


def preflight_common_config(report, _metadata, deps):
    runtime = deps.get_runtime_state()
    connections = _connect_required_databases(report, {runtime.get("final_db"), runtime.get("config_db")}, deps)
    _close_connections(connections, deps)


def run_task_preflight(title, metadata=None, *, deps):
    """Run task-specific preflight checks and return a report."""
    metadata = dict(metadata or {})
    kind = metadata.get("kind")
    report = PreflightReport(title=title)
    runtime = deps.get_runtime_state()
    _check_selected_database_names(report, runtime, deps.get_database_configs())
    _check_config_values(report, runtime, deps)
    if report.fatal_errors:
        return report

    if kind == "rebate_config":
        preflight_rebate_config(report, metadata, deps)
    elif kind == "sampling":
        preflight_sampling(report, metadata, deps)
    elif kind == "group_weight":
        preflight_group_weight(report, metadata, deps)
    elif kind == "common_config":
        preflight_common_config(report, metadata, deps)
    else:
        report.add_info("当前任务无需额外预检查")
    return report
