# 数据库对比工具

用于对比两个 MySQL 数据库内指定表是否相同。工具只读数据库，不会修改任何数据。

对比结束后会覆盖输出 `reports/db_compare_result.json`，按“一致”和“不一致”归类；不一致的表会继续按“表结构不同”“数据量不同”“ID不同”“数据内容不同”等类型分组。

输出示例：

```json
{
  "summary": {
    "total": 3,
    "same": 1,
    "different": 2
  },
  "一致": ["table_a"],
  "不一致": {
    "数据量不同": ["table_b：数据量不同（源表 10 行，目标表 9 行；未找到主键或 id 字段，无法判断是否新增）"],
    "目标表后面新增数据": ["table_c：目标表后面新增数据（新增 5 行，前 100 个ID相同）"],
    "目标表前面新增数据": ["table_d：目标表前面新增数据（新增 5 行，后 100 个ID相同）"],
    "ID不同": ["table_e：ID不同（按 id 判断）"]
  }
}
```

## 使用方式

双击或直接运行脚本会打开图形界面：

```powershell
py -3 db_compare.py
```

命令行模式示例：

```powershell
py -3 db_compare.py --cli --source-key DB1 --target-key MY --tables game_room_base_config
py -3 db_compare.py --cli --source-key DB1 --target-key MY --tables source_table:target_table,another_table
py -3 db_compare.py --cli --source-key DB1 --target-key MY --tables game_room_base_config --full-compare
```

表名支持逗号分隔。`source_table:target_table` 表示左右库表名不同；只写一个表名时默认两边同名。

图形界面的表筛选支持多个关键词，使用空格、逗号或分号分隔；表名必须同时包含所有关键词才会显示。

默认使用快速对比，只检查行数和 ID。需要进一步检查字段值内容时，图形界面取消勾选“快速对比”，或命令行增加 `--full-compare`。

图形界面对比过程中可以点击“停止”中断任务；停止后仍会覆盖输出 `reports/db_compare_result.json`，内容标记为“已停止”。

不一致分类是互斥含义：
- “目标表后面新增数据”/“源表后面新增数据”：行数不同，但按 ID 升序时较短部分的前半段完全相同。
- “目标表前面新增数据”/“源表前面新增数据”：行数不同，但按 ID 升序时较短部分的后半段完全相同。
- “ID不同”：能按主键或 `id` 判断，并且 ID 不一致。
- “数据量不同”：没有主键或 `id`，只能确认行数不同，无法判断是否属于新增。

## 配置来源

优先读取本目录下的 `db_config.example.json`。如果不存在，会读取项目根目录的 `db_config.py` 中的 `DATABASE_CONFIGS`。

JSON 格式示例：

```json
{
  "DATABASE_CONFIGS": {
    "DB1": {
      "host": "127.0.0.1",
      "port": 3306,
      "database": "source_db",
      "user": "root",
      "password": "password"
    },
    "DB2": {
      "host": "127.0.0.1",
      "port": 3306,
      "database": "target_db",
      "user": "root",
      "password": "password"
    }
  }
}
```
