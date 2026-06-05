#!/usr/bin/env python3
"""
通用数据库全量备份脚本：
将源数据库的全部表结构和数据复制到目标数据库。

依赖：
    pip install sqlalchemy pymysql
    # dump 方式还需本机已安装 MySQL 客户端：mysqldump、mysql（在 PATH 中）

脚本内置数据库配置，默认 DB1 -> DB2。
默认使用 mysqldump + mysql；启动时会自检客户端是否可用。

示例：
    py -3 backup_db.py
    py -3 backup_db.py --dump-file ndngames_backup.sql
    # 仍使用 Python 逐表复制：
    py -3 backup_db.py --method python
"""

from __future__ import annotations

import argparse
import contextlib
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Iterable

from sqlalchemy import MetaData, create_engine, func, inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.engine.url import URL, make_url
from sqlalchemy.sql.schema import Table

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext, ttk
except ImportError:
    tk = None
    filedialog = None
    messagebox = None
    scrolledtext = None
    ttk = None

BACKUP_KEEP_COUNT = 5

import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from db_config import DATABASE_CONFIGS

# ── 备份配置：修改这两行即可 ──────────────────────────────────
SOURCE_KEY = 'DB1'   # 源库（被备份的数据库）
TARGET_KEY = 'MY'   # 目标库（备份写入的服务器）
# ────────────────────────────────────────────────────────────


def get_db_config(config_name: str) -> dict:
    config = DATABASE_CONFIGS.get(config_name)
    if not config:
        raise RuntimeError(f"数据库配置不存在：{config_name}")
    return config


def require_fields(config_name: str, config: dict, required_fields: tuple[str, ...]) -> None:
    missing_fields = [field for field in required_fields if not config.get(field)]
    if missing_fields:
        missing_text = ", ".join(missing_fields)
        raise RuntimeError(f"{config_name} 缺少必要配置：{missing_text}")


def resolve_credential(config: dict, user_field: str, password_field: str) -> tuple[str, str]:
    user = config.get(user_field)
    password = config.get(password_field)

    # admin_user/admin_password 未配置时，回退到 user/password
    if not user and user_field != "user":
        user = config.get("user")
    if not password and password_field != "password":
        password = config.get("password")

    return user, password


def build_mysql_url(
    config_name: str,
    driver: str,
    database: str | None = None,
    user_field: str = "user",
    password_field: str = "password",
) -> str:
    config = get_db_config(config_name)
    require_fields(config_name, config, ("host", "port"))
    username, password = resolve_credential(config, user_field, password_field)
    if not username or not password:
        raise RuntimeError(f"{config_name} 缺少必要配置：{user_field}/{password_field}")

    db_name = database if database is not None else config.get("database")
    if db_name is None:
        raise RuntimeError(f"{config_name} 缺少必要配置：database")

    url = URL.create(
        drivername=driver,
        username=username,
        password=password,
        host=config["host"],
        port=int(config["port"]),
        database=db_name,
    )
    # 注意：str(URL) 在 SQLAlchemy 中默认会隐藏密码（显示为 ***），
    # 连接时必须使用未隐藏密码的字符串。
    return url.render_as_string(hide_password=False)


