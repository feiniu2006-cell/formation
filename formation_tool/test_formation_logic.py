import contextlib
import io
import importlib
import os
import subprocess
import sys
import tkinter as tk
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

import build_formation_exe
from formation_tool.common import common_config_entrypoints
from formation_tool.common import common_config_runner
from formation_tool.cli import formation_cli
from formation_tool.core import buy_group_config
from formation_tool.core import game_type_config
from formation_tool.core import runtime_config
from formation_tool.core import runtime_state_sync
from formation_tool.core import runtime_context_sync
from formation_tool.core import formation_modes
from formation_tool.core import formation_defaults
from formation_tool.core import settings_logic
from formation_tool.db import formation_db_access
from formation_tool.db import db_runtime
from formation_tool.db import db_entrypoints
from formation_tool.db import game_type_config_runtime
from formation_tool.group_weight import group_weight_builder
from formation_tool.group_weight import group_weight_entrypoints
from formation_tool.group_weight import group_weight_logic
from formation_tool.group_weight import group_weight_pair_sets
from formation_tool.group_weight import group_weight_storage
from formation_tool.group_weight import group_weight_runner
from formation_tool.group_weight import group_weight_ui_text
from formation_tool.rebate import rebate_config_logic
from formation_tool.rebate import buy_source_rebate_configs
from formation_tool.rebate import rebate_config_entrypoints
from formation_tool.rebate import rebate_config_runner
from formation_tool.rebate import rebate_config_storage
from formation_tool.sampling import direct_sampling_runner
from formation_tool.sampling import sampling_core
from formation_tool.sampling import sampling_entrypoints
from formation_tool.sampling import sampling_table_utils
from formation_tool.sampling import sampling_task_state
from formation_tool.utils import log_utils
from formation_tool.ui import slot_app_context
from formation_tool.ui import slot_app_deps
from formation_tool.ui import buy_group_ui
from formation_tool.ui import external_config_status
from formation_tool.ui import group_weight_rules_dialog
from formation_tool.ui import rebate_rules_dialog
from formation_tool.ui import single_sampling_dialog
from formation_tool.ui import slot_app_settings
from formation_tool.ui import slot_app_tasks
from formation_tool.ui import ui_layout_defaults
from formation_tool.ui.slot_app_settings import SlotAppSettingsMixin


def run_direct_sampling_silently(deps):
    with contextlib.redirect_stdout(io.StringIO()):
        return direct_sampling_runner.direct_sample_from_source({}, {}, deps=deps)


class PackageLayoutTests(unittest.TestCase):
    def test_split_packages_import(self):
        module_names = [
            "formation_tool.common.common_config_writer",
            "formation_tool.core.runtime_config",
            "formation_tool.core.game_type_config",
            "formation_tool.core.runtime_state_sync",
            "formation_tool.core.task_entrypoints",
            "formation_tool.core.table_driven_configs",
            "formation_tool.db.db_runtime",
            "formation_tool.db.db_entrypoints",
            "formation_tool.db.game_type_config_runtime",
            "formation_tool.db.formation_db_access",
            "formation_tool.db.formation_table_detection",
            "formation_tool.group_weight.group_weight_logic",
            "formation_tool.group_weight.group_weight_entrypoints",
            "formation_tool.group_weight.group_weight_messages",
            "formation_tool.group_weight.group_weight_preview",
            "formation_tool.group_weight.group_weight_rebate_loader",
            "formation_tool.group_weight.group_weight_buy_modes",
            "formation_tool.group_weight.group_weight_ex_modes",
            "formation_tool.group_weight.group_weight_original_modes",
            "formation_tool.group_weight.group_weight_row_helpers",
            "formation_tool.group_weight.group_weight_ui_text",
            "formation_tool.rebate.rebate_config_logic",
            "formation_tool.rebate.buy_source_rebate_configs",
            "formation_tool.rebate.rebate_config_entrypoints",
            "formation_tool.rebate.rebate_config_runner",
            "formation_tool.sampling.direct_sampling_runner",
            "formation_tool.sampling.sampling_entrypoints",
            "formation_tool.sampling.sampling_core",
            "formation_tool.sampling.sampling_table_utils",
            "formation_tool.ui.slot_app_actions",
            "formation_tool.ui.slot_app_context",
            "formation_tool.ui.slot_app_dialogs",
            "formation_tool.ui.slot_process_app",
            "formation_tool.ui.buy_group_ui",
            "formation_tool.ui.external_config_status",
            "formation_tool.ui.ui_text",
            "formation_tool.utils.sql_utils",
            "formation_tool.cli.formation_cli",
        ]
        for module_name in module_names:
            with self.subTest(module_name=module_name):
                self.assertIsNotNone(importlib.import_module(module_name))

    def test_source_text_has_no_common_mojibake_markers(self):
        markers = (
            "鎵ц",
            "寮€",
            "婧愯",
            "閰嶇",
            "瑙ｆ",
            "璇诲",
            "鐩",
            "鏁版",
            "涓嶅",
            "杩囩",
            "鍐欏",
            "澶辫",
            "銆?",
        )
        excluded_parts = {"build", "build_encrypted", "dist_encrypted", "__pycache__"}
        bad_lines = []
        for path in Path("formation_tool").rglob("*.py"):
            if path.name == "test_formation_logic.py":
                continue
            if any(part in excluded_parts for part in path.parts):
                continue
            text = path.read_text(encoding="utf-8-sig")
            for line_no, line in enumerate(text.splitlines(), 1):
                if any(marker in line for marker in markers):
                    bad_lines.append(f"{path}:{line_no}: {line}")

        self.assertEqual(bad_lines, [])


class CliEntryPointTests(unittest.TestCase):
    def test_run_cli_uses_choice_callback_for_single_game(self):
        events = []
        deps = SimpleNamespace(
            game_configs={"1": {"name": "普通局"}},
            run_all_sampling_jobs=lambda: events.append("all"),
            generate_all_rebate_configs=lambda: events.append("rebate"),
            write_common_configs=lambda: events.append("common"),
            run_single_game=lambda _config: events.append("legacy"),
            run_single_game_by_choice=lambda choice: events.append(("choice", choice)) or True,
        )

        result = formation_cli.run_cli(
            deps,
            input_func=lambda _prompt: "1",
            print_func=lambda _text: None,
        )

        self.assertTrue(result)
        self.assertEqual(events, [("choice", "1")])

    def test_run_cli_keeps_legacy_single_game_callback(self):
        events = []
        config = {"name": "普通局"}
        deps = SimpleNamespace(
            game_configs={"1": config},
            run_all_sampling_jobs=lambda: events.append("all"),
            generate_all_rebate_configs=lambda: events.append("rebate"),
            write_common_configs=lambda: events.append("common"),
            run_single_game=lambda received: events.append(("legacy", received)) or True,
        )

        result = formation_cli.run_cli(
            deps,
            input_func=lambda _prompt: "1",
            print_func=lambda _text: None,
        )

        self.assertTrue(result)
        self.assertEqual(events, [("legacy", config)])


class GroupWeightLogicTests(unittest.TestCase):
    def test_build_rebate_weight_pairs_and_zero_weight(self):
        pairs, skipped_zero, skipped_rebate_zero = group_weight_logic.build_rebate_weight_pairs(
            [0, 1000, 2000, 9000],
            [
                {"rebate_min": 0, "weight": 0},
                {"rebate_min": 1000, "weight": 10},
                {"rebate_min": 5000, "weight": 20},
            ],
            exclude_rebate_zero=True,
        )
        self.assertEqual(pairs, [(1000, 10), (2000, 10), (9000, 20)])
        self.assertEqual(skipped_zero, 0)
        self.assertEqual(skipped_rebate_zero, 1)

        pairs, skipped_zero, skipped_rebate_zero = group_weight_logic.build_rebate_weight_pairs(
            [0, 5000, 6000, 10000, 20000],
            [
                {"rebate_min": 0, "weight": 0},
                {"rebate_min": 10000, "weight": 5},
                {"rebate_min": 20000, "weight": 0},
            ],
        )
        self.assertEqual(pairs, [(10000, 5)])
        self.assertEqual(skipped_zero, 4)
        self.assertEqual(skipped_rebate_zero, 0)
        self.assertEqual(
            group_weight_logic.build_zero_weight_rebate_pairs(
                [0, 5000, 6000, 10000, 20000],
                [
                    {"rebate_min": 0, "weight": 0},
                    {"rebate_min": 10000, "weight": 5},
                    {"rebate_min": 20000, "weight": 0},
                ],
            ),
            [(0, 0), (5000, 0), (6000, 0), (20000, 0)],
        )

        zero_weight = group_weight_logic.infer_zero_rebate_weight([(1000, 10)], 0.5)
        self.assertEqual(zero_weight, 10)

    def test_zero_weight_pairs_do_not_change_rtp_calculation(self):
        base_rows, base_info = group_weight_logic.build_normal_group_weight_rows_for_group(
            9000,
            [(1000, 10)],
            free_rtp=0,
            free_enabled=False,
            special_rtp=0,
            special_enabled=False,
            free_rate_getter=lambda _group_id, _enabled: 0,
            special_rate_getter=lambda _group_id, _enabled: 0,
            target_rtp_getter=lambda _group_id: 1,
        )
        zero_rows, zero_info = group_weight_logic.build_normal_group_weight_rows_for_group(
            9000,
            [(1000, 10), (2000, 0)],
            free_rtp=0,
            free_enabled=False,
            special_rtp=0,
            special_enabled=False,
            free_rate_getter=lambda _group_id, _enabled: 0,
            special_rate_getter=lambda _group_id, _enabled: 0,
            target_rtp_getter=lambda _group_id: 1,
        )

        self.assertEqual(base_info["normal_target_rtp"], zero_info["normal_target_rtp"])
        self.assertEqual(base_info["zero_weight"], zero_info["zero_weight"])
        self.assertEqual(base_info["actual_normal_rtp"], zero_info["actual_normal_rtp"])
        self.assertEqual(base_rows, [(1, 9000, 1000, 10)])
        self.assertEqual(zero_rows, [(1, 9000, 1000, 10), (1, 9000, 2000, 0)])

    def test_zero_rebate_inference_requires_sampled_zero_and_enabled_mode(self):
        self.assertTrue(group_weight_logic.should_infer_zero_rebate("1", [0, 1000], {"1"}))
        self.assertFalse(group_weight_logic.should_infer_zero_rebate("1", [1000, 2000], {"1"}))
        self.assertFalse(group_weight_logic.should_infer_zero_rebate("1", [0, 1000], set()))

    def test_group_weight_preview_points_use_actual_rebates(self):
        preview = group_weight_builder.group_weight_preview
        names = ("BUY_GROUP_MODE", "get_group_weight_rebate_source_mode", "get_group_weight_rtp_role")
        missing = object()
        old_values = {name: getattr(preview, name, missing) for name in names}
        try:
            preview.BUY_GROUP_MODE = "buy"
            preview.get_group_weight_rebate_source_mode = lambda mode: mode
            preview.get_group_weight_rtp_role = lambda _mode: "special"

            points = preview.build_group_weight_preview_points(
                "2",
                9650,
                {
                    "2": [
                        {"rebate_min": 0, "weight": 0},
                        {"rebate_min": 5000, "weight": 3000},
                        {"rebate_min": 10000, "weight": 1000},
                    ]
                },
                {},
                {"2": [0, 5500, 8300, 12000]},
                {},
                {"2": True},
            )
        finally:
            for name, value in old_values.items():
                if value is missing:
                    if hasattr(preview, name):
                        delattr(preview, name)
                else:
                    setattr(preview, name, value)

        self.assertEqual(points, [(0, 0), (5500, 3000), (8300, 3000), (12000, 1000)])

    def test_group_weight_preview_points_use_inferred_zero_rebate_weight(self):
        preview = group_weight_builder.group_weight_preview
        names = ("BUY_GROUP_MODE", "get_group_weight_rebate_source_mode", "get_group_weight_rtp_role")
        missing = object()
        old_values = {name: getattr(preview, name, missing) for name in names}
        try:
            preview.BUY_GROUP_MODE = "buy"
            preview.get_group_weight_rebate_source_mode = lambda mode: mode
            preview.get_group_weight_rtp_role = lambda _mode: "special"

            points = preview.build_group_weight_preview_points(
                "2",
                9650,
                {"2": [{"rebate_min": 0, "weight": 0}, {"rebate_min": 1, "weight": 10}]},
                {},
                {"2": [0, 1000]},
                {},
                {"2": True},
                special_target_rtp=0.5,
                zero_rebate_inference_modes={"2"},
            )
        finally:
            for name, value in old_values.items():
                if value is missing:
                    if hasattr(preview, name):
                        delattr(preview, name)
                else:
                    setattr(preview, name, value)

        self.assertEqual(points, [(0, 10), (1000, 10)])

    def test_buy_modes_support_manual_zero_rebate_inference_but_default_off(self):
        from formation_tool.core import formation_modes

        self.assertEqual(formation_modes.BUY_GROUP_MODE, "buy")
        self.assertEqual(formation_modes.EX_PURCHASE_MODE, "ex_buy")
        self.assertTrue(formation_modes.supports_zero_rebate_inference("buy"))
        self.assertTrue(formation_modes.supports_zero_rebate_inference("ex_buy"))
        self.assertTrue(formation_modes.supports_zero_rebate_inference("99"))
        self.assertTrue(formation_modes.supports_zero_rebate_inference("98"))
        self.assertNotIn("buy", formation_modes.DEFAULT_ZERO_REBATE_INFERENCE_MODES)
        self.assertNotIn("ex_buy", formation_modes.DEFAULT_ZERO_REBATE_INFERENCE_MODES)

    def test_only_normal_modes_support_independent_rtp_option(self):
        self.assertTrue(formation_modes.supports_independent_rtp("1"))
        self.assertTrue(formation_modes.supports_independent_rtp("6"))
        self.assertFalse(formation_modes.supports_independent_rtp("2"))
        self.assertFalse(formation_modes.supports_independent_rtp("buy"))
        self.assertEqual(formation_modes.normalize_independent_rtp_modes(["1", "2", "6", "buy"]), {"1", "6"})
        self.assertEqual(formation_modes.DEFAULT_INDEPENDENT_RTP_MODES, ())

    def test_normal_preview_independent_rtp_ignores_trigger_parse_errors(self):
        preview = group_weight_builder.group_weight_preview
        names = (
            "BUY_GROUP_MODE",
            "get_group_weight_rebate_source_mode",
            "get_group_weight_rtp_role",
            "get_group_weight_write_game_type",
            "get_group_target_rtp_ratio",
        )
        missing = object()
        old_values = {name: getattr(preview, name, missing) for name in names}
        try:
            preview.BUY_GROUP_MODE = "buy"
            preview.get_group_weight_rebate_source_mode = lambda mode: mode
            preview.get_group_weight_rtp_role = lambda mode: "normal" if str(mode) == "1" else "static"
            preview.get_group_weight_write_game_type = lambda mode: int(mode)
            preview.get_group_target_rtp_ratio = lambda _group_id: 0.5

            text = preview.build_group_weight_preview_text(
                "1",
                9650,
                {"1": [{"rebate_min": 0, "weight": 0}, {"rebate_min": 1, "weight": 10}]},
                {"2": "特殊局配置错误"},
                {"1": [0, 1000]},
                {},
                {"1": True, "2": True},
                zero_rebate_inference_modes={"1"},
                independent_rtp_modes={"1"},
            )
        finally:
            for name, value in old_values.items():
                if value is missing:
                    if hasattr(preview, name):
                        delattr(preview, name)
                else:
                    setattr(preview, name, value)

        self.assertIn("独立RTP开启", text)
        self.assertIn("目标=0.5", text)
        self.assertIn("反推0权重=10", text)
        self.assertNotIn("特殊局配置错误", text)

    def test_ex_normal_preview_independent_rtp_uses_group_target_times_multiplier(self):
        preview = group_weight_builder.group_weight_preview
        names = (
            "BUY_GROUP_MODE",
            "get_group_weight_rebate_source_mode",
            "get_group_weight_rtp_role",
            "get_group_weight_write_game_type",
            "get_group_target_rtp_ratio",
        )
        missing = object()
        old_values = {name: getattr(preview, name, missing) for name in names}
        try:
            preview.BUY_GROUP_MODE = "buy"
            preview.get_group_weight_rebate_source_mode = lambda mode: mode
            preview.get_group_weight_rtp_role = lambda mode: "ex_normal" if str(mode) == "6" else "static"
            preview.get_group_weight_write_game_type = lambda mode: int(mode)
            preview.get_group_target_rtp_ratio = lambda _group_id: 1

            text = preview.build_group_weight_preview_text(
                "6",
                9650,
                {"6": [{"rebate_min": 0, "weight": 0}, {"rebate_min": 1, "weight": 10}]},
                {"7": "ex特殊局配置错误"},
                {"6": [0, 4000]},
                {},
                {"6": True, "7": True},
                ex_multiplier=2,
                zero_rebate_inference_modes={"6"},
                independent_rtp_modes={"6"},
            )
        finally:
            for name, value in old_values.items():
                if value is missing:
                    if hasattr(preview, name):
                        delattr(preview, name)
                else:
                    setattr(preview, name, value)

        self.assertIn("独立RTP开启", text)
        self.assertIn("目标=1", text)
        self.assertIn("反推目标=2", text)
        self.assertIn("反推0权重=10", text)
        self.assertIn("最终RTP=1", text)
        self.assertNotIn("ex特殊局配置错误", text)

    def test_buy_like_rows_can_infer_zero_rebate_per_group_target(self):
        row_helpers = group_weight_builder.group_weight_row_helpers
        names = ("WEIGHT_GROUP_IDS", "get_group_target_rtp_ratio")
        missing = object()
        old_values = {name: getattr(row_helpers, name, missing) for name in names}
        try:
            row_helpers.WEIGHT_GROUP_IDS = (9650,)
            row_helpers.get_group_target_rtp_ratio = lambda _group_id: 1
            rows = []

            row_count, infos = row_helpers.append_targeted_buy_like_group_weight_rows(
                rows,
                97,
                [(4000, 10)],
                2,
            )
        finally:
            for name, value in old_values.items():
                if value is missing:
                    if hasattr(row_helpers, name):
                        delattr(row_helpers, name)
                else:
                    setattr(row_helpers, name, value)

        self.assertEqual(row_count, 2)
        self.assertEqual(rows, [(97, 9650, 0, 10), (97, 9650, 4000, 10)])
        self.assertEqual(infos[9650]["zero_weight"], 10)
        self.assertEqual(infos[9650]["display_rtp"], 1)

    def test_normal_rows_can_disable_zero_rebate_inference(self):
        rows, info = group_weight_logic.build_normal_group_weight_rows_for_group(
            9000,
            [(1000, 10)],
            free_rtp=0,
            free_enabled=False,
            special_rtp=0,
            special_enabled=False,
            free_rate_getter=lambda _group_id, _enabled: 0,
            special_rate_getter=lambda _group_id, _enabled: 0,
            target_rtp_getter=lambda _group_id: 0.5,
            infer_zero_rebate=False,
        )

        self.assertEqual(info["zero_weight"], 0)
        self.assertEqual(rows, [(1, 9000, 1000, 10)])

    def test_zero_weight_trigger_modes_do_not_enable_trigger_rtp(self):
        original_modes = group_weight_builder.group_weight_original_modes
        missing = object()
        old_target = getattr(original_modes, "SPECIAL_GROUP_TARGET_RTP", missing)
        original_modes.SPECIAL_GROUP_TARGET_RTP = 1
        try:
            context = original_modes.prepare_original_trigger_rtp_context(
                rebates_by_mode={"2": [1000], "3": [5000]},
                mode_exists={"2": True, "3": True},
                mode_pairs={"2": [], "3": []},
            )
        finally:
            if old_target is missing:
                delattr(original_modes, "SPECIAL_GROUP_TARGET_RTP")
            else:
                original_modes.SPECIAL_GROUP_TARGET_RTP = old_target

        self.assertFalse(context["special_enabled"])
        self.assertFalse(context["free_enabled"])
        self.assertEqual(context["special_rtp"], 0)
        self.assertEqual(context["free_rtp"], 0)

    def test_ex_independent_target_rtp_uses_display_target_times_multiplier(self):
        row_helpers = group_weight_builder.group_weight_row_helpers
        names = (
            "WEIGHT_GROUP_IDS",
            "EX_GROUP_TARGET_RTPS",
            "EX_GROUP_MULTIPLIER",
            "get_group_target_rtp_ratio",
        )
        missing = object()
        old_values = {name: getattr(row_helpers, name, missing) for name in names}
        try:
            row_helpers.WEIGHT_GROUP_IDS = (9000,)
            row_helpers.EX_GROUP_TARGET_RTPS = {"7": 3}
            row_helpers.EX_GROUP_MULTIPLIER = 2
            row_helpers.get_group_target_rtp_ratio = lambda _group_id: 1

            rows = []
            _row_count, infos = row_helpers.append_independent_ex_group_rows(
                rows,
                "7",
                [(100000, 10)],
                has_zero=True,
            )
        finally:
            for name, value in old_values.items():
                if value is missing:
                    if hasattr(row_helpers, name):
                        delattr(row_helpers, name)
                else:
                    setattr(row_helpers, name, value)

        self.assertEqual(infos[9000]["base_target_rtp"], 3)
        self.assertEqual(infos[9000]["target_rtp"], 6)
        self.assertEqual(rows[0][:3], (7, 9000, 0))

    def test_ex_free_mode_is_static_not_independent(self):
        from formation_tool.core import formation_modes

        self.assertEqual(formation_modes.get_group_weight_rtp_role("8"), "static")
        self.assertEqual(formation_modes.EX_INDEPENDENT_GROUP_WEIGHT_MODES, ("7",))

    def test_ex_free_generation_uses_static_rtp_without_zero_inference(self):
        ex_modes = group_weight_builder.group_weight_ex_modes
        row_helpers = group_weight_builder.group_weight_row_helpers
        names = (
            "WEIGHT_GROUP_IDS",
            "GAME_TYPE_NAMES",
            "EX_GROUP_MULTIPLIER",
            "get_group_weight_write_game_type",
        )
        row_helper_names = ("WEIGHT_GROUP_IDS",)
        missing = object()
        old_values = {name: getattr(ex_modes, name, missing) for name in names}
        old_row_helper_values = {name: getattr(row_helpers, name, missing) for name in row_helper_names}
        try:
            ex_modes.WEIGHT_GROUP_IDS = (9000, 9001)
            ex_modes.GAME_TYPE_NAMES = {"8": "ex免费局"}
            ex_modes.EX_GROUP_MULTIPLIER = 2
            ex_modes.get_group_weight_write_game_type = lambda mode: int(mode)
            row_helpers.WEIGHT_GROUP_IDS = (9000, 9001)

            rows = []
            ex_info_by_mode = {"7": {}}
            ex_modes.append_ex_free_group_weight_mode(
                rows,
                formation_exists={"8": True},
                rebates_by_mode={"8": [9000, 18000]},
                mode_exists={"8": True},
                mode_pairs={"8": [(9000, 2), (18000, 1)]},
                ex_info_by_mode=ex_info_by_mode,
            )
        finally:
            for name, value in old_values.items():
                if value is missing:
                    if hasattr(ex_modes, name):
                        delattr(ex_modes, name)
                else:
                    setattr(ex_modes, name, value)
            for name, value in old_row_helper_values.items():
                if value is missing:
                    if hasattr(row_helpers, name):
                        delattr(row_helpers, name)
                else:
                    setattr(row_helpers, name, value)

        self.assertEqual(
            rows,
            [
                (8, 9000, 9000, 2),
                (8, 9000, 18000, 1),
                (8, 9001, 9000, 2),
                (8, 9001, 18000, 1),
            ],
        )
        self.assertEqual(ex_info_by_mode["8"][9000]["zero_weight"], 0)
        self.assertEqual(ex_info_by_mode["8"][9000]["actual_rtp"], 12)
        self.assertEqual(ex_info_by_mode["8"][9000]["display_rtp"], 6)

    def test_original_normal_generation_can_use_independent_rtp(self):
        original_modes = group_weight_builder.group_weight_original_modes
        names = (
            "WEIGHT_GROUP_IDS",
            "ZERO_REBATE_INFERENCE_MODES",
            "INDEPENDENT_RTP_MODES",
            "get_group_weight_write_game_type",
            "get_group_target_rtp_ratio",
            "check_cancelled",
        )
        missing = object()
        old_values = {name: getattr(original_modes, name, missing) for name in names}
        try:
            original_modes.WEIGHT_GROUP_IDS = (9000,)
            original_modes.ZERO_REBATE_INFERENCE_MODES = {"1"}
            original_modes.INDEPENDENT_RTP_MODES = {"1"}
            original_modes.get_group_weight_write_game_type = lambda mode: int(mode)
            original_modes.get_group_target_rtp_ratio = lambda _group_id: 0.5
            original_modes.check_cancelled = lambda: None
            rows = []

            count = original_modes.append_original_normal_group_weight_rows(
                rows,
                rebates_by_mode={"1": [0, 1000]},
                mode_exists={"1": True},
                mode_pairs={"1": [(1000, 10)]},
                trigger_context={
                    "free_rtp": 100,
                    "free_enabled": True,
                    "special_rtp": 100,
                    "special_enabled": True,
                },
            )
        finally:
            for name, value in old_values.items():
                if value is missing:
                    if hasattr(original_modes, name):
                        delattr(original_modes, name)
                else:
                    setattr(original_modes, name, value)

        self.assertEqual(count, 2)
        self.assertEqual(rows, [(1, 9000, 0, 10), (1, 9000, 1000, 10)])

    def test_ex_normal_generation_can_use_independent_rtp(self):
        ex_modes = group_weight_builder.group_weight_ex_modes
        names = (
            "WEIGHT_GROUP_IDS",
            "GAME_TYPE_NAMES",
            "ZERO_REBATE_INFERENCE_MODES",
            "INDEPENDENT_RTP_MODES",
            "EX_GROUP_MULTIPLIER",
            "get_group_weight_write_game_type",
            "get_group_target_rtp_ratio",
            "check_cancelled",
        )
        missing = object()
        old_values = {name: getattr(ex_modes, name, missing) for name in names}
        try:
            ex_modes.WEIGHT_GROUP_IDS = (9000,)
            ex_modes.GAME_TYPE_NAMES = {"6": "ex普通局"}
            ex_modes.ZERO_REBATE_INFERENCE_MODES = {"6"}
            ex_modes.INDEPENDENT_RTP_MODES = {"6"}
            ex_modes.EX_GROUP_MULTIPLIER = 2
            ex_modes.get_group_weight_write_game_type = lambda mode: int(mode)
            ex_modes.get_group_target_rtp_ratio = lambda _group_id: 0.5
            ex_modes.check_cancelled = lambda: None
            rows = []

            ex_modes.append_ex_normal_group_weight_mode(
                rows,
                formation_exists={"6": True},
                rebates_by_mode={"6": [0, 4000]},
                mode_exists={"6": True, "7": True, "8": True},
                mode_pairs={"6": [(4000, 10)], "7": [], "8": []},
                ex_info_by_mode={
                    "7": {9000: {"actual_rtp": 100}},
                    "8": {9000: {"actual_rtp": 100}},
                },
            )
        finally:
            for name, value in old_values.items():
                if value is missing:
                    if hasattr(ex_modes, name):
                        delattr(ex_modes, name)
                else:
                    setattr(ex_modes, name, value)

        self.assertEqual(rows, [(6, 9000, 0, 30), (6, 9000, 4000, 10)])

    def test_ex_static_preview_shows_final_rtp_after_ex_multiplier(self):
        preview = group_weight_builder.group_weight_preview.build_ex_static_group_weight_preview(
            sampled_rebates=[9000, 18000],
            rtp_pairs=[(9000, 2), (18000, 1)],
            skipped_zero=0,
            ex_multiplier=2,
        )

        self.assertIn("12", preview)
        self.assertIn("ex倍数=2", preview)
        self.assertIn("最终RTP=6", preview)

    def test_default_weight_group_ids_only_use_group_suffix_0_and_1(self):
        suffixes = {int(group_id) % 10 for group_id in formation_defaults.DEFAULT_WEIGHT_GROUP_IDS}
        self.assertEqual(suffixes, {0, 1})
        for group_id in (9652, 9653, 9654, 9655):
            self.assertNotIn(group_id, formation_defaults.DEFAULT_WEIGHT_GROUP_IDS)

    def test_extra_weight_groups_can_extend_group_ids_from_main_ui_config(self):
        module = importlib.import_module("formation_tool.process_formation_slots_way_combined")
        groups = module.normalize_extra_weight_groups([
            {"group_id": "9652", "special_weight": "300", "free_weight": "150"},
            {"group_id": "9653", "special_weight": "400", "free_weight": "200"},
        ])

        group_ids = module.build_weight_group_ids(groups)

        self.assertIn(9652, group_ids)
        self.assertIn(9653, group_ids)
        self.assertIn(9650, group_ids)

    def test_extra_weight_groups_reject_conflicting_same_suffix_weights(self):
        module = importlib.import_module("formation_tool.process_formation_slots_way_combined")

        with self.assertRaisesRegex(ValueError, "尾号2"):
            module.normalize_extra_weight_groups([
                {"group_id": "9652", "special_weight": "300", "free_weight": "150"},
                {"group_id": "9002", "special_weight": "400", "free_weight": "150"},
            ])

    def test_extra_weight_groups_reject_default_suffixes(self):
        module = importlib.import_module("formation_tool.process_formation_slots_way_combined")

        with self.assertRaisesRegex(ValueError, "尾号0已是默认分组"):
            module.normalize_extra_weight_groups([
                {"group_id": "8750", "special_weight": "300", "free_weight": "150"},
            ])

    def test_group_weight_pairs_use_group_suffix_specific_rules(self):
        names = (
            "WEIGHT_GROUP_IDS",
            "GROUP_WEIGHT_MODES",
            "GROUP_WEIGHT_RULES",
            "GROUP_WEIGHT_GROUP_RULES",
            "ZERO_REBATE_INFERENCE_MODES",
            "BUY_GROUP_MODE",
            "is_extra_buy_mode",
            "get_extra_buy_group_by_mode",
            "get_group_weight_mode_name",
        )
        missing = object()
        old_values = {name: getattr(group_weight_builder, name, missing) for name in names}
        try:
            group_weight_builder.WEIGHT_GROUP_IDS = (9650, 9651, 9652)
            group_weight_builder.GROUP_WEIGHT_MODES = ("1",)
            group_weight_builder.GROUP_WEIGHT_RULES = {
                "1": [{"rebate_min": 0, "weight": 10}],
            }
            group_weight_builder.GROUP_WEIGHT_GROUP_RULES = {
                "1": {"1": [{"rebate_min": 0, "weight": 20}]},
                "2": {"1": [{"rebate_min": 0, "weight": 30}]},
            }
            group_weight_builder.ZERO_REBATE_INFERENCE_MODES = set()
            group_weight_builder.BUY_GROUP_MODE = "buy"
            group_weight_builder.is_extra_buy_mode = lambda _mode: False
            group_weight_builder.get_extra_buy_group_by_mode = lambda _mode: None
            group_weight_builder.get_group_weight_mode_name = lambda mode: mode

            with contextlib.redirect_stdout(io.StringIO()):
                mode_pairs = group_weight_builder.build_group_weight_pairs_for_modes(
                    ["1"],
                    {"1": [100, 200]},
                )
        finally:
            for name, value in old_values.items():
                if value is missing:
                    if hasattr(group_weight_builder, name):
                        delattr(group_weight_builder, name)
                else:
                    setattr(group_weight_builder, name, value)

        self.assertEqual(
            group_weight_pair_sets.get_pairs_for_mode_group(mode_pairs, "1", 9650),
            [(100, 10), (200, 10)],
        )
        self.assertEqual(
            group_weight_pair_sets.get_pairs_for_mode_group(mode_pairs, "1", 9651),
            [(100, 20), (200, 20)],
        )
        self.assertEqual(
            group_weight_pair_sets.get_pairs_for_mode_group(mode_pairs, "1", 9652),
            [(100, 30), (200, 30)],
        )

    def test_zero_weight_rows_are_built_for_final_write_only(self):
        names = (
            "WEIGHT_GROUP_IDS",
            "GROUP_WEIGHT_RULES",
            "BUY_GROUP_MODE",
            "get_group_weight_write_game_type",
            "is_extra_buy_mode",
            "get_extra_buy_group_by_mode",
        )
        missing = object()
        old_values = {
            name: getattr(group_weight_builder, name, missing)
            for name in names
        }
        try:
            group_weight_builder.WEIGHT_GROUP_IDS = (9000, 9001)
            group_weight_builder.GROUP_WEIGHT_RULES = {
                "1": [
                    {"rebate_min": 0, "weight": 0},
                    {"rebate_min": 1000, "weight": 5},
                    {"rebate_min": 5000, "weight": 0},
                ]
            }
            group_weight_builder.BUY_GROUP_MODE = "99"
            group_weight_builder.get_group_weight_write_game_type = lambda mode: int(mode)
            group_weight_builder.is_extra_buy_mode = lambda _mode: False
            group_weight_builder.get_extra_buy_group_by_mode = lambda _mode: None

            existing_rows = [(1, 9000, 0, 12), (1, 9000, 1000, 5)]
            with contextlib.redirect_stdout(io.StringIO()):
                rows = group_weight_builder.build_group_weight_zero_weight_write_rows(
                    ["1"],
                    rebates_by_mode={"1": [0, 1000, 5000]},
                    mode_exists={"1": True},
                    existing_rows=existing_rows,
                )
        finally:
            for name, value in old_values.items():
                if value is missing:
                    if hasattr(group_weight_builder, name):
                        delattr(group_weight_builder, name)
                else:
                    setattr(group_weight_builder, name, value)

        self.assertEqual(
            rows,
            [
                (1, 9000, 5000, 0),
                (1, 9001, 0, 0),
                (1, 9001, 5000, 0),
            ],
        )

    def test_original_normal_generation_does_not_add_zero_write_rows(self):
        original_modes = group_weight_builder.group_weight_original_modes
        names = (
            "WEIGHT_GROUP_IDS",
            "build_normal_group_weight_rows_for_group",
            "check_cancelled",
            "get_group_weight_write_game_type",
            "get_group_target_rtp_ratio",
        )
        old_values = {name: getattr(original_modes, name, None) for name in names}
        had_values = {name: hasattr(original_modes, name) for name in names}
        calls = []

        def fake_normal_builder(group_id, normal_pairs, free_rtp, free_enabled, special_rtp, special_enabled, **_kwargs):
            calls.append((group_id, tuple(normal_pairs), free_rtp, free_enabled, special_rtp, special_enabled))
            return [(1, int(group_id), 1000, 10)], {
                "group_id": int(group_id),
                "free_rate": 0,
                "special_rate": 0,
                "normal_target_rtp": 1,
                "zero_weight": 0,
                "actual_normal_rtp": 1,
            }

        try:
            original_modes.WEIGHT_GROUP_IDS = (9000,)
            original_modes.build_normal_group_weight_rows_for_group = fake_normal_builder
            original_modes.check_cancelled = lambda: None
            original_modes.get_group_weight_write_game_type = lambda game_type: int(game_type)
            original_modes.get_group_target_rtp_ratio = lambda _group_id: 1

            rows = []
            with contextlib.redirect_stdout(io.StringIO()):
                row_count = original_modes.append_original_normal_group_weight_rows(
                    rows,
                    rebates_by_mode={"1": [0, 1000]},
                    mode_exists={"1": True},
                    mode_pairs={"1": [(1000, 10)]},
                    trigger_context={
                        "free_rtp": 0,
                        "free_enabled": False,
                        "special_rtp": 0,
                        "special_enabled": False,
                    },
                )
        finally:
            for name in names:
                if had_values[name]:
                    setattr(original_modes, name, old_values[name])
                elif hasattr(original_modes, name):
                    delattr(original_modes, name)

        self.assertEqual(len(calls), 1)
        self.assertEqual(row_count, 1)
        self.assertEqual(rows, [(1, 9000, 1000, 10)])

    def test_normal_rows_use_trigger_rates_and_target_getter(self):
        rows, info = group_weight_logic.build_normal_group_weight_rows_for_group(
            9000,
            [(1000, 10)],
            free_rtp=2,
            free_enabled=True,
            special_rtp=3,
            special_enabled=True,
            free_rate_getter=lambda _group_id, enabled: 0.01 if enabled else 0,
            special_rate_getter=lambda _group_id, enabled: 0.02 if enabled else 0,
            target_rtp_getter=lambda _group_id: 1,
        )
        self.assertEqual(rows[0][:3], (1, 9000, 0))
        self.assertGreaterEqual(info["zero_weight"], 0)

    def test_default_buy_group_generation_uses_configured_game_type(self):
        missing = object()
        configured_modules = (
            group_weight_builder,
            group_weight_builder.group_weight_row_helpers,
            group_weight_builder.group_weight_original_modes,
            group_weight_builder.group_weight_buy_modes,
            group_weight_builder.group_weight_ex_modes,
            group_weight_builder.group_weight_preview,
        )
        configured_names = (
            "WEIGHT_GROUP_IDS",
            "BUY_GROUP_ENABLED",
            "BUY_GROUP_MODE",
            "GAME_TYPE_NAMES",
            "BUY_GROUP_MULTIPLIER",
            "EXTRA_BUY_GROUPS",
            "get_group_weight_write_game_type",
        )
        original_values = {
            module: {
                name: getattr(module, name, missing)
                for name in configured_names
            }
            for module in configured_modules
        }
        try:
            group_weight_builder.configure(
                WEIGHT_GROUP_IDS=(0,),
                BUY_GROUP_ENABLED=True,
                BUY_GROUP_MODE="99",
                GAME_TYPE_NAMES={"99": "buy"},
                BUY_GROUP_MULTIPLIER=75,
                EXTRA_BUY_GROUPS=[],
                get_group_weight_write_game_type=lambda _mode: 120,
            )

            rows = []
            with contextlib.redirect_stdout(io.StringIO()):
                group_weight_builder.append_buy_group_weight_modes(
                    rows,
                    rebates_by_mode={"99": [0, 1000]},
                    mode_exists={"99": True},
                    mode_pairs={"99": [(1000, 2)]},
                )

            self.assertEqual(rows, [(120, 0, 1000, 2)])
        finally:
            for module, values in original_values.items():
                for name, value in values.items():
                    if value is missing:
                        if hasattr(module, name):
                            delattr(module, name)
                    else:
                        setattr(module, name, value)


