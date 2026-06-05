"""Runtime database access adapters used by the main script."""

from types import SimpleNamespace


def build_database_access_deps(
    *,
    get_database_configs,
    get_engine,
    get_db_config_by_name,
    connect_to_db,
    connect_to_database,
    close_safely,
):
    return SimpleNamespace(
        get_database_configs=get_database_configs,
        get_engine=get_engine,
        get_db_config_by_name=get_db_config_by_name,
        connect_to_db=connect_to_db,
        connect_to_database=connect_to_database,
        close_safely=close_safely,
    )


def get_table_database(table_key, table_config):
    return table_config[table_key]['database']


def get_table_name(table_key, table_config):
    return table_config[table_key]['name']


def get_engine_by_table(table_key, table_config, *, deps):
    db_name = get_table_database(table_key, table_config)
    db_config = deps.get_db_config_by_name(db_name)
    return deps.get_engine(db_config)


def connect_by_table(table_key, table_config, *, deps):
    db_name = get_table_database(table_key, table_config)
    db_config = deps.get_db_config_by_name(db_name)
    return deps.connect_to_db(db_config)


def connect_to_database(db_name, *, deps):
    db_config = deps.get_db_config_by_name(db_name)
    return deps.connect_to_db(db_config)


def list_database_configs(*, deps):
    print("当前数据库配置：")
    for db_name, db_config in deps.get_database_configs().items():
        print(f"  {db_name}: {db_config['host']}:{db_config['port']}/{db_config['database']}")


def test_database_connections(table_config, *, deps):
    print("\n=== 测试数据库连接 ===")
    used_db_names = sorted({
        table_info['database']
        for table_info in table_config.values()
        if isinstance(table_info, dict) and 'database' in table_info
    })
    if not used_db_names:
        print("未发现可用数据库，跳过测试。")
        return
    print(f"仅测试使用到的数据库：{used_db_names}")
    for db_name in used_db_names:
        print(f"\n测试 {db_name} 连接...")
        conn = deps.connect_to_database(db_name)
        if conn:
            print(f"✓ {db_name} 连接成功")
            deps.close_safely(conn)
        else:
            print(f"✗ {db_name} 连接失败")
