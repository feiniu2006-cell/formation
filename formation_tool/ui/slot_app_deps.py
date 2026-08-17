"""Dependency builders shared by SlotProcessApp mixins."""
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class UiDeps:
    database_configs: Any
    vendor_type_map: Any
    random_seed: Any
    run_all_sampling_jobs: Any
    run_all_supplemental_sampling_jobs: Any
    mirror_sampling_temp_to_target: Any
    write_common_configs: Any
    test_selected_database_connections: Any
    normalize_extra_buy_groups: Any
    get_extra_buy_groups: Any
    get_external_config_source: Any
    get_external_config_load_error: Any


@dataclass(frozen=True)
class SettingsDeps:
    default_trigger_weights: Any
    default_sampling_append_mode: Any
    default_sampling_detailed_log: Any
    default_sampling_use_temp_db: Any
    default_sampling_temp_db: Any
    default_sampling_increment_db: Any
    default_sampling_auto_sync_to_target: Any
    default_buy_group_enabled: Any
    default_ex_buy_group_enabled: Any
    default_ex_buy_group_game_type: Any
    default_ex_buy_group_source_suffix: Any
    default_buy_group_game_type: Any
    default_buy_group_multiplier: Any
    default_buy_group_source_suffix: Any
    default_ex_group_multiplier: Any
    default_extra_buy_groups: Any
    default_extra_weight_groups: Any
    default_rebate_rules: Any
    default_direct_count_tiers: Any
    default_group_weight_rules: Any
    default_group_weight_group_rules: Any
    default_special_group_target_rtp: Any
    default_ex_group_target_rtps: Any
    default_zero_rebate_inference_modes: Any
    default_independent_rtp_modes: Any
    get_runtime_state: Any
    get_trigger_weights: Any
    get_rebate_rules: Any
    get_sampling_append_mode: Any
    get_sampling_detailed_log: Any
    get_sampling_use_temp_db: Any
    get_sampling_temp_db: Any
    get_sampling_increment_db: Any
    get_sampling_auto_sync_to_target: Any
    get_group_weight_rules: Any
    get_group_weight_group_rules: Any
    get_group_weight_formation_exists: Any
    get_displayed_group_weight_modes: Any
    get_special_group_target_rtp: Any
    get_ex_group_target_rtps: Any
    get_zero_rebate_inference_modes: Any
    get_independent_rtp_modes: Any
    get_buy_group_enabled: Any
    get_ex_buy_group_enabled: Any
    get_ex_buy_group_game_type: Any
    get_ex_buy_group_source_suffix: Any
    get_buy_group_game_type: Any
    get_buy_group_multiplier: Any
    get_buy_group_source_suffix: Any
    get_buy_groups: Any
    get_ex_group_multiplier: Any
    get_ex_source_suffixes: Any
    get_extra_buy_groups: Any
    get_extra_weight_groups: Any
    get_direct_count_modes: Any
    get_direct_count_tiers: Any
    get_app_settings_path: Any
    get_app_profile_settings_path: Any
    get_profile_key: Any
    get_ready_status_text: Any
    clone_rebate_rules: Any
    clone_group_weight_rules: Any
    clone_group_weight_group_rules: Any
    clone_extra_buy_groups: Any
    clone_extra_weight_groups: Any
    clear_config_warnings: Any
    consume_config_warnings: Any
    normalize_rebate_rules_for_load: Any
    normalize_direct_count_tiers_for_load: Any
    normalize_group_weight_rules_for_load: Any
    normalize_group_weight_group_rules_for_load: Any
    normalize_extra_weight_groups: Any
    apply_runtime_config: Any
    apply_weight_config: Any
    apply_rebate_rules_config: Any
    apply_group_weight_rules_config: Any
    apply_group_weight_group_rules_config: Any
    apply_special_group_target_rtp: Any
    apply_ex_group_target_rtps_config: Any
    apply_zero_rebate_inference_modes_config: Any
    apply_independent_rtp_modes_config: Any
    apply_buy_group_multiplier: Any
    apply_buy_group_game_type: Any
    apply_buy_group_source_suffix: Any
    apply_buy_groups_config: Any
    apply_buy_group_enabled: Any
    apply_ex_buy_group_enabled: Any
    apply_ex_buy_group_game_type: Any
    apply_ex_buy_group_source_suffix: Any
    apply_ex_group_multiplier: Any
    apply_ex_source_suffixes_config: Any
    apply_extra_buy_groups_config: Any
    apply_extra_weight_groups_config: Any
    load_buy_group_options_from_game_type_config: Any
    apply_rebate_config_direct_count_modes: Any
    apply_rebate_config_direct_count_tiers: Any
    apply_sampling_append_mode: Any
    apply_sampling_detailed_log: Any
    apply_sampling_temp_db_config: Any
    apply_sampling_increment_db_config: Any
    apply_sampling_auto_sync_to_target: Any


