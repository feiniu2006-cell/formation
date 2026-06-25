"""Helpers for syncing main-script runtime context into split worker modules."""
from functools import wraps

SAMPLING_CORE_CONTEXT_KEYS = (
    'DATABASE_CONFIGS',
    'MAX_DB_RETRIES',
    'DB_RETRY_DELAY',
    'SAMPLE_ID_FETCH_CHUNK_SIZE',
    'SAMPLING_APPEND_MODE',
    'SAMPLING_DETAILED_LOG',
    'SAMPLING_USE_TEMP_DB',
    'SAMPLING_TEMP_DB',
    'check_cancelled',
    'chunked',
    'close_safely',
    'connect_by_table',
    'count_table_rows',
    'copy_table_rows',
    'drop_table_if_exists',
    'ensure_database_connection',
    'get_db_config_by_name',
    'get_engine_by_table',
    'get_existing_ids',
    'get_table_database',
    'get_table_max_id',
    'get_table_name',
    'interruptible_sleep',
    'make_staging_table_name',
    'print_step_error',
    'quote_identifier',
    'refresh_connection_read_view',
    'replace_table_with_staging',
    'sql_with_retry',
    'table_exists_exact',
    'validate_sql_identifier',
)

GROUP_WEIGHT_BUILDER_CONTEXT_KEYS = (
    'WEIGHT_GROUP_IDS',
    'GROUP_WEIGHT_MODES',
    'EX_GROUP_MODES',
    'EX_INDEPENDENT_GROUP_WEIGHT_MODES',
    'BUY_GROUP_MODE',
    'EX_PURCHASE_MODE',
    'GROUP_WEIGHT_MODE_DEFS',
    'GROUP_WEIGHT_RULES',
    'ZERO_REBATE_INFERENCE_MODES',
    'GAME_TYPE_NAMES',
    'SPECIAL_GROUP_TARGET_RTP',
    'EX_GROUP_TARGET_RTPS',
    'BUY_GROUP_ENABLED',
    'EX_BUY_GROUP_ENABLED',
    'BUY_GROUP_GAME_TYPE',
    'BUY_GROUP_MULTIPLIER',
    'BUY_GROUP_SOURCE_SUFFIX',
    'EX_GROUP_MULTIPLIER',
    'EXTRA_BUY_GROUPS',
    'build_normal_group_weight_rows_for_group',
    'check_cancelled',
    'make_extra_buy_mode',
    'get_extra_buy_game_type',
    'get_extra_buy_group_by_mode',
    'get_buy_group_game_type_for_mode',
    'get_group_weight_write_game_type',
    'get_group_target_rtp_ratio',
    'get_group_weight_mode_name',
    'get_group_weight_rebate_source_mode',
    'get_group_weight_rebate_table_name',
    'get_group_weight_rtp_role',
    'is_extra_buy_mode',
)


def collect_context(namespace, keys):
    """Collect named values from a globals-like dict or object."""
    missing = []
    values = {}
    for key in keys:
        if isinstance(namespace, dict):
            if key not in namespace:
                missing.append(key)
                continue
            values[key] = namespace[key]
        else:
            if not hasattr(namespace, key):
                missing.append(key)
                continue
            values[key] = getattr(namespace, key)
    if missing:
        raise KeyError(f"Missing runtime context keys: {', '.join(missing)}")
    return values


def assign_context_value(namespace, key, value):
    """Assign a value into a module-like object or globals-like dict."""
    if isinstance(namespace, dict):
        namespace[key] = value
    else:
        setattr(namespace, key, value)


def configure_module_globals(namespace, values, allowed_keys=None, label='module context'):
    """Validate and assign a runtime context into a module globals mapping."""
    if allowed_keys is not None:
        unknown = sorted(set(values) - set(allowed_keys))
        if unknown:
            raise KeyError(f"Unknown {label} keys: {', '.join(unknown)}")
    for key, value in values.items():
        assign_context_value(namespace, key, value)


def configure_sampling_core(sampling_core_module, namespace):
    """Sync current main-script values into sampling_core."""
    sampling_core_module.configure(
        **collect_context(namespace, SAMPLING_CORE_CONTEXT_KEYS)
    )


def configure_group_weight_builder(group_weight_builder_module, namespace):
    """Sync current main-script values into group_weight_builder."""
    group_weight_builder_module.configure(
        **collect_context(namespace, GROUP_WEIGHT_BUILDER_CONTEXT_KEYS)
    )


def synced_call(sync_func, target_func):
    """Return a wrapper that syncs runtime context before calling target_func."""
    @wraps(target_func)
    def wrapper(*args, **kwargs):
        sync_func()
        return target_func(*args, **kwargs)

    return wrapper


def install_synced_wrappers(namespace, sync_func, module, names):
    """Install synced forwarding functions into a globals-like namespace."""
    for name in names:
        assign_context_value(namespace, name, synced_call(sync_func, getattr(module, name)))


def install_direct_wrappers(namespace, module, names):
    """Install direct forwarding functions into a globals-like namespace."""
    for name in names:
        assign_context_value(namespace, name, getattr(module, name))


def kwarg_call(kwargs_factory, target_func):
    """Return a wrapper that injects keyword-only dependencies at call time."""
    @wraps(target_func)
    def wrapper(*args, **kwargs):
        injected = kwargs_factory()
        injected.update(kwargs)
        return target_func(*args, **injected)

    return wrapper


def install_kwarg_wrappers(namespace, kwargs_factory, module, names):
    """Install wrappers that call target functions with dynamic keyword args."""
    for name in names:
        assign_context_value(namespace, name, kwarg_call(kwargs_factory, getattr(module, name)))
