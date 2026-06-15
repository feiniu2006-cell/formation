"""Game type and group_weight mode definitions."""

from formation_tool.core import buy_group_config


GAME_TYPE_NAMES = {
    '1': '普通局',
    '2': '特殊局',
    '3': '免费局',
    '6': 'ex普通局',
    '7': 'ex特殊局',
    '8': 'ex免费局',
    '98': 'ex购买局',
    '99': '购买局',
}
SAMPLE_GAME_TYPE_NAMES = {
    '1': '普通局',
    '2': '特殊局',
    '3': '免费局',
    '6': 'ex普通局',
    '7': 'ex特殊局',
    '8': 'ex免费局',
}
GROUP_WEIGHT_MODES = ('1', '2', '3', '6', '7', '8', '98', '99')
GROUP_WEIGHT_UI_MODES = ('1', '2', '3', '99', '6', '7', '8', '98')
EX_GROUP_MODES = ('6', '7', '8')
EX_PURCHASE_MODE = '98'
BUY_GROUP_MODE = '99'
DEFAULT_BUY_GROUP_GAME_TYPE = buy_group_config.DEFAULT_BUY_GROUP_GAME_TYPE
DEFAULT_BUY_GROUP_SOURCE_SUFFIX = buy_group_config.DEFAULT_BUY_GROUP_SOURCE_SUFFIX
EXTRA_BUY_MODE_PREFIX = buy_group_config.EXTRA_BUY_MODE_PREFIX

GROUP_WEIGHT_MODE_DEFS = {
    '1': {'source_mode': '1', 'write_game_type': 1, 'rtp_role': 'normal'},
    '2': {'source_mode': '2', 'write_game_type': 2, 'rtp_role': 'special'},
    '3': {'source_mode': '3', 'write_game_type': 3, 'rtp_role': 'static'},
    '6': {'source_mode': '6', 'write_game_type': 6, 'rtp_role': 'ex_normal'},
    '7': {'source_mode': '7', 'write_game_type': 7, 'rtp_role': 'ex_independent'},
    '8': {'source_mode': '8', 'write_game_type': 8, 'rtp_role': 'static'},
    '98': {'source_mode': '8', 'write_game_type': 98, 'rtp_role': 'ex_buy'},
    '99': {'source_mode': '3', 'write_game_type': 99, 'rtp_role': 'buy'},
}
EX_INDEPENDENT_GROUP_WEIGHT_MODES = tuple(
    mode for mode, mode_def in GROUP_WEIGHT_MODE_DEFS.items()
    if mode_def.get('rtp_role') == 'ex_independent'
)


def make_extra_buy_mode(game_type):
    return buy_group_config.make_extra_buy_mode(game_type)


def is_extra_buy_mode(mode):
    return buy_group_config.is_extra_buy_mode(mode)


def get_extra_buy_game_type(mode):
    return buy_group_config.get_extra_buy_game_type(mode)


def get_group_weight_mode_name(mode):
    mode = str(mode)
    if is_extra_buy_mode(mode):
        return f"购买局{get_extra_buy_game_type(mode)}"
    return GAME_TYPE_NAMES[mode]


def get_group_weight_rtp_role(mode):
    """Return the RTP/write role used by a group_weight mode."""
    mode = str(mode)
    if is_extra_buy_mode(mode):
        return 'buy'
    return GROUP_WEIGHT_MODE_DEFS.get(mode, {}).get('rtp_role', 'static')


def get_extra_buy_group_by_mode(mode, extra_buy_groups):
    return buy_group_config.get_extra_buy_group_by_mode(mode, extra_buy_groups)


def get_buy_group_source_suffix(mode, *, buy_group_source_suffix, extra_buy_groups):
    """Return the formation table suffix configured for one buy-like mode."""
    return buy_group_config.get_buy_group_source_suffix(
        mode,
        buy_group_source_suffix=buy_group_source_suffix,
        extra_buy_groups=extra_buy_groups,
    )


def get_buy_group_game_type(mode, *, buy_group_game_type, extra_buy_groups):
    """Return the written game_type configured for one buy-like mode."""
    return buy_group_config.get_buy_group_game_type(
        mode,
        buy_group_game_type=buy_group_game_type,
        extra_buy_groups=extra_buy_groups,
    )


def get_buy_group_multiplier(mode, *, buy_group_multiplier, extra_buy_groups):
    """Return the RTP display multiplier configured for one buy-like mode."""
    return buy_group_config.get_buy_group_multiplier(
        mode,
        buy_group_multiplier=buy_group_multiplier,
        extra_buy_groups=extra_buy_groups,
    )


def get_group_weight_write_game_type(mode, *, buy_group_game_type, extra_buy_groups):
    """Return the game_type value written to group_weight for one mode."""
    mode = str(mode)
    if mode == BUY_GROUP_MODE or is_extra_buy_mode(mode):
        return get_buy_group_game_type(
            mode,
            buy_group_game_type=buy_group_game_type,
            extra_buy_groups=extra_buy_groups,
        )
    return int(GROUP_WEIGHT_MODE_DEFS[mode]['write_game_type'])


def has_extra_buy_groups(extra_buy_groups):
    return bool(extra_buy_groups)


def has_any_buy_group(buy_enabled, extra_buy_groups):
    return bool(buy_enabled) or has_extra_buy_groups(extra_buy_groups)


def get_active_group_weight_modes(
    formation_exists,
    *,
    buy_enabled,
    ex_buy_enabled,
    extra_buy_groups,
):
    """Return the group_weight modes that should be read/generated now."""
    modes = [
        mode
        for mode in GROUP_WEIGHT_MODES
        if mode not in (BUY_GROUP_MODE, EX_PURCHASE_MODE) and formation_exists.get(mode, False)
    ]
    if ex_buy_enabled and formation_exists.get(EX_PURCHASE_MODE, False):
        modes.append(EX_PURCHASE_MODE)
    if buy_enabled and formation_exists.get(BUY_GROUP_MODE, False):
        modes.append(BUY_GROUP_MODE)
    for group in extra_buy_groups:
        mode = make_extra_buy_mode(group['game_type'])
        if formation_exists.get(mode, False):
            modes.append(mode)
    return tuple(modes)


def get_displayed_group_weight_modes(
    formation_exists,
    *,
    buy_enabled,
    ex_buy_enabled,
    extra_buy_groups,
):
    """Return group_weight dialog tab order."""
    displayed = []
    for mode in GROUP_WEIGHT_UI_MODES:
        if mode == BUY_GROUP_MODE:
            if buy_enabled and formation_exists.get(mode, False):
                displayed.append(mode)
            for group in extra_buy_groups:
                extra_mode = make_extra_buy_mode(group['game_type'])
                if formation_exists.get(extra_mode, False):
                    displayed.append(extra_mode)
        elif mode == EX_PURCHASE_MODE:
            if ex_buy_enabled and formation_exists.get(mode, False):
                displayed.append(mode)
        elif formation_exists.get(mode, False):
            displayed.append(mode)
    return tuple(displayed)
