"""Entrypoints and dependency factories for common config generation."""

from dataclasses import dataclass
from typing import Any, Callable

from formation_tool.common import common_config_writer


@dataclass(frozen=True)
class CommonConfigConstants:
    weight_group_ids: tuple
    special_weight_table: str
    free_game_config_table: str
    bet_amount_table: str


@dataclass(frozen=True)
class RuntimeDeps:
    connect_to_database: Callable[[str], Any]
    quote_identifier: Callable[..., str]
    validate_sql_identifier: Callable[..., str]
    rollback_safely: Callable[[Any], None]
    close_safely: Callable[[Any], None]
    print_step_error: Callable[..., None]


@dataclass(frozen=True)
class WriterDeps:
    game_id: str
    final_db: str
    weight_config_db: str
    game_table_prefix: str
    weight_type_id: int
    weight_group_ids: tuple
    special_weight_by_last_digit: dict
    free_weight_by_last_digit: dict
    special_weight_table: str
    free_game_config_table: str
    bet_amount_table: str
    connect_to_database: Callable[[str], Any]
    quote_identifier: Callable[..., str]
    validate_sql_identifier: Callable[..., str]
    rollback_safely: Callable[[Any], None]
    close_safely: Callable[[Any], None]
    print_step_error: Callable[..., None]


@dataclass(frozen=True)
class RunnerTaskDeps:
    check_cancelled: Callable[[], None]
    print_section: Callable[[str], None]
    print_result_summary: Callable[..., None]


@dataclass(frozen=True)
class RunnerWriterDeps:
    write_special_weight_config: Callable[[], Any]
    write_free_game_config: Callable[[], Any]
    write_bet_amount_config: Callable[[], Any]


@dataclass(frozen=True)
class RunnerDeps:
    check_cancelled: Callable[[], None]
    print_section: Callable[[str], None]
    print_result_summary: Callable[..., None]
    special_weight_table: str
    free_game_config_table: str
    bet_amount_table: str
    write_special_weight_config: Callable[[], Any]
    write_free_game_config: Callable[[], Any]
    write_bet_amount_config: Callable[[], Any]


def build_writer_deps(runtime, constants, deps):
    """Build dependencies for per-game common config table writers."""
    return WriterDeps(
        game_id=runtime.game_id,
        final_db=runtime.final_db,
        weight_config_db=runtime.weight_config_db,
        game_table_prefix=runtime.game_table_prefix,
        weight_type_id=runtime.weight_type_id,
        weight_group_ids=constants.weight_group_ids,
        special_weight_by_last_digit=runtime.special_weight_by_last_digit,
        free_weight_by_last_digit=runtime.free_weight_by_last_digit,
        special_weight_table=constants.special_weight_table,
        free_game_config_table=constants.free_game_config_table,
        bet_amount_table=constants.bet_amount_table,
        connect_to_database=deps.connect_to_database,
        quote_identifier=deps.quote_identifier,
        validate_sql_identifier=deps.validate_sql_identifier,
        rollback_safely=deps.rollback_safely,
        close_safely=deps.close_safely,
        print_step_error=deps.print_step_error,
    )


def write_special_weight_config(runtime, constants, deps):
    return common_config_writer.write_special_weight_config(
        build_writer_deps(runtime, constants, deps)
    )


def write_free_game_config(runtime, constants, deps):
    return common_config_writer.write_free_game_config(
        build_writer_deps(runtime, constants, deps)
    )


def write_bet_amount_config(runtime, constants, deps):
    return common_config_writer.write_bet_amount_config(
        build_writer_deps(runtime, constants, deps)
    )


def build_runner_deps(constants, task_deps, writer_deps):
    """Build dependencies for the common config runner."""
    return RunnerDeps(
        check_cancelled=task_deps.check_cancelled,
        print_section=task_deps.print_section,
        print_result_summary=task_deps.print_result_summary,
        special_weight_table=constants.special_weight_table,
        free_game_config_table=constants.free_game_config_table,
        bet_amount_table=constants.bet_amount_table,
        write_special_weight_config=writer_deps.write_special_weight_config,
        write_free_game_config=writer_deps.write_free_game_config,
        write_bet_amount_config=writer_deps.write_bet_amount_config,
    )


def write_weight_config(writer_deps, table_name, columns, rows, db_name, room_id, type_id=None):
    return common_config_writer.write_weight_config(
        writer_deps,
        table_name,
        columns,
        rows,
        db_name,
        room_id,
        type_id,
    )


def table_exists_exact(conn, table_name, *, validate_sql_identifier):
    return common_config_writer.table_exists_exact(
        conn,
        table_name,
        validate_sql_identifier=validate_sql_identifier,
    )


def check_final_table_exists(writer_deps, table_name):
    return common_config_writer.check_final_table_exists(writer_deps, table_name)


def parse_number_list(text, label):
    return common_config_writer.parse_number_list(text, label)


def read_room_base_bet_config(conn, source_table, room_id, type_id, *, quote_identifier):
    return common_config_writer.read_room_base_bet_config(
        conn,
        source_table,
        room_id,
        type_id,
        quote_identifier=quote_identifier,
    )


def calculate_bet_amount_values(base_row):
    return common_config_writer.calculate_bet_amount_values(base_row)


def read_existing_bet_amount_set(conn, table_name, room_id, type_id, *, quote_identifier):
    return common_config_writer.read_existing_bet_amount_set(
        conn,
        table_name,
        room_id,
        type_id,
        quote_identifier=quote_identifier,
    )


def replace_bet_amount_rows(conn, db_name, table_name, room_id, type_id, sorted_values, *, quote_identifier):
    return common_config_writer.replace_bet_amount_rows(
        conn,
        db_name,
        table_name,
        room_id,
        type_id,
        sorted_values,
        quote_identifier=quote_identifier,
    )
