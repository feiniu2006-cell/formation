# ================== 配置区域 ==================
import copy
import os
import sys
import contextlib
import re
import time
from types import SimpleNamespace

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from db_config import DATABASE_CONFIGS, MAX_DB_RETRIES, DB_RETRY_DELAY
from formation_tool.common import common_config_entrypoints
from formation_tool.common import common_config_runner
from formation_tool.db import external_db_config_loader
from formation_tool.db import game_type_config_runtime
from formation_tool.core import formation_cli_settings
from formation_tool.core import formation_context_factories
from formation_tool.db import formation_db_access
from formation_tool.core import formation_defaults
from formation_tool.core import game_type_config
from formation_tool.core import formation_modes
from formation_tool.core import table_driven_configs
from formation_tool.db import formation_table_detection
from formation_tool.group_weight import group_weight_entrypoints
from formation_tool.group_weight import group_weight_logic
from formation_tool.group_weight import group_weight_rebate_loader
from formation_tool.rebate import buy_source_rebate_configs
from formation_tool.core import buy_group_config
from formation_tool.core import rule_config_state
from formation_tool.core import runtime_config
from formation_tool.core import runtime_state_sync
from formation_tool.core import settings_logic
from formation_tool.core import task_entrypoints
from formation_tool.core import task_dependency_factories
RANDOM_SEED = formation_defaults.DEFAULT_RANDOM_SEED
LOW_VOLUME_REBATE_COUNT_THRESHOLD = formation_defaults.DEFAULT_LOW_VOLUME_REBATE_COUNT_THRESHOLD
SAMPLE_ID_FETCH_CHUNK_SIZE = formation_defaults.DEFAULT_SAMPLE_ID_FETCH_CHUNK_SIZE
REBATE_CONFIG_REBATE_ZERO_COUNT_LIMIT = formation_defaults.DEFAULT_REBATE_CONFIG_REBATE_ZERO_COUNT_LIMIT
REBATE_CONFIG_POSITIVE_REBATE_COUNT_LIMIT = formation_defaults.DEFAULT_REBATE_CONFIG_POSITIVE_REBATE_COUNT_LIMIT
REBATE_CONFIG_MAX_REBATE = formation_defaults.DEFAULT_REBATE_CONFIG_MAX_REBATE
REBATE_CONFIG_COUNT_LIMITS = formation_defaults.clone_count_limits()
DEFAULT_REBATE_CONFIG_DIRECT_COUNT_TIERS = formation_defaults.clone_direct_count_tiers()
REBATE_CONFIG_DIRECT_COUNT_MODES = set(formation_defaults.DEFAULT_REBATE_CONFIG_DIRECT_COUNT_MODES)
SAMPLING_APPEND_MODE = formation_defaults.DEFAULT_SAMPLING_APPEND_MODE
SAMPLING_DETAILED_LOG = formation_defaults.DEFAULT_SAMPLING_DETAILED_LOG

EXTERNAL_CONFIG_SOURCE = None
EXTERNAL_CONFIG_LOAD_ERROR = None
SOURCE_FORMATION_CHECK_STATUSES = {}
GAME_TYPE_CONFIG_CACHE = game_type_config_runtime.GameTypeConfigCache()


def _load_external_database_config():
    global DATABASE_CONFIGS, MAX_DB_RETRIES, DB_RETRY_DELAY
    global EXTERNAL_CONFIG_SOURCE, EXTERNAL_CONFIG_LOAD_ERROR

    result = external_db_config_loader.load_external_database_config(
        DATABASE_CONFIGS,
        MAX_DB_RETRIES,
        DB_RETRY_DELAY,
        module_file=__file__,
    )
    DATABASE_CONFIGS = result.database_configs
    MAX_DB_RETRIES = result.max_db_retries
    DB_RETRY_DELAY = result.db_retry_delay
    EXTERNAL_CONFIG_SOURCE = result.source
    EXTERNAL_CONFIG_LOAD_ERROR = result.error


_load_external_database_config()


def get_app_settings_base_dir():
    return settings_logic.get_app_settings_base_dir(module_file=__file__, env=os.environ)


def get_app_settings_path():
    return settings_logic.get_app_settings_path(module_file=__file__, env=os.environ)


def get_app_profile_settings_path(vendor=None, game_id=None):
    vendor = GAME_TABLE_VENDOR if vendor is None else vendor
    game_id = GAME_TABLE_GAME_ID if game_id is None else game_id
    return settings_logic.get_app_profile_settings_path(
        vendor,
        game_id,
        module_file=__file__,
        env=os.environ,
    )


def apply_cli_settings_data(data, *, runtime_only=False):
    """Apply saved settings without requiring the GUI mixins."""
    return formation_cli_settings.apply_cli_settings_data(
        data,
        deps=build_cli_settings_deps(),
        runtime_only=runtime_only,
    )


def load_cli_settings(print_func=print):
    """Load saved runtime/profile settings before entering CLI mode."""
    return formation_cli_settings.load_cli_settings(
        deps=build_cli_settings_deps(),
        print_func=print_func,
    )


def build_cli_settings_deps():
    """Build callbacks used by the CLI saved-settings loader."""
    return SimpleNamespace(
        get_current_runtime=lambda: {
            'vendor': GAME_TABLE_VENDOR,
            'game_id': GAME_TABLE_GAME_ID,
            'source_db': SOURCE_DB,
            'final_db': FINAL_DB,
            'config_db': CONFIG_DB,
            'sampling_temp_db': SAMPLING_TEMP_DB,
            'sampling_use_temp_db': True,
            'sampling_auto_sync_to_target': SAMPLING_AUTO_SYNC_TO_TARGET,
        },
        get_trigger_weights=lambda: {
            'special_0': SPECIAL_WEIGHT_BY_LAST_DIGIT[0],
            'special_1': SPECIAL_WEIGHT_BY_LAST_DIGIT[1],
            'free_0': FREE_WEIGHT_BY_LAST_DIGIT[0],
            'free_1': FREE_WEIGHT_BY_LAST_DIGIT[1],
        },
        get_sampling_append_mode=lambda: SAMPLING_APPEND_MODE,
        get_sampling_detailed_log=lambda: SAMPLING_DETAILED_LOG,
        get_sampling_use_temp_db=lambda: True,
        get_sampling_temp_db=lambda: SAMPLING_TEMP_DB,
        get_sampling_auto_sync_to_target=lambda: SAMPLING_AUTO_SYNC_TO_TARGET,
        get_extra_weight_groups=lambda: EXTRA_WEIGHT_GROUPS,
        get_app_settings_path=get_app_settings_path,
        get_app_profile_settings_path=get_app_profile_settings_path,
        clear_config_warnings=clear_config_warnings,
        consume_config_warnings=consume_config_warnings,
        normalize_rebate_rules_for_load=normalize_rebate_rules_for_load,
        normalize_group_weight_rules_for_load=normalize_group_weight_rules_for_load,
        normalize_group_weight_group_rules_for_load=normalize_group_weight_group_rules_for_load,
        normalize_extra_weight_groups=normalize_extra_weight_groups,
        clone_extra_weight_groups=clone_extra_weight_groups,
        apply_runtime_config=apply_runtime_config,
        apply_weight_config=apply_weight_config,
        apply_extra_weight_groups_config=apply_extra_weight_groups_config,
        apply_rebate_rules_config=apply_rebate_rules_config,
        apply_sampling_append_mode=apply_sampling_append_mode,
        apply_sampling_detailed_log=apply_sampling_detailed_log,
        apply_sampling_temp_db_config=apply_sampling_temp_db_config,
        apply_sampling_auto_sync_to_target=apply_sampling_auto_sync_to_target,
        apply_group_weight_rules_config=apply_group_weight_rules_config,
        apply_group_weight_group_rules_config=apply_group_weight_group_rules_config,
        apply_zero_rebate_inference_modes_config=apply_zero_rebate_inference_modes_config,
        apply_independent_rtp_modes_config=apply_independent_rtp_modes_config,
        apply_rebate_config_direct_count_tiers=apply_rebate_config_direct_count_tiers,
        apply_buy_group_enabled=apply_buy_group_enabled,
        apply_ex_buy_group_enabled=apply_ex_buy_group_enabled,
        apply_ex_buy_group_game_type=apply_ex_buy_group_game_type,
        apply_ex_buy_group_source_suffix=apply_ex_buy_group_source_suffix,
        apply_buy_group_game_type=apply_buy_group_game_type,
        apply_buy_group_multiplier=apply_buy_group_multiplier,
        apply_buy_group_source_suffix=apply_buy_group_source_suffix,
        apply_ex_group_multiplier=apply_ex_group_multiplier,
        apply_ex_group_target_rtps_config=apply_ex_group_target_rtps_config,
        apply_ex_source_suffixes_config=apply_ex_source_suffixes_config,
        apply_extra_buy_groups_config=apply_extra_buy_groups_config,
        apply_special_group_target_rtp=apply_special_group_target_rtp,
        apply_rebate_config_direct_count_modes=apply_rebate_config_direct_count_modes,
        normalize_direct_count_tiers_for_load=normalize_direct_count_tiers_for_load,
    )


SOURCE_DB = runtime_config.DEFAULT_SOURCE_DB    # 源数据库
FINAL_DB  = runtime_config.DEFAULT_FINAL_DB     # 目标数据库
CONFIG_DB = runtime_config.DEFAULT_CONFIG_DB    # 采样配置数据库
# 阵型表名：{GAME_TABLE_VENDOR}_{GAME_TABLE_GAME_ID}_{suffix}
# suffix 示例：formation / free_formation / special_formation
GAME_TABLE_VENDOR = runtime_config.DEFAULT_GAME_TABLE_VENDOR          # 厂商/渠道前缀（表名前缀字段）
GAME_TABLE_GAME_ID = runtime_config.DEFAULT_GAME_TABLE_GAME_ID   # 游戏编号（数字或字符串均可）

def build_game_configs(vendor, game_id, source_db, final_db, config_db):
    return runtime_config.build_game_configs(
        vendor,
        game_id,
        source_db,
        final_db,
        config_db,
        random_seed=RANDOM_SEED,
    )


GAME_TABLE_PREFIX, _GAME_DEFS, GAME_CONFIGS = build_game_configs(
    GAME_TABLE_VENDOR, GAME_TABLE_GAME_ID, SOURCE_DB, FINAL_DB, CONFIG_DB
)

# ================== 权重配置表写入配置 ==================

WEIGHT_CONFIG_DB = FINAL_DB  # 写入目标库
SAMPLING_USE_TEMP_DB = formation_defaults.DEFAULT_SAMPLING_USE_TEMP_DB
SAMPLING_TEMP_DB = formation_defaults.DEFAULT_SAMPLING_TEMP_DB
SAMPLING_AUTO_SYNC_TO_TARGET = formation_defaults.DEFAULT_SAMPLING_AUTO_SYNC_TO_TARGET
SPECIAL_WEIGHT_TABLE   = runtime_config.SPECIAL_WEIGHT_TABLE
FREE_GAME_CONFIG_TABLE = runtime_config.FREE_GAME_CONFIG_TABLE
BET_AMOUNT_TABLE       = runtime_config.BET_AMOUNT_TABLE
GAME_TYPE_CONFIG_TABLE = game_type_config.GAME_TYPE_CONFIG_TABLE

# type_id 由 GAME_TABLE_VENDOR 自动推导
_VENDOR_TYPE_MAP = runtime_config.VENDOR_TYPE_MAP
WEIGHT_TYPE_ID = runtime_config.get_weight_type_id(GAME_TABLE_VENDOR, _VENDOR_TYPE_MAP)


def apply_runtime_config(vendor, game_id, source_db, final_db, config_db):
    """Apply the selected vendor, room, and database configuration."""
    global SOURCE_DB, FINAL_DB, CONFIG_DB, WEIGHT_CONFIG_DB
    global GAME_TABLE_VENDOR, GAME_TABLE_GAME_ID, GAME_TABLE_PREFIX
    global _GAME_DEFS, GAME_CONFIGS, WEIGHT_TYPE_ID
    global GAME_TYPE_CONFIG_CACHE

    _sync_database_runtime_state_from_globals()
    values = runtime_config.build_runtime_values(
        vendor,
        game_id,
        source_db,
        final_db,
        config_db,
        database_configs=RUNTIME_STATE.database_configs,
        random_seed=RANDOM_SEED,
        vendor_type_map=_VENDOR_TYPE_MAP,
    )
    GAME_TABLE_VENDOR = values.vendor
    GAME_TABLE_GAME_ID = values.game_id
    SOURCE_DB = values.source_db
    FINAL_DB = values.final_db
    CONFIG_DB = values.config_db
    WEIGHT_CONFIG_DB = values.weight_config_db
    WEIGHT_TYPE_ID = values.weight_type_id
    GAME_TABLE_PREFIX = values.game_table_prefix
    _GAME_DEFS = values.game_defs
    GAME_CONFIGS = values.game_configs
    GAME_TYPE_CONFIG_CACHE.reset()
    RUNTIME_STATE.apply_runtime_values(values)


# 共用 group_id 列表（room_id 取 GAME_TABLE_GAME_ID）
WEIGHT_GROUP_IDS = list(formation_defaults.DEFAULT_WEIGHT_GROUP_IDS)
EXTRA_WEIGHT_GROUPS = formation_defaults.clone_extra_weight_groups()