@dataclass(frozen=True)
class TaskDeps:
    get_runtime_state: Any
    get_external_config_source: Any
    get_external_config_load_error: Any
    get_trigger_weights: Any
    get_rebate_rules: Any
    get_sampling_append_mode: Any
    get_sampling_detailed_log: Any
    get_sampling_use_temp_db: Any
    get_sampling_temp_db: Any
    get_sampling_increment_db: Any
    get_sampling_auto_sync_to_target: Any
    get_direct_count_modes: Any
    get_direct_count_tiers: Any
    get_game_configs: Any
    ex_purchase_mode: Any
    buy_group_mode: Any
    get_group_weight_rules: Any
    get_group_weight_group_rules: Any
    get_special_group_target_rtp: Any
    get_ex_group_target_rtps: Any
    get_buy_group_enabled: Any
    get_buy_group_game_type: Any
    get_buy_group_multiplier: Any
    get_buy_group_source_suffix: Any
    get_extra_buy_groups: Any
    get_ex_group_multiplier: Any
    get_ex_source_suffixes: Any
    get_ex_buy_group_enabled: Any
    get_ex_buy_group_game_type: Any
    get_ex_buy_group_source_suffix: Any
    format_weighted_rtp: Any
    clear_cancel_request: Any
    request_cancel: Any
    task_cancelled_cls: Any
    run_task_preflight: Any
    mirror_sampling_temp_to_target: Any
    sync_sampling_temp_results: Any
    run_all_supplemental_sampling_jobs: Any
    run_single_supplemental_game_job: Any


@dataclass(frozen=True)
class GroupWeightDialogDeps:
    weight_group_ids: Any
    group_weight_modes: Any
    group_weight_ui_modes: Any
    ex_group_modes: Any
    ex_independent_group_weight_modes: Any
    ex_purchase_mode: Any
    buy_group_mode: Any
    game_type_names: Any
    rule_fields: Any
    rule_field_labels: Any
    rules: Any
    group_rules: Any
    default_rules: Any
    default_group_rules: Any
    special_target_rtp: Any
    default_special_target_rtp: Any
    ex_group_target_rtps: Any
    default_ex_group_target_rtps: Any
    zero_rebate_inference_modes: Any
    default_zero_rebate_inference_modes: Any
    independent_rtp_modes: Any
    default_independent_rtp_modes: Any
    buy_enabled: Any
    buy_game_type: Any
    buy_multiplier: Any
    buy_source_suffix: Any
    ex_multiplier: Any
    extra_buy_groups: Any
    get_formation_exists: Any
    load_preview_rebates: Any
    get_displayed_modes: Any
    collect_preview_warnings: Any
    get_mode_name: Any
    supports_zero_rebate_inference: Any
    supports_independent_rtp: Any
    is_extra_buy_mode: Any
    get_extra_buy_group_by_mode: Any
    get_buy_group_game_type_for_mode: Any
    get_group_weight_write_game_type: Any
    get_buy_group_source_suffix_for_mode: Any
    get_extra_buy_game_type: Any
    make_extra_buy_mode: Any
    has_extra_buy_groups: Any
    format_group_rtp_option: Any
    get_group_target_rtp_value: Any
    format_weighted_rtp: Any
    parse_non_negative_int_text: Any
    parse_positive_float_text: Any
    build_preview_text: Any
    build_preview_points: Any
    validate_rules: Any
    normalize_extra_buy_groups: Any
    apply_special_target: Any
    apply_ex_group_target_rtps: Any
    apply_zero_rebate_inference_modes: Any
    apply_independent_rtp_modes: Any
    apply_rules: Any
    apply_group_rules: Any
    apply_extra_buy_groups: Any
    generate_config: Any


