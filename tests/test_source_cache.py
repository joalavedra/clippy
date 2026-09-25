from __future__ import annotations

import os
import json
from pathlib import Path

import pytest

from clipping.story.source_manager import (
    _download_single_source,
    DownloadError,
    download_all_sources,
    source_fingerprint,
)


def test_local_source_fingerprint_invalidates_cache(tmp_path):
    source_path = tmp_path / "source.mp4"
    cache_dir = tmp_path / "cache"
    source_path.write_bytes(b"first")
    source = {
        "id": "source_a",
        "platform": "local",
        "local_path": str(source_path),
    }

    cached_path = _download_single_source(source, str(cache_dir))
    fingerprint_path = cache_dir / "source_a.fingerprint"
    transcript_path = cache_dir / "source_a_transcript.json"
    assert Path(cached_path).read_bytes() == b"first"
    assert fingerprint_path.read_text(encoding="utf-8") == source_fingerprint(source)
    transcript_path.write_text("cached transcript", encoding="utf-8")

    source_path.write_bytes(b"second and changed")
    stat = source_path.stat()
    os.utime(source_path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    assert source_fingerprint(source) != fingerprint_path.read_text(encoding="utf-8")

    cached_again = _download_single_source(source, str(cache_dir))
    assert Path(cached_again).read_bytes() == b"second and changed"
    assert not transcript_path.exists()
    assert fingerprint_path.read_text(encoding="utf-8") == source_fingerprint(source)


def test_strict_download_saves_status_before_raising(tmp_path, monkeypatch):
    source = {
        "id": "source_a",
        "name": "Source A",
        "platform": "youtube",
        "url": "https://example.test/video",
    }

    def fail_download(*args, **kwargs):
        raise DownloadError("network", source_id="source_a", detail="offline")

    monkeypatch.setattr(
        "clipping.story.source_manager._download_single_source",
        fail_download,
    )
    with pytest.raises(DownloadError):
        download_all_sources(
            {"source_a": source},
            str(tmp_path / "cache"),
            strict=True,
            outputs_dir=str(tmp_path / "output"),
        )

    status = json.loads(
        (tmp_path / "output" / "sources_status.json").read_text(
            encoding="utf-8"
        )
    )
    assert status["sources"] == [
        {
            "id": "source_a",
            "name": "Source A",
            "platform": "youtube",
            "url": "https://example.test/video",
            "local_path": None,
            "cached_path": None,
            "status": "failed",
        }
    ]
