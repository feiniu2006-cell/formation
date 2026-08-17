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
2. 执行采样：`ui.SingleSamplingDialog`、全部采样/补充采样按钮 -> `core.task_entrypoints` -> `sampling.direct_sampling_runner` -> `sampling.sampling_core`。
3. 生成 `group_weight`：`ui.GroupWeightRulesDialog` -> `group_weight.group_weight_runner` -> `group_weight.group_weight_builder` / `group_weight.group_weight_logic` -> `group_weight.group_weight_storage`。
4. 写通用配置：主界面按钮 -> `common.common_config_entrypoints` -> `common.common_config_runner` / `common.common_config_writer`。

## 配置参数详细注释

代码默认参数主要集中在 `core/formation_defaults.py`，group_weight 模式定义和 rebate=0 反推默认模式在 `core/formation_modes.py`。主界面保存的房间配置会覆盖其中一部分运行参数；如果只改代码默认值，已经保存过的房间配置不会自动跟着变化，需要在 GUI 中重新保存或删除对应房间配置文件。

### 基础运行参数

| 参数 | 默认值 | 作用 | 调整影响 |
| --- | --- | --- | --- |
| `DEFAULT_RANDOM_SEED` | `108` | 直接采样时用于稳定随机抽样结果。 | 修改后，同一份采样配置可能抽到不同 id；不影响采样条件和 count 计算。 |
| `DEFAULT_SOURCE_DB` | `""` | GUI 首次打开时的默认源库。 | 只影响未保存配置时的初始显示。 |
| `DEFAULT_FINAL_DB` | `"DB1"` | GUI 首次打开时的默认目标库，也是 group_weight/采样写入默认目标库。 | 只影响未保存配置时的初始显示。 |
| `DEFAULT_CONFIG_DB` | `"MY"` | GUI 首次打开时的默认配置库，用于读取/写入 `rebate_count` 等采样配置表。 | 只影响未保存配置时的初始显示。 |
| `DEFAULT_GAME_TABLE_VENDOR` | `""` | GUI 首次打开时的厂商/表名前缀。 | 只影响未保存配置时的初始显示。 |
| `DEFAULT_GAME_TABLE_GAME_ID` | `""` | GUI 首次打开时的游戏编号/房间号。 | 只影响未保存配置时的初始显示。 |

### 采样配置生成参数

| 参数 | 默认值 | 作用 | 调整影响 |
| --- | --- | --- | --- |
| `DEFAULT_LOW_VOLUME_REBATE_COUNT_THRESHOLD` | `200000` | 低数据量探测阈值。生成采样配置前会按源表条件查询不同 `id` 数，低于该值的模式会提示可使用直接计数模式。 | 该值不是采样数量；调大后更多表会被识别为低数据量，调小后提示会减少。 |
| `DEFAULT_REBATE_CONFIG_REBATE_ZERO_COUNT_LIMIT` | `5000` | 生成采样配置时，`rebate=0` 的 `count` 上限。 | 限制 `rebate=0` 写入 `rebate_count` 的数量，避免 0 奖励数据过多。 |
| `DEFAULT_REBATE_CONFIG_POSITIVE_REBATE_COUNT_LIMIT` | `200` | 规则模式下，正数 rebate 的通用 `count` 上限。 | 防止普通正数 rebate 生成过大的 count；直接计数模式还会再套用直接计数阶梯。 |
| `DEFAULT_REBATE_CONFIG_MAX_REBATE` | `1099999` | 采样配置生成允许的最大 rebate。 | 高于该值的 rebate 不进入生成结果；需要覆盖更高 rebate 时先调大该值。 |
| `DEFAULT_REBATE_CONFIG_DIRECT_COUNT_MODES` | `set()` | 默认启用直接计数模式的局类型集合。 | 代码默认不开启；实际常通过 GUI 勾选并保存到房间配置。 |
| `DEFAULT_REBATE_CONFIG_DIRECT_COUNT_TIER_LIMITS` | 见下表 | 直接计数模式的分档 count 上限。 | 用于实现低 rebate 保留较大 count、高 rebate 压小 count。 |

