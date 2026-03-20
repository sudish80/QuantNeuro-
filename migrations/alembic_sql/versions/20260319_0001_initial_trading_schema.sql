-- revision: 20260319_0001
-- down_revision: none
-- purpose: create normalized trading schema baseline

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS assets (
  id BIGSERIAL PRIMARY KEY,
  symbol TEXT NOT NULL,
  venue TEXT NOT NULL,
  asset_type TEXT NOT NULL,
  base_currency TEXT,
  quote_currency TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_assets_symbol_venue UNIQUE (symbol, venue),
  CONSTRAINT ck_assets_status CHECK (status IN ('active', 'inactive', 'halted'))
);

CREATE TABLE IF NOT EXISTS models (
  id BIGSERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  version TEXT NOT NULL,
  artifact_uri TEXT NOT NULL,
  checksum TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_models_name_version UNIQUE (name, version)
);

CREATE TABLE IF NOT EXISTS feature_sets (
  id BIGSERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  version TEXT NOT NULL,
  schema_json JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_feature_sets_name_version UNIQUE (name, version)
);

CREATE TABLE IF NOT EXISTS ohlcv (
  asset_id BIGINT NOT NULL REFERENCES assets(id),
  ts TIMESTAMPTZ NOT NULL,
  open NUMERIC(20,10) NOT NULL,
  high NUMERIC(20,10) NOT NULL,
  low NUMERIC(20,10) NOT NULL,
  close NUMERIC(20,10) NOT NULL,
  volume NUMERIC(30,10) NOT NULL,
  source TEXT NOT NULL,
  ingest_id UUID NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (asset_id, ts, source),
  CONSTRAINT ck_ohlcv_price_range CHECK (low <= high),
  CONSTRAINT ck_ohlcv_nonnegative_volume CHECK (volume >= 0)
) PARTITION BY RANGE (ts);

CREATE TABLE IF NOT EXISTS orderbook_snapshots (
  id BIGSERIAL PRIMARY KEY,
  asset_id BIGINT NOT NULL REFERENCES assets(id),
  ts TIMESTAMPTZ NOT NULL,
  bids_json JSONB NOT NULL,
  asks_json JSONB NOT NULL,
  depth INTEGER NOT NULL,
  source TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ck_orderbook_depth_positive CHECK (depth > 0)
);

CREATE TABLE IF NOT EXISTS feature_values (
  asset_id BIGINT NOT NULL REFERENCES assets(id),
  ts TIMESTAMPTZ NOT NULL,
  feature_set_id BIGINT NOT NULL REFERENCES feature_sets(id),
  values_json JSONB NOT NULL,
  hash TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (asset_id, ts, feature_set_id)
);

CREATE TABLE IF NOT EXISTS inference_events (
  id BIGSERIAL PRIMARY KEY,
  ts TIMESTAMPTZ NOT NULL,
  model_id BIGINT NOT NULL REFERENCES models(id),
  asset_id BIGINT NOT NULL REFERENCES assets(id),
  prediction NUMERIC(20,10) NOT NULL,
  confidence NUMERIC(10,8),
  latency_ms INTEGER,
  trace_id UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ck_inference_confidence_range CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1))
);

CREATE TABLE IF NOT EXISTS signals (
  id BIGSERIAL PRIMARY KEY,
  asset_id BIGINT NOT NULL REFERENCES assets(id),
  ts TIMESTAMPTZ NOT NULL,
  model_id BIGINT REFERENCES models(id),
  side TEXT NOT NULL,
  confidence NUMERIC(10,8),
  features_hash TEXT,
  status TEXT NOT NULL DEFAULT 'new',
  expires_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ck_signals_side CHECK (side IN ('buy', 'sell', 'hold')),
  CONSTRAINT ck_signals_status CHECK (status IN ('new', 'approved', 'rejected', 'expired', 'executed')),
  CONSTRAINT ck_signals_confidence_range CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1))
);

