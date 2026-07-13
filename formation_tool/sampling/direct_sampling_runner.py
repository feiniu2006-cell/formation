"""Runner for direct sampling from formation source tables."""

import inspect

from formation_tool.utils import log_utils

print = log_utils.emit


def _state_totals(state):
    totals = dict((state or {}).get('totals') or {})
    return {
        'sampled_count': int(totals.get('sampled_count') or 0),
        'remapped_id_count': int(totals.get('remapped_id_count') or 0),
        'remapped_row_count': int(totals.get('remapped_row_count') or 0),
    }


def _call_with_supported_kwargs(func, *args, **kwargs):
    """Call a dependency while preserving compatibility with older test doubles."""
    if not kwargs:
        return func(*args)
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return func(*args, **kwargs)
    parameters = signature.parameters
    if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in parameters.values()):
        return func(*args, **kwargs)
    supported = {
        key: value
        for key, value in kwargs.items()
        if key in parameters
    }
    return func(*args, **supported)


def direct_sample_from_source(table_config, sample_conditions, *, deps, append_mode=False):
    """从源数据直接采样，写入目标表。"""
    source_conn = None
    final_conn = None
    staging_conn = None
    using_separate_staging = False
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

        source_engine = deps.get_engine_by_table('SOURCE_TABLE', table_config)
        config_engine = deps.get_engine_by_table('REBATE_CONFIG_TABLE', table_config)
        append_mode = bool(append_mode)
        get_sampling_staging_table_config = getattr(
            deps,
            'get_sampling_staging_table_config',
            lambda config: config,
        )
        staging_table_config = get_sampling_staging_table_config(table_config)
        if names.get('staging_db_name') and names.get('staging_db_name') != names.get('final_db_name'):
            using_separate_staging = True
            staging_conn = deps.connect_by_table('FINAL_TABLE', staging_table_config)
            if not staging_conn:
                print(f"无法建立采样临时库 {names['staging_db_name']} 连接，处理终止")
                return False
            staging_engine = deps.get_engine_by_table('FINAL_TABLE', staging_table_config)
            final_engine = None
            if append_mode:
                final_conn = deps.connect_by_table('FINAL_TABLE', table_config)
                if not final_conn:
                    print(f"无法建立 {names['final_db_name']} 连接，追加采样处理终止")
                    return False
                final_engine = deps.get_engine_by_table('FINAL_TABLE', table_config)
        else:
            final_conn = deps.connect_by_table('FINAL_TABLE', table_config)
            if not final_conn:
                print(f"无法建立 {names['final_db_name']} 连接，处理终止")
                return False
            final_engine = deps.get_engine_by_table('FINAL_TABLE', table_config)
            staging_conn = final_conn
            staging_engine = final_engine

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
                resume_result = try_resume_direct_sampling_staging(staging_conn, names, task_state)
                if resume_result:
                    staging_state, resume_totals = resume_result

        if staging_state is None:
            staging_state = _call_with_supported_kwargs(
                deps.prepare_direct_sampling_staging,
                source_conn,
                staging_conn,
                table_config,
                names,
                append_mode,
                final_target_conn=final_conn,
                staging_table_config=staging_table_config,
                final_engine=final_engine,
                staging_engine=staging_engine,
            )
            if staging_state is None:
                return False
            if task_identity is not None:
                task_state = start_sampling_task_state(task_identity, staging_state, config_df)

        if resume_totals is not None:
            totals = dict(resume_totals)
        totals, write_conn = deps.sample_config_rows_to_staging(
            config_df,
            names=names,
            sample_conditions=sample_conditions,
            source_engine=source_engine,
            final_engine=staging_engine,
            final_conn=staging_conn,
            staging_state=staging_state,
            append_mode=append_mode,
            task_state=task_state,
            initial_totals=resume_totals,
        )
        if using_separate_staging:
            staging_conn = write_conn
        else:
            final_conn = write_conn
            staging_conn = final_conn
        success, final_conn = _call_with_supported_kwargs(
            deps.finalize_direct_sampling_staging,
            final_conn,
            names,
            staging_state,
            totals,
            append_mode,
            source_conn=source_conn,
            table_config=table_config,
            staging_conn=staging_conn,
            staging_engine=staging_engine,
            final_engine=final_engine,
        )
        mark_sampling_task_completed(task_state, success=success)
        return success

    except Exception as e:
        mark_sampling_task_failed = getattr(deps, 'mark_sampling_task_failed', lambda *_args, **_kwargs: None)
        mark_sampling_task_failed(task_state, e)
        if task_state is not None:
            totals = _state_totals(task_state)
        final_conn = _call_with_supported_kwargs(
            deps.cleanup_direct_sampling_failure,
            e,
            final_conn,
            names,
            staging_state,
            totals.get('sampled_count', 0),
            staging_conn=staging_conn,
        )
        deps.print_step_error("采样处理过程中出错", e)
        raise
    finally:
        deps.close_safely(source_conn)
        if using_separate_staging and staging_conn is not None:
            deps.close_safely(staging_conn)
        if final_conn is not None:
            deps.close_safely(final_conn)

