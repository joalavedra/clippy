"""SQLite persistence for the Clippy service layer."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id() -> str:
    return uuid.uuid4().hex


def connect(path: str) -> sqlite3.Connection:
    """Open a configured SQLite connection."""
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            platform TEXT NOT NULL,
            url TEXT,
            local_path TEXT,
            layout TEXT NOT NULL DEFAULT 'single',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            brief TEXT NOT NULL,
            formats TEXT NOT NULL,
            clips INTEGER NOT NULL,
            options TEXT NOT NULL,
            project_ids TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            stage TEXT NOT NULL DEFAULT 'prepare',
            percent REAL NOT NULL DEFAULT 0,
            error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS job_events (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
            ts TEXT NOT NULL,
            stage TEXT NOT NULL,
            message TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS assets (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
            project_ids TEXT NOT NULL,
            clip_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            hook_line TEXT NOT NULL,
            rationale TEXT NOT NULL,
            viral_score INTEGER NOT NULL,
            hashtags TEXT NOT NULL,
            metadata TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'not_planned',
            favorite INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS renders (
            id TEXT PRIMARY KEY,
            asset_id TEXT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
            ratio TEXT NOT NULL,
            duration REAL NOT NULL,
            file_key TEXT NOT NULL,
            thumb_key TEXT,
            recipe_clip TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_jobs_status_created
            ON jobs(status, created_at);
        CREATE INDEX IF NOT EXISTS idx_events_job_ts
            ON job_events(job_id, ts);
        CREATE INDEX IF NOT EXISTS idx_assets_job
            ON assets(job_id);
        """
    )
    conn.commit()


@contextmanager
def _opened(path: str) -> Iterator[sqlite3.Connection]:
    conn = connect(path)
    try:
        init_schema(conn)
        yield conn
    finally:
        conn.close()


