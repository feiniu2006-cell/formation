"""Dialog launch helpers for SlotProcessApp."""

from tkinter import messagebox

from formation_tool.ui.group_weight_rules_dialog import GroupWeightRulesDialog
from formation_tool.ui.rebate_rules_dialog import RebateRulesDialog
from formation_tool.ui.single_sampling_dialog import SingleSamplingDialog


class SlotAppDialogMixin:
    """Open configuration dialogs after syncing the main-window config."""

    def can_open_config_dialog(self):
        if self.running:
            messagebox.showinfo("正在运行", "当前任务还没有结束，请稍后再操作。")
            return False
        return self.apply_selected_config()

    def open_single_sampling_dialog(self):
        if not self.can_open_config_dialog():
            return
        SingleSamplingDialog(
            self,
            sample_game_type_names=self.app_deps.get_sample_game_type_names(),
            game_configs=self.app_deps.get_game_configs(),
            source_db_getter=self.app_deps.get_source_db,
            formation_exists_loader=self.app_deps.get_sampling_formation_exists,
            run_single_game_job=self.app_deps.run_single_game_job,
        ).open()

    def open_single_supplemental_sampling_dialog(self):
        if not self.can_open_config_dialog():
            return
        SingleSamplingDialog(
            self,
            sample_game_type_names=self.app_deps.get_sample_game_type_names(),
            game_configs=self.app_deps.get_game_configs(),
            source_db_getter=self.app_deps.get_source_db,
            formation_exists_loader=self.app_deps.get_sampling_formation_exists,
            run_single_game_job=self.app_deps.run_single_supplemental_game_job,
            dialog_title="单独补充采样",
            start_button_text="开始补充",
            task_name_suffix="补充采样",
            append_mode=True,
        ).open()

    def open_rebate_rules_dialog(self):
        if not self.can_open_config_dialog():
            return
        RebateRulesDialog(
            self,
            sample_game_type_names=self.app_deps.get_sample_game_type_names(),
            rule_fields=self.app_deps.rebate_rule_fields,
            rule_field_labels=self.app_deps.rebate_rule_field_labels,
            low_volume_threshold=self.app_deps.low_volume_rebate_count_threshold,
            current_rules_getter=self.app_deps.get_sampling_rebate_rules,
            default_rules_getter=self.app_deps.get_default_sampling_rebate_rules,
            clone_rules=self.app_deps.clone_sampling_rebate_rules,
            validate_rules=self.app_deps.validate_sampling_rebate_rules,
            apply_rules=self.app_deps.apply_rebate_rules_config,
            apply_direct_count_modes=self.app_deps.apply_rebate_config_direct_count_modes,
            current_direct_count_tiers_getter=self.app_deps.get_direct_count_tiers,
            default_direct_count_tiers_getter=lambda: self.app_deps.default_direct_count_tiers,
            normalize_direct_count_tiers=self.app_deps.normalize_direct_count_tiers_for_load,
            apply_direct_count_tiers=self.app_deps.apply_rebate_config_direct_count_tiers,
            formation_exists_loader=self.app_deps.get_sampling_formation_exists,
            index_warnings_loader=self.app_deps.get_rebate_config_index_warnings,
            low_volume_infos_loader=self.app_deps.get_rebate_config_low_volume_infos,
            generate_configs=self.app_deps.generate_all_rebate_configs,
            ready_status_getter=self.app_deps.get_ready_status_text,
        ).open()

    def open_group_weight_rules_dialog(self):
        if not self.can_open_config_dialog():
            return
        GroupWeightRulesDialog(
            self,
            self.app_deps.build_group_weight_dialog_deps(),
        ).open()

    def open_demo_group_weight_rules_dialog(self):
        if not self.can_open_config_dialog():
            return
        messagebox.showinfo(
            "演示用group_weight配置",
            "演示用 group_weight 配置入口已预留，具体配置和生成逻辑待接入。",
            parent=self.root,
        )
