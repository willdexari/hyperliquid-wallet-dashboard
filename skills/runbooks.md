# skills/runbooks.md

## Purpose
Define **operational runbooks** for the Hyperliquid Wallet Dashboard.

This file answers one question only:

> "What do I do when something breaks?"

Runbooks prioritize:
- Safety over uptime
- Visibility over silent recovery
- Halting over guessing

If a situation is not covered here, default to **System Halt** (Runbook 8).

---

## Source of Truth
- For QA checks and health logic, follow `skills/qa.md`.
- For alert behavior, follow `skills/alerts.md`.
- For dashboard masking, follow `skills/dashboard.md`.
- This skill defines operational response procedures.

---

## Scope
Applies to:
- Universe refresh jobs
- Snapshot ingestion
- Signal computation
- Alert engine
- Streamlit dashboard
- PostgreSQL database

Assets: **HYPE, BTC, ETH only**

---

## Operational Philosophy (Force of Law)
- Never trade on uncertain data
- Never auto-recover into confidence
- Never hide failures
- Prefer halting the decision surface over partial correctness

---

## System States (Authoritative)

| State | Meaning | Trading Allowed |
|-------|---------|-----------------|
| Healthy | Data fresh, coverage complete | Yes (per playbook) |
| Degraded | Partial data or warnings | Caution only |
| Stale | Data unreliable or missing | **NO** |

If state is **Stale**, the system must halt visibly.

---

## Log Locations

| Component | Log Location |
|-----------|--------------|
| Ingestion | `logs/ingest.log` or stdout if interactive |
| Signals | `logs/signals.log` or stdout if interactive |
| Alerts | `logs/alerts.log` or stdout if interactive |
| Dashboard | Streamlit console output (stderr) |
| PostgreSQL | `/var/log/postgresql/` or `pg_log/` |

**Tip:** For interactive debugging, run components in foreground without `&`.

---

## Common Diagnostic Commands

### Check System Health (First Step for Any Issue)
```bash
# Overall health status
psql -d hyperliquid -c "
  SELECT 
    timestamp,
    status,
    coverage_pct,
    EXTRACT(EPOCH FROM (NOW() - timestamp))/60 AS age_minutes
  FROM ingest_runs 
  ORDER BY timestamp DESC 
  LIMIT 5;
"

# Check for active System Stale alert
psql -d hyperliquid -c "
  SELECT * FROM alerts 
  WHERE alert_type = 'system_stale' 
    AND timestamp > NOW() - INTERVAL '1 hour'
  ORDER BY timestamp DESC 
  LIMIT 1;
"
```

### Check Process Status
```bash
# All dashboard-related processes
ps aux | grep -E "(ingest|aggregate|streamlit)" | grep -v grep

# Check if jobs are running
pgrep -f "src.ingest.fetch" && echo "Ingest: RUNNING" || echo "Ingest: STOPPED"
pgrep -f "src.aggregate.run" && echo "Signals: RUNNING" || echo "Signals: STOPPED"
pgrep -f "streamlit" && echo "Dashboard: RUNNING" || echo "Dashboard: STOPPED"
```

### Check Database Connectivity
```bash
psql -d hyperliquid -c "SELECT 1 AS connected;"
```

---

## Component Control Commands

### Start Components
```bash
# Start ingestion (background)
nohup python -m src.ingest.fetch >> logs/ingest.log 2>&1 &

# Start signal computation (background)
nohup python -m src.aggregate.run >> logs/signals.log 2>&1 &

# Start dashboard (foreground recommended for debugging)
streamlit run src/ui/app.py

# Start dashboard (background)
nohup streamlit run src/ui/app.py >> logs/dashboard.log 2>&1 &
```

### Stop Components
```bash
# Stop ingestion
pkill -f "src.ingest.fetch"

# Stop signal computation
pkill -f "src.aggregate.run"

# Stop dashboard
pkill -f "streamlit"

# Stop all
pkill -f "src.ingest.fetch"; pkill -f "src.aggregate.run"; pkill -f "streamlit"
```

