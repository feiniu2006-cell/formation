"""Script-level CLI dispatch for the formation tool."""

from types import SimpleNamespace


def run_cli_main(module):
    if not module.load_cli_settings():
        return False
    deps = SimpleNamespace(
        game_configs=module.get_cli_menu_game_configs(),
        run_all_sampling_jobs=module.run_all_sampling_jobs,
        run_all_supplemental_sampling_jobs=module.run_all_supplemental_sampling_jobs,
        generate_all_rebate_configs=module.generate_all_rebate_configs,
        write_common_configs=module.write_common_configs,
        run_single_game=module.run_single_game,
        run_single_game_by_choice=module.run_single_game_job,
        run_single_supplemental_game_job=module.run_single_supplemental_game_job,
    )
    return module.run_cli(deps)


def clean_sampling_task_states(module, max_age_days=None, *, dry_run=True):
    if max_age_days is None:
        max_age_days = module.sampling_task_state.DEFAULT_COMPLETED_STATE_RETENTION_DAYS
    removed = module.sampling_task_state.cleanup_completed_states(
        max_age_days=max_age_days,
        dry_run=dry_run,
    )
    if dry_run:
        module.print(
            f"将清理 {len(removed)} 个已完成采样任务状态文件"
            f"（保留 {int(max_age_days)} 天内记录）；追加 --yes 才会实际删除"
        )
    else:
        module.print(
            f"已清理 {len(removed)} 个已完成采样任务状态文件"
            f"（保留 {int(max_age_days)} 天内记录）"
        )
    return removed


def dispatch_main(module, argv):
    if len(argv) > 1 and argv[1] == "--clean-sampling-tasks":
        clean_args = [arg for arg in argv[2:] if arg != "--yes"]
        retention_days = (
            int(clean_args[0])
            if clean_args
            else module.sampling_task_state.DEFAULT_COMPLETED_STATE_RETENTION_DAYS
        )
        return clean_sampling_task_states(
            module,
            retention_days,
            dry_run="--yes" not in argv[2:],
        )
    if len(argv) > 1 and argv[1] == "--cli":
        return run_cli_main(module)
    return module.run_gui()
