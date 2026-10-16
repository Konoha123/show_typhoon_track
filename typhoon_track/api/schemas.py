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
