"""High-level task entrypoints shared by GUI and CLI."""

from dataclasses import dataclass
from typing import Any

from formation_tool.utils import log_utils


@dataclass(frozen=True)
class AllSamplingDeps:
    get_game_configs: Any
    get_sampling_formation_exists: Any
    get_source_formation_check_error: Any
    get_table_name: Any
    run_single_game: Any
    check_cancelled: Any


@dataclass(frozen=True)
class RebateConfigGenerationDeps:
    get_game_configs: Any
    get_rebate_rules: Any
    get_sampling_formation_exists: Any
    get_source_formation_check_error: Any
    get_table_name: Any
    generate_rebate_config_for_game: Any
    check_cancelled: Any
    rebate_zero_count_limit: int
    positive_rebate_count_limit: int
    max_rebate: int
    count_limits: Any


def build_all_sampling_deps(callbacks):
    """Build deps for running sampling for all configured modes."""
    return AllSamplingDeps(
        get_game_configs=callbacks.get_game_configs,
        get_sampling_formation_exists=callbacks.get_sampling_formation_exists,
        get_source_formation_check_error=callbacks.get_source_formation_check_error,
        get_table_name=callbacks.get_table_name,
        run_single_game=callbacks.run_single_game,
        check_cancelled=callbacks.check_cancelled,
    )


def build_rebate_config_generation_deps(callbacks, limits):
    """Build deps for generating all rebate_count configs."""
    return RebateConfigGenerationDeps(
        get_game_configs=callbacks.get_game_configs,
        get_rebate_rules=callbacks.get_rebate_rules,
        get_sampling_formation_exists=callbacks.get_sampling_formation_exists,
        get_source_formation_check_error=callbacks.get_source_formation_check_error,
        get_table_name=callbacks.get_table_name,
        generate_rebate_config_for_game=callbacks.generate_rebate_config_for_game,
        check_cancelled=callbacks.check_cancelled,
        rebate_zero_count_limit=limits.rebate_zero_count_limit,
        positive_rebate_count_limit=limits.positive_rebate_count_limit,
        max_rebate=limits.max_rebate,
        count_limits=limits.count_limits,
    )


def run_all_sampling_jobs(*, deps):
    """Run sampling for every configured mode that has a source table."""
    game_configs = deps.get_game_configs()
    log_utils.print_section("全部采样模式：按顺序处理全部已配置模式")
    results = {}
    formation_exists = deps.get_sampling_formation_exists()
    for key in sorted(game_configs):
        deps.check_cancelled()
        config = game_configs[key]
        if not formation_exists.get(key, False):
            check_error = deps.get_source_formation_check_error(key)
            if check_error:
                log_utils.emit(f"\n[{config['name']}] 源表检测失败：{check_error}，跳过")
            else:
                table_name = deps.get_table_name('SOURCE_TABLE', config['table_config'])
                log_utils.emit(f"\n[{config['name']}] 未检测到源表 {table_name}，跳过")
            results[key] = None
            continue
        results[key] = deps.run_single_game(config)
    log_utils.print_result_summary(
        "全部采样完毕，汇总结果",
        results,
        name_getter=lambda key: f"{key}. {game_configs[key]['name']}",
    )
    return results


def generate_all_rebate_configs(*, deps):
    """Generate rebate sampling config rows for every available mode."""
    game_configs = deps.get_game_configs()
    rebate_rules = deps.get_rebate_rules()
    log_utils.print_section("生成采样配置（全部模式）")
    log_utils.emit(
        f"生成采样配置限制：rebate=0 最多 {deps.rebate_zero_count_limit}，"
        f"rebate>0 最多 {deps.positive_rebate_count_limit}，"
        f"rebate最高取到 {deps.max_rebate}"
    )
    results = {}
    formation_exists = deps.get_sampling_formation_exists()
    for key in sorted(game_configs):
        deps.check_cancelled()
        config = game_configs[key]
        if not formation_exists.get(key, False):
            check_error = deps.get_source_formation_check_error(key)
            if check_error:
                log_utils.emit(f"\n[{config['name']}] 源表检测失败：{check_error}，跳过")
            else:
                table_name = deps.get_table_name('SOURCE_TABLE', config['table_config'])
                log_utils.emit(f"\n[{config['name']}] 未检测到源表 {table_name}，跳过")
            results[key] = None
            continue
        if key not in rebate_rules:
            log_utils.emit(f"\n[{config['name']}] 未配置 REBATE_RULES，跳过")
            results[key] = None
            continue
        results[key] = deps.generate_rebate_config_for_game(
            key,
            config,
            rebate_rules[key],
            count_limits=deps.count_limits,
        )
    log_utils.print_result_summary(
        "配置生成完毕，汇总结果",
        results,
        name_getter=lambda key: f"{key}. {game_configs[key]['name']}",
    )
    return results
