"""group_weight rules configuration dialog."""

import threading
import tkinter as tk
from tkinter import messagebox, ttk

from formation_tool.group_weight import group_weight_ui_text
from formation_tool.ui.gui_components import LoadingDialogBase, RuleTableEditor
from formation_tool.ui import ui_layout_defaults

ZERO_REBATE_MISSING_TEXT = "不存在rebate=0"
DEFAULT_RTP_GROUP_ID = 9650
REBATE_RANGE_BUCKETS = (
    ("0\u500d", 0, 1),
    ("1\u500d\u4ee5\u4e0b", 1, 1000),
    ("1~10\u500d", 1000, 10000),
    ("10~20\u500d", 10000, 20000),
    ("20~60\u500d", 20000, 60000),
    ("60~80\u500d", 60000, 80000),
    ("80~100\u500d", 80000, 100000),
    ("100~500\u500d", 100000, 500000),
    ("500\u500d\u4ee5\u4e0a", 500000, None),
)


def clone_mode_rules_map(rules):
    return {
        str(mode): [dict(rule) for rule in mode_rules]
        for mode, mode_rules in (rules or {}).items()
    }


def clone_group_rules_map(rules):
    return {
        str(group_suffix): clone_mode_rules_map(mode_rules)
        for group_suffix, mode_rules in (rules or {}).items()
        if isinstance(mode_rules, dict)
    }


def normalize_weight_curve_points(rules):
    """Return sorted (rebate, weight) points that can be drawn on the chart."""
    points_by_rebate = {}
    for rule in rules or []:
        try:
            rebate = int(rule.get('rebate_min'))
            weight = int(rule.get('weight'))
        except (TypeError, ValueError):
            continue
        if rebate < 0 or weight < 0:
            continue
        points_by_rebate[rebate] = weight
    return sorted(points_by_rebate.items())


def filter_weight_curve_points(points, *, hide_zero_rebate=False):
    if not hide_zero_rebate:
        return list(points or [])
    return [
        (rebate, weight)
        for rebate, weight in (points or [])
        if int(rebate) != 0
    ]


def format_zero_rebate_share_text(points):
    """Format the final rebate=0 weight share shown beside the chart."""
    normalized_points = normalize_weight_curve_points(
        {'rebate_min': rebate, 'weight': weight}
        for rebate, weight in (points or [])
    )
    if not normalized_points:
        return "rebate=0 占比（不中奖率）：--"

    weights_by_rebate = dict(normalized_points)
    if 0 not in weights_by_rebate:
        return "rebate=0 占比（不中奖率）：无 rebate=0"

    zero_weight = weights_by_rebate[0]
    total_weight = sum(weights_by_rebate.values())
    if total_weight <= 0:
        return "rebate=0 占比（不中奖率）：--（总权重为0）"

    share = zero_weight / total_weight * 100
    return (
        f"rebate=0 占比（不中奖率）：{share:.4f}%"
        f"（0权重={zero_weight}，总权重={total_weight}）"
    )


def calculate_rebate_range_shares(points):
    """Return final weight shares grouped by the configured rebate ranges."""
    normalized_points = normalize_weight_curve_points(
        {'rebate_min': rebate, 'weight': weight}
        for rebate, weight in (points or [])
    )
    total_weight = sum(weight for _rebate, weight in normalized_points)
    results = []
    for label, lower, upper in REBATE_RANGE_BUCKETS:
        bucket_weight = sum(
            weight
            for rebate, weight in normalized_points
            if rebate >= lower and (upper is None or rebate < upper)
        )
        results.append({
            'label': label,
            'weight': bucket_weight,
            'ratio': bucket_weight / total_weight if total_weight > 0 else None,
        })
    return results


def format_rebate_range_share(ratio):
    if ratio is None:
        return "--"
    if ratio <= 0:
        return "0%"
    percent = ratio * 100
    if percent < 0.000001:
        return f"{percent:.3e}%"
    return f"{percent:.8f}".rstrip('0').rstrip('.') + "%"


