"""Main Tkinter application class for the formation tool."""
import tkinter as tk

from formation_tool.ui.slot_app_dialogs import SlotAppDialogMixin
from formation_tool.ui.slot_app_settings import SlotAppSettingsMixin
from formation_tool.ui.slot_app_tasks import SlotAppTaskMixin
from formation_tool.ui.slot_app_ui import SlotAppUiMixin
from formation_tool.ui import ui_layout_defaults


class SlotProcessApp(SlotAppUiMixin, SlotAppSettingsMixin, SlotAppTaskMixin, SlotAppDialogMixin):
    """Game formation processing GUI."""

    def __init__(self, root, app_deps):
        self.root = root
        self.app_deps = app_deps
        app_deps_context = app_deps.build_deps_context()
        self.task_deps = app_deps.build_task_deps(app_deps_context)
        self.init_task_state()
        self.buttons = []
        self.cancel_button = None
        self.config_widgets = []
        self._loading_settings = False
        self._profile_load_after_id = None
        self._last_profile_key_loaded = None
        self.extra_buy_rows = []
        self.extra_buy_rows_frame = None
        self.add_extra_buy_button = None
        self.load_buy_group_types_button = None
        self.buy_group_type_loader = None
        self.ui_deps = app_deps.build_ui_deps(app_deps_context)
        self.settings_deps = app_deps.build_settings_deps(app_deps_context)

        runtime = app_deps.get_runtime_state()
        trigger_weights = app_deps.get_trigger_weights()
        self.status_var = tk.StringVar(value="就绪")
        self.vendor_var = tk.StringVar(value=runtime['vendor'])
        self.game_id_var = tk.StringVar(value=runtime['game_id'])
        self.source_db_var = tk.StringVar(value=runtime['source_db'])
        self.final_db_var = tk.StringVar(value=runtime['final_db'])
        self.config_db_var = tk.StringVar(value=runtime['config_db'])
        self.special_weight_0_var = tk.StringVar(value=str(trigger_weights['special_0']))
        self.special_weight_1_var = tk.StringVar(value=str(trigger_weights['special_1']))
        self.free_weight_0_var = tk.StringVar(value=str(trigger_weights['free_0']))
        self.free_weight_1_var = tk.StringVar(value=str(trigger_weights['free_1']))
        self.sampling_append_mode_var = tk.BooleanVar(value=app_deps.get_sampling_append_mode())
        self.sampling_detailed_log_var = tk.BooleanVar(value=app_deps.get_sampling_detailed_log())
        self.buy_group_enabled_var = tk.BooleanVar(value=app_deps.get_buy_group_enabled())
        self.ex_buy_group_enabled_var = tk.BooleanVar(value=app_deps.get_ex_buy_group_enabled())
        self.ex_buy_game_type_var = tk.StringVar(value=str(app_deps.get_ex_buy_group_game_type()))
        self.ex_buy_source_suffix_var = tk.StringVar(value=str(app_deps.get_ex_buy_group_source_suffix()))
        self.buy_game_type_var = tk.StringVar(value=str(app_deps.get_buy_group_game_type()))
        self.buy_multiplier_var = tk.StringVar(value=str(app_deps.get_buy_group_multiplier()))
        self.buy_source_suffix_var = tk.StringVar(value=str(app_deps.get_buy_group_source_suffix()))
        self.ex_multiplier_var = tk.StringVar(value=str(app_deps.get_ex_group_multiplier()))
        ex_source_suffixes = app_deps.get_ex_source_suffixes()
        self.ex_source_suffix_vars = {
            str(mode): tk.StringVar(value=str(ex_source_suffixes.get(str(mode), "")))
            for mode in app_deps.ex_group_modes
        }

        self.root.title("游戏阵型数据处理系统")
        ui_layout_defaults.apply_window_layout(self.root, ui_layout_defaults.MAIN_WINDOW)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.build_ui()
        self.setup_profile_auto_load()
        self.show_external_config_status()
        self.auto_load_app_settings()
        self.poll_log_queue()
