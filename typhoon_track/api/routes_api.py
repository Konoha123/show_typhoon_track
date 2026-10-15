"""REST 路由：CSV 双入口上传（kind=forecast|observation）与轨迹查询。

输入输出结构由 .schemas 的 pydantic 契约定义，并同步进入 OpenAPI 文档。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile

from typhoon_track.service.datasets import KINDS, DatasetStore
from typhoon_track.service.queries import track_rows

from .schemas import (
    DatasetListResponse,
    DatasetMeta,
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
            count=len(points),
            rows=points,
        )
