"""Editable rule validation and state helper functions."""

import re
from numbers import Integral


REBATE_RULE_FIELDS = (
    'rebate',
    'rebate_min',
    'rebate_max',
    'count',
    'rebate_limit_min',
    'rebate_limit_max',
    'smooth_buckets',
    'min_total',
)
REBATE_RULE_FIELD_LABELS = {
    'rebate': '精确 rebate',
    'rebate_min': '最小 rebate',
    'rebate_max': '最大 rebate',
    'count': '采样数',
    'rebate_limit_min': '数量下限',
    'rebate_limit_max': '数量上限',
    'smooth_buckets': '平滑分桶',
    'min_total': '最小数据量',
}
GROUP_WEIGHT_RULE_FIELDS = ('rebate_min', 'weight')
GROUP_WEIGHT_RULE_FIELD_LABELS = {
    'rebate_min': 'rebate 下限',
    'weight': '权重',
}
LEGACY_GROUP_WEIGHT_RULE_ALIASES = {
    '99': 'buy',
    '98': 'ex_buy',
}


def normalize_group_weight_rule_keys(rules):
    """Return group_weight rules with legacy buy keys mapped to semantic keys."""
    if not isinstance(rules, dict):
        return rules
    normalized = {}
    for key, value in rules.items():
        key_text = str(key)
        mode = LEGACY_GROUP_WEIGHT_RULE_ALIASES.get(key_text, key_text)
        if mode in normalized and key_text != mode:
            continue
        normalized[mode] = value
    return normalized


def clone_rebate_rules(rules, sample_modes):
    """Return an editable copy of rebate rules for all sampling modes."""
    return {
        mode: [dict(rule) for rule in rules.get(mode, [])]
        for mode in sample_modes
    }


def clone_group_weight_rules(rules, group_modes):
    """Return an editable copy of group_weight rules for all supported modes."""
    rules = normalize_group_weight_rule_keys(rules)
    return {
        mode: [dict(rule) for rule in rules.get(mode, [])]
        for mode in group_modes
    }


def clone_extra_buy_groups(groups):
    """Return an editable copy of extra buy group rows."""
    cloned = []
    for group in groups or []:
        item = dict(group)
        if 'rules' in item and item['rules'] is not None:
            item['rules'] = [dict(rule) for rule in item['rules']]
        cloned.append(item)
    return cloned


def normalize_formation_suffix(value, label, *, default=None):
    """Validate a formation table suffix entered in the UI/settings file."""
    text = str(default if value is None or str(value).strip() == "" else value).strip()
    if not text:
        raise ValueError(f"{label}不能为空")
    if not re.fullmatch(r'[0-9A-Za-z_]+', text):
        raise ValueError(f"{label}只能包含英文字母、数字和下划线: {text}")
    return text


def collect_unknown_config_modes(rules, allowed_modes, label):
    """Return warning messages for unknown/legacy modes in a config file."""
    if not isinstance(rules, dict):
        return []
    allowed = {str(mode) for mode in allowed_modes}
    unknown = sorted(str(mode) for mode in rules if str(mode) not in allowed)
    if not unknown:
        return []
    return [f"{label} 包含未知/旧模式，已忽略: {', '.join(unknown)}"]


def require_int(value, label, *, minimum=0):
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise ValueError(f"{label} 必须是整数")
    value = int(value)
    if value < minimum:
        raise ValueError(f"{label} 不能小于 {minimum}")
    return value


def parse_non_negative_int_text(text, label):
    text = str(text).strip()
    if not text:
        raise ValueError(f"{label}不能为空")
    try:
        value = int(text)
    except ValueError:
        try:
            number = float(text)
        except ValueError:
            raise ValueError(f"{label} 必须是整数: {text}") from None
        if not number.is_integer():
            raise ValueError(f"{label} 必须是整数: {text}")
        value = int(number)
    if value < 0:
        raise ValueError(f"{label} 不能小于 0: {value}")
    return value


def parse_positive_float_text(text, label):
    text = str(text).strip()
    if not text:
        raise ValueError(f"{label}不能为空")
    try:
        value = float(text)
    except ValueError:
        raise ValueError(f"{label} 必须是数字: {text}") from None
    if value <= 0:
        raise ValueError(f"{label} 必须大于 0: {value}")
    return value


