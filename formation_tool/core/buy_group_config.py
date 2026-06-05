"""Buy-group configuration helpers shared by UI, runtime, and group_weight."""

from dataclasses import dataclass

from formation_tool.core import formation_defaults
from formation_tool.core import rule_config_state


DEFAULT_BUY_GROUP_GAME_TYPE = formation_defaults.DEFAULT_BUY_GROUP_GAME_TYPE
DEFAULT_BUY_GROUP_SOURCE_SUFFIX = formation_defaults.DEFAULT_BUY_GROUP_SOURCE_SUFFIX
EXTRA_BUY_MODE_PREFIX = 'extra_buy:'
BUY_SOURCE_REBATE_RULE_SPECIAL_MODE = '2'
BUY_SOURCE_REBATE_RULE_FREE_MODE = '3'
BUY_SOURCE_REBATE_RULE_DEFAULT_MODE = '1'


@dataclass(frozen=True)
class BuyGroupConfig:
    """One buy-group row as entered in the UI."""

    game_type: int
    multiplier: float
    source_suffix: str = DEFAULT_BUY_GROUP_SOURCE_SUFFIX
    enabled: bool = True
    rules: list | None = None


def make_extra_buy_mode(game_type):
    return f"{EXTRA_BUY_MODE_PREFIX}{int(game_type)}"


def is_extra_buy_mode(mode):
    return str(mode).startswith(EXTRA_BUY_MODE_PREFIX)


def get_extra_buy_game_type(mode):
    if not is_extra_buy_mode(mode):
        raise ValueError(f"不是额外购买局模式: {mode}")
    return int(str(mode).split(":", 1)[1])


def formation_suffix_to_rebate_suffix(formation_suffix):
    suffix = rule_config_state.normalize_formation_suffix(
        formation_suffix,
        "阵型表后缀",
        default=DEFAULT_BUY_GROUP_SOURCE_SUFFIX,
    )
    if suffix == 'formation':
        return 'rebate_count'
    if suffix.endswith('_formation'):
        return f"rebate_{suffix[:-len('_formation')]}_count"
    return f"rebate_{suffix}_count"


def infer_rebate_rule_source_mode(source_suffix):
    """Infer which rebate-count rule set should be used for a buy source suffix."""
    suffix = str(source_suffix or '').lower()
    if 'special' in suffix:
        return BUY_SOURCE_REBATE_RULE_SPECIAL_MODE
    if 'free' in suffix:
        return BUY_SOURCE_REBATE_RULE_FREE_MODE
    return BUY_SOURCE_REBATE_RULE_DEFAULT_MODE


def normalize_buy_game_type(value, label="购买局类型"):
    return rule_config_state.parse_non_negative_int_text(value, label)


def normalize_buy_multiplier(value, label="购买倍数"):
    return rule_config_state.parse_positive_float_text(value, label)


def normalize_buy_source_suffix(value, label="购买局阵型表后缀"):
    return rule_config_state.normalize_formation_suffix(
        value,
        label,
        default=DEFAULT_BUY_GROUP_SOURCE_SUFFIX,
    )


def build_buy_group_entry(
    *,
    enabled,
    game_type,
    multiplier,
    source_suffix=DEFAULT_BUY_GROUP_SOURCE_SUFFIX,
    rules=None,
):
    """Return one normalized buy-group row in the unified settings shape."""
    entry = {
        'enabled': bool(enabled),
        'game_type': normalize_buy_game_type(game_type),
        'multiplier': normalize_buy_multiplier(multiplier),
        'source_suffix': normalize_buy_source_suffix(source_suffix),
    }
    if rules is not None:
        entry['rules'] = rules
    return entry


def build_buy_groups_from_legacy(
    *,
    buy_enabled,
    buy_game_type,
    buy_multiplier,
    buy_source_suffix,
    extra_buy_groups=None,
):
    """Build the unified buy-group list from the legacy default+extra fields."""
    groups = [
        build_buy_group_entry(
            enabled=buy_enabled,
            game_type=buy_game_type,
            multiplier=buy_multiplier,
            source_suffix=buy_source_suffix,
        )
    ]
    for group in extra_buy_groups or []:
        groups.append(
            build_buy_group_entry(
                enabled=group.get('enabled', True),
                game_type=group.get('game_type'),
                multiplier=group.get('multiplier', buy_multiplier),
                source_suffix=group.get('source_suffix', group.get('formation_suffix', buy_source_suffix)),
                rules=group.get('rules'),
            )
        )
    return groups


def normalize_buy_groups(
    groups,
    *,
    default_buy_enabled=False,
    default_buy_game_type=DEFAULT_BUY_GROUP_GAME_TYPE,
    default_buy_multiplier=formation_defaults.DEFAULT_BUY_GROUP_MULTIPLIER,
    default_buy_source_suffix=DEFAULT_BUY_GROUP_SOURCE_SUFFIX,
):
    """Normalize a unified buy-group list, falling back to one default row."""
    normalized = []
    for group in groups or []:
        if not isinstance(group, dict):
            continue
        try:
            normalized.append(
                build_buy_group_entry(
                    enabled=group.get('enabled', True),
                    game_type=group.get('game_type'),
                    multiplier=group.get('multiplier', default_buy_multiplier),
                    source_suffix=group.get('source_suffix', group.get('formation_suffix', default_buy_source_suffix)),
                    rules=group.get('rules'),
                )
            )
        except (TypeError, ValueError):
            continue

    if not normalized:
        normalized = [
            build_buy_group_entry(
                enabled=default_buy_enabled,
                game_type=default_buy_game_type,
                multiplier=default_buy_multiplier,
                source_suffix=default_buy_source_suffix,
            )
        ]
    return normalized


