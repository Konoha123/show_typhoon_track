# AGENTS.md — AI 编程 Agent 工作纪律与指南

本文件约束 AI 编程 Agent 在本项目上的工作方式。与本文件冲突的临时指令，以用户当次明确指示为准；其余情况一律遵守本文件。

---

## 1. 项目上下文

- **项目目的**：将 Google Weather Lab / WeatherNext Cyclones (WNC) 热带气旋预报模型导出的 CSV 结果导入本系统，在交互式网页中可视化预报轨迹，并叠加基础交互功能；必要时采用前后端分离方案。
- **核心数据流**：用户在页面上导入原始 CSV → 触发后端解析 → 前端可视化与交互。
- **`demo_src/` 的地位**：演示与参考代码（命令行读取、字段识别、轨迹选取），不是生产代码。可以复用其中的解析逻辑与字段映射经验，但不要在其上直接堆叠业务功能；正式代码应在项目根目录建立独立的包结构。
- **演示目录中的数据纪律**：`sample_synthetic_*.csv` 为人工合成测试数据；`FNV3P2_2026_10_14T00_00_paired (1).csv` 为真实公开预报导出文件。两者绝不可混淆，不得用合成数据冒充真实数据做验收。

## 2. 环境与依赖管理

- **Conda 环境名**：`show-typhoon-track`（Python 3.13；已安装 pandas 与开发验证工具，实际版本见 `requirements*.txt`）。
- 每次工作前先激活并核对环境：

  ```bash
  conda activate show-typhoon-track
  python --version
  python -c "import sys; print(sys.executable)"
  ```

- 当前终端解释器与目标环境不一致时，先定位正确环境，不得通过修改系统环境掩盖问题。
- 依赖安装一律在 `show-typhoon-track` 环境内执行；目前已知的数据处理依赖为 `pandas>=2.0`（演示代码要求 Python 3.10+，本项目环境满足）。
- 依赖声明已落地，分为两份，新增依赖后必须回填对应文件，不得只装不记：
  - `requirements.txt`：运行时依赖（当前仅 `pandas>=2.0`）；
  - `requirements-dev.txt`：开发与验证依赖（引用运行时文件，额外含 ruff / pyright / deptry / import-linter / pytest）。

## 3. 验证与测试纪律（强制）

- 所有 Python 代码的修改、维护、调试，**必须参照项目根目录的《Python 项目 L0–L6 分层验证规范.md》执行分层验证**：

  | 层级 | 验证名称 | 核心工具 |
  |---|---|---|
  | L0 | 语法与字节码编译检查 | py_compile / compileall |
  | L1 | 静态代码缺陷检查 | Ruff |
  | L2 | 静态类型与接口检查 | Pyright |
  | L3 | 依赖完整性与架构检查 | deptry / pip check / Import Linter |
  | L4 | 模块导入与启动初始化检查 | Python / 导入冒烟测试 |
  | L5 | 功能与集成测试 | pytest |
  | L6 | 部署环境端到端验证 | 项目实际运行命令及验收脚本 |

- **核心纪律：未经实际执行的验证，不得声称已经通过。**
- 验证范围按“变更文件集合 → 影响模块集合 → 完整源码集合”梯度确定，覆盖本次修改可能影响的整个依赖链。
- 测试基线（pytest，`testpaths = tests demo_src`，共 245 项）：`tests/` 下 core 单测（含 M9 洋区码表与前缀直映）、CLI 行为一致性对照、service/api 集成（含 /static no-cache 头回归、M9 places basin 校验与 tracks `storm_basin`）与 UI E2E（Playwright 无头浏览器，未安装环境自动跳过；首次使用需 `python -m playwright install chromium`；含 M7f 反经线绘制形状比回归 2 项、M8 终生峰值栏交互 2 项与 M5d-R12 时效滑块解耦 3 项）、WNV3 配对真实数据交叉验证（缺文件自动跳过，含 M6 影响概率、M7 核心强风区与 M8 终生峰值独立复算抽核）+ `demo_src` 原有 15 项。改动解析相关逻辑后必须全量回跑 `python -m pytest -q`；demo_src 亦可按原方式单独回跑：

  ```bash
  cd demo_src && python -m unittest -v test_wnc_csv_demo.py test_wnc_csv_real.py
  ```

