"""Environment-backed service settings."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


@dataclass
class Settings:
    data_dir: str = field(
        default_factory=lambda: os.environ.get("CLIPPY_DATA_DIR", "./data")
    )
    worker_enabled: bool = field(
        default_factory=lambda: _env_bool("CLIPPY_WORKER_ENABLED", True)
    )
    api_key: str | None = field(
        default_factory=lambda: os.environ.get("CLIPPY_API_KEY")
    )
    gemini_api_key: str | None = field(
        default_factory=lambda: os.environ.get("GOOGLE_API_KEY")
    )
    media_token_ttl: int = field(
        default_factory=lambda: int(
            max(
                60,
                min(
                    int(os.environ.get("CLIPPY_MEDIA_TOKEN_TTL", "3600")),
                    86400,
                ),
            )
        )
    )
    media_secret: str | None = field(
        default_factory=lambda: os.environ.get("CLIPPY_MEDIA_SECRET")
    )
    local_media_roots: list[str] | None = None
    cors_origins: list[str] = field(
        default_factory=lambda: [
            origin.strip()
            for origin in os.environ.get(
                "CLIPPY_CORS_ORIGINS",
                "http://localhost:5173,http://127.0.0.1:5173,"
                "http://localhost:8100,http://127.0.0.1:8100",
            ).split(",")
            if origin.strip()
        ]
    )
    db_path: str = field(init=False)
    storage_root: str = field(init=False)
    work_dir: str = field(init=False)
    cache_dir: str = field(init=False)

    def __post_init__(self):
        self.data_dir = os.path.abspath(self.data_dir)
        if self.media_secret is None and self.api_key is not None:
            self.media_secret = hashlib.sha256(
                b"clippy-media:" + self.api_key.encode()
            ).hexdigest()
        if self.local_media_roots is None:
            raw_roots = os.environ.get("CLIPPY_LOCAL_MEDIA_ROOTS")
            if raw_roots:
                roots = raw_roots.split(",")
            else:
                roots = [os.path.join(self.data_dir, "uploads")]
            self.local_media_roots = [
                os.path.abspath(root.strip())
                for root in roots
                if root.strip()
            ]
        else:
            self.local_media_roots = [
                os.path.abspath(root) for root in self.local_media_roots
            ]
        self.db_path = os.path.join(self.data_dir, "clippy.db")
        self.storage_root = os.path.join(self.data_dir, "files")
        self.work_dir = os.path.join(self.data_dir, "jobs")
        self.cache_dir = os.path.join(self.data_dir, "cache")
        for path in (
            self.data_dir,
            self.storage_root,
            self.work_dir,
            self.cache_dir,
            *self.local_media_roots,
        ):
            os.makedirs(path, exist_ok=True)

    @classmethod
    def from_env(cls) -> "Settings":
        return cls()
