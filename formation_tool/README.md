# 阵型处理工具说明

主入口仍是 `process_formation_slots_way_combined.py`。其余模块已按职责拆到子文件夹，方便维护、测试和打包。

## 目录结构

| 路径 | 作用 |
| --- | --- |
| `process_formation_slots_way_combined.py` | 主入口，负责加载配置、组装运行时依赖、启动 GUI/CLI，并保留兼容包装函数。 |
| `core/` | 运行时状态、默认规则、模式定义、规则校验、设置文件逻辑、上下文同步、任务入口和 CLI 设置加载。 |
| `db/` | 数据库配置校验、外部 `db_config.json` 加载、连接/重试、表操作、源表检测、表操作入口和运行时数据库访问适配。 |
| `sampling/` | 直接采样执行流程、采样核心逻辑和采样入口调用适配。 |
| `rebate/` | `rebate_count` 采样配置生成、规则计算、配置表写入和入口依赖组装。 |
| `group_weight/` | RTP/权重计算、`group_weight` 预览、生成流程和写表逻辑。 |
| `common/` | 当前游戏通用表配置，包括特殊局触发权重、免费局触发权重和下注档位配置。 |
| `ui/` | Tkinter 主窗口、弹窗、购买局配置组件、外部配置提示、规则表格组件、设置加载和后台任务管理。 |
| `utils/` | SQL、文件、日志、取消控制等通用工具。 |
| `cli/` | 旧版命令行菜单入口。 |
| `build_formation_exe.py` | 加密打包脚本，支持打包前自检和可选测试。 |
| `run_tests.py` / `test_*.py` | 统一测试入口和轻量逻辑/打包 smoke tests；`run_tests.py` 会发现并运行全部 `test_*.py`。 |

## 主要流程

1. 生成采样配置：`ui.RebateRulesDialog` -> `core.task_entrypoints` -> `rebate.rebate_config_runner` -> `rebate.rebate_config_logic` -> `rebate.rebate_config_storage`。
2. 执行采样：`ui.SingleSamplingDialog` 或全部采样按钮 -> `core.task_entrypoints` -> `sampling.direct_sampling_runner` -> `sampling.sampling_core`。
3. 生成 `group_weight`：`ui.GroupWeightRulesDialog` -> `group_weight.group_weight_runner` -> `group_weight.group_weight_builder` / `group_weight.group_weight_logic` -> `group_weight.group_weight_storage`。
4. 写通用配置：主界面按钮 -> `common.common_config_entrypoints` -> `common.common_config_runner` / `common.common_config_writer`。

## 采样配置生成

采样配置表通常是 `rebate_count`、`rebate_special_count`、`rebate_free_count` 等表，核心字段为 `rebate` 和 `count`。

- 规则模式：根据 rebate 规则、源表统计量和全局 count 上限生成配置。
- 直接计数模式：先按源表中每个 rebate 的实际数量生成 `count`，再应用“直接计数阶梯”限制，使低 rebate 保留较大的 count，高 rebate 自动压小 count。
- 直接计数阶梯配置会随 GUI 设置导入导出，也会被 CLI 设置加载逻辑恢复。

## 直接采样逻辑

直接采样的核心语义不能变：**采样条件只用于挑选符合 rebate 的 `id`；真正读取写入时只按 `id IN (...)` 取完整 id 组数据，不再叠加 `rebate`、`game_end` 或 `is_end` 条件。**

执行顺序：

1. 从采样配置表读取 `rebate/count`。
2. 为目标表创建临时表；追加模式会先把旧目标表复制到临时表。
3. 逐个 rebate 处理，按 `rebate = {target_rebate}` 和结束字段条件挑选候选 `id`。
4. 优先使用稀疏探测、随机 id 范围查询和候选抽样，候选不足时回退到全量 `DISTINCT id` 查询。
5. 对选中的 id，读取 SQL 只保留 `WHERE id IN (...)`，确保一局或一组 formation 数据被完整写入。
6. 分批读取和写入临时表，避免过长 `IN` 查询和过大的 DataFrame。
7. 追加模式下处理新旧数据 id 冲突，必要时为新采样数据分配新 id。
8. 采样完成后校验临时表行数，再用临时表整体替换正式目标表。

如果需要修改 `sampling/sampling_core.py`，必须保留第 5 点的完整 id 组读取语义；相关回归测试为 `SamplingCoreWriteTests.test_read_sample_rows_by_ids_reads_complete_id_groups`。

## 打包和测试

常用命令：

```powershell
py -3 formation_tool\run_tests.py
py -3 formation_tool\build_formation_exe.py --check
py -3 formation_tool\build_formation_exe.py --check --test
```

真正打包：

```powershell
py -3 formation_tool\build_formation_exe.py
```

清理打包临时文件：

```powershell
py -3 formation_tool\build_formation_exe.py --clean
```

`build_formation_exe.py` 会递归发现生产模块，因此新增业务模块后通常不需要手工维护加密模块清单；但仍建议执行 `--check` 确认模块、编译和 `db_config.json` 自检都通过。

## 配置文件

| 路径 | 作用 |
| --- | --- |
| `formation_tool_settings.json` | 上次选择配置。 |
| `formation_tool_settings/` | 按厂商和游戏编号保存的房间配置。 |
| `formation_sampling_tasks/` | 直接采样任务状态，记录临时表、已完成 rebate 和追加模式 id 映射，用于失败后恢复。 |
| `dist_encrypted/db_config.json` | exe 同目录外部数据库配置，优先用于打包程序运行。 |
| `dist_encrypted/db_config.example.json` | 示例数据库配置。 |

源码运行时，上述设置和任务状态默认保存在 `formation_tool/` 下；打包运行时默认保存在 exe 所在目录。可通过环境变量 `FORMATION_TOOL_SETTINGS_DIR` 覆盖保存目录。

## 维护建议

- 纯计算逻辑优先放到 `rebate/` 或 `group_weight/` 的 logic 模块，方便测试。
- 数据库写入流程优先放到 runner/storage 模块，主脚本只做依赖组装。
- 数据库通用入口优先放到 `db/db_entrypoints.py`，避免主脚本直接拼接表操作细节。
- `rebate` 和 `sampling` 的运行入口分别集中到 `rebate/rebate_config_entrypoints.py`、`sampling/sampling_entrypoints.py`。
- 新增跨模块依赖时优先使用 dataclass deps，少用临时 `SimpleNamespace`，方便测试和打包前检查。
- 业务模块输出日志时使用 `formation_tool.utils.log_utils.emit` 或 `print = log_utils.emit`，GUI 和命令行会走同一条日志链路。
- UI 窗口尺寸统一放到 `ui/ui_layout_defaults.py`，新增弹窗优先复用 `WindowLayout` 和 `apply_window_layout`。
- 主界面购买局配置集中在 `ui/buy_group_ui.py`；外部 `db_config.json` 状态提示集中在 `ui/external_config_status.py`。
- GUI 只负责展示、输入和任务触发，避免直接写数据库。
- 修改打包脚本或模块目录后，至少运行 `run_tests.py` 和 `build_formation_exe.py --check --test`。
