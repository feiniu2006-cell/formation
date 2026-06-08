"""Command-line entrypoint helpers for the formation tool."""


def print_cli_menu(game_configs, *, print_func=print):
    print_func("\n请选择操作：")
    print_func("  0. 全部执行（按顺序采样全部已配置模式）")
    for key, config in game_configs.items():
        print_func(f"  {key}. {config['name']}（采样）")
    print_func("  4. 游戏通用表配置（game_group_special_weight_config / game_group_free_game_config / game_bet_amount_config）")
    print_func("  r. 生成采样配置（统计 rebate 分布并写入配置表）")
    print_func("  q. 退出")


def run_cli(deps, *, input_func=input, print_func=print):
    """Run the legacy command-line menu."""
    print_func("=== 游戏阵型数据处理系统 ===")
    print_cli_menu(deps.game_configs, print_func=print_func)

    choice = input_func("\n请输入选项 (0-4 / r / q): ").strip().lower()

    if choice == 'q':
        print_func("程序已退出")
        return None

    if choice == '0':
        result = deps.run_all_sampling_jobs()
        print_func("程序已退出")
        return result

    if choice == 'r':
        result = deps.generate_all_rebate_configs()
        print_func("程序已退出")
        return result

    if choice == '4':
        result = deps.write_common_configs()
        print_func("程序已退出")
        return result

    if choice not in deps.game_configs:
        print_func(f"无效选项: {choice}")
        return False

    run_single_game_by_choice = getattr(deps, 'run_single_game_by_choice', None)
    if run_single_game_by_choice is not None:
        success = run_single_game_by_choice(choice)
    else:
        success = deps.run_single_game(deps.game_configs[choice])
    print_func("程序已退出")
    return success

