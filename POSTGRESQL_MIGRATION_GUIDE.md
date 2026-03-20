# PostgreSQL Migration Guide

## Overview

This guide covers migrating the trading model from file-based storage to PostgreSQL for:
- Scalability (handle millions of trades/signals)
- Reliability (ACID transactions, backup/recovery)
- Query flexibility (complex reporting, backtesting)
- Integration with downstream systems

**Status:** Schema and migration files ready (see `/migrations/alembic_sql/`)

---

## Architecture

### Before (File-Based)
```
state/
├── state.json              # Current state
├── state_v*.json           # Versioned snapshots
├── trades.csv              # Trade journal
└── metrics.csv             # Performance metrics
```

### After (PostgreSQL)
```
PostgreSQL
├── public schema
│   ├── trades (transaction log)
│   ├── orders (order history)
│   ├── positions (current holdings)
│   ├── signals (model signals)
│   ├── metrics (performance data)
│   ├── ohlcv (market data)
│   └── audit_events (compliance log)
```

---

## Migration Steps

### Step 1: Environment Setup

```bash
# Install PostgreSQL dependency
pip install psycopg2-binary SQLAlchemy alembic

# Or add to requirements.txt
echo "psycopg2-binary>=2.9.0" >> requirements.txt
echo "SQLAlchemy>=2.0.0" >> requirements.txt
echo "alembic>=1.10.0" >> requirements.txt

# Install
pip install -r requirements.txt
```

### Step 2: Database Initialization

```bash
# If using Docker (recommended)
docker-compose up -d postgres

# Wait for PostgreSQL to be ready
docker exec trading-postgres pg_isready -U postgres

# If local PostgreSQL, create database
createdb -U postgres trading_db
```

### Step 3: Run Migrations

```bash
# Apply initial schema
psql -U postgres -d trading_db -f migrations/alembic_sql/versions/20260319_0001_initial_trading_schema.sql

# Apply partitions and indexes
psql -U postgres -d trading_db -f migrations/alembic_sql/versions/20260319_0002_partitions_and_indexes.sql

# Apply views and retention helpers
psql -U postgres -d trading_db -f migrations/alembic_sql/versions/20260319_0003_views_and_retention_helpers.sql
```

### Step 4: Configuration Update

Update `.env` or `production_hardening/config.py`:

```python
# Before (file-based)
STATE_STORE_PATH = "state/state.json"
TRADE_JOURNAL_PATH = "state/trades.csv"

# After (PostgreSQL)
DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/trading_db"
```

### Step 5: Data Migration

Migrate existing data from JSON/CSV to PostgreSQL:

```python
from production_hardening.migration_helper import migrate_file_based_to_postgres

# Migrate existing state
migrate_file_based_to_postgres(
    source_dir="state/",
    database_url="postgresql://postgres:postgres@localhost:5432/trading_db"
)
```

### Step 6: Update Code

Replace file-based store with PostgreSQL:

```python
# Before
from production_hardening.reliability import StateStore
state_store = StateStore(path="state/state.json")

# After
from production_hardening.db_store import DBStateStore
state_store = DBStateStore(db_url="postgresql://postgres:postgres@localhost:5432/trading_db")
```

### Step 7: Verify Migration

```bash
# Check migration status
psql -U postgres -d trading_db -c "SELECT COUNT(*) FROM trades;"
psql -U postgres -d trading_db -c "SELECT COUNT(*) FROM audit_events;"

# Verify indexes exist
psql -U postgres -d trading_db -c "\d trades;"
```

---

## Schema Overview

### Core Tables

#### `assets`
```sql
CREATE TABLE assets (
    asset_id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) UNIQUE,
    name VARCHAR(255),
    asset_type VARCHAR(20),  -- STOCK, CRYPTO, BOND, etc.
    exchange VARCHAR(50),
    currency VARCHAR(3)
);
```