def validate_rebate_rules(
    rules,
    *,
    sample_modes,
    default_rules,
    fill_missing=False,
    warn_unknown=False,
    add_warning=None,
):
    """Validate rebate sampling rules and return normalized rules."""
    if not isinstance(rules, dict):
        raise ValueError("REBATE_RULES 必须是字典")

    unknown_warnings = collect_unknown_config_modes(rules, sample_modes, "REBATE_RULES")
    if unknown_warnings and not warn_unknown:
        raise ValueError(unknown_warnings[0])
    for warning in unknown_warnings:
        if add_warning:
            add_warning(warning)

    normalized_input = {str(key): value for key, value in rules.items()}
    for mode in sample_modes:
        if mode not in normalized_input:
            if not fill_missing:
                raise ValueError(f"缺少模式 {mode} 的采样规则")
            normalized_input[mode] = [dict(rule) for rule in default_rules.get(mode, [])]
        if not isinstance(normalized_input[mode], list):
            raise ValueError(f"模式 {mode} 的采样规则必须是列表")

    allowed_keys = set(REBATE_RULE_FIELDS)
    for mode in sample_modes:
        mode_rules = normalized_input[mode]
        for idx, rule in enumerate(mode_rules, start=1):
            prefix = f"模式 {mode} 第 {idx} 条规则"
            if not isinstance(rule, dict):
                raise ValueError(f"{prefix} 必须是字典")
            unknown_keys = set(rule) - allowed_keys
            if unknown_keys:
                raise ValueError(f"{prefix} 包含未知字段: {sorted(unknown_keys)}")
            if 'count' not in rule:
                raise ValueError(f"{prefix} 缺少 count")
            require_int(rule['count'], f"{prefix}.count")

            has_exact = 'rebate' in rule
            has_range = 'rebate_min' in rule or 'rebate_max' in rule
            if has_exact and has_range:
                raise ValueError(f"{prefix} 不能同时配置 rebate 和 rebate_min/rebate_max")
            if has_exact:
                require_int(rule['rebate'], f"{prefix}.rebate")
            else:
                if 'rebate_min' not in rule or 'rebate_max' not in rule:
                    raise ValueError(f"{prefix} 必须配置 rebate，或同时配置 rebate_min/rebate_max")
                rebate_min = require_int(rule['rebate_min'], f"{prefix}.rebate_min")
                rebate_max = require_int(rule['rebate_max'], f"{prefix}.rebate_max")
                if rebate_min > rebate_max:
                    raise ValueError(f"{prefix}.rebate_min 不能大于 rebate_max")

            if 'rebate_limit_min' in rule:
                require_int(rule['rebate_limit_min'], f"{prefix}.rebate_limit_min")
            if 'rebate_limit_max' in rule:
                require_int(rule['rebate_limit_max'], f"{prefix}.rebate_limit_max")
            if 'rebate_limit_min' in rule and 'rebate_limit_max' in rule:
                if rule['rebate_limit_min'] > rule['rebate_limit_max']:
                    raise ValueError(f"{prefix}.rebate_limit_min 不能大于 rebate_limit_max")
            if 'smooth_buckets' in rule:
                require_int(rule['smooth_buckets'], f"{prefix}.smooth_buckets", minimum=1)
            if 'min_total' in rule:
                require_int(rule['min_total'], f"{prefix}.min_total")

    return {mode: normalized_input[mode] for mode in sample_modes}


def normalize_group_weight_rule_list(mode_name, mode_rules):
    if not isinstance(mode_rules, list):
        raise ValueError(f"{mode_name} 的 group_weight 权重规则必须是列表")
    parsed_rules = []
    seen_rebate_min = set()
    for idx, rule in enumerate(mode_rules, start=1):
        prefix = f"{mode_name}第 {idx} 行"
        if not isinstance(rule, dict):
            raise ValueError(f"{prefix} 必须是字典")
        unknown_keys = set(rule) - set(GROUP_WEIGHT_RULE_FIELDS)
        if unknown_keys:
            raise ValueError(f"{prefix} 包含未知字段: {sorted(unknown_keys)}")
        for field in GROUP_WEIGHT_RULE_FIELDS:
            if field not in rule:
                raise ValueError(f"{prefix} 缺少 {GROUP_WEIGHT_RULE_FIELD_LABELS[field]}")
        rebate_min = require_int(rule['rebate_min'], f"{prefix}.rebate_min")
        weight = require_int(rule['weight'], f"{prefix}.weight")
        if rebate_min in seen_rebate_min:
            raise ValueError(f"{prefix} rebate 下限重复: {rebate_min}")
        seen_rebate_min.add(rebate_min)
        parsed_rules.append({'rebate_min': rebate_min, 'weight': weight})
    if not parsed_rules:
        raise ValueError(f"{mode_name} 至少需要一条 group_weight 权重规则")
    return sorted(parsed_rules, key=lambda item: item['rebate_min'])


def validate_group_weight_rules(
    rules,
    *,
    group_modes,
    game_type_names,
    default_rules,
    fill_missing=False,
    warn_unknown=False,
    add_warning=None,
):
    """Validate group_weight interval rules and return normalized rules."""
    if not isinstance(rules, dict):
        raise ValueError("group_weight 权重规则必须是字典")

    normalized_input = normalize_group_weight_rule_keys(rules)
    unknown_warnings = collect_unknown_config_modes(normalized_input, group_modes, "GROUP_WEIGHT_RULES")
    if unknown_warnings and not warn_unknown:
        raise ValueError(unknown_warnings[0])
    for warning in unknown_warnings:
        if add_warning:
            add_warning(warning)

    normalized = {}
    for mode in group_modes:
        mode_name = game_type_names.get(mode, mode)
        if mode not in normalized_input:
            if not fill_missing:
                raise ValueError(f"缺少 {mode_name} 的 group_weight 权重规则")
            mode_rules = default_rules.get(mode)
            if mode_rules is None:
                raise ValueError(f"缺少 {mode_name} 的 group_weight 权重规则")
        else:
            mode_rules = normalized_input[mode]
        normalized[mode] = normalize_group_weight_rule_list(mode_name, mode_rules)
    return normalized


def normalize_extra_buy_groups(
    groups,
    *,
    group_modes,
    default_buy_rules,
    buy_group_mode,
    default_buy_game_type=99,
    default_source_suffix='free_formation',
    reserved_game_types=None,
):
    """Validate extra buy group config and return normalized rows."""
    from formation_tool.core import buy_group_config

    return buy_group_config.normalize_extra_buy_groups(
        groups,
        group_modes=group_modes,
        default_buy_rules=default_buy_rules,
        buy_group_mode=buy_group_mode,
        default_buy_game_type=default_buy_game_type,
        default_source_suffix=default_source_suffix,
        reserved_game_types=reserved_game_types,
    )
