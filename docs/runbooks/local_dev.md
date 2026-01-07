# Local Development Runbook

## Initial Setup

### Prerequisites

1. **PostgreSQL** (version 12+)
   ```bash
   # macOS (Homebrew)
   brew install postgresql@15
   brew services start postgresql@15

   # Ubuntu/Debian
   sudo apt-get install postgresql postgresql-contrib
   sudo systemctl start postgresql
   ```

2. **Python 3.10+**
   ```bash
   python --version  # Should be 3.10 or higher
   ```

### Database Setup

1. **Create the database:**
   ```bash
   createdb hyperliquid
   ```

2. **Apply the schema:**
   ```bash
   psql -d hyperliquid -f db/schema.sql
   ```

3. **Verify tables were created:**
   ```bash
   psql -d hyperliquid -c "\dt"
   ```

   You should see all 11 tables listed.

### Python Environment Setup

1. **Create and activate virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment variables:**
   ```bash
   cp .env.example .env
   ```

   Edit `.env` if needed (defaults should work for local development).

### Verify Setup

1. **Check database connection:**
   ```bash
   psql -d hyperliquid -c "SELECT version();"
   ```

2. **Verify Python imports:**
   ```bash
   python -c "from src.config import settings; print(settings.database_url)"
   ```

---

## Running the Ingestion System

### Start Ingestion (Continuous Mode)

Run the ingestion loop continuously:

```bash
python -m src.ingest.fetch
```

This will:
- Refresh the wallet universe immediately (first run)
- Start ingesting snapshots every 60 seconds
- Refresh the universe every 6 hours
- Run until stopped with Ctrl+C

### Test Mode (Single Run)

For testing or debugging, run a single ingestion cycle:

```bash
# Snapshot only (uses existing universe)
python -m src.ingest.fetch --once

# Snapshot + universe refresh
python -m src.ingest.fetch --once --refresh-universe
```

### Monitor Ingestion

Watch the logs in real-time:

```bash
python -m src.ingest.fetch 2>&1 | tee ingestion.log
```

Check recent snapshots:

```bash
psql -d hyperliquid -c "
  SELECT snapshot_ts, status, coverage_pct, rows_written, duration_ms
  FROM ingest_runs
  ORDER BY snapshot_ts DESC
  LIMIT 10;
"
```

Check health state:

```bash
psql -d hyperliquid -c "SELECT * FROM v_latest_health;"
```

Check universe:

```bash
psql -d hyperliquid -c "
  SELECT COUNT(*) as wallet_count,
         MIN(as_of_ts) as oldest,
         MAX(as_of_ts) as newest
  FROM wallet_universe_current;
"
```

---

## Common Operations

### Reset the Database

**Warning:** This deletes all data.

```bash
psql -d hyperliquid -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
psql -d hyperliquid -f db/schema.sql
```

### Check Data Volumes

```sql
-- Run in psql -d hyperliquid
SELECT
    relname AS table,
    pg_size_pretty(pg_total_relation_size(relid)) AS total_size,
    n_live_tup AS row_count
FROM pg_stat_user_tables
ORDER BY pg_total_relation_size(relid) DESC;
```

### Clean Up Old Snapshots

Snapshots older than 7 days can be removed:

```bash
psql -d hyperliquid -c "
  DELETE FROM wallet_snapshots
  WHERE snapshot_ts < NOW() - INTERVAL '7 days';
"
```

### Inspect Failed Runs

```sql
-- Failed universe refreshes
SELECT run_id, as_of_ts, n_received, error
FROM wallet_universe_runs
WHERE status = 'failed'
ORDER BY as_of_ts DESC
LIMIT 5;

-- Failed snapshot runs
SELECT run_id, snapshot_ts, coverage_pct, error
FROM ingest_runs
WHERE status IN ('failed', 'partial')
ORDER BY snapshot_ts DESC
LIMIT 10;
```

---

## Troubleshooting

### Database Connection Errors

**Error:** `psycopg2.OperationalError: could not connect to server`

**Solutions:**
1. Check PostgreSQL is running: `pg_isready`
2. Verify DATABASE_URL in `.env`
3. Check PostgreSQL is listening: `psql -l`

### Rate Limiting (429 Errors)

