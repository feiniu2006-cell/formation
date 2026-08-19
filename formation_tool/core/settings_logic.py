"""Settings data builders and file readers for the formation tool."""

import json
import re
import sys
from pathlib import Path

from formation_tool.core import buy_group_config
from formation_tool.core import formation_defaults
from formation_tool.core import formation_modes

APP_SETTINGS_FILE_NAME = 'formation_tool_settings.json'
APP_SETTINGS_DIR_ENV = 'FORMATION_TOOL_SETTINGS_DIR'
CURRENT_SETTINGS_VERSION = 7
RULE_SETTINGS_SCHEMA_VERSION = 1


def filter_group_weight_rules_by_modes(rules, configured_modes):
    """Keep only base group_weight rule modes configured in the dialog."""
    configured = {str(mode) for mode in configured_modes or ()}
    return {
        str(mode): mode_rules
        for mode, mode_rules in (rules or {}).items()
        if str(mode) in configured
    }


def filter_group_weight_group_rules_by_modes(group_rules, configured_modes):
    """Filter every group-suffix rule map to configured group_weight modes."""
    configured = {str(mode) for mode in configured_modes or ()}
    return {
        str(group_suffix): {
            str(mode): mode_rules
            for mode, mode_rules in rules_by_mode.items()
            if str(mode) in configured
        }
        for group_suffix, rules_by_mode in (group_rules or {}).items()
        if isinstance(rules_by_mode, dict)
        and any(str(mode) in configured for mode in rules_by_mode)
    }


def get_app_settings_base_dir(*, module_file, env=None, frozen=None, executable=None, cwd=None):
    """Return the directory used by source and packaged runs for settings files."""
    env = env or {}
    override = env.get(APP_SETTINGS_DIR_ENV)
    if override:
        return Path(override).expanduser().resolve()

    is_frozen = frozen if frozen is not None else getattr(sys, 'frozen', False)
    if is_frozen:
        exe_path = Path(executable or sys.executable).resolve()
        exe_dir = exe_path.parent
        source_dir = exe_dir.parent
        if (
            exe_dir.name.lower() in {'dist_encrypted', 'dist'}
            and (source_dir / 'process_formation_slots_way_combined.py').is_file()
        ):
            return source_dir
        return exe_dir

    try:
        return Path(module_file).resolve().parent
    except Exception:
        return Path.cwd() if cwd is None else Path(cwd)


def get_app_settings_path(*, module_file, env=None):
    """Return the last-selection settings file path."""
    return get_app_settings_base_dir(module_file=module_file, env=env) / APP_SETTINGS_FILE_NAME


def safe_settings_name(value):
    text = str(value).strip()
    return re.sub(r'[^0-9A-Za-z_.-]+', '_', text) or 'default'


def get_app_profile_settings_path(vendor, game_id, *, module_file, env=None):
    """Return a room-specific settings path, or the last-selection path when incomplete."""
    vendor = str(vendor).strip()
    game_id = str(game_id).strip()
    if not vendor or not game_id:
        return get_app_settings_path(module_file=module_file, env=env)
    filename = f"{safe_settings_name(vendor)}_{safe_settings_name(game_id)}.json"
    return get_app_settings_base_dir(module_file=module_file, env=env) / 'formation_tool_settings' / filename


def build_last_settings_data(
    *,
    vendor,
    game_id,
    source_db,
    final_db,
    config_db,
    sampling_temp_db=None,
    sampling_increment_db=None,
    sampling_use_temp_db=False,
    sampling_auto_sync_to_target=formation_defaults.DEFAULT_SAMPLING_AUTO_SYNC_TO_TARGET,
):
    return {
        'version': CURRENT_SETTINGS_VERSION,
        'runtime': {
            'vendor': vendor,
            'game_id': game_id,
            'source_db': source_db,
            'final_db': final_db,
            'config_db': config_db,
            'sampling_temp_db': sampling_temp_db or formation_defaults.DEFAULT_SAMPLING_TEMP_DB,
            'sampling_increment_db': sampling_increment_db or formation_defaults.DEFAULT_SAMPLING_INCREMENT_DB,
            'sampling_use_temp_db': True,
            'sampling_auto_sync_to_target': bool(sampling_auto_sync_to_target),
        },
    }


