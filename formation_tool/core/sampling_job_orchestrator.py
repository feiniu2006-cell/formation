"""High-level sampling job orchestration helpers."""

from formation_tool.utils import log_utils


def sync_sampling_modes_after_success(modes, *, final_db, build_sync_items, sync_results, print_func=print):
    """Mirror completed staging results for successful sampling modes when enabled."""
    selected_modes = [str(mode) for mode in (modes or [])]
    if not selected_modes:
        print_func("自动镜像已开启，但本次没有成功采样的局类型，跳过镜像。")
        return False
    items = build_sync_items(selected_modes, existing_only=True)
    if not items:
        print_func("自动镜像已开启，但中转库中没有找到本次成功采样的正式表，跳过镜像。")
        return False
    print_func(f"自动镜像已开启：准备将 {len(items)} 张中转表同步到目标库 {final_db}。")
    return sync_results(items)


def successful_modes_from_results(results):
    return [
        mode
        for mode, success in (results or {}).items()
        if success is True
    ]


def run_all_sampling_jobs(*, run_all_jobs, build_deps, auto_sync, sync_successful_modes):
    results = run_all_jobs(deps=build_deps())
    if auto_sync:
        sync_successful_modes(successful_modes_from_results(results))
    return results


def run_single_sampling_job(
    choice,
    *,
    get_game_configs,
    run_single_game,
    auto_sync,
    sync_successful_modes,
    append_mode=False,
):
    game_config = get_game_configs()[choice]
    if append_mode:
        success = run_single_game(game_config, append_mode=True)
    else:
        success = run_single_game(game_config)
    if success and auto_sync:
        sync_successful_modes([choice])
    return success


def sync_sampling_temp_results(
    items,
    *,
    check_cancelled,
    sync_one,
    print_section=log_utils.print_section,
    print_result_summary=log_utils.print_result_summary,
    print_func=print,
):
    """Synchronize completed staging-DB sampling tables after user confirmation."""
    results = {}
    for index, item in enumerate(items or [], start=1):
        check_cancelled()
        table_name = item.get('table_name') if isinstance(item, dict) else None
        label = table_name or f"待同步表{index}"
        print_section(f"同步采样临时库：{label}")
        results[label] = sync_one(item)
    if not results:
        print_func("没有待同步的采样临时库结果。")
        return False
    print_result_summary(
        "采样临时库同步完毕，汇总结果",
        results,
        name_getter=lambda key: key,
    )
    return results


def mirror_sampling_temp_to_target(*, sampling_temp_db, final_db, build_sync_items, sync_results, print_func=print):
    """Mirror existing sampling staging-DB formal tables to the target DB."""
    items = build_sync_items("all", existing_only=True)
    if not items:
        print_func(f"采样临时库 {sampling_temp_db} 中没有找到当前游戏可镜像的采样正式表。")
        return False
    print_func(f"发现 {len(items)} 张采样中转表，将镜像到目标库 {final_db}。")
    return sync_results(items)
