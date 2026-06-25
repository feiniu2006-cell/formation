"""Default editable rules and startup options for the formation tool."""


DEFAULT_RANDOM_SEED = 108
DEFAULT_LOW_VOLUME_REBATE_COUNT_THRESHOLD = 200000
DEFAULT_SAMPLE_ID_FETCH_CHUNK_SIZE = 500
DEFAULT_REBATE_CONFIG_REBATE_ZERO_COUNT_LIMIT = 5000
DEFAULT_REBATE_CONFIG_POSITIVE_REBATE_COUNT_LIMIT = 200
DEFAULT_REBATE_CONFIG_MAX_REBATE = 1099999
DEFAULT_REBATE_CONFIG_DIRECT_COUNT_TIER_LIMITS = (
    {'rebate': 0, 'count': DEFAULT_REBATE_CONFIG_REBATE_ZERO_COUNT_LIMIT},
    {'rebate_min': 1, 'rebate_max': 999, 'count': 200},
    {'rebate_min': 1000, 'rebate_max': 9999, 'count': 100},
    {'rebate_min': 10000, 'rebate_max': 19999, 'count': 50},
    {'rebate_min': 20000, 'rebate_max': 49999, 'count': 20},
    {'rebate_min': 50000, 'rebate_max': 99999, 'count': 10},
    {'rebate_min': 100000, 'rebate_max': 499999, 'count': 5},
    {'rebate_min': 500000, 'rebate_max': DEFAULT_REBATE_CONFIG_MAX_REBATE, 'count': 5},
)
DEFAULT_REBATE_CONFIG_COUNT_LIMITS = {
    'rebate_zero': DEFAULT_REBATE_CONFIG_REBATE_ZERO_COUNT_LIMIT,
    'rebate_positive': DEFAULT_REBATE_CONFIG_POSITIVE_REBATE_COUNT_LIMIT,
    'max_rebate': DEFAULT_REBATE_CONFIG_MAX_REBATE,
    'direct_count_tiers': DEFAULT_REBATE_CONFIG_DIRECT_COUNT_TIER_LIMITS,
}
DEFAULT_REBATE_CONFIG_DIRECT_COUNT_MODES = set()
DEFAULT_SAMPLING_APPEND_MODE = False
DEFAULT_SAMPLING_DETAILED_LOG = False

DEFAULT_SOURCE_DB = ''
DEFAULT_FINAL_DB = 'DB1'
DEFAULT_CONFIG_DB = 'MY'
DEFAULT_GAME_TABLE_VENDOR = ''
DEFAULT_GAME_TABLE_GAME_ID = ''
DEFAULT_SAMPLING_USE_TEMP_DB = True
DEFAULT_SAMPLING_TEMP_DB = 'MY'

DEFAULT_WEIGHT_GROUP_IDS = (
    10000, 10001, 9900, 9901, 9800, 9801,
    9700, 9701, 9650, 9651, 9600, 9601,
    9500, 9501, 9400, 9401, 9300, 9301,
    9200, 9201, 9100, 9101, 9000, 9001,
)

DEFAULT_SPECIAL_WEIGHT_BY_LAST_DIGIT = {
    0: 100,
    1: 200,
}
DEFAULT_FREE_WEIGHT_BY_LAST_DIGIT = {
    0: 50,
    1: 100,
}

DEFAULT_SPECIAL_GROUP_TARGET_RTP = 6
DEFAULT_EX_GROUP_TARGET_RTPS = {}
DEFAULT_BUY_GROUP_ENABLED = False
DEFAULT_EX_BUY_GROUP_ENABLED = False
DEFAULT_EX_BUY_GROUP_GAME_TYPE = 98
DEFAULT_EX_BUY_GROUP_SOURCE_SUFFIX = ''
DEFAULT_BUY_GROUP_GAME_TYPE = 99
DEFAULT_BUY_GROUP_MULTIPLIER = 75
DEFAULT_BUY_GROUP_SOURCE_SUFFIX = 'free_formation'
DEFAULT_EX_GROUP_MULTIPLIER = 1.5
DEFAULT_EXTRA_BUY_GROUPS = []
DEFAULT_EX_SOURCE_SUFFIXES = {}


