"""Storage abstractions for service artifacts."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Protocol


class Storage(Protocol):
    def put(self, src_path: str, key: str) -> str:
        ...

    def url(self, key: str) -> str:
        ...

    def path(self, key: str) -> str:
        ...


class LocalStorage:
    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        os.makedirs(self.root, exist_ok=True)

    def path(self, key: str) -> str:
        destination = Path(self.root, key)
        root = Path(self.root)
        if root not in destination.resolve().parents and destination.resolve() != root:
            raise ValueError("Storage key escapes storage root.")
        return str(destination)

    def put(self, src_path: str, key: str) -> str:
        destination = self.path(key)
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        shutil.copy2(src_path, destination)
        return key

    def url(self, key: str) -> str:
        return f"/files/{key}"
