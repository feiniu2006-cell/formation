"""Entry point helpers for building and running the Tkinter app."""

import tkinter as tk

from formation_tool.ui import slot_app_context
from formation_tool.ui import slot_app_deps
from formation_tool.ui.slot_process_app import SlotProcessApp


def build_slot_app_deps_context(runtime_state, module_namespace):
    return slot_app_context.build_slot_app_deps_context(runtime_state, module_namespace)


def build_slot_app_ui_deps(runtime_state, module_namespace, context=None):
    return slot_app_deps.build_ui_deps(
        context or build_slot_app_deps_context(runtime_state, module_namespace)
    )


def build_slot_app_settings_deps(runtime_state, module_namespace, context=None):
    return slot_app_deps.build_settings_deps(
        context or build_slot_app_deps_context(runtime_state, module_namespace)
    )


def build_slot_app_task_deps(runtime_state, module_namespace, context=None):
    return slot_app_deps.build_task_deps(
        context or build_slot_app_deps_context(runtime_state, module_namespace)
    )


def build_group_weight_dialog_deps(runtime_state, module_namespace):
    return slot_app_deps.build_group_weight_dialog_deps(
        build_slot_app_deps_context(runtime_state, module_namespace)
    )


def build_slot_process_app_deps(runtime_state, module_namespace):
    return slot_app_deps.build_process_app_deps(
        build_slot_app_deps_context(runtime_state, module_namespace)
    )


def run_gui(runtime_state, module_namespace, *, root_factory=tk.Tk, app_class=SlotProcessApp):
    root = root_factory()
    app_class(root, build_slot_process_app_deps(runtime_state, module_namespace))
    root.mainloop()
    return root
