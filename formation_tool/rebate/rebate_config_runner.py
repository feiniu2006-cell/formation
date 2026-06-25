"""Runner for generating rebate_count sampling configuration tables."""

import inspect
import time

import pandas as pd

from formation_tool.utils import log_utils

print = log_utils.emit


def is_rebate_config_detailed_log_enabled(deps):
    return bool(getattr(deps, 'detailed_log', False))


def print_rebate_config_detail(deps, message=""):
    if is_rebate_config_detailed_log_enabled(deps):
        print(message)


def _call_with_supported_kwargs(func, *args, **kwargs):
    """Call extension callbacks with only the keyword arguments they accept."""
    try:
        parameters = inspect.signature(func).parameters
    except (TypeError, ValueError):
        return func(*args)
    if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in parameters.values()):
        supported_kwargs = kwargs
    else:
        supported_kwargs = {
            key: value
            for key, value in kwargs.items()
            if key in parameters
        }
    return func(*args, **supported_kwargs)


def get_rebate_config_run_names(game_config, deps):
    """Collect table/database names used by one rebate_config generation run."""
    table_config = game_config['table_config']
    return {
        'table_config': table_config,
        'sample_conditions': game_config['sample_conditions'],
        'source_db_name': deps.get_table_database('SOURCE_TABLE', table_config),
        'config_db_name': deps.get_table_database('REBATE_CONFIG_TABLE', table_config),
        'source_table': deps.get_table_name('SOURCE_TABLE', table_config),
        'config_table': deps.get_table_name('REBATE_CONFIG_TABLE', table_config),
    }


def resolve_rebate_config_condition(names, deps):
    """Validate the source table and return the resolved WHERE condition."""
    table_config = names['table_config']
    source_db_name = names['source_db_name']
    source_table = names['source_table']
    config_db_name = names['config_db_name']
    config_table = names['config_table']

    source_conn = deps.connect_by_table('SOURCE_TABLE', table_config)
    if not source_conn:
        print(f"无法连接源库 {source_db_name}，跳过生成 {config_table}")
        return None
    try:
        if not deps.table_exists_exact(source_conn, source_table):
            print(
                f"  源表 {source_db_name}.{source_table} 不存在，"
                f"跳过生成采样配置表 {config_db_name}.{config_table}"
            )
            return None

        try:
            game_condition = deps.resolve_rebate_config_game_condition(
                source_conn,
                source_table,
                names['sample_conditions'],
            )
        except ValueError as e:
            print(f"  {e}，跳过生成 {config_table}")
            return None

        detect_end_field = getattr(deps, 'detect_end_field', None)
        end_field = detect_end_field(source_conn, source_table) if callable(detect_end_field) else None
        names['source_has_end_field'] = bool(end_field)
        names['rebate_count_expr'] = "COUNT(DISTINCT `id`)" if end_field else "COUNT(*)"
        if not end_field:
            print_rebate_config_detail(
                deps,
                f"  {source_table} 未检测到 game_end/is_end，按 id 唯一表使用 COUNT(*) 统计",
            )
        return game_condition
    finally:
        deps.close_safely(source_conn)


def build_rebate_config_stats_condition(game_condition, rules, deps, count_limits, *, direct_count_mode=False):
    """Combine game condition with SQL-side rebate filters."""
    filters = [f"({game_condition})"]
    rebate_filter = deps.build_rebate_sql_filter(
        rules,
        count_limits,
        include_rule_ranges=not direct_count_mode,
    )
    if rebate_filter:
        filters.append(f"({rebate_filter})")
    return " AND ".join(filters)


def print_rebate_config_query_header(game_config, names):
    print(f"\n{'=' * 50}")
    print(
        f"[{game_config['name']}] 统计 rebate 分布："
        f"{names['source_db_name']}.{names['source_table']} -> "
        f"{names['config_db_name']}.{names['config_table']}"
    )


def query_rebate_distribution(names, stats_condition, deps):
    """Query source formation data and return rebate distribution stats."""
    try:
        start = time.perf_counter()
        source_engine = deps.get_engine_by_table('SOURCE_TABLE', names['table_config'])
        source_ref = deps.quote_identifier(names['source_table'], "源表名")
        count_expr = names.get('rebate_count_expr') or "COUNT(DISTINCT `id`)"
        stats_df = pd.read_sql_query(
            f"SELECT `rebate`, {count_expr} AS total "
            f"FROM {source_ref} WHERE {stats_condition} GROUP BY `rebate` ORDER BY `rebate`",
            source_engine,
        )
        print_rebate_config_detail(deps, f"rebate 分布统计耗时：{time.perf_counter() - start:.2f} 秒")
        return stats_df
    except Exception as e:
        print(f"统计查询失败: {e}（配置表 {names['config_table']} 未替换）")
        return None


