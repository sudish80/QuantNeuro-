"""Runtime configuration for production services."""

from dataclasses import dataclass
import os


@dataclass
class RuntimeConfig:
    environment: str
    jurisdiction: str
    retention_days: int
    kill_switch_path: str
    state_file: str
    trade_journal_path: str
    encrypted_audit_log_path: str
    metrics_path: str
    alerts_webhook_url: str | None
    compliance_provider_url: str | None
    compliance_provider_api_key: str | None
    compliance_decisions_path: str
    kms_key_id: str | None
    kms_region: str
    journal_passphrase: str | None
    trade_journal_plaintext_enabled: bool


@dataclass
class BinanceConfig:
    base_url: str
    api_key: str
    api_secret: str
    recv_window_ms: int = 5000


@dataclass
class RiskConfig:
    max_daily_loss_pct: float
    max_asset_exposure_pct: float
    max_total_exposure_pct: float
    circuit_breaker_loss_pct: float
    circuit_breaker_cooldown_sec: int


def load_runtime_config() -> RuntimeConfig:
    return RuntimeConfig(
        environment=os.getenv("ENVIRONMENT", "paper"),
        jurisdiction=os.getenv("JURISDICTION", "GLOBAL"),
        retention_days=int(os.getenv("RETENTION_DAYS", "365")),
        kill_switch_path=os.getenv("KILL_SWITCH_PATH", "./kill_switch.flag"),
        state_file=os.getenv("STATE_FILE", "./output/runtime_state.json"),
        trade_journal_path=os.getenv("TRADE_JOURNAL_PATH", "./output/trade_journal.csv"),
        encrypted_audit_log_path=os.getenv("ENCRYPTED_AUDIT_LOG_PATH", "./output/audit_log.enc"),
        metrics_path=os.getenv("METRICS_PATH", "./output/metrics.csv"),
        alerts_webhook_url=os.getenv("ALERTS_WEBHOOK_URL"),
        compliance_provider_url=os.getenv("COMPLIANCE_PROVIDER_URL"),
        compliance_provider_api_key=os.getenv("COMPLIANCE_PROVIDER_API_KEY"),
        compliance_decisions_path=os.getenv("COMPLIANCE_DECISIONS_PATH", "./output/compliance_decisions.json"),
        kms_key_id=os.getenv("KMS_KEY_ID"),
        kms_region=os.getenv("KMS_REGION", "us-east-1"),
        journal_passphrase=os.getenv("JOURNAL_PASSPHRASE"),
        trade_journal_plaintext_enabled=os.getenv("TRADE_JOURNAL_PLAINTEXT_ENABLED", "false").lower() in {"1", "true", "yes"},
    )


def load_binance_config() -> BinanceConfig:
    return BinanceConfig(
        base_url=os.getenv("BINANCE_BASE_URL", "https://api.binance.com"),
        api_key=os.getenv("BINANCE_API_KEY", ""),
        api_secret=os.getenv("BINANCE_API_SECRET", ""),
        recv_window_ms=int(os.getenv("BINANCE_RECV_WINDOW_MS", "5000")),
    )


def load_risk_config() -> RiskConfig:
    return RiskConfig(
        max_daily_loss_pct=float(os.getenv("MAX_DAILY_LOSS_PCT", "0.03")),
        max_asset_exposure_pct=float(os.getenv("MAX_ASSET_EXPOSURE_PCT", "0.20")),
        max_total_exposure_pct=float(os.getenv("MAX_TOTAL_EXPOSURE_PCT", "0.80")),
        circuit_breaker_loss_pct=float(os.getenv("CIRCUIT_BREAKER_LOSS_PCT", "0.05")),
        circuit_breaker_cooldown_sec=int(os.getenv("CIRCUIT_BREAKER_COOLDOWN_SEC", "1800")),
    )
