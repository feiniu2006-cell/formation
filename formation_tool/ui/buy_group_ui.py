"""Buy-group UI helpers for the main SlotProcessApp window."""

import contextlib
import tkinter as tk
from tkinter import ttk

from formation_tool.ui import ui_text


def format_ui_text(value):
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return "" if value is None else str(value)


def refresh_extra_buy_group_rows(app):
    for row_idx, row_info in enumerate(app.extra_buy_rows, start=1):
        grid_row = row_idx + 1
        row_info['number_label'].configure(text=str(row_idx + 1))
        row_info['number_label'].grid(row=grid_row, column=0, sticky="ew", padx=(0, 6), pady=1)
        row_info['enabled_check'].grid(row=grid_row, column=1, sticky="w", padx=(0, 6), pady=1)
        row_info['game_type_entry'].grid(row=grid_row, column=2, sticky="ew", padx=(0, 6), pady=1)
        row_info['multiplier_entry'].grid(row=grid_row, column=3, sticky="ew", padx=(0, 6), pady=1)
        row_info['source_suffix_entry'].grid(row=grid_row, column=4, sticky="ew", padx=(0, 6), pady=1)
        row_info['remove_button'].grid(row=grid_row, column=5, sticky="ew", pady=1)


def add_extra_buy_group_row(app, game_type="", multiplier="", source_suffix="free_formation"):
    if app.extra_buy_rows_frame is None:
        return
    row_info = {
        'number_label': ttk.Label(app.extra_buy_rows_frame, width=6, anchor="center"),
        'enabled_var': tk.BooleanVar(value=True),
        'game_type_var': tk.StringVar(value=format_ui_text(game_type)),
        'multiplier_var': tk.StringVar(value=format_ui_text(multiplier)),
        'source_suffix_var': tk.StringVar(value=format_ui_text(source_suffix)),
        'widgets': [],
    }
    enabled_check = ttk.Checkbutton(app.extra_buy_rows_frame, text="", variable=row_info['enabled_var'])
    game_type_entry = ttk.Entry(app.extra_buy_rows_frame, textvariable=row_info['game_type_var'], width=12)
    multiplier_entry = ttk.Entry(app.extra_buy_rows_frame, textvariable=row_info['multiplier_var'], width=12)
    source_suffix_entry = ttk.Entry(app.extra_buy_rows_frame, textvariable=row_info['source_suffix_var'], width=18)
    remove_button = ttk.Button(
        app.extra_buy_rows_frame,
        text=ui_text.DELETE_BUTTON_TEXT,
        command=lambda info=row_info: app.remove_extra_buy_group_row(info),
    )

    row_info.update({
        'game_type_entry': game_type_entry,
        'multiplier_entry': multiplier_entry,
        'source_suffix_entry': source_suffix_entry,
        'enabled_check': enabled_check,
        'remove_button': remove_button,
        'widgets': [
            row_info['number_label'],
            enabled_check,
            game_type_entry,
            multiplier_entry,
            source_suffix_entry,
            remove_button,
        ],
    })
    app.extra_buy_rows.append(row_info)
    app.refresh_extra_buy_group_rows()


def remove_extra_buy_group_row(app, row_info):
    if row_info in app.extra_buy_rows:
        app.extra_buy_rows.remove(row_info)
    for widget in row_info.get('widgets', []):
        widget.destroy()
    app.refresh_extra_buy_group_rows()


def delete_default_buy_group(app):
    app.buy_group_enabled_var.set(False)
    app.buy_game_type_var.set(str(app.settings_deps.default_buy_group_game_type))
    app.buy_multiplier_var.set(format_ui_text(app.settings_deps.default_buy_group_multiplier))
    app.buy_source_suffix_var.set(str(app.settings_deps.default_buy_group_source_suffix))


def clear_extra_buy_group_rows(app):
    for row_info in list(app.extra_buy_rows):
        for widget in row_info.get('widgets', []):
            widget.destroy()
    app.extra_buy_rows.clear()


def set_extra_buy_group_rows(app, groups):
    app.clear_extra_buy_group_rows()
    for group in groups or []:
        app.add_extra_buy_group_row(
            group.get('game_type', ''),
            group.get('multiplier', ''),
            group.get('source_suffix', 'free_formation'),
        )


