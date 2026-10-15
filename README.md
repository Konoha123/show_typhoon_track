# show_typhoon_track

基于 Google Weather Lab / WeatherNext Cyclones (WNC) 热带气旋预报数据，构建一套**导入 → 解析 → 交互式网页可视化**的工具：用户在页面上导入预报轨迹 CSV，系统解析后在地图上展示气旋路径与强度，并叠加基础交互功能。必要时采用前后端分离方案。

> 当前状态：起步阶段。`demo_src/` 内为已通过真实数据验收的命令行演示代码，是解析逻辑的参考基础；Web 化部分见[路线图](#7-路线图)。

## 目录结构

```
show_typhoon_track/
├── typhoon_track/                     # 正式包（分层：cli/api → service → core）
│   ├── core/                          # 解析核心（纯函数：aliases/io/normalize/selection/summary/geo）
│   ├── service/                       # 编排层（数据集存储+LRU、轨迹查询载荷）
│   ├── api/                           # FastAPI 路由与应用工厂（uvicorn typhoon_track.api.app:app）
│   ├── web/templates/                 # 页面模板（M2 管理页）
│   ├── cli.py                         # 重组 CLI 入口（python -m typhoon_track）
│   └── __main__.py
├── tests/                             # 正式测试（core 单测 + service/api 集成 + CLI 行为一致性对照）
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

## 快速开始（Web 服务，M2）

```bash
conda activate show-typhoon-track
python -m uvicorn typhoon_track.api.app:app --port 8000
# 浏览器访问 http://127.0.0.1:8000 ：上传预报/观测 CSV，浏览数据集元数据
# REST 接口：POST /api/datasets（file+kind）、GET /api/datasets、GET /api/datasets/{id}(/tracks)
```

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
python -m pytest -q                   # L5 功能测试（90 项基线）
```

## 路线图

1. **解析模块化**：将 `demo_src` 中已验证的 CSV 解析、字段映射、轨迹选取逻辑整理为独立包。
2. **Web 服务与页面上传**：提供后端接口接收页面导入的原始 CSV，导入后触发解析。
3. **轨迹地图可视化**：在交互式网页中渲染气旋路径与强度（前端技术选型待定，候选：Leaflet / Plotly / MapLibre）。
4. **交互功能**：气旋 / 集合成员 / 起报时次筛选、预报时效滑块、强度曲线联动等基础交互。

## 参考资料

- [Google 官方 Weather Lab 指南](https://developers.google.com/weathernext/guides/weatherlab)
- [Google DeepMind 官方 weathernext/cyclones/constants.py](https://github.com/google-deepmind/weathernext/blob/main/weathernext/cyclones/constants.py)
- [第三方下载工具 weathernext-download](https://github.com/CongGao-CG/weathernext-download)
