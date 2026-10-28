# show_typhoon_track

基于 Google Weather Lab / WeatherNext Cyclones (WNC) 热带气旋预报数据，构建一套**导入 → 解析 → 交互式网页可视化**的工具：用户在页面上导入预报轨迹 CSV，系统解析后在地图上展示气旋路径与强度，并叠加基础交互功能。必要时采用前后端分离方案。

> 当前状态：`typhoon_track` 正式包、三栏 Web 工作台（地图 + 曲线联动 + 集合概率特征 + 影响概率 + 终生峰值 + 预存地点洋区筛选）、服务简单入口与 configs 统一、mean 口径截断统一（最近接近修复 + 截断规则后端单源）已落地（M1–M11）；下一迭代候选见 [docs/里程碑基线.md](./docs/里程碑基线.md)。

## 目录结构

```
show_typhoon_track/
├── typhoon_track/                     # 正式包（分层：cli/api → service → core）
│   ├── core/                          # 解析核心（纯函数：aliases/io/normalize/selection/summary/geo/ensemble/impact）
│   ├── service/                       # 编排层（数据集存储+LRU、轨迹查询/集合与影响统计载荷、预存地点热读取）
│   ├── api/                           # FastAPI 路由与应用工厂（uvicorn typhoon_track.api.app:app）
│   ├── web/                           # M3 地图工作台（templates + static + Leaflet 本地 vendor）
│   ├── cli.py                         # 重组 CLI 入口（python -m typhoon_track）
│   └── __main__.py
├── tests/                             # 正式测试（core 单测 + service/api 集成 + CLI 行为一致性对照）
├── docs/                              # 验收与确认记录（含 M2/M3 验收、瓦片数据源确认）
├── app.py                             # Web 服务简单入口（python app.py，M10；监听配置 configs/server.json）
├── configs/                           # 运行时配置（tiles.toml 瓦片：url_template/attribution/max_zoom；server.json 服务监听：host/port）
├── places/                            # 预存地点（places.csv 用户维护、git 忽略；example 模板入库）
├── demo_src/                          # 演示与参考代码（命令行版，行为对照基准）
│   ├── wnc_csv_demo.py                # CSV 读取、字段识别、轨迹选取、导出
│   ├── test_wnc_csv_demo.py           # 9 项合成数据自检（无网络依赖）
│   ├── test_wnc_csv_real.py           # 6 项真实数据回归（文件缺失时自动跳过）
│   ├── FNV3P2_2026_10_14T00_00_paired (1).csv   # 真实预报导出文件
│   ├── sample_synthetic_ensemble_mean.csv       # 合成单气旋集合均值样例
│   ├── sample_synthetic_ensemble.csv            # 合成双成员样例（演示成员选取）
│   ├── 真实CSV验收记录_20261014.md     # 数据结构核验与修复说明
│   └── README.md                      # 演示代码详细使用说明
├── AGENTS.md                          # AI 编程 Agent 工作纪律与指南
├── requirements.txt                    # 运行时依赖
├── requirements-dev.txt               # 开发与验证依赖
├── ruff.toml                           # L1 静态检查配置
├── pyrightconfig.json                 # L2 类型检查配置
├── pytest.ini                          # L5 测试配置
├── pyproject.toml                      # L3 deptry 配置
├── .importlinter                       # 分层契约
├── Python 项目 L0–L6 分层验证规范.md    # Python 代码分层验证规范（强制参照）
└── README.md                           # 本文件
```

## 环境准备

- Conda 环境名：`show-typhoon-track`（Python 3.13）
- 依赖声明：`requirements.txt`（运行时，`pandas>=2.0`）；`requirements-dev.txt`（开发，额外含 ruff / pyright / deptry / import-linter / pytest）

```bash
conda activate show-typhoon-track
python -m pip install -r requirements.txt        # 仅运行
python -m pip install -r requirements-dev.txt    # 开发与验证
```

