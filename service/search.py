"""Transcript indexing and lexical/semantic footage search."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Protocol

import numpy as np

from . import db

LOGGER = logging.getLogger(__name__)


class Embedder(Protocol):
    def embed(self, texts: list[str], task: str) -> list[list[float]]:
        ...


def build_windows(
    segmen: list[dict],
    target_seconds: float = 10.0,
    max_words: int = 40,
) -> list[dict]:
    """Greedily combine transcript segments into searchable windows."""
    windows: list[dict] = []
    current: list[dict] = []
    current_words = 0

    def flush() -> None:
        nonlocal current, current_words
        if not current:
            return
        words: list[str] = []
        for segment in current:
            segment_words = segment.get("words") or []
            if segment_words:
                words.extend(
                    str(word.get("word", "")).strip()
                    for word in segment_words
                    if str(word.get("word", "")).strip()
                )
            elif segment.get("text"):
                words.extend(str(segment["text"]).split())
        text = " ".join(words).strip()
        if text:
            windows.append(
                {
                    "start": float(current[0].get("start", 0.0)),
                    "end": float(current[-1].get("end", current[0].get("start", 0.0))),
                    "text": text,
                }
            )
        current = []
        current_words = 0

    for segment in segmen:
        current.append(segment)
        segment_words = segment.get("words") or []
        current_words += len(segment_words) if segment_words else len(
            str(segment.get("text", "")).split()
        )
        start = float(current[0].get("start", 0.0))
        end = float(segment.get("end", start))
        if end - start >= target_seconds or current_words >= max_words:
            flush()
    flush()
    return windows


class GeminiEmbedder:
    """Gemini embedding adapter with the service's Embedder protocol."""

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-embedding-001",
        dim: int = 256,
    ):
        from google.genai import Client

        self.client = Client(api_key=api_key)
        self.model = model
        self.dim = dim

    def embed(self, texts: list[str], task: str) -> list[list[float]]:
        from google.genai import types

        response = self.client.models.embed_content(
            model=self.model,
            contents=texts,
            config=types.EmbedContentConfig(
                task_type=task,
                output_dimensionality=self.dim,
            ),
        )
        return [
            list(embedding.values)
            for embedding in (response.embeddings or [])
        ]


def make_embedder(settings) -> Embedder | None:
    enabled = os.environ.get("CLIPPY_SEARCH_EMBEDDINGS", "1").strip().lower()
    if enabled in {"0", "false", "no", "off"}:
        return None
    api_key = getattr(settings, "gemini_api_key", None)
    if not api_key:
        return None
    try:
        return GeminiEmbedder(api_key)
    except Exception as exc:
        LOGGER.warning("Search embeddings disabled: %s", exc)
        return None