class GroupWeightRunnerWarningTests(unittest.TestCase):
    def test_collect_group_weight_generation_warnings_reports_runtime_risks(self):
        warnings = group_weight_runner.collect_group_weight_generation_warnings(
            {"active_modes": ["1", "2", "3"]},
            rebates_by_mode={"1": [1000], "2": [], "3": [5000]},
            mode_exists={"1": True, "2": True, "3": False},
            mode_pairs={"1": [], "2": [], "3": [(5000, 10)]},
            rows=[],
        )

        self.assertIn("没有可写入的 group_weight 行", warnings)
        self.assertIn("模式 1 按当前权重规则匹配后没有可写入的 rebate", warnings)
        self.assertIn("模式 2 的采样配置表为空或没有已选 rebate", warnings)
        self.assertIn("模式 3 对应的采样配置表不存在", warnings)

    def test_group_weight_generation_warnings_allow_zero_weight_only_rows(self):
        warnings = group_weight_runner.collect_group_weight_generation_warnings(
            {"active_modes": ["1"]},
            rebates_by_mode={"1": [0]},
            mode_exists={"1": True},
            mode_pairs={"1": []},
            rows=[(1, 9000, 0, 0)],
        )

        self.assertEqual(warnings, [])


class FakeCursor:
    def __init__(self, events):
        self.events = events

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=None):
        self.events.append(("execute", sql, params))

    def executemany(self, sql, rows):
        self.events.append(("executemany", sql, list(rows)))


class FakeConn:
    def __init__(self, events):
        self.events = events

    def cursor(self, *args, **kwargs):
        self.events.append(("cursor", args, kwargs))
        return FakeCursor(self.events)

    def commit(self):
        self.events.append("commit")


class GroupWeightStorageTests(unittest.TestCase):
    def build_replace_deps(self, events, *, staging_count):
        callbacks = SimpleNamespace(
            make_staging_table_name=lambda table, suffix: f"{table}_{suffix}",
            drop_table_if_exists=lambda _conn, table: events.append(("drop", table)),
            create_group_weight_table_if_needed=lambda _conn, table: events.append(("create", table)),
            quote_identifier=lambda value, _label=None: f"`{value}`",
            count_table_rows=lambda _conn, table: (events.append(("count", table)) or staging_count),
            replace_table_with_staging=lambda _conn, staging, table, db: events.append(("replace", staging, table, db)),
            rollback_safely=lambda _conn: events.append("rollback"),
            suppress_exceptions=lambda: contextlib.suppress(Exception),
        )
        return group_weight_entrypoints.build_storage_replace_deps(callbacks)

    def test_entrypoints_return_typed_group_weight_deps(self):
        events = []
        replace_deps = self.build_replace_deps(events, staging_count=0)
        verify_deps = group_weight_entrypoints.build_storage_verify_deps(
            SimpleNamespace(quote_identifier=lambda value, *_args: value),
            {"1": "普通局"},
        )

        self.assertIsInstance(replace_deps, group_weight_entrypoints.StorageReplaceDeps)
        self.assertIsInstance(verify_deps, group_weight_entrypoints.StorageVerifyDeps)
        self.assertEqual(verify_deps.game_type_names, {"1": "普通局"})

    def test_runner_entrypoints_return_typed_group_weight_deps(self):
        callbacks = SimpleNamespace(
            check_cancelled=lambda: None,
            get_group_weight_table_name=lambda: "group_weight",
            get_group_weight_formation_exists=lambda: {"1": True},
            get_active_group_weight_modes=lambda _exists: ["1"],
            build_group_weight_generation_context=lambda: {},
            print_group_weight_generation_summary=lambda _context: None,
            connect_group_weight_databases=lambda *_args: (None, None),
            load_group_weight_generation_data=lambda *_args: ({}, {}, {}),
            load_group_weight_rebates_for_modes=lambda *_args: ({}, {}),
            build_group_weight_pairs_for_modes=lambda *_args: {},
            build_group_weight_zero_weight_write_rows=lambda *_args: [],
            build_normalized_group_weight_generation_rows=lambda *_args: [],
            build_group_weight_rows_from_loaded_data=lambda *_args: [],
            normalize_group_weight_rows=lambda rows: rows,
            write_group_weight_generation_rows=lambda *_args: 0,
            replace_group_weight_rows_atomically=lambda *_args: 0,
            verify_group_weight_zero_rebate_rows=lambda *_args: None,
            print_step_error=lambda *_args: None,
            rollback_safely=lambda *_args: None,
            close_safely=lambda *_args: None,
        )
        constants = SimpleNamespace(ex_group_modes=("6", "7", "8"), ex_purchase_mode="98")
        runtime_getters = SimpleNamespace(
            get_config_db=lambda: "CFG",
            get_final_db=lambda: "FINAL",
            get_ex_buy_group_enabled=lambda: True,
        )
        log_callbacks = SimpleNamespace(
            print_no_group_weight_rows=lambda: None,
            print_group_weight_validation_failed=lambda _error: None,
            print_replace_with_staging_notice=lambda _target: None,
            print_write_complete=lambda *_args: None,
        )

        deps = group_weight_entrypoints.build_runner_deps(
            callbacks,
            constants,
            runtime_getters,
            log_callbacks,
        )

        self.assertIsInstance(deps, group_weight_entrypoints.RunnerDeps)

    def test_rebate_loader_entrypoints_return_typed_deps(self):
        callbacks = SimpleNamespace(
            has_any_buy_group=lambda: True,
            build_preview_modes=lambda: ["1", "99"],
            get_group_weight_formation_exists=lambda: {"1": True},
            get_source_formation_check_error_for_mode=lambda _mode: None,
            get_group_weight_rebate_table_name=lambda mode: f"{mode}_rebate_count",
            get_group_weight_mode_name=lambda mode: f"mode{mode}",
            is_extra_buy_mode=lambda _mode: False,
            get_extra_buy_group_by_mode=lambda _mode: None,
            connect_to_database=lambda _db: object(),
            table_exists_exact=lambda *_args: True,
            read_rebate_config_values=lambda *_args: [],
            close_safely=lambda *_args: None,
            check_cancelled=lambda: None,
        )
        constants = SimpleNamespace(
            buy_group_mode="99",
            ex_purchase_mode="98",
            group_weight_modes=("1", "2", "3"),
        )
        runtime_getters = SimpleNamespace(
            get_config_db=lambda: "CFG",
            get_ex_buy_group_enabled=lambda: False,
            get_group_weight_rules=lambda: {},
            default_buy_group_weight_rules=lambda: [],
        )

        deps = group_weight_entrypoints.build_rebate_loader_deps(
            callbacks,
            constants,
            runtime_getters,
        )

        self.assertIsInstance(deps, group_weight_entrypoints.RebateLoaderDeps)
        self.assertEqual(deps.buy_group_mode, "99")
        self.assertEqual(deps.ex_purchase_mode, "98")

    def test_replace_group_weight_rows_atomically_replaces_after_count_check(self):
        events = []
        conn = FakeConn(events)
        rows = [(1, 9000, 0, 10), (1, 9000, 1000, 5)]
        written = group_weight_storage.replace_group_weight_rows_atomically(
            conn,
            "pg_100_group_weight",
            rows,
            "FINAL",
            deps=self.build_replace_deps(events, staging_count=len(rows)),
        )

        self.assertEqual(written, 2)
        self.assertIn(("drop", "pg_100_group_weight_tmp"), events)
        self.assertIn(("create", "pg_100_group_weight_tmp"), events)
        insert_events = [event for event in events if isinstance(event, tuple) and event[0] == "executemany"]
        self.assertEqual(len(insert_events), 1)
        self.assertEqual(insert_events[0][2], rows)
        self.assertIn(("count", "pg_100_group_weight_tmp"), events)
        self.assertIn(("replace", "pg_100_group_weight_tmp", "pg_100_group_weight", "FINAL"), events)
        self.assertIn("commit", events)

    def test_replace_group_weight_rows_atomically_rolls_back_and_drops_staging_on_count_mismatch(self):
        events = []
        conn = FakeConn(events)
        with self.assertRaises(RuntimeError):
            group_weight_storage.replace_group_weight_rows_atomically(
                conn,
                "pg_100_group_weight",
                [(1, 9000, 0, 10)],
                "FINAL",
                deps=self.build_replace_deps(events, staging_count=0),
            )

        self.assertIn("rollback", events)
        self.assertGreaterEqual(events.count(("drop", "pg_100_group_weight_tmp")), 2)
        self.assertNotIn(("replace", "pg_100_group_weight_tmp", "pg_100_group_weight", "FINAL"), events)

    def test_normalize_group_weight_rows_rejects_duplicate_write_keys(self):
        with self.assertRaisesRegex(ValueError, "重复 game_type/group_id/rebate"):
            group_weight_storage.normalize_group_weight_rows([
                (1, 9000, 0, 10),
                (1, 9000, 0, 20),
            ])


