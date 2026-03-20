"""
GRAFANA DASHBOARD CONFIGURATION & SETUP

Pre-configured dashboards for production monitoring:
- System Health Dashboard (API, database, infrastructure)
- Trading Performance Dashboard (PnL, metrics, signals)
- Risk Management Dashboard (VaR, stress tests, positions)
- Model Performance Dashboard (accuracy, drift, A/B testing)
- Resource Utilization Dashboard (latency, throughput, cache)
- Alert Status Dashboard (real-time alerts, incidents)

Usage:
    from production_hardening.monitoring_dashboards import GrafanaDashboardBuilder
    
    builder = GrafanaDashboardBuilder()
    
    # Create all standard dashboards
    dashboards = builder.create_all_dashboards()
    
    # Export to JSON for Grafana import
    for name, dashboard in dashboards.items():
        save_json(f"dashboards/{name}.json", dashboard)
"""

import json
from dataclasses import dataclass
from typing import Dict, List, Any
from datetime import datetime


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class MetricTarget:
    """Prometheus metric query."""
    expr: str
    legendFormat: str
    refId: str


@dataclass
class Panel:
    """Dashboard panel (graph, gauge, table, etc)."""
    title: str
    type: str  # "graph", "gauge", "stat", "table"
    dataSource: str = "Prometheus"
    targets: List[MetricTarget] = None
    gridPos: Dict[str, int] = None  # x, y, w, h


# ============================================================================
# DASHBOARD BUILDER
# ============================================================================