def build_app_settings_data(
    *,
    runtime,
    trigger_weights,
    rebate_rules,
    sampling_append_mode,
    sampling_detailed_log,
    sampling_use_temp_db=formation_defaults.DEFAULT_SAMPLING_USE_TEMP_DB,
    sampling_temp_db=None,
    sampling_increment_db=None,
    sampling_auto_sync_to_target=formation_defaults.DEFAULT_SAMPLING_AUTO_SYNC_TO_TARGET,
    group_weight_rules,
    group_weight_group_rules=None,
    group_weight_options,
    demo_group_weight_rules=None,
    demo_group_weight_options=None,
    direct_count_modes,
    direct_count_tiers,
):
    group_weight_options = dict(group_weight_options)
    group_weight_options['buy_groups'] = buy_group_config.build_buy_groups_from_legacy(
        buy_enabled=group_weight_options.get('buy_enabled', formation_defaults.DEFAULT_BUY_GROUP_ENABLED),
        buy_game_type=group_weight_options.get('buy_game_type', formation_defaults.DEFAULT_BUY_GROUP_GAME_TYPE),
        buy_multiplier=group_weight_options.get('buy_multiplier', formation_defaults.DEFAULT_BUY_GROUP_MULTIPLIER),
        buy_source_suffix=group_weight_options.get(
            'buy_source_suffix',
            formation_defaults.DEFAULT_BUY_GROUP_SOURCE_SUFFIX,
        ),
        extra_buy_groups=group_weight_options.get('extra_buy_groups', []),
    )
    return {
        'version': CURRENT_SETTINGS_VERSION,
        'runtime': dict(runtime),
        'trigger_weights': dict(trigger_weights),
        'rebate_rules': rebate_rules,
        'sampling_options': {
            'detailed_log': bool(sampling_detailed_log),
            'use_temp_db': True,
            'temp_db': sampling_temp_db or formation_defaults.DEFAULT_SAMPLING_TEMP_DB,
            'increment_db': sampling_increment_db or formation_defaults.DEFAULT_SAMPLING_INCREMENT_DB,
            'auto_sync_to_target': bool(sampling_auto_sync_to_target),
        },
        'group_weight_rules': group_weight_rules,
        'group_weight_group_rules': group_weight_group_rules or {},
        'group_weight_options': group_weight_options,
        'demo_group_weight_rules': demo_group_weight_rules or {},
        'demo_group_weight_options': demo_group_weight_options or {},
        'direct_count_modes': sorted(direct_count_modes),
        'direct_count_tiers': [dict(rule) for rule in direct_count_tiers],
    }


