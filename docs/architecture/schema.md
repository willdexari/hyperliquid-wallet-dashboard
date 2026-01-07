# docs/architecture/schema.md

## Purpose
This document defines the **complete PostgreSQL DDL** for the Hyperliquid Wallet Dashboard MVP.

It is designed to enforce the "Force of Law" principles:
- Idempotent writes (no duplicate snapshots/signals)
- Deterministic health state (Healthy/Degraded/Stale)
- Signal Lock (no "best guess" signals on stale/failed ingestion)
- Dirty snapshot marking (store raw, ignore dirty in signals)
- Alert hysteresis and throttling (persistent state)
- Fast dashboard reads (latest health, latest signals, recent signal history, latest alerts)

Assets are **HYPE, BTC, ETH only**.

---

## Source of Truth
- For ingestion logic, follow `skills/ingestion.md`.
- For signal computation, follow `skills/signals.md`.
- For alert logic, follow `skills/alerts.md`.
- For dashboard queries, follow `skills/dashboard.md`.
- For QA checks, follow `skills/qa.md`.

This document defines the **authoritative database schema**.

---

## Conventions

### Naming
- Table names: `snake_case`, plural where appropriate
- Column names: `snake_case`
- Constraint names: `pk_`, `chk_`, `ux_`, `fk_` prefixes

### Time
- All timestamps are **UTC** and stored as `TIMESTAMPTZ`.
- `snapshot_ts` is aligned to **60-second** boundaries.
- `signal_ts` is aligned to **5-minute** boundaries.

### Units
- `position_szi`: signed **units** (not USD notional).
- Percentages are 0–100 (NUMERIC).

### Enums (as CHECK constraints)
- `health_state`: `'healthy'` | `'degraded'` | `'stale'`
- `run_status`: `'success'` | `'partial'` | `'failed'`
- `alignment_trend`: `'rising'` | `'flat'` | `'falling'`
- `allowed_playbook`: `'Long-only'` | `'Short-only'` | `'No-trade'`
- `risk_mode`: `'Normal'` | `'Reduced'` | `'Defensive'`
- `severity`: `'medium'` | `'high'` | `'critical'`

**Note:** Playbook and risk mode use **capitalized** values for UI display consistency.

### Idempotency
- Snapshots upsert by `(snapshot_ts, wallet_id, asset)`
- Signals upsert by `(signal_ts, asset)`
- Alert state upsert by `(asset, alert_type)`

---

## Table Overview

| Table | Purpose | Write Cadence |
|-------|---------|---------------|
| `wallet_universe_current` | Active wallet universe | Every 6 hours |
| `wallet_universe_runs` | Universe refresh history | Every 6 hours |
| `wallet_universe_members` | Historical membership per run | Every 6 hours |
| `wallet_snapshots` | Raw 60s position snapshots | Every 60 seconds |
| `snapshot_anomalies` | Dirty detection audit trail | As detected |
| `ingest_runs` | Ingestion run history | Every 60 seconds |
| `ingest_health` | Current health state | Every 60 seconds |
| `signals` | 5-minute regime signals | Every 5 minutes |
| `signal_contributors` | Wallet behavior breakdown | Every 5 minutes |
| `alerts` | Alert event history | As triggered |
| `alert_state` | Hysteresis and throttle state | As updated |

---

## Data Retention Policy

### High-Volume Tables
`wallet_snapshots` grows at ~864K rows/day (200 wallets × 3 assets × 1440 minutes).

**Retention:** Keep **7 days** minimum for debugging and pattern analysis.

**Options:**
1. **Daily cleanup job** (MVP recommended):
```sql
DELETE FROM wallet_snapshots 
WHERE snapshot_ts < NOW() - INTERVAL '7 days';
```

2. **Table partitioning** (post-MVP):
```sql
-- Partition by day for easier management
CREATE TABLE wallet_snapshots (
    ...
) PARTITION BY RANGE (snapshot_ts);

CREATE TABLE wallet_snapshots_2024_01_15 
PARTITION OF wallet_snapshots
FOR VALUES FROM ('2024-01-15') TO ('2024-01-16');
```

### Medium-Volume Tables
| Table | Retention | Rationale |
|-------|-----------|-----------|
| `signals` | 30 days | Historical charts, pattern review |
| `signal_contributors` | 7 days | Dashboard only needs recent |
| `ingest_runs` | 7 days | Debugging |
| `alerts` | 90 days | Incident review |
| `snapshot_anomalies` | 30 days | Audit trail |

### Low-Volume Tables
| Table | Retention |
|-------|-----------|
| `wallet_universe_runs` | Indefinite |
| `wallet_universe_members` | 30 days |
| `wallet_universe_current` | N/A (always current) |
| `ingest_health` | N/A (single row or latest few) |
| `alert_state` | N/A (always current) |

---

## DDL

> **Recommended:** Run this as a single migration.  
> Uses only standard Postgres features (no extensions required).

