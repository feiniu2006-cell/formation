"""Dependency builders for rebate_count config generation and storage."""

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class StorageReplaceDeps:
    make_staging_table_name: Callable[[str, str], str]
    drop_table_if_exists: Callable[[Any, str], None]
    create_rebate_config_table_if_needed: Callable[[Any, str], None]
    quote_identifier: Callable[..., str]
    count_table_rows: Callable[[Any, str], int]
    replace_table_with_staging: Callable[[Any, str, str, str], Any]
    rollback_safely: Callable[[Any], None]
    suppress_exceptions: Callable[[], Any]


@dataclass(frozen=True)
class WriteRowsDeps:
    connect_by_table: Callable[[str, dict], Any]
    replace_rebate_config_rows_atomically: Callable[[Any, str, list, str], int]
    print_write_complete: Callable[[int, str], None]
    print_step_error: Callable[..., None]
    rollback_safely: Callable[[Any], None]
    close_safely: Callable[[Any], None]


@dataclass(frozen=True)
class RunnerDeps:
    check_cancelled: Callable[[], None]
    get_table_database: Callable[[str, dict], str]
    get_table_name: Callable[[str, dict], str]
    connect_by_table: Callable[[str, dict], Any]
    close_safely: Callable[[Any], None]
    table_exists_exact: Callable[[Any, str], bool]
    resolve_rebate_config_game_condition: Callable[..., str]
    get_engine_by_table: Callable[[str, dict], Any]
    quote_identifier: Callable[..., str]
    direct_count_modes: set
    build_direct_rebate_config_rows: Callable[[Any], list]
    apply_direct_count_tier_limits_to_rows: Callable[..., list]
    build_rule_based_rebate_config_rows: Callable[[Any, list], list]
    build_rebate_sql_filter: Callable[..., str | None]
    apply_rebate_config_count_limits_to_rows: Callable[..., list]
    normalize_rebate_config_rows: Callable[[list, str], list]
    write_rebate_config_rows: Callable[[dict, str, str, list], bool]
    detailed_log: bool = False


def build_storage_replace_deps(callbacks):
    """Build deps for atomic rebate_count table replacement."""
    return StorageReplaceDeps(
        make_staging_table_name=callbacks.make_staging_table_name,
        drop_table_if_exists=callbacks.drop_table_if_exists,
        create_rebate_config_table_if_needed=callbacks.create_rebate_config_table_if_needed,
        quote_identifier=callbacks.quote_identifier,
        count_table_rows=callbacks.count_table_rows,
        replace_table_with_staging=callbacks.replace_table_with_staging,
        rollback_safely=callbacks.rollback_safely,
        suppress_exceptions=callbacks.suppress_exceptions,
    )


def build_write_rows_deps(callbacks):
    """Build deps consumed by rebate_config_storage.write_rebate_config_rows."""
    return WriteRowsDeps(
        connect_by_table=callbacks.connect_by_table,
        replace_rebate_config_rows_atomically=callbacks.replace_rebate_config_rows_atomically,
        print_write_complete=callbacks.print_write_complete,
        print_step_error=callbacks.print_step_error,
        rollback_safely=callbacks.rollback_safely,
        close_safely=callbacks.close_safely,
    )


def build_runner_deps(callbacks, runtime):
    """Build deps consumed by rebate_config_runner.generate_rebate_config_for_game."""
    return RunnerDeps(
        check_cancelled=callbacks.check_cancelled,
        get_table_database=callbacks.get_table_database,
        get_table_name=callbacks.get_table_name,
        connect_by_table=callbacks.connect_by_table,
        close_safely=callbacks.close_safely,
        table_exists_exact=callbacks.table_exists_exact,
        resolve_rebate_config_game_condition=callbacks.resolve_rebate_config_game_condition,
        get_engine_by_table=callbacks.get_engine_by_table,
        quote_identifier=callbacks.quote_identifier,
        direct_count_modes=set(runtime.direct_count_modes),
        build_direct_rebate_config_rows=callbacks.build_direct_rebate_config_rows,
        apply_direct_count_tier_limits_to_rows=callbacks.apply_direct_count_tier_limits_to_rows,
        build_rule_based_rebate_config_rows=callbacks.build_rule_based_rebate_config_rows,
        build_rebate_sql_filter=callbacks.build_rebate_sql_filter,
        apply_rebate_config_count_limits_to_rows=callbacks.apply_rebate_config_count_limits_to_rows,
        normalize_rebate_config_rows=callbacks.normalize_rebate_config_rows,
        write_rebate_config_rows=callbacks.write_rebate_config_rows,
        detailed_log=bool(getattr(runtime, 'detailed_log', False)),
    )


def create_rebate_config_table_if_needed(conn, table_name, *, storage_module, quote_identifier):
    return storage_module.create_rebate_config_table_if_needed(
        conn,
        table_name,
        quote_identifier=quote_identifier,
    )
