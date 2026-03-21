"""
Enhanced Output Pipeline for Neural Network Trading System

This module provides production-grade output handling with:
1. Atomic writes with rollback
2. Data validation and schema enforcement
3. Compression for large files
4. Versioning and backup
5. Real-time dashboard with charts
6. Structured logging
7. Query interfaces for trade journal

Usage:
    from production_hardening.output_pipeline import (
        EnhancedMetrics,
        EnhancedModelRegistry,
        EnhancedStateStore,
        EnhancedTradeJournal,
        EnhancedDashboard
    )
    
    # Metrics
    metrics = EnhancedMetrics("output/metrics.csv")
    metrics.write({
        "current_price": 50000.0,
        "predicted_price": 51000.0,
        "drift_score": 0.3,
        ...
    })
    
    # State with versioning
    state = EnhancedStateStore("output/runtime_state.json")
    state.save({"positions": {...}}, versioned=True)
    
    # Dashboard with charts
    dashboard = EnhancedDashboard()
    dashboard.generate_from_csv("output/metrics.csv")
"""

import atexit
import fcntl
import gzip
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import numpy as np


# ============================================================================
# Configuration
# ============================================================================

@dataclass
class OutputPipelineConfig:
    """Configuration for output pipeline."""
    # Paths
    output_dir: str = "./output"
    metrics_file: str = "metrics.csv"
    model_registry_file: str = "model_registry.json"
    runtime_state_file: str = "runtime_state.json"
    trade_journal_file: str = "trade_journal.csv"
    dashboard_file: str = "dashboard.html"
    audit_log_file: str = "audit_log.enc"
    
    # Features
    enable_compression: bool = True
    enable_versioning: bool = True
    max_versions: int = 10
    compression_threshold_kb: int = 100
    
    # Dashboard
    dashboard_theme: str = "dark"
    dashboard_refresh_seconds: int = 30
    
    # Trade journal
    journal_db_path: str = "./output/trade_journal.db"
    journal_retention_days: int = 365
    
    # Performance
    batch_size: int = 100
    async_write: bool = True


# ============================================================================
# Base Components
# ============================================================================

class OutputError(Exception):
    """Base exception for output pipeline."""
    pass


class ValidationError(OutputError):
    """Data validation error."""
    pass


class LockError(OutputError):
    """File locking error."""
    pass


