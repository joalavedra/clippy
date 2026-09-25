"""Environment-backed service settings."""

from __future__ import annotations

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
    db_path: str = field(init=False)
    storage_root: str = field(init=False)
    work_dir: str = field(init=False)
    cache_dir: str = field(init=False)

    def __post_init__(self):
        self.data_dir = os.path.abspath(self.data_dir)
        self.db_path = os.path.join(self.data_dir, "clippy.db")
        self.storage_root = os.path.join(self.data_dir, "files")
        self.work_dir = os.path.join(self.data_dir, "jobs")
        self.cache_dir = os.path.join(self.data_dir, "cache")
        for path in (self.data_dir, self.storage_root, self.work_dir, self.cache_dir):
            os.makedirs(path, exist_ok=True)

    @classmethod
    def from_env(cls) -> "Settings":
        return cls()