@dataclass(frozen=True)
class ProcessAppDeps:
    ctx: Any

    def __getattr__(self, name):
        return getattr(self.ctx, name)

    def build_deps_context(self):
        return self.ctx

    def build_ui_deps(self, context):
        return build_ui_deps(context)

    def build_settings_deps(self, context):
        return build_settings_deps(context)

    def build_task_deps(self, context):
        return build_task_deps(context)

    def build_group_weight_dialog_deps(self):
        return build_group_weight_dialog_deps(self.ctx)

    def get_ready_status_text(self):
        return build_ready_status_text(self.ctx.get_runtime_state())


def build_runtime_state(vendor, game_id, source_db, final_db, config_db):
    """Return the current room/database selection in the settings file shape."""
    return {
        'vendor': vendor,
        'game_id': game_id,
        'source_db': source_db,
        'final_db': final_db,
        'config_db': config_db,
    }


def build_trigger_weights(special_weights, free_weights):
    """Return trigger weights in the settings file shape."""
    return {
        'special_0': special_weights[0],
        'special_1': special_weights[1],
        'special_2': special_weights[2],
        'special_3': special_weights[3],
        'free_0': free_weights[0],
        'free_1': free_weights[1],
        'free_2': free_weights[2],
        'free_3': free_weights[3],
    }


def build_ready_status_text(runtime):
    staging = ""
    if runtime.get("sampling_use_temp_db"):
        staging = f"，采样临时库 {runtime.get('sampling_temp_db')}"
    return (
        f"就绪：{runtime['vendor']}_{runtime['game_id']}  "
        f"{runtime['source_db']} -> {runtime['final_db']}，配置库 {runtime['config_db']}{staging}"
    )


def build_ui_deps(ctx):
    return UiDeps(
        database_configs=ctx.database_configs,
        vendor_type_map=ctx.vendor_type_map,
        random_seed=ctx.random_seed,
        run_all_sampling_jobs=ctx.run_all_sampling_jobs,
        run_all_supplemental_sampling_jobs=ctx.run_all_supplemental_sampling_jobs,
        mirror_sampling_temp_to_target=ctx.mirror_sampling_temp_to_target,
        write_common_configs=ctx.write_common_configs,
        test_selected_database_connections=ctx.test_selected_database_connections,
        normalize_extra_buy_groups=ctx.normalize_extra_buy_groups,
        get_extra_buy_groups=ctx.get_extra_buy_groups,
        get_external_config_source=ctx.get_external_config_source,
        get_external_config_load_error=ctx.get_external_config_load_error,
    )


