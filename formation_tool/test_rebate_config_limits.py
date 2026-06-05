import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from formation_tool.rebate import rebate_config_logic


class RebateConfigLimitTests(unittest.TestCase):
    def test_count_limits_filter_rebate_above_max_rebate(self):
        messages = []
        rows = rebate_config_logic.apply_rebate_config_count_limits_to_rows(
            [(0, 50000), (500000, 800), (500001, 20), (900000, 10)],
            {"rebate_zero": 20000, "rebate_positive": 200, "max_rebate": 500000},
            "普通局",
            print_fn=messages.append,
        )

        self.assertEqual(rows, [(0, 20000), (500000, 200)])
        self.assertEqual(len([msg for msg in messages if "rebate上限" in msg]), 2)

    def test_build_rebate_sql_filter_uses_rules_and_max_rebate(self):
        predicate = rebate_config_logic.build_rebate_sql_filter(
            [
                {"rebate": 0, "count": 2000},
                {"rebate_min": 1, "rebate_max": 999, "count": 100},
                {"rebate_min": 1000, "rebate_max": 999999, "count": 100},
            ],
            {"max_rebate": 500000},
        )

        self.assertEqual(predicate, "`rebate` BETWEEN 0 AND 500000")

    def test_build_rebate_sql_filter_direct_count_uses_only_max_rebate(self):
        predicate = rebate_config_logic.build_rebate_sql_filter(
            [{"rebate_min": 1, "rebate_max": 999, "count": 100}],
            {"max_rebate": 500000},
            include_rule_ranges=False,
        )

        self.assertEqual(predicate, "`rebate` <= 500000")


if __name__ == "__main__":
    unittest.main()