class GrafanaDashboardBuilder:
    """Build Grafana dashboards with Prometheus metrics."""
    
    def __init__(self, datasource_name: str = "Prometheus"):
        self.datasource = datasource_name
    
    def create_system_health_dashboard(self) -> Dict[str, Any]:
        """Dashboard: System Health (API, database, infrastructure)."""
        return {
            "dashboard": {
                "id": None,
                "uid": "system-health",
                "title": "System Health",
                "tags": ["production", "system"],
                "timezone": "UTC",
                "panels": [
                    # Row 1: API Health
                    self._create_panel(
                        title="API Availability",
                        type="gauge",
                        targets=[
                            {
                                "expr": "100 * (1 - (increase(api_errors_total[5m]) / increase(api_requests_total[5m])))",
                                "legendFormat": "Availability %",
                                "refId": "A"
                            }
                        ],
                        gridPos={"x": 0, "y": 0, "w": 6, "h": 8},
                        thresholds="60,90",
                        unit="percent"
                    ),
                    self._create_panel(
                        title="API Latency Percentiles",
                        type="graph",
                        targets=[
                            {"expr": "histogram_quantile(0.50, api_latency_seconds)", "legendFormat": "p50", "refId": "A"},
                            {"expr": "histogram_quantile(0.95, api_latency_seconds)", "legendFormat": "p95", "refId": "B"},
                            {"expr": "histogram_quantile(0.99, api_latency_seconds)", "legendFormat": "p99", "refId": "C"}
                        ],
                        gridPos={"x": 6, "y": 0, "w": 12, "h": 8},
                        unit="s"
                    ),
                    self._create_panel(
                        title="Error Rate",
                        type="graph",
                        targets=[
                            {"expr": "rate(api_errors_total[1m])", "legendFormat": "errors/sec", "refId": "A"}
                        ],
                        gridPos={"x": 18, "y": 0, "w": 6, "h": 8},
                        unit="reqps"
                    ),
                    
                    # Row 2: Database
                    self._create_panel(
                        title="Database Connections",
                        type="graph",
                        targets=[
                            {"expr": "pg_stat_activity_count", "legendFormat": "Active", "refId": "A"},
                            {"expr": "pg_settings_max_connections", "legendFormat": "Max", "refId": "B"}
                        ],
                        gridPos={"x": 0, "y": 8, "w": 8, "h": 8}
                    ),
                    self._create_panel(
                        title="Query Performance",
                        type="graph",
                        targets=[
                            {"expr": "histogram_quantile(0.95, pg_slow_queries)", "legendFormat": "p95", "refId": "A"}
                        ],
                        gridPos={"x": 8, "y": 8, "w": 8, "h": 8},
                        unit="ms"
                    ),
                    self._create_panel(
                        title="Cache Hit Rate",
                        type="gauge",
                        targets=[
                            {"expr": "redis_used_memory_human / redis_maxmemory", "legendFormat": "Usage", "refId": "A"}
                        ],
                        gridPos={"x": 16, "y": 8, "w": 8, "h": 8},
                        thresholds="50,90",
                        unit="percent"
                    ),
                ]
            },
            "overwrite": True
        }
    
    def create_trading_performance_dashboard(self) -> Dict[str, Any]:
        """Dashboard: Trading Performance (PnL, signals, fills)."""
        return {
            "dashboard": {
                "id": None,
                "uid": "trading-performance",
                "title": "Trading Performance",
                "tags": ["production", "trading"],
                "timezone": "UTC",
                "panels": [
                    # KPIs
                    self._create_panel(
                        title="Daily PnL",
                        type="stat",
                        targets=[
                            {"expr": "trading_pnl_daily", "legendFormat": "PnL", "refId": "A"}
                        ],
                        gridPos={"x": 0, "y": 0, "w": 6, "h": 6},
                        unit="$"
                    ),
                    self._create_panel(
                        title="Win Rate",
                        type="gauge",
                        targets=[
                            {"expr": "100 * trading_win_rate", "legendFormat": "%", "refId": "A"}
                        ],
                        gridPos={"x": 6, "y": 0, "w": 6, "h": 6},
                        thresholds="40,50",
                        unit="percent"
                    ),
                    self._create_panel(
                        title="Sharpe Ratio",
                        type="stat",
                        targets=[
                            {"expr": "trading_sharpe_ratio", "legendFormat": "Sharpe", "refId": "A"}
                        ],
                        gridPos={"x": 12, "y": 0, "w": 6, "h": 6}
                    ),
                    self._create_panel(
                        title="Drawdown",
                        type="gauge",
                        targets=[
                            {"expr": "100 * trading_max_drawdown", "legendFormat": "%", "refId": "A"}
                        ],
                        gridPos={"x": 18, "y": 0, "w": 6, "h": 6},
                        thresholds="-20,-10",
                        unit="percent"
                    ),
                    
                    # Charts
                    self._create_panel(
                        title="Cumulative PnL",
                        type="graph",
                        targets=[
                            {"expr": "increase(trading_pnl_total[1d])", "legendFormat": "PnL", "refId": "A"}
                        ],
                        gridPos={"x": 0, "y": 6, "w": 12, "h": 10},
                        unit="$"
                    ),
                    self._create_panel(
                        title="Trade Distribution",
                        type="graph",
                        targets=[
                            {"expr": "trades_per_hour", "legendFormat": "Trades", "refId": "A"}
                        ],
                        gridPos={"x": 12, "y": 6, "w": 12, "h": 10}
                    ),
                    
                    # Statistics
                    self._create_panel(
                        title="Slippage Analysis",
                        type="table",
                        targets=[
                            {"expr": "trading_slippage_bps", "legendFormat": "bps", "refId": "A"}
                        ],
                        gridPos={"x": 0, "y": 16, "w": 24, "h": 6}
                    ),
                ]
            },
            "overwrite": True
        }
    
    def create_risk_dashboard(self) -> Dict[str, Any]:
        """Dashboard: Risk Management (VaR, stress, positions)."""
        return {
            "dashboard": {
                "id": None,
                "uid": "risk-management",
                "title": "Risk Management",
                "tags": ["production", "risk"],
                "timezone": "UTC",
                "panels": [
                    # Current Risk Metrics
                    self._create_panel(
                        title="VaR-95",
                        type="stat",
                        targets=[
                            {"expr": "risk_var_95", "legendFormat": "VaR", "refId": "A"}
                        ],
                        gridPos={"x": 0, "y": 0, "w": 6, "h": 6},
                        unit="$"
                    ),
                    self._create_panel(
                        title="CVaR-95",
                        type="stat",
                        targets=[
                            {"expr": "risk_cvar_95", "legendFormat": "CVaR", "refId": "A"}
                        ],
                        gridPos={"x": 6, "y": 0, "w": 6, "h": 6},
                        unit="$"
                    ),
                    self._create_panel(
                        title="Current Leverage",
                        type="gauge",
                        targets=[
                            {"expr": "risk_leverage_ratio", "legendFormat": "x", "refId": "A"}
                        ],
                        gridPos={"x": 12, "y": 0, "w": 6, "h": 6},
                        thresholds="1.5,3.0"
                    ),
                    self._create_panel(
                        title="Kill-Switch Status",
                        type="stat",
                        targets=[
                            {"expr": "risk_kill_switch_active", "legendFormat": "Active", "refId": "A"}
                        ],
                        gridPos={"x": 18, "y": 0, "w": 6, "h": 6}
                    ),
                    
                    # Trends
                    self._create_panel(
                        title="VaR Over Time",
                        type="graph",
                        targets=[
                            {"expr": "risk_var_95", "legendFormat": "VaR-95", "refId": "A"}
                        ],
                        gridPos={"x": 0, "y": 6, "w": 12, "h": 10},
                        unit="$"
                    ),
                    self._create_panel(
                        title="Leverage Over Time",
                        type="graph",
                        targets=[
                            {"expr": "risk_leverage_ratio", "legendFormat": "Leverage", "refId": "A"},
                            {"expr": "vector(3.0)", "legendFormat": "Limit", "refId": "B"}
                        ],
                        gridPos={"x": 12, "y": 6, "w": 12, "h": 10}
                    ),
                    
                    # Stress Tests
                    self._create_panel(
                        title="Stress Test Results",
                        type="table",
                        targets=[
                            {"expr": "risk_stress_test_results", "legendFormat": "Scenario", "refId": "A"}
                        ],
                        gridPos={"x": 0, "y": 16, "w": 24, "h": 8}
                    ),
                ]
            },
            "overwrite": True
        }
    
    def create_model_performance_dashboard(self) -> Dict[str, Any]:
        """Dashboard: Model Performance (accuracy, drift, A/B testing)."""
        return {
            "dashboard": {
                "id": None,
                "uid": "model-performance",
                "title": "Model Performance",
                "tags": ["production", "ml"],
                "timezone": "UTC",
                "panels": [
                    # Current Model Metrics
                    self._create_panel(
                        title="Prediction Accuracy",
                        type="gauge",
                        targets=[
                            {"expr": "100 * model_accuracy", "legendFormat": "%", "refId": "A"}
                        ],
                        gridPos={"x": 0, "y": 0, "w": 6, "h": 6},
                        thresholds="50,60",
                        unit="percent"
                    ),
                    self._create_panel(
                        title="Feature Drift (KS)",
                        type="gauge",
                        targets=[
                            {"expr": "model_feature_drift_ks", "legendFormat": "KS", "refId": "A"}
                        ],
                        gridPos={"x": 6, "y": 0, "w": 6, "h": 6},
                        thresholds="0.05,0.15"
                    ),
                    self._create_panel(
                        title="Prediction Latency p99",
                        type="stat",
                        targets=[
                            {"expr": "histogram_quantile(0.99, model_latency_seconds)", "legendFormat": "ms", "refId": "A"}
                        ],
                        gridPos={"x": 12, "y": 0, "w": 6, "h": 6},
                        unit="ms"
                    ),
                    self._create_panel(
                        title="Active Model",
                        type="stat",
                        targets=[
                            {"expr": "model_active_version", "legendFormat": "Version", "refId": "A"}
                        ],
                        gridPos={"x": 18, "y": 0, "w": 6, "h": 6}
                    ),
                    
                    # Accuracy Over Time
                    self._create_panel(
                        title="Accuracy Trend",
                        type="graph",
                        targets=[
                            {"expr": "100 * model_accuracy", "legendFormat": "Accuracy", "refId": "A"}
                        ],
                        gridPos={"x": 0, "y": 6, "w": 12, "h": 10},
                        unit="percent"
                    ),
                    
                    # A/B Testing (Champion vs Challenger)
                    self._create_panel(
                        title="Champion vs Challenger",
                        type="graph",
                        targets=[
                            {"expr": "100 * model_accuracy{version='champion'}", "legendFormat": "Champion", "refId": "A"},
                            {"expr": "100 * model_accuracy{version='challenger'}", "legendFormat": "Challenger", "refId": "B"}
                        ],
                        gridPos={"x": 12, "y": 6, "w": 12, "h": 10},
                        unit="percent"
                    ),
                    
                    # Drift Detection
                    self._create_panel(
                        title="Feature Drift Timeline",
                        type="graph",
                        targets=[
                            {"expr": "model_feature_drift_ks", "legendFormat": "Drift", "refId": "A"}
                        ],
                        gridPos={"x": 0, "y": 16, "w": 24, "h": 8}
                    ),
                ]
            },
            "overwrite": True
        }
    
    def create_resource_utilization_dashboard(self) -> Dict[str, Any]:
        """Dashboard: Resources (throughput, latency, memory, CPU)."""
        return {
            "dashboard": {
                "id": None,
                "uid": "resource-utilization",
                "title": "Resource Utilization",
                "tags": ["production", "infrastructure"],
                "timezone": "UTC",
                "panels": [
                    # Current Metrics
                    self._create_panel(
                        title="API Throughput",
                        type="stat",
                        targets=[
                            {"expr": "rate(api_requests_total[1m])", "legendFormat": "req/s", "refId": "A"}
                        ],
                        gridPos={"x": 0, "y": 0, "w": 6, "h": 6},
                        unit="reqps"
                    ),
                    self._create_panel(
                        title="CPU Usage",
                        type="gauge",
                        targets=[
                            {"expr": "100 * (1 - avg(rate(node_cpu_seconds_total{mode='idle'}[5m])))", "legendFormat": "%", "refId": "A"}
                        ],
                        gridPos={"x": 6, "y": 0, "w": 6, "h": 6},
                        thresholds="50,80",
                        unit="percent"
                    ),
                    self._create_panel(
                        title="Memory Usage",
                        type="gauge",
                        targets=[
                            {"expr": "(node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes) / node_memory_MemTotal_bytes * 100", "legendFormat": "%", "refId": "A"}
                        ],
                        gridPos={"x": 12, "y": 0, "w": 6, "h": 6},
                        thresholds="60,85",
                        unit="percent"
                    ),
                    self._create_panel(
                        title="Cache Hit Rate",
                        type="gauge",
                        targets=[
                            {"expr": "100 * redis_keyspace_hits_total / (redis_keyspace_hits_total + redis_keyspace_misses_total)", "legendFormat": "%", "refId": "A"}
                        ],
                        gridPos={"x": 18, "y": 0, "w": 6, "h": 6},
                        thresholds="70,90",
                        unit="percent"
                    ),
                    
                    # Throughput Over Time
                    self._create_panel(
                        title="Request Rate",
                        type="graph",
                        targets=[
                            {"expr": "rate(api_requests_total[1m])", "legendFormat": "req/s", "refId": "A"}
                        ],
                        gridPos={"x": 0, "y": 6, "w": 12, "h": 10},
                        unit="reqps"
                    ),
                    
                    # System Resources
                    self._create_panel(
                        title="CPU & Memory",
                        type="graph",
                        targets=[
                            {"expr": "100 * (1 - avg(rate(node_cpu_seconds_total{mode='idle'}[5m])))", "legendFormat": "CPU %", "refId": "A"},
                            {"expr": "(node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes) / node_memory_MemTotal_bytes * 100", "legendFormat": "Memory %", "refId": "B"}
                        ],
                        gridPos={"x": 12, "y": 6, "w": 12, "h": 10},
                        unit="percent"
                    ),
                    
                    # Disk Space
                    self._create_panel(
                        title="Disk Usage",
                        type="table",
                        targets=[
                            {"expr": "node_filesystem_avail_bytes / node_filesystem_size_bytes * 100", "legendFormat": "Avail %", "refId": "A"}
                        ],
                        gridPos={"x": 0, "y": 16, "w": 24, "h": 8}
                    ),
                ]
            },
            "overwrite": True
        }
    
    def create_alerts_dashboard(self) -> Dict[str, Any]:
        """Dashboard: Active Alerts & Incidents."""
        return {
            "dashboard": {
                "id": None,
                "uid": "alerts-status",
                "title": "Alerts & Incidents",
                "tags": ["production", "alerts"],
                "timezone": "UTC",
                "panels": [
                    # Alert Summary
                    self._create_panel(
                        title="Critical Alerts",
                        type="stat",
                        targets=[
                            {"expr": "count(ALERTS{severity='critical'})", "legendFormat": "Count", "refId": "A"}
                        ],
                        gridPos={"x": 0, "y": 0, "w": 6, "h": 6}
                    ),
                    self._create_panel(
                        title="Warning Alerts",
                        type="stat",
                        targets=[
                            {"expr": "count(ALERTS{severity='warning'})", "legendFormat": "Count", "refId": "A"}
                        ],
                        gridPos={"x": 6, "y": 0, "w": 6, "h": 6}
                    ),
                    self._create_panel(
                        title="MTTR (Mean Time To Resolve)",
                        type="stat",
                        targets=[
                            {"expr": "avg(alert_resolution_time_seconds)", "legendFormat": "Minutes", "refId": "A"}
                        ],
                        gridPos={"x": 12, "y": 0, "w": 6, "h": 6},
                        unit="s"
                    ),
                    self._create_panel(
                        title="Incident Rate (7d)",
                        type="stat",
                        targets=[
                            {"expr": "rate(incidents_total[7d])", "legendFormat": "per day", "refId": "A"}
                        ],
                        gridPos={"x": 18, "y": 0, "w": 6, "h": 6}
                    ),
                    
                    # Alert Timeline
                    self._create_panel(
                        title="Alert History",
                        type="graph",
                        targets=[
                            {"expr": "increase(alerts_fired_total[1h])", "legendFormat": "Fired", "refId": "A"}
                        ],
                        gridPos={"x": 0, "y": 6, "w": 12, "h": 10}
                    ),
                    
                    # Active Alerts
                    self._create_panel(
                        title="Current Alerts",
                        type="table",
                        targets=[
                            {"expr": "ALERTS", "legendFormat": "Alert", "refId": "A"}
                        ],
                        gridPos={"x": 12, "y": 6, "w": 12, "h": 10}
                    ),
                ]
            },
            "overwrite": True
        }
    
    def create_all_dashboards(self) -> Dict[str, Dict[str, Any]]:
        """Create all dashboards."""
        return {
            "system_health": self.create_system_health_dashboard(),
            "trading_performance": self.create_trading_performance_dashboard(),
            "risk_management": self.create_risk_dashboard(),
            "model_performance": self.create_model_performance_dashboard(),
            "resource_utilization": self.create_resource_utilization_dashboard(),
            "alerts": self.create_alerts_dashboard(),
        }
    
    def _create_panel(
        self,
        title: str,
        type: str,
        targets: List[Dict[str, str]],
        gridPos: Dict[str, int],
        unit: str = "",
        thresholds: str = ""
    ) -> Dict[str, Any]:
        """Helper to create a panel."""
        panel = {
            "title": title,
            "type": type,
            "dataSource": self.datasource,
            "gridPos": gridPos,
            "targets": targets,
        }
        
        if unit:
            panel["fieldConfig"] = {"defaults": {"unit": unit}}
        
        if thresholds and type == "gauge":
            panel["options"] = {"thresholds": {"mode": "absolute", "steps": [
                {"color": "green", "value": None},
                {"color": "yellow", "value": float(thresholds.split(",")[0])},
                {"color": "red", "value": float(thresholds.split(",")[1])}
            ]}}
        
        return panel


