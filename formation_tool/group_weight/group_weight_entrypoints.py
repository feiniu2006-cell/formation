"""Dependency builders for group_weight storage and runner entrypoints."""

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class StorageReplaceDeps:
    make_staging_table_name: Callable[[str, str], str]
    drop_table_if_exists: Callable[[Any, str], None]
    create_group_weight_table_if_needed: Callable[[Any, str], None]
    quote_identifier: Callable[..., str]
    count_table_rows: Callable[[Any, str], int]
    replace_table_with_staging: Callable[[Any, str, str, str], Any]
    rollback_safely: Callable[[Any], None]
    suppress_exceptions: Callable[[], Any]


@dataclass(frozen=True)
class StorageVerifyDeps:
    quote_identifier: Callable[..., str]
    game_type_names: dict


@dataclass(frozen=True)
class RunnerDeps:
    check_cancelled: Callable[[], None]
    ex_group_modes: tuple
    ex_purchase_mode: str
    get_config_db: Callable[[], str]
    get_final_db: Callable[[], str]
    get_ex_buy_group_enabled: Callable[[], bool]
    get_group_weight_table_name: Callable[[], str]
    get_group_weight_formation_exists: Callable[[], dict]
    get_active_group_weight_modes: Callable[[dict], list]
    build_group_weight_generation_context: Callable[[], dict]
    print_group_weight_generation_summary: Callable[[dict], None]
    connect_group_weight_databases: Callable[[str, str], tuple]
    load_group_weight_generation_data: Callable[[Any, dict], tuple]
    load_group_weight_rebates_for_modes: Callable[[Any, list, str], tuple]
    build_group_weight_pairs_for_modes: Callable[[list, dict], dict]
    build_normalized_group_weight_generation_rows: Callable[..., Any]
    build_group_weight_rows_from_loaded_data: Callable[..., Any]
    normalize_group_weight_rows: Callable[[list], list]
    print_no_group_weight_rows: Callable[[], None]
    print_group_weight_validation_failed: Callable[[Exception], None]
    write_group_weight_generation_rows: Callable[[Any, dict, list], int]
    print_replace_with_staging_notice: Callable[[str], None]
    replace_group_weight_rows_atomically: Callable[[Any, str, list, str], int]
    print_write_complete: Callable[[int, str], None]
    verify_group_weight_zero_rebate_rows: Callable[[Any, str, list], None]
    print_step_error: Callable[..., None]
    rollback_safely: Callable[[Any], None]
    close_safely: Callable[[Any], None]


@dataclass(frozen=True)
class ConnectGroupWeightDeps:
    connect_to_database: Callable[[str], Any]
    close_safely: Callable[[Any], None]


@dataclass(frozen=True)
class RebateLoaderDeps:
    buy_group_mode: str
    ex_purchase_mode: str
    group_weight_modes: tuple
    get_config_db: Callable[[], str]
    get_ex_buy_group_enabled: Callable[[], bool]
    get_group_weight_rules: Callable[[], dict]
    default_buy_group_weight_rules: Callable[[], list]
    has_any_buy_group: Callable[[], bool]
    build_preview_modes: Callable[[], list]
    get_group_weight_formation_exists: Callable[[], dict]
    get_source_formation_check_error_for_mode: Callable[[str], str | None]
    get_group_weight_rebate_table_name: Callable[[str], str]
    get_group_weight_mode_name: Callable[[str], str]
    is_extra_buy_mode: Callable[[str], bool]
    get_extra_buy_group_by_mode: Callable[[str], dict | None]
    connect_to_database: Callable[[str], Any]
    table_exists_exact: Callable[[Any, str], bool]
    read_rebate_config_values: Callable[[Any, str], list]
    close_safely: Callable[[Any], None]
    check_cancelled: Callable[[], None]


def build_storage_replace_deps(callbacks):
    """Build deps for atomic group_weight table replacement."""
    return StorageReplaceDeps(
        make_staging_table_name=callbacks.make_staging_table_name,
        drop_table_if_exists=callbacks.drop_table_if_exists,
        create_group_weight_table_if_needed=callbacks.create_group_weight_table_if_needed,
        quote_identifier=callbacks.quote_identifier,
        count_table_rows=callbacks.count_table_rows,
        replace_table_with_staging=callbacks.replace_table_with_staging,
        rollback_safely=callbacks.rollback_safely,
        suppress_exceptions=callbacks.suppress_exceptions,
    )


def build_storage_verify_deps(callbacks, game_type_names):
    """Build deps for post-write rebate=0 verification."""
    return StorageVerifyDeps(
        quote_identifier=callbacks.quote_identifier,
        game_type_names=game_type_names,
    )


def call_builder_function(sync_builder_context, builder_module, func_name, *args, **kwargs):
    """Sync builder context and call one group_weight builder function."""
    sync_builder_context()
    return getattr(builder_module, func_name)(*args, **kwargs)


