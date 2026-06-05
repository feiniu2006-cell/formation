"""Runner for current-game common configuration generation."""


def write_common_configs(*, deps):
    """Write special/free/bet common config tables and print a summary."""
    deps.check_cancelled()
    deps.print_section("游戏通用表配置")
    results = {
        deps.special_weight_table: deps.write_special_weight_config(),
        deps.free_game_config_table: deps.write_free_game_config(),
        deps.bet_amount_table: deps.write_bet_amount_config(),
    }
    deps.print_result_summary(
        "写入完毕，汇总结果",
        results,
        skipped_value='skipped',
    )
    return results
