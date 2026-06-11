"""Rebate sampling rules configuration dialog."""

import threading
import tkinter as tk
from tkinter import messagebox, ttk

from formation_tool.ui import ui_layout_defaults
from formation_tool.ui.gui_components import LoadingDialogBase, RuleTableEditor


DIRECT_COUNT_TIER_MODE = '__direct_count_tiers__'
DIRECT_COUNT_TIER_FIELDS = ('rebate', 'rebate_min', 'rebate_max', 'count')
DIRECT_COUNT_TIER_LABELS = {
    'rebate': '精确rebate',
    'rebate_min': 'rebate_min',
    'rebate_max': 'rebate_max',
    'count': 'count上限',
}


class RebateRulesDialog(LoadingDialogBase):
    """采样规则配置窗口。"""

    def __init__(
        self,
        app,
        *,
        sample_game_type_names,
        rule_fields,
        rule_field_labels,
        low_volume_threshold,
        current_rules_getter,
        default_rules_getter,
        clone_rules,
        validate_rules,
        apply_rules,
        apply_direct_count_modes,
        current_direct_count_tiers_getter,
        default_direct_count_tiers_getter,
        normalize_direct_count_tiers,
        apply_direct_count_tiers,
        formation_exists_loader,
        low_volume_infos_loader,
        generate_configs,
        ready_status_getter,
        index_warnings_loader=None,
    ):
        super().__init__(app)
        self.sample_game_type_names = sample_game_type_names
        self.rule_fields = rule_fields
        self.rule_field_labels = rule_field_labels
        self.low_volume_threshold = low_volume_threshold
        self.current_rules_getter = current_rules_getter
        self.default_rules_getter = default_rules_getter
        self.clone_rules = clone_rules
        self.validate_rules = validate_rules
        self.apply_rules = apply_rules
        self.apply_direct_count_modes = apply_direct_count_modes
        self.current_direct_count_tiers_getter = current_direct_count_tiers_getter
        self.default_direct_count_tiers_getter = default_direct_count_tiers_getter
        self.normalize_direct_count_tiers = normalize_direct_count_tiers
        self.apply_direct_count_tiers = apply_direct_count_tiers
        self.formation_exists_loader = formation_exists_loader
        self.low_volume_infos_loader = low_volume_infos_loader
        self.generate_configs = generate_configs
        self.ready_status_getter = ready_status_getter
        self.index_warnings_loader = index_warnings_loader or (lambda _rules: [])

        self.formation_exists = {}
        self.mode_names = {}
        self.missing_modes = []
        self.base_rules = {}
        self.rule_editor = None
        self.direct_count_tier_editor = None
        self.check_status_var = None
        self.check_progress = None
        self.restore_button = None
        self.confirm_button = None
        self.cancel_button = None

    def open(self):
        self.create_dialog(
            "采样规则配置",
            ui_layout_defaults.REBATE_RULES_DIALOG,
        )
        self.show_loading()
        threading.Thread(target=self.load_dialog_data, daemon=True).start()

    def show_loading(self):
        loading_frame = ttk.Frame(self.frame)
        loading_frame.grid(row=0, column=0, sticky="nsew")
        loading_frame.columnconfigure(0, weight=1)
        loading_frame.rowconfigure(0, weight=1)
        ttk.Label(loading_frame, text="正在检测可配置采样源表，请稍候...").grid(
            row=0, column=0, sticky="s", pady=(0, 10)
        )
        self.loading_progress = ttk.Progressbar(loading_frame, mode="indeterminate", length=260)
        self.loading_progress.grid(row=1, column=0, sticky="n")
        self.loading_progress.start(12)

    def finish_loading(self, formation_exists=None, error=None):
        if not self.dialog.winfo_exists():
            return
        self.stop_loading()
        self.clear_frame()
        if error is not None:
            self.show_loading_error(error)
            return
        self.build_content(formation_exists or {})

    def load_dialog_data(self):
        try:
            formation_exists = self.formation_exists_loader()
        except Exception as e:
            self.root.after(0, lambda err=str(e): self.finish_loading(error=err))
            return
        self.root.after(0, lambda data=formation_exists: self.finish_loading(formation_exists=data))

    def build_content(self, formation_exists):
        self.formation_exists = formation_exists
        self.mode_names = {
            mode: name
            for mode, name in self.sample_game_type_names.items()
            if formation_exists.get(mode, False)
        }
        self.missing_modes = [
            name
            for mode, name in self.sample_game_type_names.items()
            if not formation_exists.get(mode, False)
        ]
        if not self.mode_names:
            self.show_empty_source_message()
            return

        self.frame.rowconfigure(0, weight=0)
        self.frame.rowconfigure(1, weight=0)
        self.frame.rowconfigure(2, weight=1)
        self.frame.rowconfigure(3, weight=0)

        self.base_rules = self.clone_rules(self.current_rules_getter())
        self.build_header()
        self.build_rule_tabs()
        self.build_buttons()

    def show_empty_source_message(self):
        ttk.Label(
            self.frame,
            text="当前游戏没有检测到可采样的 formation 源表，请检查厂商、游戏编号和源库配置。",
            foreground="#990000",
            wraplength=760,
        ).grid(row=0, column=0, sticky="w")
        ttk.Button(self.frame, text="关闭", command=self.dialog.destroy).grid(
            row=1, column=0, sticky="e", pady=(12, 0)
        )

    def build_header(self):
        ttk.Label(
            self.frame,
            text="请配置采样规则。空白字段表示不使用该字段；每行需填写 count，并选择精确 rebate 或 rebate_min/rebate_max 范围。",
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))
        status_text = (
            f"已检测：{', '.join(self.mode_names.values())}"
            + (f"；未检测：{', '.join(self.missing_modes)}" if self.missing_modes else "")
        )
        ttk.Label(self.frame, text=status_text, foreground="#555555").grid(
            row=1, column=0, sticky="w", pady=(0, 8)
        )

    def build_rule_tabs(self):
        notebook = ttk.Notebook(self.frame)
        notebook.grid(row=2, column=0, sticky="nsew")

        self.rule_editor = RuleTableEditor(
            notebook,
            self.rule_fields,
            self.rule_field_labels,
            row_width=13,
            x_scroll=True,
        )
        for mode in self.mode_names:
            self.rule_editor.add_mode_tab(
                mode,
                self.mode_names[mode],
                self.base_rules.get(mode, []),
                add_button_text=f"新增{self.mode_names[mode]}规则",
            )
        self.direct_count_tier_editor = RuleTableEditor(
            notebook,
            DIRECT_COUNT_TIER_FIELDS,
            DIRECT_COUNT_TIER_LABELS,
            row_width=13,
            x_scroll=True,
        )
        self.direct_count_tier_editor.add_mode_tab(
            DIRECT_COUNT_TIER_MODE,
            "直接计数阶梯",
            self.current_direct_count_tiers_getter(),
            add_button_text="新增直接计数阶梯",
        )

    def build_buttons(self):
        button_frame = ttk.Frame(self.frame)
        button_frame.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        button_frame.columnconfigure(0, weight=1)

        self.check_status_var = tk.StringVar(value="")
        ttk.Label(button_frame, textvariable=self.check_status_var).grid(row=0, column=0, sticky="w")
        self.check_progress = ttk.Progressbar(button_frame, mode="indeterminate", length=160)

        self.restore_button = ttk.Button(
            button_frame,
            text="恢复默认采样规则",
            command=self.reset_rebate_rules_to_defaults,
        )
        self.restore_button.grid(row=0, column=2, sticky="e", padx=(0, 8))
        self.confirm_button = ttk.Button(
            button_frame,
            text="确认并开始",
            command=self.confirm_and_run,
        )
        self.confirm_button.grid(row=0, column=3, sticky="e", padx=(0, 8))
        self.cancel_button = ttk.Button(
            button_frame,
            text="取消",
            command=self.dialog.destroy,
        )
        self.cancel_button.grid(row=0, column=4, sticky="e")

    def reset_rebate_rules_to_defaults(self):
        if not messagebox.askyesno(
            "恢复默认采样规则",
            "将当前窗口里的采样规则恢复为代码默认值，确认后生效。是否继续？",
            parent=self.dialog,
        ):
            return
        default_rules = self.clone_rules(self.default_rules_getter())
        self.base_rules.clear()
        self.base_rules.update(default_rules)
        for mode in list(self.rule_editor.mode_rows):
            self.rule_editor.clear_rule_rows(mode)
            for rule in self.base_rules.get(mode, []):
                self.rule_editor.add_rule_row(mode, rule)
        self.direct_count_tier_editor.clear_rule_rows(DIRECT_COUNT_TIER_MODE)
        for rule in self.default_direct_count_tiers_getter():
            self.direct_count_tier_editor.add_rule_row(DIRECT_COUNT_TIER_MODE, rule)
        self.check_status_var.set("已恢复代码默认采样规则和直接计数阶梯，点击“确认并开始”后生效")

    def collect_rebate_rules(self):
        rules = self.clone_rules(self.base_rules)
        for mode, rows in self.rule_editor.mode_rows.items():
            mode_rules = []
            for row_idx, row_info in enumerate(rows, start=1):
                rule = {}
                for field, variable in row_info['vars'].items():
                    text = variable.get().strip()
                    if not text:
                        continue
                    try:
                        rule[field] = int(text)
                    except ValueError:
                        label = self.rule_field_labels[field]
                        raise ValueError(
                            f"{self.mode_names[mode]}第 {row_idx} 行 {label} 必须是整数: {text}"
                        ) from None
                if rule:
                    mode_rules.append(rule)
            rules[mode] = mode_rules
        return self.validate_rules(rules)

    def collect_direct_count_tiers(self):
        tiers = []
        rows = self.direct_count_tier_editor.mode_rows.get(DIRECT_COUNT_TIER_MODE, [])
        for row_idx, row_info in enumerate(rows, start=1):
            rule = {}
            for field, variable in row_info['vars'].items():
                text = variable.get().strip()
                if not text:
                    continue
                try:
                    rule[field] = int(text)
                except ValueError:
                    label = DIRECT_COUNT_TIER_LABELS[field]
                    raise ValueError(f"直接计数阶梯第 {row_idx} 行 {label} 必须是整数: {text}") from None
            if rule:
                tiers.append(rule)
        return self.normalize_direct_count_tiers(tiers)

    def set_low_volume_check_state(self, checking):
        button_state = "disabled" if checking else "normal"
        self.confirm_button.configure(state=button_state)
        self.restore_button.configure(state=button_state)
        self.cancel_button.configure(state=button_state)
        if checking:
            self.check_status_var.set("正在后台检查源表数据量...")
            self.check_progress.grid(row=0, column=1, sticky="e", padx=(8, 8))
            self.check_progress.start(12)
            self.app.status_var.set("正在检查源表数据量...")
            return
        self.check_progress.stop()
        self.check_progress.grid_remove()
        self.check_status_var.set("")
        self.app.status_var.set(self.ready_status_getter())

    def finish_low_volume_check(self, rules, direct_count_tiers, low_volume_infos=None, error=None):
        if not self.dialog.winfo_exists():
            return
        self.set_low_volume_check_state(False)
        if error is not None:
            messagebox.showerror("源表数据量检查失败", error, parent=self.dialog)
            return

        direct_count_modes = set()
        for info in low_volume_infos or []:
            use_rules = messagebox.askyesno(
                "源表数据量低于阈值",
                (
                    f"{info['name']} 源表数据量低于 {self.low_volume_threshold} 条。\n\n"
                    f"源表：{info['source_db']}.{info['source_table']}\n"
                    f"配置表：{info['config_db']}.{info['config_table']}\n"
                    f"查询条件：{info['condition']}\n"
                    f"当前数据量：{info['total']}\n\n"
                    "是否按照现有采样规则生成采样配置？\n\n"
                    "选择“是”：继续使用当前采样规则。\n"
                    "选择“否”：不套用采样规则，直接将查询到的 rebate 和数量写入 count 表。"
                ),
                parent=self.dialog,
            )
            if not use_rules:
                direct_count_modes.add(info['mode'])

        self.apply_rules(rules)
        self.apply_direct_count_tiers(direct_count_tiers)
        self.apply_direct_count_modes(direct_count_modes)
        self.dialog.destroy()
        self.app.run_task(
            "生成采样配置",
            self.generate_configs,
            preflight={"kind": "rebate_config", "modes": list(self.mode_names), "index_checked": True},
        )

    def finish_index_check(self, rules, direct_count_tiers, warnings=None, error=None):
        if not self.dialog.winfo_exists():
            return
        self.set_low_volume_check_state(False)
        if error is not None:
            messagebox.showerror("索引检查失败", error, parent=self.dialog)
            return

        warnings = list(warnings or [])
        if warnings:
            details = []
            for item in warnings[:8]:
                details.append(
                    f"{item['name']}：{item['source_db']}.{item['source_table']}\n"
                    f"原因：{item['warning']}\n"
                    f"条件：{item['condition']}"
                )
            if len(warnings) > 8:
                details.append(f"还有 {len(warnings) - 8} 个表存在索引风险。")
            should_continue = messagebox.askyesno(
                "采样配置索引风险",
                (
                    "检测到部分源表没有使用合适的 rebate 统计索引，继续生成可能耗时很久。\n\n"
                    + "\n\n".join(details)
                    + "\n\n是否仍然继续？"
                ),
                parent=self.dialog,
            )
            if not should_continue:
                self.check_status_var.set("已中断生成采样配置")
                self.app.status_var.set(self.ready_status_getter())
                return

        self.start_low_volume_check(rules, direct_count_tiers)

    def start_low_volume_check(self, rules, direct_count_tiers):
        self.set_low_volume_check_state(True)
        self.check_status_var.set("正在后台检查源表数据量...")
        self.app.status_var.set("正在检查源表数据量...")
        visible_rules = {mode: rules[mode] for mode in self.mode_names}

        def worker():
            try:
                low_volume_infos = self.low_volume_infos_loader(visible_rules)
            except Exception as e:
                self.root.after(0, lambda err=str(e): self.finish_low_volume_check(rules, direct_count_tiers, error=err))
                return
            self.root.after(
                0,
                lambda infos=low_volume_infos: self.finish_low_volume_check(
                    rules,
                    direct_count_tiers,
                    low_volume_infos=infos,
                ),
            )

        threading.Thread(target=worker, daemon=True).start()

    def confirm_and_run(self):
        try:
            rules = self.collect_rebate_rules()
            direct_count_tiers = self.collect_direct_count_tiers()
        except ValueError as e:
            messagebox.showerror("采样规则错误", str(e), parent=self.dialog)
            return

        self.set_low_volume_check_state(True)
        self.check_status_var.set("正在后台检查源表索引...")
        self.app.status_var.set("正在检查源表索引...")
        visible_rules = {mode: rules[mode] for mode in self.mode_names}

        def worker():
            try:
                warnings = self.index_warnings_loader(visible_rules)
            except Exception as e:
                self.root.after(0, lambda err=str(e): self.finish_index_check(rules, direct_count_tiers, error=err))
                return
            self.root.after(
                0,
                lambda items=warnings: self.finish_index_check(
                    rules,
                    direct_count_tiers,
                    warnings=items,
                ),
            )

        threading.Thread(target=worker, daemon=True).start()

