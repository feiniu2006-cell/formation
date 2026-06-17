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
from formation_tool.core import settings_logic
from formation_tool.db import formation_db_access
from formation_tool.db import db_runtime
from formation_tool.db import db_entrypoints
from formation_tool.db import game_type_config_runtime
from formation_tool.group_weight import group_weight_builder
from formation_tool.group_weight import group_weight_entrypoints
from formation_tool.group_weight import group_weight_logic
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

        def fake_normal_builder(group_id, normal_pairs, free_rtp, free_enabled, special_rtp, special_enabled):
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
            group_modes=("1", "2", "3", "6", "7", "8", "98", "99"),
            default_buy_rules=[{"rebate_min": 0, "weight": 1}],
            buy_group_mode="99",
            default_buy_game_type=99,
            default_source_suffix="free_formation",
        )

        self.assertEqual(groups[0]["source_suffix"], "bonus_formation")
        self.assertEqual(groups[0]["game_type"], 120)

    def test_default_buy_game_type_can_change_and_free_99_for_extra_buy(self):
        groups = buy_group_config.normalize_extra_buy_groups(
            [{"game_type": "99", "multiplier": "80", "source_suffix": "bonus_formation"}],
            group_modes=("1", "2", "3", "6", "7", "8", "98", "99"),
            default_buy_rules=[{"rebate_min": 0, "weight": 1}],
            buy_group_mode="99",
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
        formation_exists = {"1": True, "99": False, "extra_buy:120": True}
        modes = formation_modes.get_active_group_weight_modes(
            formation_exists,
            buy_enabled=False,
            ex_buy_enabled=False,
            extra_buy_groups=extra_groups,
        )

        self.assertIn("1", modes)
        self.assertIn("extra_buy:120", modes)
        self.assertNotIn("99", modes)


class ExGroupWeightSourceOverrideTests(unittest.TestCase):
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

    def build_runner_deps(self, events, *, table_exists=True, write_result=True, direct_count_modes=None):
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

        class FakeFrame:
            def __len__(self):
                return 3

            def to_sql(self, *args, **kwargs):
                calls.append(("to_sql", args, kwargs))

        old_sql_with_retry = getattr(sampling_core, "sql_with_retry", None)
        had_sql_with_retry = hasattr(sampling_core, "sql_with_retry")
        sampling_core.sql_with_retry = lambda fn, label: calls.append(("retry", label)) or fn()
        try:
            sampling_core.write_sample_chunk_to_staging(FakeFrame(), "engine", "tmp_table", 1000)
        finally:
            if had_sql_with_retry:
                sampling_core.sql_with_retry = old_sql_with_retry
            else:
                delattr(sampling_core, "sql_with_retry")

        to_sql_call = next(item for item in calls if item[0] == "to_sql")
        self.assertEqual(to_sql_call[1], ("tmp_table", "engine"))
        self.assertEqual(to_sql_call[2]["if_exists"], "append")
        self.assertFalse(to_sql_call[2]["index"])
        self.assertEqual(to_sql_call[2]["chunksize"], sampling_core.SAMPLE_ROW_WRITE_CHUNK_SIZE)
        self.assertTrue(callable(to_sql_call[2]["method"]))

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

    def test_direct_sampling_success_passes_append_mode_and_closes_connections(self):
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
        self.assertIn(("prepare", deps.source_conn, deps.final_conn, "final_table", True), events)
        self.assertIn(("sample", ["config-row"], True, staging_state), events)
        self.assertIn(("finalize", final_conn_after, "final_table", staging_state, {
            "sampled_count": 3,
            "remapped_id_count": 1,
            "remapped_row_count": 2,
        }, True), events)
        self.assertNotIn("cleanup", [event[0] for event in events if isinstance(event, tuple)])
        self.assertIn(("close", deps.source_conn), events)
        self.assertIn(("close", final_conn_after), events)

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
        self.assertIn("采样写入模式：不清空追加", preview)
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
            "DEFAULT_BUY_GROUP_ENABLED": False,
            "DEFAULT_EX_BUY_GROUP_ENABLED": False,
            "DEFAULT_BUY_GROUP_GAME_TYPE": 99,
            "DEFAULT_BUY_GROUP_MULTIPLIER": 50,
            "DEFAULT_BUY_GROUP_SOURCE_SUFFIX": "free_formation",
            "DEFAULT_EX_GROUP_MULTIPLIER": 1.5,
            "DEFAULT_EXTRA_BUY_GROUPS": [],
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
        self.buy_group_enabled_var = tk.BooleanVar(master=master, value=False)
        self.ex_buy_group_enabled_var = tk.BooleanVar(master=master, value=False)
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
        self.apply_selected_config_called = False

    def set_extra_buy_group_rows(self, groups):
        self.extra_buy_rows = [dict(group) for group in groups]

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

    def test_build_app_settings_data_persists_buy_and_sampling_options(self):
        extra_groups = [
            {"game_type": 120, "multiplier": 80, "source_suffix": "bonus_formation", "rules": []}
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
            get_group_weight_rules=lambda: {"99": [{"rebate_min": 0, "weight": 10}]},
            clone_group_weight_rules=lambda rules: {key: [dict(item) for item in value] for key, value in rules.items()},
            get_special_group_target_rtp=lambda: 8.5,
            get_buy_group_enabled=lambda: True,
            get_ex_buy_group_enabled=lambda: True,
            get_buy_group_game_type=lambda: 99,
            get_buy_group_multiplier=lambda: 50,
            get_buy_group_source_suffix=lambda: "free_formation",
            get_ex_group_multiplier=lambda: 1.5,
            get_ex_source_suffixes=lambda: {"6": "manual_ex_formation"},
            get_extra_buy_groups=lambda: extra_groups,
            clone_extra_buy_groups=lambda groups: [dict(group) for group in groups],
            get_direct_count_modes=lambda: {"1", "6"},
            get_direct_count_tiers=lambda: [{"rebate_min": 1, "rebate_max": 999, "count": 88}],
        )
        app = FakeSettingsApp(deps, self.tcl_root)

        data = app.build_app_settings_data()

        self.assertTrue(data["sampling_options"]["append_mode"])
        self.assertTrue(data["sampling_options"]["detailed_log"])
        self.assertEqual(data["group_weight_options"]["buy_game_type"], 99)
        self.assertEqual(data["group_weight_options"]["buy_multiplier"], 50)
        self.assertEqual(data["group_weight_options"]["buy_source_suffix"], "free_formation")
        self.assertEqual(data["group_weight_options"]["ex_source_suffixes"], {"6": "manual_ex_formation"})
        self.assertEqual(data["group_weight_options"]["extra_buy_groups"], extra_groups)
        self.assertEqual(data["group_weight_options"]["buy_groups"][0]["game_type"], 99)
        self.assertEqual(data["group_weight_options"]["buy_groups"][1]["game_type"], 120)
        self.assertEqual(set(data["direct_count_modes"]), {"1", "6"})
        self.assertEqual(data["direct_count_tiers"], [{"rebate_min": 1, "rebate_max": 999, "count": 88}])

    def test_apply_app_settings_data_restores_buy_and_extra_buy_options(self):
        calls = []
        extra_groups = [
            {"game_type": 120, "multiplier": 80, "source_suffix": "bonus_formation", "rules": []}
        ]
        deps = SimpleNamespace(
            clear_config_warnings=lambda: calls.append(("clear", None)),
            get_buy_group_enabled=lambda: False,
            get_ex_buy_group_enabled=lambda: False,
            get_buy_group_game_type=lambda: 99,
            get_buy_group_multiplier=lambda: 50,
            get_buy_group_source_suffix=lambda: "free_formation",
            get_ex_group_multiplier=lambda: 1.5,
            get_ex_source_suffixes=lambda: {},
            get_extra_buy_groups=lambda: [],
            normalize_rebate_rules_for_load=lambda rules: {"normalized": rules},
            apply_rebate_rules_config=lambda rules: calls.append(("rebate", rules)),
            normalize_group_weight_rules_for_load=lambda rules: {"normalized": rules},
            apply_group_weight_rules_config=lambda rules: calls.append(("group_rules", rules)),
            apply_extra_buy_groups_config=lambda groups: calls.append(("extra", [dict(group) for group in groups])),
            apply_special_group_target_rtp=lambda value: calls.append(("special_rtp", value)),
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
            group_weight_rules={"99": [{"rebate_min": 0, "weight": 9}]},
            group_weight_options={
                "special_target_rtp": 7.25,
                "buy_enabled": True,
                "ex_buy_enabled": True,
                "buy_game_type": 120,
                "buy_multiplier": 60,
                "buy_source_suffix": "custom_free_formation",
                "ex_multiplier": 1.6,
                "ex_source_suffixes": {"6": "custom_ex_formation", "8": "custom_ex_free_formation"},
                "extra_buy_groups": extra_groups,
            },
            direct_count_modes=["1", "6"],
            direct_count_tiers=[{"rebate_min": 1, "rebate_max": 999, "count": 88}],
        )

        app.apply_app_settings_data(data)

        self.assertEqual(app.vendor_var.get(), "jili")
        self.assertEqual(app.game_id_var.get(), "49")
        self.assertEqual(app.buy_game_type_var.get(), "120")
        self.assertEqual(app.buy_multiplier_var.get(), "60")
        self.assertEqual(app.buy_source_suffix_var.get(), "custom_free_formation")
        self.assertTrue(app.sampling_detailed_log_var.get())
        self.assertEqual(app.ex_source_suffix_vars["6"].get(), "custom_ex_formation")
        self.assertEqual(app.ex_source_suffix_vars["8"].get(), "custom_ex_free_formation")
        self.assertEqual(app.extra_buy_rows, extra_groups)
        self.assertTrue(app.apply_selected_config_called)
        self.assertIn(("special_rtp", 7.25), calls)
        self.assertIn(("direct", ["1", "6"]), calls)
        self.assertIn(("direct_tiers", [{"rebate_min": 1, "rebate_max": 999, "count": 88}]), calls)
        self.assertIn(("extra", extra_groups), calls)

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
            "extra_buy_groups": [
                {"game_type": 92, "multiplier": 65, "source_suffix": "buy2_special_formation"}
            ],
        }

        self.assertTrue(app.apply_loaded_buy_group_options(options))

        self.assertTrue(app.buy_group_enabled_var.get())
        self.assertEqual(app.buy_game_type_var.get(), "91")
        self.assertEqual(app.buy_multiplier_var.get(), "75")
        self.assertEqual(app.buy_source_suffix_var.get(), "special_formation")
        self.assertTrue(app.ex_buy_group_enabled_var.get())
        self.assertIn(("game_type", "91"), calls)
        self.assertIn(("extra", options["extra_buy_groups"]), calls)


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
