# WNC 热带气旋 CSV 使用示例（方案 A）

更新时间：2026-10-14。**目标是读取已下载到本地的 Weather Lab / WeatherNext Cyclones (WNC) 热带气旋轨迹 CSV，不是下载程序，也不是运行 WNC 推理。2026-10-14 已用真实 FNV3P2 文件完成兼容性验收并修订。** 首次接触真实 CSV 时，先运行 `--inspect` 查看字段，确认含义和单位。`sample_synthetic_*` 两份 CSV 均为**人工合成测试数据**；另有用户提供的 `FNV3P2_2026_10_14T00_00_paired (1).csv` 属于**真实公开预报导出文件**，不要将两者混淆。

## 目录

| 文件 | 用途 |
|---|---|
| `wnc_csv_demo.py` | 命令行读取、字段识别、选取单条预报轨迹、查询强度和路径、导出 CSV |
| `README.md` | 本说明、使用示例和限制 |
| `sample_synthetic_ensemble_mean.csv` | **合成**的单气旋、单起报、集合均值类数据样例 |
| `sample_synthetic_ensemble.csv` | **合成**的双成员数据，演示防止不同成员混合 |
| `test_wnc_csv_demo.py` | 无网络依赖的9项基础自检测试 |
| `FNV3P2_2026_10_14T00_00_paired (1).csv` | 用户提供的 Google Weather Lab 原始真实数据；按原文件名保留 |
| `test_wnc_csv_real.py` | 对上述真实 CSV 的6项回归测试；原始数据不在目录时自动跳过 |
| `真实CSV验收记录_20261014.md` | 数据结构核验、脚本缺陷及修复说明 |

## 1. 环境准备

推荐 Python 3.10+；唯一运行依赖为 `pandas>=2.0`。无需 GPU、Google 账户或 WNC 模型权重。Conda / venv 均可。

```bash
python --version
python -m pip show pandas
# 如没有 pandas：
python -m pip install 'pandas>=2.0'

python -m py_compile wnc_csv_demo.py
python -m unittest -v test_wnc_csv_demo.py test_wnc_csv_real.py
```

`py_compile` 只检查语法，不代替运行时功能测试。附带真实样本时，`unittest` 应为 **15 项通过（9 项合成数据 + 6 项真实数据）**；未放真实样本时，6 项实测自动跳过。

## 2. 下载真实 CSV（两种可选方式）