```sql
-- =====================================================================
-- Hyperliquid Wallet Dashboard MVP Schema
-- Version: 1.0
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1) wallet_universe_current
-- ---------------------------------------------------------------------
-- Purpose:
--   The active wallet universe used by snapshot ingestion.
--   Updated by the universe refresh job every 6 hours.
--
-- Size: ~200 rows (constant)

CREATE TABLE IF NOT EXISTS wallet_universe_current (
    wallet_id      TEXT PRIMARY KEY,
    rank           INTEGER NOT NULL CHECK (rank > 0),
    month_pnl      NUMERIC,
    month_roi      NUMERIC,
    account_value  NUMERIC,
    as_of_ts       TIMESTAMPTZ NOT NULL,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_wuc_rank 
    ON wallet_universe_current (rank);

CREATE INDEX IF NOT EXISTS idx_wuc_as_of_ts_desc 
    ON wallet_universe_current (as_of_ts DESC);

CREATE UNIQUE INDEX IF NOT EXISTS ux_wuc_rank 
    ON wallet_universe_current (rank);

COMMENT ON TABLE wallet_universe_current IS 
    'Active wallet universe for ingestion. ~200 wallets ranked by 30D PnL.';

COMMENT ON COLUMN wallet_universe_current.wallet_id IS 
    'Wallet address (0x-prefixed).';

COMMENT ON COLUMN wallet_universe_current.rank IS 
    'Rank in universe (1 = highest PnL). Unique within current snapshot.';

COMMENT ON COLUMN wallet_universe_current.month_pnl IS 
    '30-day PnL from leaderboard.';

COMMENT ON COLUMN wallet_universe_current.month_roi IS 
    '30-day ROI from leaderboard.';

COMMENT ON COLUMN wallet_universe_current.account_value IS 
    'Account value at time of snapshot.';

COMMENT ON COLUMN wallet_universe_current.as_of_ts IS 
    'Timestamp of the leaderboard snapshot (UTC).';

COMMENT ON COLUMN wallet_universe_current.updated_at IS 
    'Row last updated (UTC).';


-- ---------------------------------------------------------------------
-- 2) wallet_universe_runs
-- ---------------------------------------------------------------------
-- Purpose:
--   History of universe refresh runs for debugging and churn tracking.
--
-- Referenced by: skills/ingestion.md (U5 churn guard)

CREATE TABLE IF NOT EXISTS wallet_universe_runs (
    run_id               SERIAL PRIMARY KEY,
    as_of_ts             TIMESTAMPTZ NOT NULL,
    status               TEXT NOT NULL,
    source               TEXT NOT NULL DEFAULT 'stats-data',
    
    n_requested          INTEGER NOT NULL CHECK (n_requested > 0),
    n_received           INTEGER NOT NULL CHECK (n_received >= 0),
    
    entered_count        INTEGER NOT NULL DEFAULT 0,
    exited_count         INTEGER NOT NULL DEFAULT 0,
    churn_warning_count  INTEGER NOT NULL DEFAULT 0,
    
    duration_ms          INTEGER,
    error                TEXT,
    
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    CONSTRAINT chk_wur_status 
        CHECK (status IN ('success', 'failed')),
    
    CONSTRAINT chk_wur_source 
        CHECK (source IN ('stats-data', 'info-api'))
);

CREATE INDEX IF NOT EXISTS idx_wur_as_of_ts_desc 
    ON wallet_universe_runs (as_of_ts DESC);

CREATE INDEX IF NOT EXISTS idx_wur_status_ts_desc 
    ON wallet_universe_runs (status, as_of_ts DESC);

COMMENT ON TABLE wallet_universe_runs IS 
    'Universe refresh run history. Tracks success/failure and churn patterns.';

COMMENT ON COLUMN wallet_universe_runs.run_id IS 
    'Auto-incrementing run identifier.';

COMMENT ON COLUMN wallet_universe_runs.as_of_ts IS 
    'Timestamp the leaderboard represents (UTC).';

COMMENT ON COLUMN wallet_universe_runs.status IS 
    'Run outcome: success | failed.';

COMMENT ON COLUMN wallet_universe_runs.source IS 
    'Data source used: stats-data | info-api.';

COMMENT ON COLUMN wallet_universe_runs.n_requested IS 
    'Number of wallets requested (typically 200).';

COMMENT ON COLUMN wallet_universe_runs.n_received IS 
    'Number of valid wallets received.';

COMMENT ON COLUMN wallet_universe_runs.entered_count IS 
    'Wallets new to universe vs prior run.';

COMMENT ON COLUMN wallet_universe_runs.exited_count IS 
    'Wallets removed from universe vs prior run.';

COMMENT ON COLUMN wallet_universe_runs.churn_warning_count IS 
    'Consecutive runs with >30% churn. Reset to 0 on normal churn.';

COMMENT ON COLUMN wallet_universe_runs.duration_ms IS 
    'Run duration in milliseconds.';

COMMENT ON COLUMN wallet_universe_runs.error IS 
    'Error message if failed.';


-- ---------------------------------------------------------------------
-- 3) wallet_universe_members
-- ---------------------------------------------------------------------
-- Purpose:
--   Historical record of which wallets were in each universe run.
--   Enables diff analysis and audit.

CREATE TABLE IF NOT EXISTS wallet_universe_members (
    run_id         INTEGER NOT NULL,
    wallet_id      TEXT NOT NULL,
    rank           INTEGER NOT NULL CHECK (rank > 0),
    month_pnl      NUMERIC,
    month_roi      NUMERIC,
    account_value  NUMERIC,
    
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    CONSTRAINT pk_wum PRIMARY KEY (run_id, wallet_id),
    
    CONSTRAINT fk_wum_run 
        FOREIGN KEY (run_id) REFERENCES wallet_universe_runs (run_id) 
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_wum_run_id 
    ON wallet_universe_members (run_id);

CREATE INDEX IF NOT EXISTS idx_wum_wallet_id 
    ON wallet_universe_members (wallet_id);

COMMENT ON TABLE wallet_universe_members IS 
    'Historical membership per universe refresh run.';

COMMENT ON COLUMN wallet_universe_members.run_id IS 
    'Foreign key to wallet_universe_runs.';

COMMENT ON COLUMN wallet_universe_members.wallet_id IS 
    'Wallet address.';

COMMENT ON COLUMN wallet_universe_members.rank IS 
    'Rank within that run.';


-- ---------------------------------------------------------------------
-- 4) wallet_snapshots
-- ---------------------------------------------------------------------
-- Purpose:
--   Raw 60-second wallet snapshots per asset.
--   Store raw even if dirty; signal job ignores dirty rows.
--
-- Size: ~864K rows/day. Retain 7 days minimum.

CREATE TABLE IF NOT EXISTS wallet_snapshots (
    snapshot_ts    TIMESTAMPTZ NOT NULL,
    wallet_id      TEXT NOT NULL,
    asset          TEXT NOT NULL,
    position_szi   NUMERIC,
    entry_px       NUMERIC,
    liq_px         NUMERIC,
    leverage       NUMERIC,
    margin_used    NUMERIC,
    is_dirty       BOOLEAN NOT NULL DEFAULT FALSE,
    dirty_reason   TEXT,
    ingest_run_id  INTEGER,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    CONSTRAINT pk_wallet_snapshots 
        PRIMARY KEY (snapshot_ts, wallet_id, asset),
    
    CONSTRAINT chk_ws_asset 
        CHECK (asset IN ('HYPE', 'BTC', 'ETH')),
    
    CONSTRAINT chk_ws_dirty_reason 
        CHECK ((is_dirty = FALSE AND dirty_reason IS NULL) OR is_dirty = TRUE)
);

-- Primary access patterns
CREATE INDEX IF NOT EXISTS idx_ws_asset_ts_desc 
    ON wallet_snapshots (asset, snapshot_ts DESC);

CREATE INDEX IF NOT EXISTS idx_ws_wallet_asset_ts_desc 
    ON wallet_snapshots (wallet_id, asset, snapshot_ts DESC);

CREATE INDEX IF NOT EXISTS idx_ws_ts_desc 
    ON wallet_snapshots (snapshot_ts DESC);

-- Dirty diagnostics
CREATE INDEX IF NOT EXISTS idx_ws_dirty_ts_desc 
    ON wallet_snapshots (is_dirty, snapshot_ts DESC) 
    WHERE is_dirty = TRUE;

COMMENT ON TABLE wallet_snapshots IS 
    'Raw 60s position snapshots. position_szi (signed units) is canonical. Dirty rows ignored by signals.';

COMMENT ON COLUMN wallet_snapshots.snapshot_ts IS 
    'Snapshot timestamp (UTC), aligned to 60s boundary.';

COMMENT ON COLUMN wallet_snapshots.wallet_id IS 
    'Wallet address.';

COMMENT ON COLUMN wallet_snapshots.asset IS 
    'Asset: HYPE | BTC | ETH.';

COMMENT ON COLUMN wallet_snapshots.position_szi IS 
    'Signed position size in units. Positive=long, negative=short, 0=flat, NULL=missing.';

COMMENT ON COLUMN wallet_snapshots.entry_px IS 
    'Entry price (optional, for debugging).';

COMMENT ON COLUMN wallet_snapshots.liq_px IS 
    'Liquidation price (optional).';

COMMENT ON COLUMN wallet_snapshots.leverage IS 
    'Position leverage (optional).';

COMMENT ON COLUMN wallet_snapshots.margin_used IS 
    'Margin allocated (optional).';

COMMENT ON COLUMN wallet_snapshots.is_dirty IS 
    'True if flagged as transient glitch. Stored but ignored by signal aggregation.';

COMMENT ON COLUMN wallet_snapshots.dirty_reason IS 
    'Reason code when dirty (e.g., transient_collapse). NULL when not dirty.';

COMMENT ON COLUMN wallet_snapshots.ingest_run_id IS 
    'Foreign key to ingest_runs (optional, for tracing).';


-- ---------------------------------------------------------------------
-- 5) snapshot_anomalies
-- ---------------------------------------------------------------------
-- Purpose:
--   Audit trail for dirty detection and other anomalies.
--   Separate from snapshots to avoid bloat.

CREATE TABLE IF NOT EXISTS snapshot_anomalies (
    id            SERIAL PRIMARY KEY,
    detected_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    snapshot_ts   TIMESTAMPTZ NOT NULL,
    wallet_id     TEXT NOT NULL,
    asset         TEXT NOT NULL,
    anomaly_type  TEXT NOT NULL,
    details       JSONB,
    
    CONSTRAINT chk_sa_asset 
        CHECK (asset IN ('HYPE', 'BTC', 'ETH')),
    
    CONSTRAINT chk_sa_type 
        CHECK (anomaly_type IN ('transient_collapse', 'szi_jump', 'null_szi', 'other'))
);

CREATE INDEX IF NOT EXISTS idx_sa_snapshot_ts_desc 
    ON snapshot_anomalies (snapshot_ts DESC);

CREATE INDEX IF NOT EXISTS idx_sa_wallet_asset_ts_desc 
    ON snapshot_anomalies (wallet_id, asset, snapshot_ts DESC);

CREATE INDEX IF NOT EXISTS idx_sa_type_ts_desc 
    ON snapshot_anomalies (anomaly_type, snapshot_ts DESC);

COMMENT ON TABLE snapshot_anomalies IS 
    'Audit log for dirty snapshot detection. Explains why snapshots were marked dirty.';

COMMENT ON COLUMN snapshot_anomalies.detected_at IS 
    'When anomaly was detected (UTC).';

COMMENT ON COLUMN snapshot_anomalies.snapshot_ts IS 
    'Affected snapshot timestamp.';

COMMENT ON COLUMN snapshot_anomalies.anomaly_type IS 
    'Category: transient_collapse | szi_jump | null_szi | other.';

COMMENT ON COLUMN snapshot_anomalies.details IS 
    'JSON details: values before/after, thresholds, context.';


-- ---------------------------------------------------------------------
-- 6) ingest_runs
-- ---------------------------------------------------------------------
-- Purpose:
--   One row per ingestion cycle (every 60s).
--   Raw run data for debugging and history.

CREATE TABLE IF NOT EXISTS ingest_runs (
    run_id              SERIAL PRIMARY KEY,
    snapshot_ts         TIMESTAMPTZ NOT NULL UNIQUE,
    status              TEXT NOT NULL,
    
    wallets_expected    INTEGER NOT NULL CHECK (wallets_expected >= 0),
    wallets_succeeded   INTEGER NOT NULL CHECK (wallets_succeeded >= 0),
    wallets_failed      INTEGER NOT NULL CHECK (wallets_failed >= 0),
    
    rows_expected       INTEGER NOT NULL CHECK (rows_expected >= 0),
    rows_written        INTEGER NOT NULL CHECK (rows_written >= 0),
    
    coverage_pct        NUMERIC NOT NULL CHECK (coverage_pct >= 0 AND coverage_pct <= 100),
    
    duration_ms         INTEGER,
    error               TEXT,
    
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    CONSTRAINT chk_ir_status 
        CHECK (status IN ('success', 'partial', 'failed')),
    
    CONSTRAINT chk_ir_wallet_counts 
        CHECK (wallets_succeeded + wallets_failed = wallets_expected OR wallets_expected = 0)
);

CREATE INDEX IF NOT EXISTS idx_ir_snapshot_ts_desc 
    ON ingest_runs (snapshot_ts DESC);

CREATE INDEX IF NOT EXISTS idx_ir_status_ts_desc 
    ON ingest_runs (status, snapshot_ts DESC);

COMMENT ON TABLE ingest_runs IS 
    'Ingestion run history. One row per 60s cycle.';

COMMENT ON COLUMN ingest_runs.run_id IS 
    'Auto-incrementing run identifier.';

COMMENT ON COLUMN ingest_runs.snapshot_ts IS 
    'Snapshot timestamp for this run (unique, 60s-aligned).';

COMMENT ON COLUMN ingest_runs.status IS 
    'Run outcome: success | partial | failed.';

COMMENT ON COLUMN ingest_runs.wallets_expected IS 
    'Wallets in universe at cycle start.';

COMMENT ON COLUMN ingest_runs.wallets_succeeded IS 
    'Wallets fetched successfully.';

COMMENT ON COLUMN ingest_runs.wallets_failed IS 
    'Wallets that failed (timeout/error).';

COMMENT ON COLUMN ingest_runs.rows_expected IS 
    'Expected rows = wallets_expected × 3 assets.';

COMMENT ON COLUMN ingest_runs.rows_written IS 
    'Actual snapshot rows written.';

COMMENT ON COLUMN ingest_runs.coverage_pct IS 
    'wallets_succeeded / wallets_expected × 100.';

COMMENT ON COLUMN ingest_runs.duration_ms IS 
    'Run duration in milliseconds.';

COMMENT ON COLUMN ingest_runs.error IS 
    'Error message if failed.';


-- ---------------------------------------------------------------------
-- 7) ingest_health
-- ---------------------------------------------------------------------
-- Purpose:
--   Current system health state. Single row (or latest few).
--   Drives Signal Lock, alert suppression, dashboard masking.
--
-- Can be implemented as:
--   A) Single-row table (UPDATE on each cycle)
--   B) View over ingest_runs (SELECT latest)
--   C) Append-only with queries on latest row
--
-- This schema uses option C (append-only) for auditability.

CREATE TABLE IF NOT EXISTS ingest_health (
    health_ts                 TIMESTAMPTZ PRIMARY KEY,
    last_success_snapshot_ts  TIMESTAMPTZ NOT NULL,
    snapshot_status           TEXT NOT NULL,
    coverage_pct              NUMERIC NOT NULL CHECK (coverage_pct >= 0 AND coverage_pct <= 100),
    health_state              TEXT NOT NULL,
    error                     TEXT,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    CONSTRAINT chk_ih_snapshot_status 
        CHECK (snapshot_status IN ('success', 'partial', 'failed')),
    
    CONSTRAINT chk_ih_health_state 
        CHECK (health_state IN ('healthy', 'degraded', 'stale'))
);

CREATE INDEX IF NOT EXISTS idx_ih_health_ts_desc 
    ON ingest_health (health_ts DESC);

CREATE INDEX IF NOT EXISTS idx_ih_health_state_ts_desc 
    ON ingest_health (health_state, health_ts DESC);

COMMENT ON TABLE ingest_health IS 
    'Authoritative health state. Drives Signal Lock and dashboard masking.';

COMMENT ON COLUMN ingest_health.health_ts IS 
    'Health record timestamp (typically = snapshot_ts).';

COMMENT ON COLUMN ingest_health.last_success_snapshot_ts IS 
    'Most recent successful snapshot. Used for stale detection.';

COMMENT ON COLUMN ingest_health.snapshot_status IS 
    'Latest ingestion status: success | partial | failed.';

COMMENT ON COLUMN ingest_health.coverage_pct IS 
    'Latest wallet coverage percentage.';

COMMENT ON COLUMN ingest_health.health_state IS 
    'Computed state: healthy | degraded | stale.';

COMMENT ON COLUMN ingest_health.error IS 
    'Error summary if applicable.';


-- ---------------------------------------------------------------------
-- 8) signals
-- ---------------------------------------------------------------------
-- Purpose:
--   5-minute regime signals per asset.
--   Must obey Signal Lock (no writes when stale/failed).

CREATE TABLE IF NOT EXISTS signals (
    signal_ts           TIMESTAMPTZ NOT NULL,
    asset               TEXT NOT NULL,
    
    alignment_score     NUMERIC NOT NULL CHECK (alignment_score >= 0 AND alignment_score <= 100),
    alignment_trend     TEXT NOT NULL,
    dispersion_index    NUMERIC NOT NULL CHECK (dispersion_index >= 0 AND dispersion_index <= 100),
    exit_cluster_score  NUMERIC NOT NULL CHECK (exit_cluster_score >= 0 AND exit_cluster_score <= 100),
    
    allowed_playbook    TEXT NOT NULL,
    risk_mode           TEXT NOT NULL,
    add_exposure        BOOLEAN NOT NULL,
    tighten_stops       BOOLEAN NOT NULL,
    
    wallet_count        INTEGER NOT NULL CHECK (wallet_count >= 0),
    missing_count       INTEGER NOT NULL CHECK (missing_count >= 0),
    dirty_count         INTEGER NOT NULL DEFAULT 0 CHECK (dirty_count >= 0),
    
    is_degraded         BOOLEAN NOT NULL DEFAULT FALSE,
    degraded_reason     TEXT,
    
    computation_ms      INTEGER,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    CONSTRAINT pk_signals 
        PRIMARY KEY (signal_ts, asset),
    
    CONSTRAINT chk_sig_asset 
        CHECK (asset IN ('HYPE', 'BTC', 'ETH')),
    
    CONSTRAINT chk_sig_trend 
        CHECK (alignment_trend IN ('rising', 'flat', 'falling')),
    
    CONSTRAINT chk_sig_playbook 
        CHECK (allowed_playbook IN ('Long-only', 'Short-only', 'No-trade')),
    
    CONSTRAINT chk_sig_risk_mode 
        CHECK (risk_mode IN ('Normal', 'Reduced', 'Defensive'))
);

CREATE INDEX IF NOT EXISTS idx_sig_asset_ts_desc 
    ON signals (asset, signal_ts DESC);

CREATE INDEX IF NOT EXISTS idx_sig_ts_desc 
    ON signals (signal_ts DESC);

COMMENT ON TABLE signals IS 
    '5-minute regime signals. Must obey Signal Lock. Playbooks: Long-only | Short-only | No-trade.';

COMMENT ON COLUMN signals.signal_ts IS 
    'Signal timestamp (UTC), aligned to 5-minute boundary.';

COMMENT ON COLUMN signals.asset IS 
    'Asset: HYPE | BTC | ETH.';

COMMENT ON COLUMN signals.alignment_score IS 
    'Consensus Alignment Score (CAS) in [0,100].';

COMMENT ON COLUMN signals.alignment_trend IS 
    'CAS trend: rising | flat | falling.';

COMMENT ON COLUMN signals.dispersion_index IS 
    'Wallet disagreement in [0,100]. High (≥60) forces No-trade.';

COMMENT ON COLUMN signals.exit_cluster_score IS 
    'Reducer percentage in [0,100]. >25 indicates de-risking.';

COMMENT ON COLUMN signals.allowed_playbook IS 
    'Regime output: Long-only | Short-only | No-trade.';

COMMENT ON COLUMN signals.risk_mode IS 
    'Risk posture: Normal | Reduced | Defensive.';

COMMENT ON COLUMN signals.add_exposure IS 
    'Whether adding exposure is regime-allowed.';

COMMENT ON COLUMN signals.tighten_stops IS 
    'Whether stops should be tightened.';

COMMENT ON COLUMN signals.wallet_count IS 
    'Wallets included in computation.';

COMMENT ON COLUMN signals.missing_count IS 
    'Wallets excluded due to missing data.';

COMMENT ON COLUMN signals.dirty_count IS 
    'Wallets excluded due to dirty snapshots.';

COMMENT ON COLUMN signals.is_degraded IS 
    'True if forced conservative due to data quality.';

COMMENT ON COLUMN signals.degraded_reason IS 
    'Reason for degradation (e.g., low_coverage, high_dirty_rate).';

COMMENT ON COLUMN signals.computation_ms IS 
    'Signal computation duration in milliseconds.';


-- ---------------------------------------------------------------------
-- 9) signal_contributors
-- ---------------------------------------------------------------------
-- Purpose:
--   Pre-computed wallet behavior breakdown per signal period.
--   Displayed in dashboard detail section (collapsed by default).
--
-- Referenced by: skills/dashboard.md

CREATE TABLE IF NOT EXISTS signal_contributors (
    signal_ts        TIMESTAMPTZ NOT NULL,
    asset            TEXT NOT NULL,
    
    pct_add_long     NUMERIC NOT NULL CHECK (pct_add_long >= 0 AND pct_add_long <= 100),
    pct_add_short    NUMERIC NOT NULL CHECK (pct_add_short >= 0 AND pct_add_short <= 100),
    pct_reducers     NUMERIC NOT NULL CHECK (pct_reducers >= 0 AND pct_reducers <= 100),
    pct_flat         NUMERIC NOT NULL CHECK (pct_flat >= 0 AND pct_flat <= 100),
    
    count_add_long   INTEGER NOT NULL CHECK (count_add_long >= 0),
    count_add_short  INTEGER NOT NULL CHECK (count_add_short >= 0),
    count_reducers   INTEGER NOT NULL CHECK (count_reducers >= 0),
    count_flat       INTEGER NOT NULL CHECK (count_flat >= 0),
    
    total_wallets    INTEGER NOT NULL CHECK (total_wallets >= 0),
    
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    CONSTRAINT pk_signal_contributors 
        PRIMARY KEY (signal_ts, asset),
    
    CONSTRAINT chk_sc_asset 
        CHECK (asset IN ('HYPE', 'BTC', 'ETH')),
    
    CONSTRAINT chk_sc_pct_sum 
        CHECK (pct_add_long + pct_add_short + pct_reducers + pct_flat BETWEEN 99 AND 101)
);

CREATE INDEX IF NOT EXISTS idx_sc_asset_ts_desc 
    ON signal_contributors (asset, signal_ts DESC);

COMMENT ON TABLE signal_contributors IS 
    'Pre-computed wallet behavior breakdown per signal period. Displayed in dashboard.';

COMMENT ON COLUMN signal_contributors.signal_ts IS 
    'Signal timestamp (matches signals.signal_ts).';

COMMENT ON COLUMN signal_contributors.asset IS 
    'Asset: HYPE | BTC | ETH.';

COMMENT ON COLUMN signal_contributors.pct_add_long IS 
    'Percentage of wallets adding long exposure.';

COMMENT ON COLUMN signal_contributors.pct_add_short IS 
    'Percentage of wallets adding short exposure.';

COMMENT ON COLUMN signal_contributors.pct_reducers IS 
    'Percentage of wallets reducing exposure.';

COMMENT ON COLUMN signal_contributors.pct_flat IS 
    'Percentage of wallets with no significant change.';

COMMENT ON COLUMN signal_contributors.count_add_long IS 
    'Count of wallets adding long.';

COMMENT ON COLUMN signal_contributors.count_add_short IS 
    'Count of wallets adding short.';

COMMENT ON COLUMN signal_contributors.count_reducers IS 
    'Count of wallets reducing.';

COMMENT ON COLUMN signal_contributors.count_flat IS 
    'Count of flat wallets.';

COMMENT ON COLUMN signal_contributors.total_wallets IS 
    'Total wallets in computation.';


-- ---------------------------------------------------------------------
-- 10) alerts
-- ---------------------------------------------------------------------
-- Purpose:
--   Alert event history.
--   Behavioral alerts suppressed during degraded/stale.

CREATE TABLE IF NOT EXISTS alerts (
    id              SERIAL PRIMARY KEY,
    alert_ts        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    asset           TEXT,
    alert_type      TEXT NOT NULL,
    severity        TEXT NOT NULL,
    message         TEXT NOT NULL,
    signal_snapshot JSONB,
    cooldown_until  TIMESTAMPTZ,
    suppressed      BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    CONSTRAINT chk_alerts_asset 
        CHECK (asset IS NULL OR asset IN ('HYPE', 'BTC', 'ETH')),
    
    CONSTRAINT chk_alerts_type 
        CHECK (alert_type IN ('regime_change', 'exit_cluster', 'system_stale')),
    
    CONSTRAINT chk_alerts_severity 
        CHECK (severity IN ('medium', 'high', 'critical'))
);

CREATE INDEX IF NOT EXISTS idx_alerts_ts_desc 
    ON alerts (alert_ts DESC);

CREATE INDEX IF NOT EXISTS idx_alerts_asset_ts_desc 
    ON alerts (asset, alert_ts DESC);

CREATE INDEX IF NOT EXISTS idx_alerts_type_ts_desc 
    ON alerts (alert_type, alert_ts DESC);

CREATE INDEX IF NOT EXISTS idx_alerts_suppressed_ts_desc 
    ON alerts (suppressed, alert_ts DESC) 
    WHERE suppressed = FALSE;

COMMENT ON TABLE alerts IS 
    'Alert event history. Behavioral alerts suppressed during degraded/stale.';

COMMENT ON COLUMN alerts.id IS 
    'Auto-incrementing alert identifier.';

COMMENT ON COLUMN alerts.alert_ts IS 
    'Alert timestamp (UTC).';

COMMENT ON COLUMN alerts.asset IS 
    'Asset for asset-specific alerts; NULL for system alerts.';

COMMENT ON COLUMN alerts.alert_type IS 
    'Type: regime_change | exit_cluster | system_stale.';

COMMENT ON COLUMN alerts.severity IS 
    'Severity: medium | high | critical.';

COMMENT ON COLUMN alerts.message IS 
    'Human-readable alert message.';

COMMENT ON COLUMN alerts.signal_snapshot IS 
    'JSON snapshot of signals at alert time (for debugging).';

COMMENT ON COLUMN alerts.cooldown_until IS 
    'When this alert type can fire again for this asset.';

COMMENT ON COLUMN alerts.suppressed IS 
    'True if alert was suppressed (cooldown, daily limit, or health state).';


-- ---------------------------------------------------------------------
-- 11) alert_state
-- ---------------------------------------------------------------------
-- Purpose:
--   Persistent state for alert hysteresis and throttling.
--   One row per (asset, alert_type) pair.
--
-- Referenced by: skills/alerts.md

CREATE TABLE IF NOT EXISTS alert_state (
    asset               TEXT NOT NULL,
    alert_type          TEXT NOT NULL,
    
    is_active           BOOLEAN NOT NULL DEFAULT FALSE,
    last_triggered_ts   TIMESTAMPTZ,
    cooldown_until      TIMESTAMPTZ,
    
    daily_count         INTEGER NOT NULL DEFAULT 0 CHECK (daily_count >= 0),
    daily_window_start  TIMESTAMPTZ,
    
    -- For regime_change: track pending state for 2-period persistence
    pending_playbook    TEXT,
    pending_periods     INTEGER NOT NULL DEFAULT 0,
    
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    CONSTRAINT pk_alert_state 
        PRIMARY KEY (asset, alert_type),
    
    CONSTRAINT chk_as_asset 
        CHECK (asset IN ('HYPE', 'BTC', 'ETH', 'SYSTEM')),
    
    CONSTRAINT chk_as_type 
        CHECK (alert_type IN ('regime_change', 'exit_cluster', 'system_stale')),
    
    CONSTRAINT chk_as_pending_playbook 
        CHECK (pending_playbook IS NULL OR pending_playbook IN ('Long-only', 'Short-only', 'No-trade'))
);

COMMENT ON TABLE alert_state IS 
    'Persistent hysteresis and throttle state per (asset, alert_type).';

COMMENT ON COLUMN alert_state.asset IS 
    'Asset or SYSTEM for system-wide alerts.';

COMMENT ON COLUMN alert_state.alert_type IS 
    'Alert type: regime_change | exit_cluster | system_stale.';

COMMENT ON COLUMN alert_state.is_active IS 
    'True if alert condition is currently active (for hysteresis).';

COMMENT ON COLUMN alert_state.last_triggered_ts IS 
    'When alert last fired (for cooldown calculation).';

COMMENT ON COLUMN alert_state.cooldown_until IS 
    'Alert suppressed until this time.';

COMMENT ON COLUMN alert_state.daily_count IS 
    'Alerts fired in current 24h window.';

COMMENT ON COLUMN alert_state.daily_window_start IS 
    'Start of current 24h window for daily limit.';

COMMENT ON COLUMN alert_state.pending_playbook IS 
    'For regime_change: playbook awaiting 2-period persistence.';

COMMENT ON COLUMN alert_state.pending_periods IS 
    'For regime_change: consecutive periods at pending_playbook.';

COMMENT ON COLUMN alert_state.updated_at IS 
    'Row last updated (UTC).';


-- ---------------------------------------------------------------------
-- 12) Initialize alert_state rows
-- ---------------------------------------------------------------------
-- Pre-populate alert_state for all (asset, alert_type) combinations
-- to avoid NULL checks in application code.

INSERT INTO alert_state (asset, alert_type, is_active, daily_count, pending_periods)
VALUES 
    ('HYPE', 'regime_change', FALSE, 0, 0),
    ('HYPE', 'exit_cluster', FALSE, 0, 0),
    ('BTC', 'regime_change', FALSE, 0, 0),
    ('BTC', 'exit_cluster', FALSE, 0, 0),
    ('ETH', 'regime_change', FALSE, 0, 0),
    ('ETH', 'exit_cluster', FALSE, 0, 0),
    ('SYSTEM', 'system_stale', FALSE, 0, 0)
ON CONFLICT (asset, alert_type) DO NOTHING;


-- ---------------------------------------------------------------------
-- 13) Utility Views (Optional)
-- ---------------------------------------------------------------------

-- Latest health state (single row)
CREATE OR REPLACE VIEW v_latest_health AS
SELECT *
FROM ingest_health
ORDER BY health_ts DESC
LIMIT 1;

COMMENT ON VIEW v_latest_health IS 
    'Convenience view for latest health state.';


-- Latest signals per asset
CREATE OR REPLACE VIEW v_latest_signals AS
SELECT DISTINCT ON (asset) *
FROM signals
ORDER BY asset, signal_ts DESC;

COMMENT ON VIEW v_latest_signals IS 
    'Convenience view for latest signal per asset.';


-- Recent alerts (24h, non-suppressed)
CREATE OR REPLACE VIEW v_recent_alerts AS
SELECT *
FROM alerts
WHERE alert_ts > NOW() - INTERVAL '24 hours'
  AND suppressed = FALSE
ORDER BY 
    CASE WHEN alert_type = 'system_stale' THEN 0 ELSE 1 END,
    alert_ts DESC
LIMIT 5;

COMMENT ON VIEW v_recent_alerts IS 
    'Dashboard view: 5 most recent non-suppressed alerts, system_stale pinned.';


-- =====================================================================
-- End of Schema
-- =====================================================================
```

