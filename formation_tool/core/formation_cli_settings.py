"""Saved-settings loader used by the legacy CLI entrypoint."""

from formation_tool.core import settings_logic


def apply_cli_settings_data(data, *, deps, runtime_only=False):
    """Apply saved settings through callbacks supplied by the main script."""
    current_runtime = deps.get_current_runtime()
    runtime = settings_logic.get_runtime_settings(data)
    if runtime:
        deps.apply_runtime_config(
            runtime.get('vendor', current_runtime['vendor']),
            runtime.get('game_id', current_runtime['game_id']),
            runtime.get('source_db', current_runtime['source_db']),
            runtime.get('final_db', current_runtime['final_db']),
            runtime.get('config_db', current_runtime['config_db']),
        )

    if runtime_only:
        return

    trigger_weights = data.get('trigger_weights', {})
    if trigger_weights:
        defaults = deps.get_trigger_weights()
        deps.apply_weight_config(
            trigger_weights.get('special_0', defaults['special_0']),
            trigger_weights.get('special_1', defaults['special_1']),
            trigger_weights.get('free_0', defaults['free_0']),
            trigger_weights.get('free_1', defaults['free_1']),
            trigger_weights.get('special_2', defaults.get('special_2')),
            trigger_weights.get('special_3', defaults.get('special_3')),
            trigger_weights.get('free_2', defaults.get('free_2')),
            trigger_weights.get('free_3', defaults.get('free_3')),
        )

    if 'rebate_rules' in data:
        deps.apply_rebate_rules_config(
            deps.normalize_rebate_rules_for_load(data['rebate_rules'])
        )

    sampling_options = data.get('sampling_options', {})
    if sampling_options:
        apply_detailed_log = getattr(deps, 'apply_sampling_detailed_log', None)
        if apply_detailed_log is not None:
            default_detailed_log = getattr(deps, 'get_sampling_detailed_log', lambda: False)()
            apply_detailed_log(sampling_options.get('detailed_log', default_detailed_log))
        apply_temp_db = getattr(deps, 'apply_sampling_temp_db_config', None)
        if apply_temp_db is not None:
            default_temp_db = getattr(deps, 'get_sampling_temp_db', lambda: None)()
            apply_temp_db(
                True,
                sampling_options.get('temp_db', default_temp_db),
            )
        apply_increment_db = getattr(deps, 'apply_sampling_increment_db_config', None)
        if apply_increment_db is not None:
            default_increment_db = getattr(deps, 'get_sampling_increment_db', lambda: None)()
            apply_increment_db(sampling_options.get('increment_db', default_increment_db))
        apply_auto_sync = getattr(deps, 'apply_sampling_auto_sync_to_target', None)
        if apply_auto_sync is not None:
            default_auto_sync = getattr(deps, 'get_sampling_auto_sync_to_target', lambda: False)()
            apply_auto_sync(sampling_options.get('auto_sync_to_target', default_auto_sync))

    if 'group_weight_rules' in data:
        deps.apply_group_weight_rules_config(
            deps.normalize_group_weight_rules_for_load(data['group_weight_rules'])
        )
    if 'group_weight_group_rules' in data:
        apply_group_rules = getattr(deps, 'apply_group_weight_group_rules_config', None)
        normalize_group_rules = getattr(
            deps,
            'normalize_group_weight_group_rules_for_load',
            lambda rules: rules or {},
        )
        if apply_group_rules is not None:
            apply_group_rules(normalize_group_rules(data['group_weight_group_rules']))

    group_options = data.get('group_weight_options', {})
    if group_options:
        if 'extra_weight_groups' in group_options:
            apply_extra_weight_groups = getattr(deps, 'apply_extra_weight_groups_config', None)
            normalize_extra_weight_groups = getattr(deps, 'normalize_extra_weight_groups', lambda groups: groups or [])
            if apply_extra_weight_groups is not None:
                apply_extra_weight_groups(normalize_extra_weight_groups(group_options.get('extra_weight_groups')))
        if 'buy_enabled' in group_options:
            deps.apply_buy_group_enabled(group_options.get('buy_enabled'))
        if 'ex_buy_enabled' in group_options:
            deps.apply_ex_buy_group_enabled(group_options.get('ex_buy_enabled'))
        if 'ex_buy_game_type' in group_options:
            deps.apply_ex_buy_group_game_type(group_options.get('ex_buy_game_type'))
        if 'ex_buy_source_suffix' in group_options:
            deps.apply_ex_buy_group_source_suffix(group_options.get('ex_buy_source_suffix'))
        if 'buy_game_type' in group_options:
            deps.apply_buy_group_game_type(group_options.get('buy_game_type'))
        if 'buy_multiplier' in group_options:
            deps.apply_buy_group_multiplier(group_options.get('buy_multiplier'))
        if 'buy_source_suffix' in group_options:
            deps.apply_buy_group_source_suffix(group_options.get('buy_source_suffix'))
        if 'ex_multiplier' in group_options:
            deps.apply_ex_group_multiplier(group_options.get('ex_multiplier'))
        if 'ex_group_target_rtps' in group_options:
            deps.apply_ex_group_target_rtps_config(group_options.get('ex_group_target_rtps'))
        if 'zero_rebate_inference_modes' in group_options:
            deps.apply_zero_rebate_inference_modes_config(group_options.get('zero_rebate_inference_modes'))
        if 'independent_rtp_modes' in group_options:
            apply_independent_rtp = getattr(deps, 'apply_independent_rtp_modes_config', None)
            if apply_independent_rtp is not None:
                apply_independent_rtp(group_options.get('independent_rtp_modes'))
        if 'ex_source_suffixes' in group_options:
            deps.apply_ex_source_suffixes_config(group_options.get('ex_source_suffixes'))
        if 'extra_buy_groups' in group_options:
            deps.apply_extra_buy_groups_config(group_options.get('extra_buy_groups'))
        if 'special_target_rtp' in group_options:
            deps.apply_special_group_target_rtp(group_options.get('special_target_rtp'))

    deps.apply_rebate_config_direct_count_modes(data.get('direct_count_modes', []))
    if 'direct_count_tiers' in data:
        deps.apply_rebate_config_direct_count_tiers(
            deps.normalize_direct_count_tiers_for_load(data['direct_count_tiers'])
        )


def load_cli_settings(*, deps, print_func=print):
    """Load last-selection and room-specific settings before CLI actions run."""
    deps.clear_config_warnings()
    loaded = False
    last_path = deps.get_app_settings_path()
    try:
        if last_path.is_file():
            apply_cli_settings_data(
                settings_logic.read_settings_file(last_path),
                deps=deps,
                runtime_only=True,
            )
            loaded = True
            print_func(f"已加载上次选择配置：{last_path}")

        profile_path = deps.get_app_profile_settings_path()
        if profile_path.is_file():
            apply_cli_settings_data(settings_logic.read_settings_file(profile_path), deps=deps)
            loaded = True
            print_func(f"已加载当前房间完整配置：{profile_path}")
        elif loaded:
            print_func(f"未找到当前房间完整配置，使用代码默认规则：{profile_path}")

        if not loaded:
            deps.apply_runtime_config(**deps.get_current_runtime())
    except Exception as exc:
        print_func(f"CLI 配置加载失败：{exc}")
        print_func("请先通过 GUI 选择厂商、游戏编号和数据库并保存配置，或检查配置文件内容。")
        return False

    for warning in deps.consume_config_warnings():
        print_func(f"配置兼容提示：{warning}")
    return True
