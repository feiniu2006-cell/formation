"""Runtime game/table configuration helpers."""

from copy import deepcopy
from types import SimpleNamespace

from formation_tool.core import buy_group_config
from formation_tool.core import formation_defaults


DEFAULT_SOURCE_DB = formation_defaults.DEFAULT_SOURCE_DB
DEFAULT_FINAL_DB = formation_defaults.DEFAULT_FINAL_DB
DEFAULT_CONFIG_DB = formation_defaults.DEFAULT_CONFIG_DB
DEFAULT_GAME_TABLE_VENDOR = formation_defaults.DEFAULT_GAME_TABLE_VENDOR
DEFAULT_GAME_TABLE_GAME_ID = formation_defaults.DEFAULT_GAME_TABLE_GAME_ID

SPECIAL_WEIGHT_TABLE = 'game_group_special_weight_config'
FREE_GAME_CONFIG_TABLE = 'game_group_free_game_config'
BET_AMOUNT_TABLE = 'game_bet_amount_config'

VENDOR_TYPE_MAP = {
    'pg': 1,
    'vg': 2,
    'jili': 3,
}

GAME_DEFINITION_SPECS = {
    '1': ('普通局', 'formation', 'rebate_count'),
    '2': ('特殊局', 'special_formation', 'rebate_special_count'),
    '3': ('免费局', 'free_formation', 'rebate_free_count'),
    '6': ('ex普通局', 'ex_formation', 'rebate_ex_count'),
    '7': ('ex特殊局', 'ex_special_formation', 'rebate_ex_special_count'),
    '8': ('ex免费局', 'ex_free_formation', 'rebate_ex_free_count'),
}


def _clone(value):
    """Return an isolated copy for mutable runtime values."""
    return deepcopy(value)


def _read(namespace, name, default=None):
    if isinstance(namespace, dict):
        return namespace.get(name, default)
    return getattr(namespace, name, default)


def _assign(namespace, name, value):
    if isinstance(namespace, dict):
        namespace[name] = value
    else:
        setattr(namespace, name, value)


def get_weight_type_id(vendor, vendor_type_map=None):
    return (vendor_type_map or VENDOR_TYPE_MAP).get(vendor)


def build_game_configs(vendor, game_id, source_db, final_db, config_db, *, random_seed):
    """Build source/final/rebate-count table config for the current game."""
    table_prefix = f'{vendor}_{game_id}_'
    game_defs = {
        key: (
            name,
            f'{table_prefix}{formation_suffix}',
            f'{table_prefix}{rebate_suffix}',
            'rebate = {target_rebate}{end_field_opt}',
        )
        for key, (name, formation_suffix, rebate_suffix) in GAME_DEFINITION_SPECS.items()
    }
    game_configs = {
        key: {
            'name': name,
            'table_config': {
                'SOURCE_TABLE': {'name': table, 'database': source_db},
                'FINAL_TABLE': {'name': table, 'database': final_db},
                'REBATE_CONFIG_TABLE': {'name': cfg_table, 'database': config_db},
            },
            'sample_conditions': {
                'where_clause': where_clause,
                'random_seed': random_seed,
            },
        }
        for key, (name, table, cfg_table, where_clause) in game_defs.items()
    }
    return table_prefix, game_defs, game_configs


def build_runtime_values(
    vendor,
    game_id,
    source_db,
    final_db,
    config_db,
    *,
    database_configs,
    random_seed,
    vendor_type_map=None,
):
    """Validate UI selections and return the derived runtime values."""
    vendor_type_map = vendor_type_map or VENDOR_TYPE_MAP
    vendor = str(vendor).strip()
    game_id = str(game_id).strip()
    source_db = str(source_db).strip()
    final_db = str(final_db).strip()
    config_db = str(config_db).strip()

    if vendor not in vendor_type_map:
        raise ValueError(f"未知厂商: {vendor}，可选厂商: {list(vendor_type_map.keys())}")
    if not game_id:
        raise ValueError("游戏编号不能为空")
    for label, db_name in (('源库', source_db), ('目标库', final_db), ('配置库', config_db)):
        if db_name not in database_configs:
            raise ValueError(f"{label}配置不存在: {db_name}，可选数据库: {list(database_configs.keys())}")

    table_prefix, game_defs, game_configs = build_game_configs(
        vendor,
        game_id,
        source_db,
        final_db,
        config_db,
        random_seed=random_seed,
    )
    return SimpleNamespace(
        vendor=vendor,
        game_id=game_id,
        source_db=source_db,
        final_db=final_db,
        config_db=config_db,
        weight_config_db=final_db,
        weight_type_id=vendor_type_map[vendor],
        game_table_prefix=table_prefix,
        game_defs=game_defs,
        game_configs=game_configs,
    )


