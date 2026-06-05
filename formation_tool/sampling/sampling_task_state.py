"""Persistent state for resumable direct sampling tasks."""

import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from formation_tool.core import settings_logic

STATE_SCHEMA_VERSION = 1
STATE_DIR_NAME = 'formation_sampling_tasks'


def utc_now_text():
    return datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'


def get_state_base_dir():
    module_root = Path(__file__).resolve().parents[1]
    return settings_logic.get_app_settings_base_dir(
        module_file=module_root / 'process_formation_slots_way_combined.py',
        env=os.environ,
        frozen=getattr(sys, 'frozen', False),
        executable=getattr(sys, 'executable', None),
    ) / STATE_DIR_NAME


def _json_key(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def build_sampling_identity(names, sample_conditions, append_mode):
    return {
        'source_db_name': names.get('source_db_name'),
        'source_table_name': names.get('source_table_name'),
        'final_db_name': names.get('final_db_name'),
        'final_table_name': names.get('final_table_name'),
        'config_db_name': names.get('config_db_name'),
        'rebate_config_table_name': names.get('rebate_config_table_name'),
        'where_clause': sample_conditions.get('where_clause'),
        'random_seed': sample_conditions.get('random_seed'),
        'append_mode': bool(append_mode),
    }


def build_state_path(identity):
    digest = hashlib.sha1(_json_key(identity).encode('utf-8')).hexdigest()[:16]
    table = settings_logic.safe_settings_name(identity.get('final_table_name') or 'sampling')
    db = settings_logic.safe_settings_name(identity.get('final_db_name') or 'db')
    return get_state_base_dir() / f"{db}_{table}_{digest}.json"


def _write_state(path, state):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + '.tmp')
    tmp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp_path, path)


def load_state(identity):
    path = build_state_path(identity)
    if not path.exists():
        return None
    try:
        state = json.loads(path.read_text(encoding='utf-8-sig'))
    except Exception:
        return None
    if state.get('schema_version') != STATE_SCHEMA_VERSION:
        return None
    if state.get('identity') != identity:
        return None
    state['_path'] = str(path)
    return state


def new_state(identity, staging_state, *, config_row_count):
    now = utc_now_text()
    path = build_state_path(identity)
    return {
        'schema_version': STATE_SCHEMA_VERSION,
        'status': 'running',
        'identity': identity,
        'staging': {
            'staging_table_name': staging_state.get('staging_table_name'),
            'base_existing_count': int(staging_state.get('base_existing_count') or 0),
            'next_id': int((staging_state.get('next_id_state') or [1])[0]),
            'id_mapping': {
                str(k): int(v)
                for k, v in dict(staging_state.get('id_mapping') or {}).items()
            },
        },
        'totals': {
            'sampled_count': 0,
            'remapped_id_count': 0,
            'remapped_row_count': 0,
        },
        'completed_rebates': [],
        'completed_rows': [],
        'config_row_count': int(config_row_count or 0),
        'created_at': now,
        'updated_at': now,
        '_path': str(path),
    }


def save_state(state):
    path = state.get('_path') or str(build_state_path(state['identity']))
    data = {key: value for key, value in state.items() if not key.startswith('_')}
    data['updated_at'] = utc_now_text()
    state['updated_at'] = data['updated_at']
    _write_state(path, data)
    state['_path'] = str(path)
    return state


def update_staging_snapshot(state, staging_state):
    staging = state.setdefault('staging', {})
    staging['staging_table_name'] = staging_state.get('staging_table_name')
    staging['base_existing_count'] = int(staging_state.get('base_existing_count') or 0)
    staging['next_id'] = int((staging_state.get('next_id_state') or [1])[0])
    staging['id_mapping'] = {
        str(k): int(v)
        for k, v in dict(staging_state.get('id_mapping') or {}).items()
    }


def completed_rebate_set(state):
    return {int(value) for value in state.get('completed_rebates') or []}


def totals_from_state(state):
    totals = dict(state.get('totals') or {})
    return {
        'sampled_count': int(totals.get('sampled_count') or 0),
        'remapped_id_count': int(totals.get('remapped_id_count') or 0),
        'remapped_row_count': int(totals.get('remapped_row_count') or 0),
    }


def record_completed_rebate(
    state,
    staging_state,
    *,
    rebate,
    sample_size,
    sampled_count,
    changed_pair_count,
    changed_row_count,
):
    rebate = int(rebate)
    completed = completed_rebate_set(state)
    if rebate not in completed:
        state.setdefault('completed_rebates', []).append(rebate)
        state.setdefault('completed_rows', []).append({
            'rebate': rebate,
            'sample_size': int(sample_size or 0),
            'sampled_count': int(sampled_count or 0),
            'remapped_id_count': int(changed_pair_count or 0),
            'remapped_row_count': int(changed_row_count or 0),
        })
    totals = totals_from_state(state)
    totals['sampled_count'] += int(sampled_count or 0)
    totals['remapped_id_count'] += int(changed_pair_count or 0)
    totals['remapped_row_count'] += int(changed_row_count or 0)
    state['totals'] = totals
    update_staging_snapshot(state, staging_state)
    state['status'] = 'running'
    save_state(state)


def mark_failed(state, error):
    if not state:
        return None
    state['status'] = 'failed'
    state['last_error'] = str(error)
    return save_state(state)


def mark_completed(state, *, success):
    if not state:
        return None
    state['status'] = 'completed' if success else 'completed_no_data'
    state.pop('last_error', None)
    return save_state(state)


def build_staging_state_from_saved(state):
    staging = state.get('staging') or {}
    return {
        'staging_table_name': staging.get('staging_table_name'),
        'base_existing_count': int(staging.get('base_existing_count') or 0),
        'id_mapping': {
            int(k): int(v)
            for k, v in dict(staging.get('id_mapping') or {}).items()
        },
        'next_id_state': [int(staging.get('next_id') or 1)],
    }