## 快速开始

正式包提供与演示脚本行为等价的重组 CLI（推荐，项目根目录运行）：

```bash
python -m typhoon_track "demo_src/FNV3P2_2026_10_14T00_00_paired (1).csv" \
  --storm WP962026 --member 9 --max-lead-hours 48
```

原始演示脚本在 `demo_src/` 下原样保留（行为对照基准），在该目录运行，详细用法见 `demo_src/README.md`：

```bash
cd demo_src

# 语法检查 + 全量自检（含真实数据时应为 15 项通过）
python -m py_compile wnc_csv_demo.py
python -m unittest -v test_wnc_csv_demo.py test_wnc_csv_real.py

# 第一步：检查真实文件的实际列名与格式
python wnc_csv_demo.py 'FNV3P2_2026_10_14T00_00_paired (1).csv' --inspect

# 列出全部气旋、集合成员及有效时效
python wnc_csv_demo.py 'FNV3P2_2026_10_14T00_00_paired (1).csv' --list-tracks

# 选取指定气旋/成员，读取前 48 小时路径与强度
python wnc_csv_demo.py 'FNV3P2_2026_10_14T00_00_paired (1).csv' \
  --storm WP962026 --member 9 --max-lead-hours 48
```

## 快速开始（Web 地图工作台，M3）

```bash
conda activate show-typhoon-track
python app.py
# 等价方式：python -m uvicorn typhoon_track.api.app:app --host 127.0.0.1 --port 8000
# 监听地址与端口在 configs/server.json 配置（pydantic 校验，缺文件报错退出）；CSV CLI 为 python -m typhoon_track，两入口不冲突
# 浏览器访问 http://127.0.0.1:8000 ：
#   - 上传预报/观测 CSV（双入口）→ 选择气旋/起报/成员 → 地图渲染轨迹
#   - 成员"全部"为意面图；单成员按强度着色点位；观测轨迹黑虚线叠加；概率圆时次滑块只取实际存在档位（默认 0 档、仅移动当前时次高亮概率圆，不截断成员线/图表；上限截断于首个低分母时次，尾部消散成员不画概率圆；单成员模式禁用）
#   - 第三栏强度分布图下方「终生峰值强度」卡：每成员终生峰值的上中位/平均；
#     卡内「每成员明细」按钮展开最右侧明细栏（成员、峰值风速/气压与出现时效；
#     风速峰值与时效标签按左栏图例的强度等级着色，哨兵"-"不着色）
#   - 目标地点与影响概率的用法见下文「目标地点与影响概率使用说明」
# 瓦片数据源在 configs/tiles.toml 配置（确认记录见 docs/瓦片数据源确认_20261015.md；M10 起由根目录 config.toml 迁入 configs/）
# REST 接口：POST /api/datasets（file+kind）、GET /api/datasets、GET /api/datasets/{id}(/tracks)
```

## 目标地点与影响概率使用说明（M6）

对任一目标地点，工作台会按当前选定的 (气旋, 起报时次) 计算三级风圈影响概率与 mean 口径最近接近：选定后地图打标记并绘制 100/200/400/800 km 参考圆（**纯视觉参考，不参与判定**），右栏「影响概率」卡片展示结果，并随气旋/起报时次/目标变化自动重算。

### 预存地点的管理

预存地点保存在项目根目录 `places/places.csv`，由使用者自行维护（该目录被 git 忽略，仅模板 `places/places.example.csv` 入库）：

```bash
cp places/places.example.csv places/places.csv   # 首次使用：从模板复制后用任意编辑器维护
```