### Restart Components
```bash
# Restart ingestion
pkill -f "src.ingest.fetch"; sleep 2; nohup python -m src.ingest.fetch >> logs/ingest.log 2>&1 &

# Restart signals
pkill -f "src.aggregate.run"; sleep 2; nohup python -m src.aggregate.run >> logs/signals.log 2>&1 &

# Restart dashboard
pkill -f "streamlit"; sleep 2; streamlit run src/ui/app.py
```

---

## Severity Classifications

| Severity | Response Time | Trading Impact | Examples |
|----------|---------------|----------------|----------|
| **P1 - Critical** | Immediate | Full halt required | System Stale, DB down, dashboard showing stale data |
| **P2 - High** | < 15 minutes | Degraded, caution only | Partial ingestion, high dirty rate, alert spam |
| **P3 - Medium** | < 1 hour | Monitoring only | Universe refresh warning, single asset degraded |
| **P4 - Low** | Next session | None | Log warnings, minor anomalies |

---

## Runbook 1: Ingestion Failure (Partial or Full)

**Severity:** P1 (if Stale) / P2 (if Degraded)  
**Estimated Time to Recover:** 5–15 minutes (if API issue) / 1–2 minutes (if process crash)

### Symptoms
- `ingest_health.snapshot_status = failed`
- Coverage < 80%
- Snapshot age > 2 minutes and growing
- Dashboard shows SYSTEM HALT or Degraded banner

### Diagnostic Commands
```bash
# Check latest ingest runs
psql -d hyperliquid -c "
  SELECT timestamp, status, coverage_pct, wallet_success_count, wallet_fail_count, error
  FROM ingest_runs 
  ORDER BY timestamp DESC 
  LIMIT 10;
"

# Check snapshot age
psql -d hyperliquid -c "
  SELECT 
    NOW() AS current_time,
    MAX(timestamp) AS last_snapshot,
    EXTRACT(EPOCH FROM (NOW() - MAX(timestamp)))/60 AS age_minutes
  FROM wallet_snapshots;
"

# Check ingest process
ps aux | grep "src.ingest" | grep -v grep

# Check recent ingest logs
tail -100 logs/ingest.log | grep -E "(ERROR|WARN|rate.limit|timeout)"
```

### Automatic System Response
- Mark health as **Degraded** or **Stale**
- Suppress behavioral alerts
- If snapshot age > 10 minutes → emit **System Stale Alert**
- Dashboard decision surface masked

### Operator Actions
1. **Identify cause** from logs:
   - `429` / `rate limit` → API throttling (wait or reduce concurrency)
   - `timeout` / `connection` → Network or API outage
   - `KeyError` / `parse` → API response schema changed
   - No errors but process not running → Process crashed

2. **If API rate limited:**
   ```bash
   # Check current concurrency setting
   grep MAX_CONCURRENCY src/ingest/config.py
   
   # Temporarily reduce if needed (edit config, restart)
   ```

3. **If API down:**
   - Check Hyperliquid status (see Escalation)
   - Wait for recovery; do not force retries

4. **If process crashed:**
   ```bash
   # Restart ingestion
   pkill -f "src.ingest.fetch"; sleep 2
   nohup python -m src.ingest.fetch >> logs/ingest.log 2>&1 &
   ```

5. **Do NOT** restart signal or alert jobs until ingestion recovers

### Verify Recovery
```bash
psql -d hyperliquid -c "
  SELECT timestamp, status, coverage_pct 
  FROM ingest_runs 
  WHERE timestamp > NOW() - INTERVAL '10 minutes'
  ORDER BY timestamp DESC;
"
# Should show 2+ consecutive rows with:
#   status = 'success'
#   coverage_pct >= 90
```

### Recovery Criteria
- Two consecutive successful ingestion cycles
- Coverage ≥ 90%
- Snapshot age ≤ 2 minutes

Only then may signals and alerts resume automatically.

---

## Runbook 2: Leaderboard / Universe Refresh Failure

**Severity:** P3 (isolated) / P2 (if repeated)  
**Estimated Time to Recover:** 5–30 minutes (depends on upstream)