CREATE TABLE IF NOT EXISTS backtest_runs (
  id BIGSERIAL PRIMARY KEY,
  strategy_name TEXT NOT NULL,
  started_at TIMESTAMPTZ NOT NULL,
  ended_at TIMESTAMPTZ,
  config_json JSONB NOT NULL,
  metrics_json JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS orders (
  id BIGSERIAL PRIMARY KEY,
  external_id TEXT,
  signal_id BIGINT REFERENCES signals(id),
  asset_id BIGINT NOT NULL REFERENCES assets(id),
  side TEXT NOT NULL,
  order_type TEXT NOT NULL,
  quantity NUMERIC(30,10) NOT NULL,
  limit_price NUMERIC(20,10),
  status TEXT NOT NULL,
  submitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ck_orders_side CHECK (side IN ('buy', 'sell')),
  CONSTRAINT ck_orders_type CHECK (order_type IN ('market', 'limit', 'stop', 'stop_limit')),
  CONSTRAINT ck_orders_status CHECK (status IN ('created', 'submitted', 'partially_filled', 'filled', 'cancelled', 'rejected')),
  CONSTRAINT ck_orders_quantity_positive CHECK (quantity > 0)
);

CREATE TABLE IF NOT EXISTS fills (
  id BIGSERIAL,
  order_id BIGINT NOT NULL REFERENCES orders(id),
  fill_ts TIMESTAMPTZ NOT NULL,
  fill_price NUMERIC(20,10) NOT NULL,
  fill_qty NUMERIC(30,10) NOT NULL,
  fee_amount NUMERIC(20,10) NOT NULL DEFAULT 0,
  fee_currency TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (id, fill_ts),
  CONSTRAINT ck_fills_qty_positive CHECK (fill_qty > 0)
) PARTITION BY RANGE (fill_ts);

CREATE TABLE IF NOT EXISTS positions (
  id BIGSERIAL PRIMARY KEY,
  asset_id BIGINT NOT NULL REFERENCES assets(id),
  quantity NUMERIC(30,10) NOT NULL,
  avg_price NUMERIC(20,10) NOT NULL,
  realized_pnl NUMERIC(24,10) NOT NULL DEFAULT 0,
  unrealized_pnl NUMERIC(24,10) NOT NULL DEFAULT 0,
  ts_updated TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_positions_asset UNIQUE (asset_id)
);

CREATE TABLE IF NOT EXISTS risk_limits (
  id BIGSERIAL PRIMARY KEY,
  scope_type TEXT NOT NULL,
  scope_key TEXT NOT NULL,
  limit_name TEXT NOT NULL,
  limit_value NUMERIC(24,10) NOT NULL,
  period TEXT NOT NULL,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_risk_limits_scope UNIQUE (scope_type, scope_key, limit_name, period)
);

CREATE TABLE IF NOT EXISTS risk_checks (
  id BIGSERIAL PRIMARY KEY,
  ts TIMESTAMPTZ NOT NULL,
  order_id BIGINT REFERENCES orders(id),
  rule_name TEXT NOT NULL,
  result TEXT NOT NULL,
  score NUMERIC(10,6),
  details_json JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ck_risk_checks_result CHECK (result IN ('pass', 'fail', 'warn'))
);

CREATE TABLE IF NOT EXISTS risk_events (
  id BIGSERIAL PRIMARY KEY,
  ts TIMESTAMPTZ NOT NULL,
  severity TEXT NOT NULL,
  rule_name TEXT NOT NULL,
  payload_json JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ck_risk_events_severity CHECK (severity IN ('low', 'medium', 'high', 'critical'))
);

CREATE TABLE IF NOT EXISTS breach_incidents (
  id BIGSERIAL PRIMARY KEY,
  opened_at TIMESTAMPTZ NOT NULL,
  closed_at TIMESTAMPTZ,
  severity TEXT NOT NULL,
  status TEXT NOT NULL,
  summary TEXT NOT NULL,
  actions_json JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ck_breach_status CHECK (status IN ('open', 'in_progress', 'resolved', 'dismissed'))
);

CREATE TABLE IF NOT EXISTS ingestion_jobs (
  id BIGSERIAL PRIMARY KEY,
  source TEXT NOT NULL,
  started_at TIMESTAMPTZ NOT NULL,
  ended_at TIMESTAMPTZ,
  status TEXT NOT NULL,
  records_in BIGINT NOT NULL DEFAULT 0,
  records_out BIGINT NOT NULL DEFAULT 0,
  error_count BIGINT NOT NULL DEFAULT 0,
  details_json JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ck_ingestion_status CHECK (status IN ('running', 'success', 'failed', 'partial'))
);

CREATE TABLE IF NOT EXISTS data_quality_checks (
  id BIGSERIAL PRIMARY KEY,
  ts TIMESTAMPTZ NOT NULL,
  asset_id BIGINT REFERENCES assets(id),
  check_name TEXT NOT NULL,
  severity TEXT NOT NULL,
  result TEXT NOT NULL,
  details_json JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ck_dq_severity CHECK (severity IN ('low', 'medium', 'high', 'critical')),
  CONSTRAINT ck_dq_result CHECK (result IN ('pass', 'fail', 'warn'))
);

CREATE TABLE IF NOT EXISTS source_watermarks (
  source TEXT NOT NULL,
  symbol TEXT NOT NULL,
  last_event_ts TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (source, symbol)
);

CREATE TABLE IF NOT EXISTS audit_events (
  id BIGSERIAL,
  ts TIMESTAMPTZ NOT NULL,
  actor TEXT,
  action TEXT NOT NULL,
  entity TEXT NOT NULL,
  entity_id TEXT,
  before_json JSONB,
  after_json JSONB,
  ip INET,
  correlation_id UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (id, ts)
) PARTITION BY RANGE (ts);

CREATE TABLE IF NOT EXISTS report_exports (
  id BIGSERIAL PRIMARY KEY,
  report_type TEXT NOT NULL,
  requested_by TEXT,
  status TEXT NOT NULL,
  uri TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ck_report_exports_status CHECK (status IN ('queued', 'running', 'success', 'failed'))
);

COMMIT;
