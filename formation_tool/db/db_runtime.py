"""Database connection and retry helpers for the formation tool."""

import contextlib

import mysql.connector
from sqlalchemy import create_engine
from sqlalchemy.engine import URL


def rollback_safely(conn, label="数据库事务"):
    """尽量回滚，不让清理异常遮住原始错误。"""
    if not conn:
        return
    with contextlib.suppress(Exception):
        conn.rollback()


def close_safely(conn):
    """尽量关闭连接。"""
    if conn:
        with contextlib.suppress(Exception):
            conn.close()


def get_engine(db_config):
    """创建 SQLAlchemy 引擎。"""
    use_pure = str(db_config.get('use_pure', True))
    url = URL.create(
        'mysql+mysqlconnector',
        username=db_config['user'],
        password=db_config['password'],
        host=db_config['host'],
        port=int(db_config['port']),
        database=db_config['database'],
        query={'use_pure': use_pure},
    )
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_recycle=1800,
    )


def connect_to_db(db_config, *, max_retries, retry_delay, check_cancelled, sleep_func):
    """连接到数据库，支持重试机制。"""
    connect_config = dict(db_config)
    connect_config.setdefault('use_pure', True)
    for attempt in range(max_retries):
        check_cancelled()
        try:
            print(f"尝试连接数据库 {db_config['host']}:{db_config['port']} (第{attempt + 1}次)...")
            conn = mysql.connector.connect(**connect_config)
            print(f"数据库连接成功: {db_config['host']}:{db_config['port']}")
            return conn
        except Exception as e:
            print(f"数据库连接失败 (第{attempt + 1}次): {e}")
            if attempt < max_retries - 1:
                print(f"等待{retry_delay}秒后重试...")
                sleep_func(retry_delay)
            else:
                print("达到最大重试次数，连接失败")
                return None


def get_db_config_by_name(db_name, database_configs):
    """根据数据库名称获取数据库配置。"""
    if db_name in database_configs:
        return database_configs[db_name]
    raise ValueError(f"未知的数据库名称: {db_name}，可用数据库: {list(database_configs.keys())}")


def ensure_database_connection(
    conn,
    db_name,
    *,
    connect_to_database,
    max_retries,
    retry_delay,
    label='数据库',
):
    """确保 mysql.connector 连接可用；连接超时后自动重连。"""
    try:
        if conn:
            conn.ping(reconnect=True, attempts=max_retries, delay=retry_delay)
            return conn
    except Exception as e:
        print(f"{label}连接已失效，正在重新连接 {db_name}: {e}")
        close_safely(conn)

    new_conn = connect_to_database(db_name)
    if not new_conn:
        raise RuntimeError(f"无法重新连接 {label}: {db_name}")
    return new_conn


def refresh_connection_read_view(conn, db_name, *, ensure_connection, rollback, label='数据库'):
    """结束当前事务快照，确保该连接能看到其它连接刚提交的数据。"""
    conn = ensure_connection(conn, db_name, label)
    try:
        conn.commit()
    except Exception:
        rollback(conn)
        raise
    return conn


def sql_with_retry(fn, *, label, max_retries, retry_delay, check_cancelled, sleep_func):
    """对 SQLAlchemy / pandas SQL 操作进行重试。"""
    for attempt in range(1, max_retries + 1):
        check_cancelled()
        try:
            return fn()
        except Exception as e:
            print(f"{label}失败 (第{attempt}次): {e}")
            if attempt < max_retries:
                print(f"等待{retry_delay}秒后重试...")
                sleep_func(retry_delay)
            else:
                raise


def check_connection(conn):
    """检查数据库连接是否有效。"""
    try:
        if conn and conn.is_connected():
            return True
        return False
    except Exception:
        return False