### Symptoms
- `wallet_universe_runs.status = failed`
- `n_received < 90%` of requested
- Rank integrity violation
- Logs show leaderboard fetch errors

### Diagnostic Commands
```bash
# Check recent universe refresh runs
psql -d hyperliquid -c "
  SELECT run_id, as_of_ts, status, n_requested, n_received, 
         entered_count, exited_count, churn_warning_count, error
  FROM wallet_universe_runs 
  ORDER BY as_of_ts DESC 
  LIMIT 10;
"

# Check current universe size
psql -d hyperliquid -c "
  SELECT COUNT(*) AS wallet_count, MAX(as_of_ts) AS last_refresh
  FROM wallet_universe_current;
"

# Test leaderboard endpoint directly
curl -s "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard" | head -c 500
```

### Automatic System Response
- Keep last known good universe
- Log warning
- Do not propagate failure downstream (ingestion continues with existing universe)

### Operator Actions
1. **Check upstream response:**
   ```bash
   # Fetch and inspect leaderboard
   curl -s "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard" | python -m json.tool | head -50
   ```

2. **Check for schema changes:**
   - Compare response fields to expected (`ethAddress`, `windowPerformances`, etc.)
   - If schema changed, update parser in `src/ingest/leaderboard.py`

3. **If churn_warning_count >= 3:**
   ```bash
   # Check churn pattern
   psql -d hyperliquid -c "
     SELECT as_of_ts, entered_count, exited_count, 
            (entered_count + exited_count)::float / n_requested * 100 AS churn_pct
     FROM wallet_universe_runs 
     ORDER BY as_of_ts DESC 
     LIMIT 10;
   "
   ```
   - High churn may indicate market event or API issue
   - Monitor but do not force refresh

4. **Do NOT** manually edit universe tables unless absolutely required

### Verify Recovery
```bash
psql -d hyperliquid -c "
  SELECT as_of_ts, status, n_received, churn_warning_count
  FROM wallet_universe_runs 
  WHERE status = 'success'
  ORDER BY as_of_ts DESC 
  LIMIT 1;
"
# Should show recent successful refresh with churn_warning_count = 0
```

### Recovery Criteria
- Successful refresh with valid rank integrity
- Universe size stable (n_received >= 90% of requested)
- Churn warning count reset to 0

---

## Runbook 3: Signal Job Halt (Signal Lock Triggered)

**Severity:** P2  
**Estimated Time to Recover:** Automatic once ingestion recovers

### Symptoms
- Signal job logs show "Signal computation blocked"
- No new rows in `signals` table
- Dashboard shows stale signal timestamps
- `ingest_health` shows Stale or failed status

### Diagnostic Commands
```bash
# Check signal job status
pgrep -f "src.aggregate.run" && echo "Process: RUNNING" || echo "Process: STOPPED"

# Check latest signals
psql -d hyperliquid -c "
  SELECT asset, timestamp, allowed_playbook, risk_mode
  FROM signals 
  WHERE timestamp = (SELECT MAX(timestamp) FROM signals)
  ORDER BY asset;
"

# Check signal age
psql -d hyperliquid -c "
  SELECT 
    MAX(timestamp) AS last_signal,
    EXTRACT(EPOCH FROM (NOW() - MAX(timestamp)))/60 AS age_minutes
  FROM signals;
"

# Check why Signal Lock triggered
tail -50 logs/signals.log | grep -E "(blocked|lock|health)"
```

### Automatic System Response
- No signals written (by design)
- Alerts suppressed
- Dashboard masked if Stale

### Operator Actions
1. **Confirm Signal Lock is working correctly** (this is expected behavior):
   ```bash
   # Check ingest health that triggered the lock
   psql -d hyperliquid -c "
     SELECT timestamp, status, coverage_pct,
            EXTRACT(EPOCH FROM (NOW() - timestamp))/60 AS age_minutes
     FROM ingest_runs 
     ORDER BY timestamp DESC 
     LIMIT 5;
   "
   ```

