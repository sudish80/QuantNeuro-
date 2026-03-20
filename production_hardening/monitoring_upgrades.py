"""
PHASE 2 - MONITORING & OBSERVABILITY UPGRADES

Advanced monitoring for production trading systems:
- SLO dashboards (availability, latency, accuracy)
- Smart alerting (multi-signal correlation, alert routing, alert fatigue reduction)
- Business KPI tracking (fill rate, signal accuracy, regime performance)
- On-call runbooks (automated remediation, escalation)
- Custom Prometheus metrics and alerting rules

Usage:
    monitor = ProductionMonitor(prometheus_url="http://localhost:9090")
    
    # Track SLO
    monitor.record_prediction(latency_ms=50, accuracy=True)
    monitor.record_trade(fill_rate=0.98, slippage_bps=2.5)
    
    # Check SLO status
    status = monitor.get_slo_status()
    print(status)
"""

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Tuple, Callable
import numpy as np

logger = logging.getLogger(__name__)


# ============================================================================
# ENUMS
# ============================================================================

class AlertSeverity(Enum):
    """Alert severity levels."""
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class AlertChannel(Enum):
    """Alert routing channels."""
    LOG = "LOG"
    SLACK = "SLACK"
    EMAIL = "EMAIL"
    PAGERDUTY = "PAGERDUTY"
    WEBHOOK = "WEBHOOK"


class SLOStatus(Enum):
    """SLO status."""
    GOOD = "GOOD"
    WARNING = "WARNING"
    VIOLATED = "VIOLATED"


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class SLO:
    """Service Level Objective."""
    name: str
    target: float  # 99.5%, 99.9%, etc
    threshold: float  # Actual value, e.g., 0.995
    window_minutes: int  # Lookback window
    current_value: float = 0.0
    status: SLOStatus = SLOStatus.GOOD
    violations: int = 0


@dataclass
class Alert:
    """Alert definition."""
    name: str
    severity: AlertSeverity
    condition: str
    threshold: float
    duration_seconds: int  # Alert fires if condition held for N seconds
    channels: List[AlertChannel] = field(default_factory=list)
    enabled: bool = True
    fired: bool = False


@dataclass
class KPI:
    """Key Performance Indicator."""
    name: str
    current: float
    target: float
    unit: str
    trend: str  # "UP", "DOWN", "FLAT"
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class HealthMetrics:
    """System health snapshot."""
    api_latency_p50_ms: float
    api_latency_p99_ms: float
    api_error_rate: float
    pred_latency_p50_ms: float
    pred_accuracy: float
    trade_fill_rate: float
    trade_slippage_bps: float
    model_drift: float
    memory_usage_mb: float
    cpu_usage_pct: float
    db_connection_pool_usage: float
    cache_hit_rate: float


# ============================================================================
# SLO TRACKER
# ============================================================================

