"""Build the typed dependency context consumed by SlotProcessApp."""

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any


@dataclass
class SlotAppDepsContext:
    database_configs: Any
    vendor_type_map: Any
    random_seed: Any
    run_all_sampling_jobs: Any
    write_common_configs: Any
    test_selected_database_connections: Any
    normalize_extra_buy_groups: Any
    default_trigger_weights: Any
    default_sampling_append_mode: Any
    default_buy_group_enabled: Any
    default_ex_buy_group_enabled: Any
    default_buy_group_game_type: Any
    default_buy_group_multiplier: Any
    default_buy_group_source_suffix: Any
    default_ex_group_multiplier: Any
    default_extra_buy_groups: Any
    default_rebate_rules: Any
    default_direct_count_tiers: Any
    default_group_weight_rules: Any
    default_special_group_target_rtp: Any
    default_ex_group_target_rtps: Any
    get_runtime_state: Any
    get_trigger_weights: Any
    get_rebate_rules: Any
    get_sampling_append_mode: Any
    get_group_weight_rules: Any
    get_special_group_target_rtp: Any
    get_ex_group_target_rtps: Any
    get_buy_group_enabled: Any
    get_ex_buy_group_enabled: Any
    get_buy_group_game_type: Any
    get_buy_group_multiplier: Any
    get_buy_group_source_suffix: Any
    get_buy_groups: Any
    get_ex_group_multiplier: Any
    get_ex_source_suffixes: Any
    get_extra_buy_groups: Any
    get_direct_count_modes: Any
    get_direct_count_tiers: Any
    get_app_settings_path: Any
    get_app_profile_settings_path: Any
    get_external_config_source: Any
    get_external_config_load_error: Any
    get_game_configs: Any
    get_sample_game_type_names: Any
    get_sampling_rebate_rules: Any
    get_default_sampling_rebate_rules: Any
    clone_sampling_rebate_rules: Any
    validate_sampling_rebate_rules: Any
    clone_rebate_rules: Any
    clone_group_weight_rules: Any
    clone_extra_buy_groups: Any
    clear_config_warnings: Any
    consume_config_warnings: Any
    normalize_rebate_rules_for_load: Any
    normalize_group_weight_rules_for_load: Any
    apply_runtime_config: Any
    apply_weight_config: Any
    apply_rebate_rules_config: Any
    apply_group_weight_rules_config: Any
    apply_special_group_target_rtp: Any
    apply_ex_group_target_rtps_config: Any
    apply_buy_group_multiplier: Any
    apply_buy_group_game_type: Any
    apply_buy_group_source_suffix: Any
    apply_buy_groups_config: Any
    apply_buy_group_enabled: Any
    apply_ex_buy_group_enabled: Any
    apply_ex_group_multiplier: Any
    apply_ex_source_suffixes_config: Any
    apply_extra_buy_groups_config: Any
    load_buy_group_options_from_game_type_config: Any
    apply_rebate_config_direct_count_modes: Any
    apply_rebate_config_direct_count_tiers: Any
    apply_sampling_append_mode: Any
    format_weighted_rtp: Any
    clear_cancel_request: Any
    request_cancel: Any
    task_cancelled_cls: Any
    get_source_db: Any
    sample_game_type_names: Any
    run_single_game_job: Any
    get_sampling_formation_exists: Any
    rebate_rule_fields: Any
    rebate_rule_field_labels: Any
    low_volume_rebate_count_threshold: Any
    normalize_direct_count_tiers_for_load: Any
    get_default_rebate_rules: Any
    validate_rebate_rules: Any
    get_rebate_config_low_volume_infos: Any
    get_rebate_config_index_warnings: Any
    generate_all_rebate_configs: Any
    weight_group_ids: Any
    group_weight_modes: Any
    group_weight_ui_modes: Any
    ex_group_modes: Any
    ex_independent_group_weight_modes: Any
    ex_purchase_mode: Any
    buy_group_mode: Any
    game_type_names: Any
    group_weight_rule_fields: Any
    group_weight_rule_field_labels: Any
    get_group_weight_formation_exists: Any
    load_group_weight_preview_rebates: Any
    get_displayed_group_weight_modes: Any
    collect_group_weight_preview_warnings: Any
    get_group_weight_mode_name: Any
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
    parse_non_negative_int_text: Any
    parse_positive_float_text: Any
    build_group_weight_preview_text: Any
    validate_group_weight_rules: Any
    generate_group_weight_config: Any
    run_task_preflight: Any