2. **Identify root cause** — Signal Lock triggers due to:
   - `status = 'failed'` → See Runbook 1 (Ingestion Failure)
   - `coverage_pct < 80` → See Runbook 1
   - `snapshot_age > 10 minutes` → See Runbook 1
   - System Stale alert active → See Runbook 1

3. **Do NOT bypass Signal Lock** — it exists to prevent bad signals

4. **If signal job process crashed** (not just locked):
   ```bash
   # Restart signal job
   nohup python -m src.aggregate.run >> logs/signals.log 2>&1 &
   ```

### Verify Recovery
```bash
# Watch for new signals (run after ingestion recovers)
psql -d hyperliquid -c "
  SELECT asset, timestamp, alignment_score, allowed_playbook
  FROM signals 
  WHERE timestamp > NOW() - INTERVAL '10 minutes'
  ORDER BY timestamp DESC;
"
# Should show new rows appearing at 5-minute intervals
```

### Recovery Criteria
- Ingest health returns to Healthy or Degraded
- Signal job resumes automatically on next 5-minute cycle
- New signals appear in table

---

## Runbook 4: Dirty Snapshot Spike (API Glitch)

**Severity:** P2 (if high rate) / P3 (if isolated)  
**Estimated Time to Recover:** Automatic once API stabilizes

### Symptoms
- Many snapshots flagged `is_dirty = true`
- Sudden position collapses (>99% drop) across multiple wallets
- Signals unexpectedly degraded to No-trade / Defensive
- Logs show "Dirty snapshot detected"

### Diagnostic Commands
```bash
# Check dirty rate by asset (last hour)
psql -d hyperliquid -c "
  SELECT 
    asset, 
    COUNT(*) FILTER (WHERE is_dirty) AS dirty_count,
    COUNT(*) AS total_count,
    ROUND(100.0 * COUNT(*) FILTER (WHERE is_dirty) / COUNT(*), 2) AS dirty_pct
  FROM wallet_snapshots
  WHERE timestamp > NOW() - INTERVAL '1 hour'
  GROUP BY asset
  ORDER BY asset;
"

# Check dirty snapshot details
psql -d hyperliquid -c "
  SELECT timestamp, wallet_id, asset, position_szi
  FROM wallet_snapshots
  WHERE is_dirty = true
    AND timestamp > NOW() - INTERVAL '1 hour'
  ORDER BY timestamp DESC
  LIMIT 20;
"

# Check for pattern: collapse then recovery
psql -d hyperliquid -c "
  SELECT 
    s1.wallet_id,
    s1.asset,
    s1.timestamp AS t0,
    s1.position_szi AS szi_t0,
    s2.position_szi AS szi_t1,
    s3.position_szi AS szi_t2
  FROM wallet_snapshots s1
  JOIN wallet_snapshots s2 ON s1.wallet_id = s2.wallet_id 
    AND s1.asset = s2.asset 
    AND s2.timestamp = s1.timestamp + INTERVAL '1 minute'
  JOIN wallet_snapshots s3 ON s1.wallet_id = s3.wallet_id 
    AND s1.asset = s3.asset 
    AND s3.timestamp = s1.timestamp + INTERVAL '2 minutes'
  WHERE s2.is_dirty = true
    AND s1.timestamp > NOW() - INTERVAL '1 hour'
  LIMIT 10;
"
```

### Automatic System Response
- Dirty snapshots ignored by signal aggregation
- Signals degrade to No-trade / Defensive if dirty rate > 10%
- Raw snapshots retained for audit

### Operator Actions
1. **Confirm pattern** (transient collapse, not real liquidations):
   - Multiple wallets affected simultaneously → likely API glitch
   - Single wallet affected → might be real (liquidation, close)

2. **Check upstream API stability:**
   ```bash
   # Test API response
   curl -s -X POST "https://api.hyperliquid.xyz/info" \
     -H "Content-Type: application/json" \
     -d '{"type":"clearinghouseState","user":"0x..."}' | python -m json.tool
   ```

3. **Do NOT delete raw snapshots** — needed for audit and pattern analysis

