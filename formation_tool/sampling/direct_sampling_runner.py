"""Runner for direct sampling from formation source tables."""

from formation_tool.utils import log_utils

print = log_utils.emit


def _state_totals(state):
    totals = dict((state or {}).get('totals') or {})
    return {
        'sampled_count': int(totals.get('sampled_count') or 0),
        'remapped_id_count': int(totals.get('remapped_id_count') or 0),
        'remapped_row_count': int(totals.get('remapped_row_count') or 0),
    }


def direct_sample_from_source(table_config, sample_conditions, *, deps):
    """从源数据直接采样，写入目标表。"""
    source_conn = None
    final_conn = None
    names = {}
    staging_state = None
    task_state = None
    totals = {'sampled_count': 0, 'remapped_id_count': 0, 'remapped_row_count': 0}
    try:
        deps.check_cancelled()
        names = deps.get_direct_sampling_names(table_config)
        if deps.reject_same_physical_sampling_table(table_config, names):
            return False

        source_conn = deps.connect_by_table('SOURCE_TABLE', table_config)
        if not source_conn:
            print(f"无法建立 {names['source_db_name']} 连接，处理终止")
            return False

        sample_conditions = deps.resolve_direct_sample_conditions(
            source_conn,
            table_config,
            sample_conditions,
        )
        if sample_conditions is None:
            return False
        warn_sampling_read_index = getattr(deps, 'warn_sampling_read_index', lambda *_args, **_kwargs: None)
        warn_sampling_read_index(
            source_conn,
            names['source_table_name'],
            sample_conditions,
        )

        final_conn = deps.connect_by_table('FINAL_TABLE', table_config)
        if not final_conn:
            print(f"无法建立 {names['final_db_name']} 连接，处理终止")
            return False

        source_engine = deps.get_engine_by_table('SOURCE_TABLE', table_config)
        final_engine = deps.get_engine_by_table('FINAL_TABLE', table_config)
        config_engine = deps.get_engine_by_table('REBATE_CONFIG_TABLE', table_config)

        try:
            config_df = deps.load_sampling_config_df(
                config_engine,
                names['config_db_name'],
                names['rebate_config_table_name'],
            )
            if config_df is None:
                return False
        except Exception as e:
            print(f"读取 {names['config_db_name']} 的 {names['rebate_config_table_name']} 表失败: {e}")
            return False

        append_mode = deps.get_append_mode()
        build_sampling_task_identity = getattr(deps, 'build_sampling_task_identity', None)
        load_sampling_task_state = getattr(deps, 'load_sampling_task_state', lambda _identity: None)
        try_resume_direct_sampling_staging = getattr(
            deps,
            'try_resume_direct_sampling_staging',
            lambda *_args: None,
        )
        start_sampling_task_state = getattr(deps, 'start_sampling_task_state', lambda *_args: None)
        mark_sampling_task_completed = getattr(deps, 'mark_sampling_task_completed', lambda *_args, **_kwargs: None)

        task_identity = None
        resume_totals = None
        if build_sampling_task_identity is not None:
            task_identity = build_sampling_task_identity(names, sample_conditions, append_mode)
            task_state = load_sampling_task_state(task_identity)
            if task_state is not None:
                resume_result = try_resume_direct_sampling_staging(final_conn, names, task_state)
                if resume_result:
                    staging_state, resume_totals = resume_result

        if staging_state is None:
            staging_state = deps.prepare_direct_sampling_staging(
                source_conn,
                final_conn,
                table_config,
                names,
                append_mode,
            )
            if staging_state is None:
                return False
            if task_identity is not None:
                task_state = start_sampling_task_state(task_identity, staging_state, config_df)

        if resume_totals is not None:
            totals = dict(resume_totals)
        totals, final_conn = deps.sample_config_rows_to_staging(
            config_df,
            names=names,
            sample_conditions=sample_conditions,
            source_engine=source_engine,
            final_engine=final_engine,
            final_conn=final_conn,
            staging_state=staging_state,
            append_mode=append_mode,
            task_state=task_state,
            initial_totals=resume_totals,
        )
        success, final_conn = deps.finalize_direct_sampling_staging(
            final_conn,
            names,
            staging_state,
            totals,
            append_mode,
        )
        mark_sampling_task_completed(task_state, success=success)
        return success

    except Exception as e:
        mark_sampling_task_failed = getattr(deps, 'mark_sampling_task_failed', lambda *_args, **_kwargs: None)
        mark_sampling_task_failed(task_state, e)
        if task_state is not None:
            totals = _state_totals(task_state)
        final_conn = deps.cleanup_direct_sampling_failure(
            e,
            final_conn,
            names,
            staging_state,
            totals.get('sampled_count', 0),
        )
        deps.print_step_error("采样处理过程中出错", e)
        raise
    finally:
        deps.close_safely(source_conn)
        deps.close_safely(final_conn)

