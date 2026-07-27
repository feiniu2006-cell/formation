"""Tkinter UI construction helpers for SlotProcessApp."""
from tkinter import messagebox, scrolledtext, ttk

from formation_tool.ui import buy_group_ui
from formation_tool.ui import external_config_status
from formation_tool.ui import slot_app_actions
from formation_tool.ui import weight_group_ui


class SlotAppUiMixin:
    """UI-building and dynamic row helpers used by SlotProcessApp."""

    def refresh_extra_buy_group_rows(self):
        return buy_group_ui.refresh_extra_buy_group_rows(self)

    def add_extra_buy_group_row(self, game_type="", multiplier="", source_suffix="free_formation"):
        return buy_group_ui.add_extra_buy_group_row(self, game_type, multiplier, source_suffix)

    def remove_extra_buy_group_row(self, row_info):
        return buy_group_ui.remove_extra_buy_group_row(self, row_info)

    def delete_default_buy_group(self):
        return buy_group_ui.delete_default_buy_group(self)

    def clear_extra_buy_group_rows(self):
        return buy_group_ui.clear_extra_buy_group_rows(self)

    def set_extra_buy_group_rows(self, groups):
        return buy_group_ui.set_extra_buy_group_rows(self, groups)

    def collect_extra_buy_groups(self):
        return buy_group_ui.collect_extra_buy_groups(self)

    def refresh_extra_weight_group_rows(self):
        return weight_group_ui.refresh_extra_weight_group_rows(self)

    def add_extra_weight_group_row(self, group_suffix="", special_weight="", free_weight=""):
        return weight_group_ui.add_extra_weight_group_row(self, group_suffix, special_weight, free_weight)

    def remove_extra_weight_group_row(self, row_info):
        return weight_group_ui.remove_extra_weight_group_row(self, row_info)

    def clear_extra_weight_group_rows(self):
        return weight_group_ui.clear_extra_weight_group_rows(self)

    def set_extra_weight_group_rows(self, groups):
        return weight_group_ui.set_extra_weight_group_rows(self, groups)

    def collect_extra_weight_groups(self):
        return weight_group_ui.collect_extra_weight_groups(self)

    def build_ui(self):
        root_frame = self.build_root_frame()
        self.build_config_section(root_frame)
        self.build_weight_section(root_frame)
        self.build_action_section(root_frame)
        self.build_log_section(root_frame)
        self.build_status_section(root_frame)

    def build_root_frame(self):
        root_frame = ttk.Frame(self.root, padding=8)
        root_frame.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        root_frame.columnconfigure(0, weight=1)
        root_frame.rowconfigure(3, weight=1)
        return root_frame

    def build_config_section(self, root_frame):
        deps = self.ui_deps
        config_frame = ttk.LabelFrame(root_frame, text="当前配置", padding=(8, 6))
        config_frame.grid(row=0, column=0, sticky="ew")
        for col in range(6):
            config_frame.columnconfigure(col, weight=1)

        db_options = sorted(deps.database_configs.keys())
        config_items = [
            ("厂商", self.vendor_var, list(deps.vendor_type_map.keys()), "readonly", "combo"),
            ("游戏编号", self.game_id_var, None, "normal", "entry"),
            ("源库", self.source_db_var, db_options, "readonly", "combo"),
            ("目标库", self.final_db_var, db_options, "readonly", "combo"),
            ("配置库", self.config_db_var, db_options, "readonly", "combo"),
            ("采样临时库", self.sampling_temp_db_var, db_options, "readonly", "combo"),
        ]
        for col, (label, variable, values, state, widget_type) in enumerate(config_items):
            ttk.Label(config_frame, text=label).grid(
                row=0, column=col, sticky="w", padx=(0, 8), pady=(0, 2)
            )
            if widget_type == "entry":
                widget = ttk.Entry(config_frame, textvariable=variable, width=14)
            else:
                widget = ttk.Combobox(
                    config_frame,
                    textvariable=variable,
                    values=values,
                    state=state,
                    width=14,
                )
            widget.grid(row=1, column=col, sticky="ew", padx=(0, 8))
            self.config_widgets.append((widget, state))

        temp_db_check = ttk.Checkbutton(
            config_frame,
            text="采样完成后自动镜像到目标库",
            variable=self.sampling_auto_sync_to_target_var,
        )
        temp_db_check.grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.config_widgets.append((temp_db_check, "normal"))

        seed_label = ttk.Label(config_frame, text=f"随机种子: {deps.random_seed}")
        seed_label.grid(row=2, column=2, columnspan=4, sticky="w", pady=(4, 0))

    def build_weight_section(self, root_frame):
        weight_frame = ttk.LabelFrame(root_frame, text="权重配置", padding=(8, 6))
        weight_frame.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        for col in range(4):
            weight_frame.columnconfigure(col, weight=1)

        weight_items = [
            ("特殊局0", self.special_weight_0_var),
            ("特殊局1", self.special_weight_1_var),
            ("免费局0", self.free_weight_0_var),
            ("免费局1", self.free_weight_1_var),
        ]
        for col, (label, variable) in enumerate(weight_items):
            ttk.Label(weight_frame, text=label).grid(
                row=0, column=col, sticky="w", padx=(0, 8), pady=(0, 2)
            )
            entry = ttk.Entry(weight_frame, textvariable=variable, width=14)
            entry.grid(row=1, column=col, sticky="ew", padx=(0, 8))
            self.config_widgets.append((entry, "normal"))

        self.build_extra_weight_group_section(weight_frame)
        self.build_purchase_section(weight_frame)

    def build_extra_weight_group_section(self, weight_frame):
        return weight_group_ui.build_extra_weight_group_section(self, weight_frame)

    def build_purchase_section(self, weight_frame):
        return buy_group_ui.build_purchase_section(self, weight_frame)

    def build_action_section(self, root_frame):
        deps = self.ui_deps
        action_container = ttk.Frame(root_frame)
        action_container.grid(row=2, column=0, sticky="ew", pady=(6, 6))
        for col in range(3):
            action_container.columnconfigure(col, weight=1)

        action_groups = slot_app_actions.build_action_groups(self, deps)
        for group_col, (group_name, actions) in enumerate(action_groups):
            self.build_action_group(action_container, group_col, group_name, actions)
        self.set_cancel_button_state("disabled")

    def build_action_group(self, action_container, group_col, group_name, actions):
        group_frame = ttk.LabelFrame(action_container, text=group_name, padding=(6, 4))
        group_frame.grid(row=0, column=group_col, sticky="nsew", padx=(0 if group_col == 0 else 4, 0))
        for col in range(2):
            group_frame.columnconfigure(col, weight=1)
        for idx, (text, command) in enumerate(actions):
            button = ttk.Button(group_frame, text=text, command=command)
            button.grid(row=idx // 2, column=idx % 2, sticky="ew", padx=2, pady=2)
            self.buttons.append(button)
            if text == "取消当前任务":
                self.cancel_button = button
        if group_name == "采样":
            self.build_sampling_mode_toggle(group_frame, len(actions))

    def build_sampling_mode_toggle(self, group_frame, action_count):
        detail_log_check = ttk.Checkbutton(
            group_frame,
            text="详细日志",
            variable=self.sampling_detailed_log_var,
        )
        toggle_row = (action_count + 1) // 2
        detail_log_check.grid(
            row=toggle_row,
            column=0,
            sticky="w",
            padx=2,
            pady=(3, 0),
        )
        self.config_widgets.append((detail_log_check, "normal"))

    def build_log_section(self, root_frame):
        log_frame = ttk.LabelFrame(root_frame, text="运行日志", padding=(6, 6))
        log_frame.grid(row=3, column=0, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            wrap="word",
            height=30,
            font=("Consolas", 10),
            state="disabled",
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")

    def build_status_section(self, root_frame):
        status_frame = ttk.Frame(root_frame)
        status_frame.grid(row=4, column=0, sticky="ew", pady=(6, 0))
        status_frame.columnconfigure(0, weight=1)
        ttk.Label(status_frame, textvariable=self.status_var).grid(row=0, column=0, sticky="w")
        self.progress = ttk.Progressbar(status_frame, mode="indeterminate", length=180)
        self.progress.grid(row=0, column=1, sticky="e")

    def show_external_config_status(self):
        source = self.ui_deps.get_external_config_source()
        load_error = self.ui_deps.get_external_config_load_error()
        missing_databases = external_config_status.find_missing_selected_databases(
            self.ui_deps.database_configs,
            (
                ("源库", self.source_db_var.get()),
                ("目标库", self.final_db_var.get()),
                ("配置库", self.config_db_var.get()),
                ("采样临时库", self.sampling_temp_db_var.get()),
            ),
        )
        if missing_databases:
            self.status_var.set("数据库配置缺少当前选择的库，请检查 db_config.json")
            messagebox.showwarning(
                "数据库配置缺失",
                external_config_status.build_missing_database_warning(
                    missing_databases,
                    external_source=source,
                    load_error=load_error,
                ),
            )
            return
        if source:
            self.status_var.set(f"已加载外部数据库配置：{source}")
        elif load_error:
            self.status_var.set("外部数据库配置加载失败，已使用内置配置")
            messagebox.showwarning(
                "外部配置加载失败",
                f"db_config.json 加载失败，当前使用 exe 内置配置。\n\n{load_error}",
            )