#### `trades`
```sql
CREATE TABLE trades (
    trade_id BIGSERIAL PRIMARY KEY,
    asset_id INTEGER REFERENCES assets(asset_id),
    timestamp TIMESTAMP,
    side VARCHAR(10),         -- BUY, SELL
    quantity DECIMAL(18, 8),
    price DECIMAL(18, 2),
    commission DECIMAL(18, 2),
    pnl DECIMAL(18, 2),
    strategy_id VARCHAR(100), -- Which algo generated this
    INDEX (asset_id, timestamp)
);

-- Partitioned by month for performance
CREATE TABLE trades_2026_03 PARTITION OF trades FOR VALUES FROM ('2026-03-01') TO ('2026-04-01');
```

#### `positions`
```sql
CREATE TABLE positions (
    position_id SERIAL PRIMARY KEY,
    asset_id INTEGER REFERENCES assets(asset_id),
    quantity DECIMAL(18, 8),
    average_price DECIMAL(18, 2),
    current_price DECIMAL(18, 2),
    pnl DECIMAL(18, 2),
    last_updated TIMESTAMP
);
```

#### `signals`
```sql
CREATE TABLE signals (
    signal_id BIGSERIAL PRIMARY KEY,
    asset_id INTEGER REFERENCES assets(asset_id),
    timestamp TIMESTAMP,
    model_version VARCHAR(50),
    signal VARCHAR(20),       -- BUY, SELL, HOLD
    confidence DECIMAL(3, 2),
    predicted_price DECIMAL(18, 2),
    INDEX (asset_id, timestamp)
);
```

#### `metrics`
```sql
CREATE TABLE metrics (
    metric_id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMP,
    trades_executed INTEGER,
    total_pnl DECIMAL(18, 2),
    win_rate DECIMAL(3, 2),
    sharpe_ratio DECIMAL(5, 2),
    max_drawdown DECIMAL(5, 2),
    INDEX (timestamp)
);
```

#### `audit_events`
```sql
CREATE TABLE audit_events (
    event_id BIGSERIAL PRIMARY KEY,
    event_type VARCHAR(50),   -- TRADE_EXECUTED, CONFIG_CHANGED, etc.
    user_id VARCHAR(100),
    details JSONB,            -- Flexible data
    timestamp TIMESTAMP,
    INDEX (event_type, timestamp)
);
```

---

## Query Examples

### Top performing assets
```sql
SELECT 
    a.symbol,
    COUNT(*) as trade_count,
    SUM(t.pnl) as total_pnl,
    AVG(t.pnl) as avg_pnl_per_trade
FROM trades t
JOIN assets a ON t.asset_id = a.asset_id
WHERE t.timestamp > NOW() - INTERVAL '30 days'
GROUP BY a.symbol
ORDER BY total_pnl DESC;
```

### Daily P&L trend
```sql
SELECT 
    DATE(timestamp) as date,
    SUM(pnl) as daily_pnl,
    COUNT(*) as trades,
    SUM(pnl) / NULLIF(COUNT(*), 0) as avg_pnl_per_trade
FROM trades
WHERE timestamp > NOW() - INTERVAL '90 days'
GROUP BY DATE(timestamp)
ORDER BY date DESC;
```

### Win rate by asset
```sql
SELECT 
    a.symbol,
    ROUND(
        100.0 * COUNT(CASE WHEN t.pnl > 0 THEN 1 END) / NULLIF(COUNT(*), 0),
        2
    ) as win_rate,
    COUNT(*) as trade_count
FROM trades t
JOIN assets a ON t.asset_id = a.asset_id
GROUP BY a.symbol
HAVING COUNT(*) >= 10
ORDER BY win_rate DESC;
```

### Audit trail for compliance
```sql
SELECT 
    timestamp,
    event_type,
    user_id,
    details->>'symbol' as symbol,
    details->>'quantity' as quantity
FROM audit_events
WHERE event_type = 'TRADE_EXECUTED'
AND timestamp > NOW() - INTERVAL '7 days'
ORDER BY timestamp DESC;
```