def format_chart_axis_value(value):
    value = int(round(float(value)))
    if abs(value) >= 10000 and value % 10000 == 0:
        return f"{value // 10000}万"
    return str(value)


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
        self.group_suffix_var = None
        self.group_suffixes = []
        self.rtp_info_var = None
        self.special_target_rtp_var = None
        self.ex_target_rtp_vars = {}
        self.zero_rebate_inference_vars = {}
        self.independent_rtp_vars = {}
        self.special_target_entry = None
        self.ex_target_entries = {}
        self.special_has_zero_for_config = False
        self._updating_zero_rebate_state = False
        self.weight_chart_canvases = {}
        self.weight_chart_points = {}
        self.zero_rebate_share_vars = {}
        self.rebate_range_share_vars = {}
        self.hide_zero_rebate_chart_var = None
        self.base_rules = {}
        self.default_base_rules = {}
        self.group_rules_by_suffix = {}
        self.default_group_rules_by_suffix = {}
        self.extra_buy_rules_by_mode = {}
        self.current_rule_group_suffix = None
        self._loading_group_rules = False

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
        self.initialize_independent_rtp_vars()
        self.initialize_group_rule_state()

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
        self.current_rule_group_suffix = self.get_selected_group_suffix()
        self.group_suffixes = self.get_available_group_suffixes()
        self.group_suffix_var = tk.IntVar(value=self.current_rule_group_suffix)
        ttk.Label(rtp_frame, text="权重分组").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(8, 0))
        suffix_frame = ttk.Frame(rtp_frame)
        suffix_frame.grid(row=1, column=1, sticky="w", pady=(8, 0))
        for col, suffix in enumerate(self.group_suffixes):
            ttk.Radiobutton(
                suffix_frame,
                text=f"分组{suffix}",
                variable=self.group_suffix_var,
                value=suffix,
                command=self.on_group_suffix_changed,
            ).grid(row=0, column=col, sticky="w", padx=(0, 10))
        ttk.Label(rtp_frame, textvariable=self.rtp_info_var, wraplength=760, justify="left").grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0)
        )

        current_group_combo.bind("<<ComboboxSelected>>", self.on_current_group_changed)
        self.special_target_rtp_var.trace_add("write", lambda *_args: self.update_rtp_info())
        for var in self.ex_target_rtp_vars.values():
            var.trace_add("write", lambda *_args: self.update_rtp_info())

    def initialize_group_rule_state(self):
        self.base_rules = clone_mode_rules_map(getattr(self.deps, 'rules', {}))
        self.default_base_rules = clone_mode_rules_map(getattr(self.deps, 'default_rules', {}))
        self.group_rules_by_suffix = clone_group_rules_map(getattr(self.deps, 'group_rules', {}))
        self.default_group_rules_by_suffix = clone_group_rules_map(
            getattr(self.deps, 'default_group_rules', {})
        )
        self.extra_buy_rules_by_mode = {}
        for group in getattr(self.deps, 'extra_buy_groups', []):
            mode = self.deps.make_extra_buy_mode(group['game_type'])
            legacy_rules = [
                dict(rule)
                for rule in group.get(
                    'rules',
                    self.base_rules.get(self.deps.buy_group_mode, []),
                )
            ]
            rules_by_suffix = {
                str(group_suffix): [dict(rule) for rule in group_rules]
                for group_suffix, group_rules in (group.get('group_rules') or {}).items()
                if isinstance(group_rules, list)
            }
            for group_suffix in self.get_available_group_suffixes():
                rules_by_suffix.setdefault(
                    str(group_suffix),
                    [dict(rule) for rule in legacy_rules],
                )
            self.extra_buy_rules_by_mode[mode] = rules_by_suffix

    def get_selected_group_id(self):
        text = self.current_group_var.get() if self.current_group_var is not None else ""
        return int(text.split(" ", 1)[0])

    def get_selected_group_suffix(self):
        return self.get_selected_group_id() % 10

    def get_available_group_suffixes(self):
        suffixes = sorted({
            int(group_id) % 10
            for group_id in getattr(self.deps, 'weight_group_ids', ())
        })
        if not suffixes:
            suffixes = sorted({
                int(group_suffix)
                for group_suffix in getattr(self, 'group_suffixes', ())
            })
        return suffixes or [0]

    def find_group_id_for_suffix(self, group_suffix, preferred_group_id=None):
        group_suffix = int(group_suffix)
        candidates = [
            int(group_id)
            for group_id in self.deps.weight_group_ids
            if int(group_id) % 10 == group_suffix
        ]
        if not candidates:
            return None
        preferred_ids = []
        if preferred_group_id is not None:
            try:
                preferred_ids.append(int(preferred_group_id))
            except (TypeError, ValueError):
                pass
        preferred_ids.append(DEFAULT_RTP_GROUP_ID)
        for preferred_id in preferred_ids:
            preferred_prefix = preferred_id // 10
            for group_id in candidates:
                if group_id // 10 == preferred_prefix:
                    return group_id
        return candidates[0]

    def set_group_suffix_var(self, group_suffix):
        var = getattr(self, 'group_suffix_var', None)
        if var is not None:
            var.set(int(group_suffix))

    def get_group_rules_for_suffix(self, group_suffix):
        return self.group_rules_by_suffix.setdefault(str(group_suffix), {})

    def get_rules_for_mode_group(self, mode, group_suffix):
        mode = str(mode)
        is_extra_buy_mode = getattr(self.deps, 'is_extra_buy_mode', lambda _mode: False)
        if is_extra_buy_mode(mode):
            rules_by_suffix = getattr(self, 'extra_buy_rules_by_mode', {}).get(mode, {})
            suffix_key = str(group_suffix)
            if suffix_key in rules_by_suffix:
                return rules_by_suffix[suffix_key]
            if '0' in rules_by_suffix:
                return rules_by_suffix['0']
            return self.get_default_rules_for_mode(mode)
        group_rules = getattr(self, 'group_rules_by_suffix', {}).get(str(group_suffix), {})
        if mode in group_rules:
            return group_rules.get(mode, [])
        group_zero_rules = getattr(self, 'group_rules_by_suffix', {}).get('0', {})
        if mode in group_zero_rules:
            return group_zero_rules.get(mode, [])
        return getattr(self, 'base_rules', getattr(self.deps, 'rules', {})).get(mode, [])

    def save_visible_rules_for_group(self, group_suffix, *, show_error=False):
        if self.rule_editor is None:
            return True
        try:
            suffix_rules = clone_mode_rules_map(self.group_rules_by_suffix.get(str(group_suffix), {}))
            for mode in self.displayed_modes:
                parsed = self.parse_group_weight_rule_rows(
                    mode,
                    self.rule_editor.get_rows(mode),
                )
                if self.deps.is_extra_buy_mode(mode):
                    self.extra_buy_rules_by_mode.setdefault(mode, {})[str(group_suffix)] = parsed
                elif mode in self.deps.group_weight_modes:
                    suffix_rules[mode] = parsed
            self.group_rules_by_suffix[str(group_suffix)] = suffix_rules
            return True
        except ValueError as e:
            if show_error:
                messagebox.showerror("group_weight 权重配置错误", str(e), parent=self.dialog)
            return False

    def load_rules_for_group(self, group_suffix):
        if self.rule_editor is None:
            return
        self._loading_group_rules = True
        try:
            modes = getattr(
                self,
                'displayed_modes',
                list(getattr(self.rule_editor, 'mode_rows', {})),
            )
            for mode in modes:
                self.rule_editor.clear_rule_rows(mode)
                for rule in self.get_initial_rules_for_mode(mode, group_suffix):
                    self.rule_editor.add_rule_row(mode, rule)
            self.apply_zero_rebate_entry_states()
            self.refresh_zero_rebate_option_states()
        finally:
            self._loading_group_rules = False

    def switch_rule_group_suffix(self, new_suffix, *, preferred_group_id=None, current_group_already_set=False):
        previous_suffix = getattr(self, 'current_rule_group_suffix', None)
        new_suffix = int(new_suffix)
        if previous_suffix == new_suffix:
            self.set_group_suffix_var(new_suffix)
            self.update_rtp_info()
            return True
        if previous_suffix is not None:
            if not self.save_visible_rules_for_group(previous_suffix, show_error=True):
                restore_group_id = self.find_group_id_for_suffix(previous_suffix, preferred_group_id)
                if restore_group_id is not None:
                    self.current_group_var.set(self.deps.format_group_rtp_option(restore_group_id))
                self.set_group_suffix_var(previous_suffix)
                return False
        if not current_group_already_set:
            group_id = self.find_group_id_for_suffix(new_suffix, preferred_group_id)
            if group_id is not None:
                self.current_group_var.set(self.deps.format_group_rtp_option(group_id))
        self.current_rule_group_suffix = new_suffix
        self.set_group_suffix_var(new_suffix)
        self.load_rules_for_group(new_suffix)
        self.update_rtp_info()
        return True

    def on_current_group_changed(self, _event=None):
        try:
            group_id = self.get_selected_group_id()
        except (ValueError, IndexError):
            self.update_rtp_info()
            return
        self.switch_rule_group_suffix(
            group_id % 10,
            preferred_group_id=group_id,
            current_group_already_set=True,
        )

    def on_group_suffix_changed(self):
        try:
            new_suffix = int(self.group_suffix_var.get())
        except (TypeError, ValueError):
            self.update_rtp_info()
            return
        try:
            preferred_group_id = self.get_selected_group_id()
        except (ValueError, IndexError):
            preferred_group_id = DEFAULT_RTP_GROUP_ID
        self.switch_rule_group_suffix(
            new_suffix,
            preferred_group_id=preferred_group_id,
            current_group_already_set=False,
        )

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

    def initialize_independent_rtp_vars(self):
        if hasattr(self.deps, 'independent_rtp_modes'):
            enabled_modes = {str(mode) for mode in (self.deps.independent_rtp_modes or set())}
        else:
            enabled_modes = {str(mode) for mode in getattr(self.deps, 'default_independent_rtp_modes', ())}
        supports = getattr(self.deps, 'supports_independent_rtp', lambda _mode: False)
        self.independent_rtp_vars = {
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
                self.get_initial_rules_for_mode(mode, self.current_rule_group_suffix),
                add_button_text=f"新增{mode_name}区间",
                options_builder=self.build_mode_options,
                side_panel_builder=self.build_weight_chart_panel,
            )
        self.apply_zero_rebate_entry_states()
        self.refresh_zero_rebate_option_states()

    def build_weight_chart_panel(self, mode, parent):
        if self.hide_zero_rebate_chart_var is None:
            self.hide_zero_rebate_chart_var = tk.BooleanVar(master=self.dialog, value=True)

        chart_frame = ttk.Frame(parent)
        chart_frame.grid(row=0, column=0, sticky="nsew")
        chart_frame.rowconfigure(1, weight=1)
        chart_frame.columnconfigure(0, weight=1)
        chart_frame.columnconfigure(1, weight=0)

        header = ttk.Frame(chart_frame)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="权重柱状图", foreground="#444444").grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(
            header,
            text="不显示rebate=0",
            variable=self.hide_zero_rebate_chart_var,
            command=self.redraw_all_weight_charts,
        ).grid(row=0, column=1, sticky="e", padx=(10, 12))
        ttk.Label(header, text="X: rebate    Y: 权重", foreground="#777777").grid(row=0, column=2, sticky="e")
        share_var = tk.StringVar(master=self.dialog, value=format_zero_rebate_share_text([]))
        self.zero_rebate_share_vars[mode] = share_var
        ttk.Label(
            header,
            textvariable=share_var,
            foreground="#555555",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))

        canvas = tk.Canvas(
            chart_frame,
            background="#ffffff",
            highlightthickness=1,
            highlightbackground="#d0d0d0",
        )
        canvas.grid(row=1, column=0, sticky="nsew")
        self.weight_chart_canvases[mode] = canvas
        canvas.bind("<Configure>", lambda _event, m=mode: self.redraw_weight_chart(m))

        range_frame = ttk.LabelFrame(
            chart_frame,
            text="rebate\u533a\u95f4\u5360\u6bd4",
            padding=(8, 6),
        )
        range_frame.grid(row=1, column=1, sticky="ns", padx=(8, 0))
        range_frame.columnconfigure(0, minsize=86)
        range_frame.columnconfigure(1, minsize=92)
        ttk.Label(range_frame, text="\u533a\u95f4", foreground="#555555").grid(
            row=0,
            column=0,
            sticky="w",
            pady=(0, 4),
        )
        ttk.Label(range_frame, text="\u6743\u91cd\u5360\u6bd4", foreground="#555555").grid(
            row=0,
            column=1,
            sticky="e",
            pady=(0, 4),
        )
        share_vars = []
        for row, (label, _lower, _upper) in enumerate(REBATE_RANGE_BUCKETS, start=1):
            ttk.Label(range_frame, text=label).grid(
                row=row,
                column=0,
                sticky="w",
                pady=2,
            )
            share_var = tk.StringVar(master=self.dialog, value="--")
            ttk.Label(range_frame, textvariable=share_var).grid(
                row=row,
                column=1,
                sticky="e",
                pady=2,
            )
            share_vars.append(share_var)
        self.rebate_range_share_vars[mode] = share_vars
        return True

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

    def mode_independent_rtp_enabled(self, mode):
        var = getattr(self, 'independent_rtp_vars', {}).get(str(mode))
        return bool(var is not None and var.get())

    def collect_independent_rtp_modes(self):
        return {
            str(mode)
            for mode, var in getattr(self, 'independent_rtp_vars', {}).items()
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

    def on_independent_rtp_changed(self, mode):
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

    def build_independent_rtp_option(self, mode, options_frame, row=0):
        var = getattr(self, 'independent_rtp_vars', {}).get(str(mode))
        if var is None:
            return row
        ttk.Checkbutton(
            options_frame,
            text="独立计算RTP",
            variable=var,
            command=lambda m=mode: self.on_independent_rtp_changed(m),
        ).grid(row=row, column=0, sticky="w", padx=(0, 8))
        note_text = "开启后不扣除其它局触发贡献，RTP目标=当前RTP组"
        if str(mode) == "6":
            note_text += "，反推目标按 ex倍数折算"
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
            text=group_weight_ui_text.SAVE_BUTTON_TEXT,
            command=self.save_config,
        ).grid(row=0, column=2, sticky="e", padx=(0, 8))
        ttk.Button(
            button_frame,
            text=group_weight_ui_text.CONFIRM_BUTTON_TEXT,
            command=self.confirm_and_run,
        ).grid(row=0, column=3, sticky="e", padx=(0, 8))
        ttk.Button(
            button_frame,
            text=group_weight_ui_text.CANCEL_BUTTON_TEXT,
            command=self.dialog.destroy,
        ).grid(row=0, column=4, sticky="e")

    def get_initial_rules_for_mode(self, mode, group_suffix=None):
        if group_suffix is None:
            group_suffix = getattr(self, 'current_rule_group_suffix', None)
        return [
            dict(rule)
            for rule in self.get_rules_for_mode_group(mode, group_suffix)
        ]

    def get_default_rules_for_mode(self, mode):
        is_extra_buy_mode = getattr(self.deps, 'is_extra_buy_mode', lambda _mode: False)
        if is_extra_buy_mode(mode):
            return getattr(self, 'default_base_rules', self.deps.default_rules).get(
                self.deps.buy_group_mode,
                [],
            )
        return getattr(self, 'default_base_rules', self.deps.default_rules).get(mode, [])

    def get_default_rules_for_mode_group(self, mode, group_suffix):
        mode = str(mode)
        suffix_key = str(group_suffix)
        default_group_rules = getattr(self, 'default_group_rules_by_suffix', {})
        if suffix_key in default_group_rules and mode in default_group_rules[suffix_key]:
            return [dict(rule) for rule in default_group_rules[suffix_key][mode]]
        if '0' in default_group_rules and mode in default_group_rules['0']:
            return [dict(rule) for rule in default_group_rules['0'][mode]]
        return [dict(rule) for rule in self.get_default_rules_for_mode(mode)]

    def reset_group_weight_rules_to_defaults(self):
        current_suffix = getattr(self, 'current_rule_group_suffix', None)
        if current_suffix is None:
            try:
                current_suffix = int(self.group_suffix_var.get())
            except (AttributeError, TypeError, ValueError):
                current_suffix = self.get_selected_group_suffix()
        if not messagebox.askyesno(
            "恢复默认权重规则",
            f"仅将当前权重分组{current_suffix}的规则恢复为默认值，其他分组和全局设置不变。"
            "点击“确认并开始”后生效。是否继续？",
            parent=self.dialog,
        ):
            return
        suffix_key = str(current_suffix)
        suffix_rules = clone_mode_rules_map(self.group_rules_by_suffix.get(suffix_key, {}))
        for mode in getattr(self.rule_editor, 'mode_rows', {}):
            default_rules = self.get_default_rules_for_mode_group(mode, current_suffix)
            if getattr(self.deps, 'is_extra_buy_mode', lambda _mode: False)(mode):
                self.extra_buy_rules_by_mode.setdefault(mode, {})[suffix_key] = default_rules
            elif mode in self.deps.group_weight_modes:
                suffix_rules[mode] = default_rules
        self.group_rules_by_suffix[suffix_key] = suffix_rules
        self.load_rules_for_group(current_suffix)
        self.apply_zero_rebate_entry_states()
        self.refresh_zero_rebate_option_states()
        self.update_rtp_info()

    def build_mode_options(self, mode, options_frame):
        row = self.build_zero_rebate_inference_option(mode, options_frame, row=0)
        row = self.build_independent_rtp_option(mode, options_frame, row=row)
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
        if self.rule_editor is None or mode not in getattr(self.rule_editor, 'mode_rows', {}):
            return self.get_initial_rules_for_mode(
                mode,
                getattr(self, 'current_rule_group_suffix', None),
            ), None
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

    def get_current_mode(self):
        try:
            return self.displayed_modes[self.notebook.index("current")]
        except Exception:
            return self.displayed_modes[0] if self.displayed_modes else self.deps.buy_group_mode

    def collect_weight_chart_rules(self, mode):
        rules = []
        if self.rule_editor is None:
            return rules
        for row_info in self.rule_editor.get_rows(mode):
            rebate_text = row_info.get('vars', {}).get('rebate_min')
            weight_text = row_info.get('vars', {}).get('weight')
            if rebate_text is None or weight_text is None:
                continue
            rebate_value = rebate_text.get().strip()
            weight_value = weight_text.get().strip()
            if not rebate_value:
                continue
            try:
                rebate = int(rebate_value)
                weight = 0 if self.is_missing_zero_rebate_rule_row(mode, row_info) else int(weight_value)
            except (TypeError, ValueError):
                continue
            rules.append({'rebate_min': rebate, 'weight': weight})
        return rules

    def update_current_weight_chart(self):
        self.update_weight_chart(self.get_current_mode())

    def update_weight_chart(self, mode):
        self.update_weight_chart_points(
            mode,
            normalize_weight_curve_points(self.collect_weight_chart_rules(mode)),
        )

    def update_weight_chart_points(self, mode, points):
        if not hasattr(self, 'weight_chart_points'):
            self.weight_chart_points = {}
        self.weight_chart_points[mode] = list(points or [])
        share_var = getattr(self, 'zero_rebate_share_vars', {}).get(mode)
        if share_var is not None:
            share_var.set(format_zero_rebate_share_text(self.weight_chart_points[mode]))
        range_share_vars = getattr(self, 'rebate_range_share_vars', {}).get(mode, [])
        range_shares = calculate_rebate_range_shares(self.weight_chart_points[mode])
        for range_share_var, item in zip(range_share_vars, range_shares):
            range_share_var.set(format_rebate_range_share(item['ratio']))
        self.redraw_weight_chart(mode)

    def hide_zero_rebate_in_chart(self):
        var = getattr(self, 'hide_zero_rebate_chart_var', None)
        return bool(var is not None and var.get())

    def redraw_all_weight_charts(self):
        for mode in list(getattr(self, 'weight_chart_canvases', {})):
            self.redraw_weight_chart(mode)

    def redraw_weight_chart(self, mode):
        canvas = getattr(self, 'weight_chart_canvases', {}).get(mode)
        if canvas is None or not canvas.winfo_exists():
            return
        points = filter_weight_curve_points(
            getattr(self, 'weight_chart_points', {}).get(mode, []),
            hide_zero_rebate=self.hide_zero_rebate_in_chart(),
        )
        self.draw_weight_chart(canvas, points)

    def draw_weight_chart(self, canvas, points):
        canvas.delete("all")
        width = max(1, int(canvas.winfo_width()))
        height = max(1, int(canvas.winfo_height()))
        if width < 80 or height < 80:
            return

        left = 58
        right = 18
        top = 24
        bottom = 42
        plot_width = max(1, width - left - right)
        plot_height = max(1, height - top - bottom)
        x0 = left
        y0 = top + plot_height
        x1 = left + plot_width
        y1 = top

        axis_color = "#333333"
        grid_color = "#e5e5e5"
        text_color = "#666666"
        bar_color = "#d62728"

        if not points:
            canvas.create_text(
                width // 2,
                height // 2,
                text="无有效权重数据",
                fill=text_color,
            )
            return

        rebates = [point[0] for point in points]
        weights = [point[1] for point in points]
        min_rebate = min(rebates)
        max_rebate = max(rebates)
        max_weight = max(max(weights), 1)
        if min_rebate == max_rebate:
            max_rebate = min_rebate + 1

        for tick in range(5):
            ratio = tick / 4
            y = y0 - ratio * plot_height
            value = max_weight * ratio
            canvas.create_line(x0, y, x1, y, fill=grid_color)
            canvas.create_text(
                x0 - 8,
                y,
                text=format_chart_axis_value(value),
                fill=text_color,
                anchor="e",
                font=("TkDefaultFont", 8),
            )

        for tick in range(5):
            ratio = tick / 4
            x = x0 + ratio * plot_width
            value = min_rebate + (max_rebate - min_rebate) * ratio
            canvas.create_line(x, y0, x, y1, fill=grid_color)
            canvas.create_text(
                x,
                y0 + 16,
                text=format_chart_axis_value(value),
                fill=text_color,
                anchor="n",
                font=("TkDefaultFont", 8),
            )

        canvas.create_line(x0, y0, x1, y0, fill=axis_color, width=2)
        canvas.create_line(x0, y0, x0, y1, fill=axis_color, width=2)
        canvas.create_text(x1, y0 + 30, text="rebate", fill=text_color, anchor="e", font=("TkDefaultFont", 8))
        canvas.create_text(x0 - 4, y1 - 8, text="权重", fill=text_color, anchor="e", font=("TkDefaultFont", 8))

        if len(points) == 1:
            bar_width = min(24, max(6, plot_width * 0.04))
        else:
            bar_width = max(1, min(16, plot_width / max(len(points), 1) * 0.7))

        for rebate, weight in points:
            x = x0 + ((rebate - min_rebate) / (max_rebate - min_rebate)) * plot_width
            y = y0 - (weight / max_weight) * plot_height
            half_width = bar_width / 2
            canvas.create_rectangle(
                x - half_width,
                y,
                x + half_width,
                y0,
                fill=bar_color,
                outline=bar_color,
            )

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
        if getattr(self, '_loading_group_rules', False):
            return
        if getattr(self, '_updating_zero_rebate_state', False):
            return
        self.apply_zero_rebate_entry_states()
        self.refresh_zero_rebate_option_states()
        text = self.current_group_var.get()
        try:
            group_id = int(text.split(" ", 1)[0])
        except (ValueError, IndexError):
            self.rtp_info_var.set(group_weight_ui_text.DEFAULT_PREVIEW_TEXT)
            self.update_weight_chart_points(self.get_current_mode(), [])
            return
        current_mode = self.get_current_mode()
        selected_suffix = group_id % 10

        rules_by_mode = {}
        parse_errors = {}
        for mode in self.dialog_modes:
            rules_by_mode[mode], parse_errors[mode] = self.parse_dialog_rules(mode)
            if mode not in getattr(self.rule_editor, 'mode_rows', {}) and parse_errors[mode] is None:
                rules_by_mode[mode] = self.get_initial_rules_for_mode(mode, selected_suffix)
        ex_target_rtps, ex_target_errors = self.parse_ex_target_rtps_for_preview()
        parse_errors.update(ex_target_errors)

        special_target, special_target_error = (
            self.parse_special_target_for_preview() if self.mode_zero_rebate_inference_enabled('2') else (None, None)
        )
        preview_kwargs = dict(
            special_has_zero_for_config=self.special_has_zero_for_config,
            special_target_rtp=special_target,
            special_target_error=special_target_error,
            buy_multiplier=self.deps.buy_multiplier,
            ex_multiplier=self.deps.ex_multiplier,
            ex_target_rtps=ex_target_rtps,
            zero_rebate_inference_modes=self.collect_zero_rebate_inference_modes(),
            independent_rtp_modes=self.collect_independent_rtp_modes(),
            buy_enabled=self.deps.buy_enabled or self.deps.has_extra_buy_groups(),
        )
        chart_points = []
        try:
            current_rtp_text = self.deps.build_preview_text(
                current_mode,
                group_id,
                rules_by_mode,
                parse_errors,
                self.preview_rebates,
                self.preview_status,
                self.formation_exists,
                **preview_kwargs,
            )
        except ValueError as e:
            current_rtp_text = str(e)
        except Exception as e:
            print(f"[WARN] group_weight preview failed: {e}")
            current_rtp_text = f"\u9884\u89c8\u751f\u6210\u5931\u8d25\uff1a{e}"
        else:
            if hasattr(self.deps, 'build_preview_points'):
                try:
                    chart_points = self.deps.build_preview_points(
                        current_mode,
                        group_id,
                        rules_by_mode,
                        parse_errors,
                        self.preview_rebates,
                        self.preview_status,
                        self.formation_exists,
                        **preview_kwargs,
                    )
                except Exception as e:
                    print(f"[WARN] group_weight chart preview failed: {e}")
                    chart_points = []
            else:
                chart_points = normalize_weight_curve_points(self.collect_weight_chart_rules(current_mode))

        self.rtp_info_var.set(
            group_weight_ui_text.build_rtp_info_text(
                self.deps,
                group_id,
                current_mode,
                current_rtp_text,
            )
        )
        self.update_weight_chart_points(current_mode, chart_points)

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
        rules = clone_mode_rules_map(self.base_rules)
        for mode in self.deps.group_weight_modes:
            if mode == self.deps.buy_group_mode and not include_buy:
                rules[mode] = self.base_rules.get(mode, [])
                continue
            rules.setdefault(mode, self.base_rules.get(mode, []))
        return self.deps.validate_rules(rules)

    def get_configured_group_weight_modes(self):
        displayed_modes = getattr(self, 'displayed_modes', None)
        if displayed_modes is None:
            displayed_modes = getattr(
                self.deps,
                'group_weight_modes',
                tuple(getattr(self, 'base_rules', {})),
            )
        supported_modes = {
            str(mode)
            for mode in getattr(self.deps, 'group_weight_modes', displayed_modes)
        }
        return [
            str(mode)
            for mode in displayed_modes
            if str(mode) in supported_modes
        ]

    def filter_group_weight_rules_for_save(self, rules):
        if (
            getattr(self, 'displayed_modes', None) is None
            and not hasattr(self.deps, 'group_weight_modes')
        ):
            configured_modes = {str(mode) for mode in (rules or {})}
        else:
            configured_modes = set(self.get_configured_group_weight_modes())
        return {
            str(mode): [dict(rule) for rule in mode_rules]
            for mode, mode_rules in (rules or {}).items()
            if str(mode) in configured_modes
        }

    def collect_group_weight_group_rules(self):
        group_rules = clone_group_rules_map(self.group_rules_by_suffix)
        group_zero_rules = clone_mode_rules_map(
            group_rules.get('0', getattr(self, 'base_rules', {}))
        )
        configured_suffixes = {
            str(group_suffix) for group_suffix in self.get_available_group_suffixes()
        }
        configured_modes = set(self.get_configured_group_weight_modes())
        for group_suffix in sorted(configured_suffixes, key=int):
            suffix_key = str(group_suffix)
            materialized_rules = clone_mode_rules_map(group_zero_rules)
            materialized_rules.update(
                clone_mode_rules_map(group_rules.get(suffix_key, {}))
            )
            group_rules[suffix_key] = materialized_rules
        return {
            str(group_suffix): {
                mode: [dict(rule) for rule in mode_rules]
                for mode, mode_rules in rules_by_mode.items()
                if mode in configured_modes
            }
            for group_suffix, rules_by_mode in group_rules.items()
            if (
                str(group_suffix) in configured_suffixes
                and any(mode in configured_modes for mode in rules_by_mode)
            )
        }

    def collect_extra_buy_groups_with_rules(self):
        groups = []
        active_suffixes = {
            str(group_suffix) for group_suffix in self.get_available_group_suffixes()
        }
        for group in self.deps.extra_buy_groups:
            mode = self.deps.make_extra_buy_mode(group['game_type'])
            updated = dict(group)
            rules_by_suffix = {
                str(group_suffix): [dict(rule) for rule in group_rules]
                for group_suffix, group_rules in self.extra_buy_rules_by_mode.get(mode, {}).items()
                if str(group_suffix) in active_suffixes
            }
            if rules_by_suffix:
                updated['group_rules'] = rules_by_suffix
                updated['rules'] = [
                    dict(rule)
                    for rule in rules_by_suffix.get(
                        '0',
                        group.get('rules', self.get_default_rules_for_mode(mode)),
                    )
                ]
            groups.append(updated)
        return self.deps.normalize_extra_buy_groups(groups)

    def apply_and_save_config(self):
        try:
            if self.current_rule_group_suffix is not None:
                if not self.save_visible_rules_for_group(
                    self.current_rule_group_suffix,
                    show_error=True,
                ):
                    return False
            rules = self.collect_group_weight_rules(
                self.deps.buy_enabled or self.deps.has_extra_buy_groups()
            )
            rules_for_save = self.filter_group_weight_rules_for_save(rules)
            group_rules = self.collect_group_weight_group_rules()
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
            return False

        self.deps.apply_rules(rules)
        self.deps.apply_group_rules(group_rules)
        self.group_rules_by_suffix = clone_group_rules_map(group_rules)
        self.deps.apply_ex_group_target_rtps(ex_target_rtps)
        self.deps.apply_zero_rebate_inference_modes(self.collect_zero_rebate_inference_modes())
        self.deps.apply_independent_rtp_modes(self.collect_independent_rtp_modes())
        self.deps.apply_extra_buy_groups(extra_buy_groups)
        save_settings = getattr(self.app, 'save_app_settings', None)
        if save_settings is not None and save_settings(
            silent=True,
            group_weight_rules_override=rules_for_save,
            group_weight_group_rules_override=group_rules,
        ) is False:
            return False
        return True

    def save_config(self):
        if not self.apply_and_save_config():
            return
        saved_suffixes = sorted(
            getattr(self, 'group_rules_by_suffix', {}),
            key=int,
        )
        saved_group_text = ', '.join(saved_suffixes) if saved_suffixes else '无'
        messagebox.showinfo(
            "保存配置",
            "group_weight 配置已保存到当前游戏的配置 JSON。\n"
            f"已保存分组：{saved_group_text}",
            parent=self.dialog,
        )

    def confirm_and_run(self):
        if not self.apply_and_save_config():
            return
        self.dialog.destroy()
        self.app.run_task(
            "生成group_weight",
            self.deps.generate_config,
            preflight={"kind": "group_weight"},
        )
