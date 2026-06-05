"""Dynamic rebate-count configs for custom buy-group source tables."""

from formation_tool.core import buy_group_config


BUY_SOURCE_SAMPLE_MODE_PREFIX = 'buy_source:'


def make_buy_source_sample_mode(source_suffix):
    """Return a stable internal sampling key for one custom buy source suffix."""
    return f"{BUY_SOURCE_SAMPLE_MODE_PREFIX}{source_suffix}"


def is_buy_source_sample_mode(mode):
    return str(mode).startswith(BUY_SOURCE_SAMPLE_MODE_PREFIX)


def clone_rule_list(rules):
    return [dict(rule) for rule in rules or []]


def _table_name(table_key, table_config):
    return table_config[table_key]['name']


def _collect_buy_source_entries(
    *,
    buy_enabled,
    buy_game_type,
    buy_source_suffix,
    extra_buy_groups,
):
    entries = []
    if buy_enabled:
        entries.append({
            'source_suffix': buy_source_suffix or buy_group_config.DEFAULT_BUY_GROUP_SOURCE_SUFFIX,
            'labels': [f"购买局{int(buy_game_type)}"],
        })

    for group in extra_buy_groups or []:
        entries.append({
            'source_suffix': group.get('source_suffix') or buy_group_config.DEFAULT_BUY_GROUP_SOURCE_SUFFIX,
            'labels': [f"购买局{int(group['game_type'])}"],
        })
    return entries


def build_buy_source_rebate_game_configs(
    *,
    table_prefix,
    source_db,
    final_db,
    config_db,
    random_seed,
    base_game_configs,
    buy_enabled,
    buy_game_type,
    buy_source_suffix,
    extra_buy_groups,
):
    """Build extra game configs for custom buy source tables not covered by fixed modes."""
    existing_rebate_tables = {
        _table_name('REBATE_CONFIG_TABLE', config['table_config'])
        for config in base_game_configs.values()
    }
    base_conditions = {
        mode: dict(config.get('sample_conditions', {}))
        for mode, config in base_game_configs.items()
    }
    grouped_sources = {}
    for entry in _collect_buy_source_entries(
        buy_enabled=buy_enabled,
        buy_game_type=buy_game_type,
        buy_source_suffix=buy_source_suffix,
        extra_buy_groups=extra_buy_groups,
    ):
        source_suffix = buy_group_config.normalize_buy_source_suffix(entry['source_suffix'])
        rebate_suffix = buy_group_config.formation_suffix_to_rebate_suffix(source_suffix)
        rebate_table = f"{table_prefix}{rebate_suffix}"
        if rebate_table in existing_rebate_tables:
            continue
        grouped = grouped_sources.setdefault(
            source_suffix,
            {
                'source_suffix': source_suffix,
                'rebate_suffix': rebate_suffix,
                'rebate_table': rebate_table,
                'labels': [],
            },
        )
        grouped['labels'].extend(entry['labels'])

    configs = {}
    for source_suffix, item in sorted(grouped_sources.items()):
        source_rule_mode = buy_group_config.infer_rebate_rule_source_mode(source_suffix)
        sample_conditions = dict(
            base_conditions.get(source_rule_mode)
            or base_conditions.get(buy_group_config.BUY_SOURCE_REBATE_RULE_DEFAULT_MODE)
            or {}
        )
        sample_conditions.setdefault('random_seed', random_seed)
        mode = make_buy_source_sample_mode(source_suffix)
        label_text = '、'.join(item['labels'])
        configs[mode] = {
            'name': f"{label_text}来源({source_suffix})",
            'rule_source_mode': source_rule_mode,
            'table_config': {
                'SOURCE_TABLE': {'name': f"{table_prefix}{source_suffix}", 'database': source_db},
                'FINAL_TABLE': {'name': f"{table_prefix}{source_suffix}", 'database': final_db},
                'REBATE_CONFIG_TABLE': {'name': item['rebate_table'], 'database': config_db},
            },
            'sample_conditions': sample_conditions,
        }
    return configs


def merge_buy_source_rebate_rules(base_rules, dynamic_game_configs):
    """Copy inferred source-mode rules onto dynamic buy source modes."""
    merged = {
        str(mode): clone_rule_list(mode_rules)
        for mode, mode_rules in (base_rules or {}).items()
    }
    for mode, config in dynamic_game_configs.items():
        source_mode = str(config.get('rule_source_mode') or buy_group_config.BUY_SOURCE_REBATE_RULE_DEFAULT_MODE)
        merged.setdefault(mode, clone_rule_list(merged.get(source_mode)))
    return merged