## 4. 数据处理纪律

以下条目源自真实数据验收（见 `demo_src/真实CSV验收记录_20261014.md`）中的教训，违反会造成静默的数据错误：

1. 读取 CSV 一律使用 `pd.read_csv(..., dtype="string")`，防止气旋编号等标识符损坏；数字与 UTC 时间再有选择地解析。真实文件可能以多行 `#` 注释开头，需 `comment="#"` 跳过。
2. 不假定表头与官方 `weathernext/cyclones/constants.py` 完全一致；首次接触任何新文件先 `--inspect` / 打印列名核实。
3. 经度可能为 0–360° 约定，不可未经转换直接与 −180–180° 系统比较。
4. 风速单位（kt）、平均口径（1 分钟/10 分钟）、气压单位以数据提供者说明为准，不自动猜测或换算。
5. 缺失值保持缺失，不臆测为 0；不随意去重同一轨迹中重复出现的有效时次，应先调查原因。
6. 不跨气旋 / 集合成员 / 起报时次混合统计；集合均值不是对成员风速或坐标的任意平均，应直接读取 Google 提供的对应产品。
7. `--at-lead-hours` 之类选取只匹配实际存在的时效，不插值、不外推。
8. 同一 CSV 可能同时含预报与观测参考轨迹；无清晰标签时先人工核实，不得将观测当作预报。

## 5. 代码风格与结构约定