def clone_rule_map(rules):
    """Return a mutable deep-enough copy of a rules mapping."""
    return {
        str(mode): [dict(rule) for rule in mode_rules]
        for mode, mode_rules in rules.items()
    }


def clone_int_map(value):
    """Return a mutable int-keyed copy for editable weight mappings."""
    return {int(key): int(item) for key, item in value.items()}


def clone_count_limits():
    """Return a mutable copy of default rebate-count generation limits."""
    limits = dict(DEFAULT_REBATE_CONFIG_COUNT_LIMITS)
    limits['direct_count_tiers'] = clone_direct_count_tiers()
    return limits


def clone_direct_count_tiers(tiers=None):
    """Return a mutable copy of direct-count tier caps."""
    return [
        dict(rule)
        for rule in (DEFAULT_REBATE_CONFIG_DIRECT_COUNT_TIER_LIMITS if tiers is None else tiers)
    ]


def clone_extra_buy_groups():
    """Return a mutable copy of default extra buy-group rows."""
    return [dict(group) for group in DEFAULT_EXTRA_BUY_GROUPS]


def clone_ex_source_suffixes(value=None):
    """Return a mutable copy of manual ex source suffix overrides."""
    return {
        str(mode): str(suffix)
        for mode, suffix in (DEFAULT_EX_SOURCE_SUFFIXES if value is None else value).items()
        if str(suffix or '').strip()
    }


def clone_ex_group_target_rtps(value=None):
    """Return a mutable copy of manual ex special/free display RTP targets."""
    return {
        str(mode): float(target)
        for mode, target in (DEFAULT_EX_GROUP_TARGET_RTPS if value is None else value).items()
        if str(target or '').strip()
    }


