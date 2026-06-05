"""Source formation table detection helpers."""

from dataclasses import dataclass
from types import SimpleNamespace


@dataclass(frozen=True)
class FormationCheckStatus:
    source_mode: str
    exists: bool
    source_db: str = ''
    source_table: str = ''
    error: str | None = None


def build_detection_deps(
    *,
    get_game_configs,
    get_table_database,
    get_table_name,
    connect_to_database,
    table_exists_exact,
    close_safely,
):
    """Build the dependency object used by formation table detection."""
    return SimpleNamespace(
        get_game_configs=get_game_configs,
        get_table_database=get_table_database,
        get_table_name=get_table_name,
        connect_to_database=connect_to_database,
        table_exists_exact=table_exists_exact,
        close_safely=close_safely,
    )


def get_group_weight_source_mode(mode, *, mode_defs, buy_group_mode, is_extra_buy_mode):
    """Return the sampling/source mode used by a group_weight mode."""
    mode = str(mode)
    if is_extra_buy_mode(mode):
        return buy_group_mode
    return mode_defs.get(mode, {}).get('source_mode')


def check_physical_source_status(source_mode, source_db, source_table, *, deps):
    """Check one physical source table and preserve the reason on failure."""
    source_mode = str(source_mode)
    conn = None
    try:
        conn = deps.connect_to_database(source_db)
        if not conn:
            return FormationCheckStatus(
                source_mode=source_mode,
                exists=False,
                source_db=source_db,
                source_table=source_table,
                error=f"无法连接源库 {source_db}，无法检测 {source_table}",
            )
        return FormationCheckStatus(
            source_mode=source_mode,
            exists=bool(deps.table_exists_exact(conn, source_table)),
            source_db=source_db,
            source_table=source_table,
        )
    except Exception as exc:
        return FormationCheckStatus(
            source_mode=source_mode,
            exists=False,
            source_db=source_db,
            source_table=source_table,
            error=f"检测源表 {source_db}.{source_table} 失败：{exc}",
        )
    finally:
        if conn is not None:
            deps.close_safely(conn)


def check_source_formation_status(source_mode, *, deps):
    """Check one configured source formation table and preserve the reason on failure."""
    source_mode = str(source_mode)
    game_configs = deps.get_game_configs()
    if source_mode not in game_configs:
        return FormationCheckStatus(
            source_mode=source_mode,
            exists=False,
            error=f"未配置局类型 {source_mode}",
        )

    table_config = game_configs[source_mode]['table_config']
    source_db = deps.get_table_database('SOURCE_TABLE', table_config)
    source_table = deps.get_table_name('SOURCE_TABLE', table_config)
    return check_physical_source_status(
        source_mode,
        source_db,
        source_table,
        deps=deps,
    )


def exists_map(statuses):
    return {mode: status.exists for mode, status in statuses.items()}


def error_map(statuses):
    return {
        mode: status.error
        for mode, status in statuses.items()
        if status.error
    }