直接计数阶梯默认值：

| rebate 范围 | count 上限 |
| --- | ---: |
| `rebate = 0` | `5000` |
| `1 <= rebate <= 999` | `200` |
| `1000 <= rebate <= 9999` | `100` |
| `10000 <= rebate <= 19999` | `50` |
| `20000 <= rebate <= 49999` | `20` |
| `50000 <= rebate <= 99999` | `10` |
| `100000 <= rebate <= 499999` | `5` |
| `500000 <= rebate <= 1099999` | `5` |

### 采样执行参数

| 参数 | 默认值 | 作用 | 调整影响 |
| --- | --- | --- | --- |
| `DEFAULT_SAMPLE_ID_FETCH_CHUNK_SIZE` | `500` | 直接采样读取完整行时，每批 `id IN (...)` 的 id 数。 | 调小会减少单次 SQL 和 DataFrame 大小，但批次变多；调大可能减少批次，但会增加单次查询压力。 |
| `DEFAULT_SAMPLING_DETAILED_LOG` | `False` | 采样详细日志开关。 | 关闭时只输出关键进度、异常和最终汇总；开启后额外输出查询、校验、读写耗时等明细。 |
| `DEFAULT_SAMPLING_USE_TEMP_DB` | `True` | 采样固定写入采样临时库中转。 | 该值保留用于兼容旧配置和内部上下文；GUI 不再提供关闭中转的开关，旧配置中的 `use_temp_db=false` 会被忽略。 |
| `DEFAULT_SAMPLING_TEMP_DB` | `"MY"` | 默认采样临时库。 | 建议配置为本地或更稳定的数据库；采样完成后会替换中转库正式表。 |
| `DEFAULT_SAMPLING_AUTO_SYNC_TO_TARGET` | `False` | 采样完成后是否自动镜像到目标库。 | GUI 中“采样完成后自动镜像到目标库”会覆盖并保存该值；关闭时目标库不变，需要手动点击“镜像到目标库”。 |

采样核心还有几个内部常量在 `sampling/sampling_core.py`：`SAMPLE_ID_RANDOM_RANGE_ATTEMPTS=8`、`SAMPLE_ID_RANDOM_RANGE_MAX_ATTEMPTS=20`、`SAMPLE_ID_RANDOM_RANGE_MAX_CANDIDATES_PER_QUERY=20000`、`SAMPLE_ROW_WRITE_CHUNK_SIZE=20`。这些用于控制随机范围候选查询和临时表写入批次，通常不建议改；临时表写入失败时会自动将批次降为 `5`、再降为 `1` 后重试。需要排查性能时优先打开“详细日志”观察瓶颈。

### group_weight 和购买局参数

