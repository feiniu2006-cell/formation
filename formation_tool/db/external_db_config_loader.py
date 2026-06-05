"""Runtime loader for external db_config.json overrides."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from formation_tool.db import db_config_utils


def external_config_candidates(module_file, *, config_name='db_config.json', cwd=None):
    """Return db_config.json lookup paths in runtime priority order."""
    candidates = []
    if getattr(sys, 'frozen', False):
        candidates.append(Path(sys.executable).resolve().with_name(config_name))
    try:
        candidates.append(Path(module_file).resolve().parent.parent / config_name)
    except Exception:
        pass
    candidates.append((Path.cwd() if cwd is None else Path(cwd)) / config_name)

    unique = []
    seen = set()
    for path in candidates:
        key = str(path).lower()
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def extract_external_db_configs(data):
    return db_config_utils.extract_database_configs(data, "db_config.json")


def parse_int_field(value, field_label, *, min_value=None, max_value=None):
    return db_config_utils.parse_int_field(
        value,
        field_label,
        min_value=min_value,
        max_value=max_value,
    )


def normalize_external_db_configs(data, current_database_configs):
    return db_config_utils.normalize_database_configs(
        data,
        current_database_configs,
        source_label="db_config.json",
    )


def load_external_database_config(
    current_database_configs,
    current_max_retries,
    current_retry_delay,
    *,
    module_file,
):
    """Load the first external db_config.json override, preserving defaults on failure."""
    for path in external_config_candidates(module_file):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding='utf-8-sig'))
            normalized_configs = normalize_external_db_configs(data, current_database_configs)
            max_db_retries, db_retry_delay = db_config_utils.normalize_runtime_options(
                data,
                current_max_retries=current_max_retries,
                current_retry_delay=current_retry_delay,
                source_label=str(path),
            )
            return SimpleNamespace(
                database_configs=normalized_configs,
                max_db_retries=max_db_retries,
                db_retry_delay=db_retry_delay,
                source=str(path),
                error=None,
            )
        except Exception as exc:
            return SimpleNamespace(
                database_configs=current_database_configs,
                max_db_retries=current_max_retries,
                db_retry_delay=current_retry_delay,
                source=None,
                error=f"{path}: {exc}",
            )

    return SimpleNamespace(
        database_configs=current_database_configs,
        max_db_retries=current_max_retries,
        db_retry_delay=current_retry_delay,
        source=None,
        error=None,
    )