def get_enabled_buy_groups(groups):
    """Return enabled rows from a unified buy-group list."""
    return [dict(group) for group in groups or [] if group.get('enabled', True)]


def split_buy_groups_to_legacy(
    groups,
    *,
    default_buy_enabled=False,
    default_buy_game_type=DEFAULT_BUY_GROUP_GAME_TYPE,
    default_buy_multiplier=formation_defaults.DEFAULT_BUY_GROUP_MULTIPLIER,
    default_buy_source_suffix=DEFAULT_BUY_GROUP_SOURCE_SUFFIX,
):
    """Split the unified buy-group list back to legacy fields used by older callers."""
    normalized = normalize_buy_groups(
        groups,
        default_buy_enabled=default_buy_enabled,
        default_buy_game_type=default_buy_game_type,
        default_buy_multiplier=default_buy_multiplier,
        default_buy_source_suffix=default_buy_source_suffix,
    )

    default_entry = dict(normalized[0])
    extra_groups = []
    for group in normalized[1:]:
        if not group.get('enabled', True):
            continue
        extra = {
            'game_type': group['game_type'],
            'multiplier': group['multiplier'],
            'source_suffix': group['source_suffix'],
        }
        if group.get('rules') is not None:
            extra['rules'] = group['rules']
        extra_groups.append(extra)

    return {
        'buy_enabled': bool(default_entry.get('enabled')),
        'buy_game_type': default_entry['game_type'],
        'buy_multiplier': default_entry['multiplier'],
        'buy_source_suffix': default_entry['source_suffix'],
        'extra_buy_groups': extra_groups,
        'buy_groups': normalized,
    }


def get_extra_buy_group_by_mode(mode, extra_buy_groups):
    game_type = get_extra_buy_game_type(mode)
    for group in extra_buy_groups:
        if int(group['game_type']) == game_type:
            return group
    return None


def get_buy_group_source_suffix(mode, *, buy_group_source_suffix, extra_buy_groups):
    """Return the formation table suffix configured for one buy-like mode."""
    mode = str(mode)
    if is_extra_buy_mode(mode):
        group = get_extra_buy_group_by_mode(mode, extra_buy_groups)
        if group:
            return group.get('source_suffix') or DEFAULT_BUY_GROUP_SOURCE_SUFFIX
    return buy_group_source_suffix or DEFAULT_BUY_GROUP_SOURCE_SUFFIX


def get_buy_group_game_type(mode, *, buy_group_game_type, extra_buy_groups):
    """Return the written game_type configured for one buy-like mode."""
    mode = str(mode)
    if is_extra_buy_mode(mode):
        return get_extra_buy_game_type(mode)
    return int(buy_group_game_type)


def get_buy_group_multiplier(mode, *, buy_group_multiplier, extra_buy_groups):
    """Return the RTP display multiplier configured for one buy-like mode."""
    mode = str(mode)
    if is_extra_buy_mode(mode):
        group = get_extra_buy_group_by_mode(mode, extra_buy_groups)
        if group:
            return float(group.get('multiplier', buy_group_multiplier))
    return float(buy_group_multiplier)


def normalize_extra_buy_groups(
    groups,
    *,
    group_modes,
    default_buy_rules,
    buy_group_mode,
    default_buy_game_type,
    default_source_suffix=DEFAULT_BUY_GROUP_SOURCE_SUFFIX,
):
    """Validate extra buy group config and return normalized rows."""
    if groups is None:
        return []
    if not isinstance(groups, list):
        raise ValueError("额外购买局配置必须是列表")

    parsed = []
    seen = {int(default_buy_game_type)}
    reserved = {int(mode) for mode in group_modes if str(mode) != str(buy_group_mode)}
    for idx, group in enumerate(groups, start=1):
        if not isinstance(group, dict):
            raise ValueError(f"额外购买局第 {idx} 行必须是对象")
        game_type = normalize_buy_game_type(group.get('game_type', ''), f"额外购买局第 {idx} 行类型")
        multiplier = normalize_buy_multiplier(group.get('multiplier', ''), f"额外购买局第 {idx} 行倍数")
        if game_type in reserved:
            raise ValueError(f"额外购买局第 {idx} 行类型 {game_type} 已是内置局类型")
        if game_type in seen:
            raise ValueError(f"购买局类型重复: {game_type}")
        seen.add(game_type)
        source_suffix = normalize_buy_source_suffix(
            group.get('source_suffix', group.get('formation_suffix', default_source_suffix)),
            f"额外购买局第 {idx} 行阵型表后缀",
        )
        rules = group.get('rules')
        if rules is None:
            rules = default_buy_rules
        rules = rule_config_state.normalize_group_weight_rule_list(f"额外购买局{game_type}", rules)
        parsed.append({
            'game_type': game_type,
            'multiplier': multiplier,
            'source_suffix': source_suffix,
            'rules': rules,
        })
    return parsed
