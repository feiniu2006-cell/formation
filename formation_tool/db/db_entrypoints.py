"""Entrypoints for database access and table operation dependency wiring."""

from dataclasses import dataclass
from typing import Any, Callable

from formation_tool.db import db_table_ops
from formation_tool.db import formation_db_access


@dataclass(frozen=True)
class DatabaseAccessCallbacks:
    get_database_configs: Callable[[], dict]
    get_engine: Callable[[dict], Any]
    get_db_config_by_name: Callable[[str], dict]
    connect_to_db: Callable[[dict], Any]
    connect_to_database: Callable[[str], Any]
    close_safely: Callable[[Any], None]


@dataclass(frozen=True)
class TableOperationDeps:
    quote_identifier: Callable[..., str]
    chunked: Callable[..., Any]
    make_staging_table_name: Callable[[str, str], str]
    drop_table_if_exists: Callable[[Any, str], None]
    table_exists_exact: Callable[[Any, str], bool]


def build_database_access_deps(callbacks: DatabaseAccessCallbacks):
    """Build deps consumed by formation_db_access."""
    return formation_db_access.build_database_access_deps(
        get_database_configs=callbacks.get_database_configs,
        get_engine=callbacks.get_engine,
        get_db_config_by_name=callbacks.get_db_config_by_name,
        connect_to_db=callbacks.connect_to_db,
        connect_to_database=callbacks.connect_to_database,
        close_safely=callbacks.close_safely,
    )


def drop_table_if_exists(conn, table_name, *, deps: TableOperationDeps):
    return db_table_ops.drop_table_if_exists(
        conn,
        table_name,
        quote_identifier=deps.quote_identifier,
    )


def count_table_rows(conn, table_name, *, deps: TableOperationDeps):
    return db_table_ops.count_table_rows(
        conn,
        table_name,
        quote_identifier=deps.quote_identifier,
    )


def get_table_max_id(conn, table_name, *, deps: TableOperationDeps):
    return db_table_ops.get_table_max_id(
        conn,
        table_name,
        quote_identifier=deps.quote_identifier,
    )


def copy_table_rows(conn, source_table, target_table, *, deps: TableOperationDeps):
    return db_table_ops.copy_table_rows(
        conn,
        source_table,
        target_table,
        quote_identifier=deps.quote_identifier,
    )


def get_existing_ids(conn, table_name, ids, *, deps: TableOperationDeps):
    return db_table_ops.get_existing_ids(
        conn,
        table_name,
        ids,
        quote_identifier=deps.quote_identifier,
        chunked=deps.chunked,
    )


def replace_table_with_staging(conn, staging_table, target_table, db_name, *, deps: TableOperationDeps):
    return db_table_ops.replace_table_with_staging(
        conn,
        staging_table,
        target_table,
        db_name,
        quote_identifier=deps.quote_identifier,
        make_staging_table_name=deps.make_staging_table_name,
        drop_table_if_exists=deps.drop_table_if_exists,
        table_exists_exact=deps.table_exists_exact,
    )
