"""Single sampling mode selection dialog."""

import threading
import tkinter as tk
from tkinter import messagebox, ttk

from formation_tool.ui import ui_layout_defaults
from formation_tool.ui.gui_components import LoadingDialogBase


class SingleSamplingDialog(LoadingDialogBase):
    """单独采样选择窗口。"""

    def __init__(
        self,
        app,
        *,
        sample_game_type_names,
        game_configs,
        source_db_getter,
        formation_exists_loader,
        run_single_game_job,
        dialog_title="单独采样",
        start_button_text="开始采样",
        task_name_suffix="采样",
        append_mode=False,
    ):
        super().__init__(app)
        self.sample_game_type_names = sample_game_type_names
        self.game_configs = game_configs
        self.source_db_getter = source_db_getter
        self.formation_exists_loader = formation_exists_loader
        self.run_single_game_job = run_single_game_job
        self.dialog_title = dialog_title
        self.start_button_text = start_button_text
        self.task_name_suffix = task_name_suffix
        self.append_mode = bool(append_mode)
        self.choice_var = tk.StringVar(value="")

    def open(self):
        self.create_dialog(
            self.dialog_title,
            ui_layout_defaults.SINGLE_SAMPLING_DIALOG,
        )
        self.show_loading()
        threading.Thread(target=self.load_sampling_modes, daemon=True).start()

    def show_loading(self):
        loading_frame = ttk.Frame(self.frame)
        loading_frame.grid(row=0, column=0, sticky="nsew")
        loading_frame.columnconfigure(0, weight=1)
        loading_frame.rowconfigure(0, weight=1)
        ttk.Label(loading_frame, text="正在检测可采样源表，请稍候...").grid(
            row=0, column=0, sticky="s", pady=(0, 10)
        )
        self.loading_progress = ttk.Progressbar(loading_frame, mode="indeterminate", length=220)
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
        self.build_sampling_choices(formation_exists or {})

    def load_sampling_modes(self):
        try:
            formation_exists = self.formation_exists_loader()
        except Exception as e:
            self.root.after(0, lambda err=str(e): self.finish_loading(error=err))
            return
        self.root.after(0, lambda data=formation_exists: self.finish_loading(formation_exists=data))

    def build_sampling_choices(self, formation_exists):
        self.frame.rowconfigure(0, weight=0)
        self.frame.rowconfigure(2, weight=1)

        available_modes = [
            mode
            for mode in self.sample_game_type_names
            if formation_exists.get(mode, False)
        ]
        missing_names = [
            name
            for mode, name in self.sample_game_type_names.items()
            if not formation_exists.get(mode, False)
        ]

        ttk.Label(self.frame, text="选择要单独采样的局类型：").grid(row=0, column=0, sticky="w")
        status_text = (
            f"可采样：{', '.join(self.sample_game_type_names[mode] for mode in available_modes) if available_modes else '无'}"
            + (f"；已屏蔽：{', '.join(missing_names)}" if missing_names else "")
        )
        ttk.Label(self.frame, text=status_text, foreground="#555555", wraplength=420).grid(
            row=1, column=0, sticky="ew", pady=(6, 10)
        )

        self.choice_var.set(available_modes[0] if available_modes else "")
        choices_frame = ttk.Frame(self.frame)
        choices_frame.grid(row=2, column=0, sticky="nsew")
        choices_frame.columnconfigure(0, weight=1)
        self.build_choice_rows(choices_frame, available_modes)
        self.build_buttons(available_modes)

    def build_choice_rows(self, choices_frame, available_modes):
        if available_modes:
            source_db = self.source_db_getter()
            for row, mode in enumerate(available_modes):
                table_name = self.game_configs[mode]['table_config']['SOURCE_TABLE']['name']
                ttk.Radiobutton(
                    choices_frame,
                    text=f"{self.sample_game_type_names[mode]}    {source_db}.{table_name}",
                    variable=self.choice_var,
                    value=mode,
                ).grid(row=row, column=0, sticky="w", pady=3)
            return

        ttk.Label(
            choices_frame,
            text="当前游戏没有检测到可采样的 formation 源表，请检查厂商、游戏编号和源库配置。",
            foreground="#990000",
            wraplength=420,
        ).grid(row=0, column=0, sticky="w")

    def build_buttons(self, available_modes):
        button_frame = ttk.Frame(self.frame)
        button_frame.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        button_frame.columnconfigure(0, weight=1)
        ttk.Button(
            button_frame,
            text=self.start_button_text,
            command=self.confirm_sampling,
            state="normal" if available_modes else "disabled",
        ).grid(row=0, column=1, sticky="e", padx=(0, 8))
        ttk.Button(button_frame, text="取消", command=self.dialog.destroy).grid(
            row=0, column=2, sticky="e"
        )

    def confirm_sampling(self):
        mode = self.choice_var.get()
        if not mode:
            messagebox.showwarning("单独采样", "没有可采样的局类型。", parent=self.dialog)
            return
        self.dialog.destroy()
        self.app.run_task(
            f"{self.sample_game_type_names[mode]}{self.task_name_suffix}",
            lambda m=mode: self.run_single_game_job(m),
            preflight={"kind": "sampling", "modes": [mode], "append_mode": self.append_mode},
        )

