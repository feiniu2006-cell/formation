# Slot 问题数据查询/清理工具

这是独立工具，不集成到 `formation_tool`，不读取或保存房间配置 JSON。数据库连接只复用上级目录的 `db_config.py`。

## 功能

- 手动选择数据库、厂商、游戏编号、表后缀，组合成表名，例如 `pg_87_free_formation`。
- 手动输入 Scatter 字段和 Wild 字段，字段内容按 `1,2,3` 这种逗号字符串解析。
- Scatter/Wild 字段中不存在于当前表的字段会自动忽略，并在日志中提示；如果某类字段全都不存在，该类规则不会命中。
- 内置符号规则：
  - `Scatter = 1`
  - `Wild = 0`
- 查询命中问题条件的数据，并展示问题行数、问题 id 数、预计删除行数和样例。
- 删除时默认删除命中问题 `id` 的整组数据，不只删命中行。
- 删除前可自动备份命中 id 组到同库备份表。

## 当前规则

每一行会统计：

```text
scatter_count = Scatter字段中数值 1 的总数量
wild_count    = Wild字段中数值 0 的总数量
```

启用的任意规则命中后，该行所属 `id` 会被视为问题 id：

```text
game_id = 0 且 scatter_count > 阈值
game_id > 0 且 scatter_count > 阈值
sort = 0 且 scatter_count > 阈值
sort > 0 且 scatter_count > 阈值
表不存在 game_id 字段时，scatter_count > 无game_id阈值
wild_count > 阈值
game_id > 最大值
sort > 最大值
```

如果表不存在 `game_id` 字段，依赖 `game_id` 的规则会自动忽略；“无game_id时 Scatter >”规则会用于这类表。
如果表不存在 `sort` 字段，依赖 `sort` 的 Scatter 规则和 `sort > 最大值` 规则会自动忽略。

删除时执行的是：

```sql
DELETE FROM 表名 WHERE id IN (问题id列表)
```

## 使用

双击：

```text
run_bad_data_cleaner.bat
```

或在当前目录运行：

```powershell
py .\bad_data_cleaner.py
```

示例配置：

```text
数据库：DB1
厂商：pg
游戏编号：87
表后缀：free_formation
Scatter字段：orl,torl
Wild字段：orl,torl
game_id=0 时 Scatter > 4
game_id>0 时 Scatter > 3
sort=0 时 Scatter > 4
sort>0 时 Scatter > 3
无game_id时 Scatter > 3
Wild > 6
game_id > 20
sort > 10
```

先点击“查询问题数据”，确认数量和样例后，再点击“删除问题id全部数据”。