def build_settings_deps(ctx):
    return SettingsDeps(
        default_trigger_weights=ctx.default_trigger_weights,
        default_sampling_append_mode=ctx.default_sampling_append_mode,
        default_sampling_detailed_log=ctx.default_sampling_detailed_log,
        default_sampling_use_temp_db=ctx.default_sampling_use_temp_db,
        default_sampling_temp_db=ctx.default_sampling_temp_db,
        default_sampling_increment_db=ctx.default_sampling_increment_db,
        default_sampling_auto_sync_to_target=ctx.default_sampling_auto_sync_to_target,
        default_buy_group_enabled=ctx.default_buy_group_enabled,
        default_ex_buy_group_enabled=ctx.default_ex_buy_group_enabled,
        default_ex_buy_group_game_type=ctx.default_ex_buy_group_game_type,
        default_ex_buy_group_source_suffix=ctx.default_ex_buy_group_source_suffix,
        default_buy_group_game_type=ctx.default_buy_group_game_type,
        default_buy_group_multiplier=ctx.default_buy_group_multiplier,
        default_buy_group_source_suffix=ctx.default_buy_group_source_suffix,
        default_ex_group_multiplier=ctx.default_ex_group_multiplier,
        default_extra_buy_groups=ctx.default_extra_buy_groups,
        default_extra_weight_groups=ctx.default_extra_weight_groups,
        default_rebate_rules=ctx.default_rebate_rules,
        default_direct_count_tiers=ctx.default_direct_count_tiers,
        default_group_weight_rules=ctx.default_group_weight_rules,
        default_group_weight_group_rules=getattr(ctx, 'default_group_weight_group_rules', {}),
        default_special_group_target_rtp=ctx.default_special_group_target_rtp,
        default_ex_group_target_rtps=ctx.default_ex_group_target_rtps,
        default_zero_rebate_inference_modes=ctx.default_zero_rebate_inference_modes,
        default_independent_rtp_modes=ctx.default_independent_rtp_modes,
        get_runtime_state=ctx.get_runtime_state,
        get_trigger_weights=ctx.get_trigger_weights,
        get_rebate_rules=ctx.get_rebate_rules,
        get_sampling_append_mode=ctx.get_sampling_append_mode,
        get_sampling_detailed_log=ctx.get_sampling_detailed_log,
        get_sampling_use_temp_db=ctx.get_sampling_use_temp_db,
        get_sampling_temp_db=ctx.get_sampling_temp_db,
        get_sampling_increment_db=ctx.get_sampling_increment_db,
        get_sampling_auto_sync_to_target=ctx.get_sampling_auto_sync_to_target,
        get_group_weight_rules=ctx.get_group_weight_rules,
        get_group_weight_group_rules=getattr(ctx, 'get_group_weight_group_rules', lambda: {}),
        get_group_weight_formation_exists=ctx.get_group_weight_formation_exists,
        get_displayed_group_weight_modes=ctx.get_displayed_group_weight_modes,
        get_special_group_target_rtp=ctx.get_special_group_target_rtp,
        get_ex_group_target_rtps=ctx.get_ex_group_target_rtps,
        get_zero_rebate_inference_modes=ctx.get_zero_rebate_inference_modes,
        get_independent_rtp_modes=ctx.get_independent_rtp_modes,
        get_buy_group_enabled=ctx.get_buy_group_enabled,
        get_ex_buy_group_enabled=ctx.get_ex_buy_group_enabled,
        get_ex_buy_group_game_type=ctx.get_ex_buy_group_game_type,
        get_ex_buy_group_source_suffix=ctx.get_ex_buy_group_source_suffix,
        get_buy_group_game_type=ctx.get_buy_group_game_type,
        get_buy_group_multiplier=ctx.get_buy_group_multiplier,
        get_buy_group_source_suffix=ctx.get_buy_group_source_suffix,
        get_buy_groups=ctx.get_buy_groups,
        get_ex_group_multiplier=ctx.get_ex_group_multiplier,
        get_ex_source_suffixes=ctx.get_ex_source_suffixes,
        get_extra_buy_groups=ctx.get_extra_buy_groups,
        get_extra_weight_groups=ctx.get_extra_weight_groups,
        get_direct_count_modes=ctx.get_direct_count_modes,
        get_direct_count_tiers=ctx.get_direct_count_tiers,
        get_app_settings_path=ctx.get_app_settings_path,
        get_app_profile_settings_path=ctx.get_app_profile_settings_path,
        get_profile_key=lambda: (
            ctx.get_runtime_state()['vendor'],
            ctx.get_runtime_state()['game_id'],
        ),
        get_ready_status_text=lambda: build_ready_status_text(ctx.get_runtime_state()),
        clone_rebate_rules=ctx.clone_rebate_rules,
        clone_group_weight_rules=ctx.clone_group_weight_rules,
        clone_group_weight_group_rules=getattr(
            ctx,
            'clone_group_weight_group_rules',
            lambda rules: {
                str(group): {
                    str(mode): [dict(rule) for rule in mode_rules]
                    for mode, mode_rules in rules_by_mode.items()
                }
                for group, rules_by_mode in (rules or {}).items()
                if isinstance(rules_by_mode, dict)
            },
        ),
        clone_extra_buy_groups=ctx.clone_extra_buy_groups,
        clone_extra_weight_groups=ctx.clone_extra_weight_groups,
        clear_config_warnings=ctx.clear_config_warnings,
        consume_config_warnings=ctx.consume_config_warnings,
        normalize_rebate_rules_for_load=ctx.normalize_rebate_rules_for_load,
        normalize_direct_count_tiers_for_load=ctx.normalize_direct_count_tiers_for_load,
        normalize_group_weight_rules_for_load=ctx.normalize_group_weight_rules_for_load,
        normalize_group_weight_group_rules_for_load=getattr(
            ctx,
            'normalize_group_weight_group_rules_for_load',
            lambda rules: rules or {},
        ),
        normalize_extra_weight_groups=ctx.normalize_extra_weight_groups,
        apply_runtime_config=ctx.apply_runtime_config,
        apply_weight_config=ctx.apply_weight_config,
        apply_rebate_rules_config=ctx.apply_rebate_rules_config,
        apply_group_weight_rules_config=ctx.apply_group_weight_rules_config,
        apply_group_weight_group_rules_config=getattr(
            ctx,
            'apply_group_weight_group_rules_config',
            lambda _rules: None,
        ),
        apply_special_group_target_rtp=ctx.apply_special_group_target_rtp,
        apply_ex_group_target_rtps_config=ctx.apply_ex_group_target_rtps_config,
        apply_zero_rebate_inference_modes_config=ctx.apply_zero_rebate_inference_modes_config,
        apply_independent_rtp_modes_config=ctx.apply_independent_rtp_modes_config,
        apply_buy_group_multiplier=ctx.apply_buy_group_multiplier,
        apply_buy_group_game_type=ctx.apply_buy_group_game_type,
        apply_buy_group_source_suffix=ctx.apply_buy_group_source_suffix,
        apply_buy_groups_config=ctx.apply_buy_groups_config,
        apply_buy_group_enabled=ctx.apply_buy_group_enabled,
        apply_ex_buy_group_enabled=ctx.apply_ex_buy_group_enabled,
        apply_ex_buy_group_game_type=ctx.apply_ex_buy_group_game_type,
        apply_ex_buy_group_source_suffix=ctx.apply_ex_buy_group_source_suffix,
        apply_ex_group_multiplier=ctx.apply_ex_group_multiplier,
        apply_ex_source_suffixes_config=ctx.apply_ex_source_suffixes_config,
        apply_extra_buy_groups_config=ctx.apply_extra_buy_groups_config,
        apply_extra_weight_groups_config=ctx.apply_extra_weight_groups_config,
        load_buy_group_options_from_game_type_config=ctx.load_buy_group_options_from_game_type_config,
        apply_rebate_config_direct_count_modes=ctx.apply_rebate_config_direct_count_modes,
        apply_rebate_config_direct_count_tiers=ctx.apply_rebate_config_direct_count_tiers,
        apply_sampling_append_mode=ctx.apply_sampling_append_mode,
        apply_sampling_detailed_log=ctx.apply_sampling_detailed_log,
        apply_sampling_temp_db_config=ctx.apply_sampling_temp_db_config,
        apply_sampling_increment_db_config=ctx.apply_sampling_increment_db_config,
        apply_sampling_auto_sync_to_target=ctx.apply_sampling_auto_sync_to_target,
    )