def migrate_settings_data(data):
    """Upgrade older settings files to the current in-memory shape."""
    if not isinstance(data, dict):
        return data
    migrated = dict(data)
    try:
        source_version = int(migrated.get('version', 0))
    except (TypeError, ValueError):
        source_version = 0
    shared_group_weight_rules = migrated.get('group_weight_rules')
    if isinstance(shared_group_weight_rules, dict):
        raw_group_rules = migrated.get('group_weight_group_rules')
        if raw_group_rules in (None, {}) or isinstance(raw_group_rules, dict):
            group_rules_by_suffix = formation_defaults.clone_group_rule_map(
                raw_group_rules or {}
            )
            group_rules_by_suffix.setdefault(
                '0',
                formation_defaults.clone_rule_map(shared_group_weight_rules),
            )
            if source_version < 7:
                default_group_rules = group_rules_by_suffix['0']
                for group_suffix in formation_defaults.DEFAULT_WEIGHT_GROUP_SUFFIXES[1:]:
                    group_rules_by_suffix.setdefault(
                        str(group_suffix),
                        formation_defaults.clone_rule_map(default_group_rules),
                    )
            migrated['group_weight_group_rules'] = group_rules_by_suffix
    if not isinstance(migrated.get('demo_group_weight_rules'), dict):
        migrated['demo_group_weight_rules'] = formation_defaults.clone_rule_map(
            formation_defaults.DEFAULT_DEMO_GROUP_WEIGHT_RULES
        )
    demo_options = dict(migrated.get('demo_group_weight_options') or {})
    demo_options.setdefault(
        'target_rtps',
        formation_defaults.clone_demo_group_weight_target_rtps(),
    )
    demo_options.setdefault(
        'zero_rebate_inference_modes',
        list(formation_defaults.DEFAULT_DEMO_ZERO_REBATE_INFERENCE_MODES),
    )
    migrated['demo_group_weight_options'] = demo_options
    sampling_options = dict(migrated.get('sampling_options') or {})
    if sampling_options:
        sampling_options.setdefault(
            'detailed_log',
            formation_defaults.DEFAULT_SAMPLING_DETAILED_LOG,
        )
        sampling_options.setdefault(
            'use_temp_db',
            True,
        )
        sampling_options.setdefault(
            'temp_db',
            (migrated.get('runtime') or {}).get('sampling_temp_db')
            or formation_defaults.DEFAULT_SAMPLING_TEMP_DB,
        )
        sampling_options.setdefault(
            'increment_db',
            (migrated.get('runtime') or {}).get('sampling_increment_db')
            or formation_defaults.DEFAULT_SAMPLING_INCREMENT_DB,
        )
        sampling_options.setdefault(
            'auto_sync_to_target',
            (migrated.get('runtime') or {}).get('sampling_auto_sync_to_target')
            or formation_defaults.DEFAULT_SAMPLING_AUTO_SYNC_TO_TARGET,
        )
        sampling_options['use_temp_db'] = True
        migrated['sampling_options'] = sampling_options
    group_options = dict(migrated.get('group_weight_options') or {})
    if group_options:
        group_options.setdefault('buy_game_type', formation_defaults.DEFAULT_BUY_GROUP_GAME_TYPE)
        group_options.setdefault('buy_source_suffix', formation_defaults.DEFAULT_BUY_GROUP_SOURCE_SUFFIX)
        group_options.setdefault('buy_multiplier', formation_defaults.DEFAULT_BUY_GROUP_MULTIPLIER)
        group_options.setdefault('buy_enabled', formation_defaults.DEFAULT_BUY_GROUP_ENABLED)
        group_options.setdefault('ex_buy_game_type', formation_defaults.DEFAULT_EX_BUY_GROUP_GAME_TYPE)
        group_options.setdefault('ex_buy_source_suffix', formation_defaults.DEFAULT_EX_BUY_GROUP_SOURCE_SUFFIX)
        group_options.setdefault('ex_source_suffixes', {})
        group_options.setdefault('ex_group_target_rtps', {})
        group_options.setdefault('extra_weight_groups', [])
        if source_version < 7:
            trigger_weights = dict(migrated.get('trigger_weights') or {})
            editable_weight_groups = []
            existing_suffixes = set()
            for group in group_options.get('extra_weight_groups') or []:
                if not isinstance(group, dict):
                    editable_weight_groups.append(group)
                    continue
                item = dict(group)
                raw_suffix = group.get('group_suffix', group.get('group_id'))
                try:
                    group_suffix = int(raw_suffix)
                except (TypeError, ValueError):
                    editable_weight_groups.append(item)
                    continue
                if 'group_suffix' not in group and abs(group_suffix) >= 10:
                    group_suffix %= 10
                item['group_suffix'] = group_suffix
                item.pop('group_id', None)
                existing_suffixes.add(group_suffix)
                special_weight = group.get('special_weight')
                free_weight = group.get('free_weight')
                if special_weight not in (None, ''):
                    trigger_weights.setdefault(f'special_{group_suffix}', special_weight)
                if free_weight not in (None, ''):
                    trigger_weights.setdefault(f'free_{group_suffix}', free_weight)
                editable_weight_groups.append(item)
            for default_group in formation_defaults.clone_extra_weight_groups():
                group_suffix = int(default_group['group_suffix'])
                if group_suffix in existing_suffixes:
                    continue
                editable_weight_groups.append({
                    'group_suffix': group_suffix,
                    'special_weight': trigger_weights.get(
                        f'special_{group_suffix}',
                        default_group['special_weight'],
                    ),
                    'free_weight': trigger_weights.get(
                        f'free_{group_suffix}',
                        default_group['free_weight'],
                    ),
                })
            editable_weight_groups.sort(
                key=lambda group: (
                    int(group.get('group_suffix', 99))
                    if isinstance(group, dict) and str(group.get('group_suffix', '')).isdigit()
                    else 99
                )
            )
            group_options['extra_weight_groups'] = editable_weight_groups
            migrated['trigger_weights'] = trigger_weights
        group_options.setdefault(
            'zero_rebate_inference_modes',
            list(formation_modes.DEFAULT_ZERO_REBATE_INFERENCE_MODES),
        )
        group_options.setdefault(
            'independent_rtp_modes',
            list(formation_modes.DEFAULT_INDEPENDENT_RTP_MODES),
        )
        if group_options.get('buy_groups'):
            split = buy_group_config.split_buy_groups_to_legacy(
                group_options.get('buy_groups'),
                default_buy_enabled=group_options['buy_enabled'],
                default_buy_game_type=group_options['buy_game_type'],
                default_buy_multiplier=group_options['buy_multiplier'],
                default_buy_source_suffix=group_options['buy_source_suffix'],
            )
            group_options.update(split)
        extra_buy_groups = []
        for group in group_options.get('extra_buy_groups') or []:
            if isinstance(group, dict):
                item = dict(group)
                item.setdefault('source_suffix', group_options['buy_source_suffix'])
                extra_buy_groups.append(item)
            else:
                extra_buy_groups.append(group)
        group_options['extra_buy_groups'] = extra_buy_groups
        group_options['buy_groups'] = buy_group_config.build_buy_groups_from_legacy(
            buy_enabled=group_options.get('buy_enabled', formation_defaults.DEFAULT_BUY_GROUP_ENABLED),
            buy_game_type=group_options.get('buy_game_type', formation_defaults.DEFAULT_BUY_GROUP_GAME_TYPE),
            buy_multiplier=group_options.get('buy_multiplier', formation_defaults.DEFAULT_BUY_GROUP_MULTIPLIER),
            buy_source_suffix=group_options.get(
                'buy_source_suffix',
                formation_defaults.DEFAULT_BUY_GROUP_SOURCE_SUFFIX,
            ),
            extra_buy_groups=group_options.get('extra_buy_groups', []),
        )
        migrated['group_weight_options'] = group_options
    migrated['version'] = CURRENT_SETTINGS_VERSION
    return migrated


def read_settings_file(path):
    return migrate_settings_data(json.loads(Path(path).read_text(encoding='utf-8-sig')))


def get_runtime_settings(data):
    if not isinstance(data, dict):
        raise ValueError("配置文件必须是 JSON 对象")
    runtime = data.get('runtime', {})
    return runtime if isinstance(runtime, dict) else {}