- 正式包结构（M1/M1b/M2 已落地）：
  - 包名 `typhoon_track`，分层契约 `cli/api → service → core`（`.importlinter` 强制）；
  - `typhoon_track/core/`：解析核心（aliases / io / normalize / selection / summary / geo / ensemble / impact / basin），纯函数、无打印，错误文案与演示脚本保持一致以支撑对照验证；`core/basin.py` 为洋区码表与前缀映射（M9：地点侧 BASIN_ORDER 固定 8 码 = IBTrACS 七分 + CP 扩展、BASIN_NAMES 显示名含气旋侧粗码 SH、TRACK_ID_PREFIX_TO_BASIN 前缀直映不合并消歧、basin_from_track_id 未识别返回 None、basin_label「代码 中文名」格式，口径见 `docs/里程碑基线.md` M9）；`core/ensemble.py` 为集合概率统计（逐时次均值/球面均值位置/概率半径/强度分布，口径见 `docs/M5口径验证记录_20261016.md`；含 `peak_profile` 成员终生峰值[M8]：wind max/pressure min 独立极值、上中位值/平均、消散有限峰值与全缺哨兵剔除，口径见 `docs/里程碑基线.md` M8）；`core/impact.py` 为影响概率与最近接近（风圈象限判定/三级风速成员命中/核心强风区 距离≤RMW 全向圆判定[M7d，RMW 缺失或≤0 不命中]/mean 口径最近接近，缺风圈列显式拒绝不回退，口径见 `docs/里程碑基线.md` M6/M7）；
  - `typhoon_track/service/`：编排层（datasets：uploads 目录存储+LRU 解析缓存；queries：筛选与行级载荷、经度双约定；places：根目录 `places/places.csv` 热读取预存地点，坏行跳过+warnings，M9 起 basin 洋区列必填——缺失/非法码跳行、整表缺列单条汇总 warning）；
  - `typhoon_track/api/`：FastAPI 路由与应用工厂（`uvicorn typhoon_track.api.app:app`）；CSV 双导入入口 `kind=forecast|observation`；轨迹查询（tracks 响应含 `storm_basin`[M9：track_id 前缀直映，未筛选/未识别为 null]）与集合统计聚合端点（`ensemble-stats`，仅限预报、拒绝跨气旋/起报混合）；影响统计端点（`impact-stats`，仅限预报、缺风圈列显式 400 不回退、返回三级风速命中概率+核心强风区（距离≤RMW，M7d）+ mean 口径最近接近）与预存地点端点（`GET /api/places`，热读取，M9 起逐地点携带 basin 洋区码）；终生峰值统计端点（`peak-stats`，M8：仅限预报、整条轨迹 wind max/pressure min 独立极值、上中位值+平均、哨兵剔除）；接口输入输出契约由 `api/schemas.py` 的 pydantic 模型定义（DatasetMeta / TrackFilters / TrackPoint / TracksResponse / EnsembleLeadStats / EnsembleStatsResponse / ImpactThresholdStats / CoreWindStats / ClosestApproach / ImpactStatsResponse / PeakMetricStats / MemberPeak / PeakStatsResponse / Place / PlacesResponse，同步进入 OpenAPI 文档）；页面注入瓦片配置、统计配置（分级/堆叠次序/p 档/低分母阈值，单源 core.ensemble）与洋区码表 BASIN_CATALOG（单源 core.basin，地点 8 码 + SH cycloneOnly，M9）；
  - `typhoon_track/web/`：三栏地图工作台（左导入/图例—中地图—右可滚动图表栏；第三栏强度分布图下方为「终生峰值强度」聚合卡——4 聚合数 + 「每成员明细」入口，最右侧每成员明细第四栏默认隐藏、入口双向展开[M8/M8-R1]；templates + static：原生 ES Module JS、Leaflet 1.9.4 与 uPlot 1.6.32 本地 vendor、观测叠加、概率圆时次滑块（纯查看器：默认 0 档、仅移动当前时次高亮 p 圆，不截断成员线/图表；max 截断于首个低分母时次与均值线同口径[M5d-R11/R12]、单成员/统计未就绪时禁用）、强度曲线双向联动[M3/M4]、自算均值叠加/强度分布堆叠/概率半径曲线与地图 p 圆[M5]、目标地点选点（预存/坐标/点选）与影响概率卡片及参考圆[M6]、预存地点洋区复选框筛选（8 码固定顺序默认全选、无地点洋区置灰、不跟随气旋）与当前气旋洋区提示（前缀直映标签，未识别隐藏）[M9]、参考圆分级配色+图例/接口调用轻量加载提示（状态栏 busy 文案+上传禁用）/位置概率半径图表暂隐藏（锚点与数据链路保留）/影响概率第四级核心强风区[M7]、跨 180° 经线组内经度展开（点/线/包围盒同组同副本、圆环相对圆心展开，走最短方向[M7f]、每成员峰值明细表哨兵"-"与风速峰值图例强度原色着色（值+时效标签，哨兵/气压列不着色）[M8/M8-R2]）；静态资源经 NoCacheStaticFiles 显式 no-cache（M8-R1：杜绝浏览器启发式缓存的「新 HTML+旧 CSS」，模板引用带 ?v= 版本参数）；
  - 根目录 `config.toml`：瓦片配置（url_template/attribution/max_zoom），api 层 `load_tile_config` 加载并注入页面，代码不硬编码（确认记录见 `docs/瓦片数据源确认_20261015.md`）；多瓦片源切换属候补功能池（见 `docs/里程碑基线.md`）；
  - `typhoon_track/cli.py` + `__main__.py`：重组 CLI 入口（`python -m typhoon_track`），与 `demo_src/wnc_csv_demo.py` 行为逐字节一致（`tests/test_cli_parity.py` 参数矩阵 × 数据集矩阵对照）；
  - `tests/`：正式测试目录（core 单测 + service/api 集成 + CLI 行为一致性对照 + Playwright UI E2E，pytest）；
  - 端到端验收记录留存于根目录（如 `M2服务与上传验收记录_20261015.md`）。
- 静态检查与测试配置已落地：
  - `ruff.toml`：L1（demo_src 按参考代码配置 per-file-ignores，正式源码保持零告警基线）；
  - `pyrightconfig.json`：L2（当前 ignore demo_src，正式包落地即纳入检查；需在激活的目标环境内运行以解析第三方库类型）；
  - `pytest.ini`：L5（`testpaths = demo_src`，正式测试目录落地后更新）；
  - `pyproject.toml`：L3 deptry 的 `known_first_party` 配置（依赖声明仍以 requirements*.txt 为准）；
  - `.importlinter` 契约待正式包结构落地后再配置。
