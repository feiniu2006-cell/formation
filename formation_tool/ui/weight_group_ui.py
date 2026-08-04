"""Extra group_weight group UI helpers for the main SlotProcessApp window."""

import tkinter as tk
from tkinter import ttk

from formation_tool.ui import ui_text


def format_ui_text(value):
    return "" if value is None else str(value)


def refresh_extra_weight_group_rows(app):
    for row_idx, row_info in enumerate(app.extra_weight_group_rows, start=2):
        grid_row = row_idx
        row_info['group_suffix_entry'].grid(row=grid_row, column=0, sticky="ew", padx=(0, 6), pady=1)
        row_info['special_weight_entry'].grid(row=grid_row, column=1, sticky="ew", padx=(0, 6), pady=1)
        row_info['free_weight_entry'].grid(row=grid_row, column=2, sticky="ew", padx=(0, 6), pady=1)
        row_info['remove_button'].grid(row=grid_row, column=3, sticky="ew", pady=1)


def add_extra_weight_group_row(app, group_suffix="", special_weight="", free_weight=""):
    if app.extra_weight_group_rows_frame is None:
        return
    if special_weight == "":
        special_weight = app.special_weight_1_var.get()
    if free_weight == "":
        free_weight = app.free_weight_1_var.get()
    row_info = {
        'group_suffix_var': tk.StringVar(value=format_ui_text(group_suffix)),
        'special_weight_var': tk.StringVar(value=format_ui_text(special_weight)),
        'free_weight_var': tk.StringVar(value=format_ui_text(free_weight)),
        'widgets': [],
    }
    group_suffix_entry = ttk.Entry(
        app.extra_weight_group_rows_frame,
        textvariable=row_info['group_suffix_var'],
        width=12,
    )
    special_weight_entry = ttk.Entry(
        app.extra_weight_group_rows_frame,
        textvariable=row_info['special_weight_var'],
        width=12,
    )
    free_weight_entry = ttk.Entry(
        app.extra_weight_group_rows_frame,
        textvariable=row_info['free_weight_var'],
        width=12,
    )
    remove_button = ttk.Button(
        app.extra_weight_group_rows_frame,
        text=ui_text.DELETE_BUTTON_TEXT,
        command=lambda info=row_info: app.remove_extra_weight_group_row(info),
    )
    row_info.update({
        'group_suffix_entry': group_suffix_entry,
        'special_weight_entry': special_weight_entry,
        'free_weight_entry': free_weight_entry,
        'remove_button': remove_button,
        'widgets': [
            group_suffix_entry,
            special_weight_entry,
            free_weight_entry,
            remove_button,
        ],
    })
    app.extra_weight_group_rows.append(row_info)
    for widget in row_info['widgets']:
        app.config_widgets.append((widget, "normal"))
    app.refresh_extra_weight_group_rows()


def remove_extra_weight_group_row(app, row_info):
    if row_info in app.extra_weight_group_rows:
        app.extra_weight_group_rows.remove(row_info)
    for widget in row_info.get('widgets', []):
        widget.destroy()
    app.refresh_extra_weight_group_rows()


def clear_extra_weight_group_rows(app):
    for row_info in list(app.extra_weight_group_rows):
        for widget in row_info.get('widgets', []):
            widget.destroy()
    app.extra_weight_group_rows.clear()


def set_extra_weight_group_rows(app, groups):
    app.clear_extra_weight_group_rows()
    for group in groups or []:
        app.add_extra_weight_group_row(
            group.get('group_suffix', group.get('group_id', '')),
            group.get('special_weight', ''),
            group.get('free_weight', ''),
        )


def collect_extra_weight_groups(app):
    groups = []
    for row_idx, row_info in enumerate(app.extra_weight_group_rows, start=1):
        group_suffix_text = row_info['group_suffix_var'].get().strip()
        special_weight_text = row_info['special_weight_var'].get().strip()
        free_weight_text = row_info['free_weight_var'].get().strip()
        if not group_suffix_text and not special_weight_text and not free_weight_text:
            continue
        if not group_suffix_text or not special_weight_text or not free_weight_text:
            raise ValueError(f"额外权重分组第 {row_idx} 行分组尾号、特殊权重、免费权重都必须填写")
        groups.append({
            'group_suffix': group_suffix_text,
            'special_weight': special_weight_text,
            'free_weight': free_weight_text,
        })
    return app.settings_deps.normalize_extra_weight_groups(groups)


def build_extra_weight_group_section(app, weight_frame):
    header = ttk.Frame(weight_frame)
    header.grid(row=0, column=0, columnspan=4, sticky="ew", pady=(0, 2))
    header.columnconfigure(0, weight=1)
    ttk.Label(header, text="权重分组").grid(row=0, column=0, sticky="w")
    app.add_extra_weight_group_button = ttk.Button(
        header,
        text="新增权重分组",
        command=lambda: app.add_extra_weight_group_row(),
    )
    app.add_extra_weight_group_button.grid(row=0, column=1, sticky="e")
    app.config_widgets.append((app.add_extra_weight_group_button, "normal"))

    app.extra_weight_group_rows_frame = ttk.Frame(weight_frame)
    app.extra_weight_group_rows_frame.grid(row=1, column=0, columnspan=4, sticky="ew")
    for col in range(3):
        app.extra_weight_group_rows_frame.columnconfigure(col, weight=1)
    app.extra_weight_group_rows_frame.columnconfigure(3, minsize=88)

    headers = ("分组尾号", "特殊权重", "免费权重", "操作")
    for col, text in enumerate(headers):
        ttk.Label(app.extra_weight_group_rows_frame, text=text).grid(
            row=0,
            column=col,
            sticky="w",
            padx=(0, 6) if col < 3 else 0,
            pady=(0, 1),
        )

    app.fixed_weight_group_suffix_var = tk.StringVar(value="0")
    fixed_suffix_entry = ttk.Entry(
        app.extra_weight_group_rows_frame,
        textvariable=app.fixed_weight_group_suffix_var,
        width=12,
        state="readonly",
    )
    fixed_special_entry = ttk.Entry(
        app.extra_weight_group_rows_frame,
        textvariable=app.special_weight_0_var,
        width=12,
    )
    fixed_free_entry = ttk.Entry(
        app.extra_weight_group_rows_frame,
        textvariable=app.free_weight_0_var,
        width=12,
    )
    fixed_remove_button = ttk.Button(
        app.extra_weight_group_rows_frame,
        text=ui_text.DELETE_BUTTON_TEXT,
        state="disabled",
    )
    fixed_suffix_entry.grid(row=1, column=0, sticky="ew", padx=(0, 6), pady=1)
    fixed_special_entry.grid(row=1, column=1, sticky="ew", padx=(0, 6), pady=1)
    fixed_free_entry.grid(row=1, column=2, sticky="ew", padx=(0, 6), pady=1)
    fixed_remove_button.grid(row=1, column=3, sticky="ew", pady=1)
    app.config_widgets.extend([
        (fixed_suffix_entry, "readonly"),
        (fixed_special_entry, "normal"),
        (fixed_free_entry, "normal"),
        (fixed_remove_button, "disabled"),
    ])
