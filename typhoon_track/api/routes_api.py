"""REST 路由：CSV 双入口上传（kind=forecast|observation）与轨迹查询。"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from typhoon_track.service.datasets import KINDS, DatasetStore
from typhoon_track.service.queries import track_rows


def register(app: FastAPI) -> None:
    def _store() -> DatasetStore:
        store: DatasetStore = app.state.store
        return store

    @app.post("/api/datasets", status_code=201)
    async def create_dataset(
        file: Annotated[UploadFile, File()], kind: Annotated[str, Form()]
    ) -> dict[str, Any]:
        if kind not in KINDS:
            raise HTTPException(status_code=400, detail=f"未知 kind: {kind}; 可选: {', '.join(KINDS)}")
        content = await file.read()
        try:
            parsed = _store().create(
                filename=file.filename or "upload.csv", content=content, kind=kind
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return dict(parsed.meta)

    @app.get("/api/datasets")
    def list_datasets() -> dict[str, Any]:
        return {"datasets": _store().list()}

    @app.get("/api/datasets/{dataset_id}")
    def get_dataset(dataset_id: str) -> dict[str, Any]:
        try:
            return _store().get(dataset_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"数据集不存在: {dataset_id}") from exc

    @app.get("/api/datasets/{dataset_id}/tracks")
    def get_tracks(
        dataset_id: str,
        storm: str | None = None,
        member: str | None = None,
        init: str | None = None,
        model: str | None = None,
        source: str | None = None,
        max_lead_hours: float | None = None,
        at_lead_hours: float | None = None,
    ) -> dict[str, Any]:
        try:
            parsed = _store().load(dataset_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"数据集不存在: {dataset_id}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            rows = track_rows(
                parsed.frame,
                storm=storm,
                member=member,
                init=init,
                model=model,
                source=source,
                max_lead_hours=max_lead_hours,
                at_lead_hours=at_lead_hours,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        filters = {
            key: value
            for key, value in {
                "storm": storm,
                "member": member,
                "init": init,
                "model": model,
                "source": source,
                "max_lead_hours": max_lead_hours,
                "at_lead_hours": at_lead_hours,
            }.items()
            if value is not None
        }
        return {"dataset_id": dataset_id, "kind": parsed.kind, "filters": filters, "count": len(rows), "rows": rows}
