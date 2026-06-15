"""Factories for runtime contexts injected into worker modules."""

from types import SimpleNamespace


def build_sampling_core_context(runtime, deps):
    """Build the context object consumed by sampling_core.configure()."""
    return SimpleNamespace(
        DATABASE_CONFIGS=runtime.database_configs,
        MAX_DB_RETRIES=runtime.max_db_retries,
        DB_RETRY_DELAY=runtime.db_retry_delay,
        SAMPLE_ID_FETCH_CHUNK_SIZE=deps.sample_id_fetch_chunk_size,
        SAMPLING_APPEND_MODE=runtime.sampling_append_mode,
        check_cancelled=deps.check_cancelled,
        chunked=deps.chunked,
        close_safely=deps.close_safely,
        connect_by_table=deps.connect_by_table,
        count_table_rows=deps.count_table_rows,
        copy_table_rows=deps.copy_table_rows,
        drop_table_if_exists=deps.drop_table_if_exists,
        ensure_database_connection=deps.ensure_database_connection,
        get_db_config_by_name=deps.get_db_config_by_name,
        get_engine_by_table=deps.get_engine_by_table,
        get_existing_ids=deps.get_existing_ids,
        get_table_database=deps.get_table_database,
        get_table_max_id=deps.get_table_max_id,
        get_table_name=deps.get_table_name,
        make_staging_table_name=deps.make_staging_table_name,
        print_step_error=deps.print_step_error,
        quote_identifier=deps.quote_identifier,
        refresh_connection_read_view=deps.refresh_connection_read_view,
        replace_table_with_staging=deps.replace_table_with_staging,
        sql_with_retry=deps.sql_with_retry,
        table_exists_exact=deps.table_exists_exact,
        validate_sql_identifier=deps.validate_sql_identifier,
    )


def build_group_weight_builder_context(runtime, constants, deps):
    """Build the context object consumed by group_weight_builder.configure()."""
    return SimpleNamespace(
        WEIGHT_GROUP_IDS=constants.weight_group_ids,
        GROUP_WEIGHT_MODES=constants.group_weight_modes,
        EX_GROUP_MODES=constants.ex_group_modes,
        EX_INDEPENDENT_GROUP_WEIGHT_MODES=constants.ex_independent_group_weight_modes,
        BUY_GROUP_MODE=constants.buy_group_mode,
        EX_PURCHASE_MODE=constants.ex_purchase_mode,
        GROUP_WEIGHT_MODE_DEFS=constants.group_weight_mode_defs,
        GROUP_WEIGHT_RULES=runtime.group_weight_rules,
        GAME_TYPE_NAMES=constants.game_type_names,
        SPECIAL_GROUP_TARGET_RTP=runtime.special_group_target_rtp,
        EX_GROUP_TARGET_RTPS=getattr(runtime, 'ex_group_target_rtps', {}),
        BUY_GROUP_ENABLED=runtime.buy_group_enabled,
        EX_BUY_GROUP_ENABLED=runtime.ex_buy_group_enabled,
        BUY_GROUP_GAME_TYPE=runtime.buy_group_game_type,
        BUY_GROUP_MULTIPLIER=runtime.buy_group_multiplier,
        BUY_GROUP_SOURCE_SUFFIX=runtime.buy_group_source_suffix,
        EX_GROUP_MULTIPLIER=runtime.ex_group_multiplier,
        EXTRA_BUY_GROUPS=runtime.extra_buy_groups,
        build_normal_group_weight_rows_for_group=deps.build_normal_group_weight_rows_for_group,
        check_cancelled=deps.check_cancelled,
        make_extra_buy_mode=deps.make_extra_buy_mode,
        get_extra_buy_game_type=deps.get_extra_buy_game_type,
        get_extra_buy_group_by_mode=deps.get_extra_buy_group_by_mode,
        get_buy_group_game_type_for_mode=deps.get_buy_group_game_type_for_mode,
        get_group_weight_write_game_type=deps.get_group_weight_write_game_type,
        get_group_target_rtp_ratio=deps.get_group_target_rtp_ratio,
        get_group_weight_mode_name=deps.get_group_weight_mode_name,
        get_group_weight_rebate_source_mode=deps.get_group_weight_rebate_source_mode,
        get_group_weight_rebate_table_name=deps.get_group_weight_rebate_table_name,
        get_group_weight_rtp_role=deps.get_group_weight_rtp_role,
        is_extra_buy_mode=deps.is_extra_buy_mode,
    )

