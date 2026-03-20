"""
Prometheus metrics integration for trading model monitoring.

Exports metrics to Prometheus for:
- Real-time performance tracking
- Automatic alerting (via Alertmanager)
- Grafana dashboarding
- SLA/SLO tracking

Metrics collected:
- Trading metrics (PnL, win rate, Sharpe ratio)
- Model metrics (inference time, accuracy)
- System metrics (GPU memory, training loss)
- Data pipeline metrics (fetch latency, data quality)
"""

from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    Summary,
    CollectorRegistry,
    push_to_gateway,
    start_http_server,
)
import time
from typing import Optional, Dict


# ============================================================================
# Global Registry
# ============================================================================

REGISTRY = CollectorRegistry()


# ============================================================================
# Trading Metrics
# ============================================================================

trades_executed_total = Counter(
    "trading_trades_executed_total",
    "Total number of trades executed",
    ["side", "symbol"],
    registry=REGISTRY,
)

trades_profit_loss = Gauge(
    "trading_pnl",
    "Current P&L in USD",
    registry=REGISTRY,
)

win_rate = Gauge(
    "trading_win_rate",
    "Trading win rate (0-1)",
    registry=REGISTRY,
)

sharpe_ratio = Gauge(
    "trading_sharpe_ratio",
    "Sharpe ratio of returns",
    registry=REGISTRY,
)

max_drawdown = Gauge(
    "trading_max_drawdown",
    "Maximum drawdown (0-1)",
    registry=REGISTRY,
)

active_positions = Gauge(
    "trading_active_positions",
    "Number of active positions",
    registry=REGISTRY,
)

portfolio_exposure = Gauge(
    "trading_portfolio_exposure_usd",
    "Total portfolio exposure (notional value)",
    registry=REGISTRY,
)

trade_latency_seconds = Histogram(
    "trading_order_latency_seconds",
    "Order execution latency",
    buckets=(0.01, 0.05, 0.1, 0.5, 1.0, 5.0),
    registry=REGISTRY,
)


# ============================================================================
# Model Metrics
# ============================================================================

model_inference_latency = Histogram(
    "model_inference_latency_seconds",
    "Model inference latency per batch",
    buckets=(0.01, 0.05, 0.1, 0.5, 1.0),
    registry=REGISTRY,
)

model_inference_count = Counter(
    "model_inferences_total",
    "Total number of model inferences",
    ["model_type"],
    registry=REGISTRY,
)

prediction_mae = Gauge(
    "model_prediction_mae",
    "Mean Absolute Error of predictions",
    registry=REGISTRY,
)

prediction_rmse = Gauge(
    "model_prediction_rmse",
    "Root Mean Squared Error of predictions",
    registry=REGISTRY,
)

training_loss = Gauge(
    "model_training_loss",
    "Current training loss",
    registry=REGISTRY,
)

validation_loss = Gauge(
    "model_validation_loss",
    "Current validation loss",
    registry=REGISTRY,
)

model_accuracy = Gauge(
    "model_accuracy",
    "Model accuracy (direction prediction)",
    registry=REGISTRY,
)


# ============================================================================
# System Metrics
# ============================================================================

gpu_memory_used_mb = Gauge(
    "system_gpu_memory_used_mb",
    "GPU memory usage (MB)",
    registry=REGISTRY,
)

gpu_memory_allocated_mb = Gauge(
    "system_gpu_memory_allocated_mb",
    "GPU memory allocated (MB)",
    registry=REGISTRY,
)

training_epoch_duration = Histogram(
    "model_training_epoch_duration_seconds",
    "Time per training epoch",
    registry=REGISTRY,
)

data_fetch_latency = Histogram(
    "data_fetch_latency_seconds",
    "Data fetching latency from source",
    buckets=(0.1, 0.5, 1.0, 5.0, 10.0),
    registry=REGISTRY,
)


# ============================================================================
# Risk Metrics
# ============================================================================

leverage_ratio = Gauge(
    "risk_leverage_ratio",
    "Current portfolio leverage (exposure/equity)",
    registry=REGISTRY,
)

