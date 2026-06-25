"""Settings load/save helpers for SlotProcessApp."""
import contextlib
import threading
from tkinter import filedialog, messagebox

from formation_tool.core import buy_group_config
from formation_tool.core import settings_logic
from formation_tool.ui import ui_text
from formation_tool.utils.file_utils import write_json_atomic


def _format_setting_text(value):
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _build_current_buy_groups(app):
    return buy_group_config.build_buy_groups_from_legacy(
        buy_enabled=app.buy_group_enabled_var.get(),
        buy_game_type=app.buy_game_type_var.get(),
        buy_multiplier=app.buy_multiplier_var.get(),
        buy_source_suffix=app.buy_source_suffix_var.get(),
        extra_buy_groups=app.collect_extra_buy_groups(),
    )


def _collect_ex_source_suffixes(app):
    return {
        str(mode): var.get().strip()
        for mode, var in getattr(app, 'ex_source_suffix_vars', {}).items()
        if var.get().strip()
    }


def _set_ex_source_suffix_vars(app, values):
    values = values or {}
    for mode, var in getattr(app, 'ex_source_suffix_vars', {}).items():
        var.set(_format_setting_text(values.get(str(mode), "")))


def _count_mapping_items(value):
    return len(value) if isinstance(value, dict) else 0


def _count_sequence_items(value):
    return len(value) if isinstance(value, (list, tuple, set)) else 0


def build_rule_import_preview(data):
    """Build a concise preview for importing portable rule settings."""
    lines = [
        "将导入规则配置，并覆盖当前界面里的对应规则：",
        "",
    ]
    rule_version = data.get('rule_schema_version', data.get('version', '未知'))
    lines.append(f"- 规则文件版本：{rule_version}")
    if 'trigger_weights' in data:
        lines.append("- 权重配置：会覆盖特殊局/免费局触发权重")
    if 'rebate_rules' in data:
        lines.append(f"- 采样规则：{_count_mapping_items(data.get('rebate_rules'))} 个模式")
    if 'sampling_options' in data:
        sampling_options = data.get('sampling_options') or {}
        detailed_log = bool(sampling_options.get('detailed_log'))
        lines.append(f"- 采样详细日志：{'开启' if detailed_log else '关闭'}")
    if 'group_weight_rules' in data:
        lines.append(f"- group_weight 权重规则：{_count_mapping_items(data.get('group_weight_rules'))} 个模式")
    if 'group_weight_options' in data:
        options = data.get('group_weight_options') or {}
        buy_groups = options.get('buy_groups') or []
        extra_buy_groups = options.get('extra_buy_groups') or []
        group_count = _count_sequence_items(buy_groups) or (
            int(bool(options.get('buy_enabled'))) + _count_sequence_items(extra_buy_groups)
        )
        lines.append(f"- 购买局配置：{group_count} 个购买局配置")
    if 'direct_count_modes' in data:
        lines.append(f"- 小表直接计数模式：{_count_sequence_items(data.get('direct_count_modes'))} 个")
    if 'direct_count_tiers' in data:
        lines.append(f"- 直接计数阶梯：{_count_sequence_items(data.get('direct_count_tiers'))} 条")

    lines.extend([
        "",
        "不会修改厂商、游戏编号、源库、目标库、配置库。",
        "是否继续导入？",
    ])
    return "\n".join(lines)