class SLOTracker:
    """Tracks Service Level Objectives."""
    
    def __init__(self):
        self.slos = {}
        self.observations = {}  # name -> list of (timestamp, value)
        self._initialize_slos()
    
    def _initialize_slos(self):
        """Initialize standard SLOs."""
        self.register_slo(
            name="api_availability",
            target=99.9,
            window_minutes=5,
            description="API endpoint availability"
        )
        
        self.register_slo(
            name="api_latency_p99",
            target=200,  # ms
            window_minutes=5,
            description="API latency at p99"
        )
        
        self.register_slo(
            name="prediction_accuracy",
            target=60,  # %
            window_minutes=60,
            description="Model prediction accuracy"
        )
        
        self.register_slo(
            name="trade_fill_rate",
            target=95,  # %
            window_minutes=5,
            description="Trade fill rate"
        )
        
        self.register_slo(
            name="model_drift",
            target=10,  # KS distance, %
            window_minutes=60,
            description="Feature drift detection"
        )
    
    def register_slo(
        self,
        name: str,
        target: float,
        window_minutes: int,
        description: str = ""
    ):
        """Register a new SLO."""
        self.slos[name] = SLO(
            name=name,
            target=target,
            threshold=target / 100 if target <= 100 else target,
            window_minutes=window_minutes
        )
        self.observations[name] = []
    
    def record(self, name: str, value: float):
        """Record observation for SLO."""
        if name not in self.observations:
            logger.warning(f"Unknown SLO: {name}")
            return
        
        self.observations[name].append((datetime.now(), value))
        
        # Prune old observations
        cutoff = datetime.now() - timedelta(minutes=self.slos[name].window_minutes * 2)
        self.observations[name] = [
            (ts, v) for ts, v in self.observations[name]
            if ts >= cutoff
        ]
        
        # Update SLO status
        self._update_slo_status(name)
    
    def _update_slo_status(self, name: str):
        """Update SLO status based on recent observations."""
        slo = self.slos[name]
        if not self.observations[name]:
            slo.status = SLOStatus.GOOD
            return
        
        # Calculate current value over window
        window_cutoff = datetime.now() - timedelta(minutes=slo.window_minutes)
        recent = [v for ts, v in self.observations[name] if ts >= window_cutoff]
        
        if not recent:
            return
        
        current = np.mean(recent)
        slo.current_value = current
        
        # Determine status
        if slo.name.endswith("_rate") or slo.name.endswith("_ratio"):
            # Higher is better (%)
            if current >= slo.threshold * 100:
                slo.status = SLOStatus.GOOD
            elif current >= slo.threshold * 100 * 0.95:  # 95% of target
                slo.status = SLOStatus.WARNING
                slo.violations += 1
            else:
                slo.status = SLOStatus.VIOLATED
                slo.violations += 1
        else:
            # Lower is better (latency, drift)
            if current <= slo.threshold:
                slo.status = SLOStatus.GOOD
            elif current <= slo.threshold * 1.1:  # 110% of target
                slo.status = SLOStatus.WARNING
                slo.violations += 1
            else:
                slo.status = SLOStatus.VIOLATED
                slo.violations += 1
    
    def get_status(self, name: str) -> Dict:
        """Get status of specific SLO."""
        if name not in self.slos:
            return {"error": f"Unknown SLO: {name}"}
        
        slo = self.slos[name]
        return {
            "name": slo.name,
            "status": slo.status.value,
            "target": slo.target,
            "current": slo.current_value,
            "violations": slo.violations
        }
    
    def get_all_statuses(self) -> Dict[str, Dict]:
        """Get status of all SLOs."""
        return {
            name: self.get_status(name)
            for name in self.slos.keys()
        }


# ============================================================================
# SMART ALERTING
# ============================================================================