var_95 = Gauge(
    "risk_value_at_risk_95",
    "Value at Risk (95% confidence)",
    registry=REGISTRY,
)

portfolio_beta = Gauge(
    "risk_portfolio_beta",
    "Portfolio beta (market sensitivity)",
    registry=REGISTRY,
)

max_sector_concentration = Gauge(
    "risk_max_sector_concentration",
    "Highest sector concentration ratio",
    registry=REGISTRY,
)

margin_utilization = Gauge(
    "risk_margin_utilization_ratio",
    "Margin utilization (0-1)",
    registry=REGISTRY,
)


# ============================================================================
# Data Quality Metrics
# ============================================================================

data_points_received = Counter(
    "data_points_received_total",
    "Total data points received",
    ["source", "symbol"],
    registry=REGISTRY,
)

data_points_missing = Counter(
    "data_points_missing_total",
    "Total missing data points",
    ["source", "symbol"],
    registry=REGISTRY,
)

data_quality_score = Gauge(
    "data_quality_score",
    "Overall data quality (0-1)",
    registry=REGISTRY,
)


# ============================================================================
# Alerting Thresholds
# ============================================================================

ALERT_THRESHOLDS = {
    "max_drawdown": 0.2,               # Alert if DD > 20%
    "max_leverage": 3.0,                # Alert if leverage > 3x
    "model_inference_latency": 2.0,     # Alert if latency > 2s
    "data_quality": 0.8,                # Alert if quality < 80%
    "margin_utilization": 0.9,          # Alert if margin > 90%
}


# ============================================================================
# Metrics Helper Class
# ============================================================================


class PrometheusMetricsCollector:
    """Centralized metrics collection service."""

    def __init__(self, pushgateway_url: Optional[str] = None, job_name: str = "trading_model"):
        """
        Initialize metrics collector.

        Args:
            pushgateway_url: Prometheus pushgateway URL (e.g., http://localhost:9091)
            job_name: Job name for pushgateway
        """
        self.pushgateway_url = pushgateway_url
        self.job_name = job_name

    def record_trade(
        self, side: str, symbol: str, quantity: float, execution_time_sec: float
    ):
        """Record a trade execution."""
        trades_executed_total.labels(side=side, symbol=symbol).inc(quantity)
        trade_latency_seconds.observe(execution_time_sec)

    def update_pnl_metrics(
        self,
        pnl: float,
        win_rate: float,
        sharpe: float,
        drawdown: float,
        active_pos: int,
        exposure: float,
    ):
        """Update all P&L related metrics."""
        trades_profit_loss.set(pnl)
        globals()["win_rate"].set(win_rate)
        sharpe_ratio.set(sharpe)
        max_drawdown.set(abs(drawdown))
        active_positions.set(active_pos)
        portfolio_exposure.set(exposure)

    def record_inference(self, model_type: str, latency_sec: float, batch_size: int = 1):
        """Record model inference."""
        model_inference_latency.observe(latency_sec)
        model_inference_count.labels(model_type=model_type).inc()

    def update_model_metrics(
        self,
        mae: float,
        rmse: float,
        train_loss: float,
        val_loss: float,
        accuracy: float,
    ):
        """Update model performance metrics."""
        prediction_mae.set(mae)
        prediction_rmse.set(rmse)
        training_loss.set(train_loss)
        validation_loss.set(val_loss)
        model_accuracy.set(accuracy)

    def update_gpu_metrics(self, used_mb: float, allocated_mb: float):
        """Update GPU memory metrics."""
        gpu_memory_used_mb.set(used_mb)
        gpu_memory_allocated_mb.set(allocated_mb)

    def record_data_fetch(self, latency_sec: float, source: str, symbol: str, success: bool):
        """Record data fetching latency."""
        data_fetch_latency.observe(latency_sec)
        data_points_received.labels(source=source, symbol=symbol).inc()

        if not success:
            data_points_missing.labels(source=source, symbol=symbol).inc()

    def update_risk_metrics(
        self,
        leverage: float,
        var_95_val: float,
        beta: float,
        sector_conc: float,
        margin_util: float,
    ):
        """Update risk metrics."""
        leverage_ratio.set(leverage)
        var_95.set(var_95_val)
        portfolio_beta.set(beta)
        max_sector_concentration.set(sector_conc)
        margin_utilization.set(margin_util)

    def update_data_quality(self, quality_score: float):
        """Update data quality metric."""
        data_quality_score.set(quality_score)

    def push_metrics(self):
        """Push metrics to Prometheus pushgateway."""
        if self.pushgateway_url:
            try:
                push_to_gateway(
                    self.pushgateway_url,
                    job=self.job_name,
                    registry=REGISTRY,
                )
                print("✓ Metrics pushed to Prometheus")
            except Exception as e:
                print(f"✗ Failed to push metrics: {e}")

    def check_alerts(self) -> Dict[str, bool]:
        """Check if any metric triggers alerts."""
        alerts = {}

        # Check drawdown alert
        alerts["high_drawdown"] = max_drawdown._value.get() > ALERT_THRESHOLDS["max_drawdown"]

        # Check leverage alert
        alerts["high_leverage"] = leverage_ratio._value.get() > ALERT_THRESHOLDS["max_leverage"]

        # Check inference latency alert
        alerts["high_latency"] = (
            model_inference_latency._sum.get() / max(model_inference_latency._count.get(), 1)
            > ALERT_THRESHOLDS["model_inference_latency"]
        )

        # Check data quality alert
        if hasattr(data_quality_score._value, "get"):
            alerts["low_data_quality"] = (
                data_quality_score._value.get() < ALERT_THRESHOLDS["data_quality"]
            )

        # Check margin alert
        alerts["high_margin_util"] = (
            margin_utilization._value.get() > ALERT_THRESHOLDS["margin_utilization"]
        )

        return alerts


