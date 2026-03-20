"""Reliability: persistent state save/load and deterministic replay support."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, UTC
from pathlib import Path
import requests

from production_hardening.io_utils import file_lock, read_text_locked


class StateStore:
    def __init__(self, file_path: str):
        self.path = Path(file_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.versions_dir = self.path.parent / f"{self.path.stem}_versions"
        self.versions_dir.mkdir(parents=True, exist_ok=True)

    def save(self, state: dict) -> None:
        if not isinstance(state, dict):
            raise TypeError("state must be a dict")
        # Single lock guards read->increment->write to prevent version races.
        with file_lock(self.path):
            latest = self._read_payload_unlocked()
            next_version = int(latest.get("version", 0)) + 1

            payload = {
                "saved_at": datetime.now(UTC).isoformat(),
                "version": next_version,
                "state": state,
            }

            encoded = json.dumps(payload, indent=2)
            self._atomic_write_unlocked(self.path, encoded)

            # Keep versioned snapshots for rollback/replay support.
            version_path = self.versions_dir / f"state_v{next_version:06d}.json"
            self._atomic_write_unlocked(version_path, encoded)

    def load(self) -> dict:
        payload = self._read_payload()
        return payload.get("state", {})

    def load_version(self, version: int) -> dict:
        if version <= 0:
            raise ValueError("version must be a positive integer")
        version_path = self.versions_dir / f"state_v{version:06d}.json"
        if not version_path.exists():
            return {}
        payload = json.loads(read_text_locked(version_path, encoding="utf-8"))
        state = payload.get("state", {})
        if not isinstance(state, dict):
            raise ValueError("State version payload is invalid")
        return state

    def _read_payload(self) -> dict:
        with file_lock(self.path):
            return self._read_payload_unlocked()

    def _read_payload_unlocked(self) -> dict:
        if not self.path.exists():
            return {}
        raw = self.path.read_text(encoding="utf-8")
        if not raw:
            return {}
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("State payload must be a JSON object")
        return payload

    def _atomic_write_unlocked(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp:
                tmp.write(text)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(tmp_path, path)
        finally:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)


def load_replay_events(csv_path: str) -> list[dict]:
    path = Path(csv_path)
    if not path.exists():
        return []

    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) < 2:
        return []

    headers = [h.strip() for h in lines[0].split(",")]
    if not headers or any(not h for h in headers):
        return []
    events = []
    for line in lines[1:]:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != len(headers):
            continue
        events.append(dict(zip(headers, parts)))
    return events


def choose_failover_endpoint(candidates: list[str], health_path: str = "/api/v3/ping") -> str:
    """Return first reachable endpoint, raising if none are healthy."""
    for base in candidates:
        url = base.rstrip("/") + health_path
        try:
            resp = requests.get(url, timeout=3)
            if resp.ok:
                return base
        except Exception:
            continue
    raise RuntimeError("No healthy endpoint available for failover")
