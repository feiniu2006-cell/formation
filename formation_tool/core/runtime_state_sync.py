"""Helpers for syncing legacy module globals with RuntimeState."""

from types import SimpleNamespace


def namespace_from_globals(globals_dict):
    return SimpleNamespace(**globals_dict)


def sync_database_runtime_state_from_globals(runtime_state, namespace_getter):
    runtime_state.sync_database_from(namespace_getter())


def sync_runtime_selection_from_globals(runtime_state, namespace_getter):
    runtime_state.sync_runtime_selection_from(namespace_getter())


def sync_trigger_weights_from_globals(runtime_state, namespace_getter):
    runtime_state.sync_trigger_weights_from(namespace_getter())


def sync_rebate_runtime_from_globals(runtime_state, namespace_getter):
    runtime_state.sync_rebate_runtime_from(namespace_getter())


def sync_sampling_runtime_from_globals(runtime_state, namespace_getter):
    runtime_state.sync_sampling_runtime_from(namespace_getter())


def sync_group_weight_runtime_from_globals(runtime_state, namespace_getter):
    runtime_state.sync_group_weight_runtime_from(namespace_getter())


def sync_external_status_from_globals(runtime_state, namespace_getter):
    runtime_state.sync_external_status_from(namespace_getter())


def sync_runtime_state_from_globals(runtime_state, namespace_getter):
    runtime_state.sync_all_from(namespace_getter())


def build_legacy_globals_snapshot(runtime_state, namespace_getter):
    target = namespace_getter()
    runtime_state.to_legacy_globals(target)
    return target