- 列格式：`name,lat,lon,note`（`note` 可选；多余列忽略；`#` 开头注释行忽略；UTF-8 编码）；
- 约束：`name` 唯一（重名以首现为准，其余跳过）；`lat`∈[-90,90]、`lon`∈[-180,180]，十进制度；
- **热读取**：服务端每次请求现读该文件——编辑保存后**刷新页面（F5）即生效**，无需重启服务；
- 坏行（坐标非数值/越界、空名、重名）逐行跳过，原因显示在左栏下拉下方，不影响其余行；
- 文件缺失时自动降级为仅临时选点（不报错）；文件存在但缺必要列或为空会给出明确错误提示。

### 页面选点方式（三者互斥）

1. **预存地点下拉**：左栏「目标地点」卡片中选择，坐标回填到输入框并立即生效；
2. **坐标输入**：在纬度/经度文本框输入十进制度，点击「应用坐标」或按 Enter（越界会提示且不生效）；
3. **地图点选**：点击「地图点选」（光标变十字）→ 再点击地图任意位置即作为目标。

点击「清除目标」撤销标记、参考圆与结果卡片。

### 结果解读与适用前提

- **三级影响概率**：烈风（风速≥34 kt）/ 暴风（风速≥50 kt）/ 飓风（风速≥64 kt）——成员在任一实际存在时次使该地点落入对应风圈象限半径内即计入分子（每成员只计一次），分母为该起报时次的成员总数；
- **核心强风区（距离≤RMW）**：成员任一时次使地点与气旋中心距离 ≤ 最大风速半径（RMW，全向圆、无象限）即计入；RMW 缺失或 ≤0 的时次不命中（留在分母，缺失保持缺失）；
- **最近接近（mean 口径）**：离目标最近的集合平均位置时次，含时效与时刻、距离（km）、气旋位于目标的方位（16 方位文字 + 方位角）、该时次自算平均风速/气压；
- 适用前提：预报数据集（kind=forecast）、已选定单一气旋与起报时次、CSV 含 34/50/64 kt 风圈四象限列；不满足时（如无风圈列的数据集）卡片显式给出不可用原因，**不做距离回退**。

## 数据说明

