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
        self.extra_weight_group_rows = []
        self.extra_weight_group_rows_frame = None
        self.add_extra_weight_group_button = None
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
        self.sampling_temp_db_var = tk.StringVar(
            value=str(runtime.get('sampling_temp_db') or app_deps.default_sampling_temp_db)
        )
        self.sampling_increment_db_var = tk.StringVar(
            value=str(runtime.get('sampling_increment_db') or app_deps.default_sampling_increment_db)
        )
        self.sampling_auto_sync_to_target_var = tk.BooleanVar(
            value=bool(runtime.get('sampling_auto_sync_to_target', False))
        )
        self.sampling_use_temp_db_var = self.sampling_auto_sync_to_target_var
        self.special_weight_0_var = tk.StringVar(value=str(trigger_weights['special_0']))
        self.special_weight_1_var = tk.StringVar(value=str(trigger_weights['special_1']))
        self.special_weight_2_var = tk.StringVar(value=str(trigger_weights['special_2']))
        self.special_weight_3_var = tk.StringVar(value=str(trigger_weights['special_3']))
        self.free_weight_0_var = tk.StringVar(value=str(trigger_weights['free_0']))
        self.free_weight_1_var = tk.StringVar(value=str(trigger_weights['free_1']))
        self.free_weight_2_var = tk.StringVar(value=str(trigger_weights['free_2']))
        self.free_weight_3_var = tk.StringVar(value=str(trigger_weights['free_3']))
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
        source_override_modes = tuple(
            str(mode)
            for mode in app_deps.group_weight_modes
            if str(mode) in {'1', '2', '3', '6', '7', '8'}
        )
        self.ex_source_suffix_vars = {
            str(mode): tk.StringVar(value=str(ex_source_suffixes.get(str(mode), "")))
            for mode in source_override_modes
        }

        self.root.title("游戏阵型数据处理系统")
        ui_layout_defaults.apply_window_layout(self.root, ui_layout_defaults.MAIN_WINDOW)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.build_ui()
        self.set_extra_weight_group_rows(app_deps.get_extra_weight_groups())
        self.setup_profile_auto_load()
        self.show_external_config_status()
        self.auto_load_app_settings()
        self.poll_log_queue()
