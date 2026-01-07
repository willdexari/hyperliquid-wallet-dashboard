-- =====================================================================
-- Hyperliquid Wallet Dashboard MVP Schema
-- Version: 1.0
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1) wallet_universe_current
-- ---------------------------------------------------------------------
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


-- ---------------------------------------------------------------------
-- 2) wallet_universe_runs
-- ---------------------------------------------------------------------
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


-- ---------------------------------------------------------------------
-- 3) wallet_universe_members
-- ---------------------------------------------------------------------
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


-- ---------------------------------------------------------------------
-- 4) wallet_snapshots
-- ---------------------------------------------------------------------
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

CREATE INDEX IF NOT EXISTS idx_ws_asset_ts_desc 
    ON wallet_snapshots (asset, snapshot_ts DESC);

CREATE INDEX IF NOT EXISTS idx_ws_wallet_asset_ts_desc 
    ON wallet_snapshots (wallet_id, asset, snapshot_ts DESC);

CREATE INDEX IF NOT EXISTS idx_ws_ts_desc 
    ON wallet_snapshots (snapshot_ts DESC);

CREATE INDEX IF NOT EXISTS idx_ws_dirty_ts_desc 
    ON wallet_snapshots (is_dirty, snapshot_ts DESC) 
    WHERE is_dirty = TRUE;


-- ---------------------------------------------------------------------
-- 5) snapshot_anomalies
-- ---------------------------------------------------------------------
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


-- ---------------------------------------------------------------------
-- 6) ingest_runs
-- ---------------------------------------------------------------------
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


-- ---------------------------------------------------------------------
-- 7) ingest_health
-- ---------------------------------------------------------------------
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


-- ---------------------------------------------------------------------
-- 8) signals
-- ---------------------------------------------------------------------
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


-- ---------------------------------------------------------------------
-- 9) signal_contributors
-- ---------------------------------------------------------------------
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


-- ---------------------------------------------------------------------
-- 10) alerts
-- ---------------------------------------------------------------------
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


-- ---------------------------------------------------------------------
-- 11) alert_state
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alert_state (
    asset               TEXT NOT NULL,
    alert_type          TEXT NOT NULL,
    
    is_active           BOOLEAN NOT NULL DEFAULT FALSE,
    last_triggered_ts   TIMESTAMPTZ,
    cooldown_until      TIMESTAMPTZ,
    
    daily_count         INTEGER NOT NULL DEFAULT 0 CHECK (daily_count >= 0),
    daily_window_start  TIMESTAMPTZ,
    
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


-- ---------------------------------------------------------------------
-- 12) Initialize alert_state rows
-- ---------------------------------------------------------------------
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
-- 13) Utility Views
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_latest_health AS
SELECT *
FROM ingest_health
ORDER BY health_ts DESC
LIMIT 1;

CREATE OR REPLACE VIEW v_latest_signals AS
SELECT DISTINCT ON (asset) *
FROM signals
ORDER BY asset, signal_ts DESC;

CREATE OR REPLACE VIEW v_recent_alerts AS
SELECT *
FROM alerts
WHERE alert_ts > NOW() - INTERVAL '24 hours'
  AND suppressed = FALSE
ORDER BY 
    CASE WHEN alert_type = 'system_stale' THEN 0 ELSE 1 END,
    alert_ts DESC
LIMIT 5;


-- =====================================================================
-- End of Schema
-- =====================================================================