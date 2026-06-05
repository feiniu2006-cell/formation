"""group_weight preview and row-building orchestration."""

from types import SimpleNamespace

from formation_tool.group_weight import group_weight_buy_modes
from formation_tool.group_weight import group_weight_ex_modes
from formation_tool.group_weight import group_weight_messages
from formation_tool.group_weight import group_weight_original_modes
from formation_tool.group_weight import group_weight_preview
from formation_tool.group_weight import group_weight_row_helpers
from formation_tool.group_weight.group_weight_logic import (
    build_rebate_weight_pairs,
    format_weighted_rtp,
)
from formation_tool.core import runtime_context_sync
from formation_tool.utils import log_utils

print = log_utils.emit

GROUP_WEIGHT_MODE_MODULES = (
    group_weight_row_helpers,
    group_weight_original_modes,
    group_weight_buy_modes,
    group_weight_ex_modes,
    group_weight_preview,
)


def configure(**values):
    """Inject the explicit runtime context owned by the main formation script."""
    runtime_context_sync.configure_module_globals(
        globals(),
        values,
        runtime_context_sync.GROUP_WEIGHT_BUILDER_CONTEXT_KEYS,
        'group_weight_builder context',
    )
    for module in GROUP_WEIGHT_MODE_MODULES:
        module.configure(**values)


def collect_group_weight_preview_warnings(displayed_modes, preview_rebates, preview_status):
    """返回 group_weight 弹窗中需要提示的缺表/空表信息，并按源采样表去重。"""
    return group_weight_preview.collect_group_weight_preview_warnings(
        displayed_modes,
        preview_rebates,
        preview_status,
    )

def build_group_weight_pairs_for_modes(active_modes, rebates_by_mode):
    """根据当前 group_weight 区间规则，把已选 rebate 转成可写入的 rebate/weight 对。"""
    mode_pairs = {mode: [] for mode in list(dict.fromkeys(list(GROUP_WEIGHT_MODES) + list(active_modes)))}
    for game_type in active_modes:
        if is_extra_buy_mode(game_type):
            extra_group = get_extra_buy_group_by_mode(game_type) or {}
            rules = extra_group.get('rules', GROUP_WEIGHT_RULES.get(BUY_GROUP_MODE, []))
        else:
            rules = GROUP_WEIGHT_RULES.get(game_type, [])
        exclude_zero = game_type in ('1', '2', *EX_GROUP_MODES)
        pairs, skipped_zero, skipped_rebate_zero = build_rebate_weight_pairs(
            rebates_by_mode[game_type],
            rules,
            exclude_rebate_zero=exclude_zero,
        )
        mode_pairs[game_type] = pairs
        mode_name = get_group_weight_mode_name(game_type)
        print(
            f"\n[{mode_name}] 可写入非0权重 rebate {len(pairs)} 个，"
            f"跳过 weight=0 的 rebate {skipped_zero} 个"
            + (f"，{mode_name}暂不使用配置中的 rebate=0 {skipped_rebate_zero} 个" if exclude_zero else "")
        )
    return mode_pairs

def build_group_weight_preview_text(*args, **kwargs):
    """Delegate preview text calculation to the preview module."""
    return group_weight_preview.build_group_weight_preview_text(*args, **kwargs)

def build_group_weight_rows_from_loaded_data(formation_exists, rebates_by_mode, mode_exists, mode_pairs):
    """根据已加载的 rebate_count 数据生成 group_weight rows；返回 None 表示配置错误。"""
    rows = []
    if not append_original_group_weight_modes(rows, rebates_by_mode, mode_exists, mode_pairs):
        return None
    append_buy_group_weight_modes(rows, rebates_by_mode, mode_exists, mode_pairs)
    append_ex_group_weight_modes(rows, formation_exists, rebates_by_mode, mode_exists, mode_pairs)
    return rows


def build_group_weight_message_deps():
    return SimpleNamespace(
        buy_group_enabled=BUY_GROUP_ENABLED,
        buy_group_mode=BUY_GROUP_MODE,
        buy_group_source_suffix=BUY_GROUP_SOURCE_SUFFIX,
        buy_group_multiplier=BUY_GROUP_MULTIPLIER,
        ex_buy_group_enabled=EX_BUY_GROUP_ENABLED,
        ex_purchase_mode=EX_PURCHASE_MODE,
        ex_group_multiplier=EX_GROUP_MULTIPLIER,
        extra_buy_groups=EXTRA_BUY_GROUPS,
        game_type_names=GAME_TYPE_NAMES,
        format_weighted_rtp=format_weighted_rtp,
        get_group_weight_write_game_type=get_group_weight_write_game_type,
        get_group_weight_rebate_table_name=get_group_weight_rebate_table_name,
        make_extra_buy_mode=make_extra_buy_mode,
    )