---

## Index Summary

| Table | Index | Purpose |
|-------|-------|---------|
| `wallet_snapshots` | `(asset, snapshot_ts DESC)` | Latest snapshots per asset |
| `wallet_snapshots` | `(wallet_id, asset, snapshot_ts DESC)` | Time series per wallet |
| `wallet_snapshots` | `(snapshot_ts DESC)` | Global recency |
| `wallet_snapshots` | `(is_dirty, snapshot_ts DESC) WHERE is_dirty` | Dirty diagnostics |
| `signals` | `(asset, signal_ts DESC)` | Latest signals per asset |
| `signals` | `(signal_ts DESC)` | Global recency |
| `alerts` | `(alert_ts DESC)` | Recent alerts |
| `alerts` | `(suppressed, alert_ts DESC) WHERE NOT suppressed` | Dashboard display |
| `ingest_runs` | `(snapshot_ts DESC)` | Recent runs |
| `ingest_health` | `(health_ts DESC)` | Latest health |

---

## Common Queries

### Dashboard: Get Latest Health
```sql
SELECT * FROM v_latest_health;
-- Or directly:
SELECT * FROM ingest_health ORDER BY health_ts DESC LIMIT 1;
```

### Dashboard: Get Latest Signals
```sql
SELECT * FROM v_latest_signals;
-- Or directly:
SELECT DISTINCT ON (asset) *
FROM signals
ORDER BY asset, signal_ts DESC;
```

