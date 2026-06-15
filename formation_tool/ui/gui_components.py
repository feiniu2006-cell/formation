"""Reusable Tkinter components for the formation tool."""

import tkinter as tk
from tkinter import ttk

from formation_tool.ui import ui_layout_defaults


class RuleTableEditor:
    """Notebook 中可增删行的规则表编辑器。"""

    def __init__(
        self,
        notebook,
        fields,
        field_labels,
        *,
        row_width=13,
        action_width=8,
        x_scroll=False,
        on_change=None,
    ):
        self.notebook = notebook
        self.fields = tuple(fields)
        self.field_labels = field_labels
        self.row_width = row_width
        self.action_width = action_width
        self.x_scroll = bool(x_scroll)
        self.on_change = on_change
        self.mode_rows = {}
        self.mode_bodies = {}

    def _emit_change(self):
        if self.on_change:
            self.on_change()

    def refresh_rule_rows(self, mode):
        for row_idx, row_info in enumerate(self.mode_rows[mode], start=1):
            row_info['frame'].grid(row=row_idx, column=0, sticky="ew", pady=2)
            row_info['number_label'].configure(text=str(row_idx))

    def remove_rule_row(self, mode, row_info):
        row_info['frame'].destroy()
        self.mode_rows[mode].remove(row_info)
        self.refresh_rule_rows(mode)
        self._emit_change()

    def clear_rule_rows(self, mode):
        for row_info in list(self.mode_rows.get(mode, [])):
            row_info['frame'].destroy()
        self.mode_rows.setdefault(mode, []).clear()
        self._emit_change()

    def add_rule_row(self, mode, rule=None):
        body = self.mode_bodies[mode]
        row_frame = ttk.Frame(body)
        row_info = {
            'frame': row_frame,
            'number_label': ttk.Label(row_frame, width=4, anchor="center"),
            'vars': {},
            'entries': {},
        }
        row_info['number_label'].grid(row=0, column=0, sticky="ew", padx=(0, 4))
        for col, field in enumerate(self.fields, start=1):
            value = '' if rule is None or field not in rule else str(rule[field])
            variable = tk.StringVar(value=value)
            entry = ttk.Entry(row_frame, textvariable=variable, width=self.row_width)
            entry.grid(row=0, column=col, sticky="ew", padx=2)
            row_info['vars'][field] = variable
            row_info['entries'][field] = entry
            row_frame.columnconfigure(col, weight=1)
            if self.on_change:
                variable.trace_add("write", lambda *_args: self._emit_change())
        ttk.Button(
            row_frame,
            text="删除",
            command=lambda m=mode, info=row_info: self.remove_rule_row(m, info),
        ).grid(row=0, column=len(self.fields) + 1, sticky="ew", padx=(6, 0))
        self.mode_rows.setdefault(mode, []).append(row_info)
        self.refresh_rule_rows(mode)
        self._emit_change()

    def add_mode_tab(self, mode, tab_text, rules, *, add_button_text, options_builder=None):
        tab = ttk.Frame(self.notebook, padding=8)
        tab.columnconfigure(0, weight=1)
        scroll_row = 0
        if options_builder:
            options_frame = ttk.Frame(tab)
            options_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
            options_frame.columnconfigure(1, weight=1)
            has_options = options_builder(mode, options_frame)
            if not has_options:
                options_frame.grid_remove()
            else:
                scroll_row = 1

        tab.rowconfigure(scroll_row, weight=1)
        canvas = tk.Canvas(tab, highlightthickness=0)
        y_scroll = ttk.Scrollbar(tab, orient="vertical", command=canvas.yview)
        body = ttk.Frame(canvas)
        self.mode_bodies[mode] = body
        self.mode_rows.setdefault(mode, [])

        canvas_window = canvas.create_window((0, 0), window=body, anchor="nw")
        canvas.configure(yscrollcommand=y_scroll.set)
        x_scroll = None
        if self.x_scroll:
            x_scroll = ttk.Scrollbar(tab, orient="horizontal", command=canvas.xview)
            canvas.configure(xscrollcommand=x_scroll.set)

        def update_scrollregion(_event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def update_body_width(event):
            canvas.itemconfigure(canvas_window, width=max(event.width, body.winfo_reqwidth()))

        body.bind("<Configure>", update_scrollregion)
        canvas.bind("<Configure>", update_body_width)

        canvas.grid(row=scroll_row, column=0, sticky="nsew")
        y_scroll.grid(row=scroll_row, column=1, sticky="ns")
        if x_scroll is not None:
            x_scroll.grid(row=scroll_row + 1, column=0, sticky="ew")
            button_row = scroll_row + 2
        else:
            button_row = scroll_row + 1

        header = ttk.Frame(body)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        ttk.Label(header, text="序号", width=4, anchor="center").grid(
            row=0, column=0, sticky="ew", padx=(0, 4)
        )
        for col, field in enumerate(self.fields, start=1):
            ttk.Label(
                header,
                text=self.field_labels[field],
                width=self.row_width,
                anchor="center",
            ).grid(row=0, column=col, sticky="ew", padx=2)
            header.columnconfigure(col, weight=1)
        ttk.Label(header, text="操作", width=self.action_width, anchor="center").grid(
            row=0, column=len(self.fields) + 1, sticky="ew", padx=(6, 0)
        )

        button_bar = ttk.Frame(tab)
        button_bar.grid(row=button_row, column=0, sticky="ew", pady=(8, 0))
        button_bar.columnconfigure(0, weight=1)
        ttk.Button(
            button_bar,
            text=add_button_text,
            command=lambda m=mode: self.add_rule_row(m),
        ).grid(row=0, column=1, sticky="e")

        for rule in rules:
            self.add_rule_row(mode, rule)

        self.notebook.add(tab, text=tab_text)

    def get_rows(self, mode):
        return self.mode_rows.get(mode, [])


class LoadingDialogBase:
    """带 loading 区域的配置弹窗基类。"""

    def __init__(self, app):
        self.app = app
        self.root = app.root
        self.dialog = None
        self.frame = None
        self.loading_progress = None

    def create_dialog(self, title, layout_or_geometry, minsize=None):
        self.dialog = tk.Toplevel(self.root)
        self.dialog.title(title)
        if isinstance(layout_or_geometry, ui_layout_defaults.WindowLayout):
            ui_layout_defaults.apply_window_layout(self.dialog, layout_or_geometry)
        else:
            self.dialog.geometry(layout_or_geometry)
            self.dialog.minsize(*minsize)
        self.dialog.transient(self.root)
        self.dialog.grab_set()

        self.frame = ttk.Frame(self.dialog, padding=12)
        self.frame.grid(row=0, column=0, sticky="nsew")
        self.dialog.columnconfigure(0, weight=1)
        self.dialog.rowconfigure(0, weight=1)
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(0, weight=1)

    def clear_frame(self):
        for child in self.frame.winfo_children():
            child.destroy()

    def stop_loading(self):
        if self.loading_progress is not None:
            self.loading_progress.stop()

    def show_loading_error(self, error):
        ttk.Label(self.frame, text=f"检测失败：{error}", foreground="#990000").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Button(self.frame, text="关闭", command=self.dialog.destroy).grid(
            row=1, column=0, sticky="e", pady=(12, 0)
        )