**Symptom:** Logs show many rate limit warnings

**Solutions:**
1. Reduce concurrency in `.env`: `MAX_CONCURRENCY=4`
2. Increase request timeout: `REQUEST_TIMEOUT_SEC=20`
3. Check if Hyperliquid API is experiencing issues

### Low Coverage

**Symptom:** `coverage_pct` consistently below 95%

**Causes:**
- Network issues
- Hyperliquid API slow/unstable
- Concurrency too high (rate limiting)
- Timeout too short

**Solutions:**
1. Check network connectivity
2. Review failed wallet fetches in logs
3. Adjust `MAX_CONCURRENCY` and `REQUEST_TIMEOUT_SEC`

### Stale Health State

**Symptom:** Dashboard shows "stale" for >3 minutes

**Check:**
1. Is ingestion running? `ps aux | grep "src.ingest.fetch"`
2. Check last successful run:
   ```sql
   SELECT * FROM ingest_runs WHERE status = 'success' ORDER BY snapshot_ts DESC LIMIT 1;
   ```
3. Review recent errors:
   ```sql
   SELECT snapshot_ts, error FROM ingest_runs WHERE error IS NOT NULL ORDER BY snapshot_ts DESC LIMIT 5;
   ```

### No Wallets in Universe

**Error:** `No wallets in universe`

**Solutions:**
1. Run universe refresh manually:
   ```bash
   python -m src.ingest.fetch --once --refresh-universe
   ```
2. Check universe refresh logs for errors
3. Verify Hyperliquid leaderboard API is accessible:
   ```bash
   curl https://stats-data.hyperliquid.xyz/Mainnet/leaderboard | jq '.leaderboardRows | length'
   ```

---

## Development Workflow

### Making Changes

1. **Update documentation first** (if definitions change)
2. **Modify code**
3. **Run tests:**
   ```bash
   pytest tests/
   ```
4. **Lint:**
   ```bash
   ruff check .
   ```
5. **Test locally:**
   ```bash
   python -m src.ingest.fetch --once
   ```

### Adding New Metrics or Logic

1. Check `docs/product/` for business logic source of truth
2. Update `docs/architecture/schema.md` if DB changes needed
3. Update `skills/` files for implementation guidance
4. Implement changes following existing patterns
5. Add tests in `tests/`

---

## Useful SQL Queries

### Latest Snapshots by Asset

```sql
SELECT
    asset,
    COUNT(DISTINCT wallet_id) as wallet_count,
    COUNT(*) as total_positions,
    SUM(CASE WHEN position_szi > 0 THEN 1 ELSE 0 END) as long_count,
    SUM(CASE WHEN position_szi < 0 THEN 1 ELSE 0 END) as short_count,
    SUM(CASE WHEN position_szi = 0 THEN 1 ELSE 0 END) as flat_count
FROM wallet_snapshots
WHERE snapshot_ts = (SELECT MAX(snapshot_ts) FROM wallet_snapshots)
GROUP BY asset;
```

### Ingestion Performance Over Time

```sql
SELECT
    DATE_TRUNC('hour', snapshot_ts) as hour,
    AVG(coverage_pct) as avg_coverage,
    AVG(duration_ms) as avg_duration_ms,
    COUNT(*) as run_count,
    SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success_count
FROM ingest_runs
WHERE snapshot_ts > NOW() - INTERVAL '24 hours'
GROUP BY hour
ORDER BY hour DESC;
```

### Universe Churn

```sql
SELECT
    as_of_ts,
    n_received,
    entered_count,
    exited_count,
    (entered_count + exited_count)::FLOAT / NULLIF(n_received, 0) * 100 as churn_pct
FROM wallet_universe_runs
WHERE status = 'success'
ORDER BY as_of_ts DESC
LIMIT 10;
```

---

## Next Steps

Once Phase 1 is working:
- Proceed to Phase 2: Signal computation (`src/aggregate/` and `src/signals/`)
- Phase 3: Alerts and dashboard (`src/alerts/` and `src/ui/`)
- Phase 4: Validation with real trades

For signal implementation, see:
- `docs/product/metrics.md` - Signal definitions
- `docs/product/playbooks.md` - Playbook logic
- `skills/signals.md` - Implementation guide
