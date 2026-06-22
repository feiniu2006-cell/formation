"""group_weight rules configuration dialog."""

import threading
import tkinter as tk
from tkinter import messagebox, ttk

from formation_tool.group_weight import group_weight_ui_text
from formation_tool.ui.gui_components import LoadingDialogBase, RuleTableEditor
from formation_tool.ui import ui_layout_defaults

ZERO_REBATE_MISSING_TEXT = "不存在rebate=0"
DEFAULT_RTP_GROUP_ID = 9650


def choose_default_rtp_group_option(group_ids, formatter, default_group_id=DEFAULT_RTP_GROUP_ID):
    """Return the dialog's initial RTP group option."""
    group_ids = list(group_ids or [])
    if not group_ids:
        return ""
    default_group_id = int(default_group_id)
    selected_group_id = default_group_id if default_group_id in [int(group_id) for group_id in group_ids] else group_ids[0]
    return formatter(selected_group_id)


class GroupWeightRulesDialog(LoadingDialogBase):
    """group_weight 权重配置窗口。"""

    def __init__(self, app, deps):
        super().__init__(app)
        self.deps = deps
        self.formation_exists = {}
        self.preview_rebates = {}
        self.preview_status = {}
        self.displayed_modes = []
        self.dialog_modes = []
        self.rule_editor = None
        self.notebook = None
        self.current_group_var = None
        self.rtp_info_var = None
        self.special_target_rtp_var = None
        self.ex_target_rtp_vars = {}
        self.zero_rebate_inference_vars = {}
        self.special_target_entry = None
        self.ex_target_entries = {}
        self.special_has_zero_for_config = False
        self._updating_zero_rebate_state = False

    def open(self):
        self.create_dialog(
            group_weight_ui_text.DIALOG_TITLE,
            ui_layout_defaults.GROUP_WEIGHT_DIALOG,
        )
        self.show_loading()
        threading.Thread(target=self.load_dialog_data, daemon=True).start()

    def show_loading(self):
        loading_frame = ttk.Frame(self.frame)
        loading_frame.grid(row=0, column=0, sticky="nsew")
        loading_frame.columnconfigure(0, weight=1)
        loading_frame.rowconfigure(0, weight=1)
        ttk.Label(loading_frame, text=group_weight_ui_text.LOADING_TEXT).grid(
            row=0, column=0, sticky="s", pady=(0, 10)
        )
        self.loading_progress = ttk.Progressbar(loading_frame, mode="indeterminate", length=240)
        self.loading_progress.grid(row=1, column=0, sticky="n")
        self.loading_progress.start(12)

    def finish_loading(self, payload=None, error=None):
        if not self.dialog.winfo_exists():
            return
        self.stop_loading()
        self.clear_frame()
        if error is not None:
            self.show_loading_error(error)
            return
        self.build_content(
            payload['formation_exists'],
            payload['preview_rebates'],
            payload['preview_status'],
        )

    def load_dialog_data(self):
        try:
            formation_exists = self.deps.get_formation_exists()
            preview_rebates, preview_status = self.deps.load_preview_rebates(
                buy_enabled=True,
            )
            payload = {
                'formation_exists': formation_exists,
                'preview_rebates': preview_rebates,
                'preview_status': preview_status,
            }
        except Exception as e:
            self.root.after(0, lambda err=str(e): self.finish_loading(error=err))
            return
        self.root.after(0, lambda data=payload: self.finish_loading(payload=data))

    def build_content(self, formation_exists, preview_rebates, preview_status):
        self.formation_exists = formation_exists
        self.preview_rebates = preview_rebates
        self.preview_status = preview_status

        self.frame.rowconfigure(0, weight=0)
        self.frame.rowconfigure(1, weight=0)
        self.frame.rowconfigure(2, weight=0)
        self.frame.rowconfigure(3, weight=1)
        self.frame.rowconfigure(4, weight=0)

        self.displayed_modes = list(self.deps.get_displayed_modes(formation_exists))
        self.dialog_modes = list(dict.fromkeys(list(self.deps.group_weight_modes) + self.displayed_modes))
        self.special_has_zero_for_config = (
            formation_exists.get('2', False)
            and 0 in {int(value) for value in preview_rebates.get('2', [])}
        )
        self.initialize_zero_rebate_inference_vars()

        self.show_missing_config_warning()
        self.build_header()
        self.build_rtp_selector()
        self.build_rule_tabs()
        self.build_buttons()
        self.update_rtp_info()

    def show_missing_config_warning(self):
        missing_or_empty = self.deps.collect_preview_warnings(
            self.displayed_modes,
            self.preview_rebates,
            self.preview_status,
        )
        if not missing_or_empty:
            return
        messagebox.showwarning(
            group_weight_ui_text.MISSING_CONFIG_TITLE,
            group_weight_ui_text.build_missing_config_warning_message(missing_or_empty),
            parent=self.dialog,
        )

    def build_header(self):
        ttk.Label(
            self.frame,
            text=group_weight_ui_text.RULE_HELP_TEXT,
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))

        status_text = group_weight_ui_text.build_detection_status_text(
            self.deps,
            self.formation_exists,
            self.displayed_modes,
        )
        ttk.Label(self.frame, text=status_text, foreground="#555555").grid(
            row=1, column=0, sticky="w", pady=(0, 8)
        )

    def build_rtp_selector(self):
        group_options = [self.deps.format_group_rtp_option(group_id) for group_id in self.deps.weight_group_ids]
        self.current_group_var = tk.StringVar(
            value=choose_default_rtp_group_option(
                self.deps.weight_group_ids,
                self.deps.format_group_rtp_option,
            )
        )
        self.rtp_info_var = tk.StringVar()
        self.special_target_rtp_var = tk.StringVar(
            value="" if self.deps.special_target_rtp is None else str(self.deps.special_target_rtp)
        )
        ex_targets = getattr(self.deps, 'ex_group_target_rtps', {}) or {}
        ex_target_modes = getattr(self.deps, 'ex_independent_group_weight_modes', ('7',))
        self.ex_target_rtp_vars = {
            mode: tk.StringVar(value="" if ex_targets.get(mode) is None else str(ex_targets.get(mode)))
            for mode in ex_target_modes
        }

        rtp_frame = ttk.Frame(self.frame)
        rtp_frame.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        rtp_frame.columnconfigure(1, weight=1)
        ttk.Label(rtp_frame, text="当前RTP组").grid(row=0, column=0, sticky="w", padx=(0, 8))
        current_group_combo = ttk.Combobox(
            rtp_frame,
            textvariable=self.current_group_var,
            values=group_options,
            state="readonly",
            width=36,
        )
        current_group_combo.grid(row=0, column=1, sticky="w")
        ttk.Label(rtp_frame, textvariable=self.rtp_info_var, wraplength=760, justify="left").grid(
            row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0)
        )

        current_group_combo.bind("<<ComboboxSelected>>", self.update_rtp_info)
        self.special_target_rtp_var.trace_add("write", lambda *_args: self.update_rtp_info())
        for var in self.ex_target_rtp_vars.values():
            var.trace_add("write", lambda *_args: self.update_rtp_info())

    def initialize_zero_rebate_inference_vars(self):
        if hasattr(self.deps, 'zero_rebate_inference_modes'):
            enabled_modes = {str(mode) for mode in (self.deps.zero_rebate_inference_modes or set())}
        else:
            enabled_modes = {str(mode) for mode in getattr(self.deps, 'default_zero_rebate_inference_modes', ())}
        supports = getattr(self.deps, 'supports_zero_rebate_inference', lambda _mode: False)
        self.zero_rebate_inference_vars = {
            mode: tk.BooleanVar(value=str(mode) in enabled_modes)
            for mode in self.dialog_modes
            if supports(mode)
        }

    def build_rule_tabs(self):
        self.notebook = ttk.Notebook(self.frame)
        self.notebook.grid(row=3, column=0, sticky="nsew")
        self.notebook.bind("<<NotebookTabChanged>>", self.update_rtp_info)

        self.rule_editor = RuleTableEditor(
            self.notebook,
            self.deps.rule_fields,
            self.deps.rule_field_labels,
            row_width=18,
            on_change=lambda: self.update_rtp_info(),
        )

        for mode in self.displayed_modes:
            mode_name = self.deps.get_mode_name(mode)
            self.rule_editor.add_mode_tab(
                mode,
                mode_name,
                self.get_initial_rules_for_mode(mode),
                add_button_text=f"新增{mode_name}区间",
                options_builder=self.build_mode_options,
            )
        self.apply_zero_rebate_entry_states()
        self.refresh_zero_rebate_option_states()

    def mode_has_rebate_zero(self, mode):
        try:
            return any(int(value) == 0 for value in self.preview_rebates.get(str(mode), []))
        except (TypeError, ValueError):
            return False

    def mode_zero_rebate_inference_enabled(self, mode):
        var = getattr(self, 'zero_rebate_inference_vars', {}).get(str(mode))
        return bool(var is not None and var.get() and self.mode_has_rebate_zero(mode))

    def collect_zero_rebate_inference_modes(self):
        return {
            str(mode)
            for mode, var in getattr(self, 'zero_rebate_inference_vars', {}).items()
            if var.get()
        }

    def refresh_zero_rebate_option_states(self):
        special_target_entry = getattr(self, 'special_target_entry', None)
        if special_target_entry is not None:
            special_target_entry.configure(
                state="normal" if self.mode_zero_rebate_inference_enabled('2') else "disabled"
            )
        for mode, entry in getattr(self, 'ex_target_entries', {}).items():
            entry.configure(
                state="normal" if self.mode_zero_rebate_inference_enabled(mode) else "disabled"
            )

    def on_zero_rebate_inference_changed(self, mode):
        self.refresh_zero_rebate_option_states()
        self.update_rtp_info()

    def build_zero_rebate_inference_option(self, mode, options_frame, row=0):
        var = getattr(self, 'zero_rebate_inference_vars', {}).get(str(mode))
        if var is None:
            return row
        has_zero = self.mode_has_rebate_zero(mode)
        ttk.Checkbutton(
            options_frame,
            text="rebate=0 反推",
            variable=var,
            command=lambda m=mode: self.on_zero_rebate_inference_changed(m),
            state="normal" if has_zero else "disabled",
        ).grid(row=row, column=0, sticky="w", padx=(0, 8))
        note_text = "采样配置存在 rebate=0" if has_zero else "不存在 rebate=0，本次不会反推"
        ttk.Label(options_frame, text=note_text, foreground="#555555").grid(
            row=row, column=1, columnspan=2, sticky="w"
        )
        return row + 1

    def is_missing_zero_rebate_rule_row(self, mode, row_info):
        rebate_var = row_info.get('vars', {}).get('rebate_min')
        return (
            rebate_var is not None
            and rebate_var.get().strip() == "0"
            and not self.mode_has_rebate_zero(mode)
        )

    def apply_zero_rebate_entry_states(self, mode=None):
        if self.rule_editor is None or not hasattr(self.rule_editor, 'get_rows'):
            return
        modes = [mode] if mode is not None else list(getattr(self.rule_editor, 'mode_rows', {}))
        self._updating_zero_rebate_state = True
        try:
            for item_mode in modes:
                for row_info in self.rule_editor.get_rows(item_mode):
                    weight_var = row_info.get('vars', {}).get('weight')
                    weight_entry = row_info.get('entries', {}).get('weight')
                    if weight_var is None or weight_entry is None:
                        continue
                    if self.is_missing_zero_rebate_rule_row(item_mode, row_info):
                        if weight_var.get() != ZERO_REBATE_MISSING_TEXT:
                            weight_var.set(ZERO_REBATE_MISSING_TEXT)
                        weight_entry.configure(state="disabled")
                    else:
                        if weight_var.get() == ZERO_REBATE_MISSING_TEXT:
                            weight_var.set("0")
                        weight_entry.configure(state="normal")
        finally:
            self._updating_zero_rebate_state = False

    def build_buttons(self):
        button_frame = ttk.Frame(self.frame)
        button_frame.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        button_frame.columnconfigure(0, weight=1)
        ttk.Button(
            button_frame,
            text="恢复默认权重规则",
            command=self.reset_group_weight_rules_to_defaults,
        ).grid(row=0, column=1, sticky="e", padx=(0, 8))
        ttk.Button(
            button_frame,
            text=group_weight_ui_text.CONFIRM_BUTTON_TEXT,
            command=self.confirm_and_run,
        ).grid(row=0, column=2, sticky="e", padx=(0, 8))
        ttk.Button(
            button_frame,
            text=group_weight_ui_text.CANCEL_BUTTON_TEXT,
            command=self.dialog.destroy,
        ).grid(row=0, column=3, sticky="e")

    def get_initial_rules_for_mode(self, mode):
        if self.deps.is_extra_buy_mode(mode):
            extra_group = self.deps.get_extra_buy_group_by_mode(mode) or {}
            return extra_group.get('rules', self.deps.default_rules.get(self.deps.buy_group_mode, []))
        return self.deps.rules.get(mode, [])

    def get_default_rules_for_mode(self, mode):
        if self.deps.is_extra_buy_mode(mode):
            return self.deps.default_rules.get(self.deps.buy_group_mode, [])
        return self.deps.default_rules.get(mode, [])

    def reset_group_weight_rules_to_defaults(self):
        if not messagebox.askyesno(
            "恢复默认权重规则",
            "将当前窗口里的 group_weight 权重规则恢复为代码默认值，点击“确认并开始”后生效。是否继续？",
            parent=self.dialog,
        ):
            return
        for mode in list(self.rule_editor.mode_rows):
            self.rule_editor.clear_rule_rows(mode)
            for rule in self.get_default_rules_for_mode(mode):
                self.rule_editor.add_rule_row(mode, rule)
        self.apply_zero_rebate_entry_states()
        default_target = getattr(self.deps, 'default_special_target_rtp', None)
        self.special_target_rtp_var.set("" if default_target is None else str(default_target))
        default_ex_targets = getattr(self.deps, 'default_ex_group_target_rtps', {}) or {}
        for mode, var in getattr(self, 'ex_target_rtp_vars', {}).items():
            var.set("" if default_ex_targets.get(mode) is None else str(default_ex_targets.get(mode)))
        default_inference_modes = {
            str(mode) for mode in getattr(self.deps, 'default_zero_rebate_inference_modes', ())
        }
        for mode, var in getattr(self, 'zero_rebate_inference_vars', {}).items():
            var.set(str(mode) in default_inference_modes)
        self.refresh_zero_rebate_option_states()
        self.update_rtp_info()

    def build_mode_options(self, mode, options_frame):
        row = self.build_zero_rebate_inference_option(mode, options_frame, row=0)
        if mode == '2':
            ttk.Label(options_frame, text="特殊局目标RTP").grid(row=row, column=0, sticky="w", padx=(0, 8))
            special_target_entry = ttk.Entry(options_frame, textvariable=self.special_target_rtp_var, width=14)
            special_target_entry.grid(row=row, column=1, sticky="w")
            self.special_target_entry = special_target_entry
            special_target_entry.configure(
                state="normal" if self.mode_zero_rebate_inference_enabled(mode) else "disabled"
            )
            note_text = group_weight_ui_text.build_special_target_note(
                self.mode_zero_rebate_inference_enabled(mode)
            )
            ttk.Label(options_frame, text=note_text, foreground="#555555").grid(
                row=row, column=2, sticky="w", padx=(10, 0)
            )
            return True
        if mode in getattr(self, 'ex_target_rtp_vars', {}):
            mode_name = self.deps.get_mode_name(mode)
            ttk.Label(options_frame, text=f"{mode_name}目标RTP").grid(
                row=row, column=0, sticky="w", padx=(0, 8)
            )
            target_entry = ttk.Entry(options_frame, textvariable=self.ex_target_rtp_vars[mode], width=14)
            target_entry.grid(row=row, column=1, sticky="w")
            self.ex_target_entries[mode] = target_entry
            target_entry.configure(
                state="normal" if self.mode_zero_rebate_inference_enabled(mode) else "disabled"
            )
            note_text = (
                f"按除以 ex倍数后的实际RTP填写；留空使用当前RTP组目标，"
                f"反推目标=目标RTP*{self.deps.format_weighted_rtp(self.deps.ex_multiplier)}"
            )
            ttk.Label(options_frame, text=note_text, foreground="#555555").grid(
                row=row, column=2, sticky="w", padx=(10, 0)
            )
            return True
        note_text = group_weight_ui_text.build_mode_option_note(mode, self.deps)
        if note_text:
            ttk.Label(options_frame, text=note_text, foreground="#555555").grid(
                row=row, column=0, columnspan=3, sticky="w"
            )
            return True
        return row > 0

    def parse_dialog_rules(self, mode):
        parsed_rules = []
        for row_info in self.rule_editor.get_rows(mode):
            rebate_text = row_info['vars']['rebate_min'].get().strip()
            weight_text = row_info['vars']['weight'].get().strip()
            missing_zero_row = self.is_missing_zero_rebate_rule_row(mode, row_info)
            if not rebate_text and not weight_text:
                continue
            if not rebate_text or (not weight_text and not missing_zero_row):
                return None, group_weight_ui_text.PARSE_INCOMPLETE_ROW
            try:
                rebate = self.deps.parse_non_negative_int_text(rebate_text, "rebate下限")
                weight = 0 if missing_zero_row else self.deps.parse_non_negative_int_text(weight_text, "权重")
            except ValueError:
                return None, group_weight_ui_text.PARSE_NOT_INTEGER
            parsed_rules.append({'rebate_min': rebate, 'weight': weight})
        return sorted(parsed_rules, key=lambda item: item['rebate_min']), None

    def parse_special_target_for_preview(self):
        text = self.special_target_rtp_var.get().strip()
        if not text:
            return None, "特殊局存在 rebate=0，请填写特殊局目标RTP"
        try:
            return self.deps.parse_positive_float_text(text, "特殊局目标RTP"), None
        except ValueError as e:
            return None, str(e)

    def parse_ex_target_rtps_for_preview(self):
        targets = {}
        errors = {}
        for mode, var in getattr(self, 'ex_target_rtp_vars', {}).items():
            if not self.mode_zero_rebate_inference_enabled(mode):
                continue
            text = var.get().strip()
            if not text:
                continue
            try:
                targets[mode] = self.deps.parse_positive_float_text(
                    text,
                    f"{self.deps.get_mode_name(mode)}目标RTP",
                )
            except ValueError as e:
                errors[mode] = str(e)
        return targets, errors

    def update_rtp_info(self, _event=None):
        if getattr(self, '_updating_zero_rebate_state', False):
            return
        self.apply_zero_rebate_entry_states()
        self.refresh_zero_rebate_option_states()
        text = self.current_group_var.get()
        try:
            group_id = int(text.split(" ", 1)[0])
        except (ValueError, IndexError):
            self.rtp_info_var.set(group_weight_ui_text.DEFAULT_PREVIEW_TEXT)
            return
        try:
            current_mode = self.displayed_modes[self.notebook.index("current")]
        except Exception:
            current_mode = self.displayed_modes[0] if self.displayed_modes else self.deps.buy_group_mode

        rules_by_mode = {}
        parse_errors = {}
        for mode in self.dialog_modes:
            rules_by_mode[mode], parse_errors[mode] = self.parse_dialog_rules(mode)
        ex_target_rtps, ex_target_errors = self.parse_ex_target_rtps_for_preview()
        parse_errors.update(ex_target_errors)

        special_target, special_target_error = (
            self.parse_special_target_for_preview() if self.mode_zero_rebate_inference_enabled('2') else (None, None)
        )
        try:
            current_rtp_text = self.deps.build_preview_text(
                current_mode,
                group_id,
                rules_by_mode,
                parse_errors,
                self.preview_rebates,
                self.preview_status,
                self.formation_exists,
                special_has_zero_for_config=self.special_has_zero_for_config,
                special_target_rtp=special_target,
                special_target_error=special_target_error,
                buy_multiplier=self.deps.buy_multiplier,
                ex_multiplier=self.deps.ex_multiplier,
                ex_target_rtps=ex_target_rtps,
                zero_rebate_inference_modes=self.collect_zero_rebate_inference_modes(),
                buy_enabled=self.deps.buy_enabled or self.deps.has_extra_buy_groups(),
            )
        except ValueError as e:
            current_rtp_text = str(e)
        except Exception as e:
            print(f"[WARN] group_weight preview failed: {e}")
            current_rtp_text = f"\u9884\u89c8\u751f\u6210\u5931\u8d25\uff1a{e}"

        self.rtp_info_var.set(
            group_weight_ui_text.build_rtp_info_text(
                self.deps,
                group_id,
                current_mode,
                current_rtp_text,
            )
        )

    def parse_group_weight_rule_rows(self, mode, rows):
        mode_rules = []
        mode_name = self.deps.get_mode_name(mode)
        for row_idx, row_info in enumerate(rows, start=1):
            missing_zero_row = self.is_missing_zero_rebate_rule_row(mode, row_info)
            texts = {
                field: row_info['vars'][field].get().strip()
                for field in self.deps.rule_fields
            }
            if not any(texts.values()):
                continue
            rule = {}
            for field, text in texts.items():
                if not text:
                    label = self.deps.rule_field_labels[field]
                    raise ValueError(f"{mode_name}第 {row_idx} 行 {label} 不能为空")
                label = self.deps.rule_field_labels[field]
                if field == 'weight' and missing_zero_row:
                    rule[field] = 0
                else:
                    rule[field] = self.deps.parse_non_negative_int_text(
                        text,
                        f"{mode_name}第 {row_idx} 行 {label}",
                    )
            mode_rules.append(rule)
        return mode_rules

    def collect_group_weight_rules(self, include_buy):
        rules = {}
        for mode in self.deps.group_weight_modes:
            if mode not in self.displayed_modes:
                rules[mode] = self.deps.rules.get(mode, [])
                continue
            if mode == self.deps.buy_group_mode and not include_buy:
                rules[mode] = self.deps.rules.get(mode, [])
                continue
            rules[mode] = self.parse_group_weight_rule_rows(
                mode,
                self.rule_editor.get_rows(mode),
            )
        return self.deps.validate_rules(rules)

    def collect_extra_buy_groups_with_rules(self):
        groups = []
        for group in self.deps.extra_buy_groups:
            mode = self.deps.make_extra_buy_mode(group['game_type'])
            updated = dict(group)
            if mode in self.displayed_modes:
                updated['rules'] = self.parse_group_weight_rule_rows(
                    mode,
                    self.rule_editor.get_rows(mode),
                )
            groups.append(updated)
        return self.deps.normalize_extra_buy_groups(groups)

    def confirm_and_run(self):
        try:
            rules = self.collect_group_weight_rules(
                self.deps.buy_enabled or self.deps.has_extra_buy_groups()
            )
            extra_buy_groups = self.collect_extra_buy_groups_with_rules()
            special_target_text = self.special_target_rtp_var.get().strip()
            special_inference_enabled = self.mode_zero_rebate_inference_enabled('2')
            if special_inference_enabled and not special_target_text:
                raise ValueError("特殊局采样配置中存在 rebate=0，请填写特殊局目标RTP")

            ex_target_rtps, ex_target_errors = self.parse_ex_target_rtps_for_preview()
            if ex_target_errors:
                raise ValueError(next(iter(ex_target_errors.values())))

            self.deps.apply_special_target(
                special_target_text if special_inference_enabled else ""
            )
        except ValueError as e:
            messagebox.showerror("group_weight 权重配置错误", str(e), parent=self.dialog)
            return

        self.deps.apply_rules(rules)
        self.deps.apply_ex_group_target_rtps(ex_target_rtps)
        self.deps.apply_zero_rebate_inference_modes(self.collect_zero_rebate_inference_modes())
        self.deps.apply_extra_buy_groups(extra_buy_groups)
        self.dialog.destroy()
        self.app.run_task(
            "生成group_weight",
            self.deps.generate_config,
            preflight={"kind": "group_weight"},
        )