# ==================  rebate 采样规则配置 ==================
# 每条规则可使用以下字段：
#   {'rebate': X, 'count': N}
#       — 精确匹配单个 rebate
#   {'rebate_min': X, 'rebate_max': Y, 'count': N}
#       — 匹配 rebate 范围 [X, Y]，匹配范围内每个 rebate 采样 count 条
#   {'rebate_min': X, 'rebate_max': Y, 'count': N, 'rebate_limit_min': A, 'rebate_limit_max': B}
#       — 同上，但限制该范围内选取的 rebate 数量：至少 A 个，最多 B 个（按 total 降序取）
#       若可用 rebate 数量不足 A 个，发出警告并取全部可用；超过 B 个则截断到 B 个
#   {'rebate_min': X, 'rebate_max': Y, 'count': N, 'rebate_limit_min': A, 'rebate_limit_max': B, 'smooth_buckets': S}
#       — 同上，并开启线性平滑模式：将 [X, Y] 平分为 S 个子区间
#         每个子区间最多取 B//S 个 rebate，按 rebate 小到大等间距采样（而非堆集到高频区）
# 未匹配任何规则的 rebate 将被跳过不写入配置表
# count 超过该 rebate 实际数据量时自动截断到实际数量
# 所有规则均可加入 'min_total': T 字段：该 rebate 的实际数据量小于 T 时将被跳过
REBATE_RULES = {
    '1': [  # 普通局
        {'rebate': 0,   'count': 2000},
        {'rebate_min': 1, 'rebate_max': 999, 'count': 100, 'rebate_limit_min': 100, 'rebate_limit_max': 200, 'smooth_buckets': 10,'min_total': 5},
        {'rebate_min': 1000, 'rebate_max': 9999, 'count': 100, 'rebate_limit_min': 90, 'rebate_limit_max': 200, 'smooth_buckets': 9,'min_total': 5},
        {'rebate_min': 10000, 'rebate_max': 19999, 'count': 50, 'rebate_limit_min': 40, 'rebate_limit_max': 80, 'smooth_buckets': 6,'min_total': 5},
        {'rebate_min': 20000, 'rebate_max': 49999, 'count': 20, 'rebate_limit_min': 30, 'rebate_limit_max': 60, 'smooth_buckets': 4,'min_total': 2},
        {'rebate_min': 50000, 'rebate_max': 99999, 'count': 10, 'rebate_limit_min': 20, 'rebate_limit_max': 40, 'smooth_buckets': 1,'min_total': 2},
        {'rebate_min': 100000, 'rebate_max': 599999, 'count': 5, 'rebate_limit_min': 10, 'rebate_limit_max': 20, 'smooth_buckets': 1,'min_total': 1},
        {'rebate_min': 600000, 'rebate_max': 1099999, 'count': 5, 'rebate_limit_min': 5, 'rebate_limit_max': 10, 'smooth_buckets': 1,'min_total': 1},
    ],
    '2': [  # 特殊局
        {'rebate': 0,   'count': 2000},
        {'rebate_min': 1, 'rebate_max': 999, 'count': 100, 'rebate_limit_min': 100, 'rebate_limit_max': 200, 'smooth_buckets': 10,'min_total': 5},
        {'rebate_min': 1000, 'rebate_max': 9999, 'count': 100, 'rebate_limit_min': 90, 'rebate_limit_max': 200, 'smooth_buckets': 9,'min_total': 5},
        {'rebate_min': 10000, 'rebate_max': 19999, 'count': 50, 'rebate_limit_min': 40, 'rebate_limit_max': 80, 'smooth_buckets': 6,'min_total': 5},
        {'rebate_min': 20000, 'rebate_max': 49999, 'count': 20, 'rebate_limit_min': 30, 'rebate_limit_max': 60, 'smooth_buckets': 4,'min_total': 2},
        {'rebate_min': 50000, 'rebate_max': 99999, 'count': 10, 'rebate_limit_min': 20, 'rebate_limit_max': 40, 'smooth_buckets': 1,'min_total': 2},
        {'rebate_min': 100000, 'rebate_max': 599999, 'count': 5, 'rebate_limit_min': 10, 'rebate_limit_max': 20, 'smooth_buckets': 1,'min_total': 1},
        {'rebate_min': 600000, 'rebate_max': 1099999, 'count': 5, 'rebate_limit_min': 5, 'rebate_limit_max': 10, 'smooth_buckets': 1,'min_total': 1},
    ],
    '3': [  # 免费局
        {'rebate_min': 5000, 'rebate_max': 9999, 'count': 100, 'rebate_limit_min': 80, 'rebate_limit_max': 160, 'smooth_buckets': 8,'min_total': 5},
        {'rebate_min': 10000, 'rebate_max': 49999, 'count': 50, 'rebate_limit_min': 40, 'rebate_limit_max': 80, 'smooth_buckets': 5,'min_total': 5},
        {'rebate_min': 50000, 'rebate_max': 99999, 'count': 20, 'rebate_limit_min': 30, 'rebate_limit_max': 60, 'smooth_buckets': 3,'min_total': 5},
        {'rebate_min': 100000, 'rebate_max': 599999, 'count': 10, 'rebate_limit_min': 20, 'rebate_limit_max': 40, 'smooth_buckets': 1,'min_total': 2},
        {'rebate_min': 600000, 'rebate_max': 1099999, 'count': 5, 'rebate_limit_min': 10, 'rebate_limit_max': 20, 'smooth_buckets': 1,'min_total': 1},
    ],
    '6': [  # ex普通局
        {'rebate': 0,   'count': 2000},
        {'rebate_min': 1, 'rebate_max': 999, 'count': 100, 'rebate_limit_min': 100, 'rebate_limit_max': 200, 'smooth_buckets': 10,'min_total': 5},
        {'rebate_min': 1000, 'rebate_max': 9999, 'count': 100, 'rebate_limit_min': 90, 'rebate_limit_max': 200, 'smooth_buckets': 9,'min_total': 5},
        {'rebate_min': 10000, 'rebate_max': 19999, 'count': 50, 'rebate_limit_min': 40, 'rebate_limit_max': 80, 'smooth_buckets': 6,'min_total': 5},
        {'rebate_min': 20000, 'rebate_max': 49999, 'count': 20, 'rebate_limit_min': 30, 'rebate_limit_max': 60, 'smooth_buckets': 4,'min_total': 2},
        {'rebate_min': 50000, 'rebate_max': 99999, 'count': 10, 'rebate_limit_min': 20, 'rebate_limit_max': 40, 'smooth_buckets': 1,'min_total': 2},
        {'rebate_min': 100000, 'rebate_max': 599999, 'count': 5, 'rebate_limit_min': 10, 'rebate_limit_max': 20, 'smooth_buckets': 1,'min_total': 1},
        {'rebate_min': 600000, 'rebate_max': 1099999, 'count': 5, 'rebate_limit_min': 5, 'rebate_limit_max': 10, 'smooth_buckets': 1,'min_total': 1},
    ],
    '7': [  # ex特殊局
        {'rebate': 0,   'count': 2000},
        {'rebate_min': 1, 'rebate_max': 999, 'count': 100, 'rebate_limit_min': 100, 'rebate_limit_max': 200, 'smooth_buckets': 10,'min_total': 5},
        {'rebate_min': 1000, 'rebate_max': 9999, 'count': 100, 'rebate_limit_min': 90, 'rebate_limit_max': 200, 'smooth_buckets': 9,'min_total': 5},
        {'rebate_min': 10000, 'rebate_max': 19999, 'count': 50, 'rebate_limit_min': 40, 'rebate_limit_max': 80, 'smooth_buckets': 6,'min_total': 5},
        {'rebate_min': 20000, 'rebate_max': 49999, 'count': 20, 'rebate_limit_min': 30, 'rebate_limit_max': 60, 'smooth_buckets': 4,'min_total': 2},
        {'rebate_min': 50000, 'rebate_max': 99999, 'count': 10, 'rebate_limit_min': 20, 'rebate_limit_max': 40, 'smooth_buckets': 1,'min_total': 2},
        {'rebate_min': 100000, 'rebate_max': 599999, 'count': 5, 'rebate_limit_min': 10, 'rebate_limit_max': 20, 'smooth_buckets': 1,'min_total': 1},
        {'rebate_min': 600000, 'rebate_max': 1099999, 'count': 5, 'rebate_limit_min': 5, 'rebate_limit_max': 10, 'smooth_buckets': 1,'min_total': 1},
    ],
    '8': [  # ex免费局
        {'rebate_min': 5000, 'rebate_max': 9999, 'count': 100, 'rebate_limit_min': 80, 'rebate_limit_max': 160, 'smooth_buckets': 8,'min_total': 5},
        {'rebate_min': 10000, 'rebate_max': 49999, 'count': 50, 'rebate_limit_min': 40, 'rebate_limit_max': 80, 'smooth_buckets': 5,'min_total': 5},
        {'rebate_min': 50000, 'rebate_max': 99999, 'count': 20, 'rebate_limit_min': 30, 'rebate_limit_max': 60, 'smooth_buckets': 3,'min_total': 5},
        {'rebate_min': 100000, 'rebate_max': 599999, 'count': 10, 'rebate_limit_min': 10, 'rebate_limit_max': 20, 'smooth_buckets': 1,'min_total': 2},
        {'rebate_min': 600000, 'rebate_max': 1099999, 'count': 5, 'rebate_limit_min': 5, 'rebate_limit_max': 10, 'smooth_buckets': 1,'min_total': 1},
    ],
    # '99': [  # ex局
    #     {'rebate_min': 5000, 'rebate_max': 9999, 'count': 100, 'rebate_limit_min': 80, 'rebate_limit_max': 160, 'smooth_buckets': 8,'min_total': 50},
    #     {'rebate_min': 10000, 'rebate_max': 49999, 'count': 50, 'rebate_limit_min': 40, 'rebate_limit_max': 80, 'smooth_buckets': 5,'min_total': 20},
    #     {'rebate_min': 50000, 'rebate_max': 99999, 'count': 20, 'rebate_limit_min': 30, 'rebate_limit_max': 60, 'smooth_buckets': 3,'min_total': 10},
    #     {'rebate_min': 100000, 'rebate_max': 159999, 'count': 5, 'rebate_limit_min': 5, 'rebate_limit_max': 20, 'smooth_buckets': 2,'min_total': 5},
    # ],
}


