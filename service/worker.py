"""Background worker that runs the existing Director CLI pipeline."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import traceback
from pathlib import Path
from typing import Any

from clipping.config import build_config
from clipping import director

from . import db
from .settings import Settings
from .storage import LocalStorage, Storage

LOGGER = logging.getLogger(__name__)


def _extract_thumbnail(video_path: str, out_path: str) -> str | None:
    try:
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                video_path,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        duration = float(probe.stdout.strip())
        seek = min(1.0, max(0.0, duration / 2))
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                str(seek),
                "-i",
                video_path,
                "-frames:v",
                "1",
                "-q:v",
                "3",
                out_path,
            ],
            check=False,
            capture_output=True,
        )
    except (OSError, ValueError) as exc:
        LOGGER.warning("Could not extract thumbnail for %s: %s", video_path, exc)
        return None
    if result.returncode != 0 or not os.path.isfile(out_path):
        LOGGER.warning(
            "Could not extract thumbnail for %s: %s",
            video_path,
            result.stderr.decode(errors="replace"),
        )
        return None
    return out_path


def _without_scenes(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_scenes(item)
            for key, item in value.items()
            if key != "scenes"
        }
    if isinstance(value, list):
        return [_without_scenes(item) for item in value]
    return value


def _job_value(job: dict, key: str, default=None):
    value = job.get(key, default)
    if isinstance(value, str) and key in {"formats", "options", "project_ids"}:
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value


def catalog_results(conn, storage: Storage, job: dict, results: list[dict]) -> list[dict]:
    """Copy render outputs and create asset/render rows for Director results."""
    job_id = job["id"]
    cataloged = []
    for result in results:
        ratio = result["format"]
        slug = result.get("slug", ratio.replace(":", "x"))
        recipe = result.get("recipe", {})
        render_manifest = result.get("render") or []
        manifests = {
            item.get("clip_id"): item
            for item in render_manifest
            if item.get("clip_id") is not None
        }
        for clip in recipe.get("clips", []):
            clip_id = clip["clip_id"]
            manifest = manifests.get(clip_id, {})
            source_path = manifest.get("final_path") or manifest.get("highlight_path")
            if not source_path or not os.path.exists(source_path):
                raise FileNotFoundError(
                    f"Rendered output not found for {ratio} clip {clip_id}: "
                    f"{source_path}"
                )
            file_key = f"{job_id}/{slug}/clip_{clip_id}.mp4"
            storage.put(source_path, file_key)
            thumb_path = manifest.get("thumbnail_path")
            if not thumb_path or not os.path.exists(thumb_path):
                outputs_dir = Path(source_path).parent
                if result.get("recipe_path"):
                    outputs_dir = Path(result["recipe_path"]).parent
                candidate = outputs_dir / f"thumbnail_{clip_id}.jpg"
                thumb_path = (
                    str(candidate)
                    if candidate.exists()
                    else _extract_thumbnail(source_path, str(candidate))
                )
            thumb_key = None
            if thumb_path and os.path.exists(thumb_path):
                thumb_key = f"{job_id}/{slug}/thumbnail_{clip_id}.jpg"
                storage.put(thumb_path, thumb_key)

            scenes = (
                clip.get("hook", {}).get("scenes", [])
                + clip.get("highlight", {}).get("scenes", [])
            )
            project_ids = sorted(
                {scene["source_id"] for scene in scenes if scene.get("source_id")}
            )
            duration = sum(
                float(scene["end"]) - float(scene["start"]) for scene in scenes
            )
            metadata = _without_scenes(clip)
            asset = {
                "id": db._id(),
                "job_id": job_id,
                "project_ids": project_ids,
                "clip_id": clip_id,
                "title": clip.get("title", ""),
                "hook_line": clip.get("hook", {}).get("text", ""),
                "rationale": clip.get("rationale", ""),
                "viral_score": clip.get("viral_score", 0),
                "hashtags": clip.get("metadata", {}).get("hashtags", []),
                "metadata": metadata,
                "state": "not_planned",
                "favorite": False,
                "created_at": db._now(),
            }
            db._create_asset_conn(conn, asset)
            render = {
                "id": db._id(),
                "asset_id": asset["id"],
                "ratio": ratio,
                "duration": duration,
                "file_key": file_key,
                "thumb_key": thumb_key,
                "recipe_clip": clip,
            }
            db._create_render_conn(conn, render)
            asset["renders"] = [render]
            cataloged.append(asset)
    conn.commit()
    return cataloged


class Worker(threading.Thread):
    def __init__(
        self,
        settings: Settings,
        storage: Storage | None = None,
    ):
        super().__init__(daemon=True, name="clippy-worker")
        self.settings = settings
        self.storage = storage
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def _stage_callback(self, job: dict):
        formats = _job_value(job, "formats", [])
        ratios = [item["ratio"] for item in formats]
        last_percent = 0

        def on_stage(stage: str, ratio: str):
            nonlocal last_percent
            if stage == "transcribe":
                percent = 10
                label = "transcribe"
            else:
                index = ratios.index(ratio) if ratio in ratios else 0
                count = max(1, len(ratios))
                if stage == "direct":
                    percent = int(10 + 80 * (2 * index) / (2 * count))
                else:
                    percent = int(10 + 80 * (2 * index + 1) / (2 * count))
                label = f"{stage}:{ratio}"
            percent = max(last_percent, percent)
            last_percent = percent
            db.update_job(
                self.settings.db_path,
                job["id"],
                stage=label,
                percent=percent,
            )
            db.add_event(self.settings.db_path, job["id"], label, "")

        return on_stage

    def run_job(self, job: dict) -> None:
        job_id = job["id"]
        try:
            db.update_job(
                self.settings.db_path,
                job_id,
                status="running",
                stage="prepare",
                percent=0,
                error=None,
            )
            projects = [
                db.get_project(self.settings.db_path, project_id)
                for project_id in _job_value(job, "project_ids", [])
            ]
            if any(project is None for project in projects):
                raise ValueError("Job references an unknown project.")
            job_dir = os.path.join(self.settings.work_dir, job_id)
            output_dir = os.path.join(job_dir, "outputs")
            os.makedirs(output_dir, exist_ok=True)
            sources = []
            for project in projects:
                source = {
                    "id": project["id"],
                    "name": project["name"],
                    "platform": project["platform"],
                    "layout": project["layout"],
                }
                source["url" if project["url"] else "local_path"] = (
                    project["url"] or project["local_path"]
                )
                sources.append(source)
            sources_path = os.path.join(job_dir, "sources.json")
            with open(sources_path, "w", encoding="utf-8") as handle:
                json.dump({"sources": sources}, handle, indent=2)
            db.add_event(self.settings.db_path, job_id, "prepare", sources_path)

            options = _job_value(job, "options", {})
            format_specs = _job_value(job, "formats", [])
            formats = ",".join(
                f"{item['ratio']}/{item['min']}-{item['max']}"
                for item in format_specs
            )
            project_name = options.get("project_name") or f"job_{job_id[:8]}"
            argv = [
                "--director",
                "--sources-json",
                sources_path,
                "--brief",
                job["brief"],
                "--formats",
                formats,
                "--clips",
                str(job["clips"]),
                "--output-dir",
                output_dir,
                "--director-recipe-out",
                os.path.join(output_dir, "director_recipe.json"),
                "--whisper-model",
                options.get("whisper_model", "small"),
                "--whisper-device",
                options.get("whisper_device", "cpu"),
                "--whisper-compute-type",
                options.get("whisper_compute_type", "int8"),
                "--story-style",
                options.get("story_style", "styled"),
                "--gemini-timeout",
                str(options.get("gemini_timeout", 180)),
                "--project-name",
                project_name,
            ]
            cfg = build_config(argv)
            cfg.story_cache_dir = self.settings.cache_dir
            results = director.run_director(
                cfg,
                on_stage=self._stage_callback(job),
            )
            if not isinstance(results, list):
                results = [results]
            storage = self.storage or LocalStorage(self.settings.storage_root)
            db.update_job(
                self.settings.db_path,
                job_id,
                stage="catalog",
                percent=90,
            )
            db.add_event(self.settings.db_path, job_id, "catalog", "")
            conn = db.connect(self.settings.db_path)
            try:
                catalog_results(conn, storage, job, results)
            finally:
                conn.close()
            db.update_job(
                self.settings.db_path,
                job_id,
                status="done",
                stage="catalog",
                percent=100,
                error=None,
            )
        except Exception as exc:
            error = str(exc)
            LOGGER.error("Job %s failed:\n%s", job_id, traceback.format_exc())
            db.update_job(
                self.settings.db_path,
                job_id,
                status="failed",
                stage="failed",
                error=error,
            )
            db.add_event(self.settings.db_path, job_id, "failed", error)

    def run(self) -> None:
        db.requeue_running(self.settings.db_path)
        while not self._stop_event.is_set():
            conn = db.connect(self.settings.db_path)
            try:
                job = db.claim_next_queued(conn)
            finally:
                conn.close()
            if job:
                self.run_job(job)
            else:
                self._stop_event.wait(2)