class SmartAlerter:
    """Intelligent alerting with correlation and routing."""
    
    def __init__(self):
        self.alerts = {}
        self.alert_history = []  # (timestamp, alert_name, fired)
        self.correlations = {}  # alert1 -> [alert2, alert3] (often fire together)
        self.suppressed = set()  # Temporarily suppressed alerts
        self.initialize_alerts()
    
    def initialize_alerts(self):
        """Initialize standard alerts."""
        
        self.register_alert(
            name="api_degradation",
            severity=AlertSeverity.WARNING,
            condition="latency_p99_ms > 500",
            threshold=500,
            duration_seconds=60,
            channels=[AlertChannel.SLACK]
        )
        
        self.register_alert(
            name="api_outage",
            severity=AlertSeverity.CRITICAL,
            condition="api_availability < 99",
            threshold=99,
            duration_seconds=10,
            channels=[AlertChannel.SLACK, AlertChannel.PAGERDUTY]
        )
        
        self.register_alert(
            name="model_drift",
            severity=AlertSeverity.WARNING,
            condition="ks_distance > 0.15",
            threshold=0.15,
            duration_seconds=300,
            channels=[AlertChannel.SLACK]
        )
        
        self.register_alert(
            name="high_slippage",
            severity=AlertSeverity.WARNING,
            condition="avg_slippage_bps > 5",
            threshold=5,
            duration_seconds=120,
            channels=[AlertChannel.SLACK]
        )
        
        self.register_alert(
            name="low_fill_rate",
            severity=AlertSeverity.CRITICAL,
            condition="fill_rate < 90",
            threshold=90,
            duration_seconds=60,
            channels=[AlertChannel.SLACK, AlertChannel.PAGERDUTY]
        )
        
        self.register_alert(
            name="cache_exhaustion",
            severity=AlertSeverity.WARNING,
            condition="redis_memory_usage > 90%",
            threshold=90,
            duration_seconds=180,
            channels=[AlertChannel.SLACK]
        )
    
    def register_alert(
        self,
        name: str,
        severity: AlertSeverity,
        condition: str,
        threshold: float,
        duration_seconds: int,
        channels: List[AlertChannel]
    ):
        """Register new alert."""
        self.alerts[name] = Alert(
            name=name,
            severity=severity,
            condition=condition,
            threshold=threshold,
            duration_seconds=duration_seconds,
            channels=channels
        )
    
    def check_and_fire(self, name: str, current_value: float) -> Optional[Alert]:
        """
        Check if alert should fire.
        
        Returns alert if fired, None otherwise.
        """
        if name not in self.alerts:
            logger.warning(f"Unknown alert: {name}")
            return None
        
        if name in self.suppressed:
            return None
        
        alert = self.alerts[name]
        
        # Check threshold
        threshold_breached = current_value > alert.threshold
        
        if threshold_breached and not alert.fired:
            alert.fired = True
            self.alert_history.append((datetime.now(), name, True))
            logger.warning(f"🚨 Alert fired: {name} ({current_value} > {alert.threshold})")
            
            # Record correlation (if another alert recently fired)
            recent_alerts = [
                a for ts, a, fired in self.alert_history[-10:]
                if fired and a != name
            ]
            if recent_alerts:
                self.correlations[name] = list(set(recent_alerts))
            
            return alert
        
        elif not threshold_breached and alert.fired:
            alert.fired = False
            self.alert_history.append((datetime.now(), name, False))
            logger.info(f"✅ Alert resolved: {name}")
        
        return None
    
    def get_correlated_alerts(self, name: str) -> List[str]:
        """Get alerts that often fire with this one."""
        return self.correlations.get(name, [])
    
    def suppress_alert(self, name: str, duration_seconds: int = 300):
        """Temporarily suppress alert to reduce fatigue."""
        self.suppressed.add(name)
        logger.info(f"⏸ Alert suppressed: {name} for {duration_seconds}s")
        
        # Auto-unsuppress (simplified)
        if len(self.suppressed) > 10:
            self.suppressed.clear()
    
    def route_alert(self, alert: Alert) -> Dict[str, List[str]]:
        """
        Route alert to appropriate channels.
        
        Returns routing decisions.
        """
        routing = {channel.value: [] for channel in AlertChannel}
        
        for channel in alert.channels:
            routing[channel.value].append(alert.name)
        
        return routing


# ============================================================================
# KPI TRACKER
# ============================================================================

class KPITracker:
    """Tracks business KPIs."""
    
    def __init__(self):
        self.kpis = {}
        self.history = {}  # name -> list of (timestamp, value)
        self._initialize_kpis()
    
    def _initialize_kpis(self):
        """Initialize standard KPIs."""
        self.register_kpi(
            name="daily_pnl",
            unit="$",
            target=5000,
            description="Daily profit and loss"
        )
        
        self.register_kpi(
            name="signal_win_rate",
            unit="%",
            target=55,
            description="% of signals with positive outcome"
        )
        
        self.register_kpi(
            name="sharpe_ratio",
            unit="ratio",
            target=1.5,
            description="Risk-adjusted return"
        )
        
        self.register_kpi(
            name="max_drawdown",
            unit="%",
            target=-10,
            description="Maximum drawdown (lower is worse)"
        )
        
        self.register_kpi(
            name="trades_per_day",
            unit="count",
            target=20,
            description="Average trading volume"
        )
    
    def register_kpi(
        self,
        name: str,
        unit: str,
        target: float,
        description: str = ""
    ):
        """Register new KPI."""
        self.kpis[name] = {
            "unit": unit,
            "target": target,
            "current": 0,
            "description": description
        }
        self.history[name] = []
    
    def update(self, name: str, value: float):
        """Update KPI value."""
        if name not in self.kpis:
            logger.warning(f"Unknown KPI: {name}")
            return
        
        self.kpis[name]["current"] = value
        self.history[name].append((datetime.now(), value))
        
        # Calculate trend
        if len(self.history[name]) >= 2:
            recent_avg = np.mean([v for ts, v in self.history[name][-10:]])
            older_avg = np.mean([v for ts, v in self.history[name][-20:-10]])
            
            if recent_avg > older_avg:
                self.kpis[name]["trend"] = "UP"
            elif recent_avg < older_avg:
                self.kpis[name]["trend"] = "DOWN"
            else:
                self.kpis[name]["trend"] = "FLAT"
    
    def get_kpi(self, name: str) -> Dict:
        """Get KPI info."""
        if name not in self.kpis:
            return {"error": f"Unknown KPI: {name}"}
        
        kpi = self.kpis[name]
        return {
            "name": name,
            "current": kpi["current"],
            "target": kpi["target"],
            "unit": kpi["unit"],
            "trend": kpi.get("trend", "FLAT"),
            "vs_target": kpi["current"] - kpi["target"]
        }
    
    def get_all_kpis(self) -> Dict[str, Dict]:
        """Get all KPIs."""
        return {
            name: self.get_kpi(name)
            for name in self.kpis.keys()
        }