def index_project(
    db_path: str,
    project_id: str,
    transcript: dict,
    embedder: Embedder | None = None,
) -> int:
    """Replace one project's transcript windows and optional embeddings."""
    windows = build_windows(transcript.get("segmen", []))
    conn = db.connect(db_path)
    try:
        db.init_schema(conn)
        old_ids = [
            row[0]
            for row in conn.execute(
                "SELECT id FROM search_windows WHERE project_id = ?",
                (project_id,),
            )
        ]
        if old_ids:
            conn.executemany(
                "DELETE FROM search_embeddings WHERE window_id = ?",
                ((window_id,) for window_id in old_ids),
            )
        conn.execute("DELETE FROM search_fts WHERE project_id = ?", (project_id,))
        conn.execute("DELETE FROM search_windows WHERE project_id = ?", (project_id,))
        conn.executemany(
            """
            INSERT INTO search_windows (id, project_id, win_index, start, end, text)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    f"{project_id}:{index}",
                    project_id,
                    index,
                    window["start"],
                    window["end"],
                    window["text"],
                )
                for index, window in enumerate(windows)
            ),
        )
        conn.executemany(
            """
            INSERT INTO search_fts (text, window_id, project_id)
            VALUES (?, ?, ?)
            """,
            (
                (window["text"], f"{project_id}:{index}", project_id)
                for index, window in enumerate(windows)
            ),
        )
        conn.commit()
    finally:
        conn.close()

    if embedder and windows:
        conn = db.connect(db_path)
        try:
            embedding_failed = False
            for offset in range(0, len(windows), 100):
                batch = windows[offset : offset + 100]
                try:
                    vectors = embedder.embed(
                        [window["text"] for window in batch],
                        "RETRIEVAL_DOCUMENT",
                    )
                    if len(vectors) != len(batch):
                        raise ValueError("embedding count did not match window count")
                    conn.executemany(
                        """
                        INSERT OR REPLACE INTO search_embeddings
                            (window_id, dim, vector)
                        VALUES (?, ?, ?)
                        """,
                        (
                            (
                                f"{project_id}:{offset + index}",
                                len(vector),
                                np.asarray(vector, dtype="<f4").tobytes(),
                            )
                            for index, vector in enumerate(vectors)
                        ),
                    )
                except Exception as exc:
                    LOGGER.warning(
                        "Could not embed transcript windows for %s: %s",
                        project_id,
                        exc,
                    )
                    embedding_failed = True
                    break
            if embedding_failed:
                conn.executemany(
                    "DELETE FROM search_embeddings WHERE window_id = ?",
                    ((f"{project_id}:{index}",) for index in range(len(windows))),
                )
            conn.commit()
        finally:
            conn.close()
    return len(windows)


def delete_project(db_path: str, project_id: str) -> None:
    """Remove all indexed transcript data for a project."""
    conn = db.connect(db_path)
    try:
        db.init_schema(conn)
        window_ids = [
            row[0]
            for row in conn.execute(
                "SELECT id FROM search_windows WHERE project_id = ?",
                (project_id,),
            )
        ]
        if window_ids:
            conn.executemany(
                "DELETE FROM search_embeddings WHERE window_id = ?",
                ((window_id,) for window_id in window_ids),
            )
        conn.execute("DELETE FROM search_fts WHERE project_id = ?", (project_id,))
        conn.execute(
            "DELETE FROM search_windows WHERE project_id = ?",
            (project_id,),
        )
        conn.commit()
    finally:
        conn.close()


def _tokens(query: str) -> list[str]:
    return re.findall(r"\w+", query, flags=re.UNICODE)


def _lexical_rows(
    conn,
    query: str,
    project_id: str | None,
) -> list[dict]:
    tokens = _tokens(query)
    if not tokens:
        return []
    match = " OR ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens)
    clauses = ["search_fts MATCH ?"]
    params: list[str] = [match]
    if project_id:
        clauses.append("search_fts.project_id = ?")
        params.append(project_id)
    rows = conn.execute(
        f"""
        SELECT window_id, project_id, bm25(search_fts) AS rank,
               highlight(search_fts, 0, '[', ']') AS highlight
        FROM search_fts
        WHERE {' AND '.join(clauses)}
        ORDER BY rank
        """,
        params,
    ).fetchall()
    ranks = [-float(row["rank"]) for row in rows]
    max_rank = max(ranks, default=0.0)
    return [
        {
            "window_id": row["window_id"],
            "project_id": row["project_id"],
            "lexical": (score / max_rank) if max_rank > 0 else 0.0,
            "highlight": row["highlight"],
        }
        for row, score in zip(rows, ranks)
    ]


def search(
    db_path: str,
    query: str,
    project_id: str | None = None,
    limit: int = 20,
    embedder: Embedder | None = None,
) -> dict:
    """Search transcript windows using FTS5 and optional embeddings."""
    started = time.perf_counter()
    limit = max(1, min(limit, 50))
    conn = db.connect(db_path)
    try:
        db.init_schema(conn)
        scope = "WHERE project_id = ?" if project_id else ""
        indexed_windows = conn.execute(
            f"SELECT COUNT(*) FROM search_windows {scope}",
            (project_id,) if project_id else (),
        ).fetchone()[0]
        if not _tokens(query):
            return {
                "query": query,
                "mode": "lexical",
                "took_ms": int((time.perf_counter() - started) * 1000),
                "indexed_windows": indexed_windows,
                "results": [],
            }
        lexical_rows = _lexical_rows(conn, query, project_id)
        lexical = {row["window_id"]: row for row in lexical_rows}
        semantic: dict[str, float] = {}
        if embedder:
            embedding_rows = conn.execute(
                f"""
                SELECT e.window_id, e.dim, e.vector
                FROM search_embeddings e
                JOIN search_windows w ON w.id = e.window_id
                {scope}
                """,
                (project_id,) if project_id else (),
            ).fetchall()
            if embedding_rows:
                try:
                    query_vector = np.asarray(
                        embedder.embed([query], "RETRIEVAL_QUERY")[0],
                        dtype=np.float32,
                    )
                    query_norm = np.linalg.norm(query_vector)
                    if query_norm:
                        for row in embedding_rows:
                            vector = np.frombuffer(row["vector"], dtype="<f4")
                            norm = np.linalg.norm(vector)
                            if len(vector) == len(query_vector) and norm:
                                similarity = float(
                                    np.dot(query_vector, vector)
                                    / (query_norm * norm)
                                )
                                if similarity > 0:
                                    semantic[row["window_id"]] = similarity
                except Exception as exc:
                    LOGGER.warning("Could not search transcript embeddings: %s", exc)
        candidate_ids = set(lexical) | set(sorted(
            semantic,
            key=semantic.get,
            reverse=True,
        )[: 3 * limit])
        if not candidate_ids:
            return {
                "query": query,
                "mode": "hybrid" if semantic else "lexical",
                "took_ms": int((time.perf_counter() - started) * 1000),
                "indexed_windows": indexed_windows,
                "results": [],
            }
        placeholders = ",".join("?" for _ in candidate_ids)
        rows = conn.execute(
            f"""
            SELECT w.id AS window_id, w.project_id, p.name AS project_name,
                   w.start, w.end, w.text
            FROM search_windows w
            LEFT JOIN projects p ON p.id = w.project_id
            WHERE w.id IN ({placeholders})
            """,
            list(candidate_ids),
        ).fetchall()
        has_semantic = bool(semantic)
        has_lexical = bool(lexical)
        result_rows = []
        for row in rows:
            lexical_score = lexical.get(row["window_id"], {}).get("lexical", 0.0)
            semantic_score = semantic.get(row["window_id"], 0.0)
            if has_lexical and has_semantic:
                score = 0.5 * lexical_score + 0.5 * semantic_score
            else:
                score = lexical_score if has_lexical else semantic_score
            result_rows.append(
                {
                    "window_id": row["window_id"],
                    "project_id": row["project_id"],
                    "project_name": row["project_name"] or row["project_id"],
                    "start": row["start"],
                    "end": row["end"],
                    "text": row["text"],
                    "highlight": lexical.get(row["window_id"], {}).get(
                        "highlight", row["text"]
                    ),
                    "score": score,
                    "lexical": lexical_score,
                    "semantic": semantic_score,
                }
            )
        result_rows.sort(key=lambda row: (-row["score"], row["start"]))
        return {
            "query": query,
            "mode": "hybrid" if has_semantic else "lexical",
            "took_ms": int((time.perf_counter() - started) * 1000),
            "indexed_windows": indexed_windows,
            "results": result_rows[:limit],
        }
    finally:
        conn.close()


def reindex_all(
    db_path: str,
    cache_dir: str,
    embedder: Embedder | None = None,
) -> dict:
    """Index every project with a cached transcript."""
    indexed: dict[str, int] = {}
    for project in db.list_projects(db_path):
        path = os.path.join(cache_dir, f"{project['id']}_transcript.json")
        if not os.path.isfile(path):
            delete_project(db_path, project["id"])
            continue
        try:
            with open(path, encoding="utf-8") as handle:
                transcript = json.load(handle)
            indexed[project["id"]] = index_project(
                db_path, project["id"], transcript, embedder=embedder
            )
        except Exception as exc:
            LOGGER.warning("Could not index project %s: %s", project["id"], exc)
    return {"indexed": indexed}
