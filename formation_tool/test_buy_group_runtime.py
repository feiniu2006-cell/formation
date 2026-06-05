import unittest
import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from formation_tool.core import runtime_config


class RuntimeBuyGroupModelTests(unittest.TestCase):
    def test_runtime_state_keeps_unified_buy_groups_in_sync_with_legacy_fields(self):
        runtime = runtime_config.RuntimeState()
        runtime.buy_group_enabled = True
        runtime.buy_group_game_type = 91
        runtime.buy_group_multiplier = 45
        runtime.buy_group_source_suffix = "special_formation"
        runtime.extra_buy_groups = [
            {"game_type": 92, "multiplier": 65, "source_suffix": "buy2_special_formation"}
        ]

        buy_groups = runtime.sync_buy_groups_from_legacy()

        self.assertEqual([group["game_type"] for group in buy_groups], [91, 92])
        self.assertTrue(buy_groups[0]["enabled"])
        self.assertEqual(buy_groups[1]["source_suffix"], "buy2_special_formation")

    def test_runtime_state_splits_unified_buy_groups_for_existing_callers(self):
        runtime = runtime_config.RuntimeState()

        runtime.apply_buy_groups([
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
                "source_suffix": "buy2_special_formation",
            },
        ])

        self.assertTrue(runtime.buy_group_enabled)
        self.assertEqual(runtime.buy_group_game_type, 91)
        self.assertEqual(runtime.buy_group_multiplier, 45.0)
        self.assertEqual(runtime.extra_buy_groups[0]["game_type"], 92)

    def test_runtime_state_sync_accepts_buy_groups_snapshot(self):
        runtime = runtime_config.RuntimeState()
        runtime.sync_group_weight_runtime_from(SimpleNamespace(
            GROUP_WEIGHT_RULES={},
            SPECIAL_GROUP_TARGET_RTP=6,
            EX_GROUP_MULTIPLIER=1.5,
            EX_BUY_GROUP_ENABLED=False,
            BUY_GROUPS=[
                {
                    "enabled": True,
                    "game_type": 91,
                    "multiplier": 45,
                    "source_suffix": "special_formation",
                }
            ],
        ))

        self.assertEqual(runtime.buy_group_game_type, 91)
        self.assertEqual(runtime.buy_groups[0]["source_suffix"], "special_formation")


if __name__ == "__main__":
    unittest.main()