# ============================================================================
# HTTP Server Setup
# ============================================================================


def start_metrics_server(port: int = 8000):
    """Start Prometheus HTTP metrics server."""
    try:
        start_http_server(port, registry=REGISTRY)
        print(f"✓ Prometheus metrics server started on port {port}")
        print(f"  Metrics available at: http://localhost:{port}/metrics")
    except Exception as e:
        print(f"✗ Failed to start metrics server: {e}")


# ============================================================================
# Global Collector Instance
# ============================================================================

prometheus_collector = PrometheusMetricsCollector()


# ============================================================================
# Example Usage
# ============================================================================

if __name__ == "__main__":
    # Start HTTP server
    start_metrics_server(port=8000)

    # Example: Record metrics
    collector = prometheus_collector

    print("\nRecording example metrics...")

    # Record trades
    for i in range(5):
        collector.record_trade(side="BUY", symbol="AAPL", quantity=100, execution_time_sec=0.05)
        time.sleep(0.1)

    # Update P&L metrics
    collector.update_pnl_metrics(
        pnl=5000.0,
        win_rate=0.55,
        sharpe=1.2,
        drawdown=-0.08,
        active_pos=3,
        exposure=50000.0,
    )

    # Record model inference
    for i in range(10):
        collector.record_inference(model_type="lstm", latency_sec=0.15, batch_size=32)
        time.sleep(0.05)

    # Update model metrics
    collector.update_model_metrics(
        mae=2.5,
        rmse=3.1,
        train_loss=0.15,
        val_loss=0.18,
        accuracy=0.65,
    )

    # Update risk metrics
    collector.update_risk_metrics(
        leverage=2.5,
        var_95_val=1500.0,
        beta=0.95,
        sector_conc=0.35,
        margin_util=0.75,
    )

    print("\n✓ Metrics recorded. Visit http://localhost:8000/metrics to view.")
    print("\nAlerts triggered:")
    alerts = collector.check_alerts()
    for alert_name, triggered in alerts.items():
        status = "🔴" if triggered else "🟢"
        print(f"  {status} {alert_name}: {triggered}")

    # Keep server running
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\nMetrics server stopped.")
