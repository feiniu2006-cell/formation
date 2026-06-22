"""Build table-driven runtime configs from game_type_config rows."""

import copy

from formation_tool.core import buy_group_config
from formation_tool.core import formation_modes


def extract_source_suffix_from_table_name(table_name, table_prefix):
    table_name = str(table_name or '').strip()
    table_prefix = str(table_prefix or '')
    if table_prefix and table_name.startswith(table_prefix):
        return table_name[len(table_prefix):]
    return table_name


def get_fallback_source_suffix_for_mode(
    mode,
    *,
    runtime,
    get_table_name,
):
    mode = formation_modes.normalize_group_weight_mode_key(mode)
    if mode in runtime.game_configs:
        table_name = get_table_name('SOURCE_TABLE', runtime.game_configs[mode]['table_config'])
        return extract_source_suffix_from_table_name(table_name, runtime.game_table_prefix)
    if mode == formation_modes.EX_PURCHASE_MODE and '8' in runtime.game_configs:
        table_name = get_table_name('SOURCE_TABLE', runtime.game_configs['8']['table_config'])
        return extract_source_suffix_from_table_name(table_name, runtime.game_table_prefix)
    return formation_modes.get_buy_group_source_suffix(
        mode,
        buy_group_source_suffix=runtime.buy_group_source_suffix,
        extra_buy_groups=runtime.extra_buy_groups,
    )


def build_runtime_buy_group_entries_with_table_sources(
    *,
    runtime,
    get_game_type_source_suffix,
):
    split = buy_group_config.split_buy_groups_to_legacy(
        runtime.buy_groups,
        default_buy_enabled=runtime.buy_group_enabled,
        default_buy_game_type=runtime.buy_group_game_type,
        default_buy_multiplier=runtime.buy_group_multiplier,
        default_buy_source_suffix=runtime.buy_group_source_suffix,
    )
    default_entry = {
        'enabled': bool(split['buy_enabled']),
        'game_type': int(split['buy_game_type']),
        'source_suffix': get_game_type_source_suffix(
            split['buy_game_type'],
            default=split['buy_source_suffix'],
        ),
    }
    extra_entries = []
    for group in split['extra_buy_groups']:
        entry = dict(group)
        entry['source_suffix'] = get_game_type_source_suffix(
            group['game_type'],
            default=group.get('source_suffix') or split['buy_source_suffix'],
        )
        extra_entries.append(entry)
    return default_entry, extra_entries


def build_table_driven_base_game_configs(
    *,
    runtime,
    get_game_type_source_suffix,
    build_rebate_table_suffix_from_formation_suffix,
):
    """Apply DB table source_suffix overrides onto the fixed game configs."""
    base_configs = {
        mode: copy.deepcopy(config)
        for mode, config in runtime.game_configs.items()
    }
    for mode, config in base_configs.items():
        source_suffix = get_game_type_source_suffix(mode)
        if not source_suffix:
            continue
        table_name = f"{runtime.game_table_prefix}{source_suffix}"
        rebate_suffix = build_rebate_table_suffix_from_formation_suffix(source_suffix)
        config['table_config']['SOURCE_TABLE']['name'] = table_name
        config['table_config']['FINAL_TABLE']['name'] = table_name
        config['table_config']['REBATE_CONFIG_TABLE']['name'] = (
            f"{runtime.game_table_prefix}{rebate_suffix}"
        )
    return base_configs


def get_buy_group_source_suffix_for_mode(
    game_type,
    *,
    get_game_type_source_suffix,
    get_buy_group_game_type_for_mode,
    get_fallback_source_suffix_for_mode,
):
    """Return the source formation suffix for one buy-like mode."""
    mode = str(game_type)
    if mode in (formation_modes.EX_PURCHASE_MODE, formation_modes.BUY_GROUP_MODE) or formation_modes.is_extra_buy_mode(mode):
        actual_game_type = int(get_buy_group_game_type_for_mode(mode))
    else:
        actual_game_type = int(mode)
    source_suffix = get_game_type_source_suffix(actual_game_type)
    if source_suffix:
        return source_suffix
    return get_fallback_source_suffix_for_mode(mode)
