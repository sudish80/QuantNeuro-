-- Production-ready index and partition maintenance script
-- PostgreSQL 14+
-- Run with an admin role during low-traffic windows.

BEGIN;

-- Ensure future monthly partitions exist for partitioned time-series parents.
CREATE OR REPLACE FUNCTION ensure_monthly_partitions(
  p_parent_table TEXT,
  p_months_ahead INTEGER DEFAULT 3,
  p_months_behind INTEGER DEFAULT 1
) RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
  d DATE := (date_trunc('month', now())::date - (p_months_behind || ' months')::interval)::date;
  d_end DATE := (date_trunc('month', now())::date + (p_months_ahead || ' months')::interval)::date;
  p_start TIMESTAMPTZ;
  p_end TIMESTAMPTZ;
  part_name TEXT;
  created_count INTEGER := 0;
BEGIN
  WHILE d <= d_end LOOP
    p_start := d::timestamptz;
    p_end := (d + interval '1 month')::timestamptz;
    part_name := format('%s_%s', p_parent_table, to_char(d, 'YYYY_MM'));

    EXECUTE format(
      'CREATE TABLE IF NOT EXISTS %I PARTITION OF %I FOR VALUES FROM (%L) TO (%L)',
      part_name, p_parent_table, p_start, p_end
    );

    created_count := created_count + 1;
    d := (d + interval '1 month')::date;
  END LOOP;

  RETURN created_count;
END;
$$;

-- Drop old partitions based on retention months.
CREATE OR REPLACE FUNCTION apply_monthly_partition_retention(
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
      CONTINUE;
    END;
  END LOOP;

  RETURN dropped_count;
END;
$$;

-- Analyze all child partitions for planner accuracy.
CREATE OR REPLACE FUNCTION analyze_child_partitions(
  p_parent_table TEXT
) RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
  rec RECORD;
  analyzed_count INTEGER := 0;
BEGIN
  FOR rec IN
    SELECT c.relname AS partition_name
    FROM pg_inherits i
    JOIN pg_class p ON p.oid = i.inhparent
    JOIN pg_class c ON c.oid = i.inhrelid
    WHERE p.relname = p_parent_table
  LOOP
    EXECUTE format('ANALYZE %I', rec.partition_name);
    analyzed_count := analyzed_count + 1;
  END LOOP;

  RETURN analyzed_count;
END;
$$;

-- Reindex child partitions where relation bloat can impact performance.
-- Note: REINDEX CONCURRENTLY cannot run inside a transaction block;
-- this helper emits commands to run separately.
CREATE OR REPLACE FUNCTION list_reindex_commands_for_partitions(
  p_parent_table TEXT
) RETURNS TABLE(cmd TEXT)
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN QUERY
  SELECT format('REINDEX TABLE CONCURRENTLY %I;', c.relname) AS cmd
  FROM pg_inherits i
  JOIN pg_class p ON p.oid = i.inhparent
  JOIN pg_class c ON c.oid = i.inhrelid
  WHERE p.relname = p_parent_table;
END;
$$;

COMMIT;

-- Suggested monthly runbook (execute in this order):
-- 1) SELECT ensure_monthly_partitions('ohlcv', 3, 1);
-- 2) SELECT ensure_monthly_partitions('fills', 3, 1);
-- 3) SELECT ensure_monthly_partitions('audit_events', 3, 1);
-- 4) SELECT apply_monthly_partition_retention('ohlcv', 24);
-- 5) SELECT apply_monthly_partition_retention('fills', 84);
-- 6) SELECT apply_monthly_partition_retention('audit_events', 84);
-- 7) SELECT analyze_child_partitions('ohlcv');
-- 8) SELECT analyze_child_partitions('fills');
-- 9) SELECT analyze_child_partitions('audit_events');
-- 10) SELECT * FROM list_reindex_commands_for_partitions('ohlcv');
