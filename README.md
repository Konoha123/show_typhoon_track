# show_typhoon_track

基于 Google Weather Lab / WeatherNext Cyclones (WNC) 热带气旋预报数据，构建一套**导入 → 解析 → 交互式网页可视化**的工具：用户在页面上导入预报轨迹 CSV，系统解析后在地图上展示气旋路径与强度，并叠加基础交互功能。必要时采用前后端分离方案。

> 当前状态：起步阶段。`demo_src/` 内为已通过真实数据验收的命令行演示代码，是解析逻辑的参考基础；Web 化部分见[路线图](#7-路线图)。

## 目录结构

```
show_typhoon_track/
├── demo_src/                          # 演示与参考代码（命令行版）
│   ├── wnc_csv_demo.py                # CSV 读取、字段识别、轨迹选取、导出
│   ├── test_wnc_csv_demo.py           # 9 项合成数据自检（无网络依赖）
│   ├── test_wnc_csv_real.py           # 6 项真实数据回归（文件缺失时自动跳过）
│   ├── FNV3P2_2026_10_14T00_00_paired (1).csv   # 真实预报导出文件
│   ├── 真实CSV验收记录_20261014.md     # 数据结构核验与修复说明
│   └── README.md                      # 演示代码详细使用说明
├── agents.md                          # AI 编程 Agent 工作纪律与指南
├── Python 项目 L0–L6 分层验证规范.md    # Python 代码分层验证规范（强制参照）
└── README.md                          # 本文件
```

## 环境准备

- Conda 环境名：`show-typhoon-track`（Python 3.13，当前为空环境）
- 已知数据处理依赖：`pandas>=2.0`（Web 服务与可视化依赖随开发补充）

```bash
conda activate show-typhoon-track
python --version
python -m pip show pandas || python -m pip install 'pandas>=2.0'
```

## 快速开始（演示代码）

在 `demo_src/` 目录下运行，详细用法见 `demo_src/README.md`：

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

## 数据说明

数据来源为 [Google Weather Lab](https://deepmind.google.com/science/weatherlab) 的 WeatherNext Cyclones (WNC) 预报产品（CSV 导出），字段语义、单位与经度约定的详细说明见 `demo_src/README.md`，要点：

- 核心字段：轨迹标识 `track_id`、起报/有效时间、预报时效、经纬度、最大风速（kt）、中心气压（hPa）、最大风速半径及 34/50/64 kt 风圈四象限半径。
- 真实样例（FNV3P2，对应 WeatherNext 2 Cyclones r2）：4,592 行、23 列、4 个气旋、每气旋 50 个集合成员、最大预报时效 360 小时；文件以多行 `#` 注释开头。
- 注意事项：经度可能为 0–360° 约定；缺失值保持缺失；不跨气旋/成员/起报时次混合统计；集合均值不是成员风速的任意平均。

## 验证与测试

本项目所有 Python 代码修改须参照[《Python 项目 L0–L6 分层验证规范.md》](<./Python 项目 L0–L6 分层验证规范.md>)执行分层验证（L0 语法编译 → L6 端到端验收），核心纪律：**未经实际执行的验证，不得声称已经通过**。工作纪律另见 [agents.md](./agents.md)。

## 路线图

1. **解析模块化**：将 `demo_src` 中已验证的 CSV 解析、字段映射、轨迹选取逻辑整理为独立包。
2. **Web 服务与页面上传**：提供后端接口接收页面导入的原始 CSV，导入后触发解析。
3. **轨迹地图可视化**：在交互式网页中渲染气旋路径与强度（前端技术选型待定，候选：Leaflet / Plotly / MapLibre）。
4. **交互功能**：气旋 / 集合成员 / 起报时次筛选、预报时效滑块、强度曲线联动等基础交互。

## 参考资料

- [Google 官方 Weather Lab 指南](https://developers.google.com/weathernext/guides/weatherlab)
- [Google DeepMind 官方 weathernext/cyclones/constants.py](https://github.com/google-deepmind/weathernext/blob/main/weathernext/cyclones/constants.py)
- [第三方下载工具 weathernext-download](https://github.com/CongGao-CG/weathernext-download)