def collect_extra_buy_groups(app):
    deps = app.ui_deps
    existing_rules = {
        int(group['game_type']): group.get('rules')
        for group in deps.get_extra_buy_groups()
        if 'game_type' in group
    }
    groups = []
    for row_idx, row_info in enumerate(app.extra_buy_rows, start=1):
        game_type_text = row_info['game_type_var'].get().strip()
        multiplier_text = row_info['multiplier_var'].get().strip()
        source_suffix_text = row_info['source_suffix_var'].get().strip()
        enabled = row_info.get('enabled_var')
        if enabled is not None and not enabled.get():
            continue
        if not game_type_text and not multiplier_text:
            continue
        if not game_type_text or not multiplier_text or not source_suffix_text:
            raise ValueError(f"额外购买局第 {row_idx} 行类型、倍数和阵型后缀都必须填写")
        group = {
            'game_type': game_type_text,
            'multiplier': multiplier_text,
            'source_suffix': source_suffix_text,
        }
        with contextlib.suppress(ValueError):
            game_type = int(float(game_type_text))
            if game_type in existing_rules and existing_rules[game_type] is not None:
                group['rules'] = existing_rules[game_type]
        groups.append(group)
    return deps.normalize_extra_buy_groups(groups)


def build_purchase_section(app, weight_frame):
    purchase_frame = ttk.Frame(weight_frame)
    purchase_frame.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(6, 0))
    for col in range(4):
        purchase_frame.columnconfigure(col, weight=1)

    ex_buy_frame = ttk.Frame(purchase_frame)
    ex_buy_frame.grid(row=0, column=0, columnspan=4, sticky="ew")
    ex_buy_frame.columnconfigure(0, weight=0)
    ex_buy_frame.columnconfigure(1, weight=0)
    ex_buy_frame.columnconfigure(2, weight=1)
    ex_buy_frame.columnconfigure(3, weight=0)
    ex_buy_frame.columnconfigure(4, weight=2)
    ex_buy_frame.columnconfigure(5, weight=0)
    ex_buy_frame.columnconfigure(6, weight=1)

    ex_buy_check = ttk.Checkbutton(
        ex_buy_frame,
        text=ui_text.EX_BUY_GROUP_CHECK_TEXT,
        variable=app.ex_buy_group_enabled_var,
    )
    ex_buy_check.grid(row=0, column=0, sticky="w", padx=(0, 12))
    app.config_widgets.append((ex_buy_check, "normal"))

    ttk.Label(ex_buy_frame, text=ui_text.EX_BUY_GAME_TYPE_LABEL).grid(
        row=0, column=1, sticky="w", padx=(0, 6)
    )
    ex_buy_game_type_entry = ttk.Entry(ex_buy_frame, textvariable=app.ex_buy_game_type_var, width=10)
    ex_buy_game_type_entry.grid(row=0, column=2, sticky="ew", padx=(0, 12))
    app.config_widgets.append((ex_buy_game_type_entry, "normal"))

    ttk.Label(ex_buy_frame, text=ui_text.EX_BUY_SOURCE_SUFFIX_LABEL).grid(
        row=0, column=3, sticky="w", padx=(0, 6)
    )
    ex_buy_source_entry = ttk.Entry(ex_buy_frame, textvariable=app.ex_buy_source_suffix_var, width=18)
    ex_buy_source_entry.grid(row=0, column=4, sticky="ew", padx=(0, 12))
    app.config_widgets.append((ex_buy_source_entry, "normal"))

    ttk.Label(ex_buy_frame, text=ui_text.EX_MULTIPLIER_LABEL).grid(
        row=0, column=5, sticky="w", padx=(0, 6)
    )
    ex_multiplier_entry = ttk.Entry(ex_buy_frame, textvariable=app.ex_multiplier_var, width=10)
    ex_multiplier_entry.grid(row=0, column=6, sticky="ew")
    app.config_widgets.append((ex_multiplier_entry, "normal"))

    source_override_labels = {
        '1': '普通局(1)覆盖后缀',
        '2': '特殊局(2)覆盖后缀',
        '3': '免费局(3)覆盖后缀',
        '6': 'ex普通局(6)覆盖后缀',
        '7': 'ex特殊局(7)覆盖后缀',
        '8': 'ex免费局(8)覆盖后缀',
    }
    for row, modes in enumerate((('1', '2', '3'), ('6', '7', '8')), start=1):
        source_frame = ttk.Frame(purchase_frame)
        source_frame.grid(row=row, column=0, columnspan=4, sticky="ew", pady=(4, 0))
        for col in range(3):
            source_frame.columnconfigure(col, weight=1)
        for col, mode in enumerate(modes):
            cell = ttk.Frame(source_frame)
            cell.grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else 6, 0))
            cell.columnconfigure(0, weight=1)
            ttk.Label(cell, text=source_override_labels[mode]).grid(
                row=0,
                column=0,
                sticky="w",
                pady=(0, 1),
            )
            entry = ttk.Entry(cell, textvariable=app.ex_source_suffix_vars[mode], width=18)
            entry.grid(row=1, column=0, sticky="ew")
            app.config_widgets.append((entry, "normal"))

    buy_header = ttk.Frame(purchase_frame)
    buy_header.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(6, 2))
    buy_header.columnconfigure(0, weight=1)
    ttk.Label(buy_header, text=ui_text.PURCHASE_SECTION_TITLE).grid(row=0, column=0, sticky="w")
    app.load_buy_group_types_button = ttk.Button(
        buy_header,
        text=ui_text.LOAD_BUY_GROUP_TYPES_BUTTON,
        command=app.load_buy_group_types_from_database,
    )
    app.load_buy_group_types_button.grid(row=0, column=1, sticky="e", padx=(0, 6))
    app.config_widgets.append((app.load_buy_group_types_button, "normal"))

    app.add_extra_buy_button = ttk.Button(
        buy_header,
        text=ui_text.ADD_BUY_GROUP_BUTTON,
        command=lambda: app.add_extra_buy_group_row(
            "",
            app.buy_multiplier_var.get(),
            app.buy_source_suffix_var.get() or "free_formation",
        ),
    )
    app.add_extra_buy_button.grid(row=0, column=2, sticky="e")

    app.extra_buy_rows_frame = ttk.Frame(purchase_frame)
    app.extra_buy_rows_frame.grid(row=4, column=0, columnspan=4, sticky="ew")
    app.extra_buy_rows_frame.columnconfigure(0, minsize=52)
    app.extra_buy_rows_frame.columnconfigure(1, minsize=64)
    app.extra_buy_rows_frame.columnconfigure(2, weight=1)
    app.extra_buy_rows_frame.columnconfigure(3, weight=1)
    app.extra_buy_rows_frame.columnconfigure(4, weight=2)
    app.extra_buy_rows_frame.columnconfigure(5, minsize=88)

    for col, header in enumerate(ui_text.BUY_TABLE_HEADERS):
        ttk.Label(app.extra_buy_rows_frame, text=header).grid(
            row=0,
            column=col,
            sticky="w" if col else "ew",
            padx=(0, 6) if col < 5 else 0,
            pady=(0, 1),
        )

    ttk.Label(app.extra_buy_rows_frame, text="1", anchor="center", width=6).grid(
        row=1, column=0, sticky="ew", padx=(0, 6), pady=1
    )
    buy_check = ttk.Checkbutton(app.extra_buy_rows_frame, text="", variable=app.buy_group_enabled_var)
    buy_check.grid(row=1, column=1, sticky="w", padx=(0, 6), pady=1)
    app.config_widgets.append((buy_check, "normal"))

    buy_game_type_entry = ttk.Entry(app.extra_buy_rows_frame, textvariable=app.buy_game_type_var, width=12)
    buy_game_type_entry.grid(row=1, column=2, sticky="ew", padx=(0, 6), pady=1)
    app.config_widgets.append((buy_game_type_entry, "normal"))

    buy_multiplier_entry = ttk.Entry(app.extra_buy_rows_frame, textvariable=app.buy_multiplier_var, width=12)
    buy_multiplier_entry.grid(row=1, column=3, sticky="ew", padx=(0, 6), pady=1)
    app.config_widgets.append((buy_multiplier_entry, "normal"))

    buy_source_entry = ttk.Entry(app.extra_buy_rows_frame, textvariable=app.buy_source_suffix_var, width=18)
    buy_source_entry.grid(row=1, column=4, sticky="ew", padx=(0, 6), pady=1)
    app.config_widgets.append((buy_source_entry, "normal"))

    delete_default_button = ttk.Button(
        app.extra_buy_rows_frame,
        text=ui_text.DELETE_BUTTON_TEXT,
        command=app.delete_default_buy_group,
    )
    delete_default_button.grid(row=1, column=5, sticky="ew", pady=1)
    app.config_widgets.append((delete_default_button, "normal"))