---

## Performance Considerations

### Indexes

```sql
-- Trade lookups by asset/date
CREATE INDEX idx_trades_asset_ts ON trades(asset_id, timestamp DESC);

-- Signal lookups
CREATE INDEX idx_signals_asset_ts ON signals(asset_id, timestamp DESC);

-- Audit trail
CREATE INDEX idx_audit_events_type_ts ON audit_events(event_type, timestamp DESC);

-- JSONB queries on audit_events
CREATE INDEX idx_audit_events_details ON audit_events USING GIN (details);
```

### Partitioning

Tables are partitioned by month for:
- **Range partitioning** on `timestamp`
- Faster queries on recent data
- Easy archive/purge of old data

```sql
-- Example: Archive trades older than 1 year
DELETE FROM trades WHERE timestamp < NOW() - INTERVAL '1 year';
```

### Retention Policies

```sql
-- Automatic cleanup of old metrics
CREATE PROCEDURE cleanup_old_metrics() AS $$
BEGIN
    DELETE FROM metrics WHERE timestamp < NOW() - INTERVAL '2 years';
    DELETE FROM audit_events WHERE timestamp < NOW() - INTERVAL '7 years';
    VACUUM ANALYZE;
END;
$$ LANGUAGE plpgsql;

-- Schedule via cron (in PostgreSQL)
-- SELECT cron.schedule('cleanup_metrics', '0 2 * * *', 'CALL cleanup_old_metrics();');
```

---

## Backup & Recovery

### Automated Backups

```bash
# Full backup
pg_dump -U postgres trading_db > backup_$(date +%Y%m%d_%H%M%S).sql

# Compressed backup
pg_dump -U postgres -Fc trading_db > backup.dump

# Restore
pg_restore -U postgres -d trading_db backup.dump
```

### Point-in-Time Recovery

PostgreSQL WAL (Write-Ahead Logs) enable recovery to any point in time:

```bash
# Enable archival in postgresql.conf
archive_mode = on
archive_command = 'cp %p /backup/wal_archive/%f'

# Restore to specific time
pg_basebackup -D backup_dir
# Then restore WAL archives and recover to target time
```

---

## Monitoring

### PostgreSQL Metrics in Prometheus

```yaml
# Docker compose includes postgres_exporter for metrics
- job_name: 'postgres'
  static_configs:
    - targets: ['localhost:9187']
```

### Key Metrics to Monitor

- **Connection count**: `pg_stat_activity`
- **Query performance**: `pg_stat_statements`
- **Cache hit ratio**: `pg_stat_database`
- **Index usage**: `pg_stat_user_indexes`

---

## Troubleshooting

### Slow Queries

```sql
-- Find slow queries (PostgreSQL 14+)
SELECT query, calls, mean_exec_time, max_exec_time
FROM pg_stat_statements
ORDER BY mean_exec_time DESC
LIMIT 10;
```

### Connection Pooling

Use `pgBouncer` for connection pooling in production:

```ini
[databases]
trading_db = host=localhost port=5432 dbname=trading_db

[pgbouncer]
pool_mode = transaction
max_client_conn = 1000
default_pool_size = 25
```

### Disk Space

```sql
-- Check table sizes
SELECT 
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
```

---

## Rollback Plan

If issues occur, rollback to file-based storage:

```python
from production_hardening.migration_helper import rollback_to_file_based

rollback_to_file_based(
    database_url="postgresql://...",
    target_dir="state_backup/"
)
```

---

## Next Steps

1. **Connection Pooling**: Deploy `pgBouncer` for production
2. **Replication**: Set up PostgreSQL replication for HA
3. **Monitoring**: Integrated Prometheus exporters (✓ done)
4. **Backup Strategy**: Automated WAL archival to S3
5. **Performance Tuning**: Query optimization and index refinement

---

**Last Updated:** March 20, 2026  
**Status:** Ready for production deployment
