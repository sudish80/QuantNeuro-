# Alembic SQL Migration Set (Initial)

This folder contains SQL-first migration revisions that map to the database blueprint in the full-stack enhancement document.

## Files
- `versions/20260319_0001_initial_trading_schema.sql`
- `versions/20260319_0002_partitions_and_indexes.sql`
- `versions/20260319_0003_views_and_retention_helpers.sql`

## Suggested Apply Order
1. `20260319_0001_initial_trading_schema.sql`
2. `20260319_0002_partitions_and_indexes.sql`
3. `20260319_0003_views_and_retention_helpers.sql`

## Notes
- These scripts target PostgreSQL 14+.
- The scripts are idempotent where practical.
- They are designed to be called by Alembic using `op.execute(...)` or run manually in deployment pipelines.
- If you are using TimescaleDB, apply extension setup before running these scripts.
