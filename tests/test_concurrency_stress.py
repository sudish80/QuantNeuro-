import csv
import json
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from production_hardening.journal import TradeJournal
from production_hardening.reliability import StateStore
from production_hardening.security import decrypt_bytes


class TestConcurrencyStress(unittest.TestCase):
    def test_state_store_parallel_writes_are_atomic_and_valid_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "runtime_state.json"
            store = StateStore(str(state_path))

            writer_count = 6
            writes_per_writer = 20
            total_writes = writer_count * writes_per_writer
            parse_errors = []
            stop = threading.Event()

            def reader_worker():
                while not stop.is_set():
                    if state_path.exists():
                        try:
                            payload = store._read_payload()
                            if payload:
                                self.assertIn("state", payload)
                                self.assertIn("version", payload)
                        except Exception as ex:
                            parse_errors.append(str(ex))
                    time.sleep(0.001)

            def writer_worker(worker_id: int):
                for seq in range(writes_per_writer):
                    store.save({"worker": worker_id, "seq": seq, "ts": time.time()})

            reader_thread = threading.Thread(target=reader_worker, daemon=True)
            reader_thread.start()

            with ThreadPoolExecutor(max_workers=writer_count) as pool:
                futures = [pool.submit(writer_worker, wid) for wid in range(writer_count)]
                for f in futures:
                    f.result()

            stop.set()
            reader_thread.join(timeout=2)

            self.assertFalse(parse_errors, f"JSON parse errors observed under concurrent writes: {parse_errors[:3]}")

            latest = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertIn("state", latest)
            self.assertIn("version", latest)

            versions_dir = Path(tmpdir) / "runtime_state_versions"
            version_files = list(versions_dir.glob("state_v*.json"))
            self.assertEqual(
                len(version_files),
                total_writes,
                "Expected one version snapshot per save operation under load",
            )

    def test_trade_journal_parallel_writes_are_locked_and_encrypted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "trade_journal.csv"
            enc_path = Path(tmpdir) / "audit_log.enc"

            journal = TradeJournal(
                csv_path=str(csv_path),
                encrypted_log_path=str(enc_path),
                kms_key_id="",
                kms_region="us-east-1",
                passphrase="unit-test-passphrase",
                plaintext_enabled=True,
            )

            write_count = 80

            def write_one(i: int):
                side = "BUY" if i % 2 == 0 else "SELL"
                journal.write_event(
                    event="ORDER",
                    symbol="BTCUSDT",
                    side=side,
                    qty=float(i + 1),
                    price=100000.0 + i,
                    status="FILLED",
                    reason=f"stress-{i}",
                )

            with ThreadPoolExecutor(max_workers=8) as pool:
                futures = [pool.submit(write_one, i) for i in range(write_count)]
                for f in futures:
                    f.result()

            with csv_path.open("r", encoding="utf-8", newline="") as f:
                rows = list(csv.reader(f))
            self.assertEqual(len(rows), 1 + write_count)
            self.assertTrue(all(len(row) == 8 for row in rows[1:]))

            encrypted_lines = [line for line in enc_path.read_bytes().splitlines() if line.strip()]
            self.assertEqual(len(encrypted_lines), write_count)

            sample = decrypt_bytes(encrypted_lines[0], "unit-test-passphrase").decode("utf-8").strip()
            payload = json.loads(sample)
            self.assertEqual(payload["event"], "ORDER")
            self.assertEqual(payload["symbol"], "BTCUSDT")


if __name__ == "__main__":
    unittest.main()
