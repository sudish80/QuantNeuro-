"""Governance layer: model versioning, approvals, rollback plans, and change records."""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, UTC
from pathlib import Path

from production_hardening.io_utils import atomic_write_text, read_text_locked


@dataclass
class ModelVersion:
    version: str
    model_type: str
    activation: str
    train_window: str
    val_rmse: float
    approved: bool
    approved_by: str
    rollback_version: str
    change_ticket: str


class GovernanceRegistry:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            atomic_write_text(self.path, json.dumps({"versions": []}, indent=2))

    def _read(self) -> dict:
        raw = read_text_locked(self.path, encoding="utf-8")
        payload = json.loads(raw) if raw else {"versions": []}
        if not isinstance(payload, dict):
            raise ValueError("Governance registry payload must be a JSON object")
        payload.setdefault("versions", [])
        return payload

    def _write(self, payload: dict) -> None:
        atomic_write_text(self.path, json.dumps(payload, indent=2))

    def register(self, v: ModelVersion) -> None:
        payload = self._read()
        item = asdict(v)
        item["registered_at"] = datetime.now(UTC).isoformat()
        payload["versions"].append(item)
        self._write(payload)

    def get_approved(self) -> list[dict]:
        payload = self._read()
        return [x for x in payload.get("versions", []) if x.get("approved")]

    def latest_approved(self) -> dict | None:
        approved = self.get_approved()
        return approved[-1] if approved else None