4. **If dirty rate sustained > 20%:**
   - Consider temporary halt (Runbook 8)
   - Investigate API issues (see Escalation)

### Verify Recovery
```bash
# Check dirty rate trending down
psql -d hyperliquid -c "
  SELECT 
    DATE_TRUNC('hour', timestamp) AS hour,
    ROUND(100.0 * COUNT(*) FILTER (WHERE is_dirty) / COUNT(*), 2) AS dirty_pct
  FROM wallet_snapshots
  WHERE timestamp > NOW() - INTERVAL '6 hours'
  GROUP BY DATE_TRUNC('hour', timestamp)
  ORDER BY hour;
"
# Should show dirty_pct decreasing to < 5%
```

### Recovery Criteria
- Dirty rate falls below 10%
- Signals automatically resume normal computation
- No manual intervention required

---

## Runbook 5: Alert Spam or Flicker

**Severity:** P2  
**Estimated Time to Recover:** 15–30 minutes (debugging)

### Symptoms
- Multiple Exit Cluster or Regime Change alerts in short period
- Alerts firing repeatedly near thresholds
- Daily alert cap being hit frequently

### Diagnostic Commands
```bash
# Check recent alert frequency
psql -d hyperliquid -c "
  SELECT 
    asset,
    alert_type,
    DATE_TRUNC('hour', timestamp) AS hour,
    COUNT(*) AS alert_count,
    COUNT(*) FILTER (WHERE suppressed) AS suppressed_count
  FROM alerts
  WHERE timestamp > NOW() - INTERVAL '24 hours'
  GROUP BY asset, alert_type, DATE_TRUNC('hour', timestamp)
  ORDER BY hour DESC, asset, alert_type;
"

# Check alert state (hysteresis)
psql -d hyperliquid -c "
  SELECT * FROM alert_state ORDER BY asset, alert_type;
"

# Check signal oscillation near thresholds
psql -d hyperliquid -c "
  SELECT timestamp, asset, exit_cluster_score, alignment_score, allowed_playbook
  FROM signals
  WHERE timestamp > NOW() - INTERVAL '2 hours'
    AND (exit_cluster_score BETWEEN 18 AND 27 
         OR alignment_score BETWEEN 23 AND 27 
         OR alignment_score BETWEEN 73 AND 77)
  ORDER BY timestamp DESC;
"
```

### Automatic System Response
- Hysteresis should prevent re-fire until reset threshold crossed
- Cooldown should enforce minimum gap between alerts
- Daily cap should limit to 4 per asset per 24h

### Operator Actions
1. **Verify hysteresis is working:**
   ```bash
   # Exit Cluster should not re-fire until reset below 20%
   psql -d hyperliquid -c "
     SELECT asset, is_active, last_triggered, cooldown_until
     FROM alert_state
     WHERE alert_type = 'exit_cluster';
   "
   ```

2. **Check if signals are genuinely oscillating:**
   - If yes → market is choppy, alerts are working correctly
   - If no → possible bug in alert engine

3. **If spam persists despite hysteresis:**
   ```bash
   # Temporarily disable alert engine (emergency only)
   pkill -f "src.alerts"
   ```
   - Treat as a **bug** — file issue and debug

4. **Do NOT widen thresholds blindly** — this hides problems, doesn't fix them

### Verify Recovery
```bash
# Check alert frequency normalized
psql -d hyperliquid -c "
  SELECT 
    asset,
    COUNT(*) AS alerts_24h
  FROM alerts
  WHERE timestamp > NOW() - INTERVAL '24 hours'
    AND suppressed = false
  GROUP BY asset;
"
# Should show <= 4 per asset
```

### Recovery Criteria
- Alert frequency returns to normal (≤ 4 per asset per day)
- Hysteresis and cooldowns functioning correctly
- No manual threshold changes required

---

## Runbook 6: Dashboard Shows Wrong or Dangerous Info

**Severity:** P1 - Critical (Release Blocker)  
**Estimated Time to Recover:** Varies (requires code fix)