- 每次任务结束前统一执行（在 `show-typhoon-track` 环境内、项目根目录）：

  ```bash
  python -m compileall -q <源码目录>         # L0
  ruff check --no-fix <源码目录或文件列表>   # L1
  pyright <源码目录或文件列表>               # L2
  python -m pip check && deptry . && lint-imports   # L3
  python -m pytest -q                        # L5（基线 159 项，UI E2E 未装自动跳过）
  ```

- 最低要求：L0 编译检查 + 现有测试全量回跑。

## 6. 提交与变更纪律

- 不主动 commit / push，除非用户明确要求。
- 提交前检查 `git status` 与 `git diff`，只暂存本次意图内的文件，不提交秘密信息与运行时产物。
- 提交信息简洁并与仓库既有风格一致；一次提交聚焦一件事。
- **里程碑单向依赖纪律**：里程碑及其对应提交只能单向依赖，即只允许后续里程碑依赖先前里程碑的成果（代码、配置、接口、验收资产），禁止任何反向依赖：
  - 先行里程碑的提交不得 import、调用或假设后续里程碑才引入的模块、接口、字段与文件；
  - 允许面向后续功能的设计预留（如配置项、可扩展参数），但该预留不得成为先行里程碑正常运行的必要条件；
  - 每个里程碑收尾时复核：本里程碑的 diff 是否触及更晚里程碑专属文件、import 与调用关系是否无前向引用；发现违例则拆分提交或把功能回移到正确的里程碑。
- **重组后行为一致性验证纪律**：凡将既有脚本拆解为模块、或对模块结构再次重组/迁移，都必须重组出行为等价的入口脚本，并与原脚本做对照验证——相同输入与参数下，stdout/stderr、退出码、导出产物保持一致；对照验证以“参数矩阵 × 数据集矩阵（含真实数据，缺失自动跳过）”的自动化测试形式纳入测试基线长期保留，以备后续结构再次变动时复验，原脚本在对照期内保持原样不动。
- 当前里程碑基线与状态**唯一登记于 `docs/里程碑基线.md`**：里程碑的增删、范围调整与状态变更，必须随对应里程碑的提交同步更新该文件；本节上述单向依赖与重组一致性纪律对基线中的每个里程碑同样生效。

## 7. 验收记录留存

- 涉及真实数据、新数据格式或端到端行为的变更，仿照 `demo_src/真实CSV验收记录_20261014.md` 的惯例，留存独立的验收记录文档（命名含日期），记录：数据来源、核验结论、发现的问题与修复。
- 保留每次真实下载的原文件名、来源 URL、下载时间及模型版本信息。

## 8. 待定事项（扩展区）

以下事项确定后回填到上文对应章节，并保持本文件与项目现状一致：

- [x] 前端技术选型：轻方案（无构建链）——FastAPI + Jinja2 + 原生 ES Module JS + Leaflet（本地 vendor，不经 npm）；前后端分离但单体服务，本机单人使用
- [x] 后端框架选型：FastAPI + uvicorn；包名 `typhoon_track`，分层契约 `api → service → core`（`.importlinter` 随 M1 落地）；CSV 双导入入口 `kind=forecast|observation`
- [x] 页面导入 CSV 的上传存储策略：`uploads/<数据集id>/original.csv + meta.json`（含 kind），无数据库，按需重解析 + 进程内 LRU 缓存（`.gitignore` 已预留 `uploads/`）
- [x] 瓦片：默认 AWS 瓦片源；URL 由根目录 `config.toml` 配置项提供（M3 落地），不硬编码；多瓦片源切换归入候补功能池（`docs/里程碑基线.md`）
- [x] 依赖声明文件形式：已采用 `requirements.txt`（运行时）+ `requirements-dev.txt`（开发）
- [x] ruff / pyright / pytest / deptry 配置落地（`ruff.toml`、`pyrightconfig.json`、`pytest.ini`、`pyproject.toml`；`.importlinter` 待包结构）
- [x] 正式包结构与测试目录（M1/M1b 已落地，登记于 §5）