REQUIRED_RUNTIME_ATTRS = (
    'database_configs',
    'runtime_dict',
    'trigger_weights_dict',
    'rebate_rules',
    'sampling_append_mode',
    'group_weight_rules',
    'special_group_target_rtp',
    'buy_group_enabled',
    'ex_buy_group_enabled',
    'buy_group_game_type',
    'buy_group_multiplier',
    'buy_group_source_suffix',
    'ex_group_multiplier',
    'ex_source_suffixes',
    'extra_buy_groups',
    'buy_groups',
    'rebate_config_direct_count_modes',
    'external_config_source',
    'external_config_load_error',
    'game_configs',
    'source_db',
)

REQUIRED_MODULE_ATTRS = (
    '_VENDOR_TYPE_MAP',
    'RANDOM_SEED',
    'run_all_sampling_jobs',
    'write_common_configs',
    'test_selected_database_connections',
    'normalize_extra_buy_groups',
    'DEFAULT_TRIGGER_WEIGHTS',
    'DEFAULT_SAMPLING_APPEND_MODE',
    'DEFAULT_BUY_GROUP_ENABLED',
    'DEFAULT_EX_BUY_GROUP_ENABLED',
    'DEFAULT_BUY_GROUP_GAME_TYPE',
    'DEFAULT_BUY_GROUP_MULTIPLIER',
    'DEFAULT_BUY_GROUP_SOURCE_SUFFIX',
    'DEFAULT_EX_GROUP_MULTIPLIER',
    'DEFAULT_EXTRA_BUY_GROUPS',
    'DEFAULT_REBATE_RULES',
    'DEFAULT_REBATE_CONFIG_DIRECT_COUNT_TIERS',
    'DEFAULT_GROUP_WEIGHT_RULES',
    'DEFAULT_SPECIAL_GROUP_TARGET_RTP',
    'DEFAULT_EX_GROUP_TARGET_RTPS',
    'get_app_settings_path',
    'get_app_profile_settings_path',
    'clone_rebate_rules',
    'clone_group_weight_rules',
    'clone_extra_buy_groups',
    'clear_config_warnings',
    'consume_config_warnings',
    'normalize_rebate_rules_for_load',
    'normalize_group_weight_rules_for_load',
    'apply_runtime_config',
    'apply_weight_config',
    'apply_rebate_rules_config',
    'apply_group_weight_rules_config',
    'apply_special_group_target_rtp',
    'apply_ex_group_target_rtps_config',
    'apply_buy_group_multiplier',
    'apply_buy_group_game_type',
    'apply_buy_group_source_suffix',
    'apply_buy_groups_config',
    'apply_buy_group_enabled',
    'apply_ex_buy_group_enabled',
    'apply_ex_group_multiplier',
    'apply_ex_source_suffixes_config',
    'apply_extra_buy_groups_config',
    'load_buy_group_options_from_game_type_config',
    'apply_rebate_config_direct_count_modes',
    'apply_rebate_config_direct_count_tiers',
    'apply_sampling_append_mode',
    'get_rebate_config_direct_count_tiers',
    'normalize_direct_count_tiers_for_load',
    'format_weighted_rtp',
    'clear_cancel_request',
    'request_cancel',
    'TaskCancelled',
    'get_runtime_game_configs',
    'get_runtime_sample_game_type_names',
    'get_runtime_rebate_rules',
    'get_runtime_default_rebate_rules',
    'clone_runtime_rebate_rules',
    'validate_runtime_rebate_rules',
    'run_single_game_job',
    'get_sampling_formation_exists',
    'REBATE_RULE_FIELDS',
    'REBATE_RULE_FIELD_LABELS',
    'LOW_VOLUME_REBATE_COUNT_THRESHOLD',
    'validate_rebate_rules',
    'get_rebate_config_low_volume_infos',
    'get_rebate_config_index_warnings',
    'generate_all_rebate_configs',
    'WEIGHT_GROUP_IDS',
    'GROUP_WEIGHT_MODES',
    'GROUP_WEIGHT_UI_MODES',
    'EX_GROUP_MODES',
    'EX_INDEPENDENT_GROUP_WEIGHT_MODES',
    'EX_PURCHASE_MODE',
    'BUY_GROUP_MODE',
    'GAME_TYPE_NAMES',
    'GROUP_WEIGHT_RULE_FIELDS',
    'GROUP_WEIGHT_RULE_FIELD_LABELS',
    'get_group_weight_formation_exists',
    'load_group_weight_preview_rebates',
    'get_displayed_group_weight_modes',
    'collect_group_weight_preview_warnings',
    'get_group_weight_mode_name',
    'is_extra_buy_mode',
    'get_extra_buy_group_by_mode',
    'get_buy_group_game_type_for_mode',
    'get_group_weight_write_game_type',
    'get_buy_group_source_suffix_for_mode',
    'get_extra_buy_game_type',
    'make_extra_buy_mode',
    'has_extra_buy_groups',
    'format_group_rtp_option',
    'get_group_target_rtp_value',
    '_parse_non_negative_int_text',
    '_parse_positive_float_text',
    'build_group_weight_preview_text',
    'validate_group_weight_rules',
    'generate_group_weight_config',
    'run_task_preflight',
)