def build_rebate_config_rows(game_key, game_config, stats_df, rules, deps, count_limits):
    """Build normalized rebate_count rows from statistics and configured rules."""
    detail_print_fn = lambda message="": print_rebate_config_detail(deps, message)
    direct_count_mode = str(game_key) in deps.direct_count_modes
    if direct_count_mode:
        print(
            "低数据量处理：已选择不使用现有采样规则，"
            "直接将统计到的 rebate 和数量写入配置表"
        )
        result_rows = _call_with_supported_kwargs(
            deps.build_direct_rebate_config_rows,
            stats_df,
            print_fn=print,
        )
        result_rows = _call_with_supported_kwargs(
            deps.apply_direct_count_tier_limits_to_rows,
            result_rows,
            count_limits,
            game_config['name'],
            print_fn=print,
            detail_print_fn=detail_print_fn,
        )
        empty_message = "未查询到可写入的 rebate 数据；配置表未替换"
    else:
        result_rows = _call_with_supported_kwargs(
            deps.build_rule_based_rebate_config_rows,
            stats_df,
            rules,
            print_fn=print,
            detail_print_fn=detail_print_fn,
        )
        empty_message = "没有匹配规则的 rebate；配置表未替换，本次无可写入行"

    if not result_rows:
        print(empty_message)
        return None

    result_rows = _call_with_supported_kwargs(
        deps.apply_rebate_config_count_limits_to_rows,
        result_rows,
        count_limits,
        game_config['name'],
        print_fn=print,
        detail_print_fn=detail_print_fn,
    )
    try:
        return deps.normalize_rebate_config_rows(result_rows, game_config['name'])
    except ValueError as e:
        print(f"采样配置校验失败: {e}")
        return None


def build_rebate_config_rows_preview(result_rows, *, limit=8):
    """Return a compact preview of generated rebate_count rows."""
    rows = list(result_rows or [])
    if not rows:
        return "无可写入采样配置"
    total_count = sum(int(count) for _rebate, count in rows)
    max_rebate = max(int(rebate) for rebate, _count in rows)
    zero_rows = sum(1 for rebate, _count in rows if int(rebate) == 0)
    positive_rows = len(rows) - zero_rows
    preview = ", ".join(
        f"{int(rebate)}:{int(count)}"
        for rebate, count in rows[:limit]
    )
    if len(rows) > limit:
        preview += ", ..."
    return (
        f"行数={len(rows)}，count合计={total_count}，"
        f"rebate=0行={zero_rows}，rebate>0行={positive_rows}，"
        f"最大rebate={max_rebate}，前{min(len(rows), limit)}项={preview}"
    )


def print_rebate_config_write_preview(names, result_rows):
    """Print write preview before replacing the rebate_count table."""
    target = f"{names['config_db_name']}.{names['config_table']}"
    print(f"\n采样配置写入预览：{target}")
    print(build_rebate_config_rows_preview(result_rows))


def write_rebate_config_rows_if_ready(names, result_rows, deps):
    """Write generated rebate_count rows to the configured table."""
    if not result_rows:
        return False
    print_rebate_config_write_preview(names, result_rows)
    print_rebate_config_detail(
        deps,
        f"\n共 {len(result_rows)} 条配置准备写入 {names['config_db_name']}.{names['config_table']}",
    )
    return deps.write_rebate_config_rows(
        names['table_config'],
        names['config_table'],
        names['config_db_name'],
        result_rows,
    )


def generate_rebate_config_for_game(game_key, game_config, rules, *, deps, count_limits=None):
    """统计源表 rebate 分布，按规则写入采样配置表。"""
    total_start = time.perf_counter()
    deps.check_cancelled()
    names = get_rebate_config_run_names(game_config, deps)
    start = time.perf_counter()
    game_condition = resolve_rebate_config_condition(names, deps)
    print_rebate_config_detail(deps, f"源表与条件解析耗时：{time.perf_counter() - start:.2f} 秒")
    if game_condition is None:
        return False

    direct_count_mode = str(game_key) in deps.direct_count_modes
    stats_condition = build_rebate_config_stats_condition(
        game_condition,
        rules,
        deps,
        count_limits,
        direct_count_mode=direct_count_mode,
    )

    print_rebate_config_query_header(game_config, names)
    stats_df = query_rebate_distribution(names, stats_condition, deps)
    if stats_df is None:
        return False
    if stats_df.empty:
        print("未查询到任何 rebate 数据；配置表未替换")
        return False

    source_total = int(stats_df['total'].sum())
    print_rebate_config_detail(deps, f"\n过滤条件: {stats_condition}")
    print(f"匹配数据量: {source_total}")

    start = time.perf_counter()
    result_rows = build_rebate_config_rows(
        game_key,
        game_config,
        stats_df,
        rules,
        deps,
        count_limits,
    )
    print_rebate_config_detail(deps, f"采样配置行构建耗时：{time.perf_counter() - start:.2f} 秒")

    start = time.perf_counter()
    result = write_rebate_config_rows_if_ready(names, result_rows, deps)
    print_rebate_config_detail(deps, f"采样配置写入耗时：{time.perf_counter() - start:.2f} 秒")
    print_rebate_config_detail(deps, f"{game_config['name']} 采样配置总耗时：{time.perf_counter() - total_start:.2f} 秒")
    return result
