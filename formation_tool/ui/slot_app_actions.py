"""Action button definitions for the main formation tool window."""


def build_action_groups(app, deps):
    """Return action groups in the shape consumed by SlotAppUiMixin."""
    return [
        (
            "采样",
            [
                ("生成采样配置", app.open_rebate_rules_dialog),
                (
                    "全部采样",
                    lambda: app.run_task(
                        "全部采样",
                        deps.run_all_sampling_jobs,
                        preflight={"kind": "sampling", "modes": "all"},
                    ),
                ),
                ("单独采样", app.open_single_sampling_dialog),
                (
                    "补充采样",
                    lambda: app.run_task(
                        "补充采样",
                        deps.run_all_supplemental_sampling_jobs,
                        preflight={"kind": "sampling", "modes": "all", "append_mode": True},
                    ),
                ),
                ("单独补充", app.open_single_supplemental_sampling_dialog),
                (
                    "镜像到目标库",
                    lambda: app.run_task(
                        "镜像采样中转库到目标库",
                        deps.mirror_sampling_temp_to_target,
                        preflight={"kind": "sampling_temp_mirror"},
                    ),
                ),
            ],
        ),
        (
            "配置生成",
            [
                ("生成group_weight", app.open_group_weight_rules_dialog),
                (
                    "通用表配置",
                    lambda: app.run_task(
                        "通用表配置",
                        deps.write_common_configs,
                        preflight={"kind": "common_config"},
                    ),
                ),
            ],
        ),
        (
            "工具",
            [
                ("测试数据库连接", lambda: app.run_task("测试数据库连接", deps.test_selected_database_connections)),
                ("保存配置", app.save_app_settings),
                ("加载配置", app.load_app_settings),
                ("导出规则", app.export_rule_settings),
                ("导入规则", app.import_rule_settings),
                ("取消当前任务", app.cancel_current_task),
                ("清空日志", app.clear_log),
                ("退出", app.on_close),
            ],
        ),
    ]
