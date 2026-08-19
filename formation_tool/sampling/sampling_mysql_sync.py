"""MySQL CLI dump/import helpers used by sampling table synchronization."""

import contextlib
import os
import shutil
import subprocess
import tempfile

from formation_tool.utils import log_utils

print = log_utils.emit


def find_mysql_cli_executable(executable_name, *, shutil_module=shutil, os_module=os):
    """Find mysql/mysqldump without requiring users to type the full path."""
    names = [executable_name]
    if not executable_name.lower().endswith('.exe'):
        names.append(f"{executable_name}.exe")

    candidates = []
    for name in names:
        found = shutil_module.which(name)
        if found:
            candidates.append(found)

    for env_key in ('ProgramFiles', 'ProgramFiles(x86)'):
        base_dir = os_module.environ.get(env_key)
        if not base_dir:
            continue
        for version in ('8.4', '8.0', '5.7'):
            for name in names:
                candidates.append(os_module.path.join(base_dir, 'MySQL', f'MySQL Server {version}', 'bin', name))

    for path in candidates:
        if path and os_module.path.exists(path):
            return path
    raise RuntimeError(f"未找到 {executable_name}，请确认 MySQL Client 已安装并加入 PATH")


def mysql_cli_env(db_config, *, os_module=os):
    env = os_module.environ.copy()
    password = db_config.get('password')
    if password:
        env['MYSQL_PWD'] = str(password)
    return env


def mysql_cli_common_args(executable_path, db_config):
    return [
        executable_path,
        f"--host={db_config['host']}",
        f"--port={int(db_config['port'])}",
        f"--user={db_config['user']}",
        "--protocol=TCP",
        "--default-character-set=utf8mb4",
    ]


def decode_cli_output(value):
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode('utf-8', errors='replace').strip()
    return str(value).strip()


def run_mysql_cli_command(args, *, env, label, input_path=None, subprocess_module=subprocess):
    input_file = None
    try:
        if input_path:
            input_file = open(input_path, 'rb')
        completed = subprocess_module.run(
            args,
            stdin=input_file,
            stdout=subprocess_module.PIPE,
            stderr=subprocess_module.PIPE,
            env=env,
            check=False,
        )
    finally:
        if input_file is not None:
            input_file.close()

    if completed.returncode != 0:
        stdout_text = decode_cli_output(completed.stdout)
        stderr_text = decode_cli_output(completed.stderr)
        detail = stderr_text or stdout_text or "无错误输出"
        raise RuntimeError(f"{label}失败，退出码 {completed.returncode}：{detail[-2000:]}")
    return completed


def dump_mysql_table_data(
    source_db_config,
    source_table_name,
    dump_path,
    *,
    label,
    os_module=os,
    shutil_module=shutil,
    subprocess_module=subprocess,
):
    mysqldump_path = find_mysql_cli_executable(
        'mysqldump',
        os_module=os_module,
        shutil_module=shutil_module,
    )
    args = mysql_cli_common_args(mysqldump_path, source_db_config) + [
        "--column-statistics=0",
        "--single-transaction",
        "--quick",
        "--skip-lock-tables",
        "--no-create-info",
        "--skip-triggers",
        "--skip-add-locks",
        "--skip-comments",
        "--compact",
        "--hex-blob",
        f"--result-file={dump_path}",
        source_db_config['database'],
        source_table_name,
    ]
    env = mysql_cli_env(source_db_config, os_module=os_module)
    try:
        return run_mysql_cli_command(args, env=env, label=label, subprocess_module=subprocess_module)
    except RuntimeError as exc:
        if "column-statistics" not in str(exc):
            raise
        retry_args = [arg for arg in args if arg != "--column-statistics=0"]
        return run_mysql_cli_command(retry_args, env=env, label=label, subprocess_module=subprocess_module)


def backticked_identifier_bytes(table_name):
    return f"`{table_name}`".encode('utf-8')


def rewrite_dump_table_name(dump_path, import_path, source_table_name, target_table_name):
    source_token = backticked_identifier_bytes(source_table_name)
    target_token = backticked_identifier_bytes(target_table_name)
    with open(dump_path, 'rb') as source_file, open(import_path, 'wb') as target_file:
        for line in source_file:
            target_file.write(line.replace(source_token, target_token))


def import_mysql_dump_file(
    target_db_config,
    import_path,
    *,
    label,
    os_module=os,
    shutil_module=shutil,
    subprocess_module=subprocess,
):
    mysql_path = find_mysql_cli_executable(
        'mysql',
        os_module=os_module,
        shutil_module=shutil_module,
    )
    args = mysql_cli_common_args(mysql_path, target_db_config) + [
        f"--database={target_db_config['database']}",
        "--binary-mode",
    ]
    return run_mysql_cli_command(
        args,
        env=mysql_cli_env(target_db_config, os_module=os_module),
        label=label,
        input_path=import_path,
        subprocess_module=subprocess_module,
    )


def dump_import_table_between_databases(
    source_db_config,
    target_db_config,
    source_table_name,
    target_table_name,
    *,
    label,
    reprepare_target=None,
    max_retries=1,
    retry_delay=0,
    check_cancelled_func=lambda: None,
    sleep_func=lambda _seconds: None,
    print_func=None,
    os_module=os,
    shutil_module=shutil,
    subprocess_module=subprocess,
    tempfile_module=tempfile,
):
    emit = print_func or print
    temp_dir = tempfile_module.mkdtemp(prefix='formation_mysql_dump_')
    dump_path = os_module.path.join(temp_dir, 'source.sql')
    import_path = os_module.path.join(temp_dir, 'target.sql')
    try:
        max_retries = max(1, int(max_retries or 1))
        retry_delay = int(retry_delay or 0)
        for attempt in range(1, max_retries + 1):
            check_cancelled_func()
            try:
                with contextlib.suppress(Exception):
                    os_module.remove(dump_path)
                emit(f"{label}：使用 mysqldump 导出 {source_table_name} (第 {attempt}/{max_retries} 次)")
                dump_mysql_table_data(
                    source_db_config,
                    source_table_name,
                    dump_path,
                    label=f"{label} dump导出",
                    os_module=os_module,
                    shutil_module=shutil_module,
                    subprocess_module=subprocess_module,
                )
                if attempt > 1:
                    emit(f"{label}：第 {attempt} 次重试导出成功")
                break
            except Exception as exc:
                if attempt >= max_retries:
                    raise
                emit(f"{label}：dump导出失败 (第{attempt}次)：{exc}")
                emit(f"等待{retry_delay}秒后重试...")
                sleep_func(retry_delay)
        check_cancelled_func()
        rewrite_dump_table_name(dump_path, import_path, source_table_name, target_table_name)
        for attempt in range(1, max_retries + 1):
            check_cancelled_func()
            if attempt > 1 and callable(reprepare_target):
                reprepare_target()
            try:
                emit(f"{label}：导入到目标临时表 {target_table_name} (第 {attempt}/{max_retries} 次)")
                import_mysql_dump_file(
                    target_db_config,
                    import_path,
                    label=f"{label} dump导入",
                    os_module=os_module,
                    shutil_module=shutil_module,
                    subprocess_module=subprocess_module,
                )
                if attempt > 1:
                    emit(f"{label}：第 {attempt} 次重试导入成功")
                return True
            except Exception as exc:
                if attempt >= max_retries:
                    raise
                emit(f"{label}：dump导入失败 (第{attempt}次)：{exc}")
                emit(f"等待{retry_delay}秒后重试...")
                sleep_func(retry_delay)
        return False
    finally:
        with contextlib.suppress(Exception):
            shutil_module.rmtree(temp_dir)
