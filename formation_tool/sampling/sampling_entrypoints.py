"""Entrypoints for calling the configured sampling core module."""


def call_core_function(sync_sampling_context, sampling_core_module, func_name, *args, **kwargs):
    """Sync sampling runtime context and call one sampling_core function."""
    sync_sampling_context()
    return getattr(sampling_core_module, func_name)(*args, **kwargs)
