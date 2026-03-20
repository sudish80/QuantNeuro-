"""Monitoring and operations: health checks, alerts, metrics logging, and drift checks."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, UTC
from pathlib import Path
import json
import math

import requests

from production_hardening.io_utils import atomic_write_text, file_lock


@dataclass
class HealthStatus:
    data_feed_ok: bool
    model_ok: bool
    execution_ok: bool
    risk_engine_ok: bool


def run_health_checks(data_feed_ok: bool, model_ok: bool, execution_ok: bool, risk_engine_ok: bool) -> HealthStatus:
    return HealthStatus(
        data_feed_ok=data_feed_ok,
        model_ok=model_ok,
        execution_ok=execution_ok,
        risk_engine_ok=risk_engine_ok,
    )


def write_metrics_csv(path: str, metrics: dict[str, float]) -> None:
    if not isinstance(metrics, dict) or not metrics:
        raise ValueError("metrics must be a non-empty dict")
    for key, value in metrics.items():
        if not isinstance(key, str) or not key:
            raise ValueError("all metric names must be non-empty strings")
        if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise ValueError(f"metric '{key}' must be a finite numeric value")

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    header = ["ts_utc"] + sorted(metrics.keys())
    row = [datetime.now(UTC).isoformat()] + [metrics[k] for k in sorted(metrics.keys())]

    with file_lock(out):
        exists = out.exists()
        with out.open("a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if not exists:
                writer.writerow(header)
            writer.writerow(row)


def send_alert(message: str, webhook_url: str | None = None) -> None:
    if webhook_url:
        try:
            requests.post(webhook_url, json={"text": message}, timeout=10)
        except Exception:
            pass
    print(f"[ALERT] {message}")


def drift_score(ref_mean: float, ref_std: float, current_mean: float) -> float:
    if abs(ref_std) < 1e-12:
        return 0.0
    return abs(current_mean - ref_mean) / abs(ref_std)


def check_model_drift(ref_mean: float, ref_std: float, current_mean: float, threshold: float = 2.0) -> tuple[bool, float]:
    score = drift_score(ref_mean, ref_std, current_mean)
    return score >= threshold, score


def generate_metrics_dashboard(metrics_csv: str, output_html: str) -> None:
    csv_path = Path(metrics_csv)
    out_path = Path(output_html)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not csv_path.exists():
        atomic_write_text(out_path, "<html><body><h2>No metrics available yet.</h2></body></html>")
        return

    rows = csv_path.read_text(encoding="utf-8").splitlines()
    if len(rows) < 2:
        atomic_write_text(out_path, "<html><body><h2>No metrics rows available.</h2></body></html>")
        return

    headers = rows[0].split(",")
    data_rows = [r.split(",") for r in rows[1:] if r.strip()]
    values = data_rows[-1]
    latest = dict(zip(headers, values))

    recent = data_rows[-120:]
    labels = [r[0] for r in recent]
    metric_keys = [h for h in headers if h != "ts_utc"]

    chart_datasets = []
    palette = ["#58a6ff", "#3fb950", "#f85149", "#d29922", "#a371f7", "#1f6feb"]
    for i, key in enumerate(metric_keys):
        series = []
        idx = headers.index(key)
        for r in recent:
            try:
                series.append(float(r[idx]))
            except Exception:
                series.append(None)
        color = palette[i % len(palette)]
        chart_datasets.append(
            {
                "label": key,
                "data": series,
                "borderColor": color,
                "backgroundColor": color + "33",
                "tension": 0.2,
                "pointRadius": 0,
                "borderWidth": 2,
            }
        )

    cards = "".join(
        f"<div class='card'><div class='label'>{k}</div><div class='value'>{v}</div></div>"
        for k, v in latest.items() if k != "ts_utc"
    )

    html = f"""
<html>
    <head>
        <title>Trading Metrics Dashboard</title>
        <meta name='viewport' content='width=device-width, initial-scale=1' />
        <script src='https://cdn.jsdelivr.net/npm/chart.js'></script>
        <style>
            :root {{
                --bg:#0d1117; --panel:#161b22; --panel2:#21262d; --border:#30363d;
                --text:#f0f6fc; --muted:#8b949e; --accent:#58a6ff;
            }}
            body {{
                margin:0; padding:20px; color:var(--text); background:
                radial-gradient(circle at 20% 0%, #1f2937 0%, #0d1117 45%);
                font-family:'Segoe UI', Arial, sans-serif;
            }}
            .wrap {{ max-width:1200px; margin:0 auto; }}
            .title {{ font-size:28px; font-weight:700; letter-spacing:-0.02em; }}
            .subtitle {{ color:var(--muted); margin-top:6px; }}
            .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:12px; margin-top:16px; }}
            .card {{ background:var(--panel); border:1px solid var(--border); border-radius:10px; padding:12px; }}
            .label {{ color:var(--muted); font-size:12px; }}
            .value {{ font-size:22px; font-weight:600; margin-top:4px; }}
            .chart {{ margin-top:16px; background:var(--panel2); border:1px solid var(--border); border-radius:12px; padding:12px; }}
        </style>
    </head>
    <body>
        <div class='wrap'>
            <div class='title'>Trading Metrics Dashboard</div>
            <div class='subtitle'>Last update: {latest.get('ts_utc', '')} | Auto-refresh: 30s</div>
            <div class='cards'>{cards}</div>
            <div class='chart'><canvas id='metricsChart' height='110'></canvas></div>
        </div>
        <script>
            const labels = {json.dumps(labels)};
            const datasets = {json.dumps(chart_datasets)};
            const ctx = document.getElementById('metricsChart').getContext('2d');
            new Chart(ctx, {{
                type: 'line',
                data: {{ labels, datasets }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: true,
                    interaction: {{ mode: 'index', intersect: false }},
                    plugins: {{ legend: {{ labels: {{ color: '#f0f6fc' }} }} }},
                    scales: {{
                        x: {{ ticks: {{ color: '#8b949e', maxTicksLimit: 8 }}, grid: {{ color: '#30363d' }} }},
                        y: {{ ticks: {{ color: '#8b949e' }}, grid: {{ color: '#30363d' }} }}
                    }}
                }}
            }});
            setTimeout(() => window.location.reload(), 30000);
        </script>
    </body>
</html>
"""
    atomic_write_text(out_path, html)


def incident_response_payload(severity: str, summary: str, context: dict) -> str:
    payload = {
        "ts_utc": datetime.now(UTC).isoformat(),
        "severity": severity,
        "summary": summary,
        "context": context,
    }
    return json.dumps(payload)
