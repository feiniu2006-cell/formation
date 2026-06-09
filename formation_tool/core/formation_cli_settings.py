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
        )

    if 'rebate_rules' in data:
        deps.apply_rebate_rules_config(
            deps.normalize_rebate_rules_for_load(data['rebate_rules'])
        )

    sampling_options = data.get('sampling_options', {})
    if sampling_options:
        deps.apply_sampling_append_mode(
            sampling_options.get('append_mode', deps.get_sampling_append_mode())
        )

    if 'group_weight_rules' in data:
        deps.apply_group_weight_rules_config(
            deps.normalize_group_weight_rules_for_load(data['group_weight_rules'])
        )

    group_options = data.get('group_weight_options', {})
    if group_options:
        if 'buy_enabled' in group_options:
            deps.apply_buy_group_enabled(group_options.get('buy_enabled'))
        if 'ex_buy_enabled' in group_options:
            deps.apply_ex_buy_group_enabled(group_options.get('ex_buy_enabled'))
        if 'buy_game_type' in group_options:
            deps.apply_buy_group_game_type(group_options.get('buy_game_type'))
        if 'buy_multiplier' in group_options:
            deps.apply_buy_group_multiplier(group_options.get('buy_multiplier'))
        if 'buy_source_suffix' in group_options:
            deps.apply_buy_group_source_suffix(group_options.get('buy_source_suffix'))
        if 'ex_multiplier' in group_options:
            deps.apply_ex_group_multiplier(group_options.get('ex_multiplier'))
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