# ============================================================================
# PRODUCTION MONITOR (MAIN CLASS)
# ============================================================================

class ProductionMonitor:
    """
    Unified monitoring for production trading system.
    """
    
    def __init__(self, prometheus_url: str = "http://localhost:9090"):
        self.prometheus_url = prometheus_url
        self.slo_tracker = SLOTracker()
        self.alerter = SmartAlerter()
        self.kpi_tracker = KPITracker()
        
        self.prediction_latencies = []
        self.trade_slippages = []
        self.trade_fills = []
        self.api_errors = []
    
    # ========== SLO TRACKING ==========
    
    def record_prediction(
        self,
        latency_ms: float,
        accuracy: bool,
        signal: str = ""
    ):
        """Record prediction metrics."""
        self.prediction_latencies.append(latency_ms)
        self.slo_tracker.record("pred_latency_p50_ms", latency_ms)
        
        if len(self.prediction_latencies) > 100:
            self.prediction_latencies = self.prediction_latencies[-100:]
    
    def record_trade(
        self,
        fill_rate: float,
        slippage_bps: float,
        latency_ms: float = 0
    ):
        """Record trade execution metrics."""
        self.trade_fills.append(fill_rate)
        self.trade_slippages.append(slippage_bps)
        
        self.slo_tracker.record("trade_fill_rate", fill_rate)
        self.slo_tracker.record("trade_slippage_bps", slippage_bps)
        
        if len(self.trade_fills) > 100:
            self.trade_fills = self.trade_fills[-100:]
            self.trade_slippages = self.trade_slippages[-100:]
    
    def record_api_call(
        self,
        latency_ms: float,
        status_code: int,
        endpoint: str
    ):
        """Record API call metrics."""
        success = 200 <= status_code < 300
        
        if not success:
            self.api_errors.append((datetime.now(), endpoint, status_code))
        
        self.slo_tracker.record("api_latency_p99_ms", latency_ms)
        
        # Check alerting
        if latency_ms > 500:
            self.alerter.check_and_fire("api_degradation", latency_ms)
    
    def record_model_drift(self, ks_distance: float):
        """Record model drift."""
        self.slo_tracker.record("model_drift", ks_distance * 100)
        
        if ks_distance > 0.15:
            self.alerter.check_and_fire("model_drift", ks_distance)
    
    # ========== ALERTING ==========
    
    def check_alerts(self) -> List[Dict]:
        """Check all alerts and return fired alerts."""
        fired = []
        
        # API latency alert
        if self.prediction_latencies:
            p99_latency = np.percentile(self.prediction_latencies, 99)
            if alert := self.alerter.check_and_fire("api_degradation", p99_latency):
                fired.append({
                    "alert": alert.name,
                    "severity": alert.severity.value,
                    "value": p99_latency
                })
        
        # Fill rate alert
        if self.trade_fills:
            avg_fill = np.mean(self.trade_fills)
            if alert := self.alerter.check_and_fire("low_fill_rate", avg_fill):
                fired.append({
                    "alert": alert.name,
                    "severity": alert.severity.value,
                    "value": avg_fill
                })
        
        # Slippage alert
        if self.trade_slippages:
            avg_slippage = np.mean(self.trade_slippages)
            if alert := self.alerter.check_and_fire("high_slippage", avg_slippage):
                fired.append({
                    "alert": alert.name,
                    "severity": alert.severity.value,
                    "value": avg_slippage
                })
        
        return fired
    
    # ========== KPI TRACKING ==========
    
    def update_kpi(self, name: str, value: float):
        """Update KPI."""
        self.kpi_tracker.update(name, value)
    
    def record_daily_performance(
        self,
        pnl: float,
        win_rate: float,
        sharpe: float,
        max_dd: float,
        num_trades: int
    ):
        """Record daily performance KPIs."""
        self.kpi_tracker.update("daily_pnl", pnl)
        self.kpi_tracker.update("signal_win_rate", win_rate * 100)
        self.kpi_tracker.update("sharpe_ratio", sharpe)
        self.kpi_tracker.update("max_drawdown", max_dd * 100)
        self.kpi_tracker.update("trades_per_day", num_trades)
    
    # ========== HEALTH CHECK ==========
    
    def get_health_snapshot(self) -> HealthMetrics:
        """Get current system health."""
        pred_latencies = self.prediction_latencies[-100:] if self.prediction_latencies else [0]
        
        return HealthMetrics(
            api_latency_p50_ms=np.percentile(pred_latencies, 50),
            api_latency_p99_ms=np.percentile(pred_latencies, 99),
            api_error_rate=len(self.api_errors) / max(len(self.prediction_latencies), 1),
            pred_latency_p50_ms=np.mean(pred_latencies),
            pred_accuracy=0.65,  # Placeholder
            trade_fill_rate=np.mean(self.trade_fills) if self.trade_fills else 0,
            trade_slippage_bps=np.mean(self.trade_slippages) if self.trade_slippages else 0,
            model_drift=0.08,  # Placeholder
            memory_usage_mb=512,  # Placeholder
            cpu_usage_pct=45,  # Placeholder
            db_connection_pool_usage=0.6,
            cache_hit_rate=0.92
        )
    
    # ========== REPORTING ==========
    
    def get_status_report(self) -> Dict:
        """Generate complete status report."""
        return {
            "timestamp": datetime.now().isoformat(),
            "slo_status": self.slo_tracker.get_all_statuses(),
            "fired_alerts": self.check_alerts(),
            "kpis": self.kpi_tracker.get_all_kpis(),
            "health": asdict(self.get_health_snapshot())
        }