class BuyGroupConfigTests(unittest.TestCase):
    def test_build_game_type_config_map_normalizes_source_and_buy_kind(self):
        configs = game_type_config.build_game_type_config_map([
            (91, "special_formation", 1),
            (98, "ex_free_formation", 2),
        ])

        self.assertEqual(configs[91]["source_suffix"], "special_formation")
        self.assertEqual(configs[91]["is_buy"], 1)
        self.assertEqual(configs[98]["source_suffix"], "ex_free_formation")
        self.assertEqual(configs[98]["is_buy"], 2)

    def test_normalize_buy_kind_rejects_unknown_value(self):
        with self.assertRaisesRegex(ValueError, "0/1/2"):
            game_type_config.normalize_buy_kind(3)

    def test_build_buy_group_options_from_configs_filters_existing_sources(self):
        configs = game_type_config.build_game_type_config_map([
            (91, "special_formation", 1),
            (92, "buy2_special_formation", 1),
            (93, "buy3_special_formation", 1),
            (98, "ex_free_formation", 2),
            (99, "free_formation", 1),
        ])

        options = game_type_config.build_buy_group_options_from_configs(
            configs,
            current_buy_game_type=99,
            current_buy_multiplier=75,
            current_buy_source_suffix="free_formation",
            existing_extra_buy_groups=[{"game_type": 92, "multiplier": 65, "source_suffix": "old"}],
            existing_source_game_types={91, 92, 98, 99},
            default_buy_game_type=99,
        )

        self.assertEqual(options["default_buy"]["game_type"], 99)
        self.assertEqual(options["default_buy"]["source_suffix"], "free_formation")
        self.assertTrue(options["default_buy"]["enabled"])
        self.assertEqual(
            [(item["game_type"], item["multiplier"], item["source_suffix"]) for item in options["extra_buy_groups"]],
            [
                (91, 75, "special_formation"),
                (92, 65, "buy2_special_formation"),
            ],
        )
        self.assertTrue(options["ex_buy_enabled"])
        self.assertEqual(options["ex_buy"]["game_type"], 98)
        self.assertEqual(options["ex_buy"]["source_suffix"], "ex_free_formation")
        self.assertEqual(options["normal_buy_game_types"], [91, 92, 99])
        self.assertEqual(options["ex_buy_game_types"], [98])

    def test_source_game_type_checks_are_cached(self):
        class FakeCursorForExists:
            def __init__(self, events):
                self.events = events

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        class FakeConnForExists:
            def __init__(self, events):
                self.events = events

            def cursor(self, *args, **kwargs):
                return FakeCursorForExists(self.events)

        events = []
        cache = game_type_config_runtime.GameTypeConfigCache()
        configs = {
            91: {"game_type": 91, "source_suffix": "special_formation", "is_buy": 1},
            92: {"game_type": 92, "source_suffix": "missing_formation", "is_buy": 1},
        }

        def connect_to_database(db_name):
            events.append(("connect", db_name))
            return FakeConnForExists(events)

        def table_exists_exact(_conn, table_name):
            events.append(("exists", table_name))
            return "missing" not in table_name

        first_existing, first_skipped = game_type_config_runtime.get_existing_source_game_types(
            configs=configs,
            source_db="HX",
            table_prefix="jili_523_",
            cache=cache,
            connect_to_database=connect_to_database,
            table_exists_exact=table_exists_exact,
            close_safely=lambda _conn: events.append("close"),
        )
        second_existing, second_skipped = game_type_config_runtime.get_existing_source_game_types(
            configs=configs,
            source_db="HX",
            table_prefix="jili_523_",
            cache=cache,
            connect_to_database=connect_to_database,
            table_exists_exact=table_exists_exact,
            close_safely=lambda _conn: events.append("close"),
        )

        self.assertEqual(first_existing, {91})
        self.assertEqual(second_existing, {91})
        self.assertEqual(first_skipped, second_skipped)
        self.assertEqual(events.count(("connect", "HX")), 1)
        self.assertEqual(events.count(("exists", "jili_523_special_formation")), 1)

    def test_source_game_type_cache_can_be_forced_to_refresh(self):
        class FakeConnForExists:
            pass

        events = []
        cache = game_type_config_runtime.GameTypeConfigCache()
        configs = {
            91: {"game_type": 91, "source_suffix": "special_formation", "is_buy": 1},
        }

        def connect_to_database(db_name):
            events.append(("connect", db_name))
            return FakeConnForExists()

        def table_exists_exact(_conn, table_name):
            events.append(("exists", table_name))
            return True

        for force in (False, True):
            game_type_config_runtime.get_existing_source_game_types(
                configs=configs,
                source_db="HX",
                table_prefix="jili_523_",
                cache=cache,
                connect_to_database=connect_to_database,
                table_exists_exact=table_exists_exact,
                close_safely=lambda _conn: events.append("close"),
                force=force,
            )

        self.assertEqual(events.count(("connect", "HX")), 2)
        self.assertEqual(events.count(("exists", "jili_523_special_formation")), 2)

    def test_infer_rebate_rule_source_mode_from_buy_source_suffix(self):
        self.assertEqual(
            buy_group_config.infer_rebate_rule_source_mode("bonus_special_formation"),
            "2",
        )
        self.assertEqual(
            buy_group_config.infer_rebate_rule_source_mode("bonus_free_formation"),
            "3",
        )
        self.assertEqual(
            buy_group_config.infer_rebate_rule_source_mode("bonus_formation"),
            "1",
        )
        self.assertEqual(
            buy_group_config.infer_rebate_rule_source_mode("special_free_formation"),
            "2",
        )

    def test_build_buy_source_rebate_configs_skip_fixed_sources_and_infer_rules(self):
        base_game_configs = {
            "1": {
                "name": "normal",
                "table_config": {
                    "SOURCE_TABLE": {"name": "pg_100_formation", "database": "SRC"},
                    "FINAL_TABLE": {"name": "pg_100_formation", "database": "FINAL"},
                    "REBATE_CONFIG_TABLE": {"name": "pg_100_rebate_count", "database": "CFG"},
                },
                "sample_conditions": {"where_clause": "normal", "random_seed": 1},
            },
            "2": {
                "name": "special",
                "table_config": {
                    "SOURCE_TABLE": {"name": "pg_100_special_formation", "database": "SRC"},
                    "FINAL_TABLE": {"name": "pg_100_special_formation", "database": "FINAL"},
                    "REBATE_CONFIG_TABLE": {"name": "pg_100_rebate_special_count", "database": "CFG"},
                },
                "sample_conditions": {"where_clause": "special", "random_seed": 2},
            },
            "3": {
                "name": "free",
                "table_config": {
                    "SOURCE_TABLE": {"name": "pg_100_free_formation", "database": "SRC"},
                    "FINAL_TABLE": {"name": "pg_100_free_formation", "database": "FINAL"},
                    "REBATE_CONFIG_TABLE": {"name": "pg_100_rebate_free_count", "database": "CFG"},
                },
                "sample_conditions": {"where_clause": "free", "random_seed": 3},
            },
        }

        configs = buy_source_rebate_configs.build_buy_source_rebate_game_configs(
            table_prefix="pg_100_",
            source_db="SRC",
            final_db="FINAL",
            config_db="CFG",
            random_seed=108,
            base_game_configs=base_game_configs,
            buy_enabled=True,
            buy_game_type=99,
            buy_source_suffix="free_formation",
            extra_buy_groups=[
                {"game_type": 120, "source_suffix": "bonus_free_formation"},
                {"game_type": 121, "source_suffix": "bonus_special_formation"},
                {"game_type": 122, "source_suffix": "bonus_formation"},
            ],
        )

        self.assertNotIn("buy_source:free_formation", configs)
        self.assertEqual(configs["buy_source:bonus_free_formation"]["rule_source_mode"], "3")
        self.assertEqual(configs["buy_source:bonus_free_formation"]["sample_conditions"]["where_clause"], "free")
        self.assertEqual(configs["buy_source:bonus_special_formation"]["rule_source_mode"], "2")
        self.assertEqual(configs["buy_source:bonus_special_formation"]["sample_conditions"]["where_clause"], "special")
        self.assertEqual(configs["buy_source:bonus_formation"]["rule_source_mode"], "1")
        self.assertEqual(
            configs["buy_source:bonus_formation"]["table_config"]["REBATE_CONFIG_TABLE"]["name"],
            "pg_100_rebate_bonus_count",
        )

    def test_custom_buy_special_source_gets_sampling_tab_when_not_fixed_source(self):
        table_prefix, _game_defs, base_game_configs = runtime_config.build_game_configs(
            "jili",
            "523",
            "HX",
            "DB1",
            "MY",
            random_seed=108,
        )

        configs = buy_source_rebate_configs.build_buy_source_rebate_game_configs(
            table_prefix=table_prefix,
            source_db="HX",
            final_db="DB1",
            config_db="MY",
            random_seed=108,
            base_game_configs=base_game_configs,
            buy_enabled=True,
            buy_game_type=91,
            buy_source_suffix="special_formation",
            extra_buy_groups=[
                {"game_type": 92, "source_suffix": "buy1_special_formation"},
                {"game_type": 93, "source_suffix": "buy2_special_formation"},
            ],
        )

        self.assertNotIn("buy_source:special_formation", configs)
        self.assertIn("buy_source:buy1_special_formation", configs)
        self.assertIn("buy_source:buy2_special_formation", configs)
        self.assertEqual(configs["buy_source:buy1_special_formation"]["rule_source_mode"], "2")
        self.assertEqual(
            configs["buy_source:buy1_special_formation"]["table_config"]["SOURCE_TABLE"]["name"],
            "jili_523_buy1_special_formation",
        )
        self.assertEqual(
            configs["buy_source:buy1_special_formation"]["table_config"]["REBATE_CONFIG_TABLE"]["name"],
            "jili_523_rebate_buy1_special_count",
        )

    def test_extra_buy_groups_preserve_source_suffix(self):
        groups = buy_group_config.normalize_extra_buy_groups(
            [{"game_type": "120", "multiplier": "80", "source_suffix": "bonus_formation"}],
            group_modes=formation_modes.GROUP_WEIGHT_MODES,
            default_buy_rules=[{"rebate_min": 0, "weight": 1}],
            buy_group_mode=formation_modes.BUY_GROUP_MODE,
            default_buy_game_type=99,
            default_source_suffix="free_formation",
        )

        self.assertEqual(groups[0]["source_suffix"], "bonus_formation")
        self.assertEqual(groups[0]["game_type"], 120)

    def test_default_buy_game_type_can_change_and_free_99_for_extra_buy(self):
        groups = buy_group_config.normalize_extra_buy_groups(
            [{"game_type": "99", "multiplier": "80", "source_suffix": "bonus_formation"}],
            group_modes=formation_modes.GROUP_WEIGHT_MODES,
            default_buy_rules=[{"rebate_min": 0, "weight": 1}],
            buy_group_mode=formation_modes.BUY_GROUP_MODE,
            default_buy_game_type=120,
            default_source_suffix="free_formation",
        )

        self.assertEqual(groups[0]["game_type"], 99)
        self.assertEqual(
            buy_group_config.get_buy_group_game_type(
                "99",
                buy_group_game_type=120,
                extra_buy_groups=groups,
            ),
            120,
        )
        self.assertEqual(
            buy_group_config.get_buy_group_game_type(
                "extra_buy:99",
                buy_group_game_type=120,
                extra_buy_groups=groups,
            ),
            99,
        )

    def test_98_and_99_are_not_fixed_group_weight_types(self):
        groups = buy_group_config.normalize_extra_buy_groups(
            [
                {"game_type": "98", "multiplier": "70", "source_suffix": "bonus_ex_formation"},
                {"game_type": "99", "multiplier": "80", "source_suffix": "bonus_formation"},
            ],
            group_modes=formation_modes.GROUP_WEIGHT_MODES,
            default_buy_rules=[{"rebate_min": 0, "weight": 1}],
            buy_group_mode=formation_modes.BUY_GROUP_MODE,
            default_buy_game_type=120,
            default_source_suffix="free_formation",
        )

        self.assertEqual([group["game_type"] for group in groups], [98, 99])
        with self.assertRaisesRegex(ValueError, "内置局类型"):
            buy_group_config.normalize_extra_buy_groups(
                [{"game_type": "6", "multiplier": "80", "source_suffix": "bonus_formation"}],
                group_modes=formation_modes.GROUP_WEIGHT_MODES,
                default_buy_rules=[{"rebate_min": 0, "weight": 1}],
                buy_group_mode=formation_modes.BUY_GROUP_MODE,
                default_buy_game_type=120,
                default_source_suffix="free_formation",
            )

    def test_settings_migration_adds_buy_group_defaults(self):
        migrated = settings_logic.migrate_settings_data(
            {
                "version": 1,
                "group_weight_options": {
                    "buy_enabled": True,
                    "buy_multiplier": 75,
                    "extra_buy_groups": [{"game_type": 120, "multiplier": 80}],
                },
            }
        )

        group_options = migrated["group_weight_options"]
        self.assertEqual(migrated["version"], settings_logic.CURRENT_SETTINGS_VERSION)
        self.assertEqual(group_options["buy_game_type"], 99)
        self.assertEqual(group_options["buy_source_suffix"], "free_formation")
        self.assertEqual(group_options["independent_rtp_modes"], [])
        self.assertEqual(group_options["extra_weight_groups"], [])
        self.assertEqual(group_options["extra_buy_groups"][0]["source_suffix"], "free_formation")
        self.assertEqual(group_options["buy_groups"][0]["game_type"], 99)
        self.assertEqual(group_options["buy_groups"][1]["game_type"], 120)

    def test_settings_migration_prefers_unified_buy_groups(self):
        migrated = settings_logic.migrate_settings_data(
            {
                "version": 3,
                "group_weight_options": {
                    "buy_groups": [
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
                    ],
                },
            }
        )

        group_options = migrated["group_weight_options"]
        self.assertEqual(group_options["buy_game_type"], 91)
        self.assertEqual(group_options["buy_multiplier"], 45.0)
        self.assertEqual(group_options["buy_source_suffix"], "special_formation")
        self.assertEqual(group_options["extra_buy_groups"][0]["game_type"], 92)

    def test_active_modes_include_extra_buy_source_independently(self):
        extra_groups = [{"game_type": 120, "source_suffix": "bonus_formation"}]
        formation_exists = {"1": True, formation_modes.BUY_GROUP_MODE: False, "extra_buy:120": True}
        modes = formation_modes.get_active_group_weight_modes(
            formation_exists,
            buy_enabled=False,
            ex_buy_enabled=False,
            extra_buy_groups=extra_groups,
        )

        self.assertIn("1", modes)
        self.assertIn("extra_buy:120", modes)
        self.assertNotIn(formation_modes.BUY_GROUP_MODE, modes)


class ExGroupWeightSourceOverrideTests(unittest.TestCase):
    def test_buy_group_manual_suffix_controls_group_weight_rebate_table(self):
        module = importlib.import_module("formation_tool.process_formation_slots_way_combined")
        runtime = module.RUNTIME_STATE
        saved_runtime = {
            name: getattr(runtime, name)
            for name in (
                "vendor",
                "game_id",
                "source_db",
                "final_db",
                "config_db",
                "game_table_prefix",
                "game_defs",
                "game_configs",
                "buy_group_enabled",
                "buy_group_game_type",
                "buy_group_multiplier",
                "buy_group_source_suffix",
                "extra_buy_groups",
                "buy_groups",
            )
        }
        saved_loader = module.load_game_type_configs
        try:
            prefix, game_defs, game_configs = runtime_config.build_game_configs(
                "jili",
                "106",
                "XP1",
                "DB1",
                "MY",
                random_seed=108,
            )
            runtime.vendor = "jili"
            runtime.game_id = "106"
            runtime.source_db = "XP1"
            runtime.final_db = "DB1"
            runtime.config_db = "MY"
            runtime.game_table_prefix = prefix
            runtime.game_defs = game_defs
            runtime.game_configs = game_configs
            runtime.buy_group_enabled = True
            runtime.buy_group_game_type = 99
            runtime.buy_group_multiplier = 5
            runtime.buy_group_source_suffix = "formation"
            runtime.extra_buy_groups = []
            runtime.buy_groups = runtime.build_buy_groups()

            module.load_game_type_configs = lambda force=False: {
                1: {"game_type": 1, "source_suffix": "formation", "is_buy": 0},
                3: {"game_type": 3, "source_suffix": "free_formation", "is_buy": 0},
                99: {"game_type": 99, "source_suffix": "free_formation", "is_buy": 1},
            }

            self.assertEqual(module.get_buy_group_source_suffix_for_mode("99"), "formation")
            self.assertEqual(module.get_group_weight_rebate_table_name("99"), "jili_106_rebate_count")
            self.assertNotEqual(module.get_group_weight_rebate_table_name("99"), "jili_106_rebate_free_count")
        finally:
            module.load_game_type_configs = saved_loader
            for name, value in saved_runtime.items():
                setattr(runtime, name, value)

    def test_ex_purchase_uses_manual_ex_buy_config_for_group_weight(self):
        module = importlib.import_module("formation_tool.process_formation_slots_way_combined")
        runtime = module.RUNTIME_STATE
        saved_runtime = {
            name: getattr(runtime, name)
            for name in (
                "vendor",
                "game_id",
                "source_db",
                "final_db",
                "config_db",
                "game_table_prefix",
                "game_defs",
                "game_configs",
                "ex_source_suffixes",
                "ex_buy_group_game_type",
                "ex_buy_group_source_suffix",
                "buy_group_enabled",
                "buy_group_game_type",
                "buy_group_multiplier",
                "buy_group_source_suffix",
                "extra_buy_groups",
                "buy_groups",
            )
        }
        saved_loader = module.load_game_type_configs
        try:
            prefix, game_defs, game_configs = runtime_config.build_game_configs(
                "jili",
                "106",
                "XP1",
                "DB1",
                "MY",
                random_seed=108,
            )
            runtime.vendor = "jili"
            runtime.game_id = "106"
            runtime.source_db = "XP1"
            runtime.final_db = "DB1"
            runtime.config_db = "MY"
            runtime.game_table_prefix = prefix
            runtime.game_defs = game_defs
            runtime.game_configs = game_configs
            runtime.ex_source_suffixes = {"8": "ex_free_formation"}
            runtime.ex_buy_group_game_type = 198
            runtime.ex_buy_group_source_suffix = "formation"
            runtime.buy_group_enabled = False
            runtime.buy_group_game_type = 99
            runtime.buy_group_multiplier = 75
            runtime.buy_group_source_suffix = "free_formation"
            runtime.extra_buy_groups = []
            runtime.buy_groups = runtime.build_buy_groups()

            module.load_game_type_configs = lambda force=False: {
                8: {"game_type": 8, "source_suffix": "ex_free_formation", "is_buy": 0},
                98: {"game_type": 98, "source_suffix": "ex_free_formation", "is_buy": 2},
            }

            self.assertEqual(module.get_buy_group_source_suffix_for_mode("98"), "formation")
            self.assertEqual(module.get_group_weight_write_game_type("98"), 198)
            self.assertEqual(module.get_group_weight_rebate_table_name("98"), "jili_106_rebate_count")
            self.assertNotEqual(module.get_group_weight_rebate_table_name("98"), "jili_106_rebate_ex_free_count")
        finally:
            module.load_game_type_configs = saved_loader
            for name, value in saved_runtime.items():
                setattr(runtime, name, value)

    def test_ex_purchase_uses_configured_game_type_for_table_driven_suffix(self):
        module = importlib.import_module("formation_tool.process_formation_slots_way_combined")
        runtime = module.RUNTIME_STATE
        saved_runtime = {
            name: getattr(runtime, name)
            for name in (
                "vendor",
                "game_id",
                "source_db",
                "final_db",
                "config_db",
                "game_table_prefix",
                "game_defs",
                "game_configs",
                "ex_source_suffixes",
                "ex_buy_group_game_type",
                "ex_buy_group_source_suffix",
                "buy_group_enabled",
                "buy_group_game_type",
                "buy_group_multiplier",
                "buy_group_source_suffix",
                "extra_buy_groups",
                "buy_groups",
            )
        }
        saved_loader = module.load_game_type_configs
        try:
            prefix, game_defs, game_configs = runtime_config.build_game_configs(
                "jili",
                "106",
                "XP1",
                "DB1",
                "MY",
                random_seed=108,
            )
            runtime.vendor = "jili"
            runtime.game_id = "106"
            runtime.source_db = "XP1"
            runtime.final_db = "DB1"
            runtime.config_db = "MY"
            runtime.game_table_prefix = prefix
            runtime.game_defs = game_defs
            runtime.game_configs = game_configs
            runtime.ex_source_suffixes = {"8": "ex_free_formation"}
            runtime.ex_buy_group_game_type = 198
            runtime.ex_buy_group_source_suffix = ""
            runtime.buy_group_enabled = False
            runtime.buy_group_game_type = 97
            runtime.buy_group_multiplier = 75
            runtime.buy_group_source_suffix = "free_formation"
            runtime.extra_buy_groups = []
            runtime.buy_groups = runtime.build_buy_groups()

            module.load_game_type_configs = lambda force=False: {
                98: {"game_type": 98, "source_suffix": "ex_free_formation", "is_buy": 2},
                198: {"game_type": 198, "source_suffix": "formation", "is_buy": 2},
            }

            self.assertEqual(
                module.get_buy_group_source_suffix_for_mode(module.EX_PURCHASE_MODE),
                "formation",
            )
            self.assertEqual(module.get_group_weight_write_game_type(module.EX_PURCHASE_MODE), 198)
            self.assertEqual(
                module.get_group_weight_rebate_table_name(module.EX_PURCHASE_MODE),
                "jili_106_rebate_count",
            )
            self.assertEqual(module.get_group_weight_write_game_type("98"), 198)
        finally:
            module.load_game_type_configs = saved_loader
            for name, value in saved_runtime.items():
                setattr(runtime, name, value)

    def test_manual_ex_suffix_affects_group_weight_only_not_sampling_configs(self):
        module = importlib.import_module("formation_tool.process_formation_slots_way_combined")
        runtime = module.RUNTIME_STATE
        saved_runtime = {
            name: getattr(runtime, name)
            for name in (
                "vendor",
                "game_id",
                "source_db",
                "final_db",
                "config_db",
                "game_table_prefix",
                "game_defs",
                "game_configs",
                "ex_source_suffixes",
                "buy_group_enabled",
                "buy_group_game_type",
                "buy_group_multiplier",
                "buy_group_source_suffix",
                "extra_buy_groups",
                "buy_groups",
            )
        }
        saved_loader = module.load_game_type_configs
        try:
            prefix, game_defs, game_configs = runtime_config.build_game_configs(
                "jili",
                "106",
                "XP1",
                "DB1",
                "MY",
                random_seed=108,
            )
            runtime.vendor = "jili"
            runtime.game_id = "106"
            runtime.source_db = "XP1"
            runtime.final_db = "DB1"
            runtime.config_db = "MY"
            runtime.game_table_prefix = prefix
            runtime.game_defs = game_defs
            runtime.game_configs = game_configs
            runtime.ex_source_suffixes = {"6": "formation"}
            runtime.buy_group_enabled = False
            runtime.buy_group_game_type = 99
            runtime.buy_group_multiplier = 75
            runtime.buy_group_source_suffix = "free_formation"
            runtime.extra_buy_groups = []
            runtime.buy_groups = runtime.build_buy_groups()

            module.load_game_type_configs = lambda force=False: {
                1: {"game_type": 1, "source_suffix": "formation", "is_buy": 0},
                6: {"game_type": 6, "source_suffix": "db_ex_formation", "is_buy": 0},
            }

            configs = module.get_runtime_game_configs()

            self.assertEqual(
                configs["6"]["table_config"]["SOURCE_TABLE"]["name"],
                "jili_106_db_ex_formation",
            )
            self.assertEqual(
                configs["6"]["table_config"]["REBATE_CONFIG_TABLE"]["name"],
                "jili_106_rebate_db_ex_count",
            )
            self.assertEqual(module.get_group_weight_rebate_table_name("6"), "jili_106_rebate_count")
            self.assertEqual(module.get_group_weight_manual_source_table_name("6"), "jili_106_formation")
        finally:
            module.load_game_type_configs = saved_loader
            for name, value in saved_runtime.items():
                setattr(runtime, name, value)

    def test_manual_ex_suffix_enables_group_weight_detection(self):
        module = importlib.import_module("formation_tool.process_formation_slots_way_combined")
        runtime = module.RUNTIME_STATE
        saved_runtime = {
            name: getattr(runtime, name)
            for name in (
                "source_db",
                "game_table_prefix",
                "game_configs",
                "ex_source_suffixes",
                "extra_buy_groups",
            )
        }
        saved_globals = {
            "GROUP_WEIGHT_MODES": module.GROUP_WEIGHT_MODES,
            "SOURCE_FORMATION_CHECK_STATUSES": dict(module.SOURCE_FORMATION_CHECK_STATUSES),
        }
        saved_funcs = {
            "connect_to_database": module.connect_to_database,
            "table_exists_exact": module.table_exists_exact,
            "close_safely": module.close_safely,
        }
        checked_tables = []
        try:
            runtime.source_db = "XP1"
            runtime.game_table_prefix = "jili_106_"
            runtime.game_configs = {
                "1": {
                    "name": "normal",
                    "table_config": {
                        "SOURCE_TABLE": {"name": "jili_106_formation", "database": "XP1"},
                    },
                },
                "6": {
                    "name": "ex normal",
                    "table_config": {
                        "SOURCE_TABLE": {"name": "jili_106_ex_formation", "database": "XP1"},
                    },
                },
            }
            runtime.ex_source_suffixes = {"6": "formation"}
            runtime.extra_buy_groups = []
            module.GROUP_WEIGHT_MODES = ("6",)
            module.connect_to_database = lambda db_name: object()

            def fake_table_exists(_conn, table_name):
                checked_tables.append(table_name)
                return table_name == "jili_106_formation"

            module.table_exists_exact = fake_table_exists
            module.close_safely = lambda _conn: None

            formation_exists = module.get_group_weight_formation_exists()

            self.assertTrue(formation_exists["6"])
            self.assertEqual(checked_tables, ["jili_106_formation"])
        finally:
            module.GROUP_WEIGHT_MODES = saved_globals["GROUP_WEIGHT_MODES"]
            module.SOURCE_FORMATION_CHECK_STATUSES.clear()
            module.SOURCE_FORMATION_CHECK_STATUSES.update(saved_globals["SOURCE_FORMATION_CHECK_STATUSES"])
            for name, value in saved_funcs.items():
                setattr(module, name, value)
            for name, value in saved_runtime.items():
                setattr(runtime, name, value)


class RuntimeContextSyncTests(unittest.TestCase):
    def test_wrappers_install_on_module_like_namespace(self):
        module = SimpleNamespace(ping=lambda: "pong")
        namespace = SimpleNamespace()
        runtime_context_sync.install_direct_wrappers(namespace, module, ("ping",))
        self.assertEqual(namespace.ping(), "pong")

    def test_configure_rejects_unknown_keys(self):
        with self.assertRaises(KeyError):
            sampling_core.configure(unknown_key=True)
        with self.assertRaises(KeyError):
            group_weight_builder.configure(unknown_key=True)

    def test_runtime_state_sync_uses_namespace_getter(self):
        calls = []
        runtime_state = SimpleNamespace(
            sync_database_from=lambda namespace: calls.append(("database", namespace.value)),
            sync_all_from=lambda namespace: calls.append(("all", namespace.value)),
            to_legacy_globals=lambda target: setattr(target, "copied", target.value + 1),
        )
        namespace_getter = lambda: SimpleNamespace(value=7)

        runtime_state_sync.sync_database_runtime_state_from_globals(runtime_state, namespace_getter)
        runtime_state_sync.sync_runtime_state_from_globals(runtime_state, namespace_getter)
        snapshot = runtime_state_sync.build_legacy_globals_snapshot(runtime_state, namespace_getter)

        self.assertEqual(calls, [("database", 7), ("all", 7)])
        self.assertEqual(snapshot.copied, 8)


class RebateConfigLogicTests(unittest.TestCase):
    def test_rebate_config_rows_preview_summarizes_generated_rows(self):
        preview = rebate_config_runner.build_rebate_config_rows_preview([
            (0, 20000),
            (1000, 200),
            (500000, 5),
        ])

        self.assertIn("行数=3", preview)
        self.assertIn("count合计=20205", preview)
        self.assertIn("rebate=0行=1", preview)
        self.assertIn("最大rebate=500000", preview)

    def test_count_limits_truncate_zero_and_positive_rebates(self):
        messages = []
        rows = rebate_config_logic.apply_rebate_config_count_limits_to_rows(
            [(0, 50000), (1000, 800), (-1, 12)],
            {"rebate_zero": 20000, "rebate_positive": 200},
            "普通局",
            print_fn=messages.append,
        )

        self.assertEqual(rows, [(0, 20000), (1000, 200), (-1, 12)])
        self.assertEqual(len([msg for msg in messages if "count上限" in msg]), 2)

    def test_direct_rebate_rows_then_limits_support_low_volume_flow(self):
        pd = importlib.import_module("pandas")
        stats_df = pd.DataFrame([
            {"rebate": 0, "total": 30000},
            {"rebate": 500, "total": 350},
            {"rebate": 1000, "total": 0},
        ])

        direct_rows = rebate_config_logic.build_direct_rebate_config_rows(
            stats_df,
            print_fn=lambda *_args: None,
        )
        limited_rows = rebate_config_logic.apply_rebate_config_count_limits_to_rows(
            direct_rows,
            {"rebate_zero": 20000, "rebate_positive": 200},
            print_fn=lambda *_args: None,
        )

        self.assertEqual(direct_rows, [(0, 30000), (500, 350)])
        self.assertEqual(limited_rows, [(0, 20000), (500, 200)])

    def test_direct_count_tier_limits_reduce_high_rebate_counts(self):
        messages = []
        rows = rebate_config_logic.apply_direct_count_tier_limits_to_rows(
            [(0, 30000), (500, 350), (1000, 300), (20000, 300), (50000, 300)],
            {
                "direct_count_tiers": [
                    {"rebate": 0, "count": 20000},
                    {"rebate_min": 1, "rebate_max": 999, "count": 200},
                    {"rebate_min": 1000, "rebate_max": 9999, "count": 100},
                    {"rebate_min": 10000, "rebate_max": 49999, "count": 20},
                    {"rebate_min": 50000, "rebate_max": 500000, "count": 5},
                ],
            },
            "普通局",
            print_fn=messages.append,
        )

        self.assertEqual(rows, [(0, 20000), (500, 200), (1000, 100), (20000, 20), (50000, 5)])
        self.assertEqual(len([msg for msg in messages if "直接计数阶梯" in msg]), 6)

    def test_rule_based_rebate_rows_then_limits_support_all_generation_flow(self):
        pd = importlib.import_module("pandas")
        stats_df = pd.DataFrame([
            {"rebate": 0, "total": 50000},
            {"rebate": 1000, "total": 1000},
            {"rebate": 2000, "total": 120},
        ])
        rules = [
            {"rebate": 0, "count": 50000},
            {"rebate_min": 1, "rebate_max": 9999, "count": 500, "min_total": 1},
        ]

        rule_rows = rebate_config_logic.build_rule_based_rebate_config_rows(
            stats_df,
            rules,
            print_fn=lambda *_args: None,
        )
        limited_rows = rebate_config_logic.apply_rebate_config_count_limits_to_rows(
            rule_rows,
            {"rebate_zero": 20000, "rebate_positive": 200},
            print_fn=lambda *_args: None,
        )

        self.assertEqual(rule_rows, [(0, 50000), (1000, 500), (2000, 120)])
        self.assertEqual(limited_rows, [(0, 20000), (1000, 200), (2000, 120)])

    def test_rule_based_rebate_rows_keep_results_and_detail_skipped_rows(self):
        pd = importlib.import_module("pandas")
        stats_df = pd.DataFrame([
            {"rebate": 0, "total": 100},
            {"rebate": 1000, "total": 20},
            {"rebate": 2000, "total": 1},
        ])
        normal_messages = []
        detail_messages = []

        rows = rebate_config_logic.build_rule_based_rebate_config_rows(
            stats_df,
            [{"rebate": 0, "count": 10}],
            print_fn=normal_messages.append,
            detail_print_fn=detail_messages.append,
        )

        self.assertEqual(rows, [(0, 10)])
        self.assertTrue(any("           0" in message and "        10" in message for message in normal_messages))
        self.assertFalse(any("跳过" in message for message in normal_messages))
        self.assertEqual(len([message for message in detail_messages if "跳过" in message]), 2)

    def test_runner_build_rebate_rows_applies_limits_and_normalization(self):
        pd = importlib.import_module("pandas")
        stats_df = pd.DataFrame([
            {"rebate": 1000, "total": 1000},
            {"rebate": 0, "total": 50000},
        ])
        deps = SimpleNamespace(
            direct_count_modes=set(),
            build_direct_rebate_config_rows=rebate_config_logic.build_direct_rebate_config_rows,
            build_rule_based_rebate_config_rows=lambda _stats, _rules: [(1000, 500), (0, 50000)],
            apply_rebate_config_count_limits_to_rows=lambda rows, limits, label: rebate_config_logic.apply_rebate_config_count_limits_to_rows(
                rows,
                limits,
                label,
                print_fn=lambda *_args: None,
            ),
            normalize_rebate_config_rows=rebate_config_logic.normalize_rebate_config_rows,
        )

        rows = rebate_config_runner.build_rebate_config_rows(
            "1",
            {"name": "普通局"},
            stats_df,
            [{"rebate": 0, "count": 50000}],
            deps,
            {"rebate_zero": 20000, "rebate_positive": 200},
        )

        self.assertEqual(rows, [(0, 20000), (1000, 200)])