| 参数 | 默认值 | 作用 | 调整影响 |
| --- | --- | --- | --- |
| `DEFAULT_WEIGHT_GROUP_IDS` | `10000-10004, ..., 9000-9004` | 初始启用尾号分组 `0/1/2/3/4`；运行时会按主界面当前列表重新生成。 | 尾号0固定保留；删除列表中的尾号1-4后，对应的整套 RTP `group_id` 会移除。 |
| `DEFAULT_EXTRA_WEIGHT_GROUPS` | 分组 `1/2/3/4` | 主界面可编辑、可删除的默认权重分组。 | 默认权重依次为特殊局 `200/300/400/500`、免费局 `100/150/200/250`；还可新增尾号 `5-9`。 |
| `DEFAULT_SPECIAL_WEIGHT_BY_LAST_DIGIT` | `{0: 100, 1: 200, 2: 300, 3: 400, 4: 500}` | 写通用配置时，特殊局触发权重按 `group_id` 个位分档。 | 分组0显示在列表固定首行，权重可编辑但不可删除；分组1-9使用可删除列表行。 |
| `DEFAULT_FREE_WEIGHT_BY_LAST_DIGIT` | `{0: 50, 1: 100, 2: 150, 3: 200, 4: 250}` | 写通用配置时，免费局触发权重按 `group_id` 个位分档。 | 分组0显示在列表固定首行，权重可编辑但不可删除；分组1-9使用可删除列表行。 |
| `DEFAULT_SPECIAL_GROUP_TARGET_RTP` | `6` | 特殊局存在 `rebate=0` 时，用于反推特殊局 0 权重的目标 RTP。 | 只影响特殊局独立反推；不存在 `rebate=0` 时不会反推。 |
| `DEFAULT_EX_GROUP_TARGET_RTPS` | `{}` | ex 独立目标 RTP 默认值，目前用于 ex特殊局。 | 通常通过 group_weight 权重配置弹窗输入并保存。 |
| `DEFAULT_BUY_GROUP_ENABLED` | `False` | 默认购买局开关。 | GUI 中“购买局配置”会覆盖并保存。 |
| `DEFAULT_EX_BUY_GROUP_ENABLED` | `False` | 默认 ex购买局开关。 | GUI 中“购买局配置”会覆盖并保存；ex购买局类型不是固定 98。 |
| `DEFAULT_EX_BUY_GROUP_GAME_TYPE` | `98` | 默认 ex购买局写入 `group_weight.game_type` 的类型。 | 只是默认值，可以在 GUI 手动改为其它 ex购买类型。 |
| `DEFAULT_EX_BUY_GROUP_SOURCE_SUFFIX` | `""` | ex购买局手动阵型后缀。 | 留空时优先按当前 ex购买类型读取 `game_room_game_type_config`；填写后仅覆盖 group_weight 生成。 |
| `DEFAULT_BUY_GROUP_GAME_TYPE` | `99` | 默认购买局写入 `group_weight.game_type` 的类型。 | 只是默认值，可以在 GUI 手动改为 91、92、93 等。 |
| `DEFAULT_BUY_GROUP_MULTIPLIER` | `75` | 购买局 RTP 展示/折算倍数。 | 用于购买局独立 RTP 计算和预览。 |
| `DEFAULT_BUY_GROUP_SOURCE_SUFFIX` | `"free_formation"` | 默认购买局读取的阵型表后缀。 | 例如指向 `{vendor}_{game_id}_free_formation`；主界面手动后缀优先于 DB 配置。 |
| `DEFAULT_EX_GROUP_MULTIPLIER` | `1.5` | ex 模式 RTP 折算倍数。 | ex普通、ex特殊、ex免费、ex购买局预览/生成会按该倍数折算最终 RTP。 |
| `DEFAULT_EX_SOURCE_SUFFIXES` | `{}` | 普通/特殊/免费及对应 ex 类型（1/2/3/6/7/8）的手动后缀覆盖默认值。 | 只服务 group_weight 生成，不影响采样配置生成和采样功能；购买局使用各自独立的后缀配置。 |
| `DEFAULT_EXTRA_BUY_GROUPS` | `[]` | 额外购买局默认列表。 | GUI 中新增购买局类型后会保存到房间配置。 |
| `DEFAULT_ZERO_REBATE_INFERENCE_MODES` | `('1', '2', '6', '7')` | 默认启用 rebate=0 反推的 group_weight 模式。 | 购买局和 ex购买局支持手动开启反推，但默认关闭；免费局和 ex免费局不反推。 |
| `DEFAULT_INDEPENDENT_RTP_MODES` | `('1', '6')` | 默认开启“独立计算RTP”的 group_weight 模式。 | 目前只支持普通局 `1` 和 ex普通局 `6`；新房间/重置默认时默认勾选。 |

### 规则字段说明

`REBATE_RULES` 是采样配置生成规则，常用字段如下：

| 字段 | 作用 |
| --- | --- |
| `rebate` | 精确匹配单个 rebate。 |
| `rebate_min` / `rebate_max` | 匹配 rebate 闭区间 `[rebate_min, rebate_max]`。 |
| `count` | 每个匹配 rebate 计划采样的 id 数，最终会受实际数据量和全局上限限制。 |
| `rebate_limit_min` / `rebate_limit_max` | 限制该规则范围内最多/至少选多少个 rebate。 |
| `smooth_buckets` | 将 rebate 区间分桶后分散选择，避免只集中在高频 rebate。 |
| `min_total` | 源表中该 rebate 的实际数据量低于该值时跳过。 |