# ============================================================================
# PROMETHEUS ALERT RULES
# ============================================================================

PROMETHEUS_ALERT_RULES = """
# Production Alert Rules for Trading System

groups:
  - name: api_alerts
    interval: 30s
    rules:
      - alert: APILatencyHigh
        expr: histogram_quantile(0.99, rate(api_latency_seconds_bucket[5m])) > 0.5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "API latency p99 > 500ms"
          description: "API p99 latency is {{ $value }}s"

      - alert: APIErrorRateHigh
        expr: rate(api_errors_total[5m]) > 0.01
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "API error rate > 1%"
          description: "API error rate is {{ $value }}/s"

      - alert: APIUnavailable
        expr: up{job="api"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "API is down"

  - name: database_alerts
    interval: 30s
    rules:
      - alert: DatabaseConnectionsFull
        expr: pg_stat_activity_count > 90
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Database connections nearly maxed"
          description: "Active connections: {{ $value }}"

      - alert: DatabaseQuerySlow
        expr: histogram_quantile(0.95, pg_slow_queries) > 5000
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Database queries slow (p95 > 5s)"

      - alert: DatabaseDiskFull
        expr: pg_database_size_bytes > (pg_database_max_size_bytes * 0.9)
        labels:
          severity: critical
        annotations:
          summary: "Database disk 90% full"

  - name: risk_alerts
    interval: 30s
    rules:
      - alert: ExcessiveLeverage
        expr: risk_leverage_ratio > 2.8
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Leverage approaching limit (3.0x)"
          description: "Current leverage: {{ $value }}x"

      - alert: DrawdownAlert
        expr: risk_drawdown_pct < -15
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Drawdown exceeds -15%"
          description: "Current drawdown: {{ $value }}%"

      - alert: KillSwitchTriggered
        expr: risk_kill_switch_active == 1
        labels:
          severity: critical
        annotations:
          summary: "Risk kill-switch triggered"
          description: "Trading halted due to risk limits"

  - name: ml_alerts
    interval: 30s
    rules:
      - alert: ModelDrift
        expr: model_feature_drift_ks > 0.15
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Model feature drift detected"
          description: "KS distance: {{ $value }}"

      - alert: PredictionAccuracyLow
        expr: model_accuracy < 0.55
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "Model accuracy below target (55%)"
          description: "Current accuracy: {{ $value | humanizePercentage }}"

      - alert: PredictionLatencyHigh
        expr: histogram_quantile(0.99, model_latency_seconds) > 1.0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Model prediction latency > 1s"

  - name: resource_alerts
    interval: 30s
    rules:
      - alert: CPUUsageHigh
        expr: 100 * (1 - avg(rate(node_cpu_seconds_total{mode="idle"}[5m]))) > 80
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "CPU usage > 80%"
          description: "Current: {{ $value }}%"

      - alert: MemoryUsageHigh
        expr: (1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100 > 85
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Memory usage > 85%"
          description: "Current: {{ $value }}%"

      - alert: DiskSpaceLow
        expr: node_filesystem_avail_bytes / node_filesystem_size_bytes < 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Disk space < 10%"
          description: "Available: {{ $value | humanize }}B"

  - name: slo_alerts
    interval: 1m
    rules:
      - alert: SLOViolation_Availability
        expr: up:api_availability_5m < 0.999
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "SLO violated: Availability < 99.9%"

      - alert: SLOViolation_Latency
        expr: histogram_quantile(0.99, up:api_latency_5m) > 0.2
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "SLO violated: Latency p99 > 200ms"

      - alert: SLOViolation_FillRate
        expr: up:trade_fill_rate_5m < 0.95
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "SLO violated: Fill rate < 95%"
"""


