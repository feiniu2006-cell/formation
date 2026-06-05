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
| `run_tests.py` / `test_formation_logic.py` | 统一测试入口和轻量逻辑/打包 smoke tests。 |

## 主要流程

1. 生成采样配置：`ui.RebateRulesDialog` -> `core.task_entrypoints` -> `rebate.rebate_config_runner` -> `rebate.rebate_config_logic` -> `rebate.rebate_config_storage`。
2. 执行采样：`ui.SingleSamplingDialog` 或全部采样按钮 -> `core.task_entrypoints` -> `sampling.direct_sampling_runner` -> `sampling.sampling_core`。
3. 生成 `group_weight`：`ui.GroupWeightRulesDialog` -> `group_weight.group_weight_runner` -> `group_weight.group_weight_builder` / `group_weight.group_weight_logic` -> `group_weight.group_weight_storage`。
4. 写通用配置：主界面按钮 -> `common.common_config_entrypoints` -> `common.common_config_runner` / `common.common_config_writer`。

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
| `dist_encrypted/db_config.json` | exe 同目录外部数据库配置，优先用于打包程序运行。 |
| `dist_encrypted/db_config.example.json` | 示例数据库配置。 |

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
