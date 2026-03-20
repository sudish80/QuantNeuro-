"""Compliance controls: KYC/AML checks, jurisdiction rules, and retention policy."""

from dataclasses import dataclass
from datetime import datetime, timedelta, UTC
from pathlib import Path


@dataclass
class AccountComplianceProfile:
    account_id: str
    kyc_verified: bool
    aml_screen_passed: bool
    risk_tier: str
    jurisdiction: str


ALLOWED_JURISDICTIONS = {
    "GLOBAL",
    "US",
    "EU",
    "UK",
    "SG",
    "AE",
    "IN",
    "JP",
}

RESTRICTED_SYMBOLS_BY_JURISDICTION = {
    "US": {"XMRUSDT"},
}


def validate_compliance(profile: AccountComplianceProfile, symbol: str) -> tuple[bool, str]:
    if not profile.kyc_verified:
        return False, "KYC not verified"
    if not profile.aml_screen_passed:
        return False, "AML screening not passed"
    if profile.jurisdiction not in ALLOWED_JURISDICTIONS:
        return False, f"Jurisdiction not allowed: {profile.jurisdiction}"

    restricted = RESTRICTED_SYMBOLS_BY_JURISDICTION.get(profile.jurisdiction, set())
    if symbol in restricted:
        return False, f"Symbol restricted in jurisdiction {profile.jurisdiction}: {symbol}"

    return True, "OK"


def enforce_retention(file_path: str, retention_days: int) -> None:
    path = Path(file_path)
    if not path.exists():
        return

    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    if datetime.fromtimestamp(path.stat().st_mtime, tz=UTC) < cutoff:
        path.unlink(missing_ok=True)