# ============================================================================
# SETUP UTILITIES
# ============================================================================

def export_dashboards_to_json(builder: GrafanaDashboardBuilder, output_dir: str = "dashboards"):
    """Export all dashboards to JSON files."""
    import os
    import json
    
    os.makedirs(output_dir, exist_ok=True)
    
    dashboards = builder.create_all_dashboards()
    for name, dashboard in dashboards.items():
        filepath = os.path.join(output_dir, f"{name}.json")
        with open(filepath, "w") as f:
            json.dump(dashboard, f, indent=2)
        print(f"✓ Exported dashboard: {filepath}")


def export_prometheus_rules(output_file: str = "alerts.yml"):
    """Export Prometheus alert rules."""
    with open(output_file, "w") as f:
        f.write(PROMETHEUS_ALERT_RULES)
    print(f"✓ Exported Prometheus rules: {output_file}")


def print_dashboard_setup_guide():
    """Print setup instructions."""
    print("""
╔════════════════════════════════════════════════════════════════════╗
║         GRAFANA DASHBOARD SETUP GUIDE                             ║
╚════════════════════════════════════════════════════════════════════╝

1. START GRAFANA & PROMETHEUS
   docker-compose up grafana prometheus

2. OPEN GRAFANA
   http://localhost:3000
   Default username/password: admin/admin

3. ADD PROMETHEUS DATA SOURCE
   Configuration → Data Sources → Add Prometheus
   URL: http://prometheus:9090
   Save & Test

4. IMPORT DASHBOARDS
   From JSON files:
   - Dashboards → New → Import
   - Upload each dashboard JSON from 'dashboards/' folder
   
   Or use dashboard IDs (if published on Grafana.com):
   - System Health: 1860 (Node Exporter)
   - Trading Perf: 3662 (Prometheus)

5. CONFIGURE ALERTS
   Alerts → Alert Rules → Load from alerts.yml

6. SET UP NOTIFICATION CHANNELS
   Configuration → Notification channels → New channel
   Supported: Slack, Email, PagerDuty, Webhook

7. CREATE ALERT POLICIES
   Alerts → Notification policies
   Route alerts to channels based on severity

SAMPLE GRAFANA DOCKER CONFIG:

environment:
  - GF_SECURITY_ADMIN_PASSWORD=admin
  - GF_INSTALL_PLUGINS=grafana-piechart-panel
  - GF_USERS_ALLOW_SIGN_UP=false
  - GF_SERVER_ROOT_URL=http://grafana:3000

Dashboard Export Path: /var/lib/grafana/dashboards
Alert Rules Path: /etc/prometheus/rules/

""")