数据来源为 [Google Weather Lab](https://deepmind.google.com/science/weatherlab) 的 WeatherNext Cyclones (WNC) 预报产品（CSV 导出），字段语义、单位与经度约定的详细说明见 `demo_src/README.md`，要点：

- 核心字段：轨迹标识 `track_id`、起报/有效时间、预报时效、经纬度、最大风速（kt）、中心气压（hPa）、最大风速半径及 34/50/64 kt 风圈四象限半径。
- 真实样例（FNV3P2，对应 WeatherNext 2 Cyclones r2）：4,592 行、23 列、4 个气旋、每气旋 50 个集合成员、最大预报时效 360 小时；文件以多行 `#` 注释开头。
- 注意事项：经度可能为 0–360° 约定；缺失值保持缺失；不跨气旋/成员/起报时次混合统计；集合均值不是成员风速的任意平均。

## 验证与测试

本项目所有 Python 代码修改须参照[《Python 项目 L0–L6 分层验证规范.md》](<./Python 项目 L0–L6 分层验证规范.md>)执行分层验证（L0 语法编译 → L6 端到端验收），核心纪律：**未经实际执行的验证，不得声称已经通过**。工作纪律另见 [AGENTS.md](./AGENTS.md)。

常用验证命令（在 `show-typhoon-track` 环境内、项目根目录执行；配置见 `ruff.toml` / `pyrightconfig.json` / `pytest.ini` / `pyproject.toml`）：

```bash
python -m compileall -q typhoon_track  # L0 语法编译
ruff check --no-fix .                 # L1 静态缺陷
pyright                               # L2 静态类型
python -m pip check && deptry . && lint-imports   # L3 依赖与架构
python -m pytest -q                   # L5 功能测试（268 项基线，含 Playwright UI E2E）
```

## 路线图

- ✅ **解析模块化**：`demo_src` 演示逻辑整理为正式包 `typhoon_track`（CLI 与演示脚本的行为一致性由自动化对照测试长期保障）
- ✅ **Web 服务与上传**：FastAPI 双入口（预报/观测）导入 CSV，页面导入即解析
- ✅ **轨迹地图可视化**：Leaflet 工作台——集合成员意面图、单成员强度着色、观测轨迹叠加、概率圆时次滑块（M5d-R12 与成员线绘制解耦）
- ✅ **强度曲线联动**：uPlot 风速/气压曲线与地图双向联动（单成员双轴；全成员细线与地图同配色）
- ✅ **预报概率特征**：逐时次自算集合统计（均值=官方口径 94/94 验证）、强度分布堆叠图（含已消散）、位置概率半径（p 下拉 40–100% + 应用确认、低分母虚线；概率圆时次滑块与地图概率圆同口径截断于首个低分母时次）、三栏工作台布局
- ✅ **影响概率**：目标地点（预存地点 `places/places.csv` 热读取 / 坐标输入 / 地图点选）三级风圈命中概率（烈风/暴风/飓风，逐成员象限判定）+ mean 口径最近接近（时效/距离/16 方位/强度），地图标记与 100/200/400/800 km 参考圆；无风圈列数据集显式不可用（不回退）
- ✅ **基于使用的优化（第一轮）**：影响概率第四级核心强风区（距离≤RMW，RMW 缺失/≤0 不命中留在分母）、参考圆分级配色+左栏图例、接口调用轻量加载提示（状态栏 busy 文案 + 上传按钮禁用）、位置概率半径图表暂隐藏（数据链路与锚点保留，视使用体验再决定恢复或删除）
- ✅ **终生峰值强度（M8）**：每成员整条预报轨迹的终生最大风速/最低气压（独立取极值、各示出现时效、并列取最早）+ 跨成员上中位值与平均数（消散成员以有限峰值参与、指标全缺成员为哨兵显"-"且不进聚合）；`peak-stats` 端点 + 默认隐藏、聚合卡内入口展开的第四栏（风速峰值与时效标签按图例强度等级着色）；无官方对照产品，以独立 pandas 复算验收
- ✅ **预存地点洋区筛选（M9）**：`places.csv` 手工维护 8 码洋区标注（IBTrACS 七分 + CP 扩展）；目标地点区洋区复选框（固定顺序、默认全选、无地点洋区置灰、不跟随气旋）即时过滤地点下拉；当前气旋洋区提示（`track_id` 前缀直映不合并：AL→NA/EP/CP/WP/IO→NI/SH，未识别前缀隐藏）
- ✅ **服务简单入口与 configs 统一（M10）**：根目录 `python app.py` 薄封装启动 Web 服务（`configs/server.json` pydantic JSON 解析 host/port，缺文件报错退出；与 `python -m uvicorn ...` 并列）；运行时配置统一 `configs/`（tiles.toml + server.json；places/uploads 属运行时数据不迁入）
- ✅ **mean 口径截断统一（M11）**：`core.ensemble` 截断规则纯函数（`low_denominator_cut_lead`，唯一规范实现）→ `ensemble-stats` 响应 `mean_cut_lead_h` → 前端地图 mean 线/时效滑块域/强度图/气压图均值线统一消费（成员细线不截断）；最近接近（mean 口径）限截断内时次，极端全低分母 closest=null 并以 `closest_note` 说明原因
- 📋 **候补**：跨数据集叠加对比、瓦片数据源切换等

开发用里程碑基线（状态、提交、依赖与验收要点）见 [docs/里程碑基线.md](./docs/里程碑基线.md)。

## 参考资料

- [Google 官方 Weather Lab 指南](https://developers.google.com/weathernext/guides/weatherlab)
- [Google DeepMind 官方 weathernext/cyclones/constants.py](https://github.com/google-deepmind/weathernext/blob/main/weathernext/cyclones/constants.py)
- [第三方下载工具 weathernext-download](https://github.com/CongGao-CG/weathernext-download)