### Symptoms
- Old signals visible during Stale state
- Asset panels visible while SYSTEM HALT banner active
- Price or indicators accidentally rendered
- Playbook shows Long-only when should be No-trade

### Diagnostic Commands
```bash
# Check actual health state
psql -d hyperliquid -c "
  SELECT 
    timestamp,
    status,
    coverage_pct,
    EXTRACT(EPOCH FROM (NOW() - timestamp))/60 AS age_minutes,
    CASE 
      WHEN EXTRACT(EPOCH FROM (NOW() - timestamp))/60 > 10 THEN 'STALE'
      WHEN coverage_pct < 80 THEN 'STALE'
      WHEN EXTRACT(EPOCH FROM (NOW() - timestamp))/60 > 2 OR coverage_pct < 90 THEN 'DEGRADED'
      ELSE 'HEALTHY'
    END AS expected_health_state
  FROM ingest_runs 
  ORDER BY timestamp DESC 
  LIMIT 1;
"

# Check what signals dashboard should show
psql -d hyperliquid -c "
  SELECT asset, timestamp, allowed_playbook, risk_mode, is_degraded
  FROM signals 
  WHERE timestamp = (SELECT MAX(timestamp) FROM signals);
"
```

### Automatic System Response
- None (this is a UI bug)

### Operator Actions
1. **Immediately stop using the dashboard for trading decisions**

2. **Verify the bug:**
   - Compare DB state (above queries) to what dashboard shows
   - Screenshot the discrepancy

3. **Check UI code:**
   ```bash
   # Verify health check logic
   grep -n "health_state" src/ui/app.py
   
   # Verify st.stop() is called
   grep -n "st.stop" src/ui/app.py
   ```

4. **If Stale but decision surfaces visible:**
   - This is a critical bug in Decision Surface Mask
   - Check `if health_state == "STALE"` logic
   - Verify `st.stop()` is called

5. **Block release until fixed** — do not deploy or use

### Verify Recovery
```bash
# After fix, test by simulating stale state
# (Stop ingestion, wait 10+ minutes, verify SYSTEM HALT appears)
pkill -f "src.ingest.fetch"
# Wait 10 minutes
# Dashboard should show SYSTEM HALT, no decision surfaces
```

### Recovery Criteria
- Bug identified and fixed in code
- Decision Surface Mask verified working
- Manual QA confirms no information leakage during Stale

---

## Runbook 7: Database Issues

**Severity:** P1 - Critical  
**Estimated Time to Recover:** 5–60 minutes (depends on issue)

### Symptoms
- "Connection refused" errors in logs
- "Disk full" errors
- Queries timing out
- All components failing simultaneously

### Diagnostic Commands
```bash
# Test connection
psql -d hyperliquid -c "SELECT 1;" 2>&1

# Check if PostgreSQL is running
pg_isready -d hyperliquid

# Check disk space
df -h

# Check database size
psql -d hyperliquid -c "
  SELECT pg_size_pretty(pg_database_size('hyperliquid')) AS db_size;
"

# Check table sizes
psql -d hyperliquid -c "
  SELECT 
    relname AS table,
    pg_size_pretty(pg_total_relation_size(relid)) AS total_size,
    n_live_tup AS row_count
  FROM pg_stat_user_tables
  ORDER BY pg_total_relation_size(relid) DESC;
"

# Check for locks
psql -d hyperliquid -c "
  SELECT pid, state, query, wait_event_type, wait_event
  FROM pg_stat_activity
  WHERE datname = 'hyperliquid' AND state != 'idle';
"
```

### Operator Actions

**If connection refused:**
```bash
# Start PostgreSQL
sudo systemctl start postgresql
# or
pg_ctl -D /var/lib/postgresql/data start
```

**If disk full:**
```bash
# Check what's using space
du -sh logs/*
du -sh /var/lib/postgresql/*

# Truncate old logs
> logs/ingest.log
> logs/signals.log

# Vacuum database
psql -d hyperliquid -c "VACUUM FULL;"

# Delete old snapshots (if necessary, keep 7 days minimum)
psql -d hyperliquid -c "
  DELETE FROM wallet_snapshots 
  WHERE timestamp < NOW() - INTERVAL '7 days';
"
```

