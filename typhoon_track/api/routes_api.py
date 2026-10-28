"""REST 路由：CSV 双入口上传（kind=forecast|observation）、轨迹查询、集合统计、终生峰值统计与预存地点。

输入输出结构由 .schemas 的 pydantic 契约定义，并同步进入 OpenAPI 文档。
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile

from typhoon_track.core.basin import basin_from_track_id
from typhoon_track.service.datasets import KINDS, DatasetStore
from typhoon_track.service.places import load_places
from typhoon_track.service.queries import ensemble_stats, impact_stats, peak_stats, track_rows

from .schemas import (
    CLOSEST_NOTE_TEXTS,
    CORE_WIND_LABEL,
    IMPACT_THRESHOLD_LABELS,
    CoreWindStats,
    DatasetListResponse,
    DatasetMeta,
    EnsembleStatsResponse,
    ImpactStatsResponse,
    ImpactThresholdStats,
    PeakStatsResponse,
    Place,
    PlacesResponse,
    TrackFilters,
    TrackPoint,
    TracksResponse,
)


def register(app: FastAPI) -> None:
    def _store() -> DatasetStore:
        store: DatasetStore = app.state.store
        return store

    @app.post("/api/datasets", status_code=201, response_model=DatasetMeta)
    async def create_dataset(
        file: Annotated[UploadFile, File()], kind: Annotated[str, Form()]
    ) -> DatasetMeta:
        if kind not in KINDS:
            raise HTTPException(
                status_code=400, detail=f"未知 kind: {kind}; 可选: {', '.join(KINDS)}"
            )
        content = await file.read()
        try:
            parsed = _store().create(
                filename=file.filename or "upload.csv", content=content, kind=kind
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return DatasetMeta.model_validate(parsed.meta)

    @app.get("/api/places", response_model=PlacesResponse)
    def list_places() -> PlacesResponse:
        """预存地点热读取（每次请求现读 places.csv，坏行跳过并报 warnings）。"""
        path = Path(app.state.places_path)
        try:
            result = load_places(path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return PlacesResponse(
            available=result.available,
            places=[
                Place(name=p.name, lat=p.lat, lon=p.lon, basin=p.basin, note=p.note)
                for p in result.places
            ],
            warnings=list(result.warnings),
        )

    @app.get("/api/datasets", response_model=DatasetListResponse)
    def list_datasets() -> DatasetListResponse:
        metas = [DatasetMeta.model_validate(meta) for meta in _store().list()]
        return DatasetListResponse(datasets=metas)

    @app.get("/api/datasets/{dataset_id}", response_model=DatasetMeta)
    def get_dataset(dataset_id: str) -> DatasetMeta:
        try:
            return DatasetMeta.model_validate(_store().get(dataset_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"数据集不存在: {dataset_id}") from exc

    @app.get("/api/datasets/{dataset_id}/tracks", response_model=TracksResponse)
    def get_tracks(
        dataset_id: str, filters: Annotated[TrackFilters, Query()]
    ) -> TracksResponse:
        try:
            parsed = _store().load(dataset_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"数据集不存在: {dataset_id}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            rows = track_rows(parsed.frame, **filters.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        points = [TrackPoint.model_validate(row) for row in rows]
        return TracksResponse(
            dataset_id=dataset_id,
            kind=parsed.kind,
            filters=filters,
            storm_basin=basin_from_track_id(filters.storm),
            count=len(points),
            rows=points,
        )

    @app.get(
        "/api/datasets/{dataset_id}/ensemble-stats", response_model=EnsembleStatsResponse
    )
    def get_ensemble_stats(
        dataset_id: str,
        storm: Annotated[str | None, Query(description="气旋编号；多气旋数据集必须指定")] = None,
        init: Annotated[str | None, Query(description="起报时次；多起报数据集必须指定")] = None,
    ) -> EnsembleStatsResponse:
        try:
            parsed = _store().load(dataset_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"数据集不存在: {dataset_id}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if parsed.kind != "forecast":
            raise HTTPException(status_code=400, detail="集合统计仅适用于预报数据集（kind=forecast）")
        try:
            payload = ensemble_stats(parsed.frame, storm=storm, init=init)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return EnsembleStatsResponse(
            dataset_id=dataset_id, kind=parsed.kind, **payload
        )

    @app.get("/api/datasets/{dataset_id}/peak-stats", response_model=PeakStatsResponse)
    def get_peak_stats(
        dataset_id: str,
        storm: Annotated[str | None, Query(description="气旋编号；多气旋数据集必须指定")] = None,
        init: Annotated[str | None, Query(description="起报时次；多起报数据集必须指定")] = None,
    ) -> PeakStatsResponse:
        """成员终生峰值统计（M8：整条轨迹 wind max / pressure min，上中位值+平均，哨兵剔除）。"""
        try:
            parsed = _store().load(dataset_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"数据集不存在: {dataset_id}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if parsed.kind != "forecast":
            raise HTTPException(status_code=400, detail="终生峰值统计仅适用于预报数据集（kind=forecast）")
        try:
            payload = peak_stats(parsed.frame, storm=storm, init=init)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return PeakStatsResponse(
            dataset_id=dataset_id, kind=parsed.kind, **payload
        )

    @app.get(
        "/api/datasets/{dataset_id}/impact-stats", response_model=ImpactStatsResponse
    )
    def get_impact_stats(
        dataset_id: str,
        lat: Annotated[float, Query(description="目标地点纬度（十进制度，-90–90）")],
        lon: Annotated[float, Query(description="目标地点经度（十进制度，-180–180）")],
        storm: Annotated[str | None, Query(description="气旋编号；多气旋数据集必须指定")] = None,
        init: Annotated[str | None, Query(description="起报时次；多起报数据集必须指定")] = None,
    ) -> ImpactStatsResponse:
        try:
            parsed = _store().load(dataset_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"数据集不存在: {dataset_id}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if parsed.kind != "forecast":
            raise HTTPException(status_code=400, detail="影响概率仅适用于预报数据集（kind=forecast）")
        try:
            payload = impact_stats(parsed.frame, lat=lat, lon=lon, storm=storm, init=init)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        thresholds = [
            ImpactThresholdStats(
                **stat,
                label=IMPACT_THRESHOLD_LABELS.get(
                    int(stat["threshold_kt"]), f"≥{stat['threshold_kt']} kt"
                ),
            )
            for stat in payload["thresholds"]
        ]
        core = payload["core_wind"]
        reason = payload.get("closest_reason")
        return ImpactStatsResponse(
            dataset_id=dataset_id,
            kind=parsed.kind,
            storm=storm,
            init=init,
            lat=lat,
            lon=lon,
            thresholds=thresholds,
            core_wind=CoreWindStats(label=CORE_WIND_LABEL, **core),
            closest=payload["closest"],
            # M11a：core 原因码 -> 中文文案（closest 非 None 时为 None）
            closest_note=CLOSEST_NOTE_TEXTS.get(reason) if reason else None,
        )
