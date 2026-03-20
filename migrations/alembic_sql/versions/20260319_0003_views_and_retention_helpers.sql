-- revision: 20260319_0003
-- down_revision: 20260319_0002
-- purpose: create materialized views and retention/maintenance helper functions

BEGIN;

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_latest_prices AS
SELECT DISTINCT ON (a.id)
  a.id AS asset_id,
  a.symbol,
  a.venue,
  o.ts,
  o.close,
  o.volume,
  o.source
FROM assets a
JOIN ohlcv o ON o.asset_id = a.id
ORDER BY a.id, o.ts DESC;

CREATE UNIQUE INDEX IF NOT EXISTS ux_mv_latest_prices_asset_id ON mv_latest_prices (asset_id);

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_intraday_pnl AS
SELECT
  date_trunc('day', o.submitted_at) AS trade_day,
  o.asset_id,
  count(*) AS order_count,
  coalesce(sum((f.fill_price - o.limit_price) * f.fill_qty), 0) AS slippage_proxy
FROM orders o
LEFT JOIN fills f ON f.order_id = o.id
WHERE o.submitted_at >= date_trunc('day', now())
GROUP BY 1, 2;

CREATE INDEX IF NOT EXISTS idx_mv_intraday_pnl_day_asset ON mv_intraday_pnl (trade_day, asset_id);

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_risk_exposure AS
SELECT
  p.asset_id,
  p.quantity,
  p.avg_price,
  (p.quantity * p.avg_price) AS gross_notional,
  p.realized_pnl,
  p.unrealized_pnl,
  p.ts_updated
FROM positions p;

CREATE UNIQUE INDEX IF NOT EXISTS ux_mv_risk_exposure_asset ON mv_risk_exposure (asset_id);

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_execution_quality AS
SELECT
  date_trunc('day', f.fill_ts) AS trade_day,
  o.asset_id,
  count(*) AS fill_count,
  avg(abs(f.fill_price - coalesce(o.limit_price, f.fill_price))) AS avg_abs_slippage,
  avg(extract(epoch from (f.fill_ts - o.submitted_at)) * 1000.0) AS avg_time_to_fill_ms
FROM fills f
JOIN orders o ON o.id = f.order_id
GROUP BY 1, 2;

CREATE INDEX IF NOT EXISTS idx_mv_execution_quality_day_asset ON mv_execution_quality (trade_day, asset_id);

-- Refresh helper
CREATE OR REPLACE FUNCTION refresh_trading_materialized_views() RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
  REFRESH MATERIALIZED VIEW CONCURRENTLY mv_latest_prices;
  REFRESH MATERIALIZED VIEW mv_intraday_pnl;
  REFRESH MATERIALIZED VIEW mv_risk_exposure;
  REFRESH MATERIALIZED VIEW mv_execution_quality;
END;
$$;

-- Retention helper for partitioned tables named <parent>_YYYY_MM
CREATE OR REPLACE FUNCTION drop_old_monthly_partitions(
  p_parent_table TEXT,
  p_keep_months INTEGER
) RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
  rec RECORD;
  cutoff DATE := (date_trunc('month', now())::date - (p_keep_months || ' months')::interval)::date;
  dropped_count INTEGER := 0;
  part_month DATE;
BEGIN
  FOR rec IN
    SELECT c.relname AS partition_name
    FROM pg_inherits i
    JOIN pg_class p ON p.oid = i.inhparent
    JOIN pg_class c ON c.oid = i.inhrelid
    WHERE p.relname = p_parent_table
  LOOP
    BEGIN
      part_month := to_date(substring(rec.partition_name from '([0-9]{4}_[0-9]{2})$'), 'YYYY_MM');
      IF part_month < cutoff THEN
        EXECUTE format('DROP TABLE IF EXISTS %I', rec.partition_name);
        dropped_count := dropped_count + 1;
      END IF;
    EXCEPTION WHEN others THEN
      -- Skip partitions not matching naming convention.
      CONTINUE;
    END;
  END LOOP;

  RETURN dropped_count;
END;
$$;

COMMIT;
