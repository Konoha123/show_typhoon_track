"""api 层 pydantic 契约：服务接口输入输出的数据结构。

- 输入：GET /tracks 查询参数以 TrackFilters 建模；上传以 multipart 表单为准（file + kind）。
- 输出：DatasetMeta / DatasetListResponse / TracksResponse 为响应模型（同步进入 OpenAPI 文档）。
- 时间字段保持 ISO 8601 字符串（与 meta.json 落盘及 M2 输出格式一致）；数值统一 float；
  缺失字段序列化为 null（缺失保持缺失，不臆造 0）。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

Kind = Literal["forecast", "observation"]


class StormSummary(BaseModel):
    """数据集内单个气旋的概况（非集合平均）。"""

    storm: str
    rows: int
    member_count: int | None = None
    lead_min: float | None = None
    lead_max: float | None = None


class DatasetSummary(BaseModel):
    """数据集级汇总：气旋列表 + 全体成员编号（无成员字段时为 null）。"""

    storms: list[StormSummary]
    members: list[str] | None = None


class DatasetMeta(BaseModel):
    """导入响应与数据集列表/详情的元数据。"""

    model_config = ConfigDict(extra="ignore")

    dataset_id: str
    kind: Kind
    original_filename: str
    created_at: str  # ISO 8601（UTC）
    rows: int
    columns: int
    mapping: dict[str, str]
    warnings: list[str]
    summary: DatasetSummary


class DatasetListResponse(BaseModel):
    datasets: list[DatasetMeta]


class Place(BaseModel):
    """单个预存地点（来自 places/places.csv，契约见 service.places）。"""

    name: str
    lat: float
    lon: float
    basin: str  # 洋区码（core.basin.BASIN_ORDER 8 码之一，M9）
    note: str | None = None


class PlacesResponse(BaseModel):
    """预存地点响应；文件缺失时 available=False 且 places 为空（前端仅临时选点）。"""

    available: bool
    places: list[Place]
    warnings: list[str]


class TrackFilters(BaseModel):
    """轨迹查询参数（全部可选；语义同 core.filter_rows，值不匹配时 400）。"""

    storm: str | None = None
    member: str | None = None
    init: str | None = None
    model: str | None = None
    source: str | None = None
    max_lead_hours: float | None = None
    at_lead_hours: float | None = None


class TrackPoint(BaseModel):
    """单条轨迹点：语义键同 core ALIASES，另含 lead_h 与 lon_signed。"""

    model_config = ConfigDict(extra="ignore")

    storm: str | None = None
    name: str | None = None
    model: str | None = None
    source: str | None = None
    member: str | None = None
    init: str | None = None
    valid: str | None = None
    lead: str | None = None
    lead_h: float | None = None
    lat: float | None = None
    lon: float | None = None
    lon_signed: float | None = None
    wind: float | None = None
    pressure: float | None = None
    rmw: float | None = None
    r34_ne: float | None = None
    r34_se: float | None = None
    r34_sw: float | None = None
    r34_nw: float | None = None
    r50_ne: float | None = None
    r50_se: float | None = None
    r50_sw: float | None = None
    r50_nw: float | None = None
    r64_ne: float | None = None
    r64_se: float | None = None
    r64_sw: float | None = None
    r64_nw: float | None = None


class TracksResponse(BaseModel):
    """轨迹查询响应；filters 为结构化回显（未提供的条件为 null）。"""

    dataset_id: str
    kind: Kind
    filters: TrackFilters
    storm_basin: str | None = None  # 当前气旋洋区（track_id 前缀直映，M9；未筛选/未识别为 null）
    count: int
    rows: list[TrackPoint]


class EnsembleLeadStats(BaseModel):
    """单个预报时效的集合统计（口径见 core.ensemble；分母 n 逐时次暴露）。"""

    lead_h: float
    valid: str | None = None  # ISO 8601（UTC）
    n_total: int
    n_present: int
    mean_wind: float | None = None
    mean_pressure: float | None = None
    mean_lat: float | None = None
    mean_lon: float | None = None
    radius_km: dict[int, float | None]  # p(%) -> km；位置缺失时为 null
    category_counts: dict[str, int]  # 各强度等级 + DISSIPATED（+ UNKNOWN 若有）
    low_denominator: bool


class EnsembleStatsResponse(BaseModel):
    """集合统计响应；一次返回全部 p 档，前端切换 p 无需重新请求。"""

    dataset_id: str
    kind: Kind
    storm: str | None
    init: str | None
    p_values: list[int]
    count: int
    leads: list[EnsembleLeadStats]


class PeakMetricStats(BaseModel):
    """单一终生峰值指标的跨成员聚合（M8；哨兵成员剔除，分母 = n_valid）。"""

    n_valid: int
    median: float | None = None  # 上中位值：升序第 floor(n/2)+1 个；无有效成员时 null
    mean: float | None = None


class MemberPeak(BaseModel):
    """单个成员的终生峰值；指标从未有有效值时为 null（前端显示"-"）。"""

    member: str
    peak_wind: float | None = None
    peak_wind_lead_h: float | None = None
    peak_pressure: float | None = None
    peak_pressure_lead_h: float | None = None


class PeakStatsResponse(BaseModel):
    """终生峰值统计响应（整条预报轨迹口径，M8 基线；风速/气压独立取极值）。"""

    dataset_id: str
    kind: Kind
    storm: str | None
    init: str | None
    n_total: int
    wind: PeakMetricStats
    pressure: PeakMetricStats
    members: list[MemberPeak]


IMPACT_THRESHOLD_LABELS: dict[int, str] = {
    34: "烈风（风速≥34 kt）",
    50: "暴风（风速≥50 kt）",
    64: "飓风（风速≥64 kt）",
}
CORE_WIND_LABEL = "核心强风区（距离≤RMW）"


class ImpactThresholdStats(BaseModel):
    """单一风速阈值的目标地点影响统计（口径见 core.impact 与 M6/M7 基线）。"""

    threshold_kt: int
    label: str
    hit_members: int
    total_members: int
    fraction: float | None  # total_members 为 0 时为 null


class CoreWindStats(BaseModel):
    """核心强风区（距气旋中心 ≤ RMW）的目标地点影响统计（M7d；口径见 core.impact）。"""

    label: str
    hit_members: int
    total_members: int
    fraction: float | None  # total_members 为 0 时为 null


class ClosestApproach(BaseModel):
    """mean 口径最近接近时次（自算逐时次均值位置，非文件 mean 成员线）。"""

    lead_h: float
    valid: str | None = None  # ISO 8601（UTC）
    distance_km: float
    bearing_deg: float  # 地点→气旋中心方位角（正北 0°、顺时针 0–360°）
    compass: str  # 16 方位文字
    mean_wind: float | None = None
    mean_pressure: float | None = None
    mean_lat: float
    mean_lon: float


class ImpactStatsResponse(BaseModel):
    """影响统计响应；thresholds 固定 34/50/64 kt 三级 + core_wind 核心强风区（M7d），
    closest 无有效位置时为 null。"""

    dataset_id: str
    kind: Kind
    storm: str | None
    init: str | None
    lat: float
    lon: float
    thresholds: list[ImpactThresholdStats]
    core_wind: CoreWindStats
    closest: ClosestApproach | None
