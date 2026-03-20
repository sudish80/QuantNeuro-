"""Real KYC/AML provider integration and persistent compliance decisions."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, UTC
import json
from pathlib import Path
from typing import Any

import requests

from production_hardening.io_utils import atomic_write_text, read_text_locked


@dataclass
class ComplianceDecision:
    account_id: str
    jurisdiction: str
    kyc_verified: bool
    aml_passed: bool
    approved: bool
    reason: str
    provider_reference: str
    checked_at_utc: str


class ComplianceDecisionStore:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            atomic_write_text(self.path, json.dumps({"decisions": {}}, indent=2))

    def _read(self) -> dict[str, Any]:
        raw = read_text_locked(self.path, encoding="utf-8")
        payload: dict[str, Any] = json.loads(raw) if raw else {"decisions": {}}
        if not isinstance(payload, dict):
            raise ValueError("Compliance decision payload must be a JSON object")
        payload.setdefault("decisions", {})
        return payload

    def _write(self, payload: dict[str, Any]) -> None:
        atomic_write_text(self.path, json.dumps(payload, indent=2))

    def save(self, decision: ComplianceDecision) -> None:
        payload = self._read()
        payload.setdefault("decisions", {})[decision.account_id] = asdict(decision)
        self._write(payload)

    def get(self, account_id: str) -> ComplianceDecision | None:
        payload = self._read()
        raw = payload.get("decisions", {}).get(account_id)
        if not raw:
            return None
        return ComplianceDecision(**raw)


class ComplianceProviderClient:
    """Adapter for a real external compliance API."""

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.session = requests.Session()

    def _post(self, endpoint: str, body: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}{endpoint}"
        resp = self.session.post(url, headers=headers, json=body, timeout=20)
        resp.raise_for_status()
        return resp.json() if resp.text else {}

    def evaluate(self, account_id: str, jurisdiction: str) -> ComplianceDecision:
        # Generic endpoint contract:
        # POST /v1/compliance/evaluate -> { kyc_verified, aml_passed, approved, reason, reference_id }
        data = self._post(
            "/v1/compliance/evaluate",
            {
                "account_id": account_id,
                "jurisdiction": jurisdiction,
            },
        )

        return ComplianceDecision(
            account_id=account_id,
            jurisdiction=jurisdiction,
            kyc_verified=bool(data.get("kyc_verified", False)),
            aml_passed=bool(data.get("aml_passed", False)),
            approved=bool(data.get("approved", False)),
            reason=str(data.get("reason", "")),
            provider_reference=str(data.get("reference_id", "")),
            checked_at_utc=datetime.now(UTC).isoformat(),
        )
