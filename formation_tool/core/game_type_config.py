"""Helpers for table-driven game_type/source_suffix/buy-kind configuration."""

from formation_tool.core import buy_group_config


GAME_TYPE_CONFIG_TABLE = 'game_room_game_type_config'

BUY_KIND_NORMAL = 0
BUY_KIND_BUY = 1
BUY_KIND_EX_BUY = 2


def normalize_buy_kind(value):
    """Normalize `is_buy` values loaded from DB or settings-like payloads."""
    if value is None or str(value).strip() == '':
        return BUY_KIND_NORMAL
    try:
        buy_kind = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"is_buy 必须是 0/1/2: {value}") from None
    if buy_kind not in (BUY_KIND_NORMAL, BUY_KIND_BUY, BUY_KIND_EX_BUY):
        raise ValueError(f"is_buy 仅支持 0/1/2: {value}")
    return buy_kind


def _row_value(row, key, index):
    if isinstance(row, dict):
        return row.get(key)
    if hasattr(row, key):
        return getattr(row, key)
    return row[index]


def normalize_game_type_config_row(row):
    """Return one normalized game_type config row."""
    game_type = int(_row_value(row, 'game_type', 0))
    source_suffix = buy_group_config.normalize_buy_source_suffix(
        _row_value(row, 'source_suffix', 1),
        f"game_type={game_type} 的 source_suffix",
    )
    buy_kind = normalize_buy_kind(_row_value(row, 'is_buy', 2))
    return {
        'game_type': game_type,
        'source_suffix': source_suffix,
        'is_buy': buy_kind,
    }


def build_game_type_config_map(rows):
    """Build a `{game_type: config}` mapping from DB query rows."""
    configs = {}
    for row in rows or []:
        item = normalize_game_type_config_row(row)
        configs[item['game_type']] = item
    return configs


def get_game_type_config(configs, game_type):
    return (configs or {}).get(int(game_type))


def get_source_suffix(configs, game_type, default=None):
    item = get_game_type_config(configs, game_type)
    if item is None:
        return default
    return item['source_suffix']


def get_buy_kind(configs, game_type, default=BUY_KIND_NORMAL):
    item = get_game_type_config(configs, game_type)
    if item is None:
        return default
    return item['is_buy']


def is_buy_kind(configs, game_type, default=BUY_KIND_NORMAL):
    return get_buy_kind(configs, game_type, default=default) == BUY_KIND_BUY


def is_ex_buy_kind(configs, game_type, default=BUY_KIND_NORMAL):
    return get_buy_kind(configs, game_type, default=default) == BUY_KIND_EX_BUY


def _build_existing_extra_buy_lookup(existing_extra_buy_groups):
    lookup = {}
    for group in existing_extra_buy_groups or []:
        try:
            game_type = int(group.get('game_type'))
        except (TypeError, ValueError):
            continue
        lookup[game_type] = dict(group)
    return lookup


def _keep_source_game_type(game_type, existing_source_game_types):
    if existing_source_game_types is None:
        return True
    return int(game_type) in {int(item) for item in existing_source_game_types}


def build_buy_group_options_from_configs(
    configs,
    *,
    current_buy_game_type,
    current_buy_multiplier,
    current_buy_source_suffix,
    current_ex_buy_game_type=98,
    current_ex_buy_source_suffix='',
    existing_extra_buy_groups=None,
    existing_source_game_types=None,
    default_buy_game_type=buy_group_config.DEFAULT_BUY_GROUP_GAME_TYPE,
    default_ex_buy_game_type=98,
):
    """Convert DB game_type config rows into UI buy-group options."""
    existing_extra_by_type = _build_existing_extra_buy_lookup(existing_extra_buy_groups)
    normal_buy_rows = [
        dict(item)
        for item in sorted((configs or {}).values(), key=lambda row: int(row['game_type']))
        if item.get('is_buy') == BUY_KIND_BUY
        and _keep_source_game_type(item['game_type'], existing_source_game_types)
    ]
    ex_buy_rows = [
        dict(item)
        for item in sorted((configs or {}).values(), key=lambda row: int(row['game_type']))
        if item.get('is_buy') == BUY_KIND_EX_BUY
        and _keep_source_game_type(item['game_type'], existing_source_game_types)
    ]

    current_buy_game_type = int(current_buy_game_type)
    default_buy_game_type = int(default_buy_game_type)
    default_row = next(
        (item for item in normal_buy_rows if int(item['game_type']) == current_buy_game_type),
        None,
    )
    if default_row is None:
        default_row = next(
            (item for item in normal_buy_rows if int(item['game_type']) == default_buy_game_type),
            None,
        )
    if default_row is None and normal_buy_rows:
        default_row = normal_buy_rows[0]

    ex_buy_game_type = int(current_ex_buy_game_type)
    default_ex_buy_game_type = int(default_ex_buy_game_type)
    ex_row = next(
        (item for item in ex_buy_rows if int(item['game_type']) == ex_buy_game_type),
        None,
    )
    if ex_row is None:
        ex_row = next(
            (item for item in ex_buy_rows if int(item['game_type']) == default_ex_buy_game_type),
            None,
        )
    if ex_row is None and ex_buy_rows:
        ex_row = ex_buy_rows[0]

    if default_row is None:
        default_game_type = current_buy_game_type
        default_buy = {
            'enabled': False,
            'game_type': current_buy_game_type,
            'multiplier': current_buy_multiplier,
            'source_suffix': current_buy_source_suffix,
        }
    else:
        default_game_type = int(default_row['game_type'])
        default_buy = {
            'enabled': True,
            'game_type': default_game_type,
            'multiplier': current_buy_multiplier,
            'source_suffix': default_row['source_suffix'],
        }

    if ex_row is None:
        ex_buy = {
            'enabled': False,
            'game_type': ex_buy_game_type,
            'source_suffix': current_ex_buy_source_suffix,
        }
    else:
        ex_buy = {
            'enabled': True,
            'game_type': int(ex_row['game_type']),
            'source_suffix': ex_row['source_suffix'],
        }

    extra_buy_groups = []
    for row in normal_buy_rows:
        game_type = int(row['game_type'])
        if game_type == default_game_type:
            continue
        previous = existing_extra_by_type.get(game_type, {})
        group = {
            'game_type': game_type,
            'multiplier': previous.get('multiplier', current_buy_multiplier),
            'source_suffix': row['source_suffix'],
        }
        if previous.get('rules') is not None:
            group['rules'] = previous['rules']
        extra_buy_groups.append(group)

    return {
        'default_buy': default_buy,
        'ex_buy': ex_buy,
        'extra_buy_groups': extra_buy_groups,
        'ex_buy_enabled': bool(ex_buy_rows),
        'normal_buy_game_types': [int(item['game_type']) for item in normal_buy_rows],
        'ex_buy_game_types': [int(item['game_type']) for item in ex_buy_rows],
    }