class RebateConfigRunnerTests(unittest.TestCase):
    def build_game_config(self):
        return {
            "name": "普通局",
            "table_config": {
                "SOURCE_TABLE": {"database": "SRC", "name": "src_formation"},
                "REBATE_CONFIG_TABLE": {"database": "CFG", "name": "rebate_count"},
            },
            "sample_conditions": {"where_clause": "rebate = {target_rebate}"},
        }

    def build_runner_deps(
        self,
        events,
        *,
        table_exists=True,
        write_result=True,
        direct_count_modes=None,
        end_field=None,
    ):
        conn = object()

        def close_safely(value):
            events.append(("close", value))

        def write_rows(_table_config, config_table, config_db, rows):
            events.append(("write", config_db, config_table, rows))
            return write_result

        return SimpleNamespace(
            check_cancelled=lambda: events.append("check"),
            get_table_database=lambda key, table_config: table_config[key]["database"],
            get_table_name=lambda key, table_config: table_config[key]["name"],
            connect_by_table=lambda _key, _table_config: conn,
            table_exists_exact=lambda _conn, _table: table_exists,
            resolve_rebate_config_game_condition=lambda *_args: "rebate >= 0",
            detect_end_field=lambda _conn, _table: end_field,
            close_safely=close_safely,
            get_engine_by_table=lambda *_args: "engine",
            quote_identifier=lambda value, _label=None: f"`{value}`",
            direct_count_modes=set(direct_count_modes or []),
            build_direct_rebate_config_rows=rebate_config_logic.build_direct_rebate_config_rows,
            apply_direct_count_tier_limits_to_rows=rebate_config_logic.apply_direct_count_tier_limits_to_rows,
            build_rule_based_rebate_config_rows=lambda _stats, _rules: [(0, 10), (1000, 5)],
            build_rebate_sql_filter=rebate_config_logic.build_rebate_sql_filter,
            apply_rebate_config_count_limits_to_rows=lambda rows, _limits, _label: rows,
            normalize_rebate_config_rows=rebate_config_logic.normalize_rebate_config_rows,
            write_rebate_config_rows=write_rows,
        )

    def run_generate_silently(self, deps, *, rules=None, count_limits=None):
        with contextlib.redirect_stdout(io.StringIO()):
            return rebate_config_runner.generate_rebate_config_for_game(
                "1",
                self.build_game_config(),
                rules or [{"rebate": 0, "count": 10}],
                deps=deps,
                count_limits=count_limits,
            )

    def test_generate_rebate_config_skips_when_source_table_missing(self):
        events = []
        deps = self.build_runner_deps(events, table_exists=False)

        result = self.run_generate_silently(deps)

        self.assertFalse(result)
        self.assertTrue(any(isinstance(event, tuple) and event[0] == "close" for event in events))
        self.assertFalse(any(isinstance(event, tuple) and event[0] == "write" for event in events))

    def test_generate_rebate_config_skips_when_stats_empty(self):
        events = []
        deps = self.build_runner_deps(events)
        pd = importlib.import_module("pandas")
        original_read_sql_query = rebate_config_runner.pd.read_sql_query
        try:
            rebate_config_runner.pd.read_sql_query = lambda *_args, **_kwargs: pd.DataFrame(columns=["rebate", "total"])
            result = self.run_generate_silently(deps)
        finally:
            rebate_config_runner.pd.read_sql_query = original_read_sql_query

        self.assertFalse(result)
        self.assertFalse(any(isinstance(event, tuple) and event[0] == "write" for event in events))

    def test_generate_rebate_config_returns_write_result(self):
        events = []
        deps = self.build_runner_deps(events, write_result=False)
        pd = importlib.import_module("pandas")
        original_read_sql_query = rebate_config_runner.pd.read_sql_query
        try:
            rebate_config_runner.pd.read_sql_query = lambda *_args, **_kwargs: pd.DataFrame([
                {"rebate": 0, "total": 100},
                {"rebate": 1000, "total": 10},
            ])
            result = self.run_generate_silently(deps)
        finally:
            rebate_config_runner.pd.read_sql_query = original_read_sql_query

        self.assertFalse(result)
        self.assertIn(("write", "CFG", "rebate_count", [(0, 10), (1000, 5)]), events)

    def test_generate_rebate_config_uses_count_star_when_source_has_no_end_field(self):
        events = []
        deps = self.build_runner_deps(events, end_field=None)
        captured = []
        pd = importlib.import_module("pandas")
        original_read_sql_query = rebate_config_runner.pd.read_sql_query
        try:
            def fake_read_sql_query(query, _engine):
                captured.append(query)
                return pd.DataFrame([{"rebate": 0, "total": 100}])

            rebate_config_runner.pd.read_sql_query = fake_read_sql_query
            result = self.run_generate_silently(deps)
        finally:
            rebate_config_runner.pd.read_sql_query = original_read_sql_query

        self.assertTrue(result)
        self.assertTrue(captured)
        self.assertIn("COUNT(*) AS total", captured[0])
        self.assertNotIn("COUNT(DISTINCT `id`)", captured[0])

    def test_generate_rebate_config_keeps_distinct_id_when_source_has_end_field(self):
        events = []
        deps = self.build_runner_deps(events, end_field="game_end")
        captured = []
        pd = importlib.import_module("pandas")
        original_read_sql_query = rebate_config_runner.pd.read_sql_query
        try:
            def fake_read_sql_query(query, _engine):
                captured.append(query)
                return pd.DataFrame([{"rebate": 0, "total": 100}])

            rebate_config_runner.pd.read_sql_query = fake_read_sql_query
            result = self.run_generate_silently(deps)
        finally:
            rebate_config_runner.pd.read_sql_query = original_read_sql_query

        self.assertTrue(result)
        self.assertTrue(captured)
        self.assertIn("COUNT(DISTINCT `id`) AS total", captured[0])

    def test_generate_direct_count_config_applies_tier_limits(self):
        events = []
        deps = self.build_runner_deps(events, direct_count_modes={"1"})
        pd = importlib.import_module("pandas")
        original_read_sql_query = rebate_config_runner.pd.read_sql_query
        try:
            rebate_config_runner.pd.read_sql_query = lambda *_args, **_kwargs: pd.DataFrame([
                {"rebate": 0, "total": 30000},
                {"rebate": 500, "total": 350},
                {"rebate": 1000, "total": 300},
                {"rebate": 20000, "total": 300},
                {"rebate": 50000, "total": 300},
            ])
            result = self.run_generate_silently(
                deps,
                count_limits={
                    "direct_count_tiers": [
                        {"rebate": 0, "count": 20000},
                        {"rebate_min": 1, "rebate_max": 999, "count": 200},
                        {"rebate_min": 1000, "rebate_max": 9999, "count": 100},
                        {"rebate_min": 10000, "rebate_max": 49999, "count": 20},
                        {"rebate_min": 50000, "rebate_max": 500000, "count": 5},
                    ],
                },
            )
        finally:
            rebate_config_runner.pd.read_sql_query = original_read_sql_query

        self.assertTrue(result)
        write_events = [event for event in events if isinstance(event, tuple) and event[0] == "write"]
        self.assertEqual(
            write_events[-1][3],
            [(0, 20000), (500, 200), (1000, 100), (20000, 20), (50000, 5)],
        )

    def test_generate_rebate_config_pushes_rebate_limits_into_stats_sql(self):
        events = []
        deps = self.build_runner_deps(events)
        pd = importlib.import_module("pandas")
        captured = {}
        original_read_sql_query = rebate_config_runner.pd.read_sql_query
        try:
            def fake_read_sql_query(query, *_args, **_kwargs):
                captured["query"] = query
                return pd.DataFrame([
                    {"rebate": 0, "total": 100},
                    {"rebate": 1000, "total": 10},
                ])

            rebate_config_runner.pd.read_sql_query = fake_read_sql_query
            result = self.run_generate_silently(
                deps,
                rules=[
                    {"rebate": 0, "count": 10},
                    {"rebate_min": 1, "rebate_max": 999999, "count": 5},
                ],
                count_limits={"max_rebate": 500000},
            )
        finally:
            rebate_config_runner.pd.read_sql_query = original_read_sql_query

        self.assertTrue(result)
        self.assertIn("rebate >= 0", captured["query"])
        self.assertIn("`rebate` BETWEEN 0 AND 500000", captured["query"])


class RebateConfigStorageTests(unittest.TestCase):
    def build_replace_deps(self, events, *, staging_count, replace_error=None):
        def replace_table(_conn, staging, table, db):
            events.append(("replace", staging, table, db))
            if replace_error is not None:
                raise replace_error

        return SimpleNamespace(
            make_staging_table_name=lambda table, suffix: f"{table}_{suffix}",
            drop_table_if_exists=lambda _conn, table: events.append(("drop", table)),
            create_rebate_config_table_if_needed=lambda _conn, table: events.append(("create", table)),
            quote_identifier=lambda value, _label=None: f"`{value}`",
            count_table_rows=lambda _conn, table: (events.append(("count", table)) or staging_count),
            replace_table_with_staging=replace_table,
            rollback_safely=lambda _conn: events.append("rollback"),
            suppress_exceptions=lambda: contextlib.suppress(Exception),
        )

    def test_replace_rebate_config_rows_atomically_cleans_staging_when_replace_fails(self):
        events = []
        conn = FakeConn(events)
        rows = [(0, 10), (1000, 5)]
        with self.assertRaisesRegex(RuntimeError, "rename failed"):
            rebate_config_storage.replace_rebate_config_rows_atomically(
                conn,
                "rebate_count",
                rows,
                "CFG",
                deps=self.build_replace_deps(
                    events,
                    staging_count=len(rows),
                    replace_error=RuntimeError("rename failed"),
                ),
            )

        self.assertIn(("create", "rebate_count_tmp"), events)
        self.assertIn(("count", "rebate_count_tmp"), events)
        self.assertIn(("replace", "rebate_count_tmp", "rebate_count", "CFG"), events)
        self.assertIn("rollback", events)
        self.assertGreaterEqual(events.count(("drop", "rebate_count_tmp")), 2)
        self.assertTrue(any(event[0] == "executemany" for event in events if isinstance(event, tuple)))

    def test_rebate_config_entrypoints_return_typed_deps(self):
        callbacks = SimpleNamespace(
            make_staging_table_name=lambda table, suffix: f"{table}_{suffix}",
            drop_table_if_exists=lambda *_args: None,
            create_rebate_config_table_if_needed=lambda *_args: None,
            quote_identifier=lambda value, *_args: value,
            count_table_rows=lambda *_args: 0,
            replace_table_with_staging=lambda *_args: None,
            rollback_safely=lambda *_args: None,
            suppress_exceptions=lambda: contextlib.suppress(Exception),
            connect_by_table=lambda *_args: None,
            replace_rebate_config_rows_atomically=lambda *_args: 0,
            print_write_complete=lambda *_args: None,
            print_step_error=lambda *_args: None,
            close_safely=lambda *_args: None,
        )
        runner_callbacks = SimpleNamespace(
            check_cancelled=lambda: None,
            get_table_database=lambda key, table_config: table_config[key]["database"],
            get_table_name=lambda key, table_config: table_config[key]["name"],
            connect_by_table=lambda *_args: None,
            close_safely=lambda *_args: None,
            table_exists_exact=lambda *_args: True,
            resolve_rebate_config_game_condition=lambda *_args: "1=1",
            get_engine_by_table=lambda *_args: None,
            quote_identifier=lambda value, *_args: value,
            build_direct_rebate_config_rows=lambda *_args: [],
            apply_direct_count_tier_limits_to_rows=lambda rows, *_args: rows,
            build_rule_based_rebate_config_rows=lambda *_args: [],
            build_rebate_sql_filter=lambda *_args, **_kwargs: None,
            apply_rebate_config_count_limits_to_rows=lambda rows, *_args: rows,
            normalize_rebate_config_rows=lambda rows, _name: rows,
            write_rebate_config_rows=lambda *_args: True,
        )

        self.assertIsInstance(
            rebate_config_entrypoints.build_storage_replace_deps(callbacks),
            rebate_config_entrypoints.StorageReplaceDeps,
        )
        self.assertIsInstance(
            rebate_config_entrypoints.build_write_rows_deps(callbacks),
            rebate_config_entrypoints.WriteRowsDeps,
        )
        runner_deps = rebate_config_entrypoints.build_runner_deps(
            runner_callbacks,
            SimpleNamespace(direct_count_modes={"1"}),
        )

        self.assertIsInstance(runner_deps, rebate_config_entrypoints.RunnerDeps)
        self.assertEqual(runner_deps.direct_count_modes, {"1"})


class DatabaseAccessTests(unittest.TestCase):
    def test_get_engine_preserves_special_characters_in_credentials(self):
        engine = db_runtime.get_engine({
            "user": "user:name",
            "password": "p@ss:word/with#chars",
            "host": "127.0.0.1",
            "port": "3306",
            "database": "formation_db",
        })

        try:
            self.assertEqual(engine.url.username, "user:name")
            self.assertEqual(engine.url.password, "p@ss:word/with#chars")
            self.assertEqual(engine.url.host, "127.0.0.1")
            self.assertEqual(engine.url.port, 3306)
            self.assertEqual(engine.url.database, "formation_db")
            self.assertEqual(engine.url.query["use_pure"], "True")
        finally:
            engine.dispose()

    def test_default_db_timeouts_are_applied_without_overriding_custom_values(self):
        defaulted = db_runtime.with_default_db_timeouts({})
        self.assertEqual(defaulted["connection_timeout"], 10)
        self.assertEqual(defaulted["read_timeout"], 300)
        self.assertEqual(defaulted["write_timeout"], 300)

        customized = db_runtime.with_default_db_timeouts({
            "connect_timeout": 7,
            "read_timeout": "30",
            "write_timeout": 40,
        })
        self.assertNotIn("connection_timeout", customized)
        self.assertEqual(customized["connect_timeout"], 7)
        self.assertEqual(customized["read_timeout"], 30)
        self.assertEqual(customized["write_timeout"], 40)

    def test_connect_to_db_hides_success_logs_unless_verbose(self):
        original_connect = db_runtime.mysql.connector.connect
        try:
            db_runtime.mysql.connector.connect = lambda **_kwargs: "conn"
            db_config = {
                "host": "127.0.0.1",
                "port": 3306,
                "user": "u",
                "password": "p",
                "database": "d",
            }

            quiet_output = io.StringIO()
            with contextlib.redirect_stdout(quiet_output):
                quiet_conn = db_runtime.connect_to_db(
                    db_config,
                    max_retries=1,
                    retry_delay=0,
                    check_cancelled=lambda: None,
                    sleep_func=lambda _seconds: None,
                )

            verbose_output = io.StringIO()
            with contextlib.redirect_stdout(verbose_output):
                verbose_conn = db_runtime.connect_to_db(
                    db_config,
                    max_retries=1,
                    retry_delay=0,
                    check_cancelled=lambda: None,
                    sleep_func=lambda _seconds: None,
                    verbose=True,
                )
        finally:
            db_runtime.mysql.connector.connect = original_connect

        self.assertEqual(quiet_conn, "conn")
        self.assertEqual(verbose_conn, "conn")
        self.assertNotIn("数据库连接成功", quiet_output.getvalue())
        self.assertIn("数据库连接成功", verbose_output.getvalue())

    def test_db_entrypoints_build_typed_database_access_callbacks(self):
        callbacks = db_entrypoints.DatabaseAccessCallbacks(
            get_database_configs=lambda: {"SRC": {"host": "127.0.0.1"}},
            get_engine=lambda _db_config: "engine",
            get_db_config_by_name=lambda name: {"name": name},
            connect_to_db=lambda db_config: ("conn", db_config),
            connect_to_database=lambda _name: None,
            close_safely=lambda _conn: None,
        )

        deps = db_entrypoints.build_database_access_deps(callbacks)
        conn = formation_db_access.connect_to_database("SRC", deps=deps)

        self.assertEqual(conn, ("conn", {"name": "SRC"}))

    def test_table_operation_deps_delegate_to_table_ops(self):
        events = []

        class FakeCursor:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, sql):
                events.append(sql)

        class FakeConn:
            def cursor(self):
                return FakeCursor()

        deps = db_entrypoints.TableOperationDeps(
            quote_identifier=lambda value, *_args: f"`{value}`",
            chunked=lambda values: [values],
            make_staging_table_name=lambda table, suffix: f"{table}_{suffix}",
            drop_table_if_exists=lambda *_args: None,
            table_exists_exact=lambda *_args: False,
        )

        db_entrypoints.drop_table_if_exists(FakeConn(), "tmp_table", deps=deps)

        self.assertEqual(events, ["DROP TABLE IF EXISTS `tmp_table`"])

    def test_connect_to_database_uses_named_config(self):
        calls = []
        deps = formation_db_access.build_database_access_deps(
            get_database_configs=lambda: {"SRC": {"host": "127.0.0.1"}},
            get_engine=lambda _db_config: None,
            get_db_config_by_name=lambda name: {"name": name},
            connect_to_db=lambda db_config: calls.append(db_config) or "conn",
            connect_to_database=lambda _name: None,
            close_safely=lambda _conn: None,
        )

        conn = formation_db_access.connect_to_database("SRC", deps=deps)

        self.assertEqual(conn, "conn")
        self.assertEqual(calls, [{"name": "SRC"}])