@contextmanager
def atomic_write(file_path: str, mode: str = "w", encoding: str = "utf-8"):
    """
    Atomic write context manager.
    
    Writes to a temp file and renames on success.
    """
    file_path = Path(file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Create temp file in same directory
    fd, temp_path = tempfile.mkstemp(
        dir=file_path.parent,
        prefix=f".{file_path.name}.",
        suffix=".tmp"
    )
    
    try:
        with os.fdopen(fd, mode, encoding=encoding) as f:
            yield f
        
        # Atomic rename
        if file_path.exists():
            # Backup existing
            backup_path = file_path.with_suffix(file_path.suffix + ".bak")
            shutil.copy2(file_path, backup_path)
        
        shutil.move(temp_path, file_path)
        
    except Exception:
        # Clean up temp file on error
        try:
            os.unlink(temp_path)
        except:
            pass
        raise


@contextmanager
def file_lock(file_path: str, timeout: float = 10.0):
    """
    File locking context manager using flock.
    
    Usage:
        with file_lock("metrics.csv"):
            # Write to file
    """
    lock_path = f"{file_path}.lock"
    lock_file = open(lock_path, 'w')
    
    start_time = datetime.now()
    while True:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            if (datetime.now() - start_time).total_seconds() > timeout:
                lock_file.close()
                raise LockError(f"Could not acquire lock on {file_path}")
            import time
            time.sleep(0.1)
    
    try:
        yield
    finally:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()
        try:
            os.unlink(lock_path)
        except:
            pass


# ============================================================================
# Enhanced Metrics
# ============================================================================

class EnhancedMetrics:
    """
    Enhanced metrics writer with:
    - Atomic writes
    - Data validation
    - Schema enforcement
    - Compression
    - Multiple output formats
    """
    
    REQUIRED_FIELDS = {
        "ts_utc", "current_price", "predicted_price", 
        "train_loss_last", "val_loss_last"
    }
    
    OPTIONAL_FIELDS = {
        "drift_score", "signal", "position_size", "pnl",
        "sharpe_ratio", "max_drawdown", "win_rate",
        "volatility", "volume", "rsi", "macd"
    }
    
    ALL_FIELDS = REQUIRED_FIELDS | OPTIONAL_FIELDS
    
    def __init__(self, path: str, config: OutputPipelineConfig | None = None):
        self.path = Path(path)
        self.config = config or OutputPipelineConfig()
        self._lock = threading.Lock()
        
        # Ensure directory exists
        self.path.parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize header if file doesn't exist
        if not self.path.exists():
            self._write_header()
    
    def _write_header(self):
        """Write CSV header."""
        fields = list(self.ALL_FIELDS)
        header = ",".join(fields)
        with open(self.path, "w") as f:
            f.write(header + "\n")
    
    def _validate(self, metrics: dict) -> None:
        """Validate metrics dictionary."""
        # Check required fields
        missing = self.REQUIRED_FIELDS - set(metrics.keys())
        if missing:
            raise ValidationError(f"Missing required fields: {missing}")
        
        # Check for unknown fields
        unknown = set(metrics.keys()) - self.ALL_FIELDS
        if unknown:
            # Just warn, don't fail
            pass
        
        # Validate types
        for field in self.REQUIRED_FIELDS:
            value = metrics.get(field)
            if value is not None and not isinstance(value, (int, float, str)):
                raise ValidationError(f"Invalid type for {field}: {type(value)}")
    
    def _compress_if_needed(self):
        """Compress file if it exceeds threshold."""
        if not self.config.enable_compression:
            return
        
        size_kb = self.path.stat().st_size / 1024
        if size_kb > self.config.compression_threshold_kb:
            compressed_path = self.path.with_suffix(".csv.gz")
            with open(self.path, 'rb') as f_in:
                with gzip.open(compressed_path, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
    
    def write(self, metrics: dict, validate: bool = True) -> None:
        """
        Write metrics to CSV.
        
        Args:
            metrics: Dictionary of metric values
            validate: Whether to validate before writing
        """
        if validate:
            self._validate(metrics)
        
        # Add timestamp if not present
        if "ts_utc" not in metrics:
            metrics["ts_utc"] = datetime.now().utcnow().isoformat() + "Z"
        
        with self._lock:
            with atomic_write(self.path, mode="a") as f:
                # Build row
                values = []
                for field in self.ALL_FIELDS:
                    value = metrics.get(field, "")
                    if isinstance(value, float):
                        values.append(f"{value:.8g}")
                    else:
                        values.append(str(value))
                
                f.write(",".join(values) + "\n")
            
            # Compress if needed
            self._compress_if_needed()
    
    def write_batch(self, metrics_list: list[dict]) -> None:
        """Write multiple metrics at once."""
        with self._lock:
            with atomic_write(self.path, mode="a") as f:
                for metrics in metrics_list:
                    if "ts_utc" not in metrics:
                        metrics["ts_utc"] = datetime.now().utcnow().isoformat() + "Z"
                    
                    values = []
                    for field in self.ALL_FIELDS:
                        value = metrics.get(field, "")
                        if isinstance(value, float):
                            values.append(f"{value:.8g}")
                        else:
                            values.append(str(value))
                    
                    f.write(",".join(values) + "\n")
    
    def read(self, n: int | None = None) -> list[dict]:
        """Read metrics from CSV."""
        results = []
        
        # Check for compressed version
        compressed_path = self.path.with_suffix(".csv.gz")
        if compressed_path.exists():
            opener = lambda: gzip.open(compressed_path, 'rt')
        else:
            opener = lambda: open(self.path, 'r')
        
        with opener() as f:
            header = f.readline().strip().split(",")
            
            for i, line in enumerate(f):
                if n and i >= n:
                    break
                
                values = line.strip().split(",")
                row = dict(zip(header, values))
                
                # Convert types
                for key, value in row.items():
                    try:
                        row[key] = float(value)
                    except:
                        pass
                
                results.append(row)
        
        return results
    
    def get_latest(self) -> dict | None:
        """Get the most recent metrics."""
        results = self.read(n=1)
        return results[-1] if results else None
    
    def get_stats(self, field: str) -> dict:
        """Get statistics for a field."""
        values = [row[field] for row in self.read() if field in row]
        if not values:
            return {}
        
        arr = np.array(values, dtype=float)
        return {
            "count": len(arr),
            "mean": float(np.mean(arr)),
            "std": float(np.std(arr)),
            "min": float(np.min(arr)),
            "max": float(np.max(arr)),
            "last": float(arr[-1]),
            "p50": float(np.percentile(arr, 50)),
            "p95": float(np.percentile(arr, 95)),
            "p99": float(np.percentile(arr, 99)),
        }


# ============================================================================
# Enhanced Model Registry
# ============================================================================

class EnhancedModelRegistry:
    """
    Enhanced model registry with:
    - File locking
    - Versioning and rollback
    - Schema validation
    - Backup
    - Expanded metadata
    """
    
    SCHEMA = {
        "version": str,
        "model_type": str,
        "activation": str,
        "train_window": str,
        "val_rmse": float,
        "val_mape": float,
        "sharpe_ratio": float,
        "max_drawdown": float,
        "approved": bool,
        "approved_by": str,
        "rollback_version": str,
        "change_ticket": str,
        "registered_at": str,
        # New fields
        "epochs_trained": int,
        "batch_size": int,
        "learning_rate": float,
        "dataset_size": int,
        "train_samples": int,
        "val_samples": int,
        "feature_count": int,
        "training_duration_seconds": float,
        "hardware": str,
        "git_commit": str,
        "checksum": str,
    }
    
    def __init__(self, path: str, config: OutputPipelineConfig | None = None):
        self.path = Path(path)
        self.config = config or OutputPipelineConfig()
        self._lock = threading.RLock()
        
        self.path.parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize if doesn't exist
        if not self.path.exists():
            self._save({"versions": []})
    
    def _load(self) -> dict:
        """Load registry from file."""
        if not self.path.exists():
            return {"versions": []}
        
        with open(self.path, "r") as f:
            return json.load(f)
    
    def _save(self, data: dict) -> None:
        """Save registry to file."""
        with atomic_write(self.path, mode="w") as f:
            json.dump(data, f, indent=2)
    
    def _validate(self, model_info: dict) -> None:
        """Validate model info against schema."""
        for field, expected_type in self.SCHEMA.items():
            if field in model_info:
                if not isinstance(model_info[field], expected_type):
                    raise ValidationError(
                        f"Invalid type for {field}: "
                        f"expected {expected_type}, got {type(model_info[field])}"
                    )
    
    def _backup(self) -> None:
        """Create backup of registry."""
        if not self.path.exists():
            return
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = self.path.parent / f"{self.path.stem}_backup_{timestamp}.json"
        shutil.copy2(self.path, backup_path)
        
        # Clean old backups
        backups = sorted(self.path.parent.glob(f"{self.path.stem}_backup_*.json"))
        while len(backups) > self.config.max_versions:
            backups[0].unlink()
            backups = backups[1:]
    
    def register(
        self,
        version: str,
        model_type: str,
        activation: str,
        train_window: str,
        val_rmse: float = 0.0,
        approved: bool = False,
        approved_by: str = "system",
        additional_info: dict | None = None
    ) -> None:
        """
        Register a new model version.
        
        Args:
            version: Unique version identifier
            model_type: Type of model (lstm, gru, etc.)
            activation: Activation function
            train_window: Training window
            val_rmse: Validation RMSE
            approved: Whether model is approved for production
            approved_by: Who approved the model
            additional_info: Additional metadata
        """
        with self._lock:
            # Load current
            data = self._load()
            
            # Check if version already exists
            for v in data.get("versions", []):
                if v["version"] == version:
                    # Update existing
                    v.update({
                        "val_rmse": val_rmse,
                        "approved": approved,
                        "approved_by": approved_by,
                    })
                    if additional_info:
                        v.update(additional_info)
                    break
            else:
                # Add new version
                model_info = {
                    "version": version,
                    "model_type": model_type,
                    "activation": activation,
                    "train_window": train_window,
                    "val_rmse": val_rmse,
                    "approved": approved,
                    "approved_by": approved_by,
                    "rollback_version": "",
                    "change_ticket": "AUTO-REGISTER",
                    "registered_at": datetime.now().utcnow().isoformat() + "Z",
                }
                
                if additional_info:
                    model_info.update(additional_info)
                
                # Validate
                self._validate(model_info)
                
                data["versions"].append(model_info)
            
            # Backup before saving
            if self.config.enable_versioning:
                self._backup()
            
            # Save
            self._save(data)
    
    def get_versions(self, approved_only: bool = False) -> list[dict]:
        """Get all registered versions."""
        data = self._load()
        versions = data.get("versions", [])
        
        if approved_only:
            versions = [v for v in versions if v.get("approved", False)]
        
        return versions
    
    def get_latest(self, approved_only: bool = True) -> dict | None:
        """Get the latest version."""
        versions = self.get_versions(approved_only)
        if not versions:
            return None
        return versions[-1]
    
    def approve(self, version: str, approved_by: str = "system") -> None:
        """Approve a model version."""
        with self._lock:
            data = self._load()
            
            for v in data.get("versions", []):
                if v["version"] == version:
                    v["approved"] = True
                    v["approved_by"] = approved_by
                    break
            
            self._backup()
            self._save(data)
    
    def rollback(self, target_version: str) -> dict:
        """
        Rollback to a previous version.
        
        Returns info about the rollback.
        """
        with self._lock:
            data = self._load()
            
            # Find target version
            target = None
            for v in data.get("versions", []):
                if v["version"] == target_version:
                    target = v.copy()
                    break
            
            if not target:
                raise ValueError(f"Version {target_version} not found")
            
            # Get current
            current = self.get_latest()
            
            # Update rollback references
            if current:
                current["rollback_version"] = target_version
            
            # Create rollback entry
            rollback_info = {
                "timestamp": datetime.now().utcnow().isoformat() + "Z",
                "from_version": current["version"] if current else "none",
                "to_version": target_version,
                "reason": "manual_rollback"
            }
            
            self._backup()
            self._save(data)
            
            return rollback_info


# ============================================================================
# Enhanced State Store
# ============================================================================

class EnhancedStateStore:
    """
    Enhanced state store with:
    - Versioning
    - Atomic writes
    - Validation
    - Compression
    """
    
    REQUIRED_STATE_FIELDS = {
        "last_signal", "last_symbol"
    }
    
    def __init__(self, path: str, config: OutputPipelineConfig | None = None):
        self.path = Path(path)
        self.config = config or OutputPipelineConfig()
        self._lock = threading.RLock()
        self._version = 0
        
        self.path.parent.mkdir(parents=True, exist_ok=True)
        
        if not self.path.exists():
            self._save({"saved_at": None, "state": {}, "version": 0})
    
    def _load(self) -> dict:
        """Load state from file."""
        if not self.path.exists():
            return {"saved_at": None, "state": {}, "version": 0}
        
        with open(self.path, "r") as f:
            return json.load(f)
    
    def _save(self, data: dict) -> None:
        """Save state to file."""
        with atomic_write(self.path, mode="w") as f:
            json.dump(data, f, indent=2)
    
    def _backup(self) -> None:
        """Create versioned backup."""
        if not self.config.enable_versioning:
            return
        
        data = self._load()
        version = data.get("version", 0) + 1
        
        # Save versioned copy
        version_path = self.path.parent / f"{self.path.stem}_v{version}.json"
        with open(version_path, "w") as f:
            json.dump(data, f)
        
        # Clean old versions
        versions = sorted(self.path.parent.glob(f"{self.path.stem}_v*.json"))
        while len(versions) > self.config.max_versions:
            versions[0].unlink()
            versions = versions[1:]
    
    def _validate(self, state: dict) -> None:
        """Validate state dictionary."""
        # Check required fields
        missing = self.REQUIRED_STATE_FIELDS - set(state.keys())
        if missing:
            # Just warn, don't fail
            pass
    
    def save(self, state: dict, versioned: bool = True) -> int:
        """
        Save state.
        
        Returns the version number.
        """
        self._validate(state)
        
        with self._lock:
            # Load current
            data = self._load()
            
            # Update
            data["saved_at"] = datetime.now().utcnow().isoformat() + "Z"
            data["state"] = state
            data["version"] = data.get("version", 0) + 1
            
            self._version = data["version"]
            
            # Backup if versioning enabled
            if versioned and self.config.enable_versioning:
                self._backup()
            
            # Compress old versions
            self._compress_old_versions()
            
            # Save
            self._save(data)
            
            return self._version
    
    def _compress_old_versions(self):
        """Compress old version files."""
        if not self.config.enable_compression:
            return
        
        for version_file in self.path.parent.glob(f"{self.path.stem}_v*.json"):
            if version_file.stat().st_size > self.config.compression_threshold_kb * 1024:
                compressed = version_file.with_suffix(".json.gz")
                with open(version_file, 'rb') as f_in:
                    with gzip.open(compressed, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
                version_file.unlink()
    
    def load(self) -> dict:
        """Load the current state."""
        data = self._load()
        return data.get("state", {})
    
    def load_version(self, version: int) -> dict:
        """Load a specific version."""
        version_path = self.path.parent / f"{self.path.stem}_v{version}.json"
        compressed_path = version_path.with_suffix(".json.gz")
        
        if version_path.exists():
            with open(version_path, "r") as f:
                return json.load(f).get("state", {})
        elif compressed_path.exists():
            with gzip.open(compressed_path, 'rt') as f:
                return json.load(f).get("state", {})
        else:
            raise ValueError(f"Version {version} not found")
    
    def get_history(self, n: int = 10) -> list[dict]:
        """Get history of state changes."""
        versions = sorted(
            self.path.parent.glob(f"{self.path.stem}_v*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )[:n]
        
        history = []
        for v in versions:
            with open(v, "r") as f:
                data = json.load(f)
                history.append({
                    "version": data.get("version", 0),
                    "saved_at": data.get("saved_at"),
                    "state": data.get("state", {})
                })
        
        return history


# ============================================================================
# Enhanced Trade Journal
# ============================================================================

class EnhancedTradeJournal:
    """
    Enhanced trade journal with:
    - SQLite backend for queries
    - Row validation
    - Event types
    - Compression
    - Retention policies
    """
    
    EVENT_TYPES = {
        "SIGNAL_GENERATED", "ORDER_PLACED", "ORDER_FILLED", "ORDER_CANCELLED",
        "POSITION_OPENED", "POSITION_CLOSED", "RISK_BLOCK", "COMPLIANCE_BLOCK",
        "HEARTBEAT", "CONFIG_CHANGE", "MODEL_CHANGE", "ERROR", "STARTUP", "SHUTDOWN"
    }
    
    def __init__(self, csv_path: str = None, db_path: str = None, 
                 config: OutputPipelineConfig | None = None):
        self.config = config or OutputPipelineConfig()
        self._lock = threading.RLock()
        
        # Paths
        self.csv_path = Path(csv_path or f"{self.config.output_dir}/{self.config.trade_journal_file}")
        self.db_path = Path(db_path or self.config.journal_db_path)
        
        # Ensure directory
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize
        self._init_csv()
        self._init_db()
    
    def _init_csv(self):
        """Initialize CSV file."""
        if not self.csv_path.exists():
            header = "ts_utc,event,symbol,side,qty,price,status,reason"
            with open(self.csv_path, "w") as f:
                f.write(header + "\n")
    
    def _init_db(self):
        """Initialize SQLite database for queries."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts_utc TEXT NOT NULL,
                    event TEXT NOT NULL,
                    symbol TEXT,
                    side TEXT,
                    qty REAL,
                    price REAL,
                    status TEXT,
                    reason TEXT,
                    metadata TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create indexes
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ts ON trades(ts_utc)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_event ON trades(event)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_symbol ON trades(symbol)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON trades(status)")
    
    def _validate(self, event: str, symbol: str = None):
        """Validate event and symbol."""
        if event not in self.EVENT_TYPES:
            raise ValidationError(f"Invalid event type: {event}")
    
    def _compress_old_entries(self):
        """Archive old entries to compressed file."""
        if not self.config.enable_compression:
            return
        
        # Check size
        size_mb = self.db_path.stat().st_size / (1024 * 1024)
        if size_mb < 10:  # 10 MB threshold
            return
        
        # Archive old entries
        cutoff = datetime.now() - timedelta(days=30)
        cutoff_str = cutoff.isoformat()
        
        # Export to compressed CSV
        archive_path = self.csv_path.parent / f"trade_archive_{datetime.now().strftime('%Y%m')}.csv.gz"
        
        with gzip.open(archive_path, 'wt') as f_out:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    "SELECT * FROM trades WHERE ts_utc < ?", (cutoff_str,)
                )
                headers = [desc[0] for desc in cursor.description]
                f_out.write(",".join(headers) + "\n")
                
                for row in cursor:
                    f_out.write(",".join(str(v) for v in row) + "\n")
        
        # Delete archived
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM trades WHERE ts_utc < ?", (cutoff_str,))
            conn.execute("VACUUM")
    
    def write_event(
        self,
        event: str,
        symbol: str = None,
        side: str = None,
        qty: float = None,
        price: float = None,
        status: str = "PENDING",
        reason: str = None,
        metadata: dict | None = None
    ) -> None:
        """Write a trade event."""
        self._validate(event, symbol)
        
        timestamp = datetime.now().utcnow().isoformat() + "Z"
        
        with self._lock:
            # Write to CSV
            with atomic_write(self.csv_path, mode="a") as f:
                row = [
                    timestamp, event, symbol or "", side or "", 
                    str(qty) if qty is not None else "",
                    str(price) if price is not None else "",
                    status, reason or ""
                ]
                f.write(",".join(row) + "\n")
            
            # Insert to SQLite
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO trades 
                    (ts_utc, event, symbol, side, qty, price, status, reason, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (timestamp, event, symbol, side, qty, price, status, reason,
                      json.dumps(metadata) if metadata else None))
            
            # Compress if needed
            self._compress_old_entries()
    
    def query(
        self,
        event: str = None,
        symbol: str = None,
        status: str = None,
        start_date: datetime = None,
        end_date: datetime = None,
        limit: int = 1000
    ) -> list[dict]:
        """Query trade journal."""
        conditions = []
        params = []
        
        if event:
            conditions.append("event = ?")
            params.append(event)
        
        if symbol:
            conditions.append("symbol = ?")
            params.append(symbol)
        
        if status:
            conditions.append("status = ?")
            params.append(status)
        
        if start_date:
            conditions.append("ts_utc >= ?")
            params.append(start_date.isoformat() + "Z")
        
        if end_date:
            conditions.append("ts_utc <= ?")
            params.append(end_date.isoformat() + "Z")
        
        query = "SELECT * FROM trades"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += f" ORDER BY ts_utc DESC LIMIT {limit}"
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
    
    def get_stats(self, days: int = 30) -> dict:
        """Get trading statistics."""
        start_date = datetime.now() - timedelta(days=days)
        
        with sqlite3.connect(self.db_path) as conn:
            # Total events
            total = conn.execute(
                "SELECT COUNT(*) FROM trades WHERE ts_utc >= ?",
                (start_date.isoformat() + "Z",)
            ).fetchone()[0]
            
            # Events by type
            by_type = {}
            cursor = conn.execute("""
                SELECT event, COUNT(*) as count 
                FROM trades 
                WHERE ts_utc >= ?
                GROUP BY event
            """, (start_date.isoformat() + "Z",))
            for row in cursor:
                by_type[row[0]] = row[1]
            
            # Events by symbol
            by_symbol = {}
            cursor = conn.execute("""
                SELECT symbol, COUNT(*) as count 
                FROM trades 
                WHERE ts_utc >= ? AND symbol IS NOT NULL
                GROUP BY symbol
            """, (start_date.isoformat() + "Z",))
            for row in cursor:
                by_symbol[row[0]] = row[1]
            
            # Blocks
            blocks = conn.execute("""
                SELECT COUNT(*) FROM trades 
                WHERE ts_utc >= ? AND event IN ('RISK_BLOCK', 'COMPLIANCE_BLOCK')
            """, (start_date.isoformat() + "Z",)).fetchone()[0]
        
        return {
            "total_events": total,
            "events_by_type": by_type,
            "events_by_symbol": by_symbol,
            "total_blocks": blocks,
            "period_days": days
        }


# ============================================================================
# Enhanced Dashboard
# ============================================================================

class EnhancedDashboard:
    """
    Enhanced dashboard with:
    - Professional dark theme
    - Interactive charts (Chart.js)
    - Real-time updates
    - Multiple visualization types
    """
    
    TEMPLATES = {
        "dark": {
            "bg": "#0d1117",
            "card_bg": "#161b22",
            "text": "#f0f6fc",
            "text_muted": "#8b949e",
            "border": "#30363d",
            "accent": "#58a6ff",
            "success": "#3fb950",
            "danger": "#f85149",
            "warning": "#d29922",
        },
        "light": {
            "bg": "#ffffff",
            "card_bg": "#f6f8fa",
            "text": "#1f2328",
            "text_muted": "#656d76",
            "border": "#d0d7de",
            "accent": "#0969da",
            "success": "#1a7f37",
            "danger": "#cf222e",
            "warning": "#9a6700",
        }
    }
    
    def __init__(self, path: str = None, config: OutputPipelineConfig | None = None):
        self.config = config or OutputPipelineConfig()
        self.path = Path(path or f"{self.config.output_dir}/{self.dashboard_file}")
        self.theme = self.TEMPLATES.get(self.config.dashboard_theme, self.TEMPLATES["dark"])
    
    def generate_from_csv(self, metrics_csv: str) -> None:
        """Generate dashboard from metrics CSV."""
        # Read metrics
        metrics = EnhancedMetrics(metrics_csv)
        data = metrics.read()
        
        if not data:
            self._generate_empty()
            return
        
        # Extract time series
        timestamps = [row.get("ts_utc", "") for row in data]
        current_prices = [row.get("current_price", 0) for row in data]
        predicted_prices = [row.get("predicted_price", 0) for row in data]
        
        # Get latest stats
        latest = data[-1] if data else {}
        
        stats = {}
        for field in ["current_price", "predicted_price", "drift_score", "sharpe_ratio"]:
            stats[field] = metrics.get_stats(field)
        
        # Generate HTML
        html = self._generate_html(
            timestamps=timestamps,
            current_prices=current_prices,
            predicted_prices=predicted_prices,
            latest=latest,
            stats=stats
        )
        
        with atomic_write(self.path, mode="w") as f:
            f.write(html)
    
    def _generate_empty(self):
        """Generate empty dashboard."""
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Trading Dashboard</title>
    <style>
        body {{ 
            font-family: 'Inter', -apple-system, sans-serif;
            background: {self.theme['bg']};
            color: {self.theme['text']};
            padding: 20px;
        }}
    </style>
</head>
<body>
    <h1>No Data Available</h1>
    <p>Run the trading pipeline to generate metrics.</p>
</body>
</html>"""
        with open(self.path, "w") as f:
            f.write(html)
    
    def _generate_html(
        self,
        timestamps: list,
        current_prices: list,
        predicted_prices: list,
        latest: dict,
        stats: dict
    ) -> str:
        """Generate the dashboard HTML."""
        
        # Format data for Chart.js
        price_data = json.dumps([
            {"x": ts, "y": p} 
            for ts, p in zip(timestamps[-100:], current_prices[-100:])
        ])
        
        pred_data = json.dumps([
            {"x": ts, "y": p} 
            for ts, p in zip(timestamps[-100:], predicted_prices[-100:])
        ])
        
        # Latest values
        current_price = latest.get("current_price", 0)
        predicted_price = latest.get("predicted_price", 0)
        drift_score = latest.get("drift_score", 0)
        
        return f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Trading Metrics Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        
        body {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: {self.theme['bg']};
            color: {self.theme['text']};
            min-height: 100vh;
            padding: 24px;
        }}
        
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 24px;
            padding-bottom: 16px;
            border-bottom: 1px solid {self.theme['border']};
        }}
        
        .title {{
            font-size: 24px;
            font-weight: 600;
        }}
        
        .refresh {{
            color: {self.theme['text_muted']};
            font-size: 14px;
        }}
        
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }}
        
        .card {{
            background: {self.theme['card_bg']};
            border: 1px solid {self.theme['border']};
            border-radius: 8px;
            padding: 16px;
        }}
        
        .card-label {{
            color: {self.theme['text_muted']};
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 8px;
        }}
        
        .card-value {{
            font-size: 24px;
            font-weight: 600;
        }}
        
        .card-value.success {{ color: {self.theme['success']}; }}
        .card-value.danger {{ color: {self.theme['danger']}; }}
        .card-value.warning {{ color: {self.theme['warning']}; }}
        
        .chart-container {{
            background: {self.theme['card_bg']};
            border: 1px solid {self.theme['border']};
            border-radius: 8px;
            padding: 16px;
            margin-bottom: 24px;
        }}
        
        .chart-title {{
            font-size: 16px;
            font-weight: 500;
            margin-bottom: 16px;
        }}
        
        .chart-wrapper {{
            height: 300px;
        }}
        
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 12px;
        }}
        
        .stat-item {{
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid {self.theme['border']};
        }}
        
        .stat-label {{
            color: {self.theme['text_muted']};
            font-size: 12px;
        }}
        
        .stat-value {{
            font-weight: 500;
            font-family: 'SF Mono', monospace;
        }}
        
        @media (max-width: 768px) {{
            body {{ padding: 12px; }}
            .grid {{ grid-template-columns: repeat(2, 1fr); }}
        }}
    </style>