def create_group_weight_table_if_needed(conn, table_name, *, storage_module, quote_identifier):
    return storage_module.create_group_weight_table_if_needed(
        conn,
        table_name,
        quote_identifier=quote_identifier,
    )


def read_rebate_config_values(conn, table_name, *, storage_module, quote_identifier):
    return storage_module.read_rebate_config_values(
        conn,
        table_name,
        quote_identifier=quote_identifier,
    )


def build_rebate_loader_deps(callbacks, constants, runtime_getters):
    """Build deps consumed by group_weight_rebate_loader."""
    return RebateLoaderDeps(
        buy_group_mode=constants.buy_group_mode,
        ex_purchase_mode=constants.ex_purchase_mode,
        group_weight_modes=constants.group_weight_modes,
        get_config_db=runtime_getters.get_config_db,
        get_ex_buy_group_enabled=runtime_getters.get_ex_buy_group_enabled,
        get_group_weight_rules=runtime_getters.get_group_weight_rules,
        default_buy_group_weight_rules=runtime_getters.default_buy_group_weight_rules,
        has_any_buy_group=callbacks.has_any_buy_group,
        build_preview_modes=callbacks.build_preview_modes,
        get_group_weight_formation_exists=callbacks.get_group_weight_formation_exists,
        get_source_formation_check_error_for_mode=callbacks.get_source_formation_check_error_for_mode,
        get_group_weight_rebate_table_name=callbacks.get_group_weight_rebate_table_name,
        get_group_weight_mode_name=callbacks.get_group_weight_mode_name,
        is_extra_buy_mode=callbacks.is_extra_buy_mode,
        get_extra_buy_group_by_mode=callbacks.get_extra_buy_group_by_mode,
        connect_to_database=callbacks.connect_to_database,
        table_exists_exact=callbacks.table_exists_exact,
        read_rebate_config_values=callbacks.read_rebate_config_values,
        close_safely=callbacks.close_safely,
        check_cancelled=callbacks.check_cancelled,
    )


def connect_group_weight_databases(read_db_name, write_db_name, *, runner_module, connect_to_database, close_safely):
    return runner_module.connect_group_weight_databases(
        read_db_name,
        write_db_name,
        deps=ConnectGroupWeightDeps(
            connect_to_database=connect_to_database,
            close_safely=close_safely,
        ),
    )


def verify_group_weight_zero_rebate_rows(write_conn, table_name, rows, *, storage_module, quote_identifier, game_type_names):
    return storage_module.verify_group_weight_zero_rebate_rows(
        write_conn,
        table_name,
        rows,
        deps=StorageVerifyDeps(
            quote_identifier=quote_identifier,
            game_type_names=game_type_names,
        ),
    )


def build_runner_deps(callbacks, constants, runtime_getters, log_callbacks):
    """Build deps consumed by group_weight_runner."""
    return RunnerDeps(
        check_cancelled=callbacks.check_cancelled,
        ex_group_modes=constants.ex_group_modes,
        ex_purchase_mode=constants.ex_purchase_mode,
        get_config_db=runtime_getters.get_config_db,
        get_final_db=runtime_getters.get_final_db,
        get_ex_buy_group_enabled=runtime_getters.get_ex_buy_group_enabled,
        get_group_weight_table_name=callbacks.get_group_weight_table_name,
        get_group_weight_formation_exists=callbacks.get_group_weight_formation_exists,
        get_active_group_weight_modes=callbacks.get_active_group_weight_modes,
        build_group_weight_generation_context=callbacks.build_group_weight_generation_context,
        print_group_weight_generation_summary=callbacks.print_group_weight_generation_summary,
        connect_group_weight_databases=callbacks.connect_group_weight_databases,
        load_group_weight_generation_data=callbacks.load_group_weight_generation_data,
        load_group_weight_rebates_for_modes=callbacks.load_group_weight_rebates_for_modes,
        build_group_weight_pairs_for_modes=callbacks.build_group_weight_pairs_for_modes,
        build_normalized_group_weight_generation_rows=callbacks.build_normalized_group_weight_generation_rows,
        build_group_weight_rows_from_loaded_data=callbacks.build_group_weight_rows_from_loaded_data,
        normalize_group_weight_rows=callbacks.normalize_group_weight_rows,
        print_no_group_weight_rows=log_callbacks.print_no_group_weight_rows,
        print_group_weight_validation_failed=log_callbacks.print_group_weight_validation_failed,
        write_group_weight_generation_rows=callbacks.write_group_weight_generation_rows,
        print_replace_with_staging_notice=log_callbacks.print_replace_with_staging_notice,
        replace_group_weight_rows_atomically=callbacks.replace_group_weight_rows_atomically,
        print_write_complete=log_callbacks.print_write_complete,
        verify_group_weight_zero_rebate_rows=callbacks.verify_group_weight_zero_rebate_rows,
        print_step_error=callbacks.print_step_error,
        rollback_safely=callbacks.rollback_safely,
        close_safely=callbacks.close_safely,
    )
