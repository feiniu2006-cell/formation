"""UI text builders for the group_weight configuration dialog."""

DIALOG_TITLE = "group_weight 权重配置"
LOADING_TEXT = "正在检测源表和采样配置，请稍候..."
RULE_HELP_TEXT = "按 rebate 下限配置 weight；区间为当前下限 <= rebate < 下一下限。weight=0 的 rebate 也会写入表，但不参与 RTP 权重计算。"
MISSING_CONFIG_TITLE = "采样配置提示"
CONFIRM_BUTTON_TEXT = "确认并开始"
CANCEL_BUTTON_TEXT = "取消"
PARSE_INCOMPLETE_ROW = "有未填完整的行"
PARSE_NOT_INTEGER = "有非整数输入"
DEFAULT_PREVIEW_TEXT = "生成时会遍历全部 RTP 组"


def build_missing_config_warning_message(missing_or_empty):
    return (
        "生成 group_weight 需要先有对应的采样配置表数据：\n\n"
        + "\n".join(missing_or_empty)
        + "\n\n缺少的类型会在生成时跳过。"
    )


def build_detection_status_text(deps, formation_exists, displayed_modes):
    detected_names = [
        deps.get_mode_name(mode)
        for mode in deps.group_weight_ui_modes
        if formation_exists.get(mode, False)
    ]
    detected_names.extend(
        deps.get_mode_name(mode)
        for mode in displayed_modes
        if deps.is_extra_buy_mode(mode)
    )
    missing_names = [
        deps.get_mode_name(mode)
        for mode in deps.group_weight_ui_modes
        if not formation_exists.get(mode, False)
    ]
    return (
        f"已检测：{', '.join(detected_names) if detected_names else '无'}"
        + (f"；未检测：{', '.join(missing_names)}" if missing_names else "")
        + "；购买局开关与倍数请在主界面配置"
    )


def build_special_target_note(has_zero):
    if has_zero:
        return "采样配置中存在 rebate=0，按此目标 RTP 反推0权重"
    return "采样配置中未检测到 rebate=0，无需填写目标 RTP"


def build_ex_mode_note(mode, deps):
    write_game_type = deps.get_group_weight_write_game_type(mode)
    if mode == deps.ex_purchase_mode:
        return (
            f"ex购买局使用 ex免费局采样配置 rebate_ex_free_count，写入 game_type={write_game_type}；"
            f"最终RTP按 购买倍数 {deps.format_weighted_rtp(deps.buy_multiplier)} * "
            f"ex倍数 {deps.format_weighted_rtp(deps.ex_multiplier)} 折算"
        )
    return (
        f"{deps.game_type_names[mode]}写入 game_type={write_game_type}；"
        f"最终RTP按主界面 ex倍数 {deps.format_weighted_rtp(deps.ex_multiplier)} 折算"
    )


def build_buy_mode_note(deps):
    return (
        f"购买局使用 {deps.buy_source_suffix} 的采样配置，写入 game_type={deps.buy_game_type}；"
        f"购买倍数请在主界面配置，当前={deps.format_weighted_rtp(deps.buy_multiplier)}"
    )


def build_extra_buy_mode_note(mode, deps):
    extra_group = deps.get_extra_buy_group_by_mode(mode) or {}
    return (
        f"额外购买局使用 {extra_group.get('source_suffix', deps.buy_source_suffix)} 的采样配置，"
        f"写入 game_type={deps.get_extra_buy_game_type(mode)}；"
        f"购买倍数={deps.format_weighted_rtp(float(extra_group.get('multiplier', deps.buy_multiplier)))}"
    )


def build_mode_option_note(mode, deps):
    if mode in deps.ex_group_modes or mode == deps.ex_purchase_mode:
        return build_ex_mode_note(mode, deps)
    if mode == deps.buy_group_mode:
        return build_buy_mode_note(deps)
    if deps.is_extra_buy_mode(mode):
        return build_extra_buy_mode_note(mode, deps)
    return ""


def build_rtp_info_text(deps, group_id, current_mode, current_rtp_text):
    return (
        f"当前组：group_id={group_id}，目标RTP={deps.get_group_target_rtp_value(group_id):.1f}%，"
        f"分组={group_id % 10}，当前{deps.get_mode_name(current_mode)}配置RTP={current_rtp_text}"
    )