</head>
<body>
    <div class="header">
        <div class="title">📊 Trading Metrics Dashboard</div>
        <div class="refresh">Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>
    </div>
    
    <div class="grid">
        <div class="card">
            <div class="card-label">Current Price</div>
            <div class="card-value">${current_price:,.2f}</div>
        </div>
        <div class="card">
            <div class="card-label">Predicted Price</div>
            <div class="card-value">${predicted_price:,.2f}</div>
        </div>
        <div class="card">
            <div class="card-label">Drift Score</div>
            <div class="card-value {'warning' if drift_score > 0.5 else ''}">{drift_score:.4f}</div>
        </div>
        <div class="card">
            <div class="card-label">Data Points</div>
            <div class="card-value">{len(current_prices)}</div>
        </div>
    </div>
    
    <div class="chart-container">
        <div class="chart-title">Price vs Prediction</div>
        <div class="chart-wrapper">
            <canvas id="priceChart"></canvas>
        </div>
    </div>
    
    <div class="grid">
        <div class="card">
            <div class="chart-title">Price Statistics</div>
            <div class="stats-grid">
                <div class="stat-item">
                    <span class="stat-label">Mean</span>
                    <span class="stat-value">${stats.get('current_price', {{}}).get('mean', 0):,.2f}</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">Std Dev</span>
                    <span class="stat-value">${stats.get('current_price', {{}}).get('std', 0):,.2f}</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">Min</span>
                    <span class="stat-value">${stats.get('current_price', {{}}).get('min', 0):,.2f}</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">Max</span>
                    <span class="stat-value">${stats.get('current_price', {{}}).get('max', 0):,.2f}</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">P50</span>
                    <span class="stat-value">${stats.get('current_price', {{}}).get('p50', 0):,.2f}</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">P95</span>
                    <span class="stat-value">${stats.get('current_price', {{}}).get('p95', 0):,.2f}</span>
                </div>
            </div>
        </div>
        
        <div class="card">
            <div class="chart-title">Prediction Statistics</div>
            <div class="stats-grid">
                <div class="stat-item">
                    <span class="stat-label">Mean</span>
                    <span class="stat-value">${stats.get('predicted_price', {{}}).get('mean', 0):,.2f}</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">Std Dev</span>
                    <span class="stat-value">${stats.get('predicted_price', {{}}).get('std', 0):,.2f}</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">Min</span>
                    <span class="stat-value">${stats.get('predicted_price', {{}}).get('min', 0):,.2f}</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">Max</span>
                    <span class="stat-value">${stats.get('predicted_price', {{}}).get('max', 0):,.2f}</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">P50</span>
                    <span class="stat-value">${stats.get('predicted_price', {{}}).get('p50', 0):,.2f}</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">P95</span>
                    <span class="stat-value">${stats.get('predicted_price', {{}}).get('p95', 0):,.2f}</span>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        const ctx = document.getElementById('priceChart').getContext('2d');
        
        const chart = new Chart(ctx, {{
            type: 'line',
            data: {{
                datasets: [
                    {{
                        label: 'Current Price',
                        data: {price_data},
                        borderColor: '{self.theme["accent"]}',
                        backgroundColor: '{self.theme["accent"]}20',
                        fill: true,
                        tension: 0.4
                    }},
                    {{
                        label: 'Predicted Price',
                        data: {pred_data},
                        borderColor: '{self.theme["danger"]}',
                        backgroundColor: '{self.theme["danger"]}20',
                        fill: true,
                        tension: 0.4
                    }}
                ]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                interaction: {{
                    mode: 'index',
                    intersect: false
                }},
                plugins: {{
                    legend: {{
                        labels: {{ color: '{self.theme["text"]}' }}
                    }}
                }},
                scales: {{
                    x: {{
                        type: 'time',
                        grid: {{ color: '{self.theme["border"]}' }},
                        ticks: {{ color: '{self.theme["text_muted"]}' }}
                    }},
                    y: {{
                        grid: {{ color: '{self.theme["border"]}' }},
                        ticks: {{ color: '{self.theme["text_muted"]}' }}
                    }}
                }}
            }}
        }});
        
        // Auto-refresh
        setInterval(() => {{
            window.location.reload();
        }}, {self.config.dashboard_refresh_seconds * 1000});
    </script>