def _require_attrs(obj, names, label):
    missing = [name for name in names if not hasattr(obj, name)]
    if missing:
        raise AttributeError(f"{label} missing required attributes: {', '.join(missing)}")
    return SimpleNamespace(**{name: getattr(obj, name) for name in names})


def build_slot_app_deps_context(runtime, module):
    """Build the context object used by slot_app_deps builders."""
    r = _require_attrs(runtime, REQUIRED_RUNTIME_ATTRS, 'runtime state')
    m = _require_attrs(module, REQUIRED_MODULE_ATTRS, 'slot app module')
    return SlotAppDepsContext(
        database_configs=r.database_configs,
        vendor_type_map=m._VENDOR_TYPE_MAP,
        random_seed=m.RANDOM_SEED,
        run_all_sampling_jobs=m.run_all_sampling_jobs,
        write_common_configs=m.write_common_configs,
        test_selected_database_connections=m.test_selected_database_connections,
        normalize_extra_buy_groups=m.normalize_extra_buy_groups,
        default_trigger_weights=m.DEFAULT_TRIGGER_WEIGHTS,
        default_sampling_append_mode=m.DEFAULT_SAMPLING_APPEND_MODE,
        default_buy_group_enabled=m.DEFAULT_BUY_GROUP_ENABLED,
        default_ex_buy_group_enabled=m.DEFAULT_EX_BUY_GROUP_ENABLED,
        default_buy_group_game_type=m.DEFAULT_BUY_GROUP_GAME_TYPE,
        default_buy_group_multiplier=m.DEFAULT_BUY_GROUP_MULTIPLIER,
        default_buy_group_source_suffix=m.DEFAULT_BUY_GROUP_SOURCE_SUFFIX,
        default_ex_group_multiplier=m.DEFAULT_EX_GROUP_MULTIPLIER,
        default_extra_buy_groups=m.DEFAULT_EXTRA_BUY_GROUPS,
        default_rebate_rules=m.DEFAULT_REBATE_RULES,
        default_direct_count_tiers=m.DEFAULT_REBATE_CONFIG_DIRECT_COUNT_TIERS,
        default_group_weight_rules=m.DEFAULT_GROUP_WEIGHT_RULES,
        default_special_group_target_rtp=m.DEFAULT_SPECIAL_GROUP_TARGET_RTP,
        default_ex_group_target_rtps=m.DEFAULT_EX_GROUP_TARGET_RTPS,
        get_runtime_state=r.runtime_dict,
        get_trigger_weights=r.trigger_weights_dict,
        get_rebate_rules=lambda: runtime.rebate_rules,
        get_sampling_append_mode=lambda: runtime.sampling_append_mode,
        get_group_weight_rules=lambda: runtime.group_weight_rules,
        get_special_group_target_rtp=lambda: runtime.special_group_target_rtp,
        get_ex_group_target_rtps=lambda: dict(getattr(runtime, 'ex_group_target_rtps', {})),
        get_buy_group_enabled=lambda: runtime.buy_group_enabled,
        get_ex_buy_group_enabled=lambda: runtime.ex_buy_group_enabled,
        get_buy_group_game_type=lambda: runtime.buy_group_game_type,
        get_buy_group_multiplier=lambda: runtime.buy_group_multiplier,
        get_buy_group_source_suffix=lambda: runtime.buy_group_source_suffix,
        get_buy_groups=lambda: runtime.buy_groups,
        get_ex_group_multiplier=lambda: runtime.ex_group_multiplier,
        get_ex_source_suffixes=lambda: dict(runtime.ex_source_suffixes),
        get_extra_buy_groups=lambda: runtime.extra_buy_groups,
        get_direct_count_modes=lambda: runtime.rebate_config_direct_count_modes,
        get_direct_count_tiers=m.get_rebate_config_direct_count_tiers,
        get_app_settings_path=m.get_app_settings_path,
        get_app_profile_settings_path=m.get_app_profile_settings_path,
        get_external_config_source=lambda: runtime.external_config_source,
        get_external_config_load_error=lambda: runtime.external_config_load_error,
        get_game_configs=m.get_runtime_game_configs,
        get_sample_game_type_names=m.get_runtime_sample_game_type_names,
        get_sampling_rebate_rules=m.get_runtime_rebate_rules,
        get_default_sampling_rebate_rules=m.get_runtime_default_rebate_rules,
        clone_sampling_rebate_rules=m.clone_runtime_rebate_rules,
        validate_sampling_rebate_rules=m.validate_runtime_rebate_rules,
        clone_rebate_rules=m.clone_rebate_rules,
        clone_group_weight_rules=m.clone_group_weight_rules,
        clone_extra_buy_groups=m.clone_extra_buy_groups,
        clear_config_warnings=m.clear_config_warnings,
        consume_config_warnings=m.consume_config_warnings,
        normalize_rebate_rules_for_load=m.normalize_rebate_rules_for_load,
        normalize_group_weight_rules_for_load=m.normalize_group_weight_rules_for_load,
        apply_runtime_config=m.apply_runtime_config,
        apply_weight_config=m.apply_weight_config,
        apply_rebate_rules_config=m.apply_rebate_rules_config,
        apply_group_weight_rules_config=m.apply_group_weight_rules_config,
        apply_special_group_target_rtp=m.apply_special_group_target_rtp,
        apply_ex_group_target_rtps_config=m.apply_ex_group_target_rtps_config,
        apply_buy_group_multiplier=m.apply_buy_group_multiplier,
        apply_buy_group_game_type=m.apply_buy_group_game_type,
        apply_buy_group_source_suffix=m.apply_buy_group_source_suffix,
        apply_buy_groups_config=m.apply_buy_groups_config,
        apply_buy_group_enabled=m.apply_buy_group_enabled,
        apply_ex_buy_group_enabled=m.apply_ex_buy_group_enabled,
        apply_ex_group_multiplier=m.apply_ex_group_multiplier,
        apply_ex_source_suffixes_config=m.apply_ex_source_suffixes_config,
        apply_extra_buy_groups_config=m.apply_extra_buy_groups_config,
        load_buy_group_options_from_game_type_config=m.load_buy_group_options_from_game_type_config,
        apply_rebate_config_direct_count_modes=m.apply_rebate_config_direct_count_modes,
        apply_rebate_config_direct_count_tiers=m.apply_rebate_config_direct_count_tiers,
        apply_sampling_append_mode=m.apply_sampling_append_mode,
        format_weighted_rtp=m.format_weighted_rtp,
        clear_cancel_request=m.clear_cancel_request,
        request_cancel=m.request_cancel,
        task_cancelled_cls=m.TaskCancelled,
        get_source_db=lambda: runtime.source_db,
        sample_game_type_names=m.get_runtime_sample_game_type_names(),
        run_single_game_job=m.run_single_game_job,
        get_sampling_formation_exists=m.get_sampling_formation_exists,
        rebate_rule_fields=m.REBATE_RULE_FIELDS,
        rebate_rule_field_labels=m.REBATE_RULE_FIELD_LABELS,
        low_volume_rebate_count_threshold=m.LOW_VOLUME_REBATE_COUNT_THRESHOLD,
        normalize_direct_count_tiers_for_load=m.normalize_direct_count_tiers_for_load,
        get_default_rebate_rules=lambda: m.DEFAULT_REBATE_RULES,
        validate_rebate_rules=m.validate_rebate_rules,
        get_rebate_config_low_volume_infos=m.get_rebate_config_low_volume_infos,
        get_rebate_config_index_warnings=m.get_rebate_config_index_warnings,
        generate_all_rebate_configs=m.generate_all_rebate_configs,
        weight_group_ids=m.WEIGHT_GROUP_IDS,
        group_weight_modes=m.GROUP_WEIGHT_MODES,
        group_weight_ui_modes=m.GROUP_WEIGHT_UI_MODES,
        ex_group_modes=m.EX_GROUP_MODES,
        ex_independent_group_weight_modes=m.EX_INDEPENDENT_GROUP_WEIGHT_MODES,
        ex_purchase_mode=m.EX_PURCHASE_MODE,
        buy_group_mode=m.BUY_GROUP_MODE,
        game_type_names=m.GAME_TYPE_NAMES,
        group_weight_rule_fields=m.GROUP_WEIGHT_RULE_FIELDS,
        group_weight_rule_field_labels=m.GROUP_WEIGHT_RULE_FIELD_LABELS,
        get_group_weight_formation_exists=m.get_group_weight_formation_exists,
        load_group_weight_preview_rebates=m.load_group_weight_preview_rebates,
        get_displayed_group_weight_modes=m.get_displayed_group_weight_modes,
        collect_group_weight_preview_warnings=m.collect_group_weight_preview_warnings,
        get_group_weight_mode_name=m.get_group_weight_mode_name,
        is_extra_buy_mode=m.is_extra_buy_mode,
        get_extra_buy_group_by_mode=m.get_extra_buy_group_by_mode,
        get_buy_group_game_type_for_mode=m.get_buy_group_game_type_for_mode,
        get_group_weight_write_game_type=m.get_group_weight_write_game_type,
        get_buy_group_source_suffix_for_mode=m.get_buy_group_source_suffix_for_mode,
        get_extra_buy_game_type=m.get_extra_buy_game_type,
        make_extra_buy_mode=m.make_extra_buy_mode,
        has_extra_buy_groups=m.has_extra_buy_groups,
        format_group_rtp_option=m.format_group_rtp_option,
        get_group_target_rtp_value=m.get_group_target_rtp_value,
        parse_non_negative_int_text=m._parse_non_negative_int_text,
        parse_positive_float_text=m._parse_positive_float_text,
        build_group_weight_preview_text=m.build_group_weight_preview_text,
        validate_group_weight_rules=m.validate_group_weight_rules,
        generate_group_weight_config=m.generate_group_weight_config,
        run_task_preflight=m.run_task_preflight,
    )