def mask_value(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 2:
        return "*" * len(value)
    return f"{value[0]}{'*' * (len(value) - 2)}{value[-1]}"


def safe_url_for_log(raw_url: str) -> str:
    parsed = make_url(raw_url)
    safe_password = mask_value(parsed.password)
    return str(parsed.set(password=safe_password))


def print_config_for_log(config_name: str) -> None:
    config = get_db_config(config_name)
    host = config.get("host", "")
    port = config.get("port", "")
    user = config.get("user", "")
    admin_user = config.get("admin_user", user)
    database = config.get("database", "<自动生成>")
    admin_password = config.get("admin_password", config.get("password"))
    print(
        f"[配置] {config_name}: host={host}, port={port}, user={user}, "
        f"password={mask_value(config.get('password'))}, database={database}"
    )
    print(
        f"[配置] {config_name} 管理账号: admin_user={admin_user}, "
        f"admin_password={mask_value(admin_password)}"
    )


def detect_outbound_ip(remote_host: str, remote_port: int) -> str:
    """探测当前机器访问目标数据库时使用的出口 IP。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect((remote_host, remote_port))
        return sock.getsockname()[0]
    except OSError:
        return "<未知>"
    finally:
        sock.close()


def print_access_denied_hint(config_name: str) -> None:
    config = get_db_config(config_name)
    host = config.get("host", "")
    port = int(config.get("port", 3306))
    user = config.get("user", "")
    outbound_ip = detect_outbound_ip(host, port)
    print(f"[排查] 当前机器访问 DB2 的出口IP: {outbound_ip}")
    print("[排查] 请在 DB2 上确认以下授权（示例）：")
    print(f"        SHOW GRANTS FOR '{user}'@'{outbound_ip}';")
    print(
        f"        GRANT ALL PRIVILEGES ON *.* TO '{user}'@'{outbound_ip}' "
        "IDENTIFIED BY '你的密码' WITH GRANT OPTION;"
    )
    print("        FLUSH PRIVILEGES;")


def _find_client(binary_name: str, override: str | None) -> str:
    if override:
        if Path(override).is_file():
            return str(Path(override).resolve())
        which_override = shutil.which(override)
        if which_override:
            return which_override
        raise RuntimeError(f"找不到指定的客户端：{override}")
    found = shutil.which(binary_name)
    if not found and binary_name.endswith(".exe"):
        found = shutil.which(binary_name[:-4])
    if not found:
        raise RuntimeError(
            f"未在 PATH 中找到 `{binary_name}`。请安装 MySQL 客户端工具，"
            f"或使用 --mysqldump-bin / --mysql-bin 指定完整路径。"
        )
    return found


def verify_mysql_client_tools(
    mysqldump_bin: str | None,
    mysql_bin: str | None,
    *,
    skip: bool = False,
) -> tuple[str, str]:
    """
    检查本机是否具备 mysqldump / mysql：能找到可执行文件且可运行 --version。
    返回解析后的绝对路径，供后续 subprocess 使用。
    """
    if skip:
        dump_path = _find_client("mysqldump.exe" if sys.platform == "win32" else "mysqldump", mysqldump_bin)
        mysql_path = _find_client("mysql.exe" if sys.platform == "win32" else "mysql", mysql_bin)
        return dump_path, mysql_path

    print("[环境] 正在检查 mysqldump / mysql 客户端…")
    dump_path = _find_client("mysqldump.exe" if sys.platform == "win32" else "mysqldump", mysqldump_bin)
    mysql_path = _find_client("mysql.exe" if sys.platform == "win32" else "mysql", mysql_bin)

    for label, path in (("mysqldump", dump_path), ("mysql", mysql_path)):
        try:
            completed = subprocess.run(
                [path, "--version"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except OSError as exc:
            raise RuntimeError(f"无法执行 {label}：{path}\n原因：{exc}") from exc

        if completed.returncode != 0:
            err = (completed.stderr or completed.stdout or "").strip()
            raise RuntimeError(
                f"{label} 执行 --version 失败（退出码 {completed.returncode}）：{path}\n{err}"
            )

        out = (completed.stdout or completed.stderr or "").strip()
        first_line = out.splitlines()[0] if out else "(无版本输出)"
        print(f"[环境] {label}: {path}")
        print(f"[环境] {label} --version → {first_line}")

    print("[环境] 检查通过，支持使用 mysqldump 方式备份。")
    return dump_path, mysql_path


def _write_client_defaults(path: Path, host: str, port: int, user: str, password: str) -> None:
    content = (
        "[client]\n"
        f"host={host}\n"
        f"port={port}\n"
        f"user={user}\n"
        f"password={password}\n"
    )
    path.write_text(content, encoding="utf-8")


def _mysql_params_from_config(config_name: str, *, need_database: bool) -> dict[str, str | int]:
    config = get_db_config(config_name)
    require_fields(config_name, config, ("host", "port"))
    username, password = resolve_credential(config, "user", "password")
    if not username or not password:
        raise RuntimeError(f"{config_name} 缺少 user/password")
    db = config.get("database")
    if need_database and not db:
        raise RuntimeError(f"{config_name} 缺少 database")
    return {
        "host": str(config["host"]),
        "port": int(config["port"]),
        "user": str(username),
        "password": str(password),
        "database": str(db) if db else "",
    }


def _mysql_params_from_sqlalchemy_url(url_str: str) -> dict[str, str | int]:
    parsed = make_url(url_str)
    if not parsed.host or not parsed.database:
        raise RuntimeError("连接串中必须包含 host 与 database")
    if not parsed.username or not parsed.password:
        raise RuntimeError("连接串中必须包含用户名与密码")
    return {
        "host": str(parsed.host),
        "port": int(parsed.port or 3306),
        "user": str(parsed.username),
        "password": str(parsed.password),
        "database": str(parsed.database),
    }


def backup_via_mysqldump(
    *,
    source_params: dict[str, str | int],
    target_params: dict[str, str | int],
    target_database: str,
    dump_file: Path | None,
    mysqldump_bin: str,
    mysql_bin: str,
) -> None:
    """
    使用 mysqldump + mysql 备份，避免 Python 逐行插入导致长时间无输出或事务过大。
    dump_file 若指定：先完整导出到本地文件，再导入（便于留档与重试）。
    """
    fd_src, src_cnf_str = tempfile.mkstemp(prefix="backup_src_", suffix=".cnf")
    fd_dst, dst_cnf_str = tempfile.mkstemp(prefix="backup_dst_", suffix=".cnf")
    os.close(fd_src)
    os.close(fd_dst)
    src_cnf = Path(src_cnf_str)
    dst_cnf = Path(dst_cnf_str)
    try:
        _write_client_defaults(
            src_cnf,
            str(source_params["host"]),
            int(source_params["port"]),
            str(source_params["user"]),
            str(source_params["password"]),
        )
        _write_client_defaults(
            dst_cnf,
            str(target_params["host"]),
            int(target_params["port"]),
            str(target_params["user"]),
            str(target_params["password"]),
        )
        for cnf in (src_cnf, dst_cnf):
            try:
                os.chmod(cnf, 0o600)
            except OSError:
                pass

        dump_bin = _find_client("mysqldump.exe" if sys.platform == "win32" else "mysqldump", mysqldump_bin)
        mysql_cli = _find_client("mysql.exe" if sys.platform == "win32" else "mysql", mysql_bin)

        dump_base = [
            dump_bin,
            f"--defaults-extra-file={src_cnf}",
            "--single-transaction",
            "--quick",
            "--routines",
            "--events",
            "--triggers",
            "--set-gtid-purged=OFF",
            str(source_params["database"]),
        ]

        mysql_base = [
            mysql_cli,
            f"--defaults-extra-file={dst_cnf}",
            target_database,
        ]

        # DEFINER 子句过滤：源库 DEFINER 用户在目标库不存在时需要 SUPER/SET_USER_ID，
        # 直接剥除可避免权限报错，导入后对象以导入用户身份生效。
        _definer_re = re.compile(rb"DEFINER=`[^`]*`@`[^`]*`\s*")

        # 导入含存储函数/触发器时，需要 log_bin_trust_function_creators=1（binlog 开启时）
        # 尝试在导入前临时设置，完成后重置；若权限不足则提示用户手动配置。
        _trust_url = (
            f"mysql+pymysql://{target_params['user']}:{target_params['password']}"
            f"@{target_params['host']}:{int(target_params['port'])}/{target_database}"
        )
        _trust_set = False
        try:
            _eng = create_engine(_trust_url)
            with _eng.connect() as _c:
                _c.execute(text("SET GLOBAL log_bin_trust_function_creators = 1"))
                _c.commit()
            _eng.dispose()
            _trust_set = True
            print("[阶段] 已临时启用目标库 log_bin_trust_function_creators=1")
        except Exception as _exc:
            print(f"[提示] 无法自动设置 log_bin_trust_function_creators：{str(_exc)[:300]}")
            print("[提示] 若导入时出现 ERROR 1419，请在目标 MySQL my.ini 的 [mysqld] 节中添加：")
            print("        log_bin_trust_function_creators = 1")
            print("        然后重启 MySQL 服务。")
            # 无法设置 trust 变量时，跳过存储函数/过程/事件/触发器，避免 ERROR 1419 导致备份失败
            dump_base = [x for x in dump_base if x not in ('--routines', '--events')]
            dump_base = [('--skip-triggers' if x == '--triggers' else x) for x in dump_base]
            print("[提示] 已自动跳过存储函数/过程/事件/触发器的导出")

        try:
            if dump_file is not None:
                dump_path = dump_file.resolve()
                print(f"[阶段] mysqldump 导出到文件: {dump_path}")
                dump_path.parent.mkdir(parents=True, exist_ok=True)
                with dump_path.open("wb") as out_f:
                    r_dump = subprocess.run(
                        dump_base,
                        stdout=out_f,
                        stderr=subprocess.PIPE,
                        check=False,
                    )
                if r_dump.returncode != 0:
                    err = r_dump.stderr.decode("utf-8", errors="replace")
                    raise RuntimeError(f"mysqldump 失败 (code={r_dump.returncode}): {err[:2000]}")
                size_mb = dump_path.stat().st_size / (1024 * 1024)
                print(f"[阶段] 导出完成，约 {size_mb:.2f} MB，正在剥除 DEFINER 子句...")
                tmp_path = dump_path.with_suffix(".tmp")
                with dump_path.open("rb") as src, tmp_path.open("wb") as dst:
                    for line in src:
                        dst.write(_definer_re.sub(b"", line))
                tmp_path.replace(dump_path)
                print(f"[阶段] DEFINER 剥除完成")

                print(f"[阶段] mysql 从文件导入到库 `{target_database}`")
                with dump_path.open("rb") as in_f:
                    r_mysql = subprocess.run(
                        mysql_base,
                        stdin=in_f,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        check=False,
                    )
                if r_mysql.returncode != 0:
                    err = r_mysql.stderr.decode("utf-8", errors="replace")
                    raise RuntimeError(f"mysql 导入失败 (code={r_mysql.returncode}): {err[:2000]}")
                print("[阶段] 导入完成")
                return

            print("[阶段] mysqldump 流式管道导入目标库（无中间大文件，过滤 DEFINER）")
            p_dump = subprocess.Popen(
                dump_base,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            assert p_dump.stdout is not None
            p_mysql = subprocess.Popen(
                mysql_base,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            assert p_mysql.stdin is not None

            dump_stderr_buf:  list[bytes] = []
            mysql_stderr_buf: list[bytes] = []

            def _read_dump_stderr():
                if p_dump.stderr:
                    dump_stderr_buf.append(p_dump.stderr.read())

            def _read_mysql_stderr():
                if p_mysql.stderr:
                    mysql_stderr_buf.append(p_mysql.stderr.read())

            def _drain_mysql_stdout():
                if p_mysql.stdout:
                    while p_mysql.stdout.read(65536):
                        pass

            def _pipe_filter():
                try:
                    for line in p_dump.stdout:
                        try:
                            p_mysql.stdin.write(_definer_re.sub(b"", line))
                        except (BrokenPipeError, ValueError, OSError):
                            # mysql 已提前退出，排空剩余输出让 mysqldump 能正常结束
                            while p_dump.stdout.read(65536):
                                pass
                            break
                finally:
                    try:
                        p_mysql.stdin.close()
                    except Exception:
                        pass

            filter_thread       = threading.Thread(target=_pipe_filter,        daemon=True)
            dump_stderr_thread  = threading.Thread(target=_read_dump_stderr,   daemon=True)
            mysql_stderr_thread = threading.Thread(target=_read_mysql_stderr,  daemon=True)
            mysql_stdout_thread = threading.Thread(target=_drain_mysql_stdout, daemon=True)
            filter_thread.start()
            dump_stderr_thread.start()
            mysql_stderr_thread.start()
            mysql_stdout_thread.start()

            # filter_thread 负责关闭 mysql stdin；其他线程随各自管道 EOF 自然结束
            filter_thread.join()
            mysql_stderr_thread.join()
            mysql_stdout_thread.join()
            dump_stderr_thread.join()

            rc_mysql = p_mysql.wait()
            rc_dump  = p_dump.wait()
            err_dump_b  = dump_stderr_buf[0]  if dump_stderr_buf  else b""
            err_mysql_b = mysql_stderr_buf[0] if mysql_stderr_buf else b""

            # 优先报 mysql 端错误：mysql 提前退出会导致管道断裂，
            # mysqldump 写入时得到 errno 22，掩盖真正的根因
            if rc_mysql != 0:
                err_mysql_s = err_mysql_b.decode("utf-8", errors="replace")
                err_dump_s  = err_dump_b.decode("utf-8", errors="replace")
                detail = f"mysql 导入失败 (code={rc_mysql}): {err_mysql_s[:2000]}"
                if err_dump_s.strip():
                    detail += f"\nmysqldump 附加信息: {err_dump_s[:500]}"
                raise RuntimeError(detail)
            if rc_dump != 0:
                err_dump = err_dump_b.decode("utf-8", errors="replace")
                raise RuntimeError(f"mysqldump 失败 (code={rc_dump}): {err_dump[:2000]}")
            print("[阶段] 流式导入完成")
        finally:
            if _trust_set:
                try:
                    _eng2 = create_engine(_trust_url)
                    with _eng2.connect() as _c2:
                        _c2.execute(text("SET GLOBAL log_bin_trust_function_creators = 0"))
                        _c2.commit()
                    _eng2.dispose()
                    print("[阶段] 已重置目标库 log_bin_trust_function_creators=0")
                except Exception:
                    pass
    finally:
        try:
            src_cnf.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            dst_cnf.unlink(missing_ok=True)
        except OSError:
            pass


def cleanup_old_backup_databases(conn, source_db_name: str, keep_count: int = BACKUP_KEEP_COUNT) -> None:
    """
    清理旧备份库：匹配 `<源库名>_YYYYMMDD_HHMMSS`。
    为保证创建新备份后总数不超过 keep_count，这里会在建库前最多保留 keep_count-1 个。
    """
    pattern = re.compile(rf"^{re.escape(source_db_name)}_(\d{{8}}_\d{{6}})$")

    all_databases = list(conn.execute(text("SHOW DATABASES")).scalars())
    matched: list[tuple[str, str]] = []
    for db_name in all_databases:
        match = pattern.fullmatch(db_name)
        if match:
            matched.append((match.group(1), db_name))

    matched.sort(key=lambda item: item[0])  # 时间戳格式可直接字典序排序
    if len(matched) < keep_count:
        print(f"[阶段] 现有同前缀备份库 {len(matched)} 个，无需清理。")
        return

    delete_count = len(matched) - (keep_count - 1)
    to_delete = matched[:delete_count]
    print(
        f"[阶段] 现有同前缀备份库 {len(matched)} 个，"
        f"将删除最旧的 {delete_count} 个后再创建新备份。"
    )
    for _, db_name in to_delete:
        escaped_name = db_name.replace("`", "``")
        conn.execute(text(f"DROP DATABASE `{escaped_name}`"))
        print(f"[清理] 已删除旧备份库: {db_name}")


def create_backup_database(source_key: str, backup_key: str, driver: str) -> tuple[str, str]:
    source_config = get_db_config(source_key)
    require_fields(source_key, source_config, ("database",))
    source_db_name = source_config["database"]

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_database_name = f"{source_db_name}_{timestamp}"
    print(f"[阶段] 准备创建备份库: {backup_database_name}")

    escaped_database_name = backup_database_name.replace("`", "``")
    admin_url = build_mysql_url(
        backup_key,
        driver,
        database="information_schema",
        user_field="admin_user",
        password_field="admin_password",
    )
    print(f"[连接] DB2管理连接: {safe_url_for_log(admin_url)}")
    try:
        with create_engine(admin_url).begin() as conn:
            identity = conn.execute(
                text("SELECT USER() AS login_user, CURRENT_USER() AS granted_user, @@hostname AS db_host")
            ).mappings().one()
            print(
                "[连接] DB2登录身份: "
                f"USER()={identity['login_user']}, "
                f"CURRENT_USER()={identity['granted_user']}, "
                f"@@hostname={identity['db_host']}"
            )

            cleanup_old_backup_databases(conn, source_db_name, keep_count=BACKUP_KEEP_COUNT)

            conn.execute(
                text(
                    f"CREATE DATABASE `{escaped_database_name}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
            )
    except SQLAlchemyError as exc:
        print("[错误] DB2管理连接或建库阶段失败。请检查 DB2 管理账号是否允许从当前机器登录。", file=sys.stderr)
        if "1045" in str(exc):
            print_access_denied_hint(backup_key)
        raise exc
    print(f"[阶段] 备份库创建成功: {backup_database_name}")

    backup_target_url = build_mysql_url(
        backup_key,
        driver,
        database=backup_database_name,
        user_field="user",
        password_field="password",
    )
    return backup_target_url, backup_database_name


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="将一个数据库的全部数据备份到另一个数据库（支持跨库引擎）。"
    )
    parser.add_argument(
        "--source-url",
        default=None,
        help="源数据库连接串，例如 mysql+pymysql://user:pwd@host:3306/dbname",
    )
    parser.add_argument(
        "--target-url",
        default=None,
        help="目标数据库连接串（如果传入则跳过自动新建备份库）。",
    )
    parser.add_argument(
        "--source-key",
        default=SOURCE_KEY,
        help=f"源数据库配置名（从 DATABASE_CONFIGS 中读取），默认 {SOURCE_KEY}。",
    )
    parser.add_argument(
        "--target-key",
        default=TARGET_KEY,
        help=f"备份库服务器配置名（从 DATABASE_CONFIGS 中读取），默认 {TARGET_KEY}。",
    )
    parser.add_argument(
        "--driver",
        default="mysql+pymysql",
        help="使用 DATABASE_CONFIGS 时的驱动名，默认 mysql+pymysql（自动建库仅支持 MySQL）。",
    )
    parser.add_argument(
        "--mode",
        choices=("replace", "append", "fail"),
        default="replace",
        help=(
            "目标库已存在数据时的策略："
            "replace=清空后再写入，append=追加，fail=发现已有数据则报错退出"
        ),
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="每批写入行数，默认 1000。",
    )
    parser.add_argument(
        "--method",
        choices=("python", "dump"),
        default="dump",
        help=(
            "dump=默认，使用 mysqldump+mysql（启动时会自检客户端）；"
            "python=用 SQLAlchemy 逐表复制。"
        ),
    )
    parser.add_argument(
        "--skip-dump-env-check",
        action="store_true",
        help="使用 dump 时跳过 mysqldump/mysql 的 --version 自检（仅仍校验可执行文件是否存在）。",
    )
    parser.add_argument(
        "--dump-file",
        default=None,
        help="method=dump 时可选：先导出为该 .sql 文件再导入（留档/便于重试）。",
    )
    parser.add_argument(
        "--mysqldump-bin",
        default=None,
        help="mysqldump 可执行文件路径（默认从 PATH 查找）。",
    )
    parser.add_argument(
        "--mysql-bin",
        default=None,
        help="mysql 客户端可执行文件路径（默认从 PATH 查找）。",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="打开图形界面。",
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="强制使用命令行模式；无参数运行时默认打开图形界面。",
    )
    return parser.parse_args(argv)


def reflect_source_tables(source_engine: Engine) -> MetaData:
    metadata = MetaData()
    metadata.reflect(bind=source_engine)
    return metadata


def ensure_target_schema(target_engine: Engine, metadata: MetaData) -> None:
    # 使用源库反射到的表结构在目标库创建缺失表。
    metadata.create_all(bind=target_engine)


def count_rows(engine: Engine, table: Table) -> int:
    with engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(table)).scalar_one()


def iter_batches(result, batch_size: int) -> Iterable[list[dict]]:
    while True:
        rows = result.fetchmany(batch_size)
        if not rows:
            break
        yield [dict(row._mapping) for row in rows]


def backup_all_tables(
    source_engine: Engine,
    target_engine: Engine,
    tables: list[Table],
    mode: str,
    batch_size: int,
) -> None:
    total_rows = 0

    with source_engine.connect() as source_conn:
        for table in tables:
            table_name = table.fullname
            print(f"\n[开始] 处理表: {table_name}")

            if mode in {"replace", "fail"}:
                existing_count = count_rows(target_engine, table)
                if mode == "fail" and existing_count > 0:
                    raise RuntimeError(
                        f"目标表 {table_name} 已有 {existing_count} 条数据，mode=fail 已停止。"
                    )

            with target_engine.begin() as target_conn:
                if mode == "replace":
                    target_conn.execute(table.delete())
                    print(f"  - 已清空目标表 {table_name}")

                result = source_conn.execution_options(stream_results=True).execute(
                    select(table)
                )
                inserted = 0

                for batch in iter_batches(result, batch_size):
                    target_conn.execute(table.insert(), batch)
                    inserted += len(batch)
                    total_rows += len(batch)

                print(f"  - 写入 {inserted} 条")

    print(f"\n[完成] 全部表备份完成，总写入行数: {total_rows}")


def run_backup(args: argparse.Namespace) -> int:
    print("[开始] 数据库备份任务启动")
    print(
        f"[参数] method={args.method}, source_key={args.source_key}, "
        f"target_key={args.target_key}, mode={args.mode}, batch_size={args.batch_size}"
    )
    if args.dump_file:
        print(f"[参数] dump_file={args.dump_file}")

    if args.batch_size <= 0:
        print("错误：--batch-size 必须大于 0", file=sys.stderr)
        return 2

    try:
        if args.method == "dump":
            resolved_dump, resolved_mysql = verify_mysql_client_tools(
                args.mysqldump_bin,
                args.mysql_bin,
                skip=args.skip_dump_env_check,
            )
            args.mysqldump_bin = resolved_dump
            args.mysql_bin = resolved_mysql

            if not args.source_url:
                print_config_for_log(args.source_key)
            if not args.target_url:
                print_config_for_log(args.target_key)

            if args.source_url:
                source_params = _mysql_params_from_sqlalchemy_url(args.source_url)
            else:
                source_params = _mysql_params_from_config(args.source_key, need_database=True)

            backup_database_name: str | None
            if args.target_url:
                target_params = _mysql_params_from_sqlalchemy_url(args.target_url)
                backup_database_name = str(target_params["database"])
                print(
                    "[提示] 已使用 --target-url：不会自动建库，请确认目标库已存在且为空。"
                )
            else:
                if not args.driver.startswith("mysql"):
                    raise RuntimeError("自动新建备份库仅支持 MySQL，请使用 --target-url 或改用 mysql+pymysql。")
                _, backup_database_name = create_backup_database(
                    source_key=args.source_key,
                    backup_key=args.target_key,
                    driver=args.driver,
                )
                target_params = _mysql_params_from_config(args.target_key, need_database=False)

            print(f"[连接] 源库(逻辑): {source_params['user']}@{source_params['host']}:{source_params['port']}/{source_params['database']}")
            print(
                f"[连接] 目标库(逻辑): {target_params['user']}@{target_params['host']}:"
                f"{target_params['port']}/{backup_database_name}"
            )

            dump_path = Path(args.dump_file).expanduser() if args.dump_file else None
            backup_via_mysqldump(
                source_params=source_params,
                target_params=target_params,
                target_database=str(backup_database_name),
                dump_file=dump_path,
                mysqldump_bin=args.mysqldump_bin,
                mysql_bin=args.mysql_bin,
            )
            print(f"备份完成，备份库名：{backup_database_name}")
            if dump_path is not None:
                print(f"SQL 文件已保存：{dump_path.resolve()}")
            return 0

        if not args.source_url:
            print_config_for_log(args.source_key)
        if not args.target_url:
            print_config_for_log(args.target_key)

        source_url = args.source_url or build_mysql_url(args.source_key, args.driver)
        print(f"[连接] 源库连接: {safe_url_for_log(source_url)}")
        if args.target_url:
            target_url = args.target_url
            backup_database_name = None
            print(f"[连接] 目标库连接(手动指定): {safe_url_for_log(target_url)}")
        else:
            if not args.driver.startswith("mysql"):
                raise RuntimeError("自动新建备份库仅支持 MySQL 驱动，请使用 --target-url 手动指定目标库。")
            target_url, backup_database_name = create_backup_database(
                source_key=args.source_key,
                backup_key=args.target_key,
                driver=args.driver,
            )
            print(f"[连接] 目标库连接(新建备份库): {safe_url_for_log(target_url)}")

        source_engine = create_engine(source_url)
        target_engine = create_engine(target_url)
        print("[阶段] 连接引擎创建完成")

        if backup_database_name:
            print(f"已创建备份库：{backup_database_name}")

        with source_engine.connect() as conn:
            source_identity = conn.execute(
                text("SELECT USER() AS login_user, CURRENT_USER() AS granted_user")
            ).mappings().one()
            print(
                "[连接] 源库登录身份: "
                f"USER()={source_identity['login_user']}, "
                f"CURRENT_USER()={source_identity['granted_user']}"
            )

        source_inspector = inspect(source_engine)
        table_names = source_inspector.get_table_names()
        if not table_names:
            print("源数据库没有可备份的数据表。")
            return 0

        metadata = reflect_source_tables(source_engine)
        tables = metadata.sorted_tables
        print(f"[阶段] 已读取源表结构，共 {len(tables)} 张表")

        if not tables:
            print("未反射到任何表结构，已退出。")
            return 0

        ensure_target_schema(target_engine, metadata)
        backup_all_tables(
            source_engine=source_engine,
            target_engine=target_engine,
            tables=tables,
            mode=args.mode,
            batch_size=args.batch_size,
        )
        if backup_database_name:
            print(f"备份完成，备份库名：{backup_database_name}")
        return 0
    except (SQLAlchemyError, RuntimeError, subprocess.SubprocessError, OSError) as exc:
        print(f"备份失败：{exc}", file=sys.stderr)
        return 1


class QueueWriter:
    """Forward stdout/stderr writes to the GUI log queue."""

    def __init__(self, log_queue: queue.Queue):
        self.log_queue = log_queue

    def write(self, message: str) -> int:
        if message:
            self.log_queue.put(message)
        return len(message)

    def flush(self) -> None:
        pass


class BackupDbApp:
    """Tkinter front end for the database backup workflow."""

    def __init__(self, root, initial_args: argparse.Namespace):
        self.root = root
        self.initial_args = initial_args
        self.worker_thread = None
        self.log_queue = queue.Queue()
        self.ui_queue = queue.Queue()
        self.normal_controls = []
        self.combo_controls = []

        config_keys = sorted(DATABASE_CONFIGS.keys())
        self.source_key_var = tk.StringVar(value=initial_args.source_key)
        self.target_key_var = tk.StringVar(value=initial_args.target_key)
        self.source_url_var = tk.StringVar(value=initial_args.source_url or "")
        self.target_url_var = tk.StringVar(value=initial_args.target_url or "")
        self.driver_var = tk.StringVar(value=initial_args.driver)
        self.method_var = tk.StringVar(value=initial_args.method)
        self.mode_var = tk.StringVar(value=initial_args.mode)
        self.batch_size_var = tk.StringVar(value=str(initial_args.batch_size))
        self.dump_file_var = tk.StringVar(value=initial_args.dump_file or "")
        self.mysqldump_bin_var = tk.StringVar(value=initial_args.mysqldump_bin or "")
        self.mysql_bin_var = tk.StringVar(value=initial_args.mysql_bin or "")
        self.skip_dump_env_check_var = tk.BooleanVar(value=initial_args.skip_dump_env_check)
        self.source_info_var = tk.StringVar()
        self.target_info_var = tk.StringVar()
        self.status_var = tk.StringVar(value="就绪")

        self.root.title("数据库备份工具")
        self.root.geometry("1040x760")
        self.root.minsize(900, 620)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui(config_keys)
        self._update_config_info()
        self._process_queues()

    def _build_ui(self, config_keys: list[str]) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        main = ttk.Frame(self.root, padding=12)
        main.grid(row=0, column=0, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(3, weight=1)

        title = ttk.Label(main, text="数据库备份工具", font=("Microsoft YaHei UI", 16, "bold"))
        title.grid(row=0, column=0, sticky="w")

        connection_frame = ttk.LabelFrame(main, text="连接设置", padding=10)
        connection_frame.grid(row=1, column=0, sticky="ew", pady=(10, 8))
        connection_frame.columnconfigure(1, weight=1)
        connection_frame.columnconfigure(3, weight=1)

        ttk.Label(connection_frame, text="源配置").grid(row=0, column=0, sticky="w")
        self.source_combo = ttk.Combobox(
            connection_frame,
            textvariable=self.source_key_var,
            values=config_keys,
            width=16,
            state="readonly",
        )
        self.source_combo.grid(row=0, column=1, sticky="w", padx=(8, 24))
        self.source_combo.bind("<<ComboboxSelected>>", lambda _event: self._update_config_info())
        self.combo_controls.append(self.source_combo)

        ttk.Label(connection_frame, text="目标配置").grid(row=0, column=2, sticky="w")
        self.target_combo = ttk.Combobox(
            connection_frame,
            textvariable=self.target_key_var,
            values=config_keys,
            width=16,
            state="readonly",
        )
        self.target_combo.grid(row=0, column=3, sticky="w", padx=(8, 0))
        self.target_combo.bind("<<ComboboxSelected>>", lambda _event: self._update_config_info())
        self.combo_controls.append(self.target_combo)

        ttk.Label(connection_frame, textvariable=self.source_info_var, foreground="#444").grid(
            row=1, column=1, sticky="w", padx=(8, 24), pady=(4, 0)
        )
        ttk.Label(connection_frame, textvariable=self.target_info_var, foreground="#444").grid(
            row=1, column=3, sticky="w", padx=(8, 0), pady=(4, 0)
        )

        ttk.Label(connection_frame, text="源连接串").grid(row=2, column=0, sticky="w", pady=(10, 0))
        source_url_entry = ttk.Entry(connection_frame, textvariable=self.source_url_var)
        source_url_entry.grid(row=2, column=1, columnspan=3, sticky="ew", padx=(8, 0), pady=(10, 0))
        self.normal_controls.append(source_url_entry)

        ttk.Label(connection_frame, text="目标连接串").grid(row=3, column=0, sticky="w", pady=(8, 0))
        target_url_entry = ttk.Entry(connection_frame, textvariable=self.target_url_var)
        target_url_entry.grid(row=3, column=1, columnspan=3, sticky="ew", padx=(8, 0), pady=(8, 0))
        self.normal_controls.append(target_url_entry)

        option_frame = ttk.LabelFrame(main, text="备份选项", padding=10)
        option_frame.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        option_frame.columnconfigure(1, weight=1)
        option_frame.columnconfigure(3, weight=1)

        ttk.Label(option_frame, text="备份方式").grid(row=0, column=0, sticky="w")
        method_combo = ttk.Combobox(
            option_frame,
            textvariable=self.method_var,
            values=("dump", "python"),
            width=14,
            state="readonly",
        )
        method_combo.grid(row=0, column=1, sticky="w", padx=(8, 24))
        self.combo_controls.append(method_combo)

        ttk.Label(option_frame, text="写入策略").grid(row=0, column=2, sticky="w")
        mode_combo = ttk.Combobox(
            option_frame,
            textvariable=self.mode_var,
            values=("replace", "append", "fail"),
            width=14,
            state="readonly",
        )
        mode_combo.grid(row=0, column=3, sticky="w", padx=(8, 0))
        self.combo_controls.append(mode_combo)

        ttk.Label(option_frame, text="驱动").grid(row=1, column=0, sticky="w", pady=(8, 0))
        driver_entry = ttk.Entry(option_frame, textvariable=self.driver_var)
        driver_entry.grid(row=1, column=1, sticky="ew", padx=(8, 24), pady=(8, 0))
        self.normal_controls.append(driver_entry)

        ttk.Label(option_frame, text="批量行数").grid(row=1, column=2, sticky="w", pady=(8, 0))
        batch_entry = ttk.Entry(option_frame, textvariable=self.batch_size_var, width=16)
        batch_entry.grid(row=1, column=3, sticky="w", padx=(8, 0), pady=(8, 0))
        self.normal_controls.append(batch_entry)

        ttk.Label(option_frame, text="SQL 文件").grid(row=2, column=0, sticky="w", pady=(8, 0))
        dump_entry = ttk.Entry(option_frame, textvariable=self.dump_file_var)
        dump_entry.grid(row=2, column=1, columnspan=2, sticky="ew", padx=(8, 8), pady=(8, 0))
        self.normal_controls.append(dump_entry)
        dump_button = ttk.Button(option_frame, text="浏览...", command=self._choose_dump_file)
        dump_button.grid(row=2, column=3, sticky="w", padx=(8, 0), pady=(8, 0))
        self.normal_controls.append(dump_button)

        ttk.Label(option_frame, text="mysqldump").grid(row=3, column=0, sticky="w", pady=(8, 0))
        dump_bin_entry = ttk.Entry(option_frame, textvariable=self.mysqldump_bin_var)
        dump_bin_entry.grid(row=3, column=1, sticky="ew", padx=(8, 8), pady=(8, 0))
        self.normal_controls.append(dump_bin_entry)
        dump_bin_button = ttk.Button(
            option_frame,
            text="选择...",
            command=lambda: self._choose_binary(self.mysqldump_bin_var, "选择 mysqldump"),
        )
        dump_bin_button.grid(row=3, column=2, sticky="w", pady=(8, 0))
        self.normal_controls.append(dump_bin_button)

        ttk.Label(option_frame, text="mysql").grid(row=4, column=0, sticky="w", pady=(8, 0))
        mysql_bin_entry = ttk.Entry(option_frame, textvariable=self.mysql_bin_var)
        mysql_bin_entry.grid(row=4, column=1, sticky="ew", padx=(8, 8), pady=(8, 0))
        self.normal_controls.append(mysql_bin_entry)
        mysql_bin_button = ttk.Button(
            option_frame,
            text="选择...",
            command=lambda: self._choose_binary(self.mysql_bin_var, "选择 mysql"),
        )
        mysql_bin_button.grid(row=4, column=2, sticky="w", pady=(8, 0))
        self.normal_controls.append(mysql_bin_button)

        skip_check = ttk.Checkbutton(
            option_frame,
            text="跳过 dump 环境自检",
            variable=self.skip_dump_env_check_var,
        )
        skip_check.grid(row=4, column=3, sticky="w", padx=(8, 0), pady=(8, 0))
        self.normal_controls.append(skip_check)

        action_frame = ttk.Frame(main)
        action_frame.grid(row=3, column=0, sticky="nsew")
        action_frame.columnconfigure(0, weight=1)
        action_frame.rowconfigure(1, weight=1)

        button_bar = ttk.Frame(action_frame)
        button_bar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.start_button = ttk.Button(button_bar, text="开始备份", command=self._start_backup)
        self.start_button.grid(row=0, column=0, sticky="w")
        clear_button = ttk.Button(button_bar, text="清空日志", command=self._clear_log)
        clear_button.grid(row=0, column=1, sticky="w", padx=(8, 0))
        self.progress = ttk.Progressbar(button_bar, mode="indeterminate", length=180)
        self.progress.grid(row=0, column=2, sticky="w", padx=(16, 0))

        log_frame = ttk.LabelFrame(action_frame, text="执行日志", padding=8)
        log_frame.grid(row=1, column=0, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            height=16,
            wrap="word",
            state="disabled",
            font=("Consolas", 10),
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")

        status_bar = ttk.Label(main, textvariable=self.status_var, anchor="w")
        status_bar.grid(row=4, column=0, sticky="ew", pady=(8, 0))

    def _config_summary(self, config_name: str) -> str:
        config = DATABASE_CONFIGS.get(config_name)
        if not config:
            return "未找到配置"
        host = config.get("host", "")
        port = config.get("port", "")
        database = config.get("database", "")
        user = config.get("user", "")
        return f"{user}@{host}:{port}/{database}"

    def _update_config_info(self) -> None:
        self.source_info_var.set(self._config_summary(self.source_key_var.get()))
        self.target_info_var.set(self._config_summary(self.target_key_var.get()))

    def _choose_dump_file(self) -> None:
        file_path = filedialog.asksaveasfilename(
            title="选择 SQL 文件",
            defaultextension=".sql",
            filetypes=[("SQL 文件", "*.sql"), ("所有文件", "*.*")],
        )
        if file_path:
            self.dump_file_var.set(file_path)

    def _choose_binary(self, target_var: tk.StringVar, title: str) -> None:
        file_path = filedialog.askopenfilename(
            title=title,
            filetypes=[("可执行文件", "*.exe"), ("所有文件", "*.*")],
        )
        if file_path:
            target_var.set(file_path)

    def _optional_text(self, value: str) -> str | None:
        value = value.strip()
        return value or None

    def _collect_args(self) -> argparse.Namespace | None:
        try:
            batch_size = int(self.batch_size_var.get().strip())
        except ValueError:
            messagebox.showerror("参数错误", "批量行数必须是整数。")
            return None
        if batch_size <= 0:
            messagebox.showerror("参数错误", "批量行数必须大于 0。")
            return None

        args = argparse.Namespace(**vars(self.initial_args))
        args.source_key = self.source_key_var.get().strip()
        args.target_key = self.target_key_var.get().strip()
        args.source_url = self._optional_text(self.source_url_var.get())
        args.target_url = self._optional_text(self.target_url_var.get())
        args.driver = self.driver_var.get().strip() or "mysql+pymysql"
        args.mode = self.mode_var.get().strip() or "replace"
        args.batch_size = batch_size
        args.method = self.method_var.get().strip() or "dump"
        args.skip_dump_env_check = bool(self.skip_dump_env_check_var.get())
        args.dump_file = self._optional_text(self.dump_file_var.get())
        args.mysqldump_bin = self._optional_text(self.mysqldump_bin_var.get())
        args.mysql_bin = self._optional_text(self.mysql_bin_var.get())
        args.gui = False
        args.cli = True
        return args

    def _append_log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _set_busy(self, busy: bool) -> None:
        self.start_button.configure(state="disabled" if busy else "normal")
        for widget in self.normal_controls:
            widget.configure(state="disabled" if busy else "normal")
        for widget in self.combo_controls:
            widget.configure(state="disabled" if busy else "readonly")
        if busy:
            self.progress.start(12)
            self.status_var.set("正在备份...")
        else:
            self.progress.stop()

    def _process_queues(self) -> None:
        while True:
            try:
                message = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self._append_log(message)

        while True:
            try:
                event = self.ui_queue.get_nowait()
            except queue.Empty:
                break

            event_type, return_code = event
            if event_type == "done":
                self._set_busy(False)
                if return_code == 0:
                    self.status_var.set("备份完成")
                    messagebox.showinfo("备份完成", "数据库备份已完成。")
                else:
                    self.status_var.set("备份失败")
                    messagebox.showerror("备份失败", "数据库备份失败，请查看执行日志。")

        self.root.after(100, self._process_queues)

    def _start_backup(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showwarning("任务正在执行", "当前备份任务还没有结束。")
            return

        args = self._collect_args()
        if args is None:
            return

        warning = (
            "即将开始数据库备份。\n\n"
            f"源: {args.source_url or args.source_key}\n"
            f"目标: {args.target_url or args.target_key}\n"
            f"方式: {args.method}\n\n"
            "请确认目标库信息正确。"
        )
        if not messagebox.askyesno("确认备份", warning, icon="warning"):
            return

        self._set_busy(True)
        self.worker_thread = threading.Thread(target=self._run_backup_worker, args=(args,), daemon=True)
        self.worker_thread.start()

    def _run_backup_worker(self, args: argparse.Namespace) -> None:
        writer = QueueWriter(self.log_queue)
        return_code = 1
        try:
            with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
                print("\n=== GUI backup started ===")
                return_code = run_backup(args)
                print(f"=== GUI backup finished, code={return_code} ===\n")
        except Exception as exc:
            self.log_queue.put(f"\nGUI backup failed: {exc}\n")
            return_code = 1
        finally:
            self.ui_queue.put(("done", return_code))

    def _on_close(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showwarning("任务正在执行", "备份任务正在执行，请等待完成后再关闭窗口。")
            return
        self.root.destroy()


def run_gui(initial_args: argparse.Namespace) -> int:
    if tk is None:
        print("当前 Python 环境不可用 Tkinter，已切换到命令行模式。")
        return run_backup(initial_args)

    root = tk.Tk()
    BackupDbApp(root, initial_args)
    root.mainloop()
    return 0


def main(argv: list[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    args = parse_args(raw_args)
    if args.gui or (not raw_args and not args.cli):
        return run_gui(args)
    return run_backup(args)


if __name__ == "__main__":
    raise SystemExit(main())
