from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from service import db
from service.app import create_app
from service.media_tokens import sign_media_token
from service.settings import Settings
from service.storage import LocalStorage
from service.worker import Worker, catalog_results
from clipping.ingest_errors import DownloadError


def _settings(tmp_path):
    return Settings(
        data_dir=str(tmp_path / "data"),
        worker_enabled=False,
        api_key="test",
        local_media_roots=[str(tmp_path / "uploads")],
    )


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
    media_path = Path(settings.local_media_roots[0]) / "demo.mp4"
    media_path.write_bytes(b"video")
    app = create_app(settings)
    with TestClient(app) as client:
        client.headers.update({"X-API-Key": "test"})
        response = client.post(
            "/api/projects",
            json={
                "name": "Local demo",
                "platform": "local",
                "local_path": str(media_path),
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


def test_search_api_requires_auth_and_reindexes_cache(tmp_path):
    settings = _settings(tmp_path)
    project = db.create_project(
        settings.db_path,
        id="search-project",
        name="Search Project",
        platform="local",
    )
    transcript = {
        "source_id": project["id"],
        "segmen": [
            {
                "start": 0,
                "end": 4,
                "words": [
                    {"word": "human", "start": 0, "end": 1},
                    {"word": "voice", "start": 1, "end": 2},
                ],
            }
        ],
    }
    Path(settings.cache_dir, f"{project['id']}_transcript.json").write_text(
        json.dumps(transcript),
        encoding="utf-8",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.get("/api/search?q=voice").status_code == 401
        client.headers.update({"X-API-Key": "test"})
        assert client.get("/api/search?q=voice").status_code == 200
        response = client.post("/api/search/reindex")
        assert response.status_code == 200
        assert response.json()["indexed"][project["id"]] == 1
        result = client.get("/api/search?q=human").json()
        assert result["results"][0]["project_name"] == "Search Project"


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


def test_catalog_results_puts_variant_render_on_same_asset(tmp_path):
    settings = _settings(tmp_path)
    conn = db.connect(settings.db_path)
    db.init_schema(conn)
    job = db.create_job(
        settings.db_path,
        brief="brief",
        formats=[{
            "ratio": "9:16",
            "min": 8,
            "max": 12,
            "variants": ["16:9"],
        }],
        clips=1,
        options={},
        project_ids=["p1"],
    )
    primary = tmp_path / "primary.mp4"
    variant = tmp_path / "variant.mp4"
    primary.write_bytes(b"primary")
    variant.write_bytes(b"variant")
    result = _recipe_clip()
    catalog_results(
        conn,
        LocalStorage(settings.storage_root),
        job,
        [{
            "format": "9:16",
            "slug": "9x16",
            "recipe": {"clips": [result]},
            "render": [{"clip_id": 1, "final_path": str(primary)}],
            "variants": [{
                "format": "16:9",
                "slug": "9x16_16x9",
                "render": [{"clip_id": 1, "final_path": str(variant)}],
            }],
        }],
    )
    conn.close()
    assets = db.list_assets(settings.db_path)
    assert len(assets) == 1
    assert [render["ratio"] for render in assets[0]["renders"]] == ["9:16", "16:9"]
    assert assets[0]["renders"][1]["file_key"].endswith(
        "9x16_16x9/clip_1.mp4"
    )


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
        client.headers.update({"X-API-Key": "test"})
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
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is required for thumbnail extraction")
    output = tmp_path / "render.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=64x64:d=1",
            "-pix_fmt",
            "yuv420p",
            str(output),
        ],
        check=True,
        capture_output=True,
    )

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
    assets = db.list_assets(settings.db_path)
    assert assets[0]["renders"][0]["thumb_key"]
    assert Path(
        LocalStorage(settings.storage_root).path(assets[0]["renders"][0]["thumb_key"])
    ).is_file()

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


def test_worker_progress_accounts_for_variant_render(tmp_path):
    settings = _settings(tmp_path)
    job = db.create_job(
        settings.db_path,
        brief="brief",
        formats=[{
            "ratio": "9:16",
            "min": 8,
            "max": 12,
            "variants": ["16:9"],
        }],
        clips=1,
        options={},
        project_ids=[],
    )
    callback = Worker(settings)._stage_callback(job)
    percentages = []
    for stage, ratio in (
        ("transcribe", ""),
        ("direct", "9:16"),
        ("render", "9:16"),
        ("render", "9:16>16:9"),
    ):
        callback(stage, ratio)
        percentages.append(db.get_job(settings.db_path, job["id"])["percent"])
    assert percentages == sorted(percentages)
    assert percentages[-1] > percentages[-2]


def test_worker_reports_classified_download_failure(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    project = db.create_project(
        settings.db_path,
        name="Remote project",
        platform="youtube",
        url="https://www.youtube.com/watch?v=video",
    )
    job = db.create_job(
        settings.db_path,
        brief="brief",
        formats=[{"ratio": "9:16", "min": 8, "max": 12}],
        clips=1,
        options={},
        project_ids=[project["id"]],
    )
    monkeypatch.setattr(
        "service.worker.build_config",
        lambda argv: SimpleNamespace(
            outputs_dir=str(tmp_path / "job-output"),
            story_cache_dir=None,
        ),
    )

    def failed_run(cfg, on_stage=None):
        raise DownloadError(
            "bot_check",
            source_id="src1",
            detail="Sign in to confirm you're not a bot",
        )

    monkeypatch.setattr("service.worker.director.run_director", failed_run)
    Worker(settings).run_job(job)

    failed = db.get_job(settings.db_path, job["id"])
    assert failed["status"] == "failed"
    assert "bot check" in failed["error"].lower()
    assert "CLIPPY_YTDLP_COOKIES" in failed["error"]
    assert any(
        event["stage"] == "download_failed"
        for event in db.list_events(settings.db_path, job["id"])
    )


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


def test_api_key_and_protected_files(tmp_path):
    settings = _settings(tmp_path)
    assert settings.media_secret != "test"
    protected = Path(settings.storage_root) / "hello.txt"
    protected.write_text("hello", encoding="utf-8")
    job = db.create_job(
        settings.db_path,
        brief="brief",
        formats=[{"ratio": "9:16", "min": 8, "max": 12}],
        clips=1,
        options={},
        project_ids=[],
    )
    asset = db.create_asset(
        settings.db_path,
        job_id=job["id"],
        project_ids=[],
        clip_id=1,
        title="Clip",
    )
    db.create_render(
        settings.db_path,
        asset_id=asset["id"],
        ratio="9:16",
        duration=1,
        file_key="hello.txt",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.get("/api/projects").status_code == 401
        assert client.get("/api/health").status_code == 200
        assert client.get("/files/hello.txt").status_code == 401
        assert client.get("/api/assets?api_key=test").status_code == 401
        client.headers.update({"X-API-Key": "test"})
        assert client.get("/api/projects").status_code == 200
        assert client.get("/files/hello.txt").status_code == 200
        client.headers.pop("X-API-Key")
        assert client.get("/files/hello.txt?api_key=test").status_code == 401
        client.headers.update({"X-API-Key": "test"})
        media_url = client.get("/api/assets").json()[0]["renders"][0]["url"]
        client.headers.pop("X-API-Key")
        assert client.get(media_url).status_code == 200
        token = media_url.partition("?token=")[2]
        wrong_key = sign_media_token("test", "other.txt", 2_000_000_000)
        expired = sign_media_token("test", "hello.txt", 1)
        tampered = f"{token[:-1]}{'0' if token[-1] != '0' else '1'}"
        assert client.get(f"/files/hello.txt?token={wrong_key}").status_code == 401
        assert client.get(f"/files/hello.txt?token={expired}").status_code == 401
        assert client.get(f"/files/hello.txt?token={tampered}").status_code == 401
        assert client.get("/files/../clippy.db").status_code == 404


def test_media_secret_derivation_and_ttl_cap(tmp_path, monkeypatch):
    monkeypatch.delenv("CLIPPY_MEDIA_SECRET", raising=False)
    monkeypatch.setenv("CLIPPY_MEDIA_TOKEN_TTL", "999999999")
    settings = Settings(
        data_dir=str(tmp_path / "data"),
        worker_enabled=False,
        api_key="x",
        local_media_roots=[str(tmp_path / "uploads")],
    )
    assert settings.media_secret != "x"
    assert settings.media_token_ttl == 86400


def test_local_path_roots_and_url_policy(tmp_path):
    settings = _settings(tmp_path)
    inside = Path(settings.local_media_roots[0]) / "inside.mp4"
    inside.write_bytes(b"video")
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"video")
    app = create_app(settings)
    with TestClient(app) as client:
        client.headers.update({"X-API-Key": "test"})
        outside_response = client.post(
            "/api/projects",
            json={
                "name": "Outside",
                "platform": "local",
                "local_path": str(outside),
            },
        )
        assert outside_response.status_code == 422
        inside_response = client.post(
            "/api/projects",
            json={
                "name": "Inside",
                "platform": "local",
                "local_path": str(inside),
            },
        )
        assert inside_response.status_code == 200
        assert inside_response.json()["local_path"] == os.path.realpath(inside)
        for url in ("https://evil.example/video", "http://127.0.0.1/video"):
            response = client.post(
                "/api/projects",
                json={"name": "Bad URL", "platform": "youtube", "url": url},
            )
            assert response.status_code == 422
        allowed = client.post(
            "/api/projects",
            json={
                "name": "YouTube",
                "platform": "youtube",
                "url": "https://youtu.be/example",
            },
        )
        assert allowed.status_code == 200
