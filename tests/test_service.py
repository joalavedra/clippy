from __future__ import annotations

import os
from types import SimpleNamespace

from fastapi.testclient import TestClient

from service import db
from service.app import create_app
from service.settings import Settings
from service.storage import LocalStorage
from service.worker import Worker, catalog_results


def _settings(tmp_path):
    return Settings(data_dir=str(tmp_path / "data"), worker_enabled=False)


def _recipe_clip(clip_id=1):
    return {
        "clip_id": clip_id,
        "title": f"Clip {clip_id}",
        "viral_score": 82,
        "rationale": "A useful point.",
        "hook": {
            "text": "A useful point.",
            "duration": 3,
            "scenes": [{"source_id": "p1", "start": 0, "end": 3, "label": "hook"}],
        },
        "highlight": {
            "scenes": [
                {"source_id": "p1", "start": 4, "end": 9, "label": "highlight"}
            ],
            "transition": "cut",
        },
        "metadata": {"description": "A description", "hashtags": ["#one"]},
    }


def _fake_results(tmp_path):
    outputs = []
    for ratio in ("9:16", "16:9"):
        slug = ratio.replace(":", "x")
        path = tmp_path / f"{slug}.mp4"
        path.write_bytes(b"fake mp4")
        outputs.append(
            {
                "format": ratio,
                "slug": slug,
                "recipe_path": str(tmp_path / f"{slug}.json"),
                "recipe": {"clips": [_recipe_clip()]},
                "render": [{"clip_id": 1, "final_path": str(path)}],
            }
        )
    return outputs


def test_create_project_and_job_api(tmp_path):
    settings = _settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.post(
            "/api/projects",
            json={
                "name": "Local demo",
                "platform": "local",
                "local_path": "/tmp/demo.mp4",
            },
        )
        assert response.status_code == 200
        project = response.json()
        job_response = client.post(
            "/api/jobs",
            json={
                "project_ids": [project["id"]],
                "brief": "Make a useful clip",
                "formats": [{"ratio": "9:16", "min": 8, "max": 12}],
            },
        )
        assert job_response.status_code == 200
        assert job_response.json()["status"] == "queued"
        assert len(client.get("/api/jobs").json()) == 1
        duplicate_formats = client.post(
            "/api/jobs",
            json={
                "project_ids": [project["id"]],
                "brief": "Duplicate formats",
                "formats": [
                    {"ratio": "9:16", "min": 8, "max": 12},
                    {"ratio": "9:16", "min": 20, "max": 30},
                ],
            },
        )
        assert duplicate_formats.status_code == 422
        clean_style = client.post(
            "/api/jobs",
            json={
                "project_ids": [project["id"]],
                "brief": "Unsupported style",
                "formats": [{"ratio": "9:16", "min": 8, "max": 12}],
                "options": {"story_style": "clean"},
            },
        )
        assert clean_style.status_code == 422
        missing = client.post(
            "/api/jobs",
            json={
                "project_ids": ["missing"],
                "brief": "Nope",
                "formats": [{"ratio": "9:16", "min": 8, "max": 12}],
            },
        )
        assert missing.status_code == 404


def test_catalog_results_creates_assets_and_renders(tmp_path):
    settings = _settings(tmp_path)
    conn = db.connect(settings.db_path)
    db.init_schema(conn)
    job = db.create_job(
        settings.db_path,
        brief="brief",
        formats=[{"ratio": "9:16", "min": 8, "max": 12}],
        clips=1,
        options={},
        project_ids=["p1", "p2"],
    )
    storage = LocalStorage(settings.storage_root)
    catalog_results(conn, storage, job, _fake_results(tmp_path))
    conn.close()
    assets = db.list_assets(settings.db_path)
    assert len(assets) == 2
    assert len(assets[0]["renders"]) == 1
    assert assets[0]["project_ids"] == ["p1"]
    for asset in assets:
        render = asset["renders"][0]
        assert os.path.isfile(storage.path(render["file_key"]))
        assert render["duration"] == 8