def get_group_target_rtp_value(group_id):
    return (int(group_id) // 10) / 10


def format_group_rtp_option(group_id):
    group_id = int(group_id)
    return f"{group_id} - 目标RTP {get_group_target_rtp_value(group_id):.1f}%，分组{group_id % 10}"

# game_group_special_weight_config 的 weight（按 group_id 个位分档）
SPECIAL_WEIGHT_BY_LAST_DIGIT = formation_defaults.clone_int_map(
    formation_defaults.DEFAULT_SPECIAL_WEIGHT_BY_LAST_DIGIT
)

# game_group_free_game_config 的 weight（按 group_id 个位分档，weight2/weight3 固定为 0）
FREE_WEIGHT_BY_LAST_DIGIT = formation_defaults.clone_int_map(
    formation_defaults.DEFAULT_FREE_WEIGHT_BY_LAST_DIGIT
)


def clone_extra_weight_groups(groups):
    return formation_defaults.clone_extra_weight_groups(groups)


def build_weight_group_ids(extra_weight_groups=None):
    group_ids = list(formation_defaults.DEFAULT_WEIGHT_GROUP_IDS)
    seen = set(int(group_id) for group_id in group_ids)
    for group in extra_weight_groups or []:
        group_id = int(group['group_id'])
        if group_id in seen:
            continue
        seen.add(group_id)
        group_ids.append(group_id)
    return group_ids


def normalize_extra_weight_groups(groups):
    normalized = []
    seen_group_ids = set()
    suffix_weights = {}
    for idx, group in enumerate(groups or [], start=1):
        if not isinstance(group, dict):
            raise ValueError(f"额外权重分组第 {idx} 行必须是对象")
        group_id = rule_config_state.parse_non_negative_int_text(
            group.get('group_id'),
            f"额外权重分组第 {idx} 行 group_id",
        )
        special_weight = rule_config_state.parse_non_negative_int_text(
            group.get('special_weight'),
            f"额外权重分组第 {idx} 行特殊局权重",
        )
        free_weight = rule_config_state.parse_non_negative_int_text(
            group.get('free_weight'),
            f"额外权重分组第 {idx} 行免费局权重",
        )
        if group_id in formation_defaults.DEFAULT_WEIGHT_GROUP_IDS:
            raise ValueError(f"额外权重分组第 {idx} 行 group_id={group_id} 已是默认分组")
        if group_id in seen_group_ids:
            raise ValueError(f"额外权重分组 group_id={group_id} 重复")
        seen_group_ids.add(group_id)
        suffix = group_id % 10
        if suffix in (0, 1):
            raise ValueError(
                f"额外权重分组第 {idx} 行 group_id={group_id} 尾号{suffix}已是默认分组；"
                "额外分组请使用尾号2-9"
            )
        weights = (special_weight, free_weight)
        if suffix in suffix_weights and suffix_weights[suffix] != weights:
            raise ValueError(
                f"额外权重分组尾号{suffix}存在不同特殊/免费权重；"
                "同一尾号只能对应一组触发权重"
            )
        suffix_weights[suffix] = weights
        normalized.append({
            'group_id': group_id,
            'special_weight': special_weight,
            'free_weight': free_weight,
        })
    return normalized


def _rebuild_trigger_weight_maps():
    global SPECIAL_WEIGHT_BY_LAST_DIGIT, FREE_WEIGHT_BY_LAST_DIGIT

    special_base = {
        0: int(SPECIAL_WEIGHT_BY_LAST_DIGIT.get(0, formation_defaults.DEFAULT_SPECIAL_WEIGHT_BY_LAST_DIGIT[0])),
        1: int(SPECIAL_WEIGHT_BY_LAST_DIGIT.get(1, formation_defaults.DEFAULT_SPECIAL_WEIGHT_BY_LAST_DIGIT[1])),
    }
    free_base = {
        0: int(FREE_WEIGHT_BY_LAST_DIGIT.get(0, formation_defaults.DEFAULT_FREE_WEIGHT_BY_LAST_DIGIT[0])),
        1: int(FREE_WEIGHT_BY_LAST_DIGIT.get(1, formation_defaults.DEFAULT_FREE_WEIGHT_BY_LAST_DIGIT[1])),
    }
    for group in EXTRA_WEIGHT_GROUPS:
        suffix = int(group['group_id']) % 10
        special_base[suffix] = int(group['special_weight'])
        free_base[suffix] = int(group['free_weight'])
    SPECIAL_WEIGHT_BY_LAST_DIGIT = special_base
    FREE_WEIGHT_BY_LAST_DIGIT = free_base
    RUNTIME_STATE.special_weight_by_last_digit = dict(SPECIAL_WEIGHT_BY_LAST_DIGIT)
    RUNTIME_STATE.free_weight_by_last_digit = dict(FREE_WEIGHT_BY_LAST_DIGIT)


def _rebuild_weight_group_ids():
    WEIGHT_GROUP_IDS[:] = build_weight_group_ids(EXTRA_WEIGHT_GROUPS)
    RUNTIME_STATE.weight_group_ids = list(WEIGHT_GROUP_IDS)
    RUNTIME_STATE.extra_weight_groups = clone_extra_weight_groups(EXTRA_WEIGHT_GROUPS)


def apply_extra_weight_groups_config(groups):
    global EXTRA_WEIGHT_GROUPS

    EXTRA_WEIGHT_GROUPS = normalize_extra_weight_groups(groups)
    _rebuild_trigger_weight_maps()
    _rebuild_weight_group_ids()
    return EXTRA_WEIGHT_GROUPS


def apply_weight_config(special_weight_0, special_weight_1, free_weight_0, free_weight_1):
    """Apply trigger weight values from the UI."""
    global SPECIAL_WEIGHT_BY_LAST_DIGIT, FREE_WEIGHT_BY_LAST_DIGIT

    values = {
        'special_0': ('特殊局个位0权重', special_weight_0),
        'special_1': ('特殊局个位1权重', special_weight_1),
        'free_0': ('免费局个位0权重', free_weight_0),
        'free_1': ('免费局个位1权重', free_weight_1),
    }
    parsed = {}
    for key, (label, value) in values.items():
        text = str(value).strip()
        if not text:
            raise ValueError(f"{label}不能为空")
        try:
            number = int(text)
        except ValueError:
            raise ValueError(f"{label}必须是整数: {text}") from None
        if number < 0:
            raise ValueError(f"{label}不能小于 0: {number}")
        parsed[key] = number

    SPECIAL_WEIGHT_BY_LAST_DIGIT = {
        0: parsed['special_0'],
        1: parsed['special_1'],
    }
    FREE_WEIGHT_BY_LAST_DIGIT = {
        0: parsed['free_0'],
        1: parsed['free_1'],
    }
    _rebuild_trigger_weight_maps()

# ==================  rebate sampling rules ==================
REBATE_RULES = formation_defaults.clone_rule_map(formation_defaults.REBATE_RULES)

# ==================  group_weight interval rules ==================
GROUP_WEIGHT_RULES = formation_defaults.clone_rule_map(formation_defaults.GROUP_WEIGHT_RULES)
GROUP_WEIGHT_GROUP_RULES = formation_defaults.clone_group_rule_map(formation_defaults.GROUP_WEIGHT_GROUP_RULES)
ZERO_REBATE_INFERENCE_MODES = set(formation_modes.DEFAULT_ZERO_REBATE_INFERENCE_MODES)
INDEPENDENT_RTP_MODES = set(formation_modes.DEFAULT_INDEPENDENT_RTP_MODES)

# 特殊局存在 rebate=0 时，用这个手动目标 RTP 反推特殊局 rebate=0 的 weight。
SPECIAL_GROUP_TARGET_RTP = formation_defaults.DEFAULT_SPECIAL_GROUP_TARGET_RTP
EX_GROUP_TARGET_RTPS = formation_defaults.clone_ex_group_target_rtps()
BUY_GROUP_ENABLED = formation_defaults.DEFAULT_BUY_GROUP_ENABLED
EX_BUY_GROUP_ENABLED = formation_defaults.DEFAULT_EX_BUY_GROUP_ENABLED
EX_BUY_GROUP_GAME_TYPE = formation_defaults.DEFAULT_EX_BUY_GROUP_GAME_TYPE
EX_BUY_GROUP_SOURCE_SUFFIX = formation_defaults.DEFAULT_EX_BUY_GROUP_SOURCE_SUFFIX
BUY_GROUP_GAME_TYPE = formation_defaults.DEFAULT_BUY_GROUP_GAME_TYPE
BUY_GROUP_MULTIPLIER = formation_defaults.DEFAULT_BUY_GROUP_MULTIPLIER
BUY_GROUP_SOURCE_SUFFIX = formation_defaults.DEFAULT_BUY_GROUP_SOURCE_SUFFIX
EX_GROUP_MULTIPLIER = formation_defaults.DEFAULT_EX_GROUP_MULTIPLIER
EX_SOURCE_SUFFIXES = formation_defaults.clone_ex_source_suffixes()
EXTRA_BUY_GROUPS = formation_defaults.clone_extra_buy_groups()
BUY_GROUPS = buy_group_config.build_buy_groups_from_legacy(
    buy_enabled=BUY_GROUP_ENABLED,
    buy_game_type=BUY_GROUP_GAME_TYPE,
    buy_multiplier=BUY_GROUP_MULTIPLIER,
    buy_source_suffix=BUY_GROUP_SOURCE_SUFFIX,
    extra_buy_groups=EXTRA_BUY_GROUPS,
)
DEFAULT_SPECIAL_GROUP_TARGET_RTP = formation_defaults.DEFAULT_SPECIAL_GROUP_TARGET_RTP
DEFAULT_EX_GROUP_TARGET_RTPS = formation_defaults.clone_ex_group_target_rtps()
DEFAULT_BUY_GROUP_ENABLED = formation_defaults.DEFAULT_BUY_GROUP_ENABLED
DEFAULT_EX_BUY_GROUP_ENABLED = formation_defaults.DEFAULT_EX_BUY_GROUP_ENABLED
DEFAULT_EX_BUY_GROUP_GAME_TYPE = formation_defaults.DEFAULT_EX_BUY_GROUP_GAME_TYPE
DEFAULT_EX_BUY_GROUP_SOURCE_SUFFIX = formation_defaults.DEFAULT_EX_BUY_GROUP_SOURCE_SUFFIX
DEFAULT_BUY_GROUP_GAME_TYPE = formation_defaults.DEFAULT_BUY_GROUP_GAME_TYPE
DEFAULT_BUY_GROUP_MULTIPLIER = formation_defaults.DEFAULT_BUY_GROUP_MULTIPLIER
DEFAULT_BUY_GROUP_SOURCE_SUFFIX = formation_defaults.DEFAULT_BUY_GROUP_SOURCE_SUFFIX
DEFAULT_EX_GROUP_MULTIPLIER = formation_defaults.DEFAULT_EX_GROUP_MULTIPLIER
DEFAULT_EX_SOURCE_SUFFIXES = formation_defaults.clone_ex_source_suffixes()
DEFAULT_EXTRA_BUY_GROUPS = formation_defaults.clone_extra_buy_groups()
DEFAULT_EXTRA_WEIGHT_GROUPS = formation_defaults.clone_extra_weight_groups()
DEFAULT_SAMPLING_APPEND_MODE = formation_defaults.DEFAULT_SAMPLING_APPEND_MODE
DEFAULT_SAMPLING_DETAILED_LOG = formation_defaults.DEFAULT_SAMPLING_DETAILED_LOG
DEFAULT_SAMPLING_USE_TEMP_DB = formation_defaults.DEFAULT_SAMPLING_USE_TEMP_DB
DEFAULT_SAMPLING_TEMP_DB = formation_defaults.DEFAULT_SAMPLING_TEMP_DB
DEFAULT_SAMPLING_AUTO_SYNC_TO_TARGET = formation_defaults.DEFAULT_SAMPLING_AUTO_SYNC_TO_TARGET

# ================== 代码区域 =================

from formation_tool.db import db_runtime
from formation_tool.db.db_runtime import close_safely, rollback_safely
from formation_tool.db import db_entrypoints
from formation_tool.cli.formation_cli import run_cli
from formation_tool.sampling import sampling_core
from formation_tool.sampling import sampling_entrypoints
from formation_tool.sampling import sampling_task_state
from formation_tool.group_weight import group_weight_runner
from formation_tool.group_weight import group_weight_builder
from formation_tool.group_weight import group_weight_storage
from formation_tool.group_weight.group_weight_logic import format_weighted_rtp
from formation_tool.utils import log_utils
from formation_tool.rebate import rebate_config_logic
from formation_tool.rebate import rebate_config_entrypoints
from formation_tool.rebate import rebate_config_runner
from formation_tool.rebate import rebate_config_storage
from formation_tool.core import runtime_context_sync
from formation_tool.ui import slot_app_entrypoints
from formation_tool.utils.sql_utils import (
    chunked,
    make_staging_table_name,
    quote_identifier,
    validate_sql_identifier,
)
from formation_tool.utils.task_utils import (
    TaskCancelled,
    check_cancelled,
    clear_cancel_request,
    interruptible_sleep,
    request_cancel,
)


def print_step_error(label, error, *, include_trace=False):
    log_utils.print_step_error(label, error, include_trace=include_trace)


def build_table_operation_deps():
    return db_entrypoints.TableOperationDeps(
        quote_identifier=quote_identifier,
        chunked=chunked,
        make_staging_table_name=make_staging_table_name,
        drop_table_if_exists=drop_table_if_exists,
        table_exists_exact=table_exists_exact,
    )


def drop_table_if_exists(conn, table_name):
    return db_entrypoints.drop_table_if_exists(
        conn,
        table_name,
        deps=build_table_operation_deps(),
    )


def count_table_rows(conn, table_name):
    return db_entrypoints.count_table_rows(
        conn,
        table_name,
        deps=build_table_operation_deps(),
    )


def get_table_max_id(conn, table_name):
    return db_entrypoints.get_table_max_id(
        conn,
        table_name,
        deps=build_table_operation_deps(),
    )


def copy_table_rows(conn, source_table, target_table):
    return db_entrypoints.copy_table_rows(
        conn,
        source_table,
        target_table,
        deps=build_table_operation_deps(),
    )


def get_existing_ids(conn, table_name, ids):
    return db_entrypoints.get_existing_ids(
        conn,
        table_name,
        ids,
        deps=build_table_operation_deps(),
    )


def remap_conflicting_sample_ids(*args, **kwargs):
    _sync_sampling_core_context()
    return sampling_core.remap_conflicting_sample_ids(*args, **kwargs)


def replace_table_with_staging(conn, staging_table, target_table, db_name):
    return db_entrypoints.replace_table_with_staging(
        conn,
        staging_table,
        target_table,
        db_name,
        deps=build_table_operation_deps(),
    )


def create_rebate_config_table_if_needed(conn, table_name):
    return rebate_config_entrypoints.create_rebate_config_table_if_needed(
        conn,
        table_name,
        storage_module=rebate_config_storage,
        quote_identifier=quote_identifier,
    )


def build_rebate_config_storage_replace_deps():
    return rebate_config_entrypoints.build_storage_replace_deps(SimpleNamespace(
        make_staging_table_name=make_staging_table_name,
        drop_table_if_exists=drop_table_if_exists,
        create_rebate_config_table_if_needed=create_rebate_config_table_if_needed,
        quote_identifier=quote_identifier,
        count_table_rows=count_table_rows,
        replace_table_with_staging=replace_table_with_staging,
        rollback_safely=rollback_safely,
        suppress_exceptions=lambda: contextlib.suppress(Exception),
    ))


def replace_rebate_config_rows_atomically(conn, table_name, rows, db_name):
    return rebate_config_storage.replace_rebate_config_rows_atomically(
        conn,
        table_name,
        rows,
        db_name,
        deps=build_rebate_config_storage_replace_deps(),
    )


def normalize_rebate_config_rows(rows, mode_name):
    return rebate_config_logic.normalize_rebate_config_rows(rows, mode_name)


REBATE_RULE_FIELDS = rule_config_state.REBATE_RULE_FIELDS
REBATE_RULE_FIELD_LABELS = rule_config_state.REBATE_RULE_FIELD_LABELS
GAME_TYPE_NAMES = formation_modes.GAME_TYPE_NAMES
SAMPLE_GAME_TYPE_NAMES = formation_modes.SAMPLE_GAME_TYPE_NAMES
GROUP_WEIGHT_MODES = formation_modes.GROUP_WEIGHT_MODES
GROUP_WEIGHT_UI_MODES = formation_modes.GROUP_WEIGHT_UI_MODES
EX_GROUP_MODES = formation_modes.EX_GROUP_MODES
EX_PURCHASE_MODE = formation_modes.EX_PURCHASE_MODE
BUY_GROUP_MODE = formation_modes.BUY_GROUP_MODE
EXTRA_BUY_MODE_PREFIX = formation_modes.EXTRA_BUY_MODE_PREFIX
GROUP_WEIGHT_MODE_DEFS = formation_modes.GROUP_WEIGHT_MODE_DEFS
EX_INDEPENDENT_GROUP_WEIGHT_MODES = formation_modes.EX_INDEPENDENT_GROUP_WEIGHT_MODES
GROUP_WEIGHT_RULE_FIELDS = rule_config_state.GROUP_WEIGHT_RULE_FIELDS
GROUP_WEIGHT_RULE_FIELD_LABELS = rule_config_state.GROUP_WEIGHT_RULE_FIELD_LABELS

DEFAULT_REBATE_RULES = {
    mode: [dict(rule) for rule in REBATE_RULES.get(mode, [])]
    for mode in SAMPLE_GAME_TYPE_NAMES
}
DEFAULT_GROUP_WEIGHT_RULES = {
    mode: [dict(rule) for rule in GROUP_WEIGHT_RULES.get(mode, [])]
    for mode in GROUP_WEIGHT_MODES
}
DEFAULT_GROUP_WEIGHT_GROUP_RULES = formation_defaults.clone_group_rule_map(
    formation_defaults.GROUP_WEIGHT_GROUP_RULES
)
DEFAULT_ZERO_REBATE_INFERENCE_MODES = set(formation_modes.DEFAULT_ZERO_REBATE_INFERENCE_MODES)
DEFAULT_INDEPENDENT_RTP_MODES = set(formation_modes.DEFAULT_INDEPENDENT_RTP_MODES)
DEFAULT_TRIGGER_WEIGHTS = {
    'special_0': SPECIAL_WEIGHT_BY_LAST_DIGIT[0],
    'special_1': SPECIAL_WEIGHT_BY_LAST_DIGIT[1],
    'free_0': FREE_WEIGHT_BY_LAST_DIGIT[0],
    'free_1': FREE_WEIGHT_BY_LAST_DIGIT[1],
}
CONFIG_WARNINGS = []
RUNTIME_STATE = runtime_config.RuntimeState()


def _current_module_namespace():
    return runtime_state_sync.namespace_from_globals(globals())


def _sync_database_runtime_state_from_globals():
    runtime_state_sync.sync_database_runtime_state_from_globals(RUNTIME_STATE, _current_module_namespace)


def _sync_runtime_selection_from_globals():
    runtime_state_sync.sync_runtime_selection_from_globals(RUNTIME_STATE, _current_module_namespace)


def _sync_trigger_weights_from_globals():
    runtime_state_sync.sync_trigger_weights_from_globals(RUNTIME_STATE, _current_module_namespace)


def _sync_rebate_runtime_from_globals():
    runtime_state_sync.sync_rebate_runtime_from_globals(RUNTIME_STATE, _current_module_namespace)


def _sync_sampling_runtime_from_globals():
    runtime_state_sync.sync_sampling_runtime_from_globals(RUNTIME_STATE, _current_module_namespace)


def _sync_group_weight_runtime_from_globals():
    runtime_state_sync.sync_group_weight_runtime_from_globals(RUNTIME_STATE, _current_module_namespace)


def _sync_external_status_from_globals():
    runtime_state_sync.sync_external_status_from_globals(RUNTIME_STATE, _current_module_namespace)


def _sync_runtime_state_from_globals():
    runtime_state_sync.sync_runtime_state_from_globals(RUNTIME_STATE, _current_module_namespace)


def _sync_globals_from_runtime_state():
    global DATABASE_CONFIGS, MAX_DB_RETRIES, DB_RETRY_DELAY
    global SOURCE_DB, FINAL_DB, CONFIG_DB, WEIGHT_CONFIG_DB
    global GAME_TABLE_VENDOR, GAME_TABLE_GAME_ID, GAME_TABLE_PREFIX
    global _GAME_DEFS, GAME_CONFIGS, WEIGHT_TYPE_ID
    global WEIGHT_GROUP_IDS, EXTRA_WEIGHT_GROUPS
    global SPECIAL_WEIGHT_BY_LAST_DIGIT, FREE_WEIGHT_BY_LAST_DIGIT
    global REBATE_RULES, GROUP_WEIGHT_RULES, GROUP_WEIGHT_GROUP_RULES
    global ZERO_REBATE_INFERENCE_MODES, INDEPENDENT_RTP_MODES
    global SAMPLING_APPEND_MODE, SAMPLING_DETAILED_LOG
    global REBATE_CONFIG_DIRECT_COUNT_MODES, SPECIAL_GROUP_TARGET_RTP
    global EX_GROUP_TARGET_RTPS
    global BUY_GROUP_ENABLED, EX_BUY_GROUP_ENABLED, EX_BUY_GROUP_GAME_TYPE, EX_BUY_GROUP_SOURCE_SUFFIX
    global BUY_GROUP_GAME_TYPE, BUY_GROUP_MULTIPLIER, BUY_GROUP_SOURCE_SUFFIX, EX_GROUP_MULTIPLIER
    global EX_SOURCE_SUFFIXES
    global EXTRA_BUY_GROUPS, BUY_GROUPS, EXTERNAL_CONFIG_SOURCE, EXTERNAL_CONFIG_LOAD_ERROR, CONFIG_WARNINGS

    target = runtime_state_sync.build_legacy_globals_snapshot(RUNTIME_STATE, _current_module_namespace)
    DATABASE_CONFIGS = target.DATABASE_CONFIGS
    MAX_DB_RETRIES = target.MAX_DB_RETRIES
    DB_RETRY_DELAY = target.DB_RETRY_DELAY
    GAME_TABLE_VENDOR = target.GAME_TABLE_VENDOR
    GAME_TABLE_GAME_ID = target.GAME_TABLE_GAME_ID
    SOURCE_DB = target.SOURCE_DB
    FINAL_DB = target.FINAL_DB
    CONFIG_DB = target.CONFIG_DB
    WEIGHT_CONFIG_DB = target.WEIGHT_CONFIG_DB
    WEIGHT_TYPE_ID = target.WEIGHT_TYPE_ID
    GAME_TABLE_PREFIX = target.GAME_TABLE_PREFIX
    _GAME_DEFS = target._GAME_DEFS
    GAME_CONFIGS = target.GAME_CONFIGS
    WEIGHT_GROUP_IDS[:] = target.WEIGHT_GROUP_IDS
    EXTRA_WEIGHT_GROUPS = target.EXTRA_WEIGHT_GROUPS
    SPECIAL_WEIGHT_BY_LAST_DIGIT = target.SPECIAL_WEIGHT_BY_LAST_DIGIT
    FREE_WEIGHT_BY_LAST_DIGIT = target.FREE_WEIGHT_BY_LAST_DIGIT
    REBATE_RULES = target.REBATE_RULES
    GROUP_WEIGHT_RULES = target.GROUP_WEIGHT_RULES
    GROUP_WEIGHT_GROUP_RULES = target.GROUP_WEIGHT_GROUP_RULES
    ZERO_REBATE_INFERENCE_MODES = target.ZERO_REBATE_INFERENCE_MODES
    INDEPENDENT_RTP_MODES = target.INDEPENDENT_RTP_MODES
    SAMPLING_APPEND_MODE = target.SAMPLING_APPEND_MODE
    SAMPLING_DETAILED_LOG = target.SAMPLING_DETAILED_LOG
    REBATE_CONFIG_DIRECT_COUNT_MODES = target.REBATE_CONFIG_DIRECT_COUNT_MODES
    SPECIAL_GROUP_TARGET_RTP = target.SPECIAL_GROUP_TARGET_RTP
    EX_GROUP_TARGET_RTPS = target.EX_GROUP_TARGET_RTPS
    BUY_GROUP_ENABLED = target.BUY_GROUP_ENABLED
    EX_BUY_GROUP_ENABLED = target.EX_BUY_GROUP_ENABLED
    EX_BUY_GROUP_GAME_TYPE = target.EX_BUY_GROUP_GAME_TYPE
    EX_BUY_GROUP_SOURCE_SUFFIX = target.EX_BUY_GROUP_SOURCE_SUFFIX
    BUY_GROUP_GAME_TYPE = target.BUY_GROUP_GAME_TYPE
    BUY_GROUP_MULTIPLIER = target.BUY_GROUP_MULTIPLIER
    BUY_GROUP_SOURCE_SUFFIX = target.BUY_GROUP_SOURCE_SUFFIX
    EX_GROUP_MULTIPLIER = target.EX_GROUP_MULTIPLIER
    EX_SOURCE_SUFFIXES = target.EX_SOURCE_SUFFIXES
    EXTRA_BUY_GROUPS = target.EXTRA_BUY_GROUPS
    BUY_GROUPS = target.BUY_GROUPS
    EXTERNAL_CONFIG_SOURCE = target.EXTERNAL_CONFIG_SOURCE
    EXTERNAL_CONFIG_LOAD_ERROR = target.EXTERNAL_CONFIG_LOAD_ERROR
    CONFIG_WARNINGS = target.CONFIG_WARNINGS


_sync_runtime_state_from_globals()


def clone_rebate_rules(rules):
    return rule_config_state.clone_rebate_rules(rules, SAMPLE_GAME_TYPE_NAMES)


def clone_runtime_rebate_rules(rules):
    return rule_config_state.clone_rebate_rules(rules, get_runtime_sample_game_type_names())


def clone_group_weight_rules(rules):
    return rule_config_state.clone_group_weight_rules(rules, GROUP_WEIGHT_MODES)


def clone_group_weight_group_rules(rules):
    return rule_config_state.clone_group_weight_group_rules(rules)


def clone_extra_buy_groups(groups):
    return rule_config_state.clone_extra_buy_groups(groups)


def clone_buy_groups(groups):
    return rule_config_state.clone_extra_buy_groups(groups)


def _sync_buy_groups_from_legacy():
    global BUY_GROUPS
    BUY_GROUPS = buy_group_config.build_buy_groups_from_legacy(
        buy_enabled=BUY_GROUP_ENABLED,
        buy_game_type=BUY_GROUP_GAME_TYPE,
        buy_multiplier=BUY_GROUP_MULTIPLIER,
        buy_source_suffix=BUY_GROUP_SOURCE_SUFFIX,
        extra_buy_groups=EXTRA_BUY_GROUPS,
    )
    RUNTIME_STATE.buy_groups = clone_buy_groups(BUY_GROUPS)
    return BUY_GROUPS


def get_buy_groups():
    _sync_group_weight_runtime_from_globals()
    return clone_buy_groups(RUNTIME_STATE.buy_groups)


def apply_buy_groups_config(groups):
    """Apply unified buy-group rows and refresh legacy fields used by existing code."""
    global BUY_GROUP_ENABLED, BUY_GROUP_GAME_TYPE, BUY_GROUP_MULTIPLIER
    global BUY_GROUP_SOURCE_SUFFIX, EXTRA_BUY_GROUPS, BUY_GROUPS
    split = RUNTIME_STATE.apply_buy_groups(groups)
    BUY_GROUP_ENABLED = split['buy_enabled']
    BUY_GROUP_GAME_TYPE = split['buy_game_type']
    BUY_GROUP_MULTIPLIER = split['buy_multiplier']
    BUY_GROUP_SOURCE_SUFFIX = split['buy_source_suffix']
    EXTRA_BUY_GROUPS = split['extra_buy_groups']
    BUY_GROUPS = split['buy_groups']
    return split


def make_extra_buy_mode(game_type):
    return formation_modes.make_extra_buy_mode(game_type)


def is_extra_buy_mode(mode):
    return formation_modes.is_extra_buy_mode(mode)


def get_extra_buy_game_type(mode):
    return formation_modes.get_extra_buy_game_type(mode)


def get_group_weight_mode_name(mode):
    mode = formation_modes.normalize_group_weight_mode_key(mode)
    if mode == BUY_GROUP_MODE:
        return f"购买局{RUNTIME_STATE.buy_group_game_type}"
    if mode == EX_PURCHASE_MODE:
        return f"ex购买局{RUNTIME_STATE.ex_buy_group_game_type}"
    return formation_modes.get_group_weight_mode_name(mode)


def get_group_weight_rtp_role(mode):
    return formation_modes.get_group_weight_rtp_role(mode)


def supports_zero_rebate_inference(mode):
    return formation_modes.supports_zero_rebate_inference(mode)


def supports_independent_rtp(mode):
    return formation_modes.supports_independent_rtp(mode)


def get_zero_rebate_inference_modes():
    _sync_group_weight_runtime_from_globals()
    return set(RUNTIME_STATE.zero_rebate_inference_modes)


def apply_zero_rebate_inference_modes_config(modes):
    global ZERO_REBATE_INFERENCE_MODES
    ZERO_REBATE_INFERENCE_MODES = formation_modes.normalize_zero_rebate_inference_modes(modes)
    RUNTIME_STATE.zero_rebate_inference_modes = set(ZERO_REBATE_INFERENCE_MODES)
    return set(ZERO_REBATE_INFERENCE_MODES)


def get_independent_rtp_modes():
    _sync_group_weight_runtime_from_globals()
    return set(RUNTIME_STATE.independent_rtp_modes)


def apply_independent_rtp_modes_config(modes):
    global INDEPENDENT_RTP_MODES
    INDEPENDENT_RTP_MODES = formation_modes.normalize_independent_rtp_modes(modes)
    RUNTIME_STATE.independent_rtp_modes = set(INDEPENDENT_RTP_MODES)
    return set(INDEPENDENT_RTP_MODES)


def get_extra_buy_group_by_mode(mode):
    _sync_group_weight_runtime_from_globals()
    return formation_modes.get_extra_buy_group_by_mode(mode, RUNTIME_STATE.extra_buy_groups)



def collect_unknown_config_modes(rules, allowed_modes, label):
    return rule_config_state.collect_unknown_config_modes(rules, allowed_modes, label)


def add_config_warning(message):
    CONFIG_WARNINGS.append(str(message))
    RUNTIME_STATE.config_warnings = CONFIG_WARNINGS
    print(f"WARN: {message}")


def clear_config_warnings():
    CONFIG_WARNINGS.clear()
    RUNTIME_STATE.config_warnings = CONFIG_WARNINGS


def consume_config_warnings():
    warnings = list(CONFIG_WARNINGS)
    CONFIG_WARNINGS.clear()
    RUNTIME_STATE.config_warnings = CONFIG_WARNINGS
    return warnings


def _parse_non_negative_int_text(text, label):
    """UI dependency wrapper used by slot_app_context."""
    return rule_config_state.parse_non_negative_int_text(text, label)


def _parse_positive_float_text(text, label):
    return rule_config_state.parse_positive_float_text(text, label)


def _validate_rebate_rules(rules, *, fill_missing=False, warn_unknown=False):
    return rule_config_state.validate_rebate_rules(
        rules,
        sample_modes=tuple(SAMPLE_GAME_TYPE_NAMES),
        default_rules=DEFAULT_REBATE_RULES,
        fill_missing=fill_missing,
        warn_unknown=warn_unknown,
        add_warning=add_config_warning,
    )


def validate_rebate_rules(rules):
    return _validate_rebate_rules(rules, fill_missing=False, warn_unknown=False)


def validate_runtime_rebate_rules(rules):
    return rule_config_state.validate_rebate_rules(
        rules,
        sample_modes=tuple(get_runtime_sample_game_type_names()),
        default_rules=get_runtime_default_rebate_rules(),
        fill_missing=False,
        warn_unknown=False,
        add_warning=add_config_warning,
    )


def normalize_rebate_rules_for_load(rules):
    return _validate_rebate_rules(rules, fill_missing=True, warn_unknown=True)


def apply_rebate_rules_config(rules):
    """Apply rebate sampling rules from settings or dialog input."""
    global REBATE_RULES
    REBATE_RULES = rules
    RUNTIME_STATE.rebate_rules = REBATE_RULES


def apply_rebate_config_direct_count_modes(modes):
    """Apply rebate modes that use direct source counts."""
    global REBATE_CONFIG_DIRECT_COUNT_MODES
    REBATE_CONFIG_DIRECT_COUNT_MODES = {str(mode) for mode in modes}
    RUNTIME_STATE.rebate_config_direct_count_modes = set(REBATE_CONFIG_DIRECT_COUNT_MODES)


def clone_direct_count_tiers(tiers):
    return formation_defaults.clone_direct_count_tiers(tiers)


def get_rebate_config_direct_count_tiers():
    return clone_direct_count_tiers(REBATE_CONFIG_COUNT_LIMITS.get('direct_count_tiers', []))


def normalize_direct_count_tiers_for_load(tiers):
    return rebate_config_logic.normalize_direct_count_tier_limits(tiers)


def apply_rebate_config_direct_count_tiers(tiers):
    """Apply direct-count tier caps used only by low-volume direct count mode."""
    normalized = normalize_direct_count_tiers_for_load(tiers)
    REBATE_CONFIG_COUNT_LIMITS['direct_count_tiers'] = clone_direct_count_tiers(normalized)
    return normalized


def apply_sampling_append_mode(enabled):
    """Deprecated: sampling append mode has been removed."""
    global SAMPLING_APPEND_MODE
    SAMPLING_APPEND_MODE = False
    RUNTIME_STATE.sampling_append_mode = SAMPLING_APPEND_MODE


def apply_sampling_detailed_log(enabled):
    """Apply verbose sampling log mode."""
    global SAMPLING_DETAILED_LOG
    SAMPLING_DETAILED_LOG = bool(enabled)
    RUNTIME_STATE.sampling_detailed_log = SAMPLING_DETAILED_LOG


def apply_sampling_temp_db_config(enabled, temp_db):
    """Apply sampling staging database settings. Staging is always enabled."""
    global SAMPLING_USE_TEMP_DB, SAMPLING_TEMP_DB
    temp_db = str(temp_db or "").strip()
    if temp_db and temp_db not in DATABASE_CONFIGS:
        raise ValueError(f"采样临时库配置不存在: {temp_db}，可选数据库: {list(DATABASE_CONFIGS.keys())}")
    if not temp_db:
        temp_db = formation_defaults.DEFAULT_SAMPLING_TEMP_DB
    if temp_db not in DATABASE_CONFIGS:
        raise ValueError(f"采样临时库配置不存在: {temp_db}，可选数据库: {list(DATABASE_CONFIGS.keys())}")
    SAMPLING_USE_TEMP_DB = True
    SAMPLING_TEMP_DB = temp_db
    RUNTIME_STATE.sampling_use_temp_db = True
    RUNTIME_STATE.sampling_temp_db = temp_db


def apply_sampling_auto_sync_to_target(enabled):
    """Apply whether sampling should mirror staging results to the target DB after success."""
    global SAMPLING_AUTO_SYNC_TO_TARGET
    SAMPLING_AUTO_SYNC_TO_TARGET = bool(enabled)
    RUNTIME_STATE.sampling_auto_sync_to_target = SAMPLING_AUTO_SYNC_TO_TARGET


def normalize_group_weight_rule_list(mode_name, mode_rules):
    return rule_config_state.normalize_group_weight_rule_list(mode_name, mode_rules)


def _validate_group_weight_rules(rules, *, fill_missing=False, warn_unknown=False):
    return rule_config_state.validate_group_weight_rules(
        rules,
        group_modes=GROUP_WEIGHT_MODES,
        game_type_names=GAME_TYPE_NAMES,
        default_rules=DEFAULT_GROUP_WEIGHT_RULES,
        fill_missing=fill_missing,
        warn_unknown=warn_unknown,
        add_warning=add_config_warning,
    )


def validate_group_weight_rules(rules):
    return _validate_group_weight_rules(rules, fill_missing=False, warn_unknown=False)


def normalize_group_weight_rules_for_load(rules):
    return _validate_group_weight_rules(rules, fill_missing=True, warn_unknown=True)


def _validate_group_weight_group_rules(rules, *, warn_unknown=False):
    return rule_config_state.validate_group_weight_group_rules(
        rules,
        group_modes=GROUP_WEIGHT_MODES,
        game_type_names=GAME_TYPE_NAMES,
        warn_unknown=warn_unknown,
        add_warning=add_config_warning,
    )


def validate_group_weight_group_rules(rules):
    return _validate_group_weight_group_rules(rules, warn_unknown=False)


def normalize_group_weight_group_rules_for_load(rules):
    return _validate_group_weight_group_rules(rules, warn_unknown=True)


def apply_group_weight_rules_config(rules):
    """Apply group_weight interval rules from settings or dialog input."""
    global GROUP_WEIGHT_RULES
    GROUP_WEIGHT_RULES = validate_group_weight_rules(rules)
    RUNTIME_STATE.group_weight_rules = GROUP_WEIGHT_RULES


def apply_group_weight_group_rules_config(rules):
    """Apply group-suffix specific group_weight interval rules."""
    global GROUP_WEIGHT_GROUP_RULES
    GROUP_WEIGHT_GROUP_RULES = validate_group_weight_group_rules(rules)
    RUNTIME_STATE.group_weight_group_rules = GROUP_WEIGHT_GROUP_RULES
    return GROUP_WEIGHT_GROUP_RULES


def apply_special_group_target_rtp(value):
    """Apply manual special-group target RTP."""
    global SPECIAL_GROUP_TARGET_RTP
    if value is None or str(value).strip() == "":
        SPECIAL_GROUP_TARGET_RTP = None
    else:
        SPECIAL_GROUP_TARGET_RTP = _parse_positive_float_text(value, "特殊局目标RTP")
    RUNTIME_STATE.special_group_target_rtp = SPECIAL_GROUP_TARGET_RTP


def normalize_ex_group_target_rtps(values):
    """Normalize manual display RTP targets for independent ex modes."""
    normalized = {}
    values = values or {}
    for mode in EX_INDEPENDENT_GROUP_WEIGHT_MODES:
        raw_value = values.get(str(mode), values.get(int(mode), None)) if isinstance(values, dict) else None
        if raw_value is None or str(raw_value).strip() == "":
            continue
        normalized[str(mode)] = _parse_positive_float_text(
            raw_value,
            f"{GAME_TYPE_NAMES.get(str(mode), mode)}目标RTP",
        )
    return normalized


def apply_ex_group_target_rtps_config(values):
    """Apply manual display RTP targets for independent ex modes."""
    global EX_GROUP_TARGET_RTPS
    EX_GROUP_TARGET_RTPS = normalize_ex_group_target_rtps(values)
    RUNTIME_STATE.ex_group_target_rtps = dict(EX_GROUP_TARGET_RTPS)
    return dict(EX_GROUP_TARGET_RTPS)


def get_ex_group_target_rtps():
    _sync_group_weight_runtime_from_globals()
    return dict(RUNTIME_STATE.ex_group_target_rtps)


def apply_buy_group_multiplier(value):
    """Apply buy-group multiplier."""
    global BUY_GROUP_MULTIPLIER
    BUY_GROUP_MULTIPLIER = _parse_positive_float_text(value, "购买倍数")
    RUNTIME_STATE.buy_group_multiplier = BUY_GROUP_MULTIPLIER
    _sync_buy_groups_from_legacy()


def apply_buy_group_game_type(value):
    """Apply the game_type written by the default buy group."""
    global BUY_GROUP_GAME_TYPE
    BUY_GROUP_GAME_TYPE = buy_group_config.normalize_buy_game_type(value, "购买局类型")
    RUNTIME_STATE.buy_group_game_type = BUY_GROUP_GAME_TYPE
    _sync_buy_groups_from_legacy()


def apply_buy_group_source_suffix(value):
    """Apply the formation suffix used by the default buy group."""
    global BUY_GROUP_SOURCE_SUFFIX
    BUY_GROUP_SOURCE_SUFFIX = rule_config_state.normalize_formation_suffix(
        value,
        "购买局阵型表后缀",
        default=formation_modes.DEFAULT_BUY_GROUP_SOURCE_SUFFIX,
    )
    RUNTIME_STATE.buy_group_source_suffix = BUY_GROUP_SOURCE_SUFFIX
    _sync_buy_groups_from_legacy()


def apply_buy_group_enabled(enabled):
    """Apply buy-group switch."""
    global BUY_GROUP_ENABLED
    BUY_GROUP_ENABLED = bool(enabled)
    RUNTIME_STATE.buy_group_enabled = BUY_GROUP_ENABLED
    _sync_buy_groups_from_legacy()


def apply_ex_buy_group_enabled(enabled):
    """Apply ex-buy-group switch."""
    global EX_BUY_GROUP_ENABLED
    EX_BUY_GROUP_ENABLED = bool(enabled)
    RUNTIME_STATE.ex_buy_group_enabled = EX_BUY_GROUP_ENABLED


def apply_ex_buy_group_game_type(value):
    """Apply the game_type written by the ex buy group."""
    global EX_BUY_GROUP_GAME_TYPE
    EX_BUY_GROUP_GAME_TYPE = buy_group_config.normalize_buy_game_type(value, "ex购买局类型")
    RUNTIME_STATE.ex_buy_group_game_type = EX_BUY_GROUP_GAME_TYPE


def apply_ex_buy_group_source_suffix(value):
    """Apply the optional formation suffix used by the ex buy group."""
    global EX_BUY_GROUP_SOURCE_SUFFIX
    text = "" if value is None else str(value).strip()
    EX_BUY_GROUP_SOURCE_SUFFIX = (
        "" if not text else rule_config_state.normalize_formation_suffix(text, "ex购买局阵型表后缀")
    )
    RUNTIME_STATE.ex_buy_group_source_suffix = EX_BUY_GROUP_SOURCE_SUFFIX


def get_ex_buy_group_game_type():
    _sync_group_weight_runtime_from_globals()
    return RUNTIME_STATE.ex_buy_group_game_type


def get_ex_buy_group_source_suffix():
    _sync_group_weight_runtime_from_globals()
    return RUNTIME_STATE.ex_buy_group_source_suffix


def apply_ex_group_multiplier(value):
    """Apply ex multiplier."""
    global EX_GROUP_MULTIPLIER
    EX_GROUP_MULTIPLIER = _parse_positive_float_text(value, "ex倍数")
    RUNTIME_STATE.ex_group_multiplier = EX_GROUP_MULTIPLIER


def normalize_ex_source_suffixes(values):
    """Normalize manual ex source suffix overrides; blank values keep DB defaults."""
    normalized = {}
    values = values or {}
    for mode in EX_GROUP_MODES:
        raw_value = values.get(str(mode), values.get(int(mode), None)) if isinstance(values, dict) else None
        if raw_value is None or str(raw_value).strip() == "":
            continue
        normalized[str(mode)] = rule_config_state.normalize_formation_suffix(
            raw_value,
            f"{GAME_TYPE_NAMES.get(str(mode), mode)}阵型表后缀",
        )
    return normalized


def apply_ex_source_suffixes_config(values):
    """Apply manual source suffix overrides for ex modes 6/7/8."""
    global EX_SOURCE_SUFFIXES
    EX_SOURCE_SUFFIXES = normalize_ex_source_suffixes(values)
    RUNTIME_STATE.ex_source_suffixes = dict(EX_SOURCE_SUFFIXES)
    return dict(EX_SOURCE_SUFFIXES)


def get_ex_source_suffixes():
    _sync_group_weight_runtime_from_globals()
    return dict(RUNTIME_STATE.ex_source_suffixes)


def normalize_extra_buy_groups(groups):
    reserved_game_types = []
    if RUNTIME_STATE.ex_buy_group_enabled:
        reserved_game_types.append(RUNTIME_STATE.ex_buy_group_game_type)
    return buy_group_config.normalize_extra_buy_groups(
        groups,
        group_modes=GROUP_WEIGHT_MODES,
        default_buy_rules=DEFAULT_GROUP_WEIGHT_RULES.get(BUY_GROUP_MODE, []),
        buy_group_mode=BUY_GROUP_MODE,
        default_buy_game_type=BUY_GROUP_GAME_TYPE,
        default_source_suffix=BUY_GROUP_SOURCE_SUFFIX,
        reserved_game_types=reserved_game_types,
    )


def apply_extra_buy_groups_config(groups):
    """Apply additional buy-group configurations."""
    global EXTRA_BUY_GROUPS
    EXTRA_BUY_GROUPS = normalize_extra_buy_groups(groups)
    RUNTIME_STATE.extra_buy_groups = EXTRA_BUY_GROUPS
    _sync_buy_groups_from_legacy()


def has_extra_buy_groups():
    _sync_group_weight_runtime_from_globals()
    return formation_modes.has_extra_buy_groups(RUNTIME_STATE.extra_buy_groups)


def has_any_buy_group():
    _sync_group_weight_runtime_from_globals()
    return bool(buy_group_config.get_enabled_buy_groups(RUNTIME_STATE.buy_groups))


def get_active_group_weight_modes(formation_exists=None):
    _sync_group_weight_runtime_from_globals()
    if formation_exists is None:
        formation_exists = get_group_weight_formation_exists()
    return formation_modes.get_active_group_weight_modes(
        formation_exists,
        buy_enabled=RUNTIME_STATE.buy_group_enabled,
        ex_buy_enabled=RUNTIME_STATE.ex_buy_group_enabled,
        extra_buy_groups=RUNTIME_STATE.extra_buy_groups,
    )


def get_displayed_group_weight_modes(formation_exists, buy_enabled=None, ex_buy_enabled=None):
    _sync_group_weight_runtime_from_globals()
    if buy_enabled is None:
        buy_enabled = RUNTIME_STATE.buy_group_enabled
    if ex_buy_enabled is None:
        ex_buy_enabled = RUNTIME_STATE.ex_buy_group_enabled
    return formation_modes.get_displayed_group_weight_modes(
        formation_exists,
        buy_enabled=buy_enabled,
        ex_buy_enabled=ex_buy_enabled,
        extra_buy_groups=RUNTIME_STATE.extra_buy_groups,
    )


def get_group_target_rtp_ratio(group_id):
    return get_group_target_rtp_value(group_id) / 100


def get_trigger_probability(group_id, weight_by_last_digit, enabled):
    if not enabled:
        return 0
    return weight_by_last_digit.get(int(group_id) % 10, 0) / 10000


def get_free_trigger_probability(group_id, enabled):
    return get_trigger_probability(group_id, FREE_WEIGHT_BY_LAST_DIGIT, enabled)


def get_special_trigger_probability(group_id, enabled):
    return get_trigger_probability(group_id, SPECIAL_WEIGHT_BY_LAST_DIGIT, enabled)


def build_normal_group_weight_rows_for_group(
    group_id,
    normal_pairs,
    free_rtp,
    free_enabled,
    special_rtp,
    special_enabled,
    *,
    game_type=1,
    target_multiplier=1,
    display_divisor=1,
    infer_zero_rebate=True,
):
    return group_weight_logic.build_normal_group_weight_rows_for_group(
        group_id,
        normal_pairs,
        free_rtp,
        free_enabled,
        special_rtp,
        special_enabled,
        free_rate_getter=get_free_trigger_probability,
        special_rate_getter=get_special_trigger_probability,
        target_rtp_getter=get_group_target_rtp_ratio,
        game_type=game_type,
        target_multiplier=target_multiplier,
        display_divisor=display_divisor,
        infer_zero_rebate=infer_zero_rebate,
    )


def build_ex_group_weight_rows_for_group(group_id, ex_pairs, ex_has_zero, ex_game_type, ex_multiplier=1):
    return group_weight_logic.build_ex_group_weight_rows_for_group(
        group_id,
        ex_pairs,
        ex_has_zero,
        ex_game_type,
        ex_multiplier,
        target_rtp_getter=get_group_target_rtp_ratio,
    )


def get_engine(db_config):
    return db_runtime.get_engine(db_config)


def connect_to_db(db_config, max_retries=None, retry_delay=None):
    """Connect to a database using current runtime retry settings by default."""
    if max_retries is None:
        max_retries = RUNTIME_STATE.max_db_retries
    if retry_delay is None:
        retry_delay = RUNTIME_STATE.db_retry_delay
    return db_runtime.connect_to_db(
        db_config,
        max_retries=max_retries,
        retry_delay=retry_delay,
        check_cancelled=check_cancelled,
        sleep_func=interruptible_sleep,
        verbose=SAMPLING_DETAILED_LOG,
    )


def get_db_config_by_name(db_name):
    """Return a database config from the current runtime database map."""
    return db_runtime.get_db_config_by_name(db_name, RUNTIME_STATE.database_configs)


def connect_to_database(db_name):
    return formation_db_access.connect_to_database(
        db_name,
        deps=SimpleNamespace(
            get_db_config_by_name=get_db_config_by_name,
            connect_to_db=connect_to_db,
        ),
    )


def ensure_database_connection(conn, db_name, label='数据库'):
    return db_runtime.ensure_database_connection(
        conn,
        db_name,
        connect_to_database=connect_to_database,
        max_retries=RUNTIME_STATE.max_db_retries,
        retry_delay=RUNTIME_STATE.db_retry_delay,
        label=label,
    )


def refresh_connection_read_view(conn, db_name, label='数据库'):
    return db_runtime.refresh_connection_read_view(
        conn,
        db_name,
        ensure_connection=ensure_database_connection,
        rollback=rollback_safely,
        label=label,
    )


def build_database_access_deps():
    return db_entrypoints.build_database_access_deps(
        db_entrypoints.DatabaseAccessCallbacks(
        get_database_configs=lambda: RUNTIME_STATE.database_configs,
        get_engine=get_engine,
        get_db_config_by_name=get_db_config_by_name,
        connect_to_db=connect_to_db,
        connect_to_database=connect_to_database,
        close_safely=close_safely,
        )
    )


def list_database_configs():
    """Print the current runtime database configuration names and targets."""
    _sync_database_runtime_state_from_globals()
    return formation_db_access.list_database_configs(deps=build_database_access_deps())


def test_database_connections(table_config):
    """Test connections for databases referenced by the given table config."""
    _sync_database_runtime_state_from_globals()
    return formation_db_access.test_database_connections(
        table_config,
        deps=build_database_access_deps(),
    )


def get_table_database(table_key, table_config):
    return formation_db_access.get_table_database(table_key, table_config)


def get_table_name(table_key, table_config):
    return formation_db_access.get_table_name(table_key, table_config)


def _extract_source_suffix_from_table_name(table_name):
    return table_driven_configs.extract_source_suffix_from_table_name(
        table_name,
        RUNTIME_STATE.game_table_prefix,
    )


def load_game_type_configs(force=False):
    """Load game_type/source_suffix/is_buy definitions from FINAL_DB."""
    _sync_runtime_selection_from_globals()
    return game_type_config_runtime.load_game_type_configs(
        final_db=RUNTIME_STATE.final_db,
        table_name=GAME_TYPE_CONFIG_TABLE,
        cache=GAME_TYPE_CONFIG_CACHE,
        force=force,
        connect_to_database=connect_to_database,
        table_exists_exact=table_exists_exact,
        quote_identifier=quote_identifier,
        close_safely=close_safely,
        build_config_map=game_type_config.build_game_type_config_map,
    )


def load_buy_group_options_from_game_type_config(*, force_source=False):
    """Load buy-group UI options from DB game_type config and current source tables."""
    return game_type_config_runtime.load_buy_group_options_from_game_type_config(
        final_db=RUNTIME_STATE.final_db,
        source_db=RUNTIME_STATE.source_db,
        table_prefix=RUNTIME_STATE.game_table_prefix,
        table_name=GAME_TYPE_CONFIG_TABLE,
        cache=GAME_TYPE_CONFIG_CACHE,
        force_source=force_source,
        current_buy_game_type=RUNTIME_STATE.buy_group_game_type,
        current_buy_multiplier=RUNTIME_STATE.buy_group_multiplier,
        current_buy_source_suffix=RUNTIME_STATE.buy_group_source_suffix,
        current_ex_buy_game_type=RUNTIME_STATE.ex_buy_group_game_type,
        current_ex_buy_source_suffix=RUNTIME_STATE.ex_buy_group_source_suffix,
        existing_extra_buy_groups=RUNTIME_STATE.extra_buy_groups,
        default_buy_game_type=DEFAULT_BUY_GROUP_GAME_TYPE,
        default_ex_buy_game_type=DEFAULT_EX_BUY_GROUP_GAME_TYPE,
        deps=game_type_config_runtime.build_buy_group_option_deps(
            connect_to_database=connect_to_database,
            table_exists_exact=table_exists_exact,
            quote_identifier=quote_identifier,
            close_safely=close_safely,
            build_config_map=game_type_config.build_game_type_config_map,
            build_buy_group_options_from_configs=game_type_config.build_buy_group_options_from_configs,
        ),
    )


def get_game_type_config_entry(game_type):
    return game_type_config.get_game_type_config(load_game_type_configs(), int(game_type))


def get_game_type_source_suffix(game_type, default=None):
    return game_type_config.get_source_suffix(load_game_type_configs(), int(game_type), default=default)


def get_game_type_buy_kind(game_type, default=game_type_config.BUY_KIND_NORMAL):
    return game_type_config.get_buy_kind(load_game_type_configs(), int(game_type), default=default)


def _get_fallback_source_suffix_for_mode(mode):
    return table_driven_configs.get_fallback_source_suffix_for_mode(
        mode,
        runtime=RUNTIME_STATE,
        get_table_name=get_table_name,
    )


def _get_runtime_buy_group_entries_with_table_sources():
    return table_driven_configs.build_runtime_buy_group_entries_with_table_sources(
        runtime=RUNTIME_STATE,
        get_game_type_source_suffix=get_game_type_source_suffix,
    )


def build_table_driven_base_game_configs():
    return table_driven_configs.build_table_driven_base_game_configs(
        runtime=RUNTIME_STATE,
        get_game_type_source_suffix=get_game_type_source_suffix,
        build_rebate_table_suffix_from_formation_suffix=build_rebate_table_suffix_from_formation_suffix,
    )


def build_sampling_core_context():
    return formation_context_factories.build_sampling_core_context(
        RUNTIME_STATE,
        SimpleNamespace(
            sample_id_fetch_chunk_size=SAMPLE_ID_FETCH_CHUNK_SIZE,
            check_cancelled=check_cancelled,
            chunked=chunked,
            close_safely=close_safely,
            connect_by_table=connect_by_table,
            count_table_rows=count_table_rows,
            copy_table_rows=copy_table_rows,
            drop_table_if_exists=drop_table_if_exists,
            ensure_database_connection=ensure_database_connection,
            get_db_config_by_name=get_db_config_by_name,
            get_engine_by_table=get_engine_by_table,
            get_existing_ids=get_existing_ids,
            get_table_database=get_table_database,
            get_table_max_id=get_table_max_id,
            get_table_name=get_table_name,
            interruptible_sleep=interruptible_sleep,
            make_staging_table_name=make_staging_table_name,
            print_step_error=print_step_error,
            quote_identifier=quote_identifier,
            refresh_connection_read_view=refresh_connection_read_view,
            replace_table_with_staging=replace_table_with_staging,
            sql_with_retry=sql_with_retry,
            table_exists_exact=table_exists_exact,
            validate_sql_identifier=validate_sql_identifier,
        ),
    )


def _sync_sampling_core_context():
    """Sync the current sampling runtime snapshot into sampling_core."""
    _sync_database_runtime_state_from_globals()
    _sync_sampling_runtime_from_globals()
    runtime_context_sync.configure_sampling_core(
        sampling_core,
        build_sampling_core_context(),
    )


def create_table_like_source(*args, **kwargs):
    _sync_sampling_core_context()
    return sampling_core.create_table_like_source(*args, **kwargs)


def create_final_table_like_source(*args, **kwargs):
    _sync_sampling_core_context()
    return sampling_core.create_final_table_like_source(*args, **kwargs)


def is_same_physical_table(*args, **kwargs):
    _sync_sampling_core_context()
    return sampling_core.is_same_physical_table(*args, **kwargs)


def get_engine_by_table(table_key, table_config):
    return formation_db_access.get_engine_by_table(
        table_key,
        table_config,
        deps=build_database_access_deps(),
    )


def connect_by_table(table_key, table_config):
    return formation_db_access.connect_by_table(
        table_key,
        table_config,
        deps=build_database_access_deps(),
    )


def get_table_columns(*args, **kwargs):
    _sync_sampling_core_context()
    return sampling_core.get_table_columns(*args, **kwargs)


def same_table_structure(*args, **kwargs):
    _sync_sampling_core_context()
    return sampling_core.same_table_structure(*args, **kwargs)


def sql_with_retry(fn, label='SQL操作'):
    return db_runtime.sql_with_retry(
        fn,
        label=label,
        max_retries=RUNTIME_STATE.max_db_retries,
        retry_delay=RUNTIME_STATE.db_retry_delay,
        check_cancelled=check_cancelled,
        sleep_func=interruptible_sleep,
    )


def check_connection(conn):
    return db_runtime.check_connection(conn)


def validate_table_config(*args, **kwargs):
    _sync_sampling_core_context()
    return sampling_core.validate_table_config(*args, **kwargs)


def get_sample_description(*args, **kwargs):
    _sync_sampling_core_context()
    return sampling_core.get_sample_description(*args, **kwargs)


def run_single_game(*args, **kwargs):
    _sync_sampling_core_context()
    return sampling_core.run_single_game(*args, **kwargs)


def detect_end_field(*args, **kwargs):
    _sync_sampling_core_context()
    return sampling_core.detect_end_field(*args, **kwargs)


def detect_end_field_optional(*args, **kwargs):
    _sync_sampling_core_context()
    return sampling_core.detect_end_field_optional(*args, **kwargs)


def validate_end_field_integrity(*args, **kwargs):
    _sync_sampling_core_context()
    return sampling_core.validate_end_field_integrity(*args, **kwargs)


def get_count_for_rebate(rebate, rules):
    return rebate_config_logic.get_count_for_rebate(rebate, rules)


def get_rule_for_rebate(rebate, rules):
    return rebate_config_logic.get_rule_for_rebate(rebate, rules)


def resolve_rebate_config_game_condition(source_conn, source_tbl, sample_cond, *, log=True):
    where_clause = sample_cond['where_clause']
    if any(p in where_clause for p in ('{end_field}', '{end_field_opt}')):
        if '{end_field}' in where_clause:
            end_field = detect_end_field(source_conn, source_tbl)
            if end_field is None:
                raise ValueError(f"{source_tbl} 中未找到 game_end 或 is_end 字段")
            where_clause = where_clause.replace('{end_field}', end_field)
            if log:
                print(f"  检测到结束条件字段：{end_field}")
        if '{end_field_opt}' in where_clause:
            end_field_opt = detect_end_field_optional(source_conn, source_tbl)
            where_clause = where_clause.replace('{end_field_opt}', end_field_opt)
            if log:
                end_text = (
                    "game_end = 1" if 'game_end' in end_field_opt
                    else "is_end = 1" if 'is_end' in end_field_opt
                    else "无"
                )
                print("  结束条件：" + end_text)

    return re.sub(
        r'rebate\s*=\s*\{target_rebate\}\s*(AND\s*)?', '', where_clause
    ).strip() or '1=1'


def get_rebate_config_low_volume_infos(rules_by_mode=None):
    low_volume_infos = []
    game_configs = get_runtime_game_configs()
    rules_by_mode = rules_by_mode or get_runtime_rebate_rules()

    for key in sorted(game_configs):
        check_cancelled()
        if key not in rules_by_mode:
            continue
        game_config = game_configs[key]
        table_config = game_config['table_config']
        sample_cond = game_config['sample_conditions']
        source_db_name = get_table_database('SOURCE_TABLE', table_config)
        config_db_name = get_table_database('REBATE_CONFIG_TABLE', table_config)
        source_tbl = get_table_name('SOURCE_TABLE', table_config)
        config_tbl = get_table_name('REBATE_CONFIG_TABLE', table_config)

        source_conn = connect_by_table('SOURCE_TABLE', table_config)
        if not source_conn:
            raise RuntimeError(f"无法连接源库 {source_db_name}，无法检查 {source_tbl} 数据量")
        try:
            if not table_exists_exact(source_conn, source_tbl):
                continue
            game_condition = resolve_rebate_config_game_condition(
                source_conn,
                source_tbl,
                sample_cond,
                log=False,
            )
            with source_conn.cursor() as cur:
                source_ref = quote_identifier(source_tbl, "源表名")
                limit = int(LOW_VOLUME_REBATE_COUNT_THRESHOLD) + 1
                start = time.perf_counter()
                cur.execute(
                    f"SELECT DISTINCT `id` FROM {source_ref} "
                    f"WHERE {game_condition} LIMIT {limit}"
                )
                rows = cur.fetchall()
            total = len(rows)
            elapsed = time.perf_counter() - start
            print(
                f"  低数据量探测 {source_db_name}.{source_tbl}: "
                f"返回 {total} 个不同id，耗时 {elapsed:.2f} 秒"
            )
        finally:
            close_safely(source_conn)

        if total < LOW_VOLUME_REBATE_COUNT_THRESHOLD:
            low_volume_infos.append({
                'mode': key,
                'name': game_config['name'],
                'source_db': source_db_name,
                'source_table': source_tbl,
                'config_db': config_db_name,
                'config_table': config_tbl,
                'condition': game_condition,
                'total': total,
            })
    return low_volume_infos


def _cursor_rows_as_dicts(cur):
    columns = [desc[0] for desc in (cur.description or [])]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def _load_index_columns(conn, source_tbl):
    source_ref = quote_identifier(source_tbl, "源表名")
    with conn.cursor() as cur:
        cur.execute(f"SHOW INDEX FROM {source_ref}")
        rows = _cursor_rows_as_dicts(cur)

    index_columns = {}
    for row in rows:
        key_name = row.get('Key_name')
        column_name = row.get('Column_name')
        seq = row.get('Seq_in_index')
        if not key_name or not column_name:
            continue
        index_columns.setdefault(str(key_name), []).append((int(seq or 0), str(column_name)))
    return {
        key: [column for _seq, column in sorted(values)]
        for key, values in index_columns.items()
    }


def _explain_rebate_stats_query(conn, source_tbl, stats_condition, count_expr="COUNT(DISTINCT `id`)"):
    source_ref = quote_identifier(source_tbl, "源表名")
    sql = (
        f"EXPLAIN SELECT `rebate`, {count_expr} AS total "
        f"FROM {source_ref} WHERE {stats_condition} "
        f"GROUP BY `rebate` ORDER BY `rebate`"
    )
    with conn.cursor() as cur:
        cur.execute(sql)
        return _cursor_rows_as_dicts(cur)


def _detect_required_rebate_index_prefix(game_condition):
    condition = str(game_condition or '').lower()
    if re.search(r'(^|[^0-9a-z_])game_end([^0-9a-z_]|$)', condition):
        return ['game_end', 'rebate']
    if re.search(r'(^|[^0-9a-z_])is_end([^0-9a-z_]|$)', condition):
        return ['is_end', 'rebate']
    return ['rebate']


def _collect_explain_used_keys(explain_rows):
    keys = []
    for row in explain_rows:
        key = row.get('key')
        if key:
            keys.append(str(key))
    return keys


def _rebate_stats_index_warning(explain_rows, index_columns, required_prefix, *, require_id=True):
    used_keys = _collect_explain_used_keys(explain_rows)
    if not used_keys:
        possible = sorted({
            str(row.get('possible_keys'))
            for row in explain_rows
            if row.get('possible_keys')
        })
        return f"EXPLAIN 未使用索引；possible_keys={', '.join(possible) or '无'}"

    reasons = []
    for key in used_keys:
        columns = [col.lower() for col in index_columns.get(key, [])]
        if not columns:
            reasons.append(f"{key}(无法读取索引列)")
            continue
        if columns[:len(required_prefix)] == required_prefix and (not require_id or 'id' in columns):
            return None
        reasons.append(f"{key}({', '.join(index_columns.get(key, []))})")

    expected_columns = required_prefix + (['id'] if require_id else [])
    expected = ', '.join(expected_columns)
    return f"EXPLAIN 使用的索引不匹配预期列顺序；期望前缀包含 {expected}，实际使用：{'; '.join(reasons)}"


def get_rebate_config_index_warnings(rules_by_mode=None):
    warnings = []
    game_configs = get_runtime_game_configs()
    rules_by_mode = rules_by_mode or get_runtime_rebate_rules()

    for key in sorted(game_configs):
        check_cancelled()
        if key not in rules_by_mode:
            continue
        game_config = game_configs[key]
        table_config = game_config['table_config']
        sample_cond = game_config['sample_conditions']
        source_db_name = get_table_database('SOURCE_TABLE', table_config)
        source_tbl = get_table_name('SOURCE_TABLE', table_config)

        source_conn = connect_by_table('SOURCE_TABLE', table_config)
        if not source_conn:
            raise RuntimeError(f"无法连接源库 {source_db_name}，无法检查 {source_tbl} 索引")
        try:
            if not table_exists_exact(source_conn, source_tbl):
                continue
            game_condition = resolve_rebate_config_game_condition(
                source_conn,
                source_tbl,
                sample_cond,
                log=False,
            )
            stats_condition = rebate_config_runner.build_rebate_config_stats_condition(
                game_condition,
                rules_by_mode[key],
                SimpleNamespace(build_rebate_sql_filter=build_rebate_sql_filter),
                REBATE_CONFIG_COUNT_LIMITS,
                direct_count_mode=False,
            )
            end_field = detect_end_field(source_conn, source_tbl)
            count_expr = "COUNT(DISTINCT `id`)" if end_field else "COUNT(*)"
            start = time.perf_counter()
            explain_rows = _explain_rebate_stats_query(source_conn, source_tbl, stats_condition, count_expr)
            index_columns = _load_index_columns(source_conn, source_tbl)
            elapsed = time.perf_counter() - start
            required_prefix = _detect_required_rebate_index_prefix(game_condition)
            warning = _rebate_stats_index_warning(
                explain_rows,
                index_columns,
                required_prefix,
                require_id=bool(end_field),
            )
            print(
                f"  索引检查 {source_db_name}.{source_tbl}: "
                f"使用索引={', '.join(_collect_explain_used_keys(explain_rows)) or '无'}，"
                f"耗时 {elapsed:.2f} 秒"
            )
        finally:
            close_safely(source_conn)

        if warning:
            warnings.append({
                'mode': key,
                'name': game_config['name'],
                'source_db': source_db_name,
                'source_table': source_tbl,
                'condition': stats_condition,
                'warning': warning,
            })
    return warnings


def write_rebate_config_rows(table_config, config_tbl, config_db_name, result_rows):
    return rebate_config_storage.write_rebate_config_rows(
        table_config,
        config_tbl,
        config_db_name,
        result_rows,
        deps=rebate_config_entrypoints.build_write_rows_deps(SimpleNamespace(
            connect_by_table=connect_by_table,
            replace_rebate_config_rows_atomically=replace_rebate_config_rows_atomically,
            print_write_complete=log_utils.print_write_complete,
            print_step_error=print_step_error,
            rollback_safely=rollback_safely,
            close_safely=close_safely,
        )),
    )


def build_direct_rebate_config_rows(stats_df, *, print_fn=print):
    return rebate_config_logic.build_direct_rebate_config_rows(
        stats_df,
        check_cancelled=check_cancelled,
        print_fn=print_fn,
    )


def apply_direct_count_tier_limits_to_rows(
    rows,
    count_limits=None,
    label="采样配置",
    *,
    print_fn=print,
    detail_print_fn=None,
):
    return rebate_config_logic.apply_direct_count_tier_limits_to_rows(
        rows,
        count_limits,
        label,
        print_fn=print_fn,
        detail_print_fn=detail_print_fn,
    )


def select_smooth_rebate_bucket_rows(
    rule,
    bucket_rows,
    limit_min,
    limit_max,
    *,
    print_fn=print,
    detail_print_fn=None,
):
    return rebate_config_logic.select_smooth_rebate_bucket_rows(
        rule,
        bucket_rows,
        limit_min,
        limit_max,
        check_cancelled=check_cancelled,
        print_fn=print_fn,
        detail_print_fn=detail_print_fn,
    )


def select_limited_rebate_bucket_rows(
    rule,
    bucket_rows,
    limit_min,
    limit_max,
    *,
    print_fn=print,
    detail_print_fn=None,
):
    return rebate_config_logic.select_limited_rebate_bucket_rows(
        rule,
        bucket_rows,
        limit_min,
        limit_max,
        check_cancelled=check_cancelled,
        print_fn=print_fn,
        detail_print_fn=detail_print_fn,
    )


def build_rule_based_rebate_config_rows(stats_df, rules, *, print_fn=print, detail_print_fn=None):
    return rebate_config_logic.build_rule_based_rebate_config_rows(
        stats_df,
        rules,
        check_cancelled=check_cancelled,
        print_fn=print_fn,
        detail_print_fn=detail_print_fn,
    )


def get_rebate_config_count_limit_for_rebate(rebate, count_limits):
    return rebate_config_logic.get_rebate_config_count_limit_for_rebate(rebate, count_limits)


def apply_rebate_config_count_limit(rebate, count, count_limits=None):
    return rebate_config_logic.apply_rebate_config_count_limit(rebate, count, count_limits)


def build_rebate_sql_filter(rules=None, count_limits=None, *, include_rule_ranges=True):
    return rebate_config_logic.build_rebate_sql_filter(
        rules,
        count_limits,
        include_rule_ranges=include_rule_ranges,
    )


def apply_rebate_config_count_limits_to_rows(
    rows,
    count_limits=None,
    label="采样配置",
    *,
    print_fn=print,
    detail_print_fn=None,
):
    return rebate_config_logic.apply_rebate_config_count_limits_to_rows(
        rows,
        count_limits,
        label,
        print_fn=print_fn,
        detail_print_fn=detail_print_fn,
    )

def generate_rebate_config_for_game(game_key, game_config, rules, count_limits=None):
    deps = rebate_config_entrypoints.build_runner_deps(
        SimpleNamespace(
            check_cancelled=check_cancelled,
            get_table_database=get_table_database,
            get_table_name=get_table_name,
            connect_by_table=connect_by_table,
            close_safely=close_safely,
            table_exists_exact=table_exists_exact,
            resolve_rebate_config_game_condition=resolve_rebate_config_game_condition,
            detect_end_field=detect_end_field,
            get_engine_by_table=get_engine_by_table,
            quote_identifier=quote_identifier,
            build_direct_rebate_config_rows=build_direct_rebate_config_rows,
            apply_direct_count_tier_limits_to_rows=apply_direct_count_tier_limits_to_rows,
            build_rule_based_rebate_config_rows=build_rule_based_rebate_config_rows,
            build_rebate_sql_filter=build_rebate_sql_filter,
            apply_rebate_config_count_limits_to_rows=apply_rebate_config_count_limits_to_rows,
            normalize_rebate_config_rows=normalize_rebate_config_rows,
            write_rebate_config_rows=write_rebate_config_rows,
        ),
        SimpleNamespace(
            direct_count_modes=RUNTIME_STATE.rebate_config_direct_count_modes,
            detailed_log=SAMPLING_DETAILED_LOG,
        ),
    )
    return rebate_config_runner.generate_rebate_config_for_game(
        game_key,
        game_config,
        rules,
        deps=deps,
        count_limits=count_limits,
    )


def get_group_weight_table_name():
    """Return the current group_weight table name."""
    return f'{RUNTIME_STATE.game_table_prefix}group_weight'


def get_buy_group_source_suffix_for_mode(game_type):
    mode = formation_modes.normalize_group_weight_mode_key(game_type)
    if mode == BUY_GROUP_MODE or is_extra_buy_mode(mode):
        return formation_modes.get_buy_group_source_suffix(
            mode,
            buy_group_source_suffix=RUNTIME_STATE.buy_group_source_suffix,
            extra_buy_groups=RUNTIME_STATE.extra_buy_groups,
        )
    if mode == EX_PURCHASE_MODE:
        source_suffix = str(RUNTIME_STATE.ex_buy_group_source_suffix or "").strip()
        if source_suffix:
            return source_suffix
    return table_driven_configs.get_buy_group_source_suffix_for_mode(
        mode,
        get_game_type_source_suffix=get_game_type_source_suffix,
        get_buy_group_game_type_for_mode=get_buy_group_game_type_for_mode,
        get_fallback_source_suffix_for_mode=_get_fallback_source_suffix_for_mode,
    )


def get_buy_group_game_type_for_mode(game_type):
    """Return the written game_type for a buy-like group_weight mode."""
    mode = formation_modes.normalize_group_weight_mode_key(game_type)
    if mode == EX_PURCHASE_MODE:
        return int(RUNTIME_STATE.ex_buy_group_game_type)
    return formation_modes.get_buy_group_game_type(
        mode,
        buy_group_game_type=RUNTIME_STATE.buy_group_game_type,
        extra_buy_groups=RUNTIME_STATE.extra_buy_groups,
    )


def get_buy_group_multiplier_for_mode(game_type):
    """Return the configured multiplier for a buy-like group_weight mode."""
    game_type = formation_modes.normalize_group_weight_mode_key(game_type)
    return formation_modes.get_buy_group_multiplier(
        game_type,
        buy_group_multiplier=RUNTIME_STATE.buy_group_multiplier,
        extra_buy_groups=RUNTIME_STATE.extra_buy_groups,
    )


def get_group_weight_write_game_type(game_type):
    """Return the game_type value written to group_weight for one mode."""
    game_type = formation_modes.normalize_group_weight_mode_key(game_type)
    if game_type == EX_PURCHASE_MODE:
        return int(RUNTIME_STATE.ex_buy_group_game_type)
    return formation_modes.get_group_weight_write_game_type(
        game_type,
        buy_group_game_type=RUNTIME_STATE.buy_group_game_type,
        extra_buy_groups=RUNTIME_STATE.extra_buy_groups,
    )


def build_rebate_table_suffix_from_formation_suffix(formation_suffix):
    """Map a formation table suffix to its corresponding rebate_count table suffix."""
    return buy_group_config.formation_suffix_to_rebate_suffix(formation_suffix)


def get_buy_group_source_table_name(game_type):
    """Return the physical source formation table for a buy-like mode."""
    return f"{RUNTIME_STATE.game_table_prefix}{get_buy_group_source_suffix_for_mode(game_type)}"


def get_buy_group_rebate_table_name(game_type):
    """Return the rebate_count table used by a buy-like mode."""
    table_suffix = build_rebate_table_suffix_from_formation_suffix(
        get_buy_group_source_suffix_for_mode(game_type)
    )
    return f"{RUNTIME_STATE.game_table_prefix}{table_suffix}"


def get_group_weight_manual_ex_source_suffix(mode):
    """Return a manual ex source suffix used by group_weight only."""
    mode = formation_modes.normalize_group_weight_mode_key(mode)
    if mode == EX_PURCHASE_MODE:
        return RUNTIME_STATE.ex_buy_group_source_suffix or None
    source_mode = GROUP_WEIGHT_MODE_DEFS.get(str(mode), {}).get('source_mode', str(mode))
    if source_mode in EX_GROUP_MODES:
        return RUNTIME_STATE.ex_source_suffixes.get(str(source_mode))
    return None


def get_group_weight_manual_source_table_name(mode):
    suffix = get_group_weight_manual_ex_source_suffix(mode)
    if not suffix:
        return None
    return f"{RUNTIME_STATE.game_table_prefix}{suffix}"


def get_group_weight_manual_rebate_table_name(mode):
    suffix = get_group_weight_manual_ex_source_suffix(mode)
    if not suffix:
        return None
    table_suffix = build_rebate_table_suffix_from_formation_suffix(suffix)
    return f"{RUNTIME_STATE.game_table_prefix}{table_suffix}"


def get_buy_source_rebate_game_configs():
    """Return dynamic sampling/rebate-count configs for custom buy source tables."""
    default_buy_entry, extra_buy_entries = _get_runtime_buy_group_entries_with_table_sources()
    return buy_source_rebate_configs.build_buy_source_rebate_game_configs(
        table_prefix=RUNTIME_STATE.game_table_prefix,
        source_db=RUNTIME_STATE.source_db,
        final_db=RUNTIME_STATE.final_db,
        config_db=RUNTIME_STATE.config_db,
        random_seed=RANDOM_SEED,
        base_game_configs=build_table_driven_base_game_configs(),
        buy_enabled=default_buy_entry['enabled'],
        buy_game_type=default_buy_entry['game_type'],
        buy_source_suffix=default_buy_entry['source_suffix'],
        extra_buy_groups=extra_buy_entries,
    )


def get_group_weight_rebate_source_mode(game_type):
    game_type = formation_modes.normalize_group_weight_mode_key(game_type)
    if game_type in (BUY_GROUP_MODE, EX_PURCHASE_MODE) or is_extra_buy_mode(game_type):
        return game_type
    return GROUP_WEIGHT_MODE_DEFS.get(game_type, {}).get('source_mode', game_type)


def get_group_weight_rebate_table_name(game_type):
    game_type = formation_modes.normalize_group_weight_mode_key(game_type)
    if game_type in (BUY_GROUP_MODE, EX_PURCHASE_MODE) or is_extra_buy_mode(game_type):
        return get_buy_group_rebate_table_name(game_type)
    manual_table = get_group_weight_manual_rebate_table_name(game_type)
    if manual_table:
        return manual_table
    source_mode = get_group_weight_rebate_source_mode(game_type)
    return get_table_name(
        'REBATE_CONFIG_TABLE',
        get_runtime_game_configs()[source_mode]['table_config'],
    )


def build_group_weight_builder_context():
    return formation_context_factories.build_group_weight_builder_context(
        RUNTIME_STATE,
        SimpleNamespace(
            weight_group_ids=WEIGHT_GROUP_IDS,
            group_weight_modes=GROUP_WEIGHT_MODES,
            ex_group_modes=EX_GROUP_MODES,
            ex_independent_group_weight_modes=EX_INDEPENDENT_GROUP_WEIGHT_MODES,
            buy_group_mode=BUY_GROUP_MODE,
            ex_purchase_mode=EX_PURCHASE_MODE,
            group_weight_mode_defs=GROUP_WEIGHT_MODE_DEFS,
            game_type_names=GAME_TYPE_NAMES,
        ),
        SimpleNamespace(
            build_normal_group_weight_rows_for_group=build_normal_group_weight_rows_for_group,
            check_cancelled=check_cancelled,
            make_extra_buy_mode=make_extra_buy_mode,
            get_extra_buy_game_type=get_extra_buy_game_type,
            get_extra_buy_group_by_mode=get_extra_buy_group_by_mode,
            get_buy_group_game_type_for_mode=get_buy_group_game_type_for_mode,
            get_group_weight_write_game_type=get_group_weight_write_game_type,
            get_group_target_rtp_ratio=get_group_target_rtp_ratio,
            get_group_weight_mode_name=get_group_weight_mode_name,
            get_group_weight_rebate_source_mode=get_group_weight_rebate_source_mode,
            get_group_weight_rebate_table_name=get_group_weight_rebate_table_name,
            get_group_weight_rtp_role=get_group_weight_rtp_role,
            is_extra_buy_mode=is_extra_buy_mode,
        ),
    )


def _sync_group_weight_builder_context():
    """Sync the current group_weight runtime snapshot into group_weight_builder."""
    _sync_runtime_selection_from_globals()
    _sync_group_weight_runtime_from_globals()
    runtime_context_sync.configure_group_weight_builder(
        group_weight_builder,
        build_group_weight_builder_context(),
    )


def create_group_weight_table_if_needed(conn, table_name):
    return group_weight_entrypoints.create_group_weight_table_if_needed(
        conn,
        table_name,
        storage_module=group_weight_storage,
        quote_identifier=quote_identifier,
    )


def build_group_weight_storage_replace_deps():
    return group_weight_entrypoints.build_storage_replace_deps(SimpleNamespace(
        make_staging_table_name=make_staging_table_name,
        drop_table_if_exists=drop_table_if_exists,
        create_group_weight_table_if_needed=create_group_weight_table_if_needed,
        quote_identifier=quote_identifier,
        count_table_rows=count_table_rows,
        replace_table_with_staging=replace_table_with_staging,
        rollback_safely=rollback_safely,
        suppress_exceptions=lambda: contextlib.suppress(Exception),
    ))


def replace_group_weight_rows_atomically(conn, table_name, rows, db_name):
    return group_weight_storage.replace_group_weight_rows_atomically(
        conn,
        table_name,
        rows,
        db_name,
        deps=build_group_weight_storage_replace_deps(),
    )


def normalize_group_weight_rows(rows):
    return group_weight_storage.normalize_group_weight_rows(rows)


def read_rebate_config_values(conn, table_name):
    return group_weight_entrypoints.read_rebate_config_values(
        conn,
        table_name,
        storage_module=group_weight_storage,
        quote_identifier=quote_identifier,
    )

def build_group_weight_rebate_loader_deps():
    return group_weight_entrypoints.build_rebate_loader_deps(
        SimpleNamespace(
            has_any_buy_group=has_any_buy_group,
            build_preview_modes=lambda: group_weight_rebate_loader.build_preview_modes(
                GROUP_WEIGHT_MODES,
                RUNTIME_STATE.extra_buy_groups,
                make_extra_buy_mode=make_extra_buy_mode,
            ),
            get_group_weight_formation_exists=get_group_weight_formation_exists,
            get_source_formation_check_error_for_mode=get_source_formation_check_error_for_mode,
            get_group_weight_rebate_table_name=get_group_weight_rebate_table_name,
            get_group_weight_mode_name=get_group_weight_mode_name,
            is_extra_buy_mode=is_extra_buy_mode,
            get_extra_buy_group_by_mode=get_extra_buy_group_by_mode,
            connect_to_database=connect_to_database,
            table_exists_exact=table_exists_exact,
            read_rebate_config_values=read_rebate_config_values,
            close_safely=close_safely,
            check_cancelled=check_cancelled,
        ),
        SimpleNamespace(
            buy_group_mode=BUY_GROUP_MODE,
            ex_purchase_mode=EX_PURCHASE_MODE,
            group_weight_modes=GROUP_WEIGHT_MODES,
        ),
        SimpleNamespace(
            get_config_db=lambda: RUNTIME_STATE.config_db,
            get_ex_buy_group_enabled=lambda: RUNTIME_STATE.ex_buy_group_enabled,
            get_group_weight_rules=lambda: RUNTIME_STATE.group_weight_rules,
            default_buy_group_weight_rules=lambda: DEFAULT_GROUP_WEIGHT_RULES.get(BUY_GROUP_MODE, []),
        ),
    )


def load_group_weight_preview_rebates(buy_enabled=None):
    """Load rebate values used by the group_weight preview dialog."""
    return group_weight_rebate_loader.load_group_weight_preview_rebates(
        deps=build_group_weight_rebate_loader_deps(),
        buy_enabled=buy_enabled,
    )


def collect_group_weight_preview_warnings(*args, **kwargs):
    return _call_group_weight_builder('collect_group_weight_preview_warnings', *args, **kwargs)


def build_group_weight_pairs_for_modes(*args, **kwargs):
    return _call_group_weight_builder('build_group_weight_pairs_for_modes', *args, **kwargs)


def load_group_weight_rebates_for_modes(conn, active_modes, read_db_name):
    return group_weight_rebate_loader.load_group_weight_rebates_for_modes(
        conn,
        active_modes,
        read_db_name,
        deps=build_group_weight_rebate_loader_deps(),
    )


def build_group_weight_preview_text(*args, **kwargs):
    return _call_group_weight_builder('build_group_weight_preview_text', *args, **kwargs)


def build_group_weight_preview_points(*args, **kwargs):
    return _call_group_weight_builder('build_group_weight_preview_points', *args, **kwargs)


def build_group_weight_rows_from_loaded_data(*args, **kwargs):
    return _call_group_weight_builder('build_group_weight_rows_from_loaded_data', *args, **kwargs)


def build_group_weight_zero_weight_write_rows(*args, **kwargs):
    return _call_group_weight_builder('build_group_weight_zero_weight_write_rows', *args, **kwargs)


def _call_group_weight_builder(func_name, *args, **kwargs):
    return group_weight_entrypoints.call_builder_function(
        _sync_group_weight_builder_context,
        group_weight_builder,
        func_name,
        *args,
        **kwargs,
    )


def append_static_group_weight_rows(*args, **kwargs):
    return _call_group_weight_builder('append_static_group_weight_rows', *args, **kwargs)


def append_buy_like_group_weight_rows(*args, **kwargs):
    return _call_group_weight_builder('append_buy_like_group_weight_rows', *args, **kwargs)


def append_extra_buy_group_weight_rows(*args, **kwargs):
    return _call_group_weight_builder('append_extra_buy_group_weight_rows', *args, **kwargs)


def append_special_group_weight_rows(*args, **kwargs):
    return _call_group_weight_builder('append_special_group_weight_rows', *args, **kwargs)


def append_independent_ex_group_rows(*args, **kwargs):
    return _call_group_weight_builder('append_independent_ex_group_rows', *args, **kwargs)


def prepare_original_trigger_rtp_context(*args, **kwargs):
    return _call_group_weight_builder('prepare_original_trigger_rtp_context', *args, **kwargs)


def log_original_trigger_rtp_context(*args, **kwargs):
    return _call_group_weight_builder('log_original_trigger_rtp_context', *args, **kwargs)


def append_original_normal_group_weight_rows(*args, **kwargs):
    return _call_group_weight_builder('append_original_normal_group_weight_rows', *args, **kwargs)


def should_skip_original_static_mode(*args, **kwargs):
    return _call_group_weight_builder('should_skip_original_static_mode', *args, **kwargs)


def append_original_special_group_weight_rows(*args, **kwargs):
    return _call_group_weight_builder('append_original_special_group_weight_rows', *args, **kwargs)


def append_original_free_group_weight_rows(*args, **kwargs):
    return _call_group_weight_builder('append_original_free_group_weight_rows', *args, **kwargs)


def append_original_group_weight_modes(*args, **kwargs):
    return _call_group_weight_builder('append_original_group_weight_modes', *args, **kwargs)


def append_buy_group_weight_modes(*args, **kwargs):
    return _call_group_weight_builder('append_buy_group_weight_modes', *args, **kwargs)


def has_rebate_zero(*args, **kwargs):
    return _call_group_weight_builder('has_rebate_zero', *args, **kwargs)


def should_skip_group_weight_mode_data(*args, **kwargs):
    return _call_group_weight_builder('should_skip_group_weight_mode_data', *args, **kwargs)


def log_ex_independent_group_weight_result(*args, **kwargs):
    return _call_group_weight_builder('log_ex_independent_group_weight_result', *args, **kwargs)


def append_ex_independent_group_weight_modes(*args, **kwargs):
    return _call_group_weight_builder('append_ex_independent_group_weight_modes', *args, **kwargs)


def append_ex_normal_group_weight_mode(*args, **kwargs):
    return _call_group_weight_builder('append_ex_normal_group_weight_mode', *args, **kwargs)


def append_ex_buy_group_weight_mode(*args, **kwargs):
    return _call_group_weight_builder('append_ex_buy_group_weight_mode', *args, **kwargs)


def append_ex_group_weight_modes(*args, **kwargs):
    return _call_group_weight_builder('append_ex_group_weight_modes', *args, **kwargs)


def build_group_weight_generation_context():
    return group_weight_runner.build_group_weight_generation_context(
        deps=build_group_weight_runner_deps(),
    )


def print_group_weight_generation_summary(*args, **kwargs):
    return _call_group_weight_builder('print_group_weight_generation_summary', *args, **kwargs)


def connect_group_weight_databases(read_db_name, write_db_name):
    return group_weight_entrypoints.connect_group_weight_databases(
        read_db_name,
        write_db_name,
        runner_module=group_weight_runner,
        connect_to_database=connect_to_database,
        close_safely=close_safely,
    )


def load_group_weight_generation_data(read_conn, context):
    return group_weight_runner.load_group_weight_generation_data(
        read_conn,
        context,
        deps=build_group_weight_runner_deps(),
    )


def build_normalized_group_weight_generation_rows(formation_exists, rebates_by_mode, mode_exists, mode_pairs):
    return group_weight_runner.build_normalized_group_weight_generation_rows(
        formation_exists,
        rebates_by_mode,
        mode_exists,
        mode_pairs,
        deps=build_group_weight_runner_deps(),
    )


def write_group_weight_generation_rows(write_conn, context, rows):
    return group_weight_runner.write_group_weight_generation_rows(
        write_conn,
        context,
        rows,
        deps=build_group_weight_runner_deps(),
    )


def verify_group_weight_zero_rebate_rows(write_conn, table_name, rows):
    return group_weight_entrypoints.verify_group_weight_zero_rebate_rows(
        write_conn,
        table_name,
        rows,
        storage_module=group_weight_storage,
        quote_identifier=quote_identifier,
        game_type_names=GAME_TYPE_NAMES,
    )


def build_group_weight_runner_deps():
    return group_weight_entrypoints.build_runner_deps(
        SimpleNamespace(
            check_cancelled=check_cancelled,
            get_group_weight_table_name=get_group_weight_table_name,
            get_group_weight_formation_exists=get_group_weight_formation_exists,
            get_active_group_weight_modes=get_active_group_weight_modes,
            build_group_weight_generation_context=build_group_weight_generation_context,
            print_group_weight_generation_summary=print_group_weight_generation_summary,
            connect_group_weight_databases=connect_group_weight_databases,
            load_group_weight_generation_data=load_group_weight_generation_data,
            load_group_weight_rebates_for_modes=load_group_weight_rebates_for_modes,
            build_group_weight_pairs_for_modes=build_group_weight_pairs_for_modes,
            build_group_weight_zero_weight_write_rows=build_group_weight_zero_weight_write_rows,
            build_normalized_group_weight_generation_rows=build_normalized_group_weight_generation_rows,
            build_group_weight_rows_from_loaded_data=build_group_weight_rows_from_loaded_data,
            normalize_group_weight_rows=normalize_group_weight_rows,
            write_group_weight_generation_rows=write_group_weight_generation_rows,
            replace_group_weight_rows_atomically=replace_group_weight_rows_atomically,
            verify_group_weight_zero_rebate_rows=verify_group_weight_zero_rebate_rows,
            print_step_error=print_step_error,
            rollback_safely=rollback_safely,
            close_safely=close_safely,
        ),
        SimpleNamespace(
            ex_group_modes=EX_GROUP_MODES,
            ex_purchase_mode=EX_PURCHASE_MODE,
        ),
        SimpleNamespace(
            get_config_db=lambda: RUNTIME_STATE.config_db,
            get_final_db=lambda: RUNTIME_STATE.final_db,
            get_ex_buy_group_enabled=lambda: RUNTIME_STATE.ex_buy_group_enabled,
        ),
        SimpleNamespace(
            print_no_group_weight_rows=log_utils.print_no_group_weight_rows,
            print_group_weight_validation_failed=log_utils.print_group_weight_validation_failed,
            print_replace_with_staging_notice=log_utils.print_replace_with_staging_notice,
            print_write_complete=log_utils.print_write_complete,
        ),
    )


def generate_group_weight_config():
    return group_weight_runner.generate_group_weight_config(deps=build_group_weight_runner_deps())


def build_common_config_constants():
    return common_config_entrypoints.CommonConfigConstants(
        weight_group_ids=WEIGHT_GROUP_IDS,
        special_weight_table=SPECIAL_WEIGHT_TABLE,
        free_game_config_table=FREE_GAME_CONFIG_TABLE,
        bet_amount_table=BET_AMOUNT_TABLE,
    )


def build_common_config_runtime_deps():
    return common_config_entrypoints.RuntimeDeps(
        connect_to_database=connect_to_database,
        quote_identifier=quote_identifier,
        validate_sql_identifier=validate_sql_identifier,
        rollback_safely=rollback_safely,
        close_safely=close_safely,
        print_step_error=print_step_error,
    )


def build_common_config_writer_deps():
    """Build dependencies for common config table writers."""
    return common_config_entrypoints.build_writer_deps(
        RUNTIME_STATE,
        build_common_config_constants(),
        build_common_config_runtime_deps(),
    )


def _do_write_weight_config(table_name, columns, rows, db_name, room_id, type_id=None):
    return common_config_entrypoints.write_weight_config(
        build_common_config_writer_deps(),
        table_name,
        columns,
        rows,
        db_name,
        room_id,
        type_id,
    )


def table_exists_exact(conn, table_name):
    return common_config_entrypoints.table_exists_exact(
        conn,
        table_name,
        validate_sql_identifier=validate_sql_identifier,
    )


def _check_final_table_exists(table_name):
    return common_config_entrypoints.check_final_table_exists(
        build_common_config_writer_deps(),
        table_name,
    )

def get_group_weight_formation_source_mode(mode):
    mode = formation_modes.normalize_group_weight_mode_key(mode)
    if mode in (BUY_GROUP_MODE, EX_PURCHASE_MODE) or is_extra_buy_mode(mode):
        return mode
    return formation_table_detection.get_group_weight_source_mode(
        mode,
        mode_defs=GROUP_WEIGHT_MODE_DEFS,
        buy_group_mode=BUY_GROUP_MODE,
        is_extra_buy_mode=is_extra_buy_mode,
    )


def clear_source_formation_check_errors():
    SOURCE_FORMATION_CHECK_STATUSES.clear()


def get_source_formation_check_status(source_mode):
    return SOURCE_FORMATION_CHECK_STATUSES.get(str(source_mode))


def get_source_formation_check_error(source_mode):
    status = get_source_formation_check_status(source_mode)
    return None if status is None else status.error


def get_source_formation_check_error_for_mode(mode):
    source_mode = get_group_weight_formation_source_mode(mode)
    if source_mode is None:
        return None
    return get_source_formation_check_error(source_mode)


def set_source_formation_check_error(source_mode, message):
    source_mode = str(source_mode)
    SOURCE_FORMATION_CHECK_STATUSES[source_mode] = formation_table_detection.FormationCheckStatus(
        source_mode=source_mode,
        exists=False,
        error=str(message),
    )


def build_source_formation_detection_deps():
    return formation_table_detection.build_detection_deps(
        get_game_configs=get_runtime_game_configs,
        get_table_database=get_table_database,
        get_table_name=get_table_name,
        connect_to_database=connect_to_database,
        table_exists_exact=table_exists_exact,
        close_safely=close_safely,
    )


def check_buy_like_source_formation_status(source_mode):
    """Check the custom source formation table configured for a buy-like mode."""
    source_mode = formation_modes.normalize_group_weight_mode_key(source_mode)
    return formation_table_detection.check_physical_source_status(
        source_mode,
        RUNTIME_STATE.source_db,
        get_buy_group_source_table_name(source_mode),
        deps=build_source_formation_detection_deps(),
    )


def check_group_weight_manual_source_formation_status(mode):
    """Check a manual ex source suffix used only by group_weight."""
    source_mode = get_group_weight_formation_source_mode(mode)
    source_table = get_group_weight_manual_source_table_name(mode)
    if source_mode is None or not source_table:
        return None
    return formation_table_detection.check_physical_source_status(
        source_mode,
        RUNTIME_STATE.source_db,
        source_table,
        deps=build_source_formation_detection_deps(),
    )


def check_source_formation_status(source_mode):
    source_mode = formation_modes.normalize_group_weight_mode_key(source_mode)
    if source_mode in (BUY_GROUP_MODE, EX_PURCHASE_MODE) or is_extra_buy_mode(source_mode):
        status = check_buy_like_source_formation_status(source_mode)
    else:
        status = formation_table_detection.check_source_formation_status(
            source_mode,
            deps=build_source_formation_detection_deps(),
        )
    SOURCE_FORMATION_CHECK_STATUSES[str(source_mode)] = status
    return status


def check_source_formation_exists(source_mode):
    return check_source_formation_status(source_mode).exists


def check_group_weight_source_formation_exists(mode):
    source_mode = get_group_weight_formation_source_mode(mode)
    if source_mode is None:
        return False
    manual_status = check_group_weight_manual_source_formation_status(mode)
    if manual_status is not None:
        SOURCE_FORMATION_CHECK_STATUSES[str(source_mode)] = manual_status
        return manual_status.exists
    return check_source_formation_exists(source_mode)


def get_group_weight_formation_exists():
    clear_source_formation_check_errors()
    mode_exists_cache = {}
    result = {}
    check_modes = list(GROUP_WEIGHT_MODES)
    check_modes.extend(make_extra_buy_mode(group['game_type']) for group in RUNTIME_STATE.extra_buy_groups)
    for mode in check_modes:
        source_mode = get_group_weight_formation_source_mode(mode)
        if source_mode is None:
            result[mode] = False
            continue
        if mode not in mode_exists_cache:
            mode_exists_cache[mode] = check_group_weight_source_formation_exists(mode)
        result[mode] = mode_exists_cache[mode]
    return result


def get_sampling_formation_exists():
    clear_source_formation_check_errors()
    return {
        mode: check_source_formation_exists(mode)
        for mode in get_runtime_game_configs()
    }


def check_ex_formation_exists():
    return any(check_group_weight_source_formation_exists(mode) for mode in EX_GROUP_MODES)


def check_special_formation_exists():
    return check_group_weight_source_formation_exists('2')


def write_special_weight_config():
    return common_config_entrypoints.write_special_weight_config(
        RUNTIME_STATE,
        build_common_config_constants(),
        build_common_config_runtime_deps(),
    )


def write_free_game_config():
    return common_config_entrypoints.write_free_game_config(
        RUNTIME_STATE,
        build_common_config_constants(),
        build_common_config_runtime_deps(),
    )


def parse_number_list(text, label):
    return common_config_entrypoints.parse_number_list(text, label)


def read_room_base_bet_config(conn, source_table, room_id, type_id):
    return common_config_entrypoints.read_room_base_bet_config(
        conn,
        source_table,
        room_id,
        type_id,
        quote_identifier=quote_identifier,
    )


def calculate_bet_amount_values(base_row):
    return common_config_entrypoints.calculate_bet_amount_values(base_row)


def read_existing_bet_amount_set(conn, table_name, room_id, type_id):
    return common_config_entrypoints.read_existing_bet_amount_set(
        conn,
        table_name,
        room_id,
        type_id,
        quote_identifier=quote_identifier,
    )


def replace_bet_amount_rows(conn, db_name, table_name, room_id, type_id, sorted_values):
    return common_config_entrypoints.replace_bet_amount_rows(
        conn,
        db_name,
        table_name,
        room_id,
        type_id,
        sorted_values,
        quote_identifier=quote_identifier,
    )


def write_bet_amount_config():
    return common_config_entrypoints.write_bet_amount_config(
        RUNTIME_STATE,
        build_common_config_constants(),
        build_common_config_runtime_deps(),
    )


def build_common_config_runner_deps():
    return common_config_entrypoints.build_runner_deps(
        build_common_config_constants(),
        common_config_entrypoints.RunnerTaskDeps(
            check_cancelled=check_cancelled,
            print_section=log_utils.print_section,
            print_result_summary=log_utils.print_result_summary,
        ),
        common_config_entrypoints.RunnerWriterDeps(
            write_special_weight_config=write_special_weight_config,
            write_free_game_config=write_free_game_config,
            write_bet_amount_config=write_bet_amount_config,
        ),
    )


def _call_sampling_core(func_name, *args, **kwargs):
    return sampling_entrypoints.call_core_function(
        _sync_sampling_core_context,
        sampling_core,
        func_name,
        *args,
        **kwargs,
    )


def check_source_table_exists(*args, **kwargs):
    return _call_sampling_core('check_source_table_exists', *args, **kwargs)


def resolve_direct_sample_conditions(*args, **kwargs):
    return _call_sampling_core('resolve_direct_sample_conditions', *args, **kwargs)


def load_sampling_config_df(*args, **kwargs):
    return _call_sampling_core('load_sampling_config_df', *args, **kwargs)


def select_sample_ids_for_rebate(*args, **kwargs):
    return _call_sampling_core('select_sample_ids_for_rebate', *args, **kwargs)


def read_sample_rows_by_ids(*args, **kwargs):
    return _call_sampling_core('read_sample_rows_by_ids', *args, **kwargs)


def format_changed_pairs_preview(*args, **kwargs):
    return _call_sampling_core('format_changed_pairs_preview', *args, **kwargs)


def remap_sample_chunk_for_append_mode(*args, **kwargs):
    return _call_sampling_core('remap_sample_chunk_for_append_mode', *args, **kwargs)


def write_sample_chunk_to_staging(*args, **kwargs):
    return _call_sampling_core('write_sample_chunk_to_staging', *args, **kwargs)


def fetch_and_write_sample_rows_in_chunks(*args, **kwargs):
    return _call_sampling_core('fetch_and_write_sample_rows_in_chunks', *args, **kwargs)


def sample_rebate_to_staging(*args, **kwargs):
    return _call_sampling_core('sample_rebate_to_staging', *args, **kwargs)


def get_direct_sampling_names(*args, **kwargs):
    return _call_sampling_core('get_direct_sampling_names', *args, **kwargs)


def reject_same_physical_sampling_table(*args, **kwargs):
    return _call_sampling_core('reject_same_physical_sampling_table', *args, **kwargs)


def prepare_direct_sampling_staging(*args, **kwargs):
    return _call_sampling_core('prepare_direct_sampling_staging', *args, **kwargs)


def sample_config_rows_to_staging(*args, **kwargs):
    return _call_sampling_core('sample_config_rows_to_staging', *args, **kwargs)


def finalize_direct_sampling_staging(*args, **kwargs):
    return _call_sampling_core('finalize_direct_sampling_staging', *args, **kwargs)


def sync_sampling_temp_table_to_target(*args, **kwargs):
    return _call_sampling_core('sync_sampling_temp_table_to_target', *args, **kwargs)


def build_sampling_temp_sync_items(modes="all", *, existing_only=False):
    """Build mirror targets from the sampling staging DB to the final DB."""
    temp_db = str(SAMPLING_TEMP_DB or FINAL_DB)
    final_db = str(FINAL_DB)
    configs = get_runtime_game_configs()
    if modes in (None, "all"):
        selected_modes = sorted(configs)
    else:
        selected_modes = [str(mode) for mode in modes if str(mode) in configs]

    conn = None
    if existing_only:
        conn = connect_to_database(temp_db)
        if not conn:
            raise RuntimeError(f"无法连接采样临时库：{temp_db}")

    items = []
    seen_tables = set()
    try:
        for mode in selected_modes:
            config = configs.get(mode)
            if not config:
                continue
            table_config = config.get('table_config') or {}
            if not {'SOURCE_TABLE', 'FINAL_TABLE', 'REBATE_CONFIG_TABLE'}.issubset(table_config):
                continue
            final_table_name = get_table_name('FINAL_TABLE', table_config)
            if final_table_name in seen_tables:
                continue
            seen_tables.add(final_table_name)
            exists = True
            row_count = None
            if existing_only:
                exists = table_exists_exact(conn, final_table_name)
                if exists:
                    row_count = count_table_rows(conn, final_table_name)
            if not exists:
                continue
            items.append({
                'mode': mode,
                'mode_name': config.get('name', mode),
                'source_db': temp_db,
                'target_db': final_db,
                'table_name': final_table_name,
                'row_count': row_count,
                'names': {
                    'source_db_name': get_table_database('SOURCE_TABLE', table_config),
                    'final_db_name': final_db,
                    'staging_db_name': temp_db,
                    'config_db_name': get_table_database('REBATE_CONFIG_TABLE', table_config),
                    'source_table_name': get_table_name('SOURCE_TABLE', table_config),
                    'final_table_name': final_table_name,
                    'rebate_config_table_name': get_table_name('REBATE_CONFIG_TABLE', table_config),
                },
                'table_config': {
                    key: dict(value) if isinstance(value, dict) else value
                    for key, value in copy.deepcopy(table_config).items()
                },
            })
    finally:
        close_safely(conn)
    return items


def cleanup_direct_sampling_failure(*args, **kwargs):
    return _call_sampling_core('cleanup_direct_sampling_failure', *args, **kwargs)


def direct_sample_from_source(*args, **kwargs):
    return _call_sampling_core('direct_sample_from_source', *args, **kwargs)


def get_runtime_game_configs():
    configs = build_table_driven_base_game_configs()
    configs.update(get_buy_source_rebate_game_configs())
    return configs


def get_cli_menu_game_configs():
    """Return menu configs without touching dynamic database-backed table overrides."""
    _sync_runtime_selection_from_globals()
    _sync_group_weight_runtime_from_globals()
    configs = {
        mode: copy.deepcopy(config)
        for mode, config in RUNTIME_STATE.game_configs.items()
    }
    configs.update(
        buy_source_rebate_configs.build_buy_source_rebate_game_configs(
            table_prefix=RUNTIME_STATE.game_table_prefix,
            source_db=RUNTIME_STATE.source_db,
            final_db=RUNTIME_STATE.final_db,
            config_db=RUNTIME_STATE.config_db,
            random_seed=RANDOM_SEED,
            base_game_configs=configs,
            buy_enabled=RUNTIME_STATE.buy_group_enabled,
            buy_game_type=RUNTIME_STATE.buy_group_game_type,
            buy_source_suffix=RUNTIME_STATE.buy_group_source_suffix,
            extra_buy_groups=RUNTIME_STATE.extra_buy_groups,
        )
    )
    return configs


def get_runtime_sample_game_type_names():
    names = dict(SAMPLE_GAME_TYPE_NAMES)
    for mode, config in get_buy_source_rebate_game_configs().items():
        names[mode] = config['name']
    return names


def get_runtime_rebate_rules():
    return buy_source_rebate_configs.merge_buy_source_rebate_rules(
        RUNTIME_STATE.rebate_rules,
        get_buy_source_rebate_game_configs(),
    )


def get_runtime_default_rebate_rules():
    return buy_source_rebate_configs.merge_buy_source_rebate_rules(
        DEFAULT_REBATE_RULES,
        get_buy_source_rebate_game_configs(),
    )


def build_all_sampling_jobs_deps(*, append_mode=False):
    return task_dependency_factories.build_all_sampling_jobs_deps(
        _current_module_namespace(),
        append_mode=append_mode,
    )


def _sync_sampling_modes_after_success(modes):
    """Mirror completed staging results for successful sampling modes when enabled."""
    selected_modes = [str(mode) for mode in (modes or [])]
    if not selected_modes:
        print("自动镜像已开启，但本次没有成功采样的局类型，跳过镜像。")
        return False
    items = build_sampling_temp_sync_items(selected_modes, existing_only=True)
    if not items:
        print("自动镜像已开启，但中转库中没有找到本次成功采样的正式表，跳过镜像。")
        return False
    print(f"自动镜像已开启：准备将 {len(items)} 张中转表同步到目标库 {FINAL_DB}。")
    return sync_sampling_temp_results(items)


def run_all_sampling_jobs():
    results = task_entrypoints.run_all_sampling_jobs(deps=build_all_sampling_jobs_deps())
    if SAMPLING_AUTO_SYNC_TO_TARGET:
        successful_modes = [
            mode
            for mode, success in (results or {}).items()
            if success is True
        ]
        _sync_sampling_modes_after_success(successful_modes)
    return results


def run_all_supplemental_sampling_jobs():
    results = task_entrypoints.run_all_sampling_jobs(
        deps=build_all_sampling_jobs_deps(append_mode=True)
    )
    if SAMPLING_AUTO_SYNC_TO_TARGET:
        successful_modes = [
            mode
            for mode, success in (results or {}).items()
            if success is True
        ]
        _sync_sampling_modes_after_success(successful_modes)
    return results


def build_rebate_config_generation_deps():
    return task_dependency_factories.build_rebate_config_generation_deps(_current_module_namespace())


def generate_all_rebate_configs():
    return task_entrypoints.generate_all_rebate_configs(deps=build_rebate_config_generation_deps())


def build_task_preflight_deps():
    return task_dependency_factories.build_task_preflight_deps(_current_module_namespace())


def run_task_preflight(title, metadata=None):
    return task_dependency_factories.run_task_preflight(
        title,
        metadata,
        _current_module_namespace(),
    )


def write_common_configs():
    return common_config_runner.write_common_configs(deps=build_common_config_runner_deps())


def test_selected_database_connections():
    """Test the currently selected source/final/config database connections."""
    table_config = get_runtime_game_configs()['1']['table_config']
    test_database_connections(table_config)


def run_single_game_job(choice):
    """Run sampling for one selected mode."""
    success = run_single_game(get_runtime_game_configs()[choice])
    if success and SAMPLING_AUTO_SYNC_TO_TARGET:
        _sync_sampling_modes_after_success([choice])
    return success


def run_single_supplemental_game_job(choice):
    """Run supplemental sampling for one selected mode."""
    success = run_single_game(get_runtime_game_configs()[choice], append_mode=True)
    if success and SAMPLING_AUTO_SYNC_TO_TARGET:
        _sync_sampling_modes_after_success([choice])
    return success


def sync_sampling_temp_result(item):
    """Synchronize one completed sampling table from staging DB to target DB."""
    if not isinstance(item, dict):
        raise ValueError("同步采样临时库需要有效的待同步信息")
    table_config = item.get('table_config')
    names = item.get('names')
    if not table_config:
        table_name = item.get('table_name')
        for config in get_runtime_game_configs().values():
            if config['table_config'].get('FINAL_TABLE', {}).get('name') == table_name:
                table_config = config['table_config']
                break
    if not table_config:
        raise ValueError(f"无法找到待同步表配置：{item}")
    return sync_sampling_temp_table_to_target(table_config, names=names)


def sync_sampling_temp_results(items):
    """Synchronize completed staging-DB sampling tables after user confirmation."""
    results = {}
    for index, item in enumerate(items or [], start=1):
        check_cancelled()
        table_name = item.get('table_name') if isinstance(item, dict) else None
        label = table_name or f"待同步表{index}"
        log_utils.print_section(f"同步采样临时库：{label}")
        results[label] = sync_sampling_temp_result(item)
    if not results:
        print("没有待同步的采样临时库结果。")
        return False
    log_utils.print_result_summary(
        "采样临时库同步完毕，汇总结果",
        results,
        name_getter=lambda key: key,
    )
    return results


def mirror_sampling_temp_to_target():
    """Mirror existing sampling staging-DB formal tables to the target DB."""
    items = build_sampling_temp_sync_items("all", existing_only=True)
    if not items:
        print(f"采样临时库 {SAMPLING_TEMP_DB} 中没有找到当前游戏可镜像的采样正式表。")
        return False
    print(f"发现 {len(items)} 张采样中转表，将镜像到目标库 {FINAL_DB}。")
    return sync_sampling_temp_results(items)


def build_slot_app_deps_context():
    return slot_app_entrypoints.build_slot_app_deps_context(
        RUNTIME_STATE,
        _current_module_namespace(),
    )


def build_slot_app_ui_deps(context=None):
    return slot_app_entrypoints.build_slot_app_ui_deps(
        RUNTIME_STATE,
        _current_module_namespace(),
        context,
    )


def build_slot_app_settings_deps(context=None):
    return slot_app_entrypoints.build_slot_app_settings_deps(
        RUNTIME_STATE,
        _current_module_namespace(),
        context,
    )


def build_slot_app_task_deps(context=None):
    return slot_app_entrypoints.build_slot_app_task_deps(
        RUNTIME_STATE,
        _current_module_namespace(),
        context,
    )


def build_group_weight_dialog_deps():
    """Build dependencies consumed by GroupWeightRulesDialog."""
    return slot_app_entrypoints.build_group_weight_dialog_deps(
        RUNTIME_STATE,
        _current_module_namespace(),
    )


def build_slot_process_app_deps():
    """Build dependencies consumed by SlotProcessApp."""
    return slot_app_entrypoints.build_slot_process_app_deps(
        RUNTIME_STATE,
        _current_module_namespace(),
    )


def run_gui():
    return slot_app_entrypoints.run_gui(
        RUNTIME_STATE,
        _current_module_namespace(),
    )


def main():
    if not load_cli_settings():
        return False
    game_configs = get_cli_menu_game_configs()
    deps = SimpleNamespace(
        game_configs=game_configs,
        run_all_sampling_jobs=run_all_sampling_jobs,
        run_all_supplemental_sampling_jobs=run_all_supplemental_sampling_jobs,
        generate_all_rebate_configs=generate_all_rebate_configs,
        write_common_configs=write_common_configs,
        run_single_game=run_single_game,
        run_single_game_by_choice=run_single_game_job,
        run_single_supplemental_game_job=run_single_supplemental_game_job,
    )
    return run_cli(deps)


def clean_sampling_task_states(max_age_days=sampling_task_state.DEFAULT_COMPLETED_STATE_RETENTION_DAYS, *, dry_run=True):
    removed = sampling_task_state.cleanup_completed_states(max_age_days=max_age_days, dry_run=dry_run)
    if dry_run:
        print(f"将清理 {len(removed)} 个已完成采样任务状态文件（保留 {int(max_age_days)} 天内记录）；追加 --yes 才会实际删除")
    else:
        print(f"已清理 {len(removed)} 个已完成采样任务状态文件（保留 {int(max_age_days)} 天内记录）")
    return removed


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--clean-sampling-tasks":
        clean_args = [arg for arg in sys.argv[2:] if arg != "--yes"]
        retention_days = int(clean_args[0]) if clean_args else sampling_task_state.DEFAULT_COMPLETED_STATE_RETENTION_DAYS
        clean_sampling_task_states(retention_days, dry_run="--yes" not in sys.argv[2:])
    elif len(sys.argv) > 1 and sys.argv[1] == "--cli":
        main()
    else:
        run_gui()



