"""FastAPI application for the Clippy service layer."""

from __future__ import annotations

from contextlib import asynccontextmanager
import hmac
import logging
import os
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from . import db
from .models import (
    Asset,
    AssetPatch,
    Job,
    JobCreate,
    JobEvent,
    Project,
    ProjectCreate,
)
from .settings import Settings
from .storage import LocalStorage
from .worker import Worker

LOGGER = logging.getLogger(__name__)


def _render_response(render: dict, storage: LocalStorage) -> dict:
    render = dict(render)
    render["url"] = storage.url(render["file_key"])
    return render


def _asset_response(asset: dict, storage: LocalStorage) -> dict:
    asset = dict(asset)
    asset["renders"] = [
        _render_response(render, storage) for render in asset.get("renders", [])
    ]
    return asset


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    if settings.api_key is None:
        LOGGER.warning(
            "CLIPPY_API_KEY unset: API is unauthenticated (local dev only)"
        )
    conn = db.connect(settings.db_path)
    db.init_schema(conn)
    conn.close()
    storage = LocalStorage(settings.storage_root)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        worker = None
        if settings.worker_enabled:
            worker = Worker(settings, storage)
            worker.start()
        app.state.worker = worker
        yield
        if worker:
            worker.stop()
            worker.join(timeout=5)

    app = FastAPI(title="Clippy Service", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials="*" not in settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def require_api_key():
        def dependency(x_api_key: str | None = Header(default=None)):
            if settings.api_key is None:
                return
            if not x_api_key or not hmac.compare_digest(
                x_api_key, settings.api_key
            ):
                raise HTTPException(status_code=401, detail="Invalid API key")

        return dependency

    require_api_key_dependency = require_api_key()
    api_router = APIRouter(
        prefix="/api",
        dependencies=[Depends(require_api_key_dependency)],
    )

    @api_router.post("/projects", response_model=Project)
    def create_project(payload: ProjectCreate):
        if payload.local_path:
            local_path = os.path.realpath(payload.local_path)
            roots = [Path(root).resolve() for root in settings.local_media_roots]
            path = Path(local_path)
            if not path.is_file() or not any(
                path.is_relative_to(root) for root in roots
            ):
                root_text = ", ".join(str(root) for root in roots)
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "local_path must be an existing file under one of: "
                        f"{root_text}"
                    ),
                )
            payload = payload.model_copy(update={"local_path": local_path})
        return db.create_project(
            settings.db_path, **payload.model_dump()
        )

    @api_router.get("/projects", response_model=list[Project])
    def list_projects():
        return db.list_projects(settings.db_path)

    @api_router.post("/jobs", response_model=Job)
    def create_job(payload: JobCreate):
        for project_id in payload.project_ids:
            if not db.get_project(settings.db_path, project_id):
                raise HTTPException(
                    status_code=404,
                    detail=f"Project not found: {project_id}",
                )
        return db.create_job(
            settings.db_path,
            project_ids=payload.project_ids,
            brief=payload.brief,
            formats=[item.model_dump() for item in payload.formats],
            clips=payload.clips,
            options=payload.options.model_dump(),
        )

    @api_router.get("/jobs", response_model=list[Job])
    def list_jobs():
        return db.list_jobs(settings.db_path)

    @api_router.get("/jobs/{job_id}", response_model=Job)
    def get_job(job_id: str):
        job = db.get_job(settings.db_path, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return job

    @api_router.get("/jobs/{job_id}/events", response_model=list[JobEvent])
    def list_job_events(job_id: str):
        if not db.get_job(settings.db_path, job_id):
            raise HTTPException(status_code=404, detail="Job not found")
        return db.list_events(settings.db_path, job_id)

    @api_router.get("/assets", response_model=list[Asset])
    def list_assets(
        job_id: str | None = None,
        project_id: str | None = None,
        ratio: str | None = None,
        min_score: int | None = Query(default=None),
        state: str | None = None,
        favorite: bool | None = None,
    ):
        rows = db.list_assets(
            settings.db_path,
            job_id=job_id,
            project_id=project_id,
            ratio=ratio,
            min_score=min_score,
            state=state,
            favorite=favorite,
        )
        return [_asset_response(row, storage) for row in rows]

    @api_router.get("/assets/{asset_id}", response_model=Asset)
    def get_asset(asset_id: str):
        asset = db.get_asset(settings.db_path, asset_id)
        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found")
        return _asset_response(asset, storage)

    @api_router.patch("/assets/{asset_id}", response_model=Asset)
    def patch_asset(asset_id: str, payload: AssetPatch):
        asset = db.update_asset(
            settings.db_path,
            asset_id,
            state=payload.state,
            favorite=payload.favorite,
        )
        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found")
        return _asset_response(asset, storage)

    app.include_router(api_router)

    @app.get("/api/health")
    def health():
        worker = getattr(app.state, "worker", None)
        return {
            "status": "ok",
            "worker_alive": bool(worker and worker.is_alive()),
            "queued": db.count_jobs(settings.db_path, "queued"),
            "running": db.count_jobs(settings.db_path, "running"),
        }

    @app.get("/files/{key:path}", dependencies=[Depends(require_api_key_dependency)])
    def get_file(key: str):
        try:
            candidate = Path(storage.path(key)).resolve()
        except ValueError:
            raise HTTPException(status_code=404, detail="File not found")
        root = Path(settings.storage_root).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            raise HTTPException(status_code=404, detail="File not found")
        if not candidate.is_file():
            raise HTTPException(status_code=404, detail="File not found")
        return FileResponse(str(candidate))

    return app


app = create_app()
