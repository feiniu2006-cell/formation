import unittest
from types import SimpleNamespace

from formation_tool.core import task_dependency_factories
from formation_tool.core import task_entrypoints
from formation_tool.core import task_preflight


class TaskEntrypointDepsTests(unittest.TestCase):
    def test_build_all_sampling_deps_returns_typed_deps(self):
        callbacks = SimpleNamespace(
            get_game_configs=lambda: {},
            get_sampling_formation_exists=lambda: {},
            get_source_formation_check_error=lambda _mode: None,
            get_table_name=lambda *_args: "",
            run_single_game=lambda _config: True,
            check_cancelled=lambda: None,
        )

        deps = task_entrypoints.build_all_sampling_deps(callbacks)

        self.assertIsInstance(deps, task_entrypoints.AllSamplingDeps)
        self.assertIs(deps.get_game_configs, callbacks.get_game_configs)

    def test_build_rebate_config_generation_deps_returns_typed_deps(self):
        callbacks = SimpleNamespace(
            get_game_configs=lambda: {},
            get_rebate_rules=lambda: {},
            get_sampling_formation_exists=lambda: {},
            get_source_formation_check_error=lambda _mode: None,
            get_table_name=lambda *_args: "",
            generate_rebate_config_for_game=lambda *_args, **_kwargs: True,
            check_cancelled=lambda: None,
        )
        limits = SimpleNamespace(
            rebate_zero_count_limit=20000,
            positive_rebate_count_limit=200,
            max_rebate=500000,
            count_limits={"rebate_zero": 20000, "rebate_positive": 200, "max_rebate": 500000},
        )

        deps = task_entrypoints.build_rebate_config_generation_deps(callbacks, limits)

        self.assertIsInstance(deps, task_entrypoints.RebateConfigGenerationDeps)
        self.assertEqual(deps.max_rebate, 500000)
        self.assertEqual(deps.count_limits["rebate_positive"], 200)

    def test_all_sampling_preflight_skips_missing_source_modes(self):
        deps = self._build_sampling_preflight_deps(
            formation_exists={"1": True, "2": False},
            config_tables={"jili_49_rebate_count": 12},
        )
        report = task_preflight.PreflightReport("全部采样")

        task_preflight.preflight_sampling(report, {"modes": "all"}, deps)

        self.assertTrue(report.ok)
        self.assertTrue(any("jili_49_special_formation" in msg for msg in report.warnings))
        self.assertTrue(any("jili_49_rebate_count" in msg for msg in report.info))

    def test_single_sampling_preflight_fails_missing_source_mode(self):
        deps = self._build_sampling_preflight_deps(
            formation_exists={"1": True, "2": False},
            config_tables={"jili_49_rebate_count": 12},
        )
        report = task_preflight.PreflightReport("单独采样")

        task_preflight.preflight_sampling(report, {"modes": ["2"]}, deps)

        self.assertFalse(report.ok)
        self.assertTrue(any("jili_49_special_formation" in msg for msg in report.fatal_errors))

    def test_task_dependency_factories_build_sampling_deps_from_module_namespace(self):
        module = SimpleNamespace(
            get_runtime_game_configs=lambda: {"1": {}},
            get_sampling_formation_exists=lambda: {"1": True},
            get_source_formation_check_error=lambda _mode: None,
            get_table_name=lambda *_args: "table",
            run_single_game=lambda _config: True,
            check_cancelled=lambda: None,
        )

        deps = task_dependency_factories.build_all_sampling_jobs_deps(module)

        self.assertIsInstance(deps, task_entrypoints.AllSamplingDeps)
        self.assertEqual(deps.get_game_configs(), {"1": {}})

    def test_task_dependency_factories_build_rebate_config_deps_from_module_namespace(self):
        module = SimpleNamespace(
            get_runtime_game_configs=lambda: {},
            get_runtime_rebate_rules=lambda: {},
            get_sampling_formation_exists=lambda: {},
            get_source_formation_check_error=lambda _mode: None,
            get_table_name=lambda *_args: "table",
            generate_rebate_config_for_game=lambda *_args, **_kwargs: True,
            check_cancelled=lambda: None,
            REBATE_CONFIG_REBATE_ZERO_COUNT_LIMIT=20000,
            REBATE_CONFIG_POSITIVE_REBATE_COUNT_LIMIT=200,
            REBATE_CONFIG_MAX_REBATE=500000,
            REBATE_CONFIG_COUNT_LIMITS={"rebate_zero": 20000},
        )

        deps = task_dependency_factories.build_rebate_config_generation_deps(module)

        self.assertIsInstance(deps, task_entrypoints.RebateConfigGenerationDeps)
        self.assertEqual(deps.max_rebate, 500000)

    def _build_sampling_preflight_deps(self, *, formation_exists, config_tables):
        game_configs = {
            "1": {
                "name": "普通局",
                "table_config": {
                    "SOURCE_TABLE": {"database": "SRC", "table": "jili_49_formation"},
                    "REBATE_CONFIG_TABLE": {"database": "CFG", "table": "jili_49_rebate_count"},
                },
            },
            "2": {
                "name": "特殊局",
                "table_config": {
                    "SOURCE_TABLE": {"database": "SRC", "table": "jili_49_special_formation"},
                    "REBATE_CONFIG_TABLE": {"database": "CFG", "table": "jili_49_rebate_special_count"},
                },
            },
        }

        return SimpleNamespace(
            get_game_configs=lambda: game_configs,
            get_sampling_formation_exists=lambda: formation_exists,
            get_source_formation_check_error=lambda _mode: None,
            get_table_database=lambda key, table_config: table_config[key]["database"],
            get_table_name=lambda key, table_config: table_config[key]["table"],
            connect_to_database=lambda db_name: db_name,
            table_exists_exact=lambda _conn, table_name: table_name in config_tables,
            count_table_rows=lambda _conn, table_name: config_tables[table_name],
            close_safely=lambda _conn: None,
        )


if __name__ == "__main__":
    unittest.main()