# ==================  group_weight 区间权重配置 ==================
# 每个局类型各自维护一套区间规则，区间按“当前 rebate_min <= rebate < 下一 rebate_min”匹配。
# weight 为 0 的 rebate 也写入 group_weight 表，但不参与 RTP 权重计算。
GROUP_WEIGHT_RULES = {
    '1': [  # 普通局
        {'rebate_min': 0,       'weight': 0},
        {'rebate_min': 1,       'weight': 10000},
        {'rebate_min': 1000,    'weight': 5000},
        {'rebate_min': 2000,    'weight': 5000},
        {'rebate_min': 3000,    'weight': 4000},
        {'rebate_min': 4000,    'weight': 4000},
        {'rebate_min': 5000,    'weight': 3000},
        {'rebate_min': 6000,    'weight': 3000},
        {'rebate_min': 7000,    'weight': 2000},
        {'rebate_min': 8000,    'weight': 2000},
        {'rebate_min': 9000,    'weight': 1000},
        {'rebate_min': 10000,   'weight': 500},
        {'rebate_min': 20000,   'weight': 250},
        {'rebate_min': 30000,   'weight': 100},
        {'rebate_min': 40000,   'weight': 20},
        {'rebate_min': 50000,   'weight': 10},
        {'rebate_min': 60000,   'weight': 5},
        {'rebate_min': 70000,   'weight': 5},
        {'rebate_min': 80000,   'weight': 2},
        {'rebate_min': 90000,   'weight': 2},
        {'rebate_min': 100000,  'weight': 1},
        {'rebate_min': 200000,  'weight': 1},
        {'rebate_min': 300000,  'weight': 1},
        {'rebate_min': 400000,  'weight': 1},
        {'rebate_min': 500000,  'weight': 1},
        {'rebate_min': 1000000, 'weight': 0},
    ],
    '2': [  # 特殊局
        {'rebate_min': 0,       'weight': 0},
        {'rebate_min': 1,       'weight': 10000},
        {'rebate_min': 1000,    'weight': 9000},
        {'rebate_min': 2000,    'weight': 8000},
        {'rebate_min': 3000,    'weight': 7000},
        {'rebate_min': 4000,    'weight': 6000},
        {'rebate_min': 5000,    'weight': 5000},
        {'rebate_min': 6000,    'weight': 4000},
        {'rebate_min': 7000,    'weight': 3000},
        {'rebate_min': 8000,    'weight': 2000},
        {'rebate_min': 9000,    'weight': 2000},
        {'rebate_min': 10000,   'weight': 1000},
        {'rebate_min': 20000,   'weight': 500},
        {'rebate_min': 30000,   'weight': 250},
        {'rebate_min': 40000,   'weight': 100},
        {'rebate_min': 50000,   'weight': 50},
        {'rebate_min': 60000,   'weight': 20},
        {'rebate_min': 70000,   'weight': 10},
        {'rebate_min': 80000,   'weight': 5},
        {'rebate_min': 90000,   'weight': 5},
        {'rebate_min': 100000,  'weight': 1},
        {'rebate_min': 200000,  'weight': 1},
        {'rebate_min': 300000,  'weight': 1},
        {'rebate_min': 400000,  'weight': 1},
        {'rebate_min': 500000,  'weight': 1},
        {'rebate_min': 1000000, 'weight': 0},
    ],
    '3': [  # 免费局
        {'rebate_min': 0,        'weight': 0},
        {'rebate_min': 1,       'weight': 0},
        {'rebate_min': 5000,    'weight': 8000},
        {'rebate_min': 6000,    'weight': 8000},
        {'rebate_min': 7000,    'weight': 8000},
        {'rebate_min': 8000,    'weight': 8000},
        {'rebate_min': 9000,    'weight': 8000},
        {'rebate_min': 10000,   'weight': 8000},
        {'rebate_min': 20000,   'weight': 4000},
        {'rebate_min': 30000,   'weight': 2000},
        {'rebate_min': 40000,   'weight': 1000},
        {'rebate_min': 50000,   'weight': 500},
        {'rebate_min': 60000,   'weight': 100},
        {'rebate_min': 70000,   'weight': 50},
        {'rebate_min': 80000,   'weight': 10},
        {'rebate_min': 90000,   'weight': 5},
        {'rebate_min': 100000,  'weight': 1},
        {'rebate_min': 200000,  'weight': 1},
        {'rebate_min': 300000,  'weight': 1},
        {'rebate_min': 400000,  'weight': 1},
        {'rebate_min': 500000,  'weight': 1},
        {'rebate_min': 1000000, 'weight': 1},
    ],
    'buy': [  # 购买局，独立配置；界面中可单独调整
        {'rebate_min': 0,        'weight': 0},
        {'rebate_min': 5000,     'weight': 0},
        {'rebate_min': 10000,    'weight': 0},
        {'rebate_min': 20000,    'weight': 0},
        {'rebate_min': 30000,    'weight': 10000},
        {'rebate_min': 40000,    'weight': 10000},
        {'rebate_min': 50000,    'weight': 10000},
        {'rebate_min': 60000,    'weight': 10000},
        {'rebate_min': 70000,    'weight': 10000},
        {'rebate_min': 80000,    'weight': 5000},
        {'rebate_min': 90000,    'weight': 1000},
        {'rebate_min': 100000,   'weight': 500},
        {'rebate_min': 200000,   'weight': 100},
        {'rebate_min': 300000,   'weight': 50},
        {'rebate_min': 400000,   'weight': 10},
        {'rebate_min': 500000,   'weight': 5},
        {'rebate_min': 1000000,  'weight': 1},
        {'rebate_min': 2000000,  'weight': 1},
        {'rebate_min': 3000000,  'weight': 0},
        {'rebate_min': 4000000,  'weight': 0},
        {'rebate_min': 5000000,  'weight': 0},
        {'rebate_min': 10000000, 'weight': 0},
    ],
    '6': [  # ex普通局
        {'rebate_min': 0,       'weight': 0},
        {'rebate_min': 1,       'weight': 10000},
        {'rebate_min': 1000,    'weight': 9000},
        {'rebate_min': 2000,    'weight': 8000},
        {'rebate_min': 3000,    'weight': 7000},
        {'rebate_min': 4000,    'weight': 6000},
        {'rebate_min': 5000,    'weight': 5000},
        {'rebate_min': 6000,    'weight': 4000},
        {'rebate_min': 7000,    'weight': 3000},
        {'rebate_min': 8000,    'weight': 2000},
        {'rebate_min': 9000,    'weight': 2000},
        {'rebate_min': 10000,   'weight': 1000},
        {'rebate_min': 20000,   'weight': 500},
        {'rebate_min': 30000,   'weight': 250},
        {'rebate_min': 40000,   'weight': 100},
        {'rebate_min': 50000,   'weight': 50},
        {'rebate_min': 60000,   'weight': 20},
        {'rebate_min': 70000,   'weight': 10},
        {'rebate_min': 80000,   'weight': 5},
        {'rebate_min': 90000,   'weight': 5},
        {'rebate_min': 100000,  'weight': 1},
        {'rebate_min': 200000,  'weight': 1},
        {'rebate_min': 300000,  'weight': 1},
        {'rebate_min': 400000,  'weight': 1},
        {'rebate_min': 500000,  'weight': 1},
        {'rebate_min': 1000000, 'weight': 0},
    ],
    '7': [  # ex特殊局
        {'rebate_min': 0,        'weight': 0},
        {'rebate_min': 1,       'weight': 5000},
        {'rebate_min': 1000,    'weight': 5000},
        {'rebate_min': 2000,    'weight': 5000},
        {'rebate_min': 3000,    'weight': 5000},
        {'rebate_min': 4000,    'weight': 5000},
        {'rebate_min': 5000,    'weight': 5000},
        {'rebate_min': 6000,    'weight': 4000},
        {'rebate_min': 7000,    'weight': 4000},
        {'rebate_min': 8000,    'weight': 3000},
        {'rebate_min': 9000,    'weight': 3000},
        {'rebate_min': 10000,   'weight': 2000},
        {'rebate_min': 20000,   'weight': 1000},
        {'rebate_min': 30000,   'weight': 500},
        {'rebate_min': 40000,   'weight': 250},
        {'rebate_min': 50000,   'weight': 100},
        {'rebate_min': 60000,   'weight': 50},
        {'rebate_min': 70000,   'weight': 20},
        {'rebate_min': 80000,   'weight': 10},
        {'rebate_min': 90000,   'weight': 5},
        {'rebate_min': 100000,  'weight': 1},
        {'rebate_min': 200000,  'weight': 1},
        {'rebate_min': 300000,  'weight': 1},
        {'rebate_min': 400000,  'weight': 1},
        {'rebate_min': 500000,  'weight': 1},
        {'rebate_min': 1000000, 'weight': 0},
    ],
    '8': [  # ex免费局
        {'rebate_min': 0,        'weight': 0},
        {'rebate_min': 1,       'weight': 0},
        {'rebate_min': 5000,    'weight': 8000},
        {'rebate_min': 6000,    'weight': 8000},
        {'rebate_min': 7000,    'weight': 8000},
        {'rebate_min': 8000,    'weight': 8000},
        {'rebate_min': 9000,    'weight': 8000},
        {'rebate_min': 10000,   'weight': 8000},
        {'rebate_min': 20000,   'weight': 4000},
        {'rebate_min': 30000,   'weight': 2000},
        {'rebate_min': 40000,   'weight': 1000},
        {'rebate_min': 50000,   'weight': 500},
        {'rebate_min': 60000,   'weight': 100},
        {'rebate_min': 70000,   'weight': 50},
        {'rebate_min': 80000,   'weight': 10},
        {'rebate_min': 90000,   'weight': 5},
        {'rebate_min': 100000,  'weight': 1},
        {'rebate_min': 200000,  'weight': 1},
        {'rebate_min': 300000,  'weight': 1},
        {'rebate_min': 400000,  'weight': 1},
        {'rebate_min': 500000,  'weight': 1},
        {'rebate_min': 1000000, 'weight': 1},
    ],
    'ex_buy': [  # ex购买局，独立配置；界面中可单独调整
        {'rebate_min': 0,        'weight': 0},
        {'rebate_min': 5000,     'weight': 0},
        {'rebate_min': 10000,    'weight': 0},
        {'rebate_min': 20000,    'weight': 0},
        {'rebate_min': 30000,    'weight': 10000},
        {'rebate_min': 40000,    'weight': 10000},
        {'rebate_min': 50000,    'weight': 10000},
        {'rebate_min': 60000,    'weight': 10000},
        {'rebate_min': 70000,    'weight': 10000},
        {'rebate_min': 80000,    'weight': 5000},
        {'rebate_min': 90000,    'weight': 1000},
        {'rebate_min': 100000,   'weight': 500},
        {'rebate_min': 200000,   'weight': 100},
        {'rebate_min': 300000,   'weight': 50},
        {'rebate_min': 400000,   'weight': 10},
        {'rebate_min': 500000,   'weight': 5},
        {'rebate_min': 1000000,  'weight': 1},
        {'rebate_min': 2000000,  'weight': 1},
        {'rebate_min': 3000000,  'weight': 0},
        {'rebate_min': 4000000,  'weight': 0},
        {'rebate_min': 5000000,  'weight': 0},
        {'rebate_min': 10000000, 'weight': 0},
    ],
}