def print_group_weight_generation_summary(context):
    """Print a concise summary for this group_weight generation."""
    group_weight_messages.print_generation_summary(
        context,
        deps=build_group_weight_message_deps(),
    )


def append_static_group_weight_rows(rows, write_game_type, pairs):
    return group_weight_row_helpers.append_static_group_weight_rows(rows, write_game_type, pairs)


def append_buy_like_group_weight_rows(rows, write_game_type, pairs, multiplier):
    return group_weight_row_helpers.append_buy_like_group_weight_rows(rows, write_game_type, pairs, multiplier)


def append_special_group_weight_rows(rows, write_game_type, pairs, zero_weight):
    return group_weight_row_helpers.append_special_group_weight_rows(rows, write_game_type, pairs, zero_weight)


def append_independent_ex_group_rows(rows, game_type, pairs, has_zero):
    return group_weight_row_helpers.append_independent_ex_group_rows(rows, game_type, pairs, has_zero)


def has_rebate_zero(rebates):
    return group_weight_row_helpers.has_rebate_zero(rebates)


def prepare_original_trigger_rtp_context(rebates_by_mode, mode_exists, mode_pairs):
    return group_weight_original_modes.prepare_original_trigger_rtp_context(
        rebates_by_mode,
        mode_exists,
        mode_pairs,
    )


def log_original_trigger_rtp_context(context):
    return group_weight_original_modes.log_original_trigger_rtp_context(context)


def append_original_normal_group_weight_rows(rows, rebates_by_mode, mode_exists, mode_pairs, trigger_context):
    return group_weight_original_modes.append_original_normal_group_weight_rows(
        rows,
        rebates_by_mode,
        mode_exists,
        mode_pairs,
        trigger_context,
    )


def should_skip_original_static_mode(game_type, rebates_by_mode, mode_exists):
    return group_weight_original_modes.should_skip_original_static_mode(game_type, rebates_by_mode, mode_exists)


def append_original_special_group_weight_rows(rows, rebates_by_mode, mode_exists, mode_pairs, trigger_context):
    return group_weight_original_modes.append_original_special_group_weight_rows(
        rows,
        rebates_by_mode,
        mode_exists,
        mode_pairs,
        trigger_context,
    )


def append_original_free_group_weight_rows(rows, rebates_by_mode, mode_exists, mode_pairs, trigger_context):
    return group_weight_original_modes.append_original_free_group_weight_rows(
        rows,
        rebates_by_mode,
        mode_exists,
        mode_pairs,
        trigger_context,
    )


def append_original_group_weight_modes(rows, rebates_by_mode, mode_exists, mode_pairs):
    return group_weight_original_modes.append_original_group_weight_modes(
        rows,
        rebates_by_mode,
        mode_exists,
        mode_pairs,
    )


def append_extra_buy_group_weight_rows(rows, source_rebates, extra_buy):
    return group_weight_buy_modes.append_extra_buy_group_weight_rows(rows, source_rebates, extra_buy)


def append_buy_group_weight_modes(rows, rebates_by_mode, mode_exists, mode_pairs):
    return group_weight_buy_modes.append_buy_group_weight_modes(rows, rebates_by_mode, mode_exists, mode_pairs)


def should_skip_group_weight_mode_data(game_type, mode_exists, rebates_by_mode):
    return group_weight_ex_modes.should_skip_group_weight_mode_data(game_type, mode_exists, rebates_by_mode)


def log_ex_independent_group_weight_result(game_type, mode_infos, has_zero, mode_rows):
    return group_weight_ex_modes.log_ex_independent_group_weight_result(game_type, mode_infos, has_zero, mode_rows)


def append_ex_independent_group_weight_modes(rows, formation_exists, rebates_by_mode, mode_exists, mode_pairs):
    return group_weight_ex_modes.append_ex_independent_group_weight_modes(
        rows,
        formation_exists,
        rebates_by_mode,
        mode_exists,
        mode_pairs,
    )


def append_ex_normal_group_weight_mode(rows, formation_exists, rebates_by_mode, mode_exists, mode_pairs, ex_info_by_mode):
    return group_weight_ex_modes.append_ex_normal_group_weight_mode(
        rows,
        formation_exists,
        rebates_by_mode,
        mode_exists,
        mode_pairs,
        ex_info_by_mode,
    )


def append_ex_buy_group_weight_mode(rows, formation_exists, rebates_by_mode, mode_exists, mode_pairs):
    return group_weight_ex_modes.append_ex_buy_group_weight_mode(
        rows,
        formation_exists,
        rebates_by_mode,
        mode_exists,
        mode_pairs,
    )


def append_ex_group_weight_modes(rows, formation_exists, rebates_by_mode, mode_exists, mode_pairs):
    return group_weight_ex_modes.append_ex_group_weight_modes(
        rows,
        formation_exists,
        rebates_by_mode,
        mode_exists,
        mode_pairs,
    )
