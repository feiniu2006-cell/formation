"""Settings data builders and file readers for the formation tool."""

import json
import re
import sys
from pathlib import Path

from formation_tool.core import buy_group_config
from formation_tool.core import formation_defaults

APP_SETTINGS_FILE_NAME = 'formation_tool_settings.json'
APP_SETTINGS_DIR_ENV = 'FORMATION_TOOL_SETTINGS_DIR'
CURRENT_SETTINGS_VERSION = 3
RULE_SETTINGS_SCHEMA_VERSION = 1


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


def build_last_settings_data(*, vendor, game_id, source_db, final_db, config_db):
    return {
        'version': CURRENT_SETTINGS_VERSION,
        'runtime': {
            'vendor': vendor,
            'game_id': game_id,
            'source_db': source_db,
            'final_db': final_db,
            'config_db': config_db,
        },
    }


def build_app_settings_data(
    *,
    runtime,
    trigger_weights,
    rebate_rules,
    sampling_append_mode,
    group_weight_rules,
    group_weight_options,
    direct_count_modes,
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
            'append_mode': bool(sampling_append_mode),
        },
        'group_weight_rules': group_weight_rules,
        'group_weight_options': group_weight_options,
        'direct_count_modes': sorted(direct_count_modes),
    }


def migrate_settings_data(data):
    """Upgrade older settings files to the current in-memory shape."""
    if not isinstance(data, dict):
        return data
    migrated = dict(data)
    group_options = dict(migrated.get('group_weight_options') or {})
    if group_options:
        group_options.setdefault('buy_game_type', formation_defaults.DEFAULT_BUY_GROUP_GAME_TYPE)
        group_options.setdefault('buy_source_suffix', formation_defaults.DEFAULT_BUY_GROUP_SOURCE_SUFFIX)
        group_options.setdefault('buy_multiplier', formation_defaults.DEFAULT_BUY_GROUP_MULTIPLIER)
        group_options.setdefault('buy_enabled', formation_defaults.DEFAULT_BUY_GROUP_ENABLED)
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
