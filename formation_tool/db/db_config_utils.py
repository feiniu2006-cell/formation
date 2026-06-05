"""Shared helpers for external db_config.json parsing and validation."""

DB_CONFIG_REQUIRED_KEYS = ('host', 'port', 'user', 'password', 'database')
DB_CONFIG_NON_EMPTY_STRING_KEYS = ('host', 'user', 'database')
DB_CONFIG_METADATA_KEYS = {'DATABASE_CONFIGS', 'MAX_DB_RETRIES', 'DB_RETRY_DELAY'}


def extract_database_configs(data, source_label="db_config.json"):
    """Extract DATABASE_CONFIGS from full or shorthand db_config.json shapes."""
    if not isinstance(data, dict):
        raise ValueError(f"{source_label} must be a JSON object")
    configs = data.get('DATABASE_CONFIGS')
    if configs is None:
        configs = {
            key: value
            for key, value in data.items()
            if key not in DB_CONFIG_METADATA_KEYS and isinstance(value, dict)
        }
    return configs


def parse_int_field(value, field_label, *, min_value=None, max_value=None):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_label} must be an integer") from None
    if min_value is not None and parsed < min_value:
        raise ValueError(f"{field_label} must be >= {min_value}")
    if max_value is not None and parsed > max_value:
        raise ValueError(f"{field_label} must be <= {max_value}")
    return parsed


def validate_database_configs(configs, source_label="db_config.json", *, base_configs=None):
    """Validate the common database config shape used by db_config.py/json."""
    if not isinstance(configs, dict) or not configs:
        raise ValueError(f"{source_label} DATABASE_CONFIGS is empty or invalid")

    base_configs = base_configs or {}
    errors = []
    for db_name, cfg in configs.items():
        label = f"{source_label} {db_name}"
        if not isinstance(db_name, str) or not db_name.strip():
            errors.append(f"{source_label} has an empty database alias")
            continue
        if not isinstance(cfg, dict):
            errors.append(f"{label} must be a config object")
            continue

        normalized = dict(base_configs.get(db_name, {}))
        normalized.update(cfg)
        missing_keys = [key for key in DB_CONFIG_REQUIRED_KEYS if key not in normalized]
        if missing_keys:
            errors.append(f"{label} missing keys: {missing_keys}")
            continue

        for key in DB_CONFIG_NON_EMPTY_STRING_KEYS:
            if not isinstance(normalized.get(key), str) or not normalized[key].strip():
                errors.append(f"{label}.{key} must be a non-empty string")
        if not isinstance(normalized.get('password'), str):
            errors.append(f"{label}.password must be a string")
        try:
            parse_int_field(normalized.get('port'), f"{label}.port", min_value=1, max_value=65535)
        except ValueError as exc:
            errors.append(str(exc))

    if errors:
        raise ValueError("; ".join(errors))


def normalize_database_configs(data, base_configs, source_label="db_config.json"):
    """Return merged database configs after validating an external JSON config."""
    configs = extract_database_configs(data, source_label)
    validate_database_configs(configs, source_label, base_configs=base_configs)

    merged = dict(base_configs)
    for db_name, cfg in configs.items():
        normalized = dict(merged.get(db_name, {}))
        normalized.update(cfg)
        normalized['port'] = parse_int_field(
            normalized.get('port'),
            f"{source_label} {db_name}.port",
            min_value=1,
            max_value=65535,
        )
        merged[db_name] = normalized
    return merged


def validate_db_runtime_options(data, source_label="db_config.json"):
    if not isinstance(data, dict):
        return
    if 'MAX_DB_RETRIES' in data:
        parse_int_field(data['MAX_DB_RETRIES'], f"{source_label}.MAX_DB_RETRIES", min_value=1)
    if 'DB_RETRY_DELAY' in data:
        parse_int_field(data['DB_RETRY_DELAY'], f"{source_label}.DB_RETRY_DELAY", min_value=0)


def normalize_runtime_options(
    data,
    *,
    current_max_retries,
    current_retry_delay,
    source_label="db_config.json",
):
    """Return runtime retry options from external JSON, falling back to current values."""
    if not isinstance(data, dict):
        return current_max_retries, current_retry_delay

    max_retries = current_max_retries
    retry_delay = current_retry_delay
    if 'MAX_DB_RETRIES' in data:
        max_retries = parse_int_field(
            data['MAX_DB_RETRIES'],
            f"{source_label}.MAX_DB_RETRIES",
            min_value=1,
        )
    if 'DB_RETRY_DELAY' in data:
        retry_delay = parse_int_field(
            data['DB_RETRY_DELAY'],
            f"{source_label}.DB_RETRY_DELAY",
            min_value=0,
        )
    return max_retries, retry_delay