def _json_load(value: str, default: Any) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _project(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row else None


def _job(row: sqlite3.Row | None) -> dict | None:
    if not row:
        return None
    result = dict(row)
    result["formats"] = _json_load(result["formats"], [])
    result["options"] = _json_load(result["options"], {})
    result["project_ids"] = _json_load(result["project_ids"], [])
    return result


def _event(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row else None


def _asset(row: sqlite3.Row | None) -> dict | None:
    if not row:
        return None
    result = dict(row)
    result["project_ids"] = _json_load(result["project_ids"], [])
    result["hashtags"] = _json_load(result["hashtags"], [])
    result["metadata"] = _json_load(result["metadata"], {})
    result["favorite"] = bool(result["favorite"])
    result["renders"] = []
    return result


def _render(row: sqlite3.Row | None) -> dict | None:
    if not row:
        return None
    result = dict(row)
    result["recipe_clip"] = _json_load(result["recipe_clip"], {})
    return result


def create_project(db_path: str, **fields: Any) -> dict:
    project = {
        "id": fields.get("id", _id()),
        "name": fields["name"],
        "platform": fields["platform"],
        "url": fields.get("url"),
        "local_path": fields.get("local_path"),
        "layout": fields.get("layout", "single"),
        "created_at": fields.get("created_at", _now()),
    }
    with _opened(db_path) as conn:
        conn.execute(
            """
            INSERT INTO projects
                (id, name, platform, url, local_path, layout, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            tuple(project.values()),
        )
        conn.commit()
    return project


def list_projects(db_path: str) -> list[dict]:
    with _opened(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM projects ORDER BY created_at, id"
        ).fetchall()
    return [_project(row) for row in rows]


def get_project(db_path: str, project_id: str) -> dict | None:
    with _opened(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
    return _project(row)


def create_job(db_path: str, **fields: Any) -> dict:
    now = _now()
    job = {
        "id": fields.get("id", _id()),
        "brief": fields["brief"],
        "formats": fields["formats"],
        "clips": fields["clips"],
        "options": fields.get("options", {}),
        "project_ids": fields["project_ids"],
        "status": fields.get("status", "queued"),
        "stage": fields.get("stage", "prepare"),
        "percent": fields.get("percent", 0),
        "error": fields.get("error"),
        "created_at": fields.get("created_at", now),
        "updated_at": fields.get("updated_at", now),
    }
    with _opened(db_path) as conn:
        conn.execute(
            """
            INSERT INTO jobs
                (id, brief, formats, clips, options, project_ids, status,
                 stage, percent, error, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job["id"],
                job["brief"],
                json.dumps(job["formats"]),
                job["clips"],
                json.dumps(job["options"]),
                json.dumps(job["project_ids"]),
                job["status"],
                job["stage"],
                job["percent"],
                job["error"],
                job["created_at"],
                job["updated_at"],
            ),
        )
        conn.commit()
    return job


def list_jobs(db_path: str) -> list[dict]:
    with _opened(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC, id DESC"
        ).fetchall()
    return [_job(row) for row in rows]


def get_job(db_path: str, job_id: str) -> dict | None:
    with _opened(db_path) as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _job(row)


def claim_next_queued(conn: sqlite3.Connection) -> dict | None:
    """Atomically claim the oldest queued job."""
    init_schema(conn)
    conn.execute("BEGIN IMMEDIATE")
    row = conn.execute(
        "SELECT * FROM jobs WHERE status = 'queued' "
        "ORDER BY created_at, id LIMIT 1"
    ).fetchone()
    if not row:
        conn.commit()
        return None
    now = _now()
    conn.execute(
        "UPDATE jobs SET status='running', stage='prepare', percent=0, "
        "error=NULL, updated_at=? WHERE id=? AND status='queued'",
        (now, row["id"]),
    )
    conn.commit()
    claimed = dict(row)
    claimed.update(
        {"status": "running", "stage": "prepare", "percent": 0, "error": None, "updated_at": now}
    )
    claimed["formats"] = _json_load(claimed["formats"], [])
    claimed["options"] = _json_load(claimed["options"], {})
    claimed["project_ids"] = _json_load(claimed["project_ids"], [])
    return claimed


def requeue_running(db_path: str) -> list[str]:
    """Requeue jobs left running by a previous worker process."""
    with _opened(db_path) as conn:
        rows = conn.execute(
            "SELECT id FROM jobs WHERE status = 'running' ORDER BY created_at, id"
        ).fetchall()
        if not rows:
            return []
        now = _now()
        conn.execute(
            "UPDATE jobs SET status='queued', stage='queued', percent=0, "
            "updated_at=? WHERE status='running'",
            (now,),
        )
        for row in rows:
            conn.execute(
                "INSERT INTO job_events (id, job_id, ts, stage, message) "
                "VALUES (?, ?, ?, ?, ?)",
                (_id(), row["id"], now, "queued", "requeued after restart"),
            )
        conn.commit()
    return [row["id"] for row in rows]


def update_job(db_path: str, job_id: str, **fields: Any) -> dict | None:
    allowed = {
        "status",
        "stage",
        "percent",
        "error",
        "brief",
        "formats",
        "clips",
        "options",
        "project_ids",
    }
    updates = {key: value for key, value in fields.items() if key in allowed}
    if not updates:
        return get_job(db_path, job_id)
    encoded = {}
    for key, value in updates.items():
        encoded[key] = (
            json.dumps(value)
            if key in {"formats", "options", "project_ids"}
            else value
        )
    encoded["updated_at"] = _now()
    assignments = ", ".join(f"{key} = ?" for key in encoded)
    with _opened(db_path) as conn:
        conn.execute(
            f"UPDATE jobs SET {assignments} WHERE id = ?",
            (*encoded.values(), job_id),
        )
        conn.commit()
    return get_job(db_path, job_id)


def add_event(db_path: str, job_id: str, stage: str, message: str) -> dict:
    event = {
        "id": _id(),
        "job_id": job_id,
        "ts": _now(),
        "stage": stage,
        "message": message,
    }
    with _opened(db_path) as conn:
        conn.execute(
            "INSERT INTO job_events (id, job_id, ts, stage, message) "
            "VALUES (?, ?, ?, ?, ?)",
            tuple(event.values()),
        )
        conn.commit()
    return event


def list_events(db_path: str, job_id: str) -> list[dict]:
    with _opened(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM job_events WHERE job_id = ? ORDER BY ts, id",
            (job_id,),
        ).fetchall()
    return [_event(row) for row in rows]


def create_asset(db_path: str, **fields: Any) -> dict:
    asset = {
        "id": fields.get("id", _id()),
        "job_id": fields["job_id"],
        "project_ids": fields.get("project_ids", []),
        "clip_id": fields["clip_id"],
        "title": fields.get("title", ""),
        "hook_line": fields.get("hook_line", ""),
        "rationale": fields.get("rationale", ""),
        "viral_score": fields.get("viral_score", 0),
        "hashtags": fields.get("hashtags", []),
        "metadata": fields.get("metadata", {}),
        "state": fields.get("state", "not_planned"),
        "favorite": fields.get("favorite", False),
        "created_at": fields.get("created_at", _now()),
    }
    with _opened(db_path) as conn:
        _create_asset_conn(conn, asset)
        conn.commit()
    return get_asset(db_path, asset["id"])


def _create_asset_conn(conn: sqlite3.Connection, asset: dict) -> None:
    conn.execute(
        """
        INSERT INTO assets
            (id, job_id, project_ids, clip_id, title, hook_line, rationale,
             viral_score, hashtags, metadata, state, favorite, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            asset["id"],
            asset["job_id"],
            json.dumps(asset["project_ids"]),
            asset["clip_id"],
            asset["title"],
            asset["hook_line"],
            asset["rationale"],
            asset["viral_score"],
            json.dumps(asset["hashtags"]),
            json.dumps(asset["metadata"]),
            asset["state"],
            int(asset["favorite"]),
            asset["created_at"],
        ),
    )


def create_render(db_path: str, **fields: Any) -> dict:
    render = {
        "id": fields.get("id", _id()),
        "asset_id": fields["asset_id"],
        "ratio": fields["ratio"],
        "duration": fields["duration"],
        "file_key": fields["file_key"],
        "thumb_key": fields.get("thumb_key"),
        "recipe_clip": fields.get("recipe_clip", {}),
    }
    with _opened(db_path) as conn:
        _create_render_conn(conn, render)
        conn.commit()
    return render


def _create_render_conn(conn: sqlite3.Connection, render: dict) -> None:
    conn.execute(
        """
        INSERT INTO renders
            (id, asset_id, ratio, duration, file_key, thumb_key, recipe_clip)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            render["id"],
            render["asset_id"],
            render["ratio"],
            render["duration"],
            render["file_key"],
            render["thumb_key"],
            json.dumps(render["recipe_clip"]),
        ),
    )


def _attach_renders(conn: sqlite3.Connection, asset: dict) -> dict:
    rows = conn.execute(
        "SELECT * FROM renders WHERE asset_id = ? ORDER BY id",
        (asset["id"],),
    ).fetchall()
    asset["renders"] = [_render(row) for row in rows]
    return asset


def list_assets(db_path: str, filters: dict | None = None, **kwargs: Any) -> list[dict]:
    filters = {**(filters or {}), **kwargs}
    clauses = []
    params: list[Any] = []
    for key in ("job_id", "state"):
        if filters.get(key) is not None:
            clauses.append(f"a.{key} = ?")
            params.append(filters[key])
    if filters.get("favorite") is not None:
        clauses.append("a.favorite = ?")
        params.append(int(filters["favorite"]))
    if filters.get("min_score") is not None:
        clauses.append("a.viral_score >= ?")
        params.append(filters["min_score"])
    if filters.get("ratio") is not None:
        clauses.append(
            "EXISTS (SELECT 1 FROM renders rf WHERE rf.asset_id=a.id AND rf.ratio=?)"
        )
        params.append(filters["ratio"])
    with _opened(db_path) as conn:
        query = "SELECT a.* FROM assets a"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY a.created_at DESC, a.id DESC"
        rows = conn.execute(query, params).fetchall()
        assets = [_asset(row) for row in rows]
        if filters.get("project_id") is not None:
            project_id = filters["project_id"]
            assets = [
                asset
                for asset in assets
                if project_id in asset["project_ids"]
            ]
        return [_attach_renders(conn, asset) for asset in assets]


def get_asset(db_path: str, asset_id: str) -> dict | None:
    with _opened(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM assets WHERE id = ?", (asset_id,)
        ).fetchone()
        asset = _asset(row)
        return _attach_renders(conn, asset) if asset else None


def update_asset(
    db_path: str,
    asset_id: str,
    state: str | None = None,
    favorite: bool | None = None,
) -> dict | None:
    updates = {}
    if state is not None:
        updates["state"] = state
    if favorite is not None:
        updates["favorite"] = int(favorite)
    if not updates:
        return get_asset(db_path, asset_id)
    assignments = ", ".join(f"{key} = ?" for key in updates)
    with _opened(db_path) as conn:
        conn.execute(
            f"UPDATE assets SET {assignments} WHERE id = ?",
            (*updates.values(), asset_id),
        )
        conn.commit()
    return get_asset(db_path, asset_id)


def count_jobs(db_path: str, status: str | None = None) -> int:
    with _opened(db_path) as conn:
        if status:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM jobs WHERE status = ?", (status,)
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) AS count FROM jobs").fetchone()
    return int(row["count"])