**If queries slow:**
```bash
# Check for missing indexes
psql -d hyperliquid -c "
  SELECT schemaname, tablename, indexname 
  FROM pg_indexes 
  WHERE schemaname = 'public';
"

# Analyze tables
psql -d hyperliquid -c "ANALYZE;"
```

**If locked queries:**
```bash
# Kill blocking query (use pid from diagnostic)
psql -d hyperliquid -c "SELECT pg_terminate_backend(<pid>);"
```

### Verify Recovery
```bash
# Verify connection and basic query
psql -d hyperliquid -c "
  SELECT COUNT(*) FROM wallet_snapshots 
  WHERE timestamp > NOW() - INTERVAL '5 minutes';
"
# Should return quickly with recent count
```

### Recovery Criteria
- Database accepting connections
- Queries completing in reasonable time
- Disk space > 20% free
- All components can write successfully

---

## Runbook 8: Full System Halt (Manual)

**Severity:** P1 - Critical  
**Estimated Time to Recover:** 15–60 minutes (depends on root cause)

### When to Use
- Multiple subsystems failing simultaneously
- Inconsistent data across components
- Loss of trust in data integrity
- Unknown failure mode not covered by other runbooks

### Operator Actions

**Step 1: Stop all processing (preserve data)**
```bash
# Stop in order: alerts → signals → (leave ingestion if safe)
pkill -f "src.alerts"
pkill -f "src.aggregate.run"

# Only stop ingestion if it's causing problems
# pkill -f "src.ingest.fetch"

echo "Processing stopped at $(date)" >> logs/halt.log
```

**Step 2: Verify dashboard is in Stale mode**
- Dashboard should automatically show SYSTEM HALT
- If not, stop dashboard: `pkill -f "streamlit"`

**Step 3: Diagnose root cause**
```bash
# Check all health indicators
psql -d hyperliquid -c "
  SELECT 'ingest' AS component, timestamp, status, coverage_pct 
  FROM ingest_runs ORDER BY timestamp DESC LIMIT 1
  UNION ALL
  SELECT 'signals', timestamp, 'n/a', NULL
  FROM signals ORDER BY timestamp DESC LIMIT 1
  UNION ALL
  SELECT 'alerts', timestamp, alert_type, NULL
  FROM alerts ORDER BY timestamp DESC LIMIT 1;
"

# Check recent errors across all logs
grep -h "ERROR" logs/*.log | tail -50
```

**Step 4: Document the incident**
```bash
# Create incident log
echo "=== INCIDENT $(date) ===" >> logs/incidents.log
echo "Symptoms: [describe]" >> logs/incidents.log
echo "Root cause: [describe]" >> logs/incidents.log
echo "Actions taken: [describe]" >> logs/incidents.log
```

**Step 5: Controlled restart** (only after root cause identified)
```bash
# Start in order: ingestion → (wait for 2 cycles) → signals → alerts → dashboard

# 1. Start ingestion
nohup python -m src.ingest.fetch >> logs/ingest.log 2>&1 &

# 2. Wait for 2 successful cycles (2-3 minutes)
sleep 180
psql -d hyperliquid -c "
  SELECT timestamp, status, coverage_pct 
  FROM ingest_runs 
  ORDER BY timestamp DESC LIMIT 3;
"

# 3. Start signals (only if ingestion healthy)
nohup python -m src.aggregate.run >> logs/signals.log 2>&1 &

# 4. Start dashboard
streamlit run src/ui/app.py
```

### Resume Criteria
- Root cause identified and documented
- At least 2 clean ingestion cycles (status=success, coverage>=90%)
- Signals recompute cleanly (no errors, values in bounds)
- No unexpected alerts on startup
- Dashboard shows Healthy state

---

## Runbook 9: Process Crash (OOM, Unexpected Exit)

**Severity:** P2  
**Estimated Time to Recover:** 2–10 minutes

### Symptoms
- Process not running but no manual stop
- Logs end abruptly
- "Killed" message in system logs (OOM)