class SlotAppSettingsMixin:
    """Profile auto-load, settings persistence, and UI-to-runtime config sync."""

    def setup_profile_auto_load(self):
        self.vendor_var.trace_add("write", self.schedule_profile_auto_load)
        self.game_id_var.trace_add("write", self.schedule_profile_auto_load)

    def schedule_profile_auto_load(self, *_args):
        if self._loading_settings or self.running:
            return
        if self._profile_load_after_id is not None:
            with contextlib.suppress(Exception):
                self.root.after_cancel(self._profile_load_after_id)
        self._profile_load_after_id = self.root.after(700, self.auto_load_current_profile)

    def auto_load_current_profile(self):
        self._profile_load_after_id = None
        if self._loading_settings or self.running:
            return
        vendor = self.vendor_var.get().strip()
        game_id = self.game_id_var.get().strip()
        if not vendor or not game_id:
            return
        key = (vendor, game_id)
        if key == self._last_profile_key_loaded:
            return
        self.load_current_profile_or_defaults(auto=True)

    def reset_profile_settings_to_defaults(self):
        """Reset room-specific options/rules without changing vendor/game/db selection."""
        deps = self.settings_deps
        self.special_weight_0_var.set(str(deps.default_trigger_weights['special_0']))
        self.special_weight_1_var.set(str(deps.default_trigger_weights['special_1']))
        self.free_weight_0_var.set(str(deps.default_trigger_weights['free_0']))
        self.free_weight_1_var.set(str(deps.default_trigger_weights['free_1']))
        self.sampling_detailed_log_var.set(deps.default_sampling_detailed_log)
        self.sampling_use_temp_db_var.set(getattr(deps, "default_sampling_use_temp_db", False))
        self.sampling_temp_db_var.set(getattr(deps, "default_sampling_temp_db", self.final_db_var.get()))
        self.buy_group_enabled_var.set(deps.default_buy_group_enabled)
        self.ex_buy_group_enabled_var.set(deps.default_ex_buy_group_enabled)
        self.ex_buy_game_type_var.set(str(deps.default_ex_buy_group_game_type))
        self.ex_buy_source_suffix_var.set(str(deps.default_ex_buy_group_source_suffix))
        self.buy_game_type_var.set(str(deps.default_buy_group_game_type))
        self.buy_multiplier_var.set(str(deps.default_buy_group_multiplier))
        self.buy_source_suffix_var.set(str(deps.default_buy_group_source_suffix))
        self.ex_multiplier_var.set(str(deps.default_ex_group_multiplier))
        _set_ex_source_suffix_vars(self, {})
        self.set_extra_buy_group_rows(deps.default_extra_buy_groups)
        deps.apply_rebate_rules_config(deps.clone_rebate_rules(deps.default_rebate_rules))
        deps.apply_group_weight_rules_config(deps.clone_group_weight_rules(deps.default_group_weight_rules))
        deps.apply_special_group_target_rtp(deps.default_special_group_target_rtp)
        getattr(deps, "apply_ex_group_target_rtps_config", lambda _targets: None)(
            getattr(deps, "default_ex_group_target_rtps", {})
        )
        getattr(deps, "apply_zero_rebate_inference_modes_config", lambda _modes: None)(
            getattr(deps, "default_zero_rebate_inference_modes", ())
        )
        deps.apply_buy_group_game_type(deps.default_buy_group_game_type)
        deps.apply_buy_group_source_suffix(deps.default_buy_group_source_suffix)
        deps.apply_ex_buy_group_game_type(deps.default_ex_buy_group_game_type)
        deps.apply_ex_buy_group_source_suffix(deps.default_ex_buy_group_source_suffix)
        deps.apply_ex_source_suffixes_config({})
        deps.apply_extra_buy_groups_config(deps.default_extra_buy_groups)
        deps.apply_rebate_config_direct_count_modes([])
        deps.apply_rebate_config_direct_count_tiers(deps.default_direct_count_tiers)

    def build_last_settings_data(self):
        return settings_logic.build_last_settings_data(**self.settings_deps.get_runtime_state())

    def build_app_settings_data(self):
        deps = self.settings_deps
        get_buy_groups = getattr(
            deps,
            "get_buy_groups",
            lambda: buy_group_config.build_buy_groups_from_legacy(
                buy_enabled=deps.get_buy_group_enabled(),
                buy_game_type=deps.get_buy_group_game_type(),
                buy_multiplier=deps.get_buy_group_multiplier(),
                buy_source_suffix=deps.get_buy_group_source_suffix(),
                extra_buy_groups=deps.clone_extra_buy_groups(deps.get_extra_buy_groups()),
            ),
        )
        return settings_logic.build_app_settings_data(
            runtime=deps.get_runtime_state(),
            trigger_weights=deps.get_trigger_weights(),
            rebate_rules=deps.clone_rebate_rules(deps.get_rebate_rules()),
            sampling_append_mode=False,
            sampling_detailed_log=deps.get_sampling_detailed_log(),
            sampling_use_temp_db=getattr(deps, "get_sampling_use_temp_db", lambda: False)(),
            sampling_temp_db=getattr(deps, "get_sampling_temp_db", lambda: None)(),
            group_weight_rules=deps.clone_group_weight_rules(deps.get_group_weight_rules()),
            group_weight_options={
                'special_target_rtp': deps.get_special_group_target_rtp(),
                'ex_group_target_rtps': getattr(deps, "get_ex_group_target_rtps", lambda: {})(),
                'zero_rebate_inference_modes': sorted(
                    getattr(deps, "get_zero_rebate_inference_modes", lambda: set())()
                ),
                'buy_enabled': deps.get_buy_group_enabled(),
                'ex_buy_enabled': deps.get_ex_buy_group_enabled(),
                'ex_buy_game_type': deps.get_ex_buy_group_game_type(),
                'ex_buy_source_suffix': deps.get_ex_buy_group_source_suffix(),
                'buy_game_type': deps.get_buy_group_game_type(),
                'buy_multiplier': deps.get_buy_group_multiplier(),
                'buy_source_suffix': deps.get_buy_group_source_suffix(),
                'buy_groups': get_buy_groups(),
                'ex_multiplier': deps.get_ex_group_multiplier(),
                'ex_source_suffixes': deps.get_ex_source_suffixes(),
                'extra_buy_groups': deps.clone_extra_buy_groups(deps.get_extra_buy_groups()),
            },
            direct_count_modes=deps.get_direct_count_modes(),
            direct_count_tiers=deps.get_direct_count_tiers(),
        )

    def build_rule_settings_data(self):
        """Build a portable rule/options payload without overwriting room selection on import."""
        data = dict(self.build_app_settings_data())
        data['kind'] = 'formation_rule_settings'
        data['rule_schema_version'] = settings_logic.RULE_SETTINGS_SCHEMA_VERSION
        data['runtime_hint'] = data.pop('runtime', {})
        return data

    def apply_app_settings_data(self, data, *, runtime_only=False, reset_missing=False):
        deps = self.settings_deps
        deps.clear_config_warnings()
        runtime = settings_logic.get_runtime_settings(data)
        if runtime:
            self.vendor_var.set(str(runtime.get('vendor', self.vendor_var.get())))
            self.game_id_var.set(str(runtime.get('game_id', self.game_id_var.get())))
            self.source_db_var.set(str(runtime.get('source_db', self.source_db_var.get())))
            self.final_db_var.set(str(runtime.get('final_db', self.final_db_var.get())))
            self.config_db_var.set(str(runtime.get('config_db', self.config_db_var.get())))
            if hasattr(self, 'sampling_temp_db_var'):
                self.sampling_temp_db_var.set(str(runtime.get('sampling_temp_db', self.sampling_temp_db_var.get())))
            if hasattr(self, 'sampling_use_temp_db_var'):
                self.sampling_use_temp_db_var.set(bool(runtime.get('sampling_use_temp_db', self.sampling_use_temp_db_var.get())))

        if runtime_only:
            if not self.apply_selected_config():
                raise ValueError("配置文件中的基础配置无效")
            return

        if reset_missing:
            self.reset_profile_settings_to_defaults()

        trigger_weights = data.get('trigger_weights', {})
        if trigger_weights:
            self.special_weight_0_var.set(str(trigger_weights.get('special_0', self.special_weight_0_var.get())))
            self.special_weight_1_var.set(str(trigger_weights.get('special_1', self.special_weight_1_var.get())))
            self.free_weight_0_var.set(str(trigger_weights.get('free_0', self.free_weight_0_var.get())))
            self.free_weight_1_var.set(str(trigger_weights.get('free_1', self.free_weight_1_var.get())))

        if 'rebate_rules' in data:
            deps.apply_rebate_rules_config(deps.normalize_rebate_rules_for_load(data['rebate_rules']))

        sampling_options = data.get('sampling_options', {})
        if sampling_options:
            self.sampling_detailed_log_var.set(
                bool(sampling_options.get(
                    'detailed_log',
                    getattr(deps, 'default_sampling_detailed_log', False),
                ))
            )
            if hasattr(self, 'sampling_use_temp_db_var'):
                self.sampling_use_temp_db_var.set(bool(sampling_options.get('use_temp_db', False)))
            if hasattr(self, 'sampling_temp_db_var'):
                self.sampling_temp_db_var.set(str(sampling_options.get('temp_db', self.sampling_temp_db_var.get())))

        if 'group_weight_rules' in data:
            deps.apply_group_weight_rules_config(
                deps.normalize_group_weight_rules_for_load(data['group_weight_rules'])
            )

        group_options = data.get('group_weight_options', {})
        if group_options:
            if group_options.get('buy_groups'):
                group_options = dict(group_options)
                group_options.update(
                    buy_group_config.split_buy_groups_to_legacy(
                        group_options.get('buy_groups'),
                        default_buy_enabled=group_options.get('buy_enabled', deps.get_buy_group_enabled()),
                        default_buy_game_type=group_options.get('buy_game_type', deps.get_buy_group_game_type()),
                        default_buy_multiplier=group_options.get('buy_multiplier', deps.get_buy_group_multiplier()),
                        default_buy_source_suffix=group_options.get(
                            'buy_source_suffix',
                            deps.get_buy_group_source_suffix(),
                        ),
                    )
                )
            self.buy_group_enabled_var.set(bool(group_options.get('buy_enabled', deps.get_buy_group_enabled())))
            self.ex_buy_group_enabled_var.set(bool(group_options.get('ex_buy_enabled', deps.get_ex_buy_group_enabled())))
            self.ex_buy_game_type_var.set(_format_setting_text(group_options.get('ex_buy_game_type', deps.get_ex_buy_group_game_type())))
            self.ex_buy_source_suffix_var.set(_format_setting_text(group_options.get('ex_buy_source_suffix', deps.get_ex_buy_group_source_suffix())))
            self.buy_game_type_var.set(_format_setting_text(group_options.get('buy_game_type', deps.get_buy_group_game_type())))
            self.buy_multiplier_var.set(_format_setting_text(group_options.get('buy_multiplier', deps.get_buy_group_multiplier())))
            self.buy_source_suffix_var.set(_format_setting_text(group_options.get('buy_source_suffix', deps.get_buy_group_source_suffix())))
            self.ex_multiplier_var.set(_format_setting_text(group_options.get('ex_multiplier', deps.get_ex_group_multiplier())))
            _set_ex_source_suffix_vars(
                self,
                group_options.get('ex_source_suffixes', deps.get_ex_source_suffixes()),
            )
            extra_buy_groups = group_options.get('extra_buy_groups', deps.get_extra_buy_groups())
            self.set_extra_buy_group_rows(extra_buy_groups)
            if group_options.get('buy_groups'):
                getattr(deps, "apply_buy_groups_config", lambda _groups: None)(group_options['buy_groups'])
            deps.apply_extra_buy_groups_config(extra_buy_groups)
            if 'special_target_rtp' in group_options:
                deps.apply_special_group_target_rtp(group_options.get('special_target_rtp'))
            if 'ex_group_target_rtps' in group_options:
                getattr(deps, "apply_ex_group_target_rtps_config", lambda _targets: None)(
                    group_options.get('ex_group_target_rtps')
                )
            if 'zero_rebate_inference_modes' in group_options:
                getattr(deps, "apply_zero_rebate_inference_modes_config", lambda _modes: None)(
                    group_options.get('zero_rebate_inference_modes')
                )

        if not self.apply_selected_config():
            raise ValueError("配置文件中的基础配置无效")

        deps.apply_rebate_config_direct_count_modes(data.get('direct_count_modes', []))
        if 'direct_count_tiers' in data:
            deps.apply_rebate_config_direct_count_tiers(
                deps.normalize_direct_count_tiers_for_load(data['direct_count_tiers'])
            )

    def load_app_settings_from_path(self, path, *, runtime_only=False, reset_missing=False):
        data = settings_logic.read_settings_file(path)
        self.apply_app_settings_data(data, runtime_only=runtime_only, reset_missing=reset_missing)
        return self.settings_deps.consume_config_warnings()

    def auto_load_app_settings(self):
        path = self.settings_deps.get_app_settings_path()
        if not path.is_file():
            return
        self._loading_settings = True
        try:
            warnings = self.load_app_settings_from_path(path, runtime_only=True)
        except Exception as e:
            self.status_var.set(f"自动加载配置失败：{e}")
            return
        finally:
            self._loading_settings = False
        self.status_var.set(f"已自动加载上次选择：{path}")
        if warnings:
            self.status_var.set(f"已自动加载上次选择，存在兼容提示：{warnings[0]}")
        self.load_current_profile_or_defaults(auto=True)

    def load_current_profile_or_defaults(self, *, auto=False):
        deps = self.settings_deps
        vendor = self.vendor_var.get().strip()
        game_id = self.game_id_var.get().strip()
        if not vendor or not game_id:
            return False

        profile_path = deps.get_app_profile_settings_path(vendor, game_id)
        self._loading_settings = True
        try:
            if profile_path.is_file():
                warnings = self.load_app_settings_from_path(profile_path, reset_missing=True)
                self._last_profile_key_loaded = (self.vendor_var.get().strip(), self.game_id_var.get().strip())
                self.status_var.set(f"已加载房间配置：{profile_path}")
                if warnings:
                    if auto:
                        self.status_var.set(f"已加载房间配置，存在兼容提示：{warnings[0]}")
                    else:
                        messagebox.showwarning("配置兼容提示", "\n".join(warnings))
                if not auto:
                    messagebox.showinfo("加载配置", f"房间配置已加载：\n{profile_path}")
                return True

            self.reset_profile_settings_to_defaults()
            if not self.apply_selected_config():
                raise ValueError("当前基础配置无效")
            self._last_profile_key_loaded = (vendor, game_id)
            self.status_var.set(f"未找到房间配置，已使用代码默认配置：{vendor}_{game_id}")
            if not auto:
                messagebox.showinfo(
                    "加载配置",
                    f"未找到当前房间配置，已使用代码默认配置：\n{profile_path}",
                )
            return False
        except Exception as e:
            self._last_profile_key_loaded = None
            if auto:
                self.status_var.set(f"自动加载房间配置失败：{e}")
            else:
                messagebox.showerror("加载配置失败", str(e))
            return False
        finally:
            self._loading_settings = False

    def save_app_settings(self):
        if self.running:
            messagebox.showinfo("正在运行", "当前任务还没有结束，请稍后再操作。")
            return
        if not self.apply_selected_config():
            return
        deps = self.settings_deps
        data = self.build_app_settings_data()
        last_data = self.build_last_settings_data()
        profile_path = deps.get_app_profile_settings_path()
        last_path = deps.get_app_settings_path()
        try:
            write_json_atomic(profile_path, data)
            if profile_path != last_path:
                write_json_atomic(last_path, last_data)
        except Exception as e:
            messagebox.showerror("保存配置失败", str(e))
            return
        self._last_profile_key_loaded = deps.get_profile_key()
        self.status_var.set(f"已保存配置：{profile_path}")
        messagebox.showinfo(
            "保存配置",
            f"当前房间完整配置已保存到：\n{profile_path}\n\n上次选择已记录到：\n{last_path}",
        )

    def load_app_settings(self):
        if self.running:
            messagebox.showinfo("正在运行", "当前任务还没有结束，请稍后再操作。")
            return
        self.load_current_profile_or_defaults(auto=False)

    def export_rule_settings(self):
        if self.running:
            messagebox.showinfo(ui_text.RUNNING_TITLE, ui_text.RUNNING_MESSAGE)
            return
        if not self.apply_selected_config():
            return
        runtime = self.settings_deps.get_runtime_state()
        initial_name = (
            f"formation_rules_"
            f"{settings_logic.safe_settings_name(runtime['vendor'])}_"
            f"{settings_logic.safe_settings_name(runtime['game_id'])}.json"
        )
        path = filedialog.asksaveasfilename(
            title=ui_text.EXPORT_RULES_TITLE,
            defaultextension=".json",
            initialfile=initial_name,
            filetypes=((ui_text.JSON_FILE_TYPE_LABEL, "*.json"),),
        )
        if not path:
            return
        try:
            write_json_atomic(path, self.build_rule_settings_data())
        except Exception as e:
            messagebox.showerror(ui_text.EXPORT_RULES_TITLE, str(e))
            return
        self.status_var.set(f"已导出规则配置：{path}")
        messagebox.showinfo(ui_text.EXPORT_RULES_TITLE, f"规则配置已导出：\n{path}")

    def import_rule_settings(self):
        if self.running:
            messagebox.showinfo(ui_text.RUNNING_TITLE, ui_text.RUNNING_MESSAGE)
            return
        path = filedialog.askopenfilename(
            title=ui_text.IMPORT_RULES_TITLE,
            filetypes=((ui_text.JSON_FILE_TYPE_LABEL, "*.json"),),
        )
        if not path:
            return
        try:
            data = settings_logic.read_settings_file(path)
            data = dict(data)
            if not messagebox.askyesno(
                ui_text.IMPORT_RULES_PREVIEW_TITLE,
                build_rule_import_preview(data),
            ):
                return
            data.pop('runtime', None)
            data.pop('runtime_hint', None)
            self.apply_app_settings_data(data, runtime_only=False, reset_missing=False)
        except Exception as e:
            messagebox.showerror(ui_text.IMPORT_RULES_TITLE, str(e))
            return
        self.status_var.set(f"已导入规则配置：{path}")
        messagebox.showinfo(ui_text.IMPORT_RULES_TITLE, f"规则配置已导入：\n{path}")

    def load_buy_group_types_from_database(self):
        """Load buy-group rows from game_room_game_type_config and current source tables."""
        if self.running:
            messagebox.showinfo(ui_text.RUNNING_TITLE, ui_text.RUNNING_MESSAGE)
            return
        if getattr(self, "buy_group_type_loader", None) is not None and self.buy_group_type_loader.is_alive():
            messagebox.showinfo(ui_text.LOADING_BUY_TYPES_TITLE, ui_text.LOADING_BUY_TYPES_MESSAGE)
            return
        if not self.apply_selected_config():
            return

        self.set_buy_group_type_loading_state(True)
        self.status_var.set(ui_text.LOAD_BUY_TYPES_STATUS)
        if hasattr(self, "append_log"):
            self.append_log(f"\n{ui_text.LOAD_BUY_TYPES_STATUS}\n")

        def worker():
            try:
                options = self.settings_deps.load_buy_group_options_from_game_type_config(force_source=True)
            except Exception as exc:
                self.root.after(0, lambda error=exc: self.finish_buy_group_type_loading(error=error))
                return
            self.root.after(0, lambda data=options: self.finish_buy_group_type_loading(options=data))

        self.buy_group_type_loader = threading.Thread(target=worker, daemon=True)
        self.buy_group_type_loader.start()

    def set_buy_group_type_loading_state(self, loading):
        button = getattr(self, "load_buy_group_types_button", None)
        if button is not None:
            button.configure(state="disabled" if loading else "normal")

    def apply_loaded_buy_group_options(self, options):
        deps = self.settings_deps
        default_buy = options['default_buy']
        ex_buy = options.get('ex_buy', {})
        self.buy_group_enabled_var.set(bool(default_buy['enabled']))
        self.buy_game_type_var.set(_format_setting_text(default_buy['game_type']))
        self.buy_multiplier_var.set(_format_setting_text(default_buy['multiplier']))
        self.buy_source_suffix_var.set(_format_setting_text(default_buy['source_suffix']))
        self.ex_buy_group_enabled_var.set(bool(options['ex_buy_enabled']))
        if ex_buy:
            self.ex_buy_game_type_var.set(_format_setting_text(ex_buy.get('game_type', self.ex_buy_game_type_var.get())))
            self.ex_buy_source_suffix_var.set(_format_setting_text(ex_buy.get('source_suffix', self.ex_buy_source_suffix_var.get())))
        self.set_extra_buy_group_rows(options['extra_buy_groups'])

        try:
            deps.apply_buy_group_enabled(self.buy_group_enabled_var.get())
            deps.apply_buy_group_game_type(self.buy_game_type_var.get())
            deps.apply_buy_group_multiplier(self.buy_multiplier_var.get())
            deps.apply_buy_group_source_suffix(self.buy_source_suffix_var.get())
            deps.apply_ex_buy_group_enabled(self.ex_buy_group_enabled_var.get())
            deps.apply_ex_buy_group_game_type(self.ex_buy_game_type_var.get())
            deps.apply_ex_buy_group_source_suffix(self.ex_buy_source_suffix_var.get())
            deps.apply_extra_buy_groups_config(self.collect_extra_buy_groups())
            getattr(deps, "apply_buy_groups_config", lambda _groups: None)(_build_current_buy_groups(self))
        except ValueError as e:
            messagebox.showerror(ui_text.LOAD_BUY_TYPES_FAILED_TITLE, str(e))
            return False
        return True

    def build_buy_group_load_summary(self, options):
        normal_types = options.get('normal_buy_game_types', [])
        ex_types = options.get('ex_buy_game_types', [])
        skipped = options.get('skipped', [])
        return (
            f"已加载购买局类型：{normal_types or '无'}；"
            f"ex购买局类型：{ex_types or '无'}；"
            f"跳过不存在源表：{len(skipped)} 个"
        )

    def build_buy_group_skip_details(self, options):
        skipped = options.get('skipped', [])
        if not skipped:
            return ""
        lines = ["跳过的阵型类型："]
        for item in skipped:
            lines.append(
                f"- game_type={item.get('game_type')}, "
                f"source_suffix={item.get('source_suffix')}, "
                f"table={item.get('table_name')}"
            )
        return "\n".join(lines)

    def finish_buy_group_type_loading(self, *, options=None, error=None):
        self.set_buy_group_type_loading_state(False)
        if error is not None:
            self.status_var.set(ui_text.LOAD_BUY_TYPES_FAILED_TITLE)
            messagebox.showerror(ui_text.LOAD_BUY_TYPES_FAILED_TITLE, str(error))
            if hasattr(self, "append_log"):
                self.append_log(f"{ui_text.LOAD_BUY_TYPES_FAILED_TITLE}：{error}\n")
            return

        if not self.apply_loaded_buy_group_options(options):
            self.status_var.set(ui_text.LOAD_BUY_TYPES_FAILED_TITLE)
            return

        summary = self.build_buy_group_load_summary(options)
        details = self.build_buy_group_skip_details(options)
        self.status_var.set(summary)
        if hasattr(self, "append_log"):
            self.append_log(summary + "\n")
            if details:
                self.append_log(details + "\n")
        message = summary if not details else f"{summary}\n\n{details}"
        messagebox.showinfo(ui_text.LOAD_BUY_GROUP_TYPES_BUTTON, message)
        if messagebox.askyesno(ui_text.SAVE_SETTINGS_TITLE, ui_text.SAVE_BUY_TYPES_PROMPT):
            self.save_app_settings()

    def apply_selected_config(self):
        deps = self.settings_deps
        try:
            deps.apply_runtime_config(
                self.vendor_var.get(),
                self.game_id_var.get(),
                self.source_db_var.get(),
                self.final_db_var.get(),
                self.config_db_var.get(),
            )
            deps.apply_weight_config(
                self.special_weight_0_var.get(),
                self.special_weight_1_var.get(),
                self.free_weight_0_var.get(),
                self.free_weight_1_var.get(),
            )
            deps.apply_buy_group_enabled(self.buy_group_enabled_var.get())
            deps.apply_ex_buy_group_enabled(self.ex_buy_group_enabled_var.get())
            deps.apply_ex_buy_group_game_type(self.ex_buy_game_type_var.get())
            deps.apply_ex_buy_group_source_suffix(self.ex_buy_source_suffix_var.get())
            deps.apply_buy_group_game_type(self.buy_game_type_var.get())
            deps.apply_buy_group_multiplier(self.buy_multiplier_var.get())
            deps.apply_buy_group_source_suffix(self.buy_source_suffix_var.get())
            deps.apply_ex_group_multiplier(self.ex_multiplier_var.get())
            deps.apply_ex_source_suffixes_config(_collect_ex_source_suffixes(self))
            deps.apply_extra_buy_groups_config(self.collect_extra_buy_groups())
            getattr(deps, "apply_buy_groups_config", lambda _groups: None)(_build_current_buy_groups(self))
            deps.apply_sampling_detailed_log(self.sampling_detailed_log_var.get())
            getattr(deps, "apply_sampling_temp_db_config", lambda _enabled, _db: None)(
                self.sampling_use_temp_db_var.get(),
                self.sampling_temp_db_var.get(),
            )
        except ValueError as e:
            messagebox.showerror("配置错误", str(e))
            return False
        self.status_var.set(deps.get_ready_status_text())
        return True
