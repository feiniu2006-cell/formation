"""Dependency factories for high-level sampling/config tasks."""

from types import SimpleNamespace

from formation_tool.core import task_entrypoints
from formation_tool.core import task_preflight


def build_all_sampling_jobs_deps(module):
    """Build deps for running all sampling jobs from the main module namespace."""
    return task_entrypoints.build_all_sampling_deps(
        SimpleNamespace(
            get_game_configs=module.get_runtime_game_configs,
            get_sampling_formation_exists=module.get_sampling_formation_exists,
            get_source_formation_check_error=module.get_source_formation_check_error,
            get_table_name=module.get_table_name,
            run_single_game=module.run_single_game,
            check_cancelled=module.check_cancelled,
        )
    )


def build_rebate_config_generation_deps(module):
    """Build deps for generating rebate_count configs from the main module namespace."""
    return task_entrypoints.build_rebate_config_generation_deps(
        SimpleNamespace(
            get_game_configs=module.get_runtime_game_configs,
            get_rebate_rules=module.get_runtime_rebate_rules,
            get_sampling_formation_exists=module.get_sampling_formation_exists,
            get_source_formation_check_error=module.get_source_formation_check_error,
            get_table_name=module.get_table_name,
            generate_rebate_config_for_game=module.generate_rebate_config_for_game,
            check_cancelled=module.check_cancelled,
        ),
        SimpleNamespace(
            rebate_zero_count_limit=module.REBATE_CONFIG_REBATE_ZERO_COUNT_LIMIT,
            positive_rebate_count_limit=module.REBATE_CONFIG_POSITIVE_REBATE_COUNT_LIMIT,
            max_rebate=module.REBATE_CONFIG_MAX_REBATE,
            count_limits=module.REBATE_CONFIG_COUNT_LIMITS,
        ),
    )


def build_task_preflight_deps(module):
    """Build deps consumed by task_preflight from the main module namespace."""
    runtime_state = module.RUNTIME_STATE
    return SimpleNamespace(
        get_runtime_state=runtime_state.runtime_dict,
        get_database_configs=lambda: runtime_state.database_configs,
        get_trigger_weights=runtime_state.trigger_weights_dict,
        get_rebate_rules=module.get_runtime_rebate_rules,
        get_rebate_config_index_warnings=module.get_rebate_config_index_warnings,
        validate_rebate_rules=module.validate_runtime_rebate_rules,
        get_group_weight_rules=lambda: runtime_state.group_weight_rules,
        validate_group_weight_rules=module.validate_group_weight_rules,
        get_buy_groups=lambda: runtime_state.buy_groups,
        get_ex_buy_group_enabled=lambda: runtime_state.ex_buy_group_enabled,
        get_ex_buy_group_game_type=lambda: runtime_state.ex_buy_group_game_type,
        get_ex_buy_group_source_suffix=lambda: runtime_state.ex_buy_group_source_suffix,
        get_ex_group_multiplier=lambda: runtime_state.ex_group_multiplier,
        get_special_group_target_rtp=lambda: runtime_state.special_group_target_rtp,
        get_game_configs=module.get_runtime_game_configs,
        get_sampling_formation_exists=module.get_sampling_formation_exists,
        get_source_formation_check_error=module.get_source_formation_check_error,
        get_table_database=module.get_table_database,
        get_table_name=module.get_table_name,
        get_sampling_append_mode=lambda: module.RUNTIME_STATE.sampling_append_mode,
        get_sampling_use_temp_db=lambda: True,
        get_sampling_temp_db=lambda: module.RUNTIME_STATE.sampling_temp_db,
        get_sampling_auto_sync_to_target=lambda: module.RUNTIME_STATE.sampling_auto_sync_to_target,
        get_group_weight_formation_exists=module.get_group_weight_formation_exists,
        get_active_group_weight_modes=module.get_active_group_weight_modes,
        build_group_weight_generation_context=module.build_group_weight_generation_context,
        get_group_weight_rebate_table_name=module.get_group_weight_rebate_table_name,
        get_group_weight_mode_name=module.get_group_weight_mode_name,
        connect_to_database=module.connect_to_database,
        quote_identifier=module.quote_identifier,
        table_exists_exact=module.table_exists_exact,
        count_table_rows=module.count_table_rows,
        close_safely=module.close_safely,
    )


def run_task_preflight(title, metadata, module):
    """Run task preflight with deps built from the main module namespace."""
    return task_preflight.run_task_preflight(
        title,
        metadata,
        deps=build_task_preflight_deps(module),
    )