group_weight 默认区间规则在 `core/formation_defaults.py` 中显式分为 `GROUP_WEIGHT_RULES_0` 到 `GROUP_WEIGHT_RULES_4` 五套完整配置，分别服务 group_id 尾号 `0/1/2/3/4`；当前初始内容相同，但可以直接在各自配置段修改，并且保存和编辑时彼此独立。`GROUP_WEIGHT_RULES` 保留为尾号 `0` 的兼容入口。区间语义为“当前 `rebate_min <= rebate < 下一条 rebate_min`”。新增尾号 `5-9` 没有专属规则时默认复制尾号 `0` 的当前规则。`weight=0` 的 rebate 会写入数据库，但不参与 RTP 权重计算。

group_weight 内部模式使用语义 key：普通购买局是 `buy`，ex购买局是 `ex_buy`。`99` 和 `98` 只是默认写入的 `game_type`，不是固定业务类型；旧配置文件里保存的 `group_weight_rules["99"]` 和 `group_weight_rules["98"]` 会在加载时自动映射到 `buy` 和 `ex_buy`。固定不可占用的内置类型只有 `1/2/3/6/7/8`。

购买局和 ex购买局的源表后缀优先级：

1. 主界面手动填写的后缀优先。
2. 未填写时，按当前配置的购买类型或 ex购买类型读取目标库 `game_room_game_type_config.source_suffix`。
3. 仍未取到时，购买局使用 `DEFAULT_BUY_GROUP_SOURCE_SUFFIX`，ex购买局回退到 ex免费局来源。

ex普通/ex特殊/ex免费手动后缀只服务 group_weight 生成，不影响采样配置生成和采样功能；例如把 ex普通局手动指向 `formation`，不会额外生成 ex普通局采样配置页。

rebate=0 反推必须同时满足两个条件：当前采样配置存在 `rebate=0`，并且在 group_weight 权重配置界面手动开启该模式的“rebate=0 反推”开关。普通局、特殊局、ex普通局、ex特殊局默认开启；购买局和 ex购买局支持但默认关闭；免费局和 ex免费局不反推。

普通局 `game_type=1` 和 ex普通局 `game_type=6` 额外支持“独立计算RTP”开关，配置会保存到 `group_weight_options.independent_rtp_modes`。默认开启；关闭时保持原逻辑：普通局目标会扣除特殊局/免费局触发贡献后反推；ex普通局目标会扣除 ex特殊局/ex免费局贡献后反推。开启后该页签不再和其它局一起计算 RTP，普通局直接以当前 RTP 组为目标，ex普通局以“当前 RTP 组 * ex倍数”为实际反推目标，最终显示 RTP 仍除以 ex倍数回到当前组目标。

group_weight 的尾号0固定显示在主界面“权重分组”列表首行，特殊/免费权重可编辑，但删除按钮禁用；尾号 `1/2/3/4` 默认显示在后续行，可修改权重或删除，也可新增尾号 `5-9`。当前列表会按每个 RTP 档位展开，例如保留尾号0、1、4时生成 `10000/10001/10004、9900/9901/9904……9000/9001/9004`。额外分组配置保存在 `group_weight_options.extra_weight_groups`，删除后不会在下次加载时自动恢复；旧版本 JSON 会自动迁移为列表结构。

group_weight 权重配置窗口提供“保存配置”和“确认并开始”两个操作。“保存配置”会校验并立即保存当前各分组的区间权重、反推开关和 RTP 选项，但保持窗口打开且不生成数据；“确认并开始”会先执行相同的保存，再关闭窗口并开始生成任务。固定类型的分组区间规则保存在 `group_weight_group_rules`；额外购买局按类型保存在对应 `extra_buy_groups[].group_rules`。每个分组尾号都是独立项，修改分组 0 不会再同步修改分组 1/2/3；新增分组尚未单独修改时会复制尾号 `0` 的当前规则，之后可分别修改并保存。