class RuntimeState:
    """Mutable runtime snapshot shared by the main script and split modules."""

    def __init__(self):
        self.database_configs = {}
        self.max_db_retries = 3
        self.db_retry_delay = 5

        self.vendor = DEFAULT_GAME_TABLE_VENDOR
        self.game_id = DEFAULT_GAME_TABLE_GAME_ID
        self.source_db = DEFAULT_SOURCE_DB
        self.final_db = DEFAULT_FINAL_DB
        self.config_db = DEFAULT_CONFIG_DB
        self.weight_config_db = DEFAULT_FINAL_DB
        self.weight_type_id = None
        self.game_table_prefix = ''
        self.game_defs = {}
        self.game_configs = {}

        self.special_weight_by_last_digit = formation_defaults.clone_int_map(
            formation_defaults.DEFAULT_SPECIAL_WEIGHT_BY_LAST_DIGIT
        )
        self.free_weight_by_last_digit = formation_defaults.clone_int_map(
            formation_defaults.DEFAULT_FREE_WEIGHT_BY_LAST_DIGIT
        )

        self.rebate_rules = formation_defaults.clone_rule_map(formation_defaults.REBATE_RULES)
        self.group_weight_rules = formation_defaults.clone_rule_map(formation_defaults.GROUP_WEIGHT_RULES)
        self.sampling_append_mode = formation_defaults.DEFAULT_SAMPLING_APPEND_MODE
        self.rebate_config_direct_count_modes = set(formation_defaults.DEFAULT_REBATE_CONFIG_DIRECT_COUNT_MODES)
        self.special_group_target_rtp = formation_defaults.DEFAULT_SPECIAL_GROUP_TARGET_RTP
        self.ex_group_target_rtps = formation_defaults.clone_ex_group_target_rtps()
        self.buy_group_enabled = formation_defaults.DEFAULT_BUY_GROUP_ENABLED
        self.ex_buy_group_enabled = formation_defaults.DEFAULT_EX_BUY_GROUP_ENABLED
        self.buy_group_game_type = formation_defaults.DEFAULT_BUY_GROUP_GAME_TYPE
        self.buy_group_multiplier = formation_defaults.DEFAULT_BUY_GROUP_MULTIPLIER
        self.buy_group_source_suffix = formation_defaults.DEFAULT_BUY_GROUP_SOURCE_SUFFIX
        self.ex_group_multiplier = formation_defaults.DEFAULT_EX_GROUP_MULTIPLIER
        self.ex_source_suffixes = formation_defaults.clone_ex_source_suffixes()
        self.extra_buy_groups = formation_defaults.clone_extra_buy_groups()
        self.buy_groups = self.build_buy_groups()

        self.external_config_source = None
        self.external_config_load_error = None
        self.source_formation_check_statuses = {}
        self.config_warnings = []

    def sync_database_from(self, namespace):
        self.database_configs = _clone(_read(namespace, 'DATABASE_CONFIGS', self.database_configs))
        self.max_db_retries = _read(namespace, 'MAX_DB_RETRIES', self.max_db_retries)
        self.db_retry_delay = _read(namespace, 'DB_RETRY_DELAY', self.db_retry_delay)

    def sync_runtime_selection_from(self, namespace):
        self.vendor = _read(namespace, 'GAME_TABLE_VENDOR', self.vendor)
        self.game_id = _read(namespace, 'GAME_TABLE_GAME_ID', self.game_id)
        self.source_db = _read(namespace, 'SOURCE_DB', self.source_db)
        self.final_db = _read(namespace, 'FINAL_DB', self.final_db)
        self.config_db = _read(namespace, 'CONFIG_DB', self.config_db)
        self.weight_config_db = _read(namespace, 'WEIGHT_CONFIG_DB', self.weight_config_db)
        self.weight_type_id = _read(namespace, 'WEIGHT_TYPE_ID', self.weight_type_id)
        self.game_table_prefix = _read(namespace, 'GAME_TABLE_PREFIX', self.game_table_prefix)
        self.game_defs = _clone(_read(namespace, '_GAME_DEFS', self.game_defs))
        self.game_configs = _clone(_read(namespace, 'GAME_CONFIGS', self.game_configs))

    def sync_trigger_weights_from(self, namespace):
        self.special_weight_by_last_digit = _clone(
            _read(namespace, 'SPECIAL_WEIGHT_BY_LAST_DIGIT', self.special_weight_by_last_digit)
        )
        self.free_weight_by_last_digit = _clone(
            _read(namespace, 'FREE_WEIGHT_BY_LAST_DIGIT', self.free_weight_by_last_digit)
        )

    def sync_rebate_runtime_from(self, namespace):
        self.rebate_rules = _clone(_read(namespace, 'REBATE_RULES', self.rebate_rules))
        self.rebate_config_direct_count_modes = set(
            _read(namespace, 'REBATE_CONFIG_DIRECT_COUNT_MODES', self.rebate_config_direct_count_modes)
        )

    def sync_sampling_runtime_from(self, namespace):
        self.sampling_append_mode = bool(_read(namespace, 'SAMPLING_APPEND_MODE', self.sampling_append_mode))

    def sync_group_weight_runtime_from(self, namespace):
        self.group_weight_rules = _clone(_read(namespace, 'GROUP_WEIGHT_RULES', self.group_weight_rules))
        self.special_group_target_rtp = _read(namespace, 'SPECIAL_GROUP_TARGET_RTP', self.special_group_target_rtp)
        self.ex_group_target_rtps = _clone(_read(namespace, 'EX_GROUP_TARGET_RTPS', self.ex_group_target_rtps))
        self.ex_group_multiplier = _read(namespace, 'EX_GROUP_MULTIPLIER', self.ex_group_multiplier)
        self.ex_source_suffixes = _clone(_read(namespace, 'EX_SOURCE_SUFFIXES', self.ex_source_suffixes))
        self.ex_buy_group_enabled = bool(_read(namespace, 'EX_BUY_GROUP_ENABLED', self.ex_buy_group_enabled))

        buy_groups = _read(namespace, 'BUY_GROUPS', None)
        if buy_groups is not None:
            self.apply_buy_groups(buy_groups)
            return

        self.buy_group_enabled = bool(_read(namespace, 'BUY_GROUP_ENABLED', self.buy_group_enabled))
        self.buy_group_game_type = _read(namespace, 'BUY_GROUP_GAME_TYPE', self.buy_group_game_type)
        self.buy_group_multiplier = _read(namespace, 'BUY_GROUP_MULTIPLIER', self.buy_group_multiplier)
        self.buy_group_source_suffix = _read(namespace, 'BUY_GROUP_SOURCE_SUFFIX', self.buy_group_source_suffix)
        self.extra_buy_groups = _clone(_read(namespace, 'EXTRA_BUY_GROUPS', self.extra_buy_groups))
        self.sync_buy_groups_from_legacy()

    def sync_external_status_from(self, namespace):
        self.external_config_source = _read(namespace, 'EXTERNAL_CONFIG_SOURCE', self.external_config_source)
        self.external_config_load_error = _read(namespace, 'EXTERNAL_CONFIG_LOAD_ERROR', self.external_config_load_error)
        self.source_formation_check_statuses = _clone(
            _read(namespace, 'SOURCE_FORMATION_CHECK_STATUSES', self.source_formation_check_statuses)
        )
        self.config_warnings = _clone(_read(namespace, 'CONFIG_WARNINGS', self.config_warnings))

    def sync_all_from(self, namespace):
        self.sync_database_from(namespace)
        self.sync_runtime_selection_from(namespace)
        self.sync_trigger_weights_from(namespace)
        self.sync_rebate_runtime_from(namespace)
        self.sync_sampling_runtime_from(namespace)
        self.sync_group_weight_runtime_from(namespace)
        self.sync_external_status_from(namespace)

    def apply_runtime_values(self, values):
        self.vendor = values.vendor
        self.game_id = values.game_id
        self.source_db = values.source_db
        self.final_db = values.final_db
        self.config_db = values.config_db
        self.weight_config_db = values.weight_config_db
        self.weight_type_id = values.weight_type_id
        self.game_table_prefix = values.game_table_prefix
        self.game_defs = _clone(values.game_defs)
        self.game_configs = _clone(values.game_configs)

    def build_buy_groups(self):
        return buy_group_config.build_buy_groups_from_legacy(
            buy_enabled=self.buy_group_enabled,
            buy_game_type=self.buy_group_game_type,
            buy_multiplier=self.buy_group_multiplier,
            buy_source_suffix=self.buy_group_source_suffix,
            extra_buy_groups=self.extra_buy_groups,
        )

    def sync_buy_groups_from_legacy(self):
        self.buy_groups = self.build_buy_groups()
        return self.buy_groups

    def apply_buy_groups(self, groups):
        split = buy_group_config.split_buy_groups_to_legacy(
            groups,
            default_buy_enabled=self.buy_group_enabled,
            default_buy_game_type=self.buy_group_game_type,
            default_buy_multiplier=self.buy_group_multiplier,
            default_buy_source_suffix=self.buy_group_source_suffix,
        )
        self.buy_group_enabled = split['buy_enabled']
        self.buy_group_game_type = split['buy_game_type']
        self.buy_group_multiplier = split['buy_multiplier']
        self.buy_group_source_suffix = split['buy_source_suffix']
        self.extra_buy_groups = _clone(split['extra_buy_groups'])
        self.buy_groups = _clone(split['buy_groups'])
        return split

    def to_legacy_globals(self, namespace):
        _assign(namespace, 'DATABASE_CONFIGS', _clone(self.database_configs))
        _assign(namespace, 'MAX_DB_RETRIES', self.max_db_retries)
        _assign(namespace, 'DB_RETRY_DELAY', self.db_retry_delay)
        _assign(namespace, 'GAME_TABLE_VENDOR', self.vendor)
        _assign(namespace, 'GAME_TABLE_GAME_ID', self.game_id)
        _assign(namespace, 'SOURCE_DB', self.source_db)
        _assign(namespace, 'FINAL_DB', self.final_db)
        _assign(namespace, 'CONFIG_DB', self.config_db)
        _assign(namespace, 'WEIGHT_CONFIG_DB', self.weight_config_db)
        _assign(namespace, 'WEIGHT_TYPE_ID', self.weight_type_id)
        _assign(namespace, 'GAME_TABLE_PREFIX', self.game_table_prefix)
        _assign(namespace, '_GAME_DEFS', _clone(self.game_defs))
        _assign(namespace, 'GAME_CONFIGS', _clone(self.game_configs))
        _assign(namespace, 'SPECIAL_WEIGHT_BY_LAST_DIGIT', _clone(self.special_weight_by_last_digit))
        _assign(namespace, 'FREE_WEIGHT_BY_LAST_DIGIT', _clone(self.free_weight_by_last_digit))
        _assign(namespace, 'REBATE_RULES', _clone(self.rebate_rules))
        _assign(namespace, 'GROUP_WEIGHT_RULES', _clone(self.group_weight_rules))
        _assign(namespace, 'SAMPLING_APPEND_MODE', self.sampling_append_mode)
        _assign(namespace, 'REBATE_CONFIG_DIRECT_COUNT_MODES', set(self.rebate_config_direct_count_modes))
        _assign(namespace, 'SPECIAL_GROUP_TARGET_RTP', self.special_group_target_rtp)
        _assign(namespace, 'EX_GROUP_TARGET_RTPS', _clone(self.ex_group_target_rtps))
        _assign(namespace, 'BUY_GROUP_ENABLED', self.buy_group_enabled)
        _assign(namespace, 'EX_BUY_GROUP_ENABLED', self.ex_buy_group_enabled)
        _assign(namespace, 'BUY_GROUP_GAME_TYPE', self.buy_group_game_type)
        _assign(namespace, 'BUY_GROUP_MULTIPLIER', self.buy_group_multiplier)
        _assign(namespace, 'BUY_GROUP_SOURCE_SUFFIX', self.buy_group_source_suffix)
        _assign(namespace, 'EX_GROUP_MULTIPLIER', self.ex_group_multiplier)
        _assign(namespace, 'EX_SOURCE_SUFFIXES', _clone(self.ex_source_suffixes))
        _assign(namespace, 'EXTRA_BUY_GROUPS', _clone(self.extra_buy_groups))
        _assign(namespace, 'BUY_GROUPS', _clone(self.buy_groups))
        _assign(namespace, 'EXTERNAL_CONFIG_SOURCE', self.external_config_source)
        _assign(namespace, 'EXTERNAL_CONFIG_LOAD_ERROR', self.external_config_load_error)
        _assign(namespace, 'SOURCE_FORMATION_CHECK_STATUSES', _clone(self.source_formation_check_statuses))
        _assign(namespace, 'CONFIG_WARNINGS', _clone(self.config_warnings))

    def runtime_dict(self):
        return {
            'vendor': self.vendor,
            'game_id': self.game_id,
            'source_db': self.source_db,
            'final_db': self.final_db,
            'config_db': self.config_db,
        }

    def trigger_weights_dict(self):
        return {
            'special_0': self.special_weight_by_last_digit.get(0, 0),
            'special_1': self.special_weight_by_last_digit.get(1, 0),
            'free_0': self.free_weight_by_last_digit.get(0, 0),
            'free_1': self.free_weight_by_last_digit.get(1, 0),
        }