def build_task_deps(ctx):
    return TaskDeps(
        get_runtime_state=ctx.get_runtime_state,
        get_external_config_source=ctx.get_external_config_source,
        get_external_config_load_error=ctx.get_external_config_load_error,
        get_trigger_weights=ctx.get_trigger_weights,
        get_rebate_rules=ctx.get_rebate_rules,
        get_sampling_append_mode=ctx.get_sampling_append_mode,
        get_sampling_detailed_log=ctx.get_sampling_detailed_log,
        get_sampling_use_temp_db=ctx.get_sampling_use_temp_db,
        get_sampling_temp_db=ctx.get_sampling_temp_db,
        get_sampling_increment_db=ctx.get_sampling_increment_db,
        get_sampling_auto_sync_to_target=ctx.get_sampling_auto_sync_to_target,
        get_direct_count_modes=ctx.get_direct_count_modes,
        get_direct_count_tiers=ctx.get_direct_count_tiers,
        get_game_configs=ctx.get_game_configs,
        ex_purchase_mode=ctx.ex_purchase_mode,
        buy_group_mode=ctx.buy_group_mode,
        get_group_weight_rules=ctx.get_group_weight_rules,
        get_group_weight_group_rules=getattr(ctx, 'get_group_weight_group_rules', lambda: {}),
        get_special_group_target_rtp=ctx.get_special_group_target_rtp,
        get_ex_group_target_rtps=ctx.get_ex_group_target_rtps,
        get_buy_group_enabled=ctx.get_buy_group_enabled,
        get_buy_group_game_type=ctx.get_buy_group_game_type,
        get_buy_group_multiplier=ctx.get_buy_group_multiplier,
        get_buy_group_source_suffix=ctx.get_buy_group_source_suffix,
        get_extra_buy_groups=ctx.get_extra_buy_groups,
        get_ex_group_multiplier=ctx.get_ex_group_multiplier,
        get_ex_source_suffixes=ctx.get_ex_source_suffixes,
        get_ex_buy_group_enabled=ctx.get_ex_buy_group_enabled,
        get_ex_buy_group_game_type=ctx.get_ex_buy_group_game_type,
        get_ex_buy_group_source_suffix=ctx.get_ex_buy_group_source_suffix,
        format_weighted_rtp=ctx.format_weighted_rtp,
        clear_cancel_request=ctx.clear_cancel_request,
        request_cancel=ctx.request_cancel,
        task_cancelled_cls=ctx.task_cancelled_cls,
        run_task_preflight=ctx.run_task_preflight,
        mirror_sampling_temp_to_target=ctx.mirror_sampling_temp_to_target,
        sync_sampling_temp_results=ctx.sync_sampling_temp_results,
        run_all_supplemental_sampling_jobs=ctx.run_all_supplemental_sampling_jobs,
        run_single_supplemental_game_job=ctx.run_single_supplemental_game_job,
    )