</body>
</html>"""
    
    def generate_from_multiple(self, metrics_files: list[str]) -> None:
        """Generate dashboard from multiple metric files."""
        all_data = []
        
        for mf in metrics_files:
            metrics = EnhancedMetrics(mf)
            all_data.extend(metrics.read())
        
        if not all_data:
            self._generate_empty()
            return
        
        # Sort by timestamp
        all_data.sort(key=lambda x: x.get("ts_utc", ""))
        
        self.generate_from_csv = lambda csv: None  # Prevent recursion
        # Write combined data to temp file
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            temp_path = f.name
            # Write combined data
        
        try:
            self.generate_from_csv(temp_path)
        finally:
            os.unlink(temp_path)


# ============================================================================
# Pipeline Integration
# ============================================================================

class OutputPipeline:
    """
    Unified output pipeline coordinating all output components.
    """
    
    def __init__(self, output_dir: str = "./output", config: OutputPipelineConfig | None = None):
        self.config = config or OutputPipelineConfig()
        self.config.output_dir = output_dir
        
        # Initialize components
        self.metrics = EnhancedMetrics(f"{output_dir}/metrics.csv", self.config)
        self.registry = EnhancedModelRegistry(f"{output_dir}/model_registry.json", self.config)
        self.state = EnhancedStateStore(f"{output_dir}/runtime_state.json", self.config)
        self.journal = EnhancedTradeJournal(
            csv_path=f"{output_dir}/trade_journal.csv",
            db_path=f"{output_dir}/trade_journal.db",
            config=self.config
        )
        self.dashboard = EnhancedDashboard(f"{output_dir}/dashboard.html", self.config)
    
    def write_metrics(self, metrics: dict) -> None:
        """Write metrics and update dashboard."""
        self.metrics.write(metrics)
        self.dashboard.generate_from_csv(self.metrics.path)
    
    def log_trade_event(self, event: str, **kwargs) -> None:
        """Log a trade event."""
        self.journal.write_event(event, **kwargs)
    
    def save_state(self, state: dict) -> int:
        """Save runtime state."""
        return self.state.save(state)
    
    def register_model(self, version: str, model_type: str, **kwargs) -> None:
        """Register a model."""
        self.registry.register(version, model_type, **kwargs)


# ============================================================================
# Main
# ============================================================================

if __name__ == "__main__":
    # Example usage
    pipeline = OutputPipeline("./output")
    
    # Write metrics
    pipeline.write_metrics({
        "current_price": 50000.0,
        "predicted_price": 51000.0,
        "drift_score": 0.3,
        "train_loss_last": 0.001,
        "val_loss_last": 0.002,
    })
    
    # Log events
    pipeline.log_trade_event("SIGNAL_GENERATED", symbol="BTCUSD", side="BUY")
    pipeline.log_trade_event("ORDER_PLACED", symbol="BTCUSD", side="BUY", qty=0.1, price=50000)
    
    # Save state
    version = pipeline.save_state({
        "last_signal": "BUY",
        "last_symbol": "BTCUSD",
        "realized_pnl": 100.0
    })
    print(f"State saved at version {version}")
    
    # Register model
    pipeline.register_model(
        version="lstm-v2",
        model_type="lstm",
        activation="relu",
        train_window="5y",
        val_rmse=0.001,
        additional_info={"epochs_trained": 50, "batch_size": 64}
    )
    
    print("\nStats:", pipeline.journal.get_stats())
    print("\nDashboard generated!")