**手工：** 打开 [Google Weather Lab](https://deepmind.google.com/science/weatherlab)，进入 Cyclone Tracking / Download，选择 WNC 模型、起报时次和 CSV 格式，区分 *ensemble mean* 与 *ensemble members*。界面具体按钮可能更新。

**命令行（第三方工具，并非本项目依赖）：** [weathernext-download](https://github.com/CongGao-CG/weathernext-download) 支持从 Weather Lab 获取相应文件（实际下载可用性取决于上游）：

```bash
python -m pip install --upgrade weathernext-download
# 选定 2026-07-01 00 UTC，下载 OPER 的集合均值 CSV
weathernext-download --cyclone --time 2026070100 --oper --ensemble_mean --csv
# 如果需要逐成员轨迹：
weathernext-download --cyclone --time 2026070100 --oper --ensemble --csv
```

该下载工具文档表示文件保存在当前工作目录的 `ensemble_mean/`、`ensemble/` 下。**不要假定真实文件名或列格式，首先检查下载内容与文件头。** 此示例不自动请求网络，也不负责判断下载工具的许可、数据版本或成功状态。

## 3. 从命令行读取本地 CSV

在本目录下运行（路径可改成实际下载文件路径）：

```bash
# 第一步：检查列名、类型对应关系和前3行
python wnc_csv_demo.py sample_synthetic_ensemble_mean.csv --inspect

# 第二步：提取位置、预报时效、强度、风圈及峰值/24h增量
python wnc_csv_demo.py sample_synthetic_ensemble_mean.csv

# 查看 48 小时预报，示例返回一行
python wnc_csv_demo.py sample_synthetic_ensemble_mean.csv --at-lead-hours 48

# 只查看 120 小时内；导出标准化选择结果
python wnc_csv_demo.py sample_synthetic_ensemble_mean.csv \
    --max-lead-hours 120 --output selected_track.csv

# 真实文件（替换成你下载的路径）
python wnc_csv_demo.py '/path/to/your_weatherlab_tracks.csv' --inspect
python wnc_csv_demo.py '/path/to/your_weatherlab_tracks.csv' --list-tracks
python wnc_csv_demo.py '/path/to/your_weatherlab_tracks.csv' --storm 'ACTUAL_TRACK_ID' \
    --init '2026-07-01T00:00Z' --member 'ACTUAL_MEMBER_ID'
```

最后一行只是**命令写法示意**：气旋、成员编号、起报时次必须是该文件中真实存在的值。不要把 `sample=0` 误认作集合均值。第一次运行请先 `--inspect`。如果无 `member` 列，就不要填写 `--member`。`--storm` 采用 `track_id` 或 `storm_name` 的**精确匹配**，不是模糊搜索。

### 逐成员 CSV：不要把不同成员直接混合统计

```bash
# 合成文件含 01 和 02 两个成员；直接运行会报提示，防止混合
python wnc_csv_demo.py sample_synthetic_ensemble.csv
# 明确指定成员后正常输出
python wnc_csv_demo.py sample_synthetic_ensemble.csv --member 01
```

如果输入含**多个起报时次、多个气旋、多个模型或多个数据来源**，示例也会要求用 `--init`、`--storm`、`--model`、`--source` 明确选取。这样能够减少将不同预报实验与实况轨迹混为一谈的风险。**集合均值不是简单地对各成员的风速或坐标任意平均**；应该直接读取 Google 提供的对应产品。

## 4. 代码演示的典型字段和提取方式

脚本使用 `pandas.read_csv(..., dtype="string")` 读入，防止气旋编号损坏；再有选择地解析数字和 UTC 时刻。**Google 官方代码的** `weathernext/cyclones/constants.py` **支持以下一组字段命名；但不能据此保证 Weather Lab 每一类 CSV 导出完全使用相同表头。**

| 标准语义名（脚本内部） | 官方仓库对应列名举例 | 说明 |
|---|---|---|
| `storm` | `track_id` | 轨迹唯一标识；不一定与公众命名/国际编号一致 |
| `init` | `init_time` | 预报初始化时间（UTC） |
| `valid` | `valid_time` | 预报验证/有效时间（UTC） |
| `lead_h` | 由 `valid_time - init_time` 得到，同时交叉验证原始 `lead_time_hours` | 预报时效（小时），明确时间单位 |
| `lat` / `lon` | `lat` / `lon` | 纬度、经度（度）；不改变 CSV 经度约定 |
| `wind` | `maximum_sustained_wind_speed_knots` | 最大持续风速（kt） |
| `pressure` | `minimum_sea_level_pressure_hpa` | 最低中心海平面气压（hPa） |
| `rmw` | `radius_of_maximum_winds_km` | 最大风速半径（km） |
| `r34_ne` 等 | `radius_34_knot_winds_ne_km` 等 | 不同风圈阈值/象限半径（km） |
| `member` | 例如 `ensemble_member` | 集合成员；具体列名/编码以真实文件为准 |

也支持 `r34/r50/r64` 风圈的 `ne/se/sw/nw` 四象限，前提是实际 CSV 提供相应列。若未提供则不生成缺失值，不臆测风圈。

**典型处理逻辑（见 `wnc_csv_demo.py`）：**

```python
import pandas as pd

df = pd.read_csv('/path/to/your.csv', dtype='string')
print(df.columns.tolist())                 # 先确认列名
# 如果包含官方命名：
subset = df[df['track_id'] == 'ACTUAL_TRACK_ID'].copy()
subset['valid_time'] = pd.to_datetime(subset['valid_time'], utc=True)
subset['maximum_sustained_wind_speed_knots'] = pd.to_numeric(
    subset['maximum_sustained_wind_speed_knots'], errors='coerce')
subset = subset.sort_values('valid_time')   # 单条轨迹按有效时间排序
print(subset[['valid_time', 'lat', 'lon',
              'maximum_sustained_wind_speed_knots']].head())
```

**这里 `ACTUAL_TRACK_ID` 必须替换为 CSV 的真实取值**。正式使用应像完整示例脚本那样先选定模型、成员和起报时次。

### 如果实际表头与官方常量不同

脚本自带少量别名识别；也可以显式映射真实列名：

```bash
python wnc_csv_demo.py my_real.csv --inspect
# 假设 CSV 的实际风速列名是 VMAX_KT、气压列是 PMIN_HPA，且已核实单位
python wnc_csv_demo.py my_real.csv --column wind=VMAX_KT --column pressure=PMIN_HPA
```

`--column` 的右侧必须是 **CSV 中真实存在的列名**。对不带单位的风速（如 `VMAX`）、气压（如 `MSLP`）或数值型 `lead_time` 不自动猜测单位；需先查元数据，再决定是否手动映射/换算。若只存在数值 `lead_time`，没有同时提供 `init_time` 和 `valid_time`，必须使用 `--lead-unit hours` 或 `--lead-unit seconds`，才允许按预报时效筛选。

## 5. 输出内容如何理解

- **轨迹表**：每行的有效时间、预报时效、经纬度、最大风速 kt、最低气压 hPa，以及存在时的风圈半径；经度可能为 0–360°，不可未经转换直接拿来同 −180–180° 系统比较。
- **最大预报风速 / 最低预报中心气压**：分别在当前**单轨迹**中取最大/最小值，它们不一定发生在同一时刻；也不等于模式全部成员的最大强度。
- **24 小时强度变化**：仅在同一条轨迹上，配对恰好相差 24 小时的两行风速计算 `V(t+24h)-V(t)`。达到 `+30 kt` 则标记满足常见的 1 分钟持续风速 RI 数值阈值；**这不是集合概率，也不保证该系统实际快速增强**。
- **CSV 输出**：`--output` 写出已筛选、标准化的字段，例如 `wind`、`pressure`、`lead_h`；输出单位与字段含义依赖上一步原始数据核对。

## 6. 边界与首次真实数据验收

1. `sample_synthetic_*` 文件为合成数据，另已使用真实 Google 导出 `FNV3P2_2026_10_14T00_00_paired (1).csv` 完成 **CSV 格式/字段与基本计算**的端到端兼容性验收。**这不是模型预测精度验证，也不代表兼容 Google 所有年份和所有产品类型。**
2. 同一 CSV 可能既有预测轨迹又有成对的观测参考轨迹。若有 `source` / `track_type` 等列，请使用 `--source` 区分；没有清晰标签时，先人工核实，不得将观测记录当作预报。
3. 没有 `member` 列不意味着这是集合平均；要结合下载时选的产品及文件来源核实。不要跨气旋/成员/起报时次计算 24 小时增强量。
4. 如果 CSV 是**非轨迹 CSV**（例如全球格点气象变量、ATCF 文件或嵌套 JSON），本脚本不适用。`--inspect` 看不到 `lat/lon`、`valid_time` 等字段时，应该停止并核对文件类型。
5. 风速是 1 分钟平均还是其他口径、缺失值的含义、经度坐标约定、源模型版本，应以该批数据提供者的说明为准；不可自动拿风速 `kt` 推断中国/JMA 的 10 分钟最大风速。
6. 如果一条轨迹重复出现同一有效时次，需调查是否未拆分成员、合并多个风暴或重复行；统计前不应随意去重。

### 官方与工具资料

- [Google 官方 Weather Lab 指南](https://developers.google.com/weathernext/guides/weatherlab)
- [Google DeepMind 官方 `weathernext/cyclones/constants.py`](https://github.com/google-deepmind/weathernext/blob/main/weathernext/cyclones/constants.py)
- [第三方下载工具 `weathernext-download`](https://github.com/CongGao-CG/weathernext-download)

**后续改进建议：** 继续保留每次真实下载的原文件、来源 URL、下载时间及模型版本；新型号/格式出现时扩大 schema 回归测试，特别核对集合均值文件与逐成员文件的差异。


## 7. 已实测的 FNV3P2 原始 CSV（2026-10-14）

用户上传 `FNV3P2_2026_10_14T00_00_paired (1).csv` 的基本结构：**4,592行、23列、4个气旋、每个气旋50个集合成员**；起报 `2026-10-14 00:00 UTC`，最大预报时效360小时（只有部分轨迹到达360小时）。`FNV3P2` 对应第三方工具列出的 **WeatherNext 2 Cyclones (r2)**，非 WNV3；源文件**没有独立的 model 或 source/observation 列**，模型名称来自文件名/下载元数据，而不是 CSV 行内字段。`paired` 文件名不表示每条 `sample` 是观测实况。不得直接从本文件推导模式-实况误差。更多数据质量和限制见验收记录。

原文件以六行 `#` 注释开头，其中包含许可提示和 `# BEGIN DATA` 标记；**修订脚本使用 `pd.read_csv(..., comment="#")` 跳过这些注释**，其后正式 CSV 表头正常识别。代码识别 `lead_time_hours`，且将其与 `valid_time - init_time` 的时效结果交叉验证；发现不一致时中止，而不是静默使用错误时效。

在脚本和原文件所在文件夹运行以下**已实际验证**的命令：

```bash
# 查看真实格式及实际列名
python wnc_csv_demo.py 'FNV3P2_2026_10_14T00_00_paired (1).csv' --inspect

# 列出全部气旋、成员及有效时效
python wnc_csv_demo.py 'FNV3P2_2026_10_14T00_00_paired (1).csv' --list-tracks

# EP202026 第0号成员，读取24小时预报并导出一行标准化数据
python wnc_csv_demo.py 'FNV3P2_2026_10_14T00_00_paired (1).csv' \
  --storm EP202026 --member 0 --at-lead-hours 24 --output selected.csv

# WP962026 第9号成员，读取前48小时的路径/风速和24小时增量
python wnc_csv_demo.py 'FNV3P2_2026_10_14T00_00_paired (1).csv' \
  --storm WP962026 --member 9 --max-lead-hours 48

# 新增6项真实格式回归测试
python -m unittest -v test_wnc_csv_demo.py test_wnc_csv_real.py
```

**特别注意**：`--at-lead-hours` 只选择当前成员**实际存在**的时效，不会插值。比如 EP202026 的第0号成员只有 0～66小时预报（每6小时一项），不能拿它查询72小时预报；如需72小时，请选择确实覆盖该时效的成员。`--at-lead-hours 24` 仅得到一条记录，当然无法计算该成员跨24小时的风速增量；若要计算增量，应使用完整或足够长的时效窗口。

截至此次验收，源数据存在50个 `radius_34_knot_winds_se_km` 和50个 `radius_34_knot_winds_sw_km` 缺失值，均位于 EP212026 的初始时效、50个集合成员中。缺失值保持缺失，不要未经证据填成0；其余数值的实际物理意义仍以 Weather Lab 文档为准。