def build_group_weight_dialog_deps(ctx):
    """Return dependencies consumed by GroupWeightRulesDialog."""
    extra_buy_groups = ctx.clone_extra_buy_groups(ctx.get_extra_buy_groups())
    for group in extra_buy_groups:
        group['source_suffix'] = ctx.get_buy_group_source_suffix_for_mode(
            ctx.make_extra_buy_mode(group['game_type'])
        )
    return GroupWeightDialogDeps(
        weight_group_ids=getattr(ctx, 'get_weight_group_ids', lambda: ctx.weight_group_ids)(),
        group_weight_modes=ctx.group_weight_modes,
        group_weight_ui_modes=ctx.group_weight_ui_modes,
        ex_group_modes=ctx.ex_group_modes,
        ex_independent_group_weight_modes=ctx.ex_independent_group_weight_modes,
        ex_purchase_mode=ctx.ex_purchase_mode,
        buy_group_mode=ctx.buy_group_mode,
        game_type_names=ctx.game_type_names,
        rule_fields=ctx.group_weight_rule_fields,
        rule_field_labels=ctx.group_weight_rule_field_labels,
        rules=ctx.clone_group_weight_rules(ctx.get_group_weight_rules()),
        group_rules=getattr(ctx, 'clone_group_weight_group_rules', lambda rules: rules or {})(
            getattr(ctx, 'get_group_weight_group_rules', lambda: {})()
        ),
        default_rules=ctx.clone_group_weight_rules(ctx.default_group_weight_rules),
        default_group_rules=getattr(ctx, 'clone_group_weight_group_rules', lambda rules: rules or {})(
            getattr(ctx, 'default_group_weight_group_rules', {})
        ),
        special_target_rtp=ctx.get_special_group_target_rtp(),
        default_special_target_rtp=getattr(
            ctx,
            'default_special_group_target_rtp',
            ctx.get_special_group_target_rtp(),
        ),
        ex_group_target_rtps=getattr(ctx, 'get_ex_group_target_rtps', lambda: {})(),
        default_ex_group_target_rtps=getattr(ctx, 'default_ex_group_target_rtps', {}),
        zero_rebate_inference_modes=getattr(ctx, 'get_zero_rebate_inference_modes', lambda: set())(),
        default_zero_rebate_inference_modes=getattr(ctx, 'default_zero_rebate_inference_modes', set()),
        independent_rtp_modes=getattr(ctx, 'get_independent_rtp_modes', lambda: set())(),
        default_independent_rtp_modes=getattr(ctx, 'default_independent_rtp_modes', set()),
        buy_enabled=ctx.get_buy_group_enabled(),
        buy_game_type=ctx.get_buy_group_game_type(),
        buy_multiplier=ctx.get_buy_group_multiplier(),
        buy_source_suffix=ctx.get_buy_group_source_suffix_for_mode(ctx.buy_group_mode),
        ex_multiplier=ctx.get_ex_group_multiplier(),
        extra_buy_groups=extra_buy_groups,
        get_formation_exists=ctx.get_group_weight_formation_exists,
        load_preview_rebates=ctx.load_group_weight_preview_rebates,
        get_displayed_modes=ctx.get_displayed_group_weight_modes,
        collect_preview_warnings=ctx.collect_group_weight_preview_warnings,
        get_mode_name=ctx.get_group_weight_mode_name,
        supports_zero_rebate_inference=getattr(ctx, 'supports_zero_rebate_inference', lambda _mode: False),
        supports_independent_rtp=getattr(ctx, 'supports_independent_rtp', lambda _mode: False),
        is_extra_buy_mode=ctx.is_extra_buy_mode,
        get_extra_buy_group_by_mode=ctx.get_extra_buy_group_by_mode,
        get_buy_group_game_type_for_mode=ctx.get_buy_group_game_type_for_mode,
        get_group_weight_write_game_type=ctx.get_group_weight_write_game_type,
        get_buy_group_source_suffix_for_mode=ctx.get_buy_group_source_suffix_for_mode,
        get_extra_buy_game_type=ctx.get_extra_buy_game_type,
        make_extra_buy_mode=ctx.make_extra_buy_mode,
        has_extra_buy_groups=ctx.has_extra_buy_groups,
        format_group_rtp_option=ctx.format_group_rtp_option,
        get_group_target_rtp_value=ctx.get_group_target_rtp_value,
        format_weighted_rtp=ctx.format_weighted_rtp,
        parse_non_negative_int_text=ctx.parse_non_negative_int_text,
        parse_positive_float_text=ctx.parse_positive_float_text,
        build_preview_text=ctx.build_group_weight_preview_text,
        build_preview_points=ctx.build_group_weight_preview_points,
        validate_rules=ctx.validate_group_weight_rules,
        normalize_extra_buy_groups=ctx.normalize_extra_buy_groups,
        apply_special_target=ctx.apply_special_group_target_rtp,
        apply_ex_group_target_rtps=getattr(ctx, 'apply_ex_group_target_rtps_config', lambda _targets: None),
        apply_zero_rebate_inference_modes=getattr(
            ctx,
            'apply_zero_rebate_inference_modes_config',
            lambda _modes: None,
        ),
        apply_independent_rtp_modes=getattr(
            ctx,
            'apply_independent_rtp_modes_config',
            lambda _modes: None,
        ),
        apply_rules=ctx.apply_group_weight_rules_config,
        apply_group_rules=getattr(ctx, 'apply_group_weight_group_rules_config', lambda _rules: None),
        apply_extra_buy_groups=ctx.apply_extra_buy_groups_config,
        generate_config=ctx.generate_group_weight_config,
    )


def build_process_app_deps(ctx):
    """Return the dependency facade consumed by SlotProcessApp."""
    return ProcessAppDeps(ctx)