保存配置时，`group_weight_rules` 以及每个分组下的 `group_weight_group_rules` 只写入 group_weight 配置窗口实际显示并配置的类型。例如窗口中只有普通局 `game_type=1`，JSON 中这些权重规则只保存键 `"1"`；采样使用的 `rebate_rules` 不受该过滤影响。

兼容旧配置时，`group_weight_rules` 或 `group_weight_group_rules` 中值为空数组的类型按“未配置”处理，不会因为不存在的局类型弹出“至少需要一条权重规则”；运行时会使用代码默认规则补齐，后续保存时按当前窗口实际类型清理这些空项。

group_weight 权重柱状图右侧按 `0倍`、`1倍以下`、`1~10倍`、`10~20倍`、`20~50倍`、`50~80倍`、`80~100倍`、`100~500倍`、`500倍以上` 展示最终权重占比。占比分母为当前页签全部实际 rebate 的最终权重总和，`rebate=0` 使用反推后的最终权重；“不显示 rebate=0”仅影响柱状图绘制，不改变区间占比。

## 采样配置生成

采样配置表通常是 `rebate_count`、`rebate_special_count`、`rebate_free_count` 等表，核心字段为 `rebate` 和 `count`。

- 规则模式：根据 rebate 规则、源表统计量和全局 count 上限生成配置。
- 直接计数模式：先按源表中每个 rebate 的实际数量生成 `count`，再应用“直接计数阶梯”限制，使低 rebate 保留较大的 count，高 rebate 自动压小 count。
- 直接计数阶梯配置会随 GUI 设置导入导出，也会被 CLI 设置加载逻辑恢复。

## 直接采样逻辑

直接采样的核心语义不能变：**采样条件只用于挑选符合 rebate 的 `id`；真正读取写入时只按 `id IN (...)` 取完整 id 组数据，不再叠加 `rebate`、`game_end` 或 `is_end` 条件。**

执行顺序：

1. 从采样配置表读取 `rebate/count`。
2. 在采样临时库创建采样临时表；采样始终先写入中转库，不直接写目标库。
3. 逐个 rebate 处理，按 `rebate = {target_rebate}` 和结束字段条件挑选候选 `id`。
4. 优先使用稀疏探测、随机 id 范围查询和候选抽样，候选不足时回退到全量 `DISTINCT id` 查询。
5. 只对本次已采样的 id 做结束字段完整性校验，确认这些 id 下 `game_end=1` 或 `is_end=1` 的行数恰好为 1；不再对整张源表做全表 `GROUP BY id` 校验。
6. 对选中的 id，读取 SQL 只保留 `WHERE id IN (...)`，确保一局或一组 formation 数据被完整写入。
7. 分批读取和写入临时表，避免过长 `IN` 查询和过大的 DataFrame。
8. 采样完成后校验临时表行数。
9. 用临时表整体替换中转库正式表；此时目标库默认保持不变。
10. 如果勾选“采样完成后自动镜像到目标库”，采样成功后会把本次成功采样的中转库正式表镜像到目标库；全部采样只自动镜像本次返回成功的局类型，单独采样只镜像当前局类型。
11. 未开启自动镜像时，需要在主界面采样按钮区点击“镜像到目标库”，确认后会优先使用 `mysqldump`/`mysql` 将中转库正式表导出并导入目标库临时表，导出和导入失败都会最多重试 5 次，校验行数后再整体替换目标库正式表。镜像功能需要本机能调用 MySQL Client 工具。

### 补充采样逻辑

补充采样用于在目标库已有正式表的基础上新增采样数据，但采样期间仍然只写入采样临时库，目标库不会被直接修改。

1. 预检查会额外检查目标库旧正式表；普通采样未开启自动镜像时不会检查目标库。
2. 如果目标库旧正式表存在，会先校验字段名和基础类型是否与源表一致；`int(10)/int(11)`、`varchar(255)/varchar(500)` 这类长度差异不会阻止补充采样。
3. 校验通过后，按目标库旧正式表结构创建采样临时库临时表，并使用 `mysqldump`/`mysql` 将旧正式表复制进去。
4. 旧数据复制完成后保留全部原始 `id`，不会对旧数据重新编号。
5. 新采样数据写入前会按采样 `id` 整组改写，从旧数据 `MAX(id) + 1` 开始连续分配，确保不会与旧数据冲突。
6. 补充采样完成后，采样临时库正式表就是“原始旧数据 + 新采样数据”的完整表；是否镜像到目标库仍由“采样完成后自动镜像到目标库”或手动“镜像到目标库”控制。
7. 如果目标库旧正式表不存在，补充采样会按新表处理，新采样数据从 `id=1` 开始分配。