### Dashboard: Get Signal History (6h)
```sql
SELECT *
FROM signals
WHERE asset = $1
  AND signal_ts > NOW() - INTERVAL '6 hours'
ORDER BY signal_ts DESC;
```

### Dashboard: Get Recent Alerts
```sql
SELECT * FROM v_recent_alerts;
```

### Signal Job: Check Signal Lock
```sql
SELECT health_state, snapshot_status, coverage_pct,
       EXTRACT(EPOCH FROM (NOW() - last_success_snapshot_ts))/60 AS stale_minutes
FROM ingest_health
ORDER BY health_ts DESC
LIMIT 1;
-- Proceed only if health_state != 'stale' AND snapshot_status != 'failed'
```

### Signal Job: Get Snapshots for Aggregation
```sql
SELECT *
FROM wallet_snapshots
WHERE asset = $1
  AND snapshot_ts BETWEEN $2 AND $3
  AND is_dirty = FALSE
ORDER BY wallet_id, snapshot_ts;
```

### Cleanup: Delete Old Snapshots
```sql
DELETE FROM wallet_snapshots
WHERE snapshot_ts < NOW() - INTERVAL '7 days';
```

---

## Migration Notes

### Initial Setup
```bash
createdb hyperliquid
psql -d hyperliquid -f db/schema.sql
```

### Verify Schema
```bash
psql -d hyperliquid -c "\dt"
psql -d hyperliquid -c "\di"
```

### Check Table Sizes
```sql
SELECT 
    relname AS table,
    pg_size_pretty(pg_total_relation_size(relid)) AS total_size,
    n_live_tup AS row_count
FROM pg_stat_user_tables
ORDER BY pg_total_relation_size(relid) DESC;
```

---

## Definition of Done

- [ ] All tables from skills files are defined
- [ ] All columns have CHECK constraints where applicable
- [ ] All tables have appropriate indexes
- [ ] All tables and columns have COMMENT documentation
- [ ] Playbook/risk mode values are consistent (capitalized)
- [ ] `alert_state` pre-populated for all combinations
- [ ] Utility views created for common queries
- [ ] Retention policy documented
- [ ] Common queries documented
- [ ] Migration instructions provided