class SamplingCoreWriteTests(unittest.TestCase):
    def test_sampling_config_normalization_rejects_invalid_rows(self):
        valid = sampling_core.normalize_sampling_config_df(
            sampling_core.pd.DataFrame([
                {"rebate": "0", "count": "10"},
                {"rebate": 1000, "count": 5},
            ]),
            "CFG",
            "rebate_count",
        )
        self.assertEqual(valid.to_dict("records"), [
            {"rebate": 0, "count": 10},
            {"rebate": 1000, "count": 5},
        ])

        with self.assertRaisesRegex(ValueError, "rebate 重复"):
            sampling_core.normalize_sampling_config_df(sampling_core.pd.DataFrame([
                {"rebate": 1000, "count": 10},
                {"rebate": 1000, "count": 5},
            ]))
        with self.assertRaisesRegex(ValueError, "count 必须大于 0"):
            sampling_core.normalize_sampling_config_df(sampling_core.pd.DataFrame([
                {"rebate": 1000, "count": 0},
            ]))
        with self.assertRaisesRegex(ValueError, "rebate 不能小于 0"):
            sampling_core.normalize_sampling_config_df(sampling_core.pd.DataFrame([
                {"rebate": -1, "count": 1},
            ]))
        with self.assertRaisesRegex(ValueError, "必须是整数"):
            sampling_core.normalize_sampling_config_df(sampling_core.pd.DataFrame([
                {"rebate": 1000.5, "count": 1},
            ]))

    def test_sampling_timing_records_slowest_rebate_breakdown(self):
        messages = []
        old_writer = log_utils._LOG_WRITER
        old_detailed_log = getattr(sampling_core, "SAMPLING_DETAILED_LOG", False)
        log_utils.set_log_writer(messages.append)
        sampling_core.SAMPLING_DETAILED_LOG = True
        timing = sampling_core.new_sampling_timing()
        before = sampling_core.snapshot_sampling_timing(timing)
        sampling_core.add_sampling_timing(timing, "id_query_seconds", 1.25)
        sampling_core.add_sampling_timing(timing, "row_read_seconds", 2.5)
        sampling_core.add_sampling_timing(timing, "row_write_seconds", 3.75)
        sampling_core.add_sampling_timing(timing, "id_remap_seconds", 0.5)
        try:
            sampling_core.record_rebate_timing(
                timing,
                time.perf_counter() - 8.0,
                row_count=20,
                target_rebate=1000,
                before=before,
            )
            sampling_core.print_sampling_timing_summary(timing)
        finally:
            sampling_core.SAMPLING_DETAILED_LOG = old_detailed_log
            log_utils.set_log_writer(old_writer)

        self.assertEqual(timing["rebate_details"][0]["rebate"], 1000)
        self.assertEqual(timing["rebate_details"][0]["row_count"], 20)
        self.assertAlmostEqual(timing["rebate_details"][0]["id_query_seconds"], 1.25)
        self.assertTrue(any("最慢rebate" in message for message in messages))
        self.assertTrue(any("rebate=1000" in message for message in messages))

    def test_id_queries_use_engine_connection_and_record_timing(self):
        calls = []

        class FakeResult:
            def __init__(self, rows):
                self.rows = rows

            def __iter__(self):
                return iter(self.rows)

            def fetchone(self):
                return self.rows[0] if self.rows else None

        class FakeConnection:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def exec_driver_sql(self, query):
                calls.append(("query", query))
                if "MIN" in query:
                    return FakeResult([(10, 90)])
                return FakeResult([(11,), (12,), (None,)])

        class FakeEngine:
            def connect(self):
                calls.append("connect")
                return FakeConnection()

        old_sql_with_retry = getattr(sampling_core, "sql_with_retry", None)
        had_sql_with_retry = hasattr(sampling_core, "sql_with_retry")
        sampling_core.sql_with_retry = lambda fn, label: calls.append(("retry", label)) or fn()
        timing = sampling_core.new_sampling_timing()
        try:
            ids = sampling_core._query_limited_distinct_ids(
                FakeEngine(),
                "`source_table`",
                "`rebate` = 1000",
                1000,
                3,
                timing=timing,
            )
            min_id, max_id = sampling_core._query_sample_id_range(
                FakeEngine(),
                "`source_table`",
                "`rebate` = 1000",
                1000,
                timing=timing,
            )
        finally:
            if had_sql_with_retry:
                sampling_core.sql_with_retry = old_sql_with_retry
            else:
                delattr(sampling_core, "sql_with_retry")

        self.assertEqual(ids, [11, 12])
        self.assertEqual((min_id, max_id), (10, 90))
        self.assertEqual(calls.count("connect"), 2)
        self.assertGreaterEqual(timing["id_query_seconds"], 0)

    def test_random_range_candidate_stats_record_attempts(self):
        calls = []

        class FakeResult:
            def __init__(self, rows):
                self.rows = rows

            def __iter__(self):
                return iter(self.rows)

        class FakeConnection:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def exec_driver_sql(self, query):
                calls.append(query)
                attempt = len(calls)
                return FakeResult([(attempt,), (attempt + 100,)])

        class FakeEngine:
            def connect(self):
                return FakeConnection()

        old_sql_with_retry = getattr(sampling_core, "sql_with_retry", None)
        had_sql_with_retry = hasattr(sampling_core, "sql_with_retry")
        old_check_cancelled = getattr(sampling_core, "check_cancelled", None)
        had_check_cancelled = hasattr(sampling_core, "check_cancelled")
        sampling_core.sql_with_retry = lambda fn, label: fn()
        sampling_core.check_cancelled = lambda: None
        timing = sampling_core.new_sampling_timing()
        try:
            ids = sampling_core._query_candidate_ids_from_random_ranges(
                source_engine=FakeEngine(),
                source_table_ref="`source_table`",
                where_clause="`rebate` = 1000",
                target_rebate=1000,
                sample_size=5,
                random_seed=123,
                min_id=1,
                max_id=100,
                timing=timing,
            )
        finally:
            if had_sql_with_retry:
                sampling_core.sql_with_retry = old_sql_with_retry
            else:
                delattr(sampling_core, "sql_with_retry")
            if had_check_cancelled:
                sampling_core.check_cancelled = old_check_cancelled
            else:
                delattr(sampling_core, "check_cancelled")

        self.assertGreaterEqual(len(ids), 5)
        self.assertEqual(timing["random_range_attempts"], 3)
        self.assertEqual(timing["random_range_returned_ids"], 6)
        self.assertEqual(timing["random_range_added_ids"], 6)
        self.assertEqual(timing["random_range_duplicate_ids"], 0)

    def test_random_range_attempts_and_limits_scale_with_sample_size(self):
        self.assertEqual(
            sampling_core._random_range_attempt_limit(200),
            sampling_core.SAMPLE_ID_RANDOM_RANGE_ATTEMPTS,
        )
        self.assertGreater(
            sampling_core._random_range_attempt_limit(1000),
            sampling_core.SAMPLE_ID_RANDOM_RANGE_ATTEMPTS,
        )
        self.assertGreater(
            sampling_core._random_range_per_query_limit(1000, sampling_core.SAMPLE_ID_RANDOM_RANGE_ATTEMPTS + 4),
            sampling_core._random_range_per_query_limit(1000, 1),
        )

    def test_select_sample_ids_records_full_scan_fallback(self):
        class FakeResult:
            def __init__(self, rows):
                self.rows = rows

            def __iter__(self):
                return iter(self.rows)

            def fetchone(self):
                return self.rows[0] if self.rows else None

        class FakeConnection:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def exec_driver_sql(self, query):
                if "MIN(`id`)" in query:
                    return FakeResult([(1, 100)])
                if "ORDER BY `id`" in query:
                    return FakeResult([(1,)])
                if "LIMIT" in query:
                    return FakeResult([(1,), (2,), (3,)])
                return FakeResult([(4,), (5,), (6,)])

        class FakeEngine:
            def connect(self):
                return FakeConnection()

        old_sql_with_retry = getattr(sampling_core, "sql_with_retry", None)
        had_sql_with_retry = hasattr(sampling_core, "sql_with_retry")
        old_check_cancelled = getattr(sampling_core, "check_cancelled", None)
        had_check_cancelled = hasattr(sampling_core, "check_cancelled")
        sampling_core.sql_with_retry = lambda fn, label: fn()
        sampling_core.check_cancelled = lambda: None
        timing = sampling_core.new_sampling_timing()
        try:
            ids = sampling_core.select_sample_ids_for_rebate(
                source_engine=FakeEngine(),
                source_db_name="SRC",
                source_table_ref="`source_table`",
                sample_conditions={
                    "where_clause": "`rebate` = {target_rebate}",
                    "random_seed": 123,
                },
                target_rebate=1000,
                sample_size=2,
                timing=timing,
            )
        finally:
            if had_sql_with_retry:
                sampling_core.sql_with_retry = old_sql_with_retry
            else:
                delattr(sampling_core, "sql_with_retry")
            if had_check_cancelled:
                sampling_core.check_cancelled = old_check_cancelled
            else:
                delattr(sampling_core, "check_cancelled")

        self.assertEqual(len(ids), 2)
        self.assertEqual(timing["full_scan_fallback_count"], 1)
        self.assertEqual(timing["full_scan_fallback_rebates"], [1000])
        self.assertEqual(timing["random_range_attempts"], sampling_core.SAMPLE_ID_RANDOM_RANGE_ATTEMPTS)
        self.assertGreater(timing["random_range_duplicate_ids"], 0)

    def test_read_sample_rows_by_ids_reads_complete_id_groups(self):
        calls = []

        class FakeFrame:
            def __len__(self):
                return 2

        old_sql_with_retry = getattr(sampling_core, "sql_with_retry", None)
        had_sql_with_retry = hasattr(sampling_core, "sql_with_retry")
        old_read_sql_query = sampling_core.pd.read_sql_query
        sampling_core.sql_with_retry = lambda fn, label: calls.append(("retry", label)) or fn()
        sampling_core.pd.read_sql_query = (
            lambda query, engine: calls.append(("read_sql", query, engine)) or FakeFrame()
        )
        try:
            df = sampling_core.read_sample_rows_by_ids(
                "engine",
                "`source_table`",
                [10, 20],
                1000,
            )
        finally:
            sampling_core.pd.read_sql_query = old_read_sql_query
            if had_sql_with_retry:
                sampling_core.sql_with_retry = old_sql_with_retry
            else:
                delattr(sampling_core, "sql_with_retry")

        self.assertEqual(len(df), 2)
        query = next(item[1] for item in calls if item[0] == "read_sql")
        normalized_query = " ".join(query.split())
        self.assertIn("WHERE `id` IN (10,20)", normalized_query)
        self.assertNotIn("rebate", normalized_query.lower())
        self.assertNotIn("game_end", normalized_query.lower())

    def test_copy_table_between_engines_logs_copy_context_without_rebate_label(self):
        calls = []
        old_read_sql_query = sampling_core.pd.read_sql_query
        old_write = sampling_core.write_dataframe_to_staging_with_retry
        old_check_cancelled = getattr(sampling_core, "check_cancelled", None)
        had_check_cancelled = hasattr(sampling_core, "check_cancelled")
        old_quote_identifier = getattr(sampling_core, "quote_identifier", None)
        had_quote_identifier = hasattr(sampling_core, "quote_identifier")
        sampling_core.pd.read_sql_query = lambda *_args, **_kwargs: [
            sampling_core.pd.DataFrame([{"id": 1}])
        ]
        sampling_core.write_dataframe_to_staging_with_retry = (
            lambda df, target_engine, target_table_name, target_rebate=None, **kwargs:
            calls.append((target_rebate, kwargs))
        )
        sampling_core.check_cancelled = lambda: None
        sampling_core.quote_identifier = lambda value, _label: f"`{value}`"
        try:
            copied = sampling_core.copy_table_between_engines(
                "source-engine",
                "target-engine",
                "source_tmp",
                "target_tmp",
                label="同步采样临时表到目标库",
            )
        finally:
            sampling_core.pd.read_sql_query = old_read_sql_query
            sampling_core.write_dataframe_to_staging_with_retry = old_write
            if had_check_cancelled:
                sampling_core.check_cancelled = old_check_cancelled
            else:
                delattr(sampling_core, "check_cancelled")
            if had_quote_identifier:
                sampling_core.quote_identifier = old_quote_identifier
            else:
                delattr(sampling_core, "quote_identifier")

        self.assertEqual(copied, 1)
        self.assertEqual(len(calls), 1)
        target_rebate, kwargs = calls[0]
        self.assertIsNone(target_rebate)
        self.assertEqual(kwargs["operation_label"], "同步采样临时表到目标库：写入复制分块 1")
        self.assertEqual(kwargs["log_context"], "同步采样临时表到目标库，复制分块 1")
        self.assertNotIn("rebate", kwargs["operation_label"])
        self.assertNotIn("rebate", kwargs["log_context"])

    def test_append_sampling_remaps_sample_ids_after_existing_data(self):
        df = sampling_core.pd.DataFrame([
            {"id": 10, "sort": 1},
            {"id": 10, "sort": 2},
            {"id": 20, "sort": 1},
        ])
        remapped, pair_count, row_count, pairs = sampling_core.remap_sample_ids_to_append_sequence(
            df,
            id_mapping={},
            next_id_state=[5],
        )

        self.assertEqual(remapped["id"].tolist(), [5, 5, 6])
        self.assertEqual(pair_count, 2)
        self.assertEqual(row_count, 3)
        self.assertEqual(pairs, [(10, 5), (20, 6)])

    def test_append_structure_signature_ignores_column_lengths(self):
        source_columns = [
            ("id", "int(11)", "NO", ""),
            ("formation", "varchar(255)", "YES", ""),
            ("rebate", "bigint(20)", "NO", ""),
        ]
        target_columns = [
            ("id", "int(10)", "YES", "auto_increment"),
            ("formation", "varchar(500)", "NO", ""),
            ("rebate", "bigint(10)", "YES", ""),
        ]

        self.assertEqual(
            sampling_table_utils.append_compatible_column_signature(source_columns),
            sampling_table_utils.append_compatible_column_signature(target_columns),
        )

    def test_append_structure_signature_keeps_base_type_and_enum_values(self):
        self.assertNotEqual(
            sampling_table_utils.normalize_column_type_for_append("int(11)"),
            sampling_table_utils.normalize_column_type_for_append("bigint(20)"),
        )
        self.assertNotEqual(
            sampling_table_utils.normalize_column_type_for_append("enum('a','b')"),
            sampling_table_utils.normalize_column_type_for_append("enum('a','c')"),
        )

    def test_append_sampling_chunk_uses_keyword_remap_arguments(self):
        df = sampling_core.pd.DataFrame([
            {"id": 10, "sort": 1},
            {"id": 20, "sort": 1},
        ])

        with contextlib.redirect_stdout(io.StringIO()):
            remapped, pair_count, row_count, final_conn = sampling_core.remap_sample_chunk_for_append_mode(
                df,
                final_conn="final-conn",
                final_db_name="DB1",
                staging_table_name="tmp_table",
                id_mapping={},
                next_id_state=[100],
            )

        self.assertEqual(remapped["id"].tolist(), [100, 101])
        self.assertEqual(pair_count, 2)
        self.assertEqual(row_count, 2)
        self.assertEqual(final_conn, "final-conn")

    def test_dump_import_table_between_databases_uses_mysql_cli_and_rewrites_target_table(self):
        calls = []
        old_run = sampling_core.subprocess.run
        old_which = sampling_core.shutil.which
        old_print = sampling_core.print
        old_check_cancelled = getattr(sampling_core, "check_cancelled", None)
        had_check_cancelled = hasattr(sampling_core, "check_cancelled")
        sampling_core.shutil.which = lambda name: f"C:\\mysql\\bin\\{name}"
        sampling_core.print = lambda message="": calls.append(("print", message))
        sampling_core.check_cancelled = lambda: None

        def fake_run(args, stdin=None, stdout=None, stderr=None, env=None, check=False):
            calls.append(("run", args, env, stdin is not None))
            exe_name = Path(args[0]).name.lower()
            if exe_name.startswith("mysqldump"):
                dump_path = next(arg.split("=", 1)[1] for arg in args if arg.startswith("--result-file="))
                Path(dump_path).write_bytes(b"INSERT INTO `source_table` VALUES (1);\n")
            elif exe_name.startswith("mysql"):
                calls.append(("import_data", stdin.read()))
            return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

        sampling_core.subprocess.run = fake_run
        try:
            result = sampling_core.dump_import_table_between_databases(
                {
                    "host": "127.0.0.1",
                    "port": 3306,
                    "user": "source_user",
                    "password": "source_secret",
                    "database": "source_db",
                },
                {
                    "host": "192.168.1.1",
                    "port": 3307,
                    "user": "target_user",
                    "password": "target_secret",
                    "database": "target_db",
                },
                "source_table",
                "target_tmp",
                label="镜像测试",
            )
        finally:
            sampling_core.subprocess.run = old_run
            sampling_core.shutil.which = old_which
            sampling_core.print = old_print
            if had_check_cancelled:
                sampling_core.check_cancelled = old_check_cancelled
            else:
                delattr(sampling_core, "check_cancelled")

        self.assertTrue(result)
        run_calls = [call for call in calls if call[0] == "run"]
        self.assertEqual(len(run_calls), 2)
        dump_args = run_calls[0][1]
        import_args = run_calls[1][1]
        self.assertIn("--single-transaction", dump_args)
        self.assertIn("--database=target_db", import_args)
        self.assertNotIn("source_secret", " ".join(dump_args))
        self.assertNotIn("target_secret", " ".join(import_args))
        self.assertEqual(run_calls[0][2]["MYSQL_PWD"], "source_secret")
        self.assertEqual(run_calls[1][2]["MYSQL_PWD"], "target_secret")
        imported = next(call[1] for call in calls if call[0] == "import_data")
        self.assertIn(b"`target_tmp`", imported)
        self.assertNotIn(b"`source_table`", imported)

    def test_dump_import_table_between_databases_retries_import_and_reprepares_target(self):
        calls = []
        old_run = sampling_core.subprocess.run
        old_which = sampling_core.shutil.which
        old_print = sampling_core.print
        old_sleep = getattr(sampling_core, "interruptible_sleep", None)
        had_sleep = hasattr(sampling_core, "interruptible_sleep")
        old_check_cancelled = getattr(sampling_core, "check_cancelled", None)
        had_check_cancelled = hasattr(sampling_core, "check_cancelled")
        old_retries = getattr(sampling_core, "MYSQL_DUMP_IMPORT_RETRIES", None)
        had_retries = hasattr(sampling_core, "MYSQL_DUMP_IMPORT_RETRIES")
        old_retry_delay = getattr(sampling_core, "DB_RETRY_DELAY", None)
        had_retry_delay = hasattr(sampling_core, "DB_RETRY_DELAY")
        import_attempts = {"count": 0}
        sampling_core.shutil.which = lambda name: f"C:\\mysql\\bin\\{name}"
        sampling_core.print = lambda message="": calls.append(("print", message))
        sampling_core.interruptible_sleep = lambda seconds: calls.append(("sleep", seconds))
        sampling_core.check_cancelled = lambda: None
        sampling_core.MYSQL_DUMP_IMPORT_RETRIES = 5
        sampling_core.DB_RETRY_DELAY = 0

        def fake_run(args, stdin=None, stdout=None, stderr=None, env=None, check=False):
            exe_name = Path(args[0]).name.lower()
            if exe_name.startswith("mysqldump"):
                dump_path = next(arg.split("=", 1)[1] for arg in args if arg.startswith("--result-file="))
                Path(dump_path).write_bytes(b"INSERT INTO `source_table` VALUES (1);\n")
                return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
            import_attempts["count"] += 1
            if import_attempts["count"] < 3:
                return SimpleNamespace(returncode=1, stdout=b"", stderr=b"lost connection")
            return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

        sampling_core.subprocess.run = fake_run
        try:
            result = sampling_core.dump_import_table_between_databases(
                {"host": "h", "port": 3306, "user": "u", "password": "p", "database": "sdb"},
                {"host": "h", "port": 3306, "user": "u", "password": "p", "database": "tdb"},
                "source_table",
                "target_tmp",
                label="镜像测试",
                reprepare_target=lambda: calls.append("reprepare"),
            )
        finally:
            sampling_core.subprocess.run = old_run
            sampling_core.shutil.which = old_which
            sampling_core.print = old_print
            if had_sleep:
                sampling_core.interruptible_sleep = old_sleep
            else:
                delattr(sampling_core, "interruptible_sleep")
            if had_check_cancelled:
                sampling_core.check_cancelled = old_check_cancelled
            else:
                delattr(sampling_core, "check_cancelled")
            if had_retries:
                sampling_core.MYSQL_DUMP_IMPORT_RETRIES = old_retries
            else:
                delattr(sampling_core, "MYSQL_DUMP_IMPORT_RETRIES")
            if had_retry_delay:
                sampling_core.DB_RETRY_DELAY = old_retry_delay
            else:
                delattr(sampling_core, "DB_RETRY_DELAY")

        self.assertTrue(result)
        self.assertEqual(import_attempts["count"], 3)
        self.assertEqual(calls.count("reprepare"), 2)

    def test_finalize_temp_db_replaces_staging_formal_table_without_auto_sync(self):
        calls = []
        old_count = getattr(sampling_core, "count_table_rows", None)
        old_refresh = getattr(sampling_core, "refresh_connection_read_view", None)
        old_replace = getattr(sampling_core, "replace_table_with_staging", None)
        old_copy = getattr(sampling_core, "copy_table_between_engines", None)
        old_print = sampling_core.print
        sampling_core.count_table_rows = lambda _conn, _table: 10
        sampling_core.refresh_connection_read_view = lambda conn, _db, _label: conn
        sampling_core.replace_table_with_staging = (
            lambda conn, staging, target, db: calls.append(("replace", conn, staging, target, db))
        )
        sampling_core.copy_table_between_engines = (
            lambda *_args, **_kwargs: self.fail("target sync should not run during sampling finalize")
        )
        sampling_core.print = lambda message="": calls.append(("print", message))
        try:
            result, final_conn = sampling_core.finalize_direct_sampling_staging(
                None,
                {
                    "source_db_name": "SRC",
                    "final_db_name": "DST",
                    "staging_db_name": "TMP",
                    "source_table_name": "source_table",
                    "final_table_name": "final_table",
                },
                {"staging_table_name": "final_table_tmp", "base_existing_count": 0},
                {"sampled_count": 10, "remapped_id_count": 0, "remapped_row_count": 0},
                False,
                table_config={"FINAL_TABLE": {"database": "DST", "name": "final_table"}},
                staging_conn="staging-conn",
            )
        finally:
            sampling_core.print = old_print
            if old_count is not None:
                sampling_core.count_table_rows = old_count
            else:
                delattr(sampling_core, "count_table_rows")
            if old_refresh is not None:
                sampling_core.refresh_connection_read_view = old_refresh
            else:
                delattr(sampling_core, "refresh_connection_read_view")
            if old_replace is not None:
                sampling_core.replace_table_with_staging = old_replace
            else:
                delattr(sampling_core, "replace_table_with_staging")
            if old_copy is not None:
                sampling_core.copy_table_between_engines = old_copy
            else:
                delattr(sampling_core, "copy_table_between_engines")

        self.assertIsNone(final_conn)
        self.assertIs(result, True)
        self.assertIn(("replace", "staging-conn", "final_table_tmp", "final_table", "TMP"), calls)

    def test_resolve_direct_sample_conditions_defers_end_field_integrity_validation(self):
        old_get_table_name = getattr(sampling_core, "get_table_name", None)
        old_detect_optional = getattr(sampling_core, "detect_end_field_optional", None)
        old_validate = getattr(sampling_core, "validate_end_field_integrity", None)
        sampling_core.get_table_name = lambda _key, _config: "source_table"
        sampling_core.detect_end_field_optional = lambda _conn, _table: " AND game_end = 1"
        sampling_core.validate_end_field_integrity = (
            lambda *_args: self.fail("full-table end-field validation should be deferred")
        )
        try:
            resolved = sampling_core.resolve_direct_sample_conditions(
                object(),
                {},
                {
                    "where_clause": "rebate = {target_rebate}{end_field_opt}",
                    "random_seed": 108,
                },
            )
        finally:
            if old_get_table_name is not None:
                sampling_core.get_table_name = old_get_table_name
            else:
                delattr(sampling_core, "get_table_name")
            if old_detect_optional is not None:
                sampling_core.detect_end_field_optional = old_detect_optional
            else:
                delattr(sampling_core, "detect_end_field_optional")
            if old_validate is not None:
                sampling_core.validate_end_field_integrity = old_validate
            else:
                delattr(sampling_core, "validate_end_field_integrity")

        self.assertEqual(resolved["where_clause"], "rebate = {target_rebate} AND game_end = 1")
        self.assertEqual(resolved["end_field_for_validation"], "game_end")

    def test_sampled_id_end_field_validation_checks_only_selected_ids(self):
        queries = []

        class FakeResult:
            def __iter__(self):
                return iter([(10, 1), (20, 1)])

        class FakeConnection:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def exec_driver_sql(self, query):
                queries.append(query)
                return FakeResult()

        class FakeEngine:
            def connect(self):
                return FakeConnection()

        old_sql_with_retry = getattr(sampling_core, "sql_with_retry", None)
        had_sql_with_retry = hasattr(sampling_core, "sql_with_retry")
        old_check_cancelled = getattr(sampling_core, "check_cancelled", None)
        had_check_cancelled = hasattr(sampling_core, "check_cancelled")
        old_quote_identifier = getattr(sampling_core, "quote_identifier", None)
        had_quote_identifier = hasattr(sampling_core, "quote_identifier")
        old_chunked = getattr(sampling_core, "chunked", None)
        had_chunked = hasattr(sampling_core, "chunked")
        sampling_core.sql_with_retry = lambda fn, label: fn()
        sampling_core.check_cancelled = lambda: None
        sampling_core.quote_identifier = lambda value, _label: f"`{value}`"
        sampling_core.chunked = lambda values, _size: [list(values)]
        try:
            sampling_core.validate_sampled_ids_end_field_integrity(
                FakeEngine(),
                "`source_table`",
                "source_table",
                "game_end",
                [10, 20],
                target_rebate=1000,
            )
        finally:
            if had_sql_with_retry:
                sampling_core.sql_with_retry = old_sql_with_retry
            else:
                delattr(sampling_core, "sql_with_retry")
            if had_check_cancelled:
                sampling_core.check_cancelled = old_check_cancelled
            else:
                delattr(sampling_core, "check_cancelled")
            if had_quote_identifier:
                sampling_core.quote_identifier = old_quote_identifier
            else:
                delattr(sampling_core, "quote_identifier")
            if had_chunked:
                sampling_core.chunked = old_chunked
            else:
                delattr(sampling_core, "chunked")

        normalized_query = " ".join(queries[0].split())
        self.assertIn("WHERE `id` IN (10,20)", normalized_query)
        self.assertIn("GROUP BY `id`", normalized_query)
        self.assertNotIn("HAVING", normalized_query)

    def test_sampled_id_end_field_validation_reports_bad_selected_ids(self):
        class FakeResult:
            def __iter__(self):
                return iter([(10, 2), (20, 0)])

        class FakeConnection:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def exec_driver_sql(self, _query):
                return FakeResult()

        class FakeEngine:
            def connect(self):
                return FakeConnection()

        old_sql_with_retry = getattr(sampling_core, "sql_with_retry", None)
        had_sql_with_retry = hasattr(sampling_core, "sql_with_retry")
        old_check_cancelled = getattr(sampling_core, "check_cancelled", None)
        had_check_cancelled = hasattr(sampling_core, "check_cancelled")
        old_quote_identifier = getattr(sampling_core, "quote_identifier", None)
        had_quote_identifier = hasattr(sampling_core, "quote_identifier")
        old_chunked = getattr(sampling_core, "chunked", None)
        had_chunked = hasattr(sampling_core, "chunked")
        sampling_core.sql_with_retry = lambda fn, label: fn()
        sampling_core.check_cancelled = lambda: None
        sampling_core.quote_identifier = lambda value, _label: f"`{value}`"
        sampling_core.chunked = lambda values, _size: [list(values)]
        try:
            with self.assertRaisesRegex(ValueError, "仅检查已采样ID"):
                sampling_core.validate_sampled_ids_end_field_integrity(
                    FakeEngine(),
                    "`source_table`",
                    "source_table",
                    "game_end",
                    [10, 20],
                    target_rebate=1000,
                )
        finally:
            if had_sql_with_retry:
                sampling_core.sql_with_retry = old_sql_with_retry
            else:
                delattr(sampling_core, "sql_with_retry")
            if had_check_cancelled:
                sampling_core.check_cancelled = old_check_cancelled
            else:
                delattr(sampling_core, "check_cancelled")
            if had_quote_identifier:
                sampling_core.quote_identifier = old_quote_identifier
            else:
                delattr(sampling_core, "quote_identifier")
            if had_chunked:
                sampling_core.chunked = old_chunked
            else:
                delattr(sampling_core, "chunked")

    def test_write_sample_chunk_uses_batched_progress_insert(self):
        calls = []

        class FakeConnection:
            pass

        class FakeBegin:
            def __init__(self):
                self.conn = FakeConnection()

            def __enter__(self):
                calls.append("begin")
                return self.conn

            def __exit__(self, *_args):
                calls.append("end")
                return False

        class FakeEngine:
            def begin(self):
                return FakeBegin()

        class FakeFrame:
            def __len__(self):
                return 3

            def to_sql(self, *args, **kwargs):
                calls.append(("to_sql", args, kwargs))

        old_check_cancelled = getattr(sampling_core, "check_cancelled", None)
        had_check_cancelled = hasattr(sampling_core, "check_cancelled")
        sampling_core.check_cancelled = lambda: None
        try:
            sampling_core.write_sample_chunk_to_staging(FakeFrame(), FakeEngine(), "tmp_table", 1000)
        finally:
            if had_check_cancelled:
                sampling_core.check_cancelled = old_check_cancelled
            else:
                delattr(sampling_core, "check_cancelled")

        to_sql_call = next(item for item in calls if item[0] == "to_sql")
        self.assertEqual(to_sql_call[1][0], "tmp_table")
        self.assertIsInstance(to_sql_call[1][1], FakeConnection)
        self.assertEqual(to_sql_call[2]["if_exists"], "append")
        self.assertFalse(to_sql_call[2]["index"])
        self.assertEqual(to_sql_call[2]["chunksize"], sampling_core.SAMPLE_ROW_WRITE_CHUNK_SIZE)
        self.assertTrue(callable(to_sql_call[2]["method"]))
        self.assertEqual(calls[0], "begin")
        self.assertIn("end", calls)

    def test_write_sample_chunk_disposes_engine_before_retry(self):
        calls = []

        class FakeConnection:
            pass

        class FakeBegin:
            def __init__(self, fail):
                self.fail = fail
                self.conn = FakeConnection()

            def __enter__(self):
                calls.append("begin")
                return self.conn

            def __exit__(self, *_args):
                calls.append("end")
                return False

        class FakeEngine:
            def __init__(self):
                self.attempt = 0

            def begin(self):
                self.attempt += 1
                return FakeBegin(self.attempt == 1)

            def dispose(self):
                calls.append("dispose")

        class FakeFrame:
            def __len__(self):
                return 3

            def to_sql(self, *_args, **_kwargs):
                calls.append(("to_sql", _kwargs.get("chunksize")))
                if sum(1 for item in calls if isinstance(item, tuple) and item[0] == "to_sql") == 1:
                    raise RuntimeError("lock wait timeout")

        old_check_cancelled = getattr(sampling_core, "check_cancelled", None)
        had_check_cancelled = hasattr(sampling_core, "check_cancelled")
        old_interruptible_sleep = getattr(sampling_core, "interruptible_sleep", None)
        had_interruptible_sleep = hasattr(sampling_core, "interruptible_sleep")
        old_max_retries = getattr(sampling_core, "MAX_DB_RETRIES", None)
        had_max_retries = hasattr(sampling_core, "MAX_DB_RETRIES")
        old_retry_delay = getattr(sampling_core, "DB_RETRY_DELAY", None)
        had_retry_delay = hasattr(sampling_core, "DB_RETRY_DELAY")
        old_chunk_size = getattr(sampling_core, "SAMPLE_ROW_WRITE_CHUNK_SIZE", None)
        had_chunk_size = hasattr(sampling_core, "SAMPLE_ROW_WRITE_CHUNK_SIZE")
        old_print = sampling_core.print
        sampling_core.check_cancelled = lambda: calls.append("check")
        sampling_core.interruptible_sleep = lambda seconds: calls.append(("sleep", seconds))
        sampling_core.MAX_DB_RETRIES = 2
        sampling_core.DB_RETRY_DELAY = 5
        sampling_core.SAMPLE_ROW_WRITE_CHUNK_SIZE = 20
        sampling_core.print = lambda message="": calls.append(("print", message))
        try:
            sampling_core.write_sample_chunk_to_staging(FakeFrame(), FakeEngine(), "tmp_table", 6300)
        finally:
            sampling_core.print = old_print
            if had_check_cancelled:
                sampling_core.check_cancelled = old_check_cancelled
            else:
                delattr(sampling_core, "check_cancelled")
            if had_interruptible_sleep:
                sampling_core.interruptible_sleep = old_interruptible_sleep
            else:
                delattr(sampling_core, "interruptible_sleep")
            if had_max_retries:
                sampling_core.MAX_DB_RETRIES = old_max_retries
            else:
                delattr(sampling_core, "MAX_DB_RETRIES")
            if had_retry_delay:
                sampling_core.DB_RETRY_DELAY = old_retry_delay
            else:
                delattr(sampling_core, "DB_RETRY_DELAY")
            if had_chunk_size:
                sampling_core.SAMPLE_ROW_WRITE_CHUNK_SIZE = old_chunk_size
            else:
                delattr(sampling_core, "SAMPLE_ROW_WRITE_CHUNK_SIZE")

        self.assertIn("dispose", calls)
        self.assertIn(("sleep", 5), calls)
        self.assertEqual(
            [item[1] for item in calls if isinstance(item, tuple) and item[0] == "to_sql"],
            [20, 5],
        )
        self.assertTrue(
            any(
                isinstance(item, tuple)
                and item[0] == "print"
                and "第2次重试成功" in item[1]
                for item in calls
            )
        )

    def test_sample_row_write_method_reports_inserted_rows(self):
        calls = []

        class FakeResult:
            rowcount = 2

        class FakeSqlTable:
            class table:
                @staticmethod
                def insert():
                    return "insert-statement"

        class FakeConn:
            def execute(self, statement, rows):
                calls.append(("execute", statement, rows))
                return FakeResult()

        old_check_cancelled = getattr(sampling_core, "check_cancelled", None)
        had_check_cancelled = hasattr(sampling_core, "check_cancelled")
        old_print = sampling_core.print
        sampling_core.check_cancelled = lambda: calls.append(("check_cancelled",))
        sampling_core.print = lambda message="": calls.append(("print", message))
        try:
            method = sampling_core._make_sample_row_write_method(3, 1000)
            rowcount = method(
                FakeSqlTable(),
                FakeConn(),
                ["id", "value"],
                [(1, "a"), (2, "b")],
            )
        finally:
            sampling_core.print = old_print
            if had_check_cancelled:
                sampling_core.check_cancelled = old_check_cancelled
            else:
                delattr(sampling_core, "check_cancelled")

        self.assertEqual(rowcount, 2)
        execute_call = next(item for item in calls if item[0] == "execute")
        self.assertEqual(execute_call[1], "insert-statement")
        self.assertEqual(execute_call[2], [{"id": 1, "value": "a"}, {"id": 2, "value": "b"}])
        self.assertTrue(any(item[0] == "check_cancelled" for item in calls))

    def test_sampling_detail_log_is_off_by_default(self):
        calls = []
        old_detailed_log = getattr(sampling_core, "SAMPLING_DETAILED_LOG", False)
        old_print = sampling_core.print
        sampling_core.print = lambda message="": calls.append(message)
        try:
            sampling_core.SAMPLING_DETAILED_LOG = False
            sampling_core.print_sampling_detail("hidden")
            sampling_core.SAMPLING_DETAILED_LOG = True
            sampling_core.print_sampling_detail("shown")
        finally:
            sampling_core.SAMPLING_DETAILED_LOG = old_detailed_log
            sampling_core.print = old_print

        self.assertEqual(calls, ["shown"])