生成采样配置统计 rebate 分布时，会按源表结构选择计数方式：源表存在 `game_end` 或 `is_end` 字段时使用 `COUNT(DISTINCT id)`，用于多行组成同一局的数据；源表不存在这两个字段时，按 `id` 唯一表处理，使用 `COUNT(*)` 降低大表统计开销。

如果需要修改 `sampling/sampling_core.py`，必须保留第 6 点的完整 id 组读取语义；相关回归测试为 `SamplingCoreWriteTests.test_read_sample_rows_by_ids_reads_complete_id_groups`。已采样 id 局部完整性校验的回归测试为 `SamplingCoreWriteTests.test_sampled_id_end_field_validation_checks_only_selected_ids`。

## 采样日志开关

主界面采样按钮区提供 `详细日志` 复选框，默认关闭。该开关只影响日志输出，不改变采样配置、采样条件、候选 id 选择、完整 id 组读取或写入结果。

- 关闭时：保留任务配置、rebate 进度、候选不足 fallback 提示、异常信息、最终性能汇总和任务摘要，适合正常运行。
- 开启时：额外输出采样条件、每个 rebate 的完成摘要、稀疏探测、ID 范围、候选汇总、已采样 ID 校验通过、完整行读取耗时、临时表写入准备/完成、随机 id 范围每次尝试、临时表每批写入开始/完成等明细，适合排查某个 rebate 卡住或写入慢的问题。
- 生成采样配置时也复用该开关。关闭时保留匹配数据量、入选采样结果表、写入预览、截断汇总和异常；开启时额外输出 SQL 过滤条件、统计/构建/写入耗时、未匹配规则跳过、`min_total` 跳过、`rebate_limit_max` 跳过、逐条 count/rebate 上限截断等明细。
- GUI 任务头会按任务类型输出摘要：生成采样配置只输出采样规则和直接计数阶梯，不输出 group_weight 区间、购买局或 ex 配置；数据库连接成功/尝试信息默认隐藏，开启详细日志后显示，失败和重试信息始终显示。
- 开关会随房间配置保存到 `sampling_options.detailed_log`，旧配置文件没有该字段时按关闭处理；CLI 加载设置时也会恢复该开关。

## 打包和测试

常用命令：

```powershell
py -3 formation_tool\run_tests.py
py -3 formation_tool\build_formation_exe.py --check
py -3 formation_tool\build_formation_exe.py --check --test
py -3 formation_tool\build_formation_exe.py --list-modules
```

真正打包：

```powershell
py -3 formation_tool\build_formation_exe.py
```

清理打包临时文件：

```powershell
py -3 formation_tool\build_formation_exe.py --clean
```

`build_formation_exe.py` 会递归发现生产模块，因此新增业务模块后通常不需要手工维护加密模块清单；`--list-modules` 可以查看本次会加密进 exe 的模块。`--check` 会检查依赖模块、加密模块清单、源码编译、内置 `db_config.py` 和可选外部 `db_config.json`。脚本已显式包含 `tkinter.filedialog`、`tkinter.messagebox`、`tkinter.scrolledtext`、`tkinter.ttk` 等 hiddenimports，避免打包后 GUI 弹窗导入失败。

## 配置文件

| 路径 | 作用 |
| --- | --- |
| `formation_tool_settings.json` | 上次选择配置。 |
| `formation_tool_settings/` | 按厂商和游戏编号保存的房间配置，包括采样中转库、详细日志开关、采样规则、group_weight 规则、购买局配置和直接计数阶梯。 |
| `formation_sampling_tasks/` | 直接采样任务状态，记录临时表和已完成 rebate，用于失败后恢复。 |
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