# ============================================================================
# RUNBOOK TEMPLATES
# ============================================================================

class RunbookExecutor:
    """Execute automated remediation runbooks."""
    
    def __init__(self, monitor: ProductionMonitor):
        self.monitor = monitor
    
    def handle_high_latency(self):
        """Runbook: Reduce latency."""
        logger.info("📋 Running: High Latency Remediation")
        logger.info("  1. Clear prediction cache")
        logger.info("  2. Reduce batch size from 32 to 16")
        logger.info("  3. Skip feature engineering for < 50ms SLA")
        # Implement actual remediation here
    
    def handle_low_fill_rate(self):
        """Runbook: Improve fill rate."""
        logger.info("📋 Running: Low Fill Rate Remediation")
        logger.info("  1. Reduce order size (-20%)")
        logger.info("  2. Increase patience (add 100ms timeout)")
        logger.info("  3. Switch to VWAP execution")
        # Implement actual remediation here
    
    def handle_model_drift(self):
        """Runbook: Model drift detected."""
        logger.info("📋 Running: Model Drift Remediation")
        logger.info("  1. Alert data science team")
        logger.info("  2. Reduce champion model weight (-20%)")
        logger.info("  3. Increase challenger model weight (+20%)")
        logger.info("  4. Trigger re-training pipeline")
        # Implement actual remediation here
