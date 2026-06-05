"""Database runtime helpers for table-driven game type configuration."""

from dataclasses import dataclass, field
from types import SimpleNamespace


@dataclass
class GameTypeConfigCache:
    """Small per-runtime cache for game_type config and source-table existence."""

    configs: dict = field(default_factory=dict)
    config_db: str | None = None
    config_error: str | None = None
    config_loaded: bool = False
    source_exists: dict = field(default_factory=dict)

    def reset(self):
        self.configs = {}
        self.config_db = None
        self.config_error = None
        self.config_loaded = False
        self.source_exists = {}

    def reset_source_exists(self):
        self.source_exists = {}


def build_game_type_config_query(table_name, quote_identifier):
    table_ref = quote_identifier(table_name, "类型配置表名")
    return (
        f"SELECT `game_type`, `source_suffix`, `is_buy` "
        f"FROM {table_ref} ORDER BY `game_type`"
    )


def load_game_type_configs(
    *,
    final_db,
    table_name,
    cache,
    force,
    connect_to_database,
    table_exists_exact,
    quote_identifier,
    close_safely,
    build_config_map,
):
    """Load game_type/source_suffix/is_buy definitions from the final DB."""
    final_db = str(final_db or '').strip()
    if not force and cache.config_loaded and cache.config_db == final_db:
        return cache.configs

    cache.configs = {}
    cache.config_db = final_db
    cache.config_error = None
    cache.config_loaded = True
    if not final_db:
        cache.config_error = f"未选择目标库，无法读取 {table_name}"
        return cache.configs

    conn = connect_to_database(final_db)
    if not conn:
        cache.config_error = f"无法连接目标库 {final_db}，无法读取 {table_name}"
        return cache.configs

    try:
        if not table_exists_exact(conn, table_name):
            cache.config_error = f"{final_db}.{table_name} 不存在"
            return cache.configs
        with conn.cursor() as cur:
            cur.execute(build_game_type_config_query(table_name, quote_identifier))
            rows = cur.fetchall()
        try:
            cache.configs = build_config_map(rows)
        except (TypeError, ValueError) as exc:
            cache.configs = {}
            cache.config_error = f"{table_name} 配置内容无效：{exc}"
            return cache.configs
        cache.config_error = None
        return cache.configs
    except Exception as exc:
        cache.configs = {}
        cache.config_error = f"读取 {table_name} 异常：{exc}"
        return cache.configs
    finally:
        close_safely(conn)


def _source_cache_key(source_db, table_prefix, configs):
    config_signature = tuple(
        (int(game_type), str(item.get('source_suffix') or ''))
        for game_type, item in sorted((configs or {}).items(), key=lambda pair: int(pair[0]))
    )
    return (str(source_db or ''), str(table_prefix or ''), config_signature)


def get_existing_source_game_types(
    *,
    configs,
    source_db,
    table_prefix,
    cache,
    connect_to_database,
    table_exists_exact,
    close_safely,
    force=False,
):
    """Return `(existing_game_types, skipped_rows)` for current room source tables."""
    source_db = str(source_db or '').strip()
    if not source_db:
        raise ValueError("未选择源库，无法按阵型表过滤购买局类型")

    cache_key = _source_cache_key(source_db, table_prefix, configs)
    if force:
        cache.source_exists.pop(cache_key, None)
    if cache_key in cache.source_exists:
        cached = cache.source_exists[cache_key]
        return set(cached['existing']), [dict(item) for item in cached['skipped']]

    conn = connect_to_database(source_db)
    if not conn:
        raise ValueError(f"无法连接源库 {source_db}，无法加载阵型对应类型")

    existing = set()
    skipped = []
    try:
        for game_type, item in sorted((configs or {}).items(), key=lambda pair: int(pair[0])):
            suffix = item.get('source_suffix')
            table_name = f"{table_prefix}{suffix}"
            if table_exists_exact(conn, table_name):
                existing.add(int(game_type))
            else:
                skipped.append({
                    'game_type': int(game_type),
                    'source_suffix': suffix,
                    'table_name': table_name,
                })
        cache.source_exists[cache_key] = {
            'existing': set(existing),
            'skipped': [dict(item) for item in skipped],
        }
        return existing, skipped
    finally:
        close_safely(conn)


def load_buy_group_options_from_game_type_config(
    *,
    final_db,
    source_db,
    table_prefix,
    table_name,
    cache,
    force_source,
    current_buy_game_type,
    current_buy_multiplier,
    current_buy_source_suffix,
    existing_extra_buy_groups,
    default_buy_game_type,
    deps,
):
    """Load DB game_type rows, filter by existing source tables, and build UI buy options."""
    configs = load_game_type_configs(
        final_db=final_db,
        table_name=table_name,
        cache=cache,
        force=True,
        connect_to_database=deps.connect_to_database,
        table_exists_exact=deps.table_exists_exact,
        quote_identifier=deps.quote_identifier,
        close_safely=deps.close_safely,
        build_config_map=deps.build_config_map,
    )
    if cache.config_error:
        raise ValueError(f"读取 {final_db}.{table_name} 失败：{cache.config_error}")
    if not configs:
        raise ValueError(f"{final_db}.{table_name} 没有可用配置")

    existing_source_game_types, skipped = get_existing_source_game_types(
        configs=configs,
        source_db=source_db,
        table_prefix=table_prefix,
        cache=cache,
        connect_to_database=deps.connect_to_database,
        table_exists_exact=deps.table_exists_exact,
        close_safely=deps.close_safely,
        force=force_source,
    )
    options = deps.build_buy_group_options_from_configs(
        configs,
        current_buy_game_type=current_buy_game_type,
        current_buy_multiplier=current_buy_multiplier,
        current_buy_source_suffix=current_buy_source_suffix,
        existing_extra_buy_groups=existing_extra_buy_groups,
        existing_source_game_types=existing_source_game_types,
        default_buy_game_type=default_buy_game_type,
    )
    options.update({
        'source_db': source_db,
        'final_db': final_db,
        'config_table': table_name,
        'loaded_count': len(configs),
        'existing_source_game_types': sorted(existing_source_game_types),
        'skipped': skipped,
    })
    return options


def build_buy_group_option_deps(
    *,
    connect_to_database,
    table_exists_exact,
    quote_identifier,
    close_safely,
    build_config_map,
    build_buy_group_options_from_configs,
):
    return SimpleNamespace(
        connect_to_database=connect_to_database,
        table_exists_exact=table_exists_exact,
        quote_identifier=quote_identifier,
        close_safely=close_safely,
        build_config_map=build_config_map,
        build_buy_group_options_from_configs=build_buy_group_options_from_configs,
    )
