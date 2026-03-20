-- revision: 20260319_0002
-- down_revision: 20260319_0001
-- purpose: create rolling monthly partitions and core indexes

BEGIN;

DO $$
DECLARE
  start_month DATE := date_trunc('month', now())::date - interval '1 month';
  end_month DATE := date_trunc('month', now())::date + interval '3 month';
  d DATE;
  p_start TIMESTAMPTZ;
  p_end TIMESTAMPTZ;
  suffix TEXT;
BEGIN
  d := start_month;
  WHILE d <= end_month LOOP
    p_start := d::timestamptz;
    p_end := (d + interval '1 month')::timestamptz;
    suffix := to_char(d, 'YYYY_MM');

    EXECUTE format(
      'CREATE TABLE IF NOT EXISTS ohlcv_%s PARTITION OF ohlcv FOR VALUES FROM (%L) TO (%L);',
      suffix, p_start, p_end
    );

    EXECUTE format(
      'CREATE TABLE IF NOT EXISTS fills_%s PARTITION OF fills FOR VALUES FROM (%L) TO (%L);',
      suffix, p_start, p_end
    );

    EXECUTE format(
      'CREATE TABLE IF NOT EXISTS audit_events_%s PARTITION OF audit_events FOR VALUES FROM (%L) TO (%L);',
      suffix, p_start, p_end
    );

    d := (d + interval '1 month')::date;
  END LOOP;
END $$;

-- Parent-partitioned indexes. PostgreSQL will keep partition index trees aligned.
CREATE INDEX IF NOT EXISTS idx_ohlcv_asset_ts_desc ON ohlcv (asset_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_ohlcv_ts_desc ON ohlcv (ts DESC);
CREATE INDEX IF NOT EXISTS idx_ohlcv_source_ts_desc ON ohlcv (source, ts DESC);

CREATE INDEX IF NOT EXISTS idx_orderbook_asset_ts_desc ON orderbook_snapshots (asset_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_inference_asset_ts_desc ON inference_events (asset_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_signals_asset_ts_conf ON signals (asset_id, ts DESC, confidence);
CREATE INDEX IF NOT EXISTS idx_signals_status_expires ON signals (status, expires_at);

CREATE INDEX IF NOT EXISTS idx_orders_status_updated ON orders (status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_orders_asset_submitted ON orders (asset_id, submitted_at DESC);
CREATE INDEX IF NOT EXISTS idx_orders_external_id ON orders (external_id);

CREATE INDEX IF NOT EXISTS idx_fills_order_ts_desc ON fills (order_id, fill_ts DESC);
CREATE INDEX IF NOT EXISTS idx_positions_asset_updated ON positions (asset_id, ts_updated DESC);

CREATE INDEX IF NOT EXISTS idx_risk_checks_order_ts ON risk_checks (order_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_risk_events_severity_ts ON risk_events (severity, ts DESC);
CREATE INDEX IF NOT EXISTS idx_dq_asset_ts ON data_quality_checks (asset_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_ingestion_source_started ON ingestion_jobs (source, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_audit_actor_ts_desc ON audit_events (actor, ts DESC);
CREATE INDEX IF NOT EXISTS idx_audit_entity_entityid_ts ON audit_events (entity, entity_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_audit_correlation ON audit_events (correlation_id);

COMMIT;