class DirectSamplingRunnerTests(unittest.TestCase):
    def build_base_deps(self, events, *, append_mode=True):
        names = {
            "source_db_name": "SRC",
            "final_db_name": "DST",
            "config_db_name": "CFG",
            "source_table_name": "source_table",
            "final_table_name": "final_table",
            "rebate_config_table_name": "rebate_count",
        }
        source_conn = object()
        final_conn = object()

        def connect_by_table(table_key, _table_config):
            events.append(("connect", table_key))
            return source_conn if table_key == "SOURCE_TABLE" else final_conn

        def close_safely(conn):
            events.append(("close", conn))

        return SimpleNamespace(
            names=names,
            source_conn=source_conn,
            final_conn=final_conn,
            check_cancelled=lambda: events.append("check_cancelled"),
            get_direct_sampling_names=lambda _table_config: names,
            reject_same_physical_sampling_table=lambda _table_config, _names: False,
            connect_by_table=connect_by_table,
            resolve_direct_sample_conditions=lambda *_args: {"where_clause": "rebate = {target_rebate}"},
            get_engine_by_table=lambda table_key, _table_config: f"engine:{table_key}",
            load_sampling_config_df=lambda *_args: ["config-row"],
            get_append_mode=lambda: append_mode,
            print_step_error=lambda *args: events.append(("error", args)),
            close_safely=close_safely,
        )

    def test_direct_sampling_success_uses_replace_mode_and_closes_connections(self):
        events = []
        deps = self.build_base_deps(events, append_mode=True)
        final_conn_after = object()
        staging_state = {
            "staging_table_name": "final_table_tmp",
            "base_existing_count": 2,
            "id_mapping": {},
            "next_id_state": [10],
        }

        def prepare_staging(source_conn, final_conn, _table_config, names, append_mode):
            events.append(("prepare", source_conn, final_conn, names["final_table_name"], append_mode))
            return staging_state

        def sample_rows(config_df, **kwargs):
            events.append(("sample", config_df, kwargs["append_mode"], kwargs["staging_state"]))
            return {"sampled_count": 3, "remapped_id_count": 1, "remapped_row_count": 2}, final_conn_after

        def finalize(final_conn, names, received_staging_state, totals, append_mode):
            events.append(("finalize", final_conn, names["final_table_name"], received_staging_state, totals, append_mode))
            return True, final_conn

        deps.prepare_direct_sampling_staging = prepare_staging
        deps.sample_config_rows_to_staging = sample_rows
        deps.finalize_direct_sampling_staging = finalize
        deps.cleanup_direct_sampling_failure = lambda *args: events.append(("cleanup", args))

        result = run_direct_sampling_silently(deps)

        self.assertTrue(result)
        self.assertIn(("prepare", deps.source_conn, deps.final_conn, "final_table", False), events)
        self.assertIn(("sample", ["config-row"], False, staging_state), events)
        self.assertIn(("finalize", final_conn_after, "final_table", staging_state, {
            "sampled_count": 3,
            "remapped_id_count": 1,
            "remapped_row_count": 2,
        }, False), events)
        self.assertNotIn("cleanup", [event[0] for event in events if isinstance(event, tuple)])
        self.assertIn(("close", deps.source_conn), events)
        self.assertIn(("close", final_conn_after), events)

    def test_direct_sampling_temp_db_clear_mode_skips_target_until_sync(self):
        events = []
        deps = self.build_base_deps(events, append_mode=False)
        deps.names["staging_db_name"] = "TMP"
        target_final_conn = object()
        staging_conn = object()
        updated_staging_conn = object()
        staging_state = {"staging_table_name": "final_table_tmp", "base_existing_count": 0}

        def connect_by_table(table_key, table_config):
            db_name = (table_config.get("FINAL_TABLE") or {}).get("database") if isinstance(table_config, dict) else None
            events.append(("connect", table_key, db_name))
            if table_key == "SOURCE_TABLE":
                return deps.source_conn
            return staging_conn if db_name == "TMP" else target_final_conn

        def get_engine_by_table(table_key, table_config):
            db_name = (table_config.get("FINAL_TABLE") or {}).get("database") if isinstance(table_config, dict) else None
            return f"engine:{table_key}:{db_name or 'DST'}"

        def prepare_staging(source_conn, final_conn, _table_config, names, append_mode, **kwargs):
            events.append((
                "prepare",
                source_conn,
                final_conn,
                kwargs["final_target_conn"],
                kwargs["staging_table_config"]["FINAL_TABLE"]["database"],
            ))
            return staging_state

        def sample_rows(_config_df, **kwargs):
            events.append((
                "sample",
                kwargs["final_conn"],
                kwargs["final_engine"],
                kwargs["names"]["staging_db_name"],
            ))
            return {"sampled_count": 3, "remapped_id_count": 0, "remapped_row_count": 0}, updated_staging_conn

        def finalize(final_conn, _names, _staging_state, _totals, _append_mode, **kwargs):
            events.append((
                "finalize",
                final_conn,
                kwargs["staging_conn"],
                kwargs["final_engine"],
                kwargs["staging_engine"],
            ))
            return True, final_conn

        deps.connect_by_table = connect_by_table
        deps.get_engine_by_table = get_engine_by_table
        deps.get_sampling_staging_table_config = lambda _config: {"FINAL_TABLE": {"database": "TMP"}}
        deps.prepare_direct_sampling_staging = prepare_staging
        deps.sample_config_rows_to_staging = sample_rows
        deps.finalize_direct_sampling_staging = finalize
        deps.cleanup_direct_sampling_failure = lambda *args, **kwargs: events.append(("cleanup", args, kwargs))

        result = run_direct_sampling_silently(deps)

        self.assertTrue(result)
        self.assertNotIn(("connect", "FINAL_TABLE", None), events)
        self.assertIn(("connect", "FINAL_TABLE", "TMP"), events)
        self.assertIn(("prepare", deps.source_conn, staging_conn, None, "TMP"), events)
        self.assertIn(("sample", staging_conn, "engine:FINAL_TABLE:TMP", "TMP"), events)
        self.assertIn((
            "finalize",
            None,
            updated_staging_conn,
            None,
            "engine:FINAL_TABLE:TMP",
        ), events)
        self.assertIn(("close", updated_staging_conn), events)
        self.assertNotIn(("close", target_final_conn), events)

    def test_direct_sampling_success_passes_clear_mode_to_staging_flow(self):
        events = []
        deps = self.build_base_deps(events, append_mode=False)
        staging_state = {"staging_table_name": "final_table_tmp"}

        deps.prepare_direct_sampling_staging = lambda *_args: staging_state

        def sample_rows(_config_df, **kwargs):
            events.append(("sample_append_mode", kwargs["append_mode"]))
            return {"sampled_count": 1, "remapped_id_count": 0, "remapped_row_count": 0}, deps.final_conn

        def finalize(_final_conn, _names, _staging_state, _totals, append_mode):
            events.append(("finalize_append_mode", append_mode))
            return True, deps.final_conn

        deps.sample_config_rows_to_staging = sample_rows
        deps.finalize_direct_sampling_staging = finalize
        deps.cleanup_direct_sampling_failure = lambda *args: events.append(("cleanup", args))

        result = run_direct_sampling_silently(deps)

        self.assertTrue(result)
        self.assertIn(("sample_append_mode", False), events)
        self.assertIn(("finalize_append_mode", False), events)

    def test_direct_sampling_can_run_explicit_append_mode(self):
        events = []
        deps = self.build_base_deps(events, append_mode=False)
        staging_state = {"staging_table_name": "final_table_tmp"}

        deps.prepare_direct_sampling_staging = lambda *_args: staging_state

        def sample_rows(_config_df, **kwargs):
            events.append(("sample_append_mode", kwargs["append_mode"]))
            return {"sampled_count": 1, "remapped_id_count": 0, "remapped_row_count": 0}, deps.final_conn

        def finalize(_final_conn, _names, _staging_state, _totals, append_mode):
            events.append(("finalize_append_mode", append_mode))
            return True, deps.final_conn

        deps.sample_config_rows_to_staging = sample_rows
        deps.finalize_direct_sampling_staging = finalize
        deps.cleanup_direct_sampling_failure = lambda *args: events.append(("cleanup", args))

        with contextlib.redirect_stdout(io.StringIO()):
            result = direct_sampling_runner.direct_sample_from_source(
                {},
                {},
                deps=deps,
                append_mode=True,
            )

        self.assertTrue(result)
        self.assertIn(("sample_append_mode", True), events)
        self.assertIn(("finalize_append_mode", True), events)

    def test_direct_sampling_sample_failure_keeps_staging_context_for_cleanup(self):
        events = []
        deps = self.build_base_deps(events)
        staging_state = {"staging_table_name": "final_table_tmp"}

        deps.prepare_direct_sampling_staging = lambda *_args: staging_state

        def fail_sample(*_args, **_kwargs):
            raise RuntimeError("sample failed")

        def cleanup(error, final_conn, names, received_staging_state, sampled_count):
            events.append((
                "cleanup",
                str(error),
                final_conn,
                names["final_table_name"],
                received_staging_state,
                sampled_count,
            ))
            return final_conn

        deps.sample_config_rows_to_staging = fail_sample
        deps.finalize_direct_sampling_staging = lambda *_args: events.append("unexpected_finalize")
        deps.cleanup_direct_sampling_failure = cleanup

        with self.assertRaises(RuntimeError):
            run_direct_sampling_silently(deps)

        self.assertIn((
            "cleanup",
            "sample failed",
            deps.final_conn,
            "final_table",
            staging_state,
            0,
        ), events)
        self.assertNotIn("unexpected_finalize", events)

    def test_direct_sampling_config_load_failure_returns_false_without_staging(self):
        events = []
        deps = self.build_base_deps(events)

        def fail_load(*_args):
            raise RuntimeError("missing config")

        deps.load_sampling_config_df = fail_load
        deps.prepare_direct_sampling_staging = lambda *_args: events.append("unexpected_prepare")
        deps.sample_config_rows_to_staging = lambda *_args, **_kwargs: events.append("unexpected_sample")
        deps.finalize_direct_sampling_staging = lambda *_args: events.append("unexpected_finalize")
        deps.cleanup_direct_sampling_failure = lambda *args: events.append(("cleanup", args))

        result = run_direct_sampling_silently(deps)

        self.assertFalse(result)
        self.assertNotIn("unexpected_prepare", events)
        self.assertNotIn("unexpected_sample", events)
        self.assertNotIn("unexpected_finalize", events)
        self.assertIn(("close", deps.source_conn), events)
        self.assertIn(("close", deps.final_conn), events)

    def test_direct_sampling_failure_keeps_sampled_staging_context_for_cleanup(self):
        events = []
        deps = self.build_base_deps(events)
        staging_state = {"staging_table_name": "final_table_tmp"}

        deps.prepare_direct_sampling_staging = lambda *_args: staging_state
        deps.sample_config_rows_to_staging = lambda *_args, **_kwargs: (
            {"sampled_count": 5, "remapped_id_count": 0, "remapped_row_count": 0},
            deps.final_conn,
        )

        def fail_finalize(*_args):
            raise RuntimeError("staging count mismatch")

        def cleanup(error, final_conn, names, received_staging_state, sampled_count):
            events.append((
                "cleanup",
                str(error),
                final_conn,
                names["final_table_name"],
                received_staging_state,
                sampled_count,
            ))
            return final_conn

        deps.finalize_direct_sampling_staging = fail_finalize
        deps.cleanup_direct_sampling_failure = cleanup

        with self.assertRaises(RuntimeError):
            run_direct_sampling_silently(deps)

        self.assertIn((
            "cleanup",
            "staging count mismatch",
            deps.final_conn,
            "final_table",
            staging_state,
            5,
        ), events)
        self.assertIn(("close", deps.source_conn), events)
        self.assertIn(("close", deps.final_conn), events)

    def test_direct_sampling_resumes_existing_staging_state(self):
        events = []
        deps = self.build_base_deps(events)
        task_state = {
            "status": "failed",
            "totals": {"sampled_count": 5, "remapped_id_count": 1, "remapped_row_count": 2},
        }
        staging_state = {
            "staging_table_name": "final_table_tmp_old",
            "base_existing_count": 2,
            "id_mapping": {10: 20},
            "next_id_state": [30],
        }

        deps.build_sampling_task_identity = lambda names, sample_conditions, append_mode: {
            "table": names["final_table_name"],
            "where": sample_conditions["where_clause"],
            "append": append_mode,
        }
        deps.load_sampling_task_state = lambda _identity: task_state
        deps.try_resume_direct_sampling_staging = lambda _final_conn, _names, _state: (
            staging_state,
            {"sampled_count": 5, "remapped_id_count": 1, "remapped_row_count": 2},
        )
        deps.prepare_direct_sampling_staging = lambda *_args: events.append("unexpected_prepare")

        def sample_rows(config_df, **kwargs):
            events.append((
                "sample",
                config_df,
                kwargs["staging_state"],
                kwargs["task_state"],
                kwargs["initial_totals"],
            ))
            return {"sampled_count": 8, "remapped_id_count": 1, "remapped_row_count": 2}, deps.final_conn

        deps.sample_config_rows_to_staging = sample_rows
        deps.finalize_direct_sampling_staging = lambda _conn, _names, _staging, totals, _append: (
            events.append(("finalize", totals)) or (True, deps.final_conn)
        )
        deps.cleanup_direct_sampling_failure = lambda *args: events.append(("cleanup", args))
        deps.mark_sampling_task_completed = lambda state, *, success: events.append(("completed", state, success))

        result = run_direct_sampling_silently(deps)

        self.assertTrue(result)
        self.assertNotIn("unexpected_prepare", events)
        self.assertIn((
            "sample",
            ["config-row"],
            staging_state,
            task_state,
            {"sampled_count": 5, "remapped_id_count": 1, "remapped_row_count": 2},
        ), events)
        self.assertIn(("finalize", {"sampled_count": 8, "remapped_id_count": 1, "remapped_row_count": 2}), events)
        self.assertIn(("completed", task_state, True), events)

    def test_direct_sampling_failure_uses_task_state_totals_for_cleanup(self):
        events = []
        deps = self.build_base_deps(events)
        task_state = {"status": "running", "totals": {"sampled_count": 4}}
        staging_state = {"staging_table_name": "final_table_tmp"}

        deps.build_sampling_task_identity = lambda *_args: {"id": "sampling"}
        deps.load_sampling_task_state = lambda _identity: None
        deps.start_sampling_task_state = lambda *_args: task_state
        deps.prepare_direct_sampling_staging = lambda *_args: staging_state

        def fail_sample(*_args, **_kwargs):
            task_state["totals"] = {"sampled_count": 9, "remapped_id_count": 0, "remapped_row_count": 0}
            raise RuntimeError("sample failed")

        def cleanup(error, _final_conn, _names, _staging_state, sampled_count):
            events.append(("cleanup", str(error), sampled_count))
            return deps.final_conn

        deps.sample_config_rows_to_staging = fail_sample
        deps.finalize_direct_sampling_staging = lambda *_args: events.append("unexpected_finalize")
        deps.cleanup_direct_sampling_failure = cleanup
        deps.mark_sampling_task_failed = lambda state, error: events.append(("failed", state, str(error)))

        with self.assertRaises(RuntimeError):
            run_direct_sampling_silently(deps)

        self.assertIn(("failed", task_state, "sample failed"), events)
        self.assertIn(("cleanup", "sample failed", 9), events)
        self.assertNotIn("unexpected_finalize", events)