### Diagnostic Commands
```bash
# Check if process is running
pgrep -f "src.ingest.fetch" || echo "Ingest NOT running"
pgrep -f "src.aggregate.run" || echo "Signals NOT running"
pgrep -f "streamlit" || echo "Dashboard NOT running"

# Check system logs for OOM killer
dmesg | grep -i "killed process" | tail -10
journalctl -xe | grep -i "out of memory" | tail -10

# Check memory usage
free -h

# Check last lines of log before crash
tail -50 logs/ingest.log
tail -50 logs/signals.log
```

### Operator Actions

**If OOM killed:**
```bash
# Check what's using memory
ps aux --sort=-%mem | head -20

# Reduce memory usage in config if needed
# e.g., reduce MAX_CONCURRENCY, batch sizes

# Restart with memory monitoring
nohup python -m src.ingest.fetch >> logs/ingest.log 2>&1 &
watch -n 5 'free -h'
```

**If crashed without OOM:**
```bash
# Check for Python errors
tail -100 logs/ingest.log | grep -E "(Error|Exception|Traceback)"

# Check for unhandled exceptions
grep -A 5 "Traceback" logs/*.log | tail -50

# Restart after reviewing error
nohup python -m src.ingest.fetch >> logs/ingest.log 2>&1 &
```

**For persistent crashes:**
- Add more logging around crash point
- Consider running in foreground to see immediate output
- Check for resource leaks (connections, file handles)

### Verify Recovery
```bash
# Verify process running and producing output
pgrep -f "src.ingest.fetch" && tail -f logs/ingest.log

# Should see regular log entries without errors
```

### Recovery Criteria
- Process running continuously for 10+ minutes
- No OOM kills
- Logs showing normal operation

---

## What NOT to Do (Under Any Circumstances)

| Action | Why It's Dangerous |
|--------|-------------------|
| "Force run" signals during Stale | Produces unreliable signals |
| Manually edit signal values | Breaks data integrity |
| Silence alerts without understanding why | Hides real problems |
| Trade off partially masked dashboards | Data may be wrong |
| Override QA gates | Defeats safety system |
| Delete snapshots to "fix" dirty rate | Loses audit trail |
| Widen alert thresholds to stop spam | Hides real signals |
| Restart everything without diagnosis | May repeat the failure |

---

## Escalation

For issues beyond these runbooks:

### External Resources
- **Hyperliquid API Status:** Check their Discord for outage announcements
- **Hyperliquid Discord:** https://discord.gg/hyperliquid
- **API Documentation:** https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api

### Internal Resources
- **System Design:** `docs/architecture/schema.md`
- **Signal Logic:** `skills/signals.md`
- **QA Rules:** `skills/qa.md`

### When to Escalate
- API returning unexpected data format (schema change)
- Sustained outage > 1 hour with no external announcements
- Data corruption that can't be explained by runbooks
- Security concerns (unexpected access patterns)

---

## Definition of Done

This runbook is complete when:

- [ ] Runbook 1: Ingestion Failure — documented with commands
- [ ] Runbook 2: Universe Refresh Failure — documented with commands
- [ ] Runbook 3: Signal Lock Triggered — documented with commands
- [ ] Runbook 4: Dirty Snapshot Spike — documented with commands
- [ ] Runbook 5: Alert Spam — documented with commands
- [ ] Runbook 6: Dashboard Wrong Info — documented with commands
- [ ] Runbook 7: Database Issues — documented with commands
- [ ] Runbook 8: Full System Halt — documented with commands
- [ ] Runbook 9: Process Crash — documented with commands
- [ ] All runbooks have diagnostic commands
- [ ] All runbooks have verification steps
- [ ] All runbooks have recovery criteria
- [ ] Severity and time-to-recover documented
- [ ] Escalation path documented

---

## Final Principle

If you ever think:

> "It's probably fine, I'll just take the trade…"

The system has already failed.

This runbook exists so that **never happens**.

When in doubt: **halt, diagnose, then recover**. Never guess.
