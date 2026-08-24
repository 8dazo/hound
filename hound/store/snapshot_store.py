"""Snapshot storage for baseline OpenAPI specifications."""

from __future__ import annotations

import abc
import datetime
import json
from pathlib import Path
from typing import Any


class SnapshotStore(abc.ABC):
    """Abstract base class for snapshot persistence."""

    @abc.abstractmethod
    def get_snapshot(self, target_name: str) -> dict[str, Any] | None:
        """Retrieve stored spec dictionary for the given target."""

    @abc.abstractmethod
    def get_snapshot_hash(self, target_name: str) -> str | None:
        """Retrieve the SHA256 content hash of the stored spec for the given target."""

    @abc.abstractmethod
    def save_snapshot(self, target_name: str, spec_data: dict[str, Any], content_hash: str) -> None:
        """Store the spec dictionary and content hash for the given target."""

    @abc.abstractmethod
    def reset_snapshot(self, target_name: str) -> bool:
        """Discard the snapshot for the given target. Returns True if removed."""


class LocalSnapshotStore(SnapshotStore):
    """Stores snapshots on local filesystem under .hound/snapshots/."""

    def __init__(self, base_dir: Path | str = ".hound/snapshots") -> None:
        self.base_dir = Path(base_dir)

    def _get_path(self, target_name: str) -> Path:
        return self.base_dir / f"{target_name}.json"

    def get_snapshot(self, target_name: str) -> dict[str, Any] | None:
        path = self._get_path(target_name)
        if not path.is_file():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("spec")
        except Exception:
            return None

    def get_snapshot_hash(self, target_name: str) -> str | None:
        path = self._get_path(target_name)
        if not path.is_file():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("content_hash")
        except Exception:
            return None

    def save_snapshot(self, target_name: str, spec_data: dict[str, Any], content_hash: str) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        path = self._get_path(target_name)
        payload = {
            "target": target_name,
            "content_hash": content_hash,
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "spec": spec_data,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    def reset_snapshot(self, target_name: str) -> bool:
        path = self._get_path(target_name)
        if path.is_file():
            path.unlink()
            return True
        return False