class SamplingTaskStateTests(unittest.TestCase):
    def test_write_state_retries_transient_replace_failure(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "state.json"
            calls = []
            messages = []
            original_replace = sampling_task_state.os.replace
            original_print = sampling_task_state.print
            try:
                def flaky_replace(src, dst):
                    calls.append((src, dst))
                    if len(calls) <= 2:
                        raise PermissionError(5, "拒绝访问", str(dst))
                    return original_replace(src, dst)

                sampling_task_state.os.replace = flaky_replace
                sampling_task_state.print = lambda message="", *_args, **_kwargs: messages.append(str(message))

                result = sampling_task_state._write_state(
                    path,
                    {"schema_version": 1, "identity": {"table": "x"}},
                    retries=5,
                    retry_delay=0,
                )
            finally:
                sampling_task_state.os.replace = original_replace
                sampling_task_state.print = original_print

            self.assertTrue(result)
            self.assertEqual(len(calls), 3)
            self.assertTrue(any("暂时保存失败" in message for message in messages))
            self.assertTrue(any("保存成功" in message for message in messages))
            self.assertEqual(
                sampling_task_state.json.loads(path.read_text(encoding="utf-8"))["identity"],
                {"table": "x"},
            )

    def test_save_state_warns_and_continues_after_persistent_write_failure(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "state.json"
            warnings = []
            original_write_once = sampling_task_state._write_state_once
            original_sleep = sampling_task_state.time.sleep
            original_print = sampling_task_state.print
            try:
                def locked_write(*_args, **_kwargs):
                    raise PermissionError(5, "拒绝访问", str(path))

                sampling_task_state._write_state_once = locked_write
                sampling_task_state.time.sleep = lambda *_args, **_kwargs: None
                sampling_task_state.print = lambda message="": warnings.append(str(message))

                state = {"identity": {"table": "x"}, "_path": str(path)}
                result = sampling_task_state.save_state(state)
            finally:
                sampling_task_state._write_state_once = original_write_once
                sampling_task_state.time.sleep = original_sleep
                sampling_task_state.print = original_print

            self.assertIs(result, state)
            self.assertEqual(state["_path"], str(path))
            self.assertTrue(any("将继续采样" in message for message in warnings))
            self.assertTrue(any("不影响已写入的采样数据" in message for message in warnings))

    def test_state_roundtrip_records_completed_rebate_and_id_mapping(self):
        old_settings_dir = os.environ.get(settings_logic.APP_SETTINGS_DIR_ENV)
        with tempfile.TemporaryDirectory() as tmp_dir:
            os.environ[settings_logic.APP_SETTINGS_DIR_ENV] = tmp_dir
            try:
                identity = sampling_task_state.build_sampling_identity(
                    {
                        "source_db_name": "SRC",
                        "source_table_name": "source_table",
                        "final_db_name": "DST",
                        "final_table_name": "final_table",
                        "config_db_name": "CFG",
                        "rebate_config_table_name": "rebate_count",
                    },
                    {"where_clause": "rebate = {target_rebate}", "random_seed": 108},
                    True,
                )
                staging_state = {
                    "staging_table_name": "final_table_tmp",
                    "base_existing_count": 3,
                    "id_mapping": {11: 101},
                    "next_id_state": [102],
                }
                state = sampling_task_state.new_state(identity, staging_state, config_row_count=2)
                sampling_task_state.save_state(state)
                sampling_task_state.record_completed_rebate(
                    state,
                    staging_state,
                    rebate=5000,
                    sample_size=100,
                    sampled_count=120,
                    changed_pair_count=1,
                    changed_row_count=4,
                )

                loaded = sampling_task_state.load_state(identity)

                self.assertIsNotNone(loaded)
                self.assertEqual(loaded["identity"], identity)
                self.assertEqual(loaded["completed_rebates"], [5000])
                self.assertEqual(loaded["totals"]["sampled_count"], 120)
                restored = sampling_task_state.build_staging_state_from_saved(loaded)
                self.assertEqual(restored["id_mapping"], {11: 101})
                self.assertEqual(restored["next_id_state"], [102])
            finally:
                if old_settings_dir is None:
                    os.environ.pop(settings_logic.APP_SETTINGS_DIR_ENV, None)
                else:
                    os.environ[settings_logic.APP_SETTINGS_DIR_ENV] = old_settings_dir

    def test_cleanup_completed_states_removes_only_expired_completed_files(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            def write_state(name, status, updated_at):
                path = tmp_path / name
                path.write_text(
                    textwrap.dedent(f"""\
                    {{
                      "schema_version": 1,
                      "status": "{status}",
                      "identity": {{}},
                      "updated_at": "{updated_at}"
                    }}
                    """),
                    encoding="utf-8",
                )
                return path

            old_completed = write_state("old_completed.json", "completed", "2026-01-01T00:00:00Z")
            recent_completed = write_state("recent_completed.json", "completed", "2026-01-19T00:00:00Z")
            old_running = write_state("old_running.json", "running", "2026-01-01T00:00:00Z")
            old_failed = write_state("old_failed.json", "failed", "2026-01-01T00:00:00Z")

            removed = sampling_task_state.cleanup_completed_states(
                max_age_days=7,
                base_dir=tmp_path,
                now=sampling_task_state.parse_utc_text("2026-01-20T00:00:00Z"),
            )

            self.assertEqual(removed, [old_completed])
            self.assertFalse(old_completed.exists())
            self.assertTrue(recent_completed.exists())
            self.assertTrue(old_running.exists())
            self.assertTrue(old_failed.exists())


class RuleImportPreviewTests(unittest.TestCase):
    def test_rule_import_preview_summarizes_imported_sections(self):
        preview = slot_app_settings.build_rule_import_preview({
            "rule_schema_version": 1,
            "trigger_weights": {"special_0": 100},
            "rebate_rules": {"1": [], "2": []},
            "sampling_options": {"append_mode": True, "detailed_log": True},
            "group_weight_rules": {"1": [], "99": []},
            "group_weight_options": {
                "buy_groups": [
                    {"enabled": True, "game_type": 99, "multiplier": 75, "source_suffix": "free_formation"},
                ],
            },
            "direct_count_modes": ["1"],
        })

        self.assertIn("规则文件版本：1", preview)
        self.assertIn("采样规则：2 个模式", preview)
        self.assertNotIn("采样写入模式", preview)
        self.assertIn("采样详细日志：开启", preview)
        self.assertIn("group_weight 权重规则：2 个模式", preview)
        self.assertIn("购买局配置：1 个购买局配置", preview)
        self.assertIn("不会修改厂商、游戏编号、源库、目标库、配置库", preview)


class SamplingEntryPointsTests(unittest.TestCase):
    def test_call_core_function_syncs_before_calling(self):
        events = []
        module = SimpleNamespace(run=lambda value: events.append(("run", value)) or "ok")

        result = sampling_entrypoints.call_core_function(
            lambda: events.append("sync"),
            module,
            "run",
            7,
        )

        self.assertEqual(result, "ok")
        self.assertEqual(events, ["sync", ("run", 7)])


class CommonConfigTests(unittest.TestCase):
    def test_common_config_runner_summarizes_results(self):
        calls = []
        deps = SimpleNamespace(
            check_cancelled=lambda: calls.append("check"),
            print_section=lambda title: calls.append(("section", title)),
            print_result_summary=lambda title, results, skipped_value=None: calls.append(
                ("summary", title, results, skipped_value)
            ),
            special_weight_table="special",
            free_game_config_table="free",
            bet_amount_table="bet",
            write_special_weight_config=lambda: True,
            write_free_game_config=lambda: "skipped",
            write_bet_amount_config=lambda: False,
        )
        result = common_config_runner.write_common_configs(deps=deps)
        self.assertEqual(result, {"special": True, "free": "skipped", "bet": False})
        self.assertEqual(calls[0], "check")

    def test_common_config_entrypoints_build_writer_deps(self):
        runtime = SimpleNamespace(
            game_id="100",
            final_db="FINAL",
            weight_config_db="CFG",
            game_table_prefix="pg_100_",
            weight_type_id=7,
            special_weight_by_last_digit={0: 10},
            free_weight_by_last_digit={0: 20},
        )
        constants = SimpleNamespace(
            weight_group_ids=(9000,),
            special_weight_table="special",
            free_game_config_table="free",
            bet_amount_table="bet",
        )
        deps = SimpleNamespace(
            connect_to_database=lambda *_args: None,
            quote_identifier=lambda value, *_args: value,
            validate_sql_identifier=lambda value, *_args: value,
            rollback_safely=lambda *_args: None,
            close_safely=lambda *_args: None,
            print_step_error=lambda *_args: None,
        )
        writer_deps = common_config_entrypoints.build_writer_deps(runtime, constants, deps)
        self.assertIsInstance(writer_deps, common_config_entrypoints.WriterDeps)
        self.assertEqual(writer_deps.game_id, "100")
        self.assertEqual(writer_deps.special_weight_table, "special")

    def test_common_config_missing_formation_tables_are_skipped(self):
        from formation_tool.common import common_config_writer

        deps = SimpleNamespace(
            game_id="49",
            final_db="FINAL",
            weight_config_db="CFG",
            game_table_prefix="jili_49_",
            weight_type_id=1,
            weight_group_ids=(9000,),
            special_weight_by_last_digit={0: 100},
            free_weight_by_last_digit={0: 50},
            special_weight_table="game_group_special_weight_config",
            free_game_config_table="game_group_free_game_config",
            connect_to_database=lambda *_args: None,
            validate_sql_identifier=lambda value, *_args: value,
            close_safely=lambda *_args: None,
        )

        self.assertEqual(common_config_writer.write_special_weight_config(deps), "skipped")
        self.assertEqual(common_config_writer.write_free_game_config(deps), "skipped")

    def test_common_config_entrypoints_build_typed_runner_deps(self):
        constants = common_config_entrypoints.CommonConfigConstants(
            weight_group_ids=(9000,),
            special_weight_table="special",
            free_game_config_table="free",
            bet_amount_table="bet",
        )
        task_deps = common_config_entrypoints.RunnerTaskDeps(
            check_cancelled=lambda: None,
            print_section=lambda _title: None,
            print_result_summary=lambda *_args, **_kwargs: None,
        )
        writer_deps = common_config_entrypoints.RunnerWriterDeps(
            write_special_weight_config=lambda: True,
            write_free_game_config=lambda: True,
            write_bet_amount_config=lambda: True,
        )

        deps = common_config_entrypoints.build_runner_deps(constants, task_deps, writer_deps)

        self.assertIsInstance(deps, common_config_entrypoints.RunnerDeps)
        self.assertEqual(deps.bet_amount_table, "bet")


class SlotAppDepsTests(unittest.TestCase):
    def build_task_header_app(self):
        class FakeTaskHeaderApp(slot_app_tasks.SlotAppTaskMixin):
            def __init__(self):
                self.messages = []
                self.task_deps = SimpleNamespace(
                    get_runtime_state=lambda: {
                        "vendor": "jili",
                        "game_id": "106",
                        "source_db": "SRC",
                        "final_db": "DST",
                        "config_db": "CFG",
                    },
                    get_external_config_source=lambda: None,
                    get_external_config_load_error=lambda: None,
                    get_trigger_weights=lambda: {
                        "special_0": 100,
                        "special_1": 200,
                        "free_0": 50,
                        "free_1": 100,
                    },
                    get_rebate_rules=lambda: {
                        "1": [{}],
                        "2": [{}],
                        "3": [],
                        "6": [{}],
                        "7": [],
                        "8": [],
                    },
                    get_sampling_append_mode=lambda: False,
                    get_sampling_detailed_log=lambda: False,
                    get_direct_count_modes=lambda: set(),
                    get_direct_count_tiers=lambda: [{"rebate": 0, "count": 5000}],
                    get_game_configs=lambda: {"1": {"name": "普通局"}},
                    get_group_weight_rules=lambda: {"1": [{}], "99": [{}]},
                    get_special_group_target_rtp=lambda: 6,
                    get_buy_group_enabled=lambda: True,
                    get_buy_group_multiplier=lambda: 43,
                    get_buy_group_game_type=lambda: 99,
                    get_buy_group_source_suffix=lambda: "free_formation",
                    get_extra_buy_groups=lambda: [],
                    format_weighted_rtp=lambda value: f"{value:g}",
                    get_ex_group_multiplier=lambda: 1.5,
                    get_ex_buy_group_enabled=lambda: False,
                    get_ex_source_suffixes=lambda: {},
                )

            def append_log(self, message):
                self.messages.append(message)

        return FakeTaskHeaderApp()

    def test_rebate_config_task_header_excludes_group_weight_and_purchase_logs(self):
        app = self.build_task_header_app()

        app.append_task_header_log(
            "生成采样配置",
            preflight={"kind": "rebate_config", "modes": ["1"]},
        )
        text = "".join(app.messages)

        self.assertIn("采样规则：", text)
        self.assertIn("直接计数阶梯", text)
        self.assertNotIn("group_weight区间", text)
        self.assertNotIn("购买局：", text)
        self.assertNotIn("ex模式：", text)
        self.assertNotIn("权重配置：", text)

    def test_slot_app_context_reports_missing_module_attrs(self):
        runtime = SimpleNamespace(**{
            name: None
            for name in slot_app_context.REQUIRED_RUNTIME_ATTRS
        })
        module = SimpleNamespace(_VENDOR_TYPE_MAP={})

        with self.assertRaisesRegex(AttributeError, "RANDOM_SEED"):
            slot_app_context.build_slot_app_deps_context(runtime, module)

    def test_slot_app_context_reads_buy_options_from_live_runtime(self):
        runtime = SimpleNamespace(**{
            name: None
            for name in slot_app_context.REQUIRED_RUNTIME_ATTRS
        })
        runtime.database_configs = {}
        runtime.runtime_dict = lambda: {
            "vendor": "jili",
            "game_id": "523",
            "source_db": "HX",
            "final_db": "DB1",
            "config_db": "MY",
        }
        runtime.trigger_weights_dict = lambda: {}
        runtime.buy_group_enabled = False
        runtime.buy_group_game_type = 99
        runtime.buy_group_multiplier = 50
        runtime.buy_group_source_suffix = "free_formation"
        runtime.extra_buy_groups = []
        runtime.extra_weight_groups = []
        runtime.ex_buy_group_enabled = False
        runtime.ex_group_multiplier = 1.5
        runtime.ex_source_suffixes = {}
        runtime.rebate_rules = {}
        runtime.sampling_append_mode = False
        runtime.sampling_detailed_log = False
        runtime.group_weight_rules = {}
        runtime.special_group_target_rtp = None
        runtime.rebate_config_direct_count_modes = set()
        runtime.external_config_source = None
        runtime.external_config_load_error = None
        runtime.game_configs = {}
        runtime.source_db = "HX"

        module_values = {
            name: (lambda *_args, **_kwargs: None)
            for name in slot_app_context.REQUIRED_MODULE_ATTRS
        }
        module_values.update({
            "_VENDOR_TYPE_MAP": {},
            "RANDOM_SEED": 108,
            "DEFAULT_TRIGGER_WEIGHTS": {},
            "DEFAULT_SAMPLING_APPEND_MODE": False,
            "DEFAULT_SAMPLING_DETAILED_LOG": False,
            "DEFAULT_SAMPLING_USE_TEMP_DB": True,
            "DEFAULT_SAMPLING_TEMP_DB": "MY",
            "DEFAULT_SAMPLING_AUTO_SYNC_TO_TARGET": False,
            "DEFAULT_BUY_GROUP_ENABLED": False,
            "DEFAULT_EX_BUY_GROUP_ENABLED": False,
            "DEFAULT_BUY_GROUP_GAME_TYPE": 99,
            "DEFAULT_BUY_GROUP_MULTIPLIER": 50,
            "DEFAULT_BUY_GROUP_SOURCE_SUFFIX": "free_formation",
            "DEFAULT_EX_GROUP_MULTIPLIER": 1.5,
            "DEFAULT_EXTRA_BUY_GROUPS": [],
            "DEFAULT_EXTRA_WEIGHT_GROUPS": [],
            "DEFAULT_REBATE_RULES": {},
            "DEFAULT_REBATE_CONFIG_DIRECT_COUNT_TIERS": [],
            "DEFAULT_GROUP_WEIGHT_RULES": {},
            "DEFAULT_SPECIAL_GROUP_TARGET_RTP": None,
            "get_runtime_game_configs": lambda: {},
            "get_runtime_sample_game_type_names": lambda: {},
            "get_runtime_rebate_rules": lambda: {},
            "get_runtime_default_rebate_rules": lambda: {},
            "clone_runtime_rebate_rules": lambda rules: dict(rules),
            "validate_runtime_rebate_rules": lambda rules: rules,
            "clone_extra_weight_groups": lambda groups: [dict(group) for group in groups],
            "normalize_extra_weight_groups": lambda groups: [dict(group) for group in groups],
            "WEIGHT_GROUP_IDS": (),
            "GROUP_WEIGHT_MODES": (),
            "GROUP_WEIGHT_UI_MODES": (),
            "EX_GROUP_MODES": (),
            "EX_INDEPENDENT_GROUP_WEIGHT_MODES": (),
            "EX_PURCHASE_MODE": "98",
            "BUY_GROUP_MODE": "99",
            "GAME_TYPE_NAMES": {},
            "GROUP_WEIGHT_RULE_FIELDS": (),
            "GROUP_WEIGHT_RULE_FIELD_LABELS": {},
            "build_group_weight_preview_points": lambda *_args, **_kwargs: [],
        })
        module = SimpleNamespace(**module_values)
        ctx = slot_app_context.build_slot_app_deps_context(runtime, module)

        runtime.buy_group_enabled = True
        runtime.buy_group_game_type = 91
        runtime.buy_group_multiplier = 45
        runtime.buy_group_source_suffix = "special_formation"

        self.assertTrue(ctx.get_buy_group_enabled())
        self.assertEqual(ctx.get_buy_group_game_type(), 91)
        self.assertEqual(ctx.get_buy_group_multiplier(), 45)
        self.assertEqual(ctx.get_buy_group_source_suffix(), "special_formation")
        self.assertTrue(ctx.default_sampling_use_temp_db)
        self.assertEqual(ctx.default_sampling_temp_db, "MY")
        self.assertFalse(ctx.default_sampling_auto_sync_to_target)
        self.assertFalse(ctx.get_sampling_auto_sync_to_target())

        settings_deps = slot_app_deps.build_settings_deps(ctx)
        self.assertTrue(settings_deps.default_sampling_use_temp_db)
        self.assertEqual(settings_deps.default_sampling_temp_db, "MY")
        self.assertFalse(settings_deps.default_sampling_auto_sync_to_target)
        self.assertFalse(settings_deps.get_sampling_auto_sync_to_target())

    def test_process_app_deps_include_gui_entrypoints(self):
        ctx = SimpleNamespace(
            get_runtime_state=lambda: {
                "vendor": "pg",
                "game_id": "100",
                "source_db": "SRC",
                "final_db": "DST",
                "config_db": "CFG",
            },
            weight_group_ids=(9000,),
            group_weight_modes=("1", "99"),
            group_weight_ui_modes=("1", "99"),
            ex_group_modes=(),
            ex_independent_group_weight_modes=(),
            ex_purchase_mode="98",
            buy_group_mode="99",
            game_type_names={"1": "普通局", "99": "购买局"},
            group_weight_rule_fields=("rebate_min", "weight"),
            group_weight_rule_field_labels={"rebate_min": "rebate下限", "weight": "权重"},
            get_group_weight_rules=lambda: {"1": [], "99": []},
            default_group_weight_rules={"1": [], "99": []},
            default_buy_group_game_type=99,
            default_buy_group_source_suffix="free_formation",
            clone_group_weight_rules=lambda rules: {key: list(value) for key, value in rules.items()},
            get_special_group_target_rtp=lambda: 6,
            get_buy_group_enabled=lambda: True,
            get_buy_group_game_type=lambda: 99,
            get_buy_group_multiplier=lambda: 75,
            get_buy_group_source_suffix=lambda: "free_formation",
            get_ex_group_multiplier=lambda: 1.5,
            get_ex_source_suffixes=lambda: {},
            get_extra_buy_groups=lambda: [],
            clone_extra_buy_groups=lambda groups: list(groups),
            get_group_weight_formation_exists=lambda: {"1": True},
            load_group_weight_preview_rebates=lambda **_kwargs: ({}, {}),
            get_displayed_group_weight_modes=lambda _exists: ("1",),
            collect_group_weight_preview_warnings=lambda *_args: [],
            get_group_weight_mode_name=lambda mode: {"1": "普通局", "99": "购买局"}[mode],
            is_extra_buy_mode=lambda _mode: False,
            get_extra_buy_group_by_mode=lambda _mode: None,
            get_buy_group_game_type_for_mode=lambda _mode: 99,
            get_group_weight_write_game_type=lambda _mode: 99,
            get_buy_group_source_suffix_for_mode=lambda _mode: "free_formation",
            get_extra_buy_game_type=lambda _mode: 100,
            make_extra_buy_mode=lambda game_type: f"extra_buy:{game_type}",
            has_extra_buy_groups=lambda: False,
            format_weighted_rtp=lambda value: f"{value:g}",
            format_group_rtp_option=lambda group_id: str(group_id),
            get_group_target_rtp_value=lambda group_id: group_id / 100,
            parse_non_negative_int_text=lambda text, _label: int(text),
            parse_positive_float_text=lambda text, _label: float(text),
            build_group_weight_preview_text=lambda *_args, **_kwargs: "ok",
            build_group_weight_preview_points=lambda *_args, **_kwargs: [],
            validate_group_weight_rules=lambda rules: rules,
            normalize_extra_buy_groups=lambda groups: groups,
            apply_special_group_target_rtp=lambda _value: None,
            apply_group_weight_rules_config=lambda _rules: None,
            apply_extra_buy_groups_config=lambda _groups: None,
            generate_group_weight_config=lambda: True,
        )
        app_deps = slot_app_deps.build_process_app_deps(ctx)

        self.assertIsInstance(app_deps, slot_app_deps.ProcessAppDeps)
        self.assertEqual(app_deps.build_deps_context(), ctx)
        self.assertIn("pg_100", app_deps.get_ready_status_text())
        dialog_deps = app_deps.build_group_weight_dialog_deps()
        self.assertIsInstance(dialog_deps, slot_app_deps.GroupWeightDialogDeps)
        self.assertEqual(dialog_deps.group_weight_modes, ("1", "99"))
        self.assertEqual(dialog_deps.rules, {"1": [], "99": []})
        self.assertEqual(dialog_deps.format_weighted_rtp(75), "75")
        self.assertIn(
            "75",
            group_weight_ui_text.build_mode_option_note("99", dialog_deps),
        )

    def test_ex_purchase_note_uses_resolved_source_suffix(self):
        deps = SimpleNamespace(
            ex_group_modes=("6", "7", "8"),
            ex_purchase_mode="98",
            buy_group_mode="99",
            game_type_names={"98": "ex购买局"},
            get_group_weight_write_game_type=lambda _mode: 98,
            get_buy_group_source_suffix_for_mode=lambda _mode: "formation",
            format_weighted_rtp=lambda value: f"{value:g}",
            buy_multiplier=5,
            ex_multiplier=1.5,
            is_extra_buy_mode=lambda _mode: False,
        )

        note = group_weight_ui_text.build_mode_option_note("98", deps)

        self.assertIn("formation 的采样配置", note)
        self.assertNotIn("rebate_ex_free_count", note)


class FakeSettingsApp(SlotAppSettingsMixin):
    def __init__(self, deps, master):
        self.settings_deps = deps
        self.vendor_var = tk.StringVar(master=master, value="pg")
        self.game_id_var = tk.StringVar(master=master, value="100")
        self.source_db_var = tk.StringVar(master=master, value="SRC")
        self.final_db_var = tk.StringVar(master=master, value="DST")
        self.config_db_var = tk.StringVar(master=master, value="CFG")
        self.special_weight_0_var = tk.StringVar(master=master, value="10")
        self.special_weight_1_var = tk.StringVar(master=master, value="20")
        self.free_weight_0_var = tk.StringVar(master=master, value="30")
        self.free_weight_1_var = tk.StringVar(master=master, value="40")
        self.sampling_append_mode_var = tk.BooleanVar(master=master, value=False)
        self.sampling_detailed_log_var = tk.BooleanVar(master=master, value=False)
        self.sampling_auto_sync_to_target_var = tk.BooleanVar(master=master, value=False)
        self.sampling_use_temp_db_var = self.sampling_auto_sync_to_target_var
        self.sampling_temp_db_var = tk.StringVar(master=master, value="DST")
        self.buy_group_enabled_var = tk.BooleanVar(master=master, value=False)
        self.ex_buy_group_enabled_var = tk.BooleanVar(master=master, value=False)
        self.ex_buy_game_type_var = tk.StringVar(master=master, value="98")
        self.ex_buy_source_suffix_var = tk.StringVar(master=master, value="")
        self.buy_game_type_var = tk.StringVar(master=master, value="99")
        self.buy_multiplier_var = tk.StringVar(master=master, value="50")
        self.buy_source_suffix_var = tk.StringVar(master=master, value="free_formation")
        self.ex_multiplier_var = tk.StringVar(master=master, value="1.5")
        self.ex_source_suffix_vars = {
            "6": tk.StringVar(master=master, value=""),
            "7": tk.StringVar(master=master, value=""),
            "8": tk.StringVar(master=master, value=""),
        }
        self.status_var = tk.StringVar(master=master, value="")
        self.extra_buy_rows = []
        self.extra_weight_group_rows = []
        self.apply_selected_config_called = False

    def set_extra_buy_group_rows(self, groups):
        self.extra_buy_rows = [dict(group) for group in groups]

    def set_extra_weight_group_rows(self, groups):
        self.extra_weight_group_rows = [dict(group) for group in groups]

    def collect_extra_weight_groups(self):
        return [dict(group) for group in self.extra_weight_group_rows]

    def apply_selected_config(self):
        self.apply_selected_config_called = True
        return True


class SlotAppSettingsPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.original_default_root = tk._default_root
        self.tcl_root = tk.Tcl()
        tk._default_root = self.tcl_root

    def tearDown(self):
        tk._default_root = self.original_default_root

    def test_sampling_temp_db_defaults_to_configured_default_not_final_db(self):
        last_data = settings_logic.build_last_settings_data(
            vendor="pg",
            game_id="100",
            source_db="SRC",
            final_db="DB1",
            config_db="CFG",
        )
        app_data = settings_logic.build_app_settings_data(
            runtime={
                "vendor": "pg",
                "game_id": "100",
                "source_db": "SRC",
                "final_db": "DB1",
                "config_db": "CFG",
            },
            trigger_weights={},
            rebate_rules={},
            sampling_append_mode=False,
            sampling_detailed_log=False,
            group_weight_rules={},
            group_weight_options={},
            direct_count_modes=[],
            direct_count_tiers=[],
        )

        self.assertEqual(last_data["runtime"]["sampling_temp_db"], "MY")
        self.assertTrue(last_data["runtime"]["sampling_use_temp_db"])
        self.assertFalse(last_data["runtime"]["sampling_auto_sync_to_target"])
        self.assertEqual(app_data["sampling_options"]["temp_db"], "MY")
        self.assertTrue(app_data["sampling_options"]["use_temp_db"])
        self.assertFalse(app_data["sampling_options"]["auto_sync_to_target"])

    def test_old_temp_db_switch_does_not_enable_auto_sync(self):
        migrated = settings_logic.migrate_settings_data({
            "version": settings_logic.CURRENT_SETTINGS_VERSION,
            "runtime": {"sampling_temp_db": "MY", "sampling_use_temp_db": True},
            "sampling_options": {"use_temp_db": True, "temp_db": "MY"},
        })

        self.assertTrue(migrated["sampling_options"]["use_temp_db"])
        self.assertFalse(migrated["sampling_options"]["auto_sync_to_target"])

    def test_build_app_settings_data_persists_buy_and_sampling_options(self):
        extra_groups = [
            {"game_type": 120, "multiplier": 80, "source_suffix": "bonus_formation", "rules": []}
        ]
        extra_weight_groups = [
            {"group_id": 9652, "special_weight": 300, "free_weight": 150}
        ]
        deps = SimpleNamespace(
            get_runtime_state=lambda: {
                "vendor": "pg",
                "game_id": "100",
                "source_db": "SRC",
                "final_db": "DST",
                "config_db": "CFG",
            },
            get_trigger_weights=lambda: {
                "special_0": 10,
                "special_1": 20,
                "free_0": 30,
                "free_1": 40,
            },
            get_rebate_rules=lambda: {"1": [{"rebate": 0, "count": 1}]},
            clone_rebate_rules=lambda rules: {key: [dict(item) for item in value] for key, value in rules.items()},
            get_sampling_append_mode=lambda: True,
            get_sampling_detailed_log=lambda: True,
            get_sampling_auto_sync_to_target=lambda: True,
            get_group_weight_rules=lambda: {"99": [{"rebate_min": 0, "weight": 10}]},
            clone_group_weight_rules=lambda rules: {key: [dict(item) for item in value] for key, value in rules.items()},
            get_special_group_target_rtp=lambda: 8.5,
            get_zero_rebate_inference_modes=lambda: {"1", "7"},
            get_independent_rtp_modes=lambda: {"1", "6"},
            get_buy_group_enabled=lambda: True,
            get_ex_buy_group_enabled=lambda: True,
            get_ex_buy_group_game_type=lambda: 98,
            get_ex_buy_group_source_suffix=lambda: "ex_free_formation",
            get_buy_group_game_type=lambda: 99,
            get_buy_group_multiplier=lambda: 50,
            get_buy_group_source_suffix=lambda: "free_formation",
            get_ex_group_multiplier=lambda: 1.5,
            get_ex_source_suffixes=lambda: {"6": "manual_ex_formation"},
            get_extra_buy_groups=lambda: extra_groups,
            clone_extra_buy_groups=lambda groups: [dict(group) for group in groups],
            get_extra_weight_groups=lambda: extra_weight_groups,
            clone_extra_weight_groups=lambda groups: [dict(group) for group in groups],
            get_direct_count_modes=lambda: {"1", "6"},
            get_direct_count_tiers=lambda: [{"rebate_min": 1, "rebate_max": 999, "count": 88}],
        )
        app = FakeSettingsApp(deps, self.tcl_root)

        data = app.build_app_settings_data()

        self.assertNotIn("append_mode", data["sampling_options"])
        self.assertTrue(data["sampling_options"]["detailed_log"])
        self.assertTrue(data["sampling_options"]["use_temp_db"])
        self.assertTrue(data["sampling_options"]["auto_sync_to_target"])
        self.assertEqual(data["group_weight_options"]["buy_game_type"], 99)
        self.assertEqual(data["group_weight_options"]["ex_buy_game_type"], 98)
        self.assertEqual(data["group_weight_options"]["ex_buy_source_suffix"], "ex_free_formation")
        self.assertEqual(data["group_weight_options"]["buy_multiplier"], 50)
        self.assertEqual(data["group_weight_options"]["buy_source_suffix"], "free_formation")
        self.assertEqual(data["group_weight_options"]["zero_rebate_inference_modes"], ["1", "7"])
        self.assertEqual(data["group_weight_options"]["independent_rtp_modes"], ["1", "6"])
        self.assertEqual(data["group_weight_options"]["ex_source_suffixes"], {"6": "manual_ex_formation"})
        self.assertEqual(data["group_weight_options"]["extra_buy_groups"], extra_groups)
        self.assertEqual(data["group_weight_options"]["extra_weight_groups"], extra_weight_groups)
        self.assertEqual(data["group_weight_options"]["buy_groups"][0]["game_type"], 99)
        self.assertEqual(data["group_weight_options"]["buy_groups"][1]["game_type"], 120)
        self.assertEqual(set(data["direct_count_modes"]), {"1", "6"})
        self.assertEqual(data["direct_count_tiers"], [{"rebate_min": 1, "rebate_max": 999, "count": 88}])

    def test_apply_app_settings_data_restores_buy_and_extra_buy_options(self):
        calls = []
        extra_groups = [
            {"game_type": 120, "multiplier": 80, "source_suffix": "bonus_formation", "rules": []}
        ]
        extra_weight_groups = [
            {"group_id": 9652, "special_weight": 300, "free_weight": 150}
        ]
        deps = SimpleNamespace(
            clear_config_warnings=lambda: calls.append(("clear", None)),
            get_buy_group_enabled=lambda: False,
            get_ex_buy_group_enabled=lambda: False,
            get_ex_buy_group_game_type=lambda: 98,
            get_ex_buy_group_source_suffix=lambda: "",
            get_buy_group_game_type=lambda: 99,
            get_buy_group_multiplier=lambda: 50,
            get_buy_group_source_suffix=lambda: "free_formation",
            get_ex_group_multiplier=lambda: 1.5,
            get_ex_source_suffixes=lambda: {},
            get_extra_buy_groups=lambda: [],
            get_extra_weight_groups=lambda: [],
            normalize_rebate_rules_for_load=lambda rules: {"normalized": rules},
            apply_rebate_rules_config=lambda rules: calls.append(("rebate", rules)),
            normalize_group_weight_rules_for_load=lambda rules: {"normalized": rules},
            apply_group_weight_rules_config=lambda rules: calls.append(("group_rules", rules)),
            apply_extra_buy_groups_config=lambda groups: calls.append(("extra", [dict(group) for group in groups])),
            apply_extra_weight_groups_config=lambda groups: calls.append(
                ("extra_weight", [dict(group) for group in groups])
            ),
            apply_special_group_target_rtp=lambda value: calls.append(("special_rtp", value)),
            apply_zero_rebate_inference_modes_config=lambda modes: calls.append(("zero_infer", list(modes))),
            apply_independent_rtp_modes_config=lambda modes: calls.append(("independent_rtp", list(modes))),
            apply_rebate_config_direct_count_modes=lambda modes: calls.append(("direct", list(modes))),
            normalize_direct_count_tiers_for_load=lambda tiers: [dict(rule) for rule in tiers],
            apply_rebate_config_direct_count_tiers=lambda tiers: calls.append(("direct_tiers", [dict(rule) for rule in tiers])),
        )
        app = FakeSettingsApp(deps, self.tcl_root)
        data = settings_logic.build_app_settings_data(
            runtime={
                "vendor": "jili",
                "game_id": "49",
                "source_db": "JJ",
                "final_db": "DB1",
                "config_db": "MY",
            },
            trigger_weights={"special_0": 11, "special_1": 22, "free_0": 33, "free_1": 44},
            rebate_rules={"1": [{"rebate": 0, "count": 2}]},
            sampling_append_mode=True,
            sampling_detailed_log=True,
            sampling_auto_sync_to_target=True,
            group_weight_rules={"99": [{"rebate_min": 0, "weight": 9}]},
            group_weight_options={
                "special_target_rtp": 7.25,
                "zero_rebate_inference_modes": ["1", "7"],
                "independent_rtp_modes": ["1", "6"],
                "buy_enabled": True,
                "ex_buy_enabled": True,
                "ex_buy_game_type": 198,
                "ex_buy_source_suffix": "custom_ex_buy_formation",
                "buy_game_type": 120,
                "buy_multiplier": 60,
                "buy_source_suffix": "custom_free_formation",
                "ex_multiplier": 1.6,
                "ex_source_suffixes": {"6": "custom_ex_formation", "8": "custom_ex_free_formation"},
                "extra_buy_groups": extra_groups,
                "extra_weight_groups": extra_weight_groups,
            },
            direct_count_modes=["1", "6"],
            direct_count_tiers=[{"rebate_min": 1, "rebate_max": 999, "count": 88}],
        )

        app.apply_app_settings_data(data)

        self.assertEqual(app.vendor_var.get(), "jili")
        self.assertEqual(app.game_id_var.get(), "49")
        self.assertEqual(app.buy_game_type_var.get(), "120")
        self.assertEqual(app.ex_buy_game_type_var.get(), "198")
        self.assertEqual(app.ex_buy_source_suffix_var.get(), "custom_ex_buy_formation")
        self.assertEqual(app.buy_multiplier_var.get(), "60")
        self.assertEqual(app.buy_source_suffix_var.get(), "custom_free_formation")
        self.assertTrue(app.sampling_detailed_log_var.get())
        self.assertTrue(app.sampling_auto_sync_to_target_var.get())
        self.assertEqual(app.ex_source_suffix_vars["6"].get(), "custom_ex_formation")
        self.assertEqual(app.ex_source_suffix_vars["8"].get(), "custom_ex_free_formation")
        self.assertEqual(app.extra_buy_rows, extra_groups)
        self.assertEqual(app.extra_weight_group_rows, extra_weight_groups)
        self.assertTrue(app.apply_selected_config_called)
        self.assertIn(("special_rtp", 7.25), calls)
        self.assertIn(("zero_infer", ["1", "7"]), calls)
        self.assertIn(("independent_rtp", ["1", "6"]), calls)
        self.assertIn(("direct", ["1", "6"]), calls)
        self.assertIn(("direct_tiers", [{"rebate_min": 1, "rebate_max": 999, "count": 88}]), calls)
        self.assertIn(("extra", extra_groups), calls)
        self.assertIn(("extra_weight", extra_weight_groups), calls)

    def test_buy_group_load_summary_and_skip_details_include_missing_tables(self):
        deps = SimpleNamespace()
        app = FakeSettingsApp(deps, self.tcl_root)
        options = {
            "normal_buy_game_types": [91, 92],
            "ex_buy_game_types": [98],
            "skipped": [
                {
                    "game_type": 93,
                    "source_suffix": "buy3_special_formation",
                    "table_name": "jili_523_buy3_special_formation",
                }
            ],
        }

        summary = app.build_buy_group_load_summary(options)
        details = app.build_buy_group_skip_details(options)

        self.assertIn("91", summary)
        self.assertIn("98", summary)
        self.assertIn("1", summary)
        self.assertIn("game_type=93", details)
        self.assertIn("jili_523_buy3_special_formation", details)

    def test_apply_loaded_buy_group_options_updates_ui_and_runtime(self):
        calls = []
        deps = SimpleNamespace(
            apply_buy_group_enabled=lambda value: calls.append(("enabled", value)),
            apply_buy_group_game_type=lambda value: calls.append(("game_type", value)),
            apply_buy_group_multiplier=lambda value: calls.append(("multiplier", value)),
            apply_buy_group_source_suffix=lambda value: calls.append(("suffix", value)),
            apply_ex_buy_group_enabled=lambda value: calls.append(("ex_enabled", value)),
            apply_ex_buy_group_game_type=lambda value: calls.append(("ex_game_type", value)),
            apply_ex_buy_group_source_suffix=lambda value: calls.append(("ex_suffix", value)),
            apply_extra_buy_groups_config=lambda groups: calls.append(("extra", [dict(item) for item in groups])),
        )
        app = FakeSettingsApp(deps, self.tcl_root)
        app.collect_extra_buy_groups = lambda: app.extra_buy_rows
        options = {
            "default_buy": {
                "enabled": True,
                "game_type": 91,
                "multiplier": 75,
                "source_suffix": "special_formation",
            },
            "ex_buy_enabled": True,
            "ex_buy": {
                "enabled": True,
                "game_type": 198,
                "source_suffix": "custom_ex_buy_formation",
            },
            "extra_buy_groups": [
                {"game_type": 92, "multiplier": 65, "source_suffix": "buy2_special_formation"}
            ],
        }

        self.assertTrue(app.apply_loaded_buy_group_options(options))

        self.assertTrue(app.buy_group_enabled_var.get())
        self.assertEqual(app.buy_game_type_var.get(), "91")
        self.assertEqual(app.ex_buy_game_type_var.get(), "198")
        self.assertEqual(app.ex_buy_source_suffix_var.get(), "custom_ex_buy_formation")
        self.assertEqual(app.buy_multiplier_var.get(), "75")
        self.assertEqual(app.buy_source_suffix_var.get(), "special_formation")
        self.assertTrue(app.ex_buy_group_enabled_var.get())
        self.assertIn(("game_type", "91"), calls)
        self.assertIn(("ex_game_type", "198"), calls)
        self.assertIn(("ex_suffix", "custom_ex_buy_formation"), calls)
        self.assertIn(("extra", options["extra_buy_groups"]), calls)


class SamplingAutoSyncTests(unittest.TestCase):
    def test_all_sampling_auto_syncs_only_successful_modes(self):
        module = importlib.import_module("formation_tool.process_formation_slots_way_combined")
        saved = {
            "SAMPLING_AUTO_SYNC_TO_TARGET": module.SAMPLING_AUTO_SYNC_TO_TARGET,
            "FINAL_DB": module.FINAL_DB,
            "build_all_sampling_jobs_deps": module.build_all_sampling_jobs_deps,
            "run_all_sampling_jobs": module.task_entrypoints.run_all_sampling_jobs,
            "build_sampling_temp_sync_items": module.build_sampling_temp_sync_items,
            "sync_sampling_temp_results": module.sync_sampling_temp_results,
        }
        calls = []
        try:
            module.SAMPLING_AUTO_SYNC_TO_TARGET = True
            module.FINAL_DB = "DB1"
            module.build_all_sampling_jobs_deps = lambda: object()
            module.task_entrypoints.run_all_sampling_jobs = lambda *, deps: {
                "1": True,
                "2": False,
                "3": None,
            }
            module.build_sampling_temp_sync_items = (
                lambda modes, existing_only=False: calls.append(("items", list(modes), existing_only))
                or [{"table_name": "pg_1_formation"}]
            )
            module.sync_sampling_temp_results = (
                lambda items: calls.append(("sync", [dict(item) for item in items])) or {"pg_1_formation": True}
            )

            with contextlib.redirect_stdout(io.StringIO()):
                result = module.run_all_sampling_jobs()
        finally:
            module.SAMPLING_AUTO_SYNC_TO_TARGET = saved["SAMPLING_AUTO_SYNC_TO_TARGET"]
            module.FINAL_DB = saved["FINAL_DB"]
            module.build_all_sampling_jobs_deps = saved["build_all_sampling_jobs_deps"]
            module.task_entrypoints.run_all_sampling_jobs = saved["run_all_sampling_jobs"]
            module.build_sampling_temp_sync_items = saved["build_sampling_temp_sync_items"]
            module.sync_sampling_temp_results = saved["sync_sampling_temp_results"]

        self.assertEqual(result, {"1": True, "2": False, "3": None})
        self.assertEqual(calls[0], ("items", ["1"], True))
        self.assertEqual(calls[1], ("sync", [{"table_name": "pg_1_formation"}]))

    def test_single_sampling_auto_syncs_selected_mode_after_success(self):
        module = importlib.import_module("formation_tool.process_formation_slots_way_combined")
        saved = {
            "SAMPLING_AUTO_SYNC_TO_TARGET": module.SAMPLING_AUTO_SYNC_TO_TARGET,
            "get_runtime_game_configs": module.get_runtime_game_configs,
            "run_single_game": module.run_single_game,
            "build_sampling_temp_sync_items": module.build_sampling_temp_sync_items,
            "sync_sampling_temp_results": module.sync_sampling_temp_results,
        }
        calls = []
        try:
            module.SAMPLING_AUTO_SYNC_TO_TARGET = True
            module.get_runtime_game_configs = lambda: {"2": {"name": "特殊局"}}
            module.run_single_game = lambda config: calls.append(("sample", config["name"])) or True
            module.build_sampling_temp_sync_items = (
                lambda modes, existing_only=False: calls.append(("items", list(modes), existing_only))
                or [{"table_name": "pg_1_special_formation"}]
            )
            module.sync_sampling_temp_results = (
                lambda items: calls.append(("sync", [dict(item) for item in items])) or {"pg_1_special_formation": True}
            )

            with contextlib.redirect_stdout(io.StringIO()):
                result = module.run_single_game_job("2")
        finally:
            module.SAMPLING_AUTO_SYNC_TO_TARGET = saved["SAMPLING_AUTO_SYNC_TO_TARGET"]
            module.get_runtime_game_configs = saved["get_runtime_game_configs"]
            module.run_single_game = saved["run_single_game"]
            module.build_sampling_temp_sync_items = saved["build_sampling_temp_sync_items"]
            module.sync_sampling_temp_results = saved["sync_sampling_temp_results"]

        self.assertTrue(result)
        self.assertEqual(calls[0], ("sample", "特殊局"))
        self.assertEqual(calls[1], ("items", ["2"], True))
        self.assertEqual(calls[2], ("sync", [{"table_name": "pg_1_special_formation"}]))


class BuildFormationExeTests(unittest.TestCase):
    def test_parse_args_supports_existing_modes(self):
        check_args = build_formation_exe.parse_args(["--check", "--test"])
        self.assertTrue(check_args.check)
        self.assertTrue(check_args.test)

        list_args = build_formation_exe.parse_args(["--list-modules"])
        self.assertTrue(list_args.list_modules)

    def test_parse_args_rejects_conflicting_modes(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                build_formation_exe.parse_args(["--clean", "--test"])
            with self.assertRaises(SystemExit):
                build_formation_exe.parse_args(["--list-modules", "--check"])

    def test_module_manifest_is_complete_for_split_packages(self):
        self.assertEqual(build_formation_exe.collect_module_manifest_errors(), [])
        self.assertIn(
            "formation_tool.group_weight.group_weight_logic",
            build_formation_exe.FORMATION_TOOL_ENCRYPTED_MODULES,
        )
        self.assertIn(
            "formation_tool.ui.ui_layout_defaults",
            build_formation_exe.FORMATION_TOOL_ENCRYPTED_MODULES,
        )
        self.assertIn(
            "formation_tool.ui.slot_app_entrypoints",
            build_formation_exe.FORMATION_TOOL_ENCRYPTED_MODULES,
        )
        self.assertIn(
            "formation_tool.core.task_entrypoints",
            build_formation_exe.FORMATION_TOOL_ENCRYPTED_MODULES,
        )
        self.assertIn(
            "formation_tool.db.db_entrypoints",
            build_formation_exe.FORMATION_TOOL_ENCRYPTED_MODULES,
        )
        self.assertIn(
            "formation_tool.ui.buy_group_ui",
            build_formation_exe.FORMATION_TOOL_ENCRYPTED_MODULES,
        )
        self.assertIn(
            "formation_tool.ui.external_config_status",
            build_formation_exe.FORMATION_TOOL_ENCRYPTED_MODULES,
        )
        self.assertIn(
            "formation_tool.rebate.rebate_config_entrypoints",
            build_formation_exe.FORMATION_TOOL_ENCRYPTED_MODULES,
        )
        self.assertIn(
            "formation_tool.sampling.sampling_entrypoints",
            build_formation_exe.FORMATION_TOOL_ENCRYPTED_MODULES,
        )
        self.assertFalse(
            any(".test_" in module_name for module_name in build_formation_exe.FORMATION_TOOL_ENCRYPTED_MODULES),
            build_formation_exe.FORMATION_TOOL_ENCRYPTED_MODULES,
        )

    def test_print_encrypted_module_list_outputs_manifest(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            build_formation_exe.print_encrypted_module_list()

        text = output.getvalue()
        self.assertIn("Encrypted module count:", text)
        self.assertIn("formation_tool.ui.ui_layout_defaults", text)

    def test_build_launcher_contains_package_hierarchy_loader(self):
        launcher = build_formation_exe.build_launcher()
        try:
            text = launcher.read_text(encoding="utf-8")
            self.assertIn("def _ensure_package", text)
            self.assertIn("class _EncryptedModuleLoader", text)
            self.assertIn("def _install_encrypted_importer", text)
            self.assertIn("_install_encrypted_importer(base_dir)", text)
            self.assertIn("decode('utf-8-sig')", text)
            self.assertIn("from tkinter import filedialog, messagebox, scrolledtext, ttk", text)
            for module_name in (
                "copy",
                "dataclasses",
                "datetime",
                "functools",
                "hashlib",
                "inspect",
                "numbers",
                "random",
                "typing",
            ):
                self.assertIn(f"import {module_name}  # noqa: F401", text)
            self.assertIn("formation_tool.rebate.rebate_config_storage", text)
            self.assertIn("formation_tool.common.common_config_runner", text)
        finally:
            build_formation_exe.cleanup_temp_launcher()
        self.assertFalse(launcher.exists())

    def test_build_spec_includes_tkinter_hiddenimports(self):
        spec_path = build_formation_exe.build_spec()
        try:
            text = spec_path.read_text(encoding="utf-8")
            for module_name in build_formation_exe.TKINTER_HIDDENIMPORTS:
                self.assertIn(repr(module_name), text)
            self.assertIn("collect_submodules('mysql.connector')", text)
        finally:
            spec_path.unlink(missing_ok=True)
        self.assertFalse(spec_path.exists())

    def test_generated_importer_executes_dependent_encrypted_modules(self):
        launcher = build_formation_exe.build_launcher()
        smoke_script = build_formation_exe.BUILD_ROOT / "launcher_importer_smoke.py"
        script = f"""
import importlib
import pathlib
import tempfile

launcher_path = pathlib.Path({str(launcher)!r})
source = launcher_path.read_text(encoding='utf-8')
namespace = {{
    '__name__': 'launcher_smoke',
    '__file__': str(launcher_path),
    '__builtins__': __builtins__,
}}
exec(source, namespace)
namespace['_MODULE_PAYLOADS'] = (
    ('formation_tool.fake.child', b"VALUE = 'child-ok'\\n"),
    (
        'formation_tool.fake.parent',
        b"from formation_tool.fake.child import VALUE\\nRESULT = VALUE + '-parent'\\n",
    ),
)
namespace['_decrypt'] = lambda payload: payload.decode('utf-8-sig')

with tempfile.TemporaryDirectory() as base_dir:
    namespace['_install_encrypted_importer'](base_dir)
    module = importlib.import_module('formation_tool.fake.parent')
    assert module.RESULT == 'child-ok-parent', module.RESULT
"""
        try:
            smoke_script.write_text(textwrap.dedent(script), encoding="utf-8")
            subprocess.run(
                [sys.executable, str(smoke_script)],
                cwd=str(build_formation_exe.TOOL_ROOT.parent),
                check=True,
                capture_output=True,
                text=True,
            )
        finally:
            smoke_script.unlink(missing_ok=True)
            build_formation_exe.cleanup_temp_launcher()
        self.assertFalse(launcher.exists())

    def test_encrypt_text_strips_utf8_bom(self):
        class FakeFernet:
            def encrypt(self, data):
                return data

        path = build_formation_exe.BUILD_ROOT / "bom_test_source.py"
        build_formation_exe.BUILD_ROOT.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\xef\xbb\xbfprint('ok')\n")
        try:
            encrypted = build_formation_exe.encrypt_text(FakeFernet(), path)
        finally:
            path.unlink(missing_ok=True)
        self.assertEqual(encrypted, b"print('ok')\n")

    def test_stage_existing_output_exe_can_restore_previous_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            exe_path = Path(temp_dir) / "formation.exe"
            exe_path.write_text("old exe", encoding="utf-8")

            staged_path = build_formation_exe.stage_existing_output_exe(exe_path)

            self.assertFalse(exe_path.exists())
            self.assertTrue(staged_path.exists())
            self.assertEqual(staged_path.read_text(encoding="utf-8"), "old exe")

            build_formation_exe.restore_staged_output_exe(staged_path, exe_path)

            self.assertTrue(exe_path.exists())
            self.assertEqual(exe_path.read_text(encoding="utf-8"), "old exe")
            self.assertFalse(staged_path.exists())


class UiLayoutDefaultsTests(unittest.TestCase):
    def test_window_layouts_keep_legacy_constants_in_sync(self):
        self.assertEqual(
            ui_layout_defaults.MAIN_WINDOW_GEOMETRY,
            ui_layout_defaults.MAIN_WINDOW.geometry,
        )
        self.assertEqual(
            ui_layout_defaults.GROUP_WEIGHT_DIALOG_MINSIZE,
            ui_layout_defaults.GROUP_WEIGHT_DIALOG.minsize,
        )

    def test_dialog_layouts_are_larger_than_minimums(self):
        for layout in (
            ui_layout_defaults.GROUP_WEIGHT_DIALOG,
            ui_layout_defaults.REBATE_RULES_DIALOG,
            ui_layout_defaults.SINGLE_SAMPLING_DIALOG,
        ):
            width, height = (int(part) for part in layout.geometry.split("x"))
            min_width, min_height = layout.minsize
            self.assertGreaterEqual(width, min_width)
            self.assertGreaterEqual(height, min_height)


class ExternalConfigStatusTests(unittest.TestCase):
    def test_missing_selected_database_warning_lists_aliases(self):
        missing = external_config_status.find_missing_selected_databases(
            {"MY": {}, "DB1": {}},
            (("源库", "XP1"), ("目标库", "DB1"), ("配置库", "XP1")),
        )

        message = external_config_status.build_missing_database_warning(
            missing,
            external_source="C:/tool/db_config.json",
        )

        self.assertEqual(missing, [("源库", "XP1")])
        self.assertIn("C:/tool/db_config.json", message)
        self.assertIn("- 源库: XP1", message)


class BuyGroupUiTests(unittest.TestCase):
    def test_collect_extra_buy_groups_preserves_existing_rules(self):
        class Var:
            def __init__(self, value):
                self.value = value

            def get(self):
                return self.value

        deps = SimpleNamespace(
            get_extra_buy_groups=lambda: [
                {"game_type": 120, "rules": [{"rebate_min": 0, "weight": 1}]}
            ],
            normalize_extra_buy_groups=lambda groups: groups,
        )
        app = SimpleNamespace(
            ui_deps=deps,
            extra_buy_rows=[
                {
                    "game_type_var": Var("120"),
                    "multiplier_var": Var("50"),
                    "source_suffix_var": Var("free_formation"),
                }
            ],
        )

        groups = buy_group_ui.collect_extra_buy_groups(app)

        self.assertEqual(groups[0]["game_type"], "120")
        self.assertEqual(groups[0]["rules"], [{"rebate_min": 0, "weight": 1}])

    def test_collect_extra_buy_groups_skips_disabled_rows(self):
        class Var:
            def __init__(self, value):
                self.value = value

            def get(self):
                return self.value

        deps = SimpleNamespace(
            get_extra_buy_groups=lambda: [],
            normalize_extra_buy_groups=lambda groups: groups,
        )
        app = SimpleNamespace(
            ui_deps=deps,
            extra_buy_rows=[
                {
                    "enabled_var": Var(False),
                    "game_type_var": Var("120"),
                    "multiplier_var": Var("50"),
                    "source_suffix_var": Var("free_formation"),
                },
                {
                    "enabled_var": Var(True),
                    "game_type_var": Var("121"),
                    "multiplier_var": Var("60"),
                    "source_suffix_var": Var("bonus_formation"),
                },
            ],
        )

        groups = buy_group_ui.collect_extra_buy_groups(app)

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["game_type"], "121")

    def test_delete_default_buy_group_disables_and_resets_defaults(self):
        master = tk.Tcl()
        app = SimpleNamespace(
            settings_deps=SimpleNamespace(
                default_buy_group_game_type=99,
                default_buy_group_multiplier=75,
                default_buy_group_source_suffix="free_formation",
            ),
            buy_group_enabled_var=tk.BooleanVar(master=master, value=True),
            buy_game_type_var=tk.StringVar(master=master, value="91"),
            buy_multiplier_var=tk.StringVar(master=master, value="45"),
            buy_source_suffix_var=tk.StringVar(master=master, value="special_formation"),
        )

        buy_group_ui.delete_default_buy_group(app)

        self.assertFalse(app.buy_group_enabled_var.get())
        self.assertEqual(app.buy_game_type_var.get(), "99")
        self.assertEqual(app.buy_multiplier_var.get(), "75")
        self.assertEqual(app.buy_source_suffix_var.get(), "free_formation")


class GuiDialogSmokeTests(unittest.TestCase):
    def setUp(self):
        self.original_default_root = tk._default_root
        self.tcl_root = tk.Tcl()
        tk._default_root = self.tcl_root
        self.app = SimpleNamespace(root=self.tcl_root, run_task=lambda *_args: None)

    def tearDown(self):
        tk._default_root = self.original_default_root

    def test_dialog_constructors_do_not_require_display(self):
        single_dialog = single_sampling_dialog.SingleSamplingDialog(
            self.app,
            sample_game_type_names={"1": "normal"},
            game_configs={"1": {"table_config": {"SOURCE_TABLE": {"name": "formation"}}}},
            source_db_getter=lambda: "SRC",
            formation_exists_loader=lambda: {"1": True},
            run_single_game_job=lambda *_args: True,
        )
        rebate_dialog = rebate_rules_dialog.RebateRulesDialog(
            self.app,
            sample_game_type_names={"1": "normal"},
            rule_fields=("rebate", "count"),
            rule_field_labels={"rebate": "rebate", "count": "count"},
            low_volume_threshold=200000,
            current_rules_getter=lambda: {"1": []},
            default_rules_getter=lambda: {"1": []},
            clone_rules=lambda rules: dict(rules),
            validate_rules=lambda rules: rules,
            apply_rules=lambda rules: None,
            apply_direct_count_modes=lambda modes: None,
            current_direct_count_tiers_getter=lambda: [],
            default_direct_count_tiers_getter=lambda: [],
            normalize_direct_count_tiers=lambda tiers: tiers,
            apply_direct_count_tiers=lambda tiers: None,
            formation_exists_loader=lambda: {"1": True},
            low_volume_infos_loader=lambda: {},
            generate_configs=lambda: True,
            ready_status_getter=lambda: "ready",
        )
        group_dialog = group_weight_rules_dialog.GroupWeightRulesDialog(
            self.app,
            SimpleNamespace(),
        )

        self.assertEqual(single_dialog.choice_var.get(), "")
        self.assertEqual(rebate_dialog.low_volume_threshold, 200000)
        self.assertIs(group_dialog.deps.__class__, SimpleNamespace)


class GroupWeightRulesDialogTests(unittest.TestCase):
    def test_default_rtp_group_option_prefers_9650_when_available(self):
        formatter = lambda group_id: f"{group_id} - target"

        self.assertEqual(
            group_weight_rules_dialog.choose_default_rtp_group_option(
                [10000, 9900, 9650, 9600],
                formatter,
            ),
            "9650 - target",
        )
        self.assertEqual(
            group_weight_rules_dialog.choose_default_rtp_group_option(
                [10000, 9900],
                formatter,
            ),
            "10000 - target",
        )

    def test_weight_curve_points_are_sorted_and_ignore_invalid_rows(self):
        points = group_weight_rules_dialog.normalize_weight_curve_points([
            {"rebate_min": "3000", "weight": "4"},
            {"rebate_min": "bad", "weight": "9"},
            {"rebate_min": "1000", "weight": "10"},
            {"rebate_min": "3000", "weight": "5"},
            {"rebate_min": "-1", "weight": "1"},
            {"rebate_min": "5000", "weight": "-2"},
        ])

        self.assertEqual(points, [(1000, 10), (3000, 5)])

    def test_weight_curve_can_hide_zero_rebate_point(self):
        points = [(0, 999), (1000, 10), (2000, 5)]

        self.assertEqual(
            group_weight_rules_dialog.filter_weight_curve_points(points, hide_zero_rebate=True),
            [(1000, 10), (2000, 5)],
        )
        self.assertEqual(
            group_weight_rules_dialog.filter_weight_curve_points(points, hide_zero_rebate=False),
            points,
        )

    def test_zero_rebate_share_uses_final_preview_weights(self):
        text = group_weight_rules_dialog.format_zero_rebate_share_text([
            (0, 300),
            (1000, 100),
            (2000, 100),
            (3000, 0),
        ])

        self.assertEqual(
            text,
            "rebate=0 占比（不中奖率）：60.0000%（0权重=300，总权重=500）",
        )

    def test_zero_rebate_share_explains_missing_or_zero_total_weight(self):
        self.assertEqual(
            group_weight_rules_dialog.format_zero_rebate_share_text([(1000, 100)]),
            "rebate=0 占比（不中奖率）：无 rebate=0",
        )
        self.assertEqual(
            group_weight_rules_dialog.format_zero_rebate_share_text([(0, 0), (1000, 0)]),
            "rebate=0 占比（不中奖率）：--（总权重为0）",
        )

    def test_missing_zero_rebate_locks_zero_weight_entry_and_parses_as_zero(self):
        class FakeEntry:
            def __init__(self):
                self.state = None

            def configure(self, **kwargs):
                self.state = kwargs.get("state", self.state)

        master = tk.Tcl()
        rebate_var = tk.StringVar(master=master, value="0")
        weight_var = tk.StringVar(master=master, value="0")
        weight_entry = FakeEntry()
        row_info = {
            "vars": {
                "rebate_min": rebate_var,
                "weight": weight_var,
            },
            "entries": {
                "weight": weight_entry,
            },
        }
        dialog = group_weight_rules_dialog.GroupWeightRulesDialog.__new__(
            group_weight_rules_dialog.GroupWeightRulesDialog
        )
        dialog.preview_rebates = {"7": [1000, 2000]}
        dialog.rule_editor = SimpleNamespace(
            mode_rows={"7": [row_info]},
            get_rows=lambda _mode: [row_info],
        )
        dialog.deps = SimpleNamespace(
            rule_fields=("rebate_min", "weight"),
            rule_field_labels={"rebate_min": "rebate下限", "weight": "权重"},
            parse_non_negative_int_text=lambda text, _label: int(text),
            get_mode_name=lambda mode: f"mode {mode}",
        )

        dialog.apply_zero_rebate_entry_states("7")
        parsed, error = dialog.parse_dialog_rules("7")
        rows = dialog.parse_group_weight_rule_rows("7", [row_info])

        self.assertEqual(weight_var.get(), group_weight_rules_dialog.ZERO_REBATE_MISSING_TEXT)
        self.assertEqual(weight_entry.state, "disabled")
        self.assertIsNone(error)
        self.assertEqual(parsed, [{"rebate_min": 0, "weight": 0}])
        self.assertEqual(rows, [{"rebate_min": 0, "weight": 0}])

    def test_update_rtp_info_shows_preview_failure_without_raising(self):
        class FakeRuleEditor:
            def get_rows(self, _mode):
                return []

        master = tk.Tcl()
        dialog = group_weight_rules_dialog.GroupWeightRulesDialog.__new__(
            group_weight_rules_dialog.GroupWeightRulesDialog
        )
        dialog.deps = SimpleNamespace(
            rule_fields=(),
            rule_field_labels={},
            build_preview_text=lambda *_args, **_kwargs: (_ for _ in ()).throw(TypeError("bad preview")),
            buy_multiplier=1,
            ex_multiplier=1,
            buy_enabled=False,
            has_extra_buy_groups=lambda: False,
            buy_group_mode="99",
            get_group_target_rtp_value=lambda _group_id: 100.0,
            get_mode_name=lambda mode: f"mode {mode}",
        )
        dialog.rule_editor = FakeRuleEditor()
        dialog.dialog_modes = ["1"]
        dialog.displayed_modes = ["1"]
        dialog.preview_rebates = {}
        dialog.preview_status = {}
        dialog.formation_exists = {}
        dialog.special_has_zero_for_config = False
        dialog.current_group_var = tk.StringVar(master=master, value="9000 - target")
        dialog.rtp_info_var = tk.StringVar(master=master)
        dialog.notebook = SimpleNamespace(index=lambda _name: 0)

        dialog.update_rtp_info()

        self.assertIn("预览生成失败：bad preview", dialog.rtp_info_var.get())

    def test_current_rtp_group_selection_syncs_group_suffix(self):
        master = tk.Tcl()
        loaded = []
        dialog = group_weight_rules_dialog.GroupWeightRulesDialog.__new__(
            group_weight_rules_dialog.GroupWeightRulesDialog
        )
        dialog.deps = SimpleNamespace(
            weight_group_ids=[9650, 9651, 9652, 9653],
            format_group_rtp_option=lambda group_id: f"{group_id} - target",
        )
        dialog.current_group_var = tk.StringVar(master=master, value="9650 - target")
        dialog.group_suffix_var = tk.IntVar(master=master, value=0)
        dialog.current_rule_group_suffix = 0
        dialog.save_visible_rules_for_group = lambda *_args, **_kwargs: True
        dialog.load_rules_for_group = lambda suffix: loaded.append(suffix)
        dialog.update_rtp_info = lambda *_args: None

        dialog.current_group_var.set("9652 - target")
        dialog.on_current_group_changed()

        self.assertEqual(dialog.current_rule_group_suffix, 2)
        self.assertEqual(dialog.group_suffix_var.get(), 2)
        self.assertEqual(loaded, [2])

    def test_group_suffix_selection_keeps_current_rtp_family_when_possible(self):
        master = tk.Tcl()
        loaded = []
        dialog = group_weight_rules_dialog.GroupWeightRulesDialog.__new__(
            group_weight_rules_dialog.GroupWeightRulesDialog
        )
        dialog.deps = SimpleNamespace(
            weight_group_ids=[9650, 9651, 9652, 9653, 9000, 9001],
            format_group_rtp_option=lambda group_id: f"{group_id} - target",
        )
        dialog.current_group_var = tk.StringVar(master=master, value="9000 - target")
        dialog.group_suffix_var = tk.IntVar(master=master, value=1)
        dialog.current_rule_group_suffix = 0
        dialog.save_visible_rules_for_group = lambda *_args, **_kwargs: True
        dialog.load_rules_for_group = lambda suffix: loaded.append(suffix)
        dialog.update_rtp_info = lambda *_args: None

        dialog.on_group_suffix_changed()

        self.assertEqual(dialog.current_group_var.get(), "9001 - target")
        self.assertEqual(dialog.current_rule_group_suffix, 1)
        self.assertEqual(loaded, [1])

    def test_restore_defaults_resets_visible_rules_and_special_target(self):
        class FakeRuleEditor:
            def __init__(self):
                self.mode_rows = {"1": [], "extra_buy:91": []}
                self.added = []

            def clear_rule_rows(self, mode):
                self.added.append(("clear", mode))

            def add_rule_row(self, mode, rule):
                self.added.append(("add", mode, dict(rule)))

        master = tk.Tcl()
        dialog = group_weight_rules_dialog.GroupWeightRulesDialog.__new__(
            group_weight_rules_dialog.GroupWeightRulesDialog
        )
        dialog.deps = SimpleNamespace(
            buy_group_mode="99",
            default_rules={
                "1": [{"rebate_min": 0, "weight": 10}],
                "99": [{"rebate_min": 1000, "weight": 20}],
            },
            is_extra_buy_mode=lambda mode: str(mode).startswith("extra_buy:"),
            default_special_target_rtp=6.5,
        )
        dialog.rule_editor = FakeRuleEditor()
        dialog.special_target_rtp_var = tk.StringVar(master=master, value="9")
        dialog.dialog = None
        dialog.update_rtp_info = lambda: setattr(dialog, "updated", True)

        original_askyesno = group_weight_rules_dialog.messagebox.askyesno
        try:
            group_weight_rules_dialog.messagebox.askyesno = lambda *_args, **_kwargs: True
            dialog.reset_group_weight_rules_to_defaults()
        finally:
            group_weight_rules_dialog.messagebox.askyesno = original_askyesno

        self.assertIn(("clear", "1"), dialog.rule_editor.added)
        self.assertIn(("add", "1", {"rebate_min": 0, "weight": 10}), dialog.rule_editor.added)
        self.assertIn(("clear", "extra_buy:91"), dialog.rule_editor.added)
        self.assertIn(
            ("add", "extra_buy:91", {"rebate_min": 1000, "weight": 20}),
            dialog.rule_editor.added,
        )
        self.assertEqual(dialog.special_target_rtp_var.get(), "6.5")
        self.assertTrue(dialog.updated)


if __name__ == "__main__":
    unittest.main()
