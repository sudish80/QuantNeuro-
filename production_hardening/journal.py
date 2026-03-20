"""Audit trail and encrypted log writer with retention support."""

from __future__ import annotations

import csv
import json
from datetime import datetime, UTC
from pathlib import Path

from production_hardening.io_utils import file_lock
from production_hardening.security import append_encrypted_line, append_kms_encrypted_line


class TradeJournal:
    def __init__(
        self,
        csv_path: str,
        encrypted_log_path: str,
        kms_key_id: str,
        kms_region: str,
        passphrase: str | None = None,
        plaintext_enabled: bool = False,
    ):
        self.csv_path = Path(csv_path)
        self.enc_path = Path(encrypted_log_path)
        self.kms_key_id = kms_key_id
        self.kms_region = kms_region
        self.passphrase = passphrase
        self.plaintext_enabled = plaintext_enabled
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        self.enc_path.parent.mkdir(parents=True, exist_ok=True)
        if self.plaintext_enabled and not self.csv_path.exists():
            with file_lock(self.csv_path):
                with self.csv_path.open("w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        "ts_utc",
                        "event",
                        "symbol",
                        "side",
                        "qty",
                        "price",
                        "status",
                        "reason",
                    ])

    def write_event(
        self,
        event: str,
        symbol: str,
        side: str,
        qty: float,
        price: float,
        status: str,
        reason: str = "",
    ) -> None:
        if not event or not isinstance(event, str):
            raise ValueError("event must be a non-empty string")
        if not symbol or not isinstance(symbol, str):
            raise ValueError("symbol must be a non-empty string")
        if side not in {"BUY", "SELL", "HOLD"}:
            raise ValueError("side must be one of BUY, SELL, HOLD")
        if qty < 0:
            raise ValueError("qty must be non-negative")
        if price < 0:
            raise ValueError("price must be non-negative")
        if not status or not isinstance(status, str):
            raise ValueError("status must be a non-empty string")

        ts = datetime.now(UTC).isoformat()
        if self.plaintext_enabled:
            with file_lock(self.csv_path):
                with self.csv_path.open("a", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow([ts, event, symbol, side, qty, price, status, reason])

        payload = {
            "ts_utc": ts,
            "event": event,
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "price": price,
            "status": status,
            "reason": reason,
        }
        line = json.dumps(payload, separators=(",", ":"))

        if self.kms_key_id:
            append_kms_encrypted_line(
                file_path=str(self.enc_path),
                line=line,
                kms_key_id=self.kms_key_id,
                kms_region=self.kms_region,
                encryption_context={
                    "app": "neural-network-trader",
                    "symbol": symbol,
                    "event": event,
                },
            )
            return

        if self.passphrase:
            append_encrypted_line(file_path=str(self.enc_path), line=line, passphrase=self.passphrase)
            return

        raise RuntimeError("Encrypted journaling requires either kms_key_id or passphrase")
