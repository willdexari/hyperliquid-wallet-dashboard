# Hyperliquid Wallet Dashboard

A local prototype dashboard for tracking top Hyperliquid wallet behavior on **HYPE, BTC, and ETH** to provide objective regime filters for manual discretionary trading.

## Quick Start

### 1. Prerequisites

- Python 3.10+
- PostgreSQL 12+

### 2. Setup

```bash
# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Create database
createdb hyperliquid
psql -d hyperliquid -f db/schema.sql

# Configure environment
cp .env.example .env
```

### 3. Run Ingestion

```bash
# Start continuous ingestion (Ctrl+C to stop)
python -m src.ingest.fetch

# Or run single test cycle
python -m src.ingest.fetch --once --refresh-universe
```

### 4. Verify Data

```bash
# Check latest snapshots
psql -d hyperliquid -c "SELECT * FROM v_latest_health;"

# Check wallet count
psql -d hyperliquid -c "SELECT COUNT(*) FROM wallet_universe_current;"

# Check recent ingestion runs
psql -d hyperliquid -c "
  SELECT snapshot_ts, status, coverage_pct, rows_written
  FROM ingest_runs
  ORDER BY snapshot_ts DESC
  LIMIT 5;
"
```

## Project Status

### Phase 1: DB Schema + Ingestion ✓
- [x] Database schema for all tables
- [x] Universe refresh (top 200 wallets by 30D PnL)
- [x] Snapshot ingestion (60s cadence for HYPE/BTC/ETH)
- [x] Health state tracking
- [x] Rate limiting and error handling

### Phase 2: Signal Computation (Planned)
- [ ] 5-minute signal aggregation
- [ ] Consensus Alignment Score (CAS)
- [ ] Dispersion Index
- [ ] Exit Cluster Score
- [ ] Playbook outputs

### Phase 3: Alerts + Dashboard (Planned)
- [ ] Alert evaluation with throttling
- [ ] Streamlit dashboard
- [ ] Historical charts
- [ ] Health status display

### Phase 4: Validation (Planned)
- [ ] 50+ trades logged
- [ ] Review outcomes
- [ ] Refine thresholds

## Documentation

- **[CLAUDE.md](./CLAUDE.md)** - Development guidelines and project overview
- **[Local Dev Runbook](./docs/runbooks/local_dev.md)** - Setup and troubleshooting
- **[Schema Documentation](./docs/architecture/schema.md)** - Database schema details
- **[Ingestion Guide](./skills/ingestion.md)** - Implementation details

## Architecture

```
├── src/
│   ├── config.py          # Configuration management
│   ├── db.py              # Database utilities
│   ├── ingest/            # Wallet data ingestion
│   │   ├── fetch.py       # Main runner
│   │   ├── hyperliquid_client.py  # API client
│   │   ├── universe.py    # Universe refresh
│   │   └── snapshots.py   # Snapshot ingestion
│   ├── aggregate/         # Signal aggregation (TODO)
│   ├── signals/           # Signal computation (TODO)
│   ├── alerts/            # Alert evaluation (TODO)
│   └── ui/                # Streamlit dashboard (TODO)
├── db/
│   └── schema.sql         # PostgreSQL schema
├── docs/                  # Architecture and product specs
├── skills/                # Implementation guides
└── tests/                 # Test suite
```

## Key Features

### Data Collection (Phase 1)
- **Universe Refresh**: Top 200 wallets by 30D PnL, refreshed every 6 hours
- **Position Snapshots**: Every 60 seconds for HYPE, BTC, ETH
- **Health Monitoring**: Automatic detection of stale/degraded data
- **Rate Limiting**: Configurable concurrency to respect API limits
- **Idempotency**: Safe to re-run without duplicates

### Signal Philosophy (Phase 2+)
- **Behavioral over Absolute**: Track position deltas, not levels
- **Consensus Matters**: Align with top wallet agreement
- **Exit Detection**: Identify when smart money reduces exposure
- **Clear Playbooks**: Long-only, Short-only, or No-trade outputs

## API Endpoints Used

- **Leaderboard**: `https://stats-data.hyperliquid.xyz/Mainnet/leaderboard`
- **Wallet Positions**: `https://api.hyperliquid.xyz/info` (clearinghouseState)

No authentication required for these public endpoints.

## Configuration

Edit `.env` to customize:

```bash
# Database
DATABASE_URL=postgresql://localhost:5432/hyperliquid

# Ingestion
MAX_CONCURRENCY=8          # Concurrent wallet fetches
REQUEST_TIMEOUT_SEC=15     # API request timeout
UNIVERSE_SIZE=200          # Number of wallets to track

# Intervals
UNIVERSE_REFRESH_HOURS=6   # Universe refresh cadence
SNAPSHOT_INTERVAL_SEC=60   # Snapshot cadence (fixed)
```

## Troubleshooting

See [Local Dev Runbook](./docs/runbooks/local_dev.md) for detailed troubleshooting.

Common issues:
- **Low coverage**: Reduce `MAX_CONCURRENCY` if rate limited
- **Stale health**: Check ingestion is running and no errors in logs
- **No wallets**: Run `python -m src.ingest.fetch --once --refresh-universe`

## Development

### Linting
```bash
ruff check .
```

### Testing
```bash
pytest tests/
```

### Making Changes

1. Read relevant documentation in `docs/` first
2. Consult `skills/` files for implementation guidance
3. Make changes in small, testable steps
4. Add tests for new functionality
5. Run linter and tests before committing

## Non-Goals

- Automated trade execution
- Price prediction or indicator replacement
- Machine learning models
- Adding assets before prototype validation

## License

This is a personal prototype project. Not for production use