def test_asset_patch_api(tmp_path):
    settings = _settings(tmp_path)
    job = db.create_job(
        settings.db_path,
        brief="brief",
        formats=[{"ratio": "9:16", "min": 8, "max": 12}],
        clips=1,
        options={},
        project_ids=[],
    )
    db.create_asset(
        settings.db_path,
        job_id=job["id"],
        project_ids=[],
        clip_id=1,
        title="Clip",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        asset = client.get("/api/assets").json()[0]
        response = client.patch(
            f"/api/assets/{asset['id']}",
            json={"state": "ready", "favorite": True},
        )
        assert response.status_code == 200
        assert response.json()["state"] == "ready"
        assert response.json()["favorite"] is True


def test_worker_success_and_failure(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    project = db.create_project(
        settings.db_path,
        name="Project",
        platform="local",
        local_path="/tmp/source.mp4",
    )
    job = db.create_job(
        settings.db_path,
        brief="brief",
        formats=[{"ratio": "9:16", "min": 8, "max": 12}],
        clips=1,
        options={},
        project_ids=[project["id"]],
    )
    output = tmp_path / "render.mp4"
    output.write_bytes(b"video")

    monkeypatch.setattr(
        "service.worker.build_config",
        lambda argv: SimpleNamespace(
            outputs_dir=str(tmp_path / "job-output"),
            story_cache_dir=None,
        ),
    )

    def successful_run(cfg, on_stage=None):
        for stage, ratio in (
            ("transcribe", ""),
            ("direct", "9:16"),
            ("render", "9:16"),
        ):
            on_stage(stage, ratio)
        return [
            {
                "format": "9:16",
                "slug": "9x16",
                "recipe": {"clips": [_recipe_clip()]},
                "render": [{"clip_id": 1, "final_path": str(output)}],
            }
        ]

    monkeypatch.setattr("service.worker.director.run_director", successful_run)
    worker = Worker(settings, LocalStorage(settings.storage_root))
    worker.run_job(job)
    done = db.get_job(settings.db_path, job["id"])
    assert done["status"] == "done"
    assert done["percent"] == 100
    assert {event["stage"] for event in db.list_events(settings.db_path, job["id"])} >= {
        "transcribe",
        "direct:9:16",
        "render:9:16",
        "catalog",
    }

    failed_job = db.create_job(
        settings.db_path,
        brief="failed",
        formats=[{"ratio": "9:16", "min": 8, "max": 12}],
        clips=1,
        options={},
        project_ids=[project["id"]],
    )
    monkeypatch.setattr(
        "service.worker.director.run_director",
        lambda cfg, on_stage=None: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    worker.run_job(failed_job)
    failed = db.get_job(settings.db_path, failed_job["id"])
    assert failed["status"] == "failed"
    assert failed["error"] == "boom"


def test_worker_progress_is_monotonic_for_two_formats(tmp_path):
    settings = _settings(tmp_path)
    job = db.create_job(
        settings.db_path,
        brief="brief",
        formats=[
            {"ratio": "9:16", "min": 8, "max": 12},
            {"ratio": "16:9", "min": 20, "max": 30},
        ],
        clips=1,
        options={},
        project_ids=[],
    )
    worker = Worker(settings)
    callback = worker._stage_callback(job)
    percentages = []
    for stage, ratio in (
        ("transcribe", ""),
        ("direct", "9:16"),
        ("render", "9:16"),
        ("direct", "16:9"),
        ("render", "16:9"),
    ):
        callback(stage, ratio)
        percentages.append(db.get_job(settings.db_path, job["id"])["percent"])
    assert percentages == [10, 10, 30, 50, 70]
    assert percentages == sorted(percentages)


def test_requeue_running_jobs(tmp_path):
    settings = _settings(tmp_path)
    job = db.create_job(
        settings.db_path,
        brief="orphaned",
        formats=[{"ratio": "9:16", "min": 8, "max": 12}],
        clips=1,
        options={},
        project_ids=[],
        status="running",
        stage="render:9:16",
        percent=70,
    )
    assert db.requeue_running(settings.db_path) == [job["id"]]
    requeued = db.get_job(settings.db_path, job["id"])
    assert requeued["status"] == "queued"
    assert requeued["stage"] == "queued"
    assert requeued["percent"] == 0
    assert db.list_events(settings.db_path, job["id"])[0]["message"] == (
        "requeued after restart"
    )
