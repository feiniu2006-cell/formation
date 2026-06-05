import unittest
from types import SimpleNamespace

from formation_tool.core import table_driven_configs


class TableDrivenConfigTests(unittest.TestCase):
    def test_build_table_driven_base_game_configs_overrides_table_names(self):
        runtime = SimpleNamespace(
            game_table_prefix="jili_523_",
            game_configs={
                "1": {
                    "table_config": {
                        "SOURCE_TABLE": {"name": "jili_523_formation"},
                        "FINAL_TABLE": {"name": "jili_523_formation"},
                        "REBATE_CONFIG_TABLE": {"name": "jili_523_rebate_count"},
                    }
                }
            },
        )

        configs = table_driven_configs.build_table_driven_base_game_configs(
            runtime=runtime,
            get_game_type_source_suffix=lambda mode: "custom_formation" if mode == "1" else None,
            build_rebate_table_suffix_from_formation_suffix=lambda suffix: f"rebate_{suffix}_count",
        )

        table_config = configs["1"]["table_config"]
        self.assertEqual(table_config["SOURCE_TABLE"]["name"], "jili_523_custom_formation")
        self.assertEqual(table_config["FINAL_TABLE"]["name"], "jili_523_custom_formation")
        self.assertEqual(table_config["REBATE_CONFIG_TABLE"]["name"], "jili_523_rebate_custom_formation_count")

    def test_runtime_buy_group_entries_use_table_source_suffix(self):
        runtime = SimpleNamespace(
            buy_groups=[
                {
                    "enabled": True,
                    "game_type": 91,
                    "multiplier": 45,
                    "source_suffix": "special_formation",
                },
                {
                    "enabled": True,
                    "game_type": 92,
                    "multiplier": 65,
                    "source_suffix": "fallback_special_formation",
                },
            ],
            buy_group_enabled=False,
            buy_group_game_type=99,
            buy_group_multiplier=75,
            buy_group_source_suffix="free_formation",
        )

        default_entry, extra_entries = table_driven_configs.build_runtime_buy_group_entries_with_table_sources(
            runtime=runtime,
            get_game_type_source_suffix=lambda game_type, default=None: {
                91: "db_special_formation",
                92: "db_buy2_special_formation",
            }.get(int(game_type), default),
        )

        self.assertEqual(default_entry["game_type"], 91)
        self.assertEqual(default_entry["source_suffix"], "db_special_formation")
        self.assertEqual(extra_entries[0]["source_suffix"], "db_buy2_special_formation")


if __name__ == "__main__":
    unittest.main()
