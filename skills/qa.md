# skills/qa.md

## Purpose
Define **QA checks and safety gates** for the Hyperliquid Wallet Dashboard.

This file prevents the two most expensive failure modes:
1) **Silent data corruption** (looks fine, is wrong)
2) **Stale or incomplete data driving decisions**

QA checks must be deterministic, cheap, enforced automatically, and capable of halting the pipeline.

---

## Source of Truth
- For signal definitions, follow `skills/signals.md`.
- For alert logic, follow `skills/alerts.md`.
- For dashboard behavior, follow `skills/dashboard.md`.
- This skill defines QA checks that enforce rules from other skills.

---

## Scope
Applies to:
- Universe refresh
- Snapshot ingestion
- Signal computation
- Alert generation
- Dashboard health state and masking

Assets: **HYPE, BTC, ETH only**

---

## QA Philosophy (Force of Law)

**Prefer halting over trading on bad data.**

If a QA check fails:
- **Do not proceed** to downstream stages
- Mark health as **Degraded** or **Stale**
- Suppress behavioral alerts
- Mask the decision surface if Stale

| Failure Type | Outcome |
|--------------|---------|
| False negative (halt when data is actually fine) | Lost trading opportunity |
| False positive (proceed when data is bad) | Potential loss from bad decision |

False negatives are recoverable. False positives can be catastrophic.

---

## Health State (Single Source of Truth)

Health state is computed from `ingest_health` and must match dashboard rules (per `skills/dashboard.md`):

| State | Conditions |
|-------|------------|
| **Healthy** | snapshot_age ≤ 2m AND coverage ≥ 90% |
| **Degraded** | snapshot_age 2–10m OR coverage 80–90% |
| **Stale** | snapshot_age > 10m OR coverage < 80% OR system_stale alert active OR snapshot_status = failed |

**If health is Stale:**
- Dashboard must unmount all decision surfaces (`st.stop()`)
- Only system alert surfaces may render
- Signal computation must halt
- Behavioral alerts must be suppressed

---

## Gated Pipeline Architecture (Critical)

This system is a **gated pipeline**. Downstream stages must not "best guess" when upstream health is bad.

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Universe   │────▶│   Snapshot   │────▶│    Signal    │────▶│  Dashboard   │
│   Refresh    │     │   Ingestion  │     │  Computation │     │   Render     │
└──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘
       │                    │                    │                    │
       ▼                    ▼                    ▼                    ▼
   [U1-U5]              [S1-S7]              [G0-G6]              [D1-D4]
    checks               checks               checks               checks
       │                    │                    │                    │
       ▼                    ▼                    ▼                    ▼
   If fail:             If fail:             If fail:             If fail:
   Keep last            Mark health          Skip cycle           Mask UI
   good universe        Degraded/Stale       No signals           st.stop()
```

Each stage gates the next. No stage may proceed if its upstream is unhealthy.

---

## Signal Lock Mechanism (Mandatory)

The signal computation job MUST check `ingest_health` before computing signals for each cycle.

### Check Logic
```python
def should_compute_signals() -> tuple[bool, str]:
    """Check if signal computation should proceed."""
    health = get_latest_ingest_health()
    
    if health.status == "failed":
        return False, "Ingest status is failed"
    
    if health.snapshot_age_minutes > 10:
        return False, f"Data stale: {health.snapshot_age_minutes}m since last snapshot"
    
    if health.coverage_pct < 80:
        return False, f"Coverage too low: {health.coverage_pct}%"
    
    if is_system_stale_alert_active():
        return False, "System Stale alert is active"
    
    return True, "OK"
```

### Behavior When Blocked
```python
def signal_computation_loop():
    while True:
        # Wait for next 5-minute boundary
        sleep_until_next_5min_boundary()
        
        # Check health gate
        can_proceed, reason = should_compute_signals()
        
        if not can_proceed:
            log.warning(f"Signal computation blocked: {reason}")
            # Do NOT write partial signals
            # Do NOT write placeholder rows
            # Do NOT exit (would require manual restart)
            continue  # Sleep until next boundary
        
        # Proceed with computation
        compute_and_write_signals()
```

**Rules:**
- The job should NOT exit entirely on health failure (would require manual restart)
- Use a loop that checks health at each 5-minute boundary
- Log every blocked cycle with reason
- Never write partial or placeholder signals when blocked

### Mid-Computation Health Transition

If health transitions to Stale during signal computation:
- Discard partial results immediately
- Do not write to signals table
- Log: `"Signal computation aborted: health transitioned to Stale"`
- Wait for next cycle

```python
def compute_and_write_signals():
    results = {}
    
    for asset in ["HYPE", "BTC", "ETH"]:
        # Re-check health before each asset (defensive)
        can_proceed, reason = should_compute_signals()
        if not can_proceed:
            log.warning(f"Aborting mid-computation: {reason}")
            return  # Discard all partial results
        
        results[asset] = compute_signals_for_asset(asset)
    
    # Final health check before write
    can_proceed, reason = should_compute_signals()
    if not can_proceed:
        log.warning(f"Aborting before write: {reason}")
        return
    
    # All checks passed, write atomically
    write_signals(results)
```

---

## Checks by Stage

---

## 1) Universe Refresh QA

### U1. Non-empty Universe
- **Required:** `n_received > 0`
- **Failure action:** Mark run failed, do not update `wallet_universe_current`
- **Log:** `"Universe refresh failed: empty response"`

### U2. Minimum Completeness
- **Required:** `n_received >= 0.9 * n_requested`
- **Failure action:** Mark run failed, keep last known good universe
- **Log:** `"Universe refresh failed: only {n_received}/{n_requested} wallets received"`

### U3. Rank Integrity
- **Required:**
  - Ranks are unique within run
  - Ranks start at 1
  - Max rank == n_received
- **Failure action:** Mark run failed
- **Log:** `"Universe refresh failed: rank integrity violation"`

### U4. Wallet ID Validity
- **Required:**
  - All wallet_id values non-empty
  - No duplicate wallet_id within a run
- **Failure action:** Mark run failed
- **Log:** `"Universe refresh failed: invalid or duplicate wallet IDs"`

### U5. Universe Churn Guard (Warning)
Excessive churn may indicate API issues or market anomalies.

**Calculation:**
```python
entered = wallets_in_new - wallets_in_prior
exited = wallets_in_prior - wallets_in_new
churn_rate = (len(entered) + len(exited)) / n_requested * 100
```

**Thresholds:**
| Churn Rate | Action |
|------------|--------|
| ≤ 30% | Normal, reset warning count |
| > 30% | Log warning, increment `churn_warning_count` |
| > 30% for 3 consecutive runs | Mark run failed |

**State tracking:**
```sql
-- Add to wallet_universe_runs table
ALTER TABLE wallet_universe_runs ADD COLUMN churn_warning_count INTEGER DEFAULT 0;
```

```python
if churn_rate > 30:
    prior_warning_count = get_prior_run_churn_warning_count()
    new_warning_count = prior_warning_count + 1
    
    if new_warning_count >= 3:
        mark_run_failed("Churn rate >30% for 3 consecutive runs")
    else:
        log.warning(f"High churn rate: {churn_rate:.1f}% (warning {new_warning_count}/3)")
else:
    new_warning_count = 0  # Reset on normal churn
```

---

## 2) Snapshot Ingestion QA

### S1. Timestamp Boundary
- **Required:** `snapshot_ts` aligned to 60-second boundary
- **Validation:** `snapshot_ts.second == 0 AND snapshot_ts.microsecond == 0`
- **Failure action:** Do not write snapshots, mark run failed
- **Log:** `"Snapshot failed: timestamp {ts} not aligned to 60s boundary"`

### S2. Expected Row Count
- **Calculation:** `expected_rows = wallets_in_universe * 3` (one per asset)
- **Required:** Computation matches expected
- **Failure action:** Mark run failed if expected_rows cannot be determined
- **Log:** `"Snapshot failed: cannot determine expected row count"`

### S3. Coverage Threshold
- **Calculation:** `coverage_pct = wallets_succeeded / wallets_expected * 100`
- **Required:** Coverage computed and stored in `ingest_health`
- **Thresholds:**

| Coverage | Health State | Action |
|----------|--------------|--------|
| ≥ 90% | Healthy | Proceed normally |
| 80–90% | Degraded | Log warning, continue |
| < 80% | Stale | Force Stale, suppress signals |

- **Failure action:** If coverage cannot be computed, mark run failed

### S4. Duplicate Key Protection
- **Required:** No duplicate rows for `(snapshot_ts, wallet_id, asset)`
- **Enforcement:**
  - DB unique constraint on `(timestamp, wallet_id, asset)`
  - Use UPSERT (INSERT ... ON CONFLICT UPDATE)
- **Failure action:** If constraint violation occurs unexpectedly, mark run failed and emit system alert
- **Log:** `"Snapshot failed: duplicate key violation for {wallet_id}/{asset}"`

### S5. Position Proxy Sanity (Per-Asset)
Track non-null rate for `position_szi` per asset.

**Calculation:**
```python
for asset in ["HYPE", "BTC", "ETH"]:
    non_null_count = count_where(asset=asset, position_szi IS NOT NULL)
    total_count = count_where(asset=asset)
    non_null_rate = non_null_count / total_count * 100
```

**Thresholds (per asset):**
| Non-null Rate | Health Impact | Action |
|---------------|---------------|--------|
| ≥ 80% | None | Proceed normally |
| 60–80% | Degraded | Force Degraded for that asset |
| < 60% | Stale | Force Stale |

- **Log:** `"Position proxy degraded for {asset}: {non_null_rate:.1f}% non-null"`

### S6. Dirty Snapshot Detection (Outlier Jump)

Outlier jumps can be real or API glitches. Store raw data but mark suspicious patterns as **Dirty**.

**Dirty Pattern: Transient Zero/Null Collapse**

Detects when a position briefly disappears then returns.

**Detection window:** 3 consecutive snapshots (t, t+60s, t+120s)

**Conditions:**
```python
szi_t0 = snapshot_at(t).position_szi
szi_t1 = snapshot_at(t + 60s).position_szi
szi_t2 = snapshot_at(t + 120s).position_szi

# Collapse condition: position nearly disappears
is_collapse = (
    szi_t0 is not None and abs(szi_t0) > epsilon and
    (szi_t1 is None or abs(szi_t1) < 0.01 * abs(szi_t0))
)

# Recovery condition: position returns to significant level
is_recovery = (
    szi_t2 is not None and 
    abs(szi_t2) > 0.50 * abs(szi_t0)
)

# Mark middle snapshot as dirty if both conditions met
if is_collapse and is_recovery:
    mark_dirty(snapshot_at(t + 60s), reason="transient_collapse")
```

**Storage options:**
```sql
-- Option A: Boolean flag on snapshots
ALTER TABLE wallet_snapshots ADD COLUMN is_dirty BOOLEAN DEFAULT FALSE;

-- Option B: Separate anomaly table (preferred for auditability)
CREATE TABLE snapshot_anomalies (
    id SERIAL PRIMARY KEY,
    snapshot_ts TIMESTAMPTZ NOT NULL,
    wallet_id TEXT NOT NULL,
    asset TEXT NOT NULL,
    anomaly_type TEXT NOT NULL,  -- 'transient_collapse', etc.
    metadata JSONB,
    detected_at TIMESTAMPTZ DEFAULT NOW()
);
```

**Rules:**
- Dirty snapshots remain in storage for auditability
- Signal aggregation MUST ignore dirty snapshots (enforced by G4)
- Log: `"Dirty snapshot detected: {wallet_id}/{asset} at {ts} (transient_collapse)"`

### S7. Latency / Stale Switch (Fatal)

**Condition:** `now() - last_success_snapshot_ts > 10 minutes`

**Actions:**
1. Emit System Stale alert (Critical severity)
2. Force `health_state = Stale`
3. Suppress all behavioral alerts
4. Dashboard enters SYSTEM HALT mode

**Cross-reference:** Enforces `skills/alerts.md` System Stale Alert rules.

---

## 3) Signal Computation QA

### G0. Signal Lock (Mandatory)
- **Required:** Check `ingest_health` before any computation
- **Behavior:** See "Signal Lock Mechanism" section above
- **Failure action:** Skip cycle, write no signals
- **Cross-reference:** Gates all of `skills/signals.md`

### G1. Signal Timestamp Boundary
- **Required:** `signal_ts` aligned to 5-minute boundary
- **Validation:** `signal_ts.minute % 5 == 0 AND signal_ts.second == 0`
- **Failure action:** Do not write signals for that timestamp
- **Log:** `"Signal computation failed: timestamp {ts} not aligned to 5m boundary"`

### G2. Sufficient Input Window
- **Required:** At least 5 snapshots exist in last 5-minute window per asset
- **Rationale:** 5 minutes at 60s cadence = 5 snapshots. Requiring 5 ensures no gaps.
- **Threshold:** If only 4 snapshots available, allow with Degraded flag

| Snapshots Available | Action |
|---------------------|--------|
| 5 | Proceed normally |
| 4 | Proceed with `is_degraded = true` |
| < 4 | Skip asset, mark failed |

- **Failure action:** Force No-trade / Defensive for affected asset
- **Log:** `"Insufficient snapshots for {asset}: {count}/5"`

### G3. Coverage Gate for Signals
- **Required:** Wallet coverage ≥ 90% over the 5-minute window for non-degraded signals
- **Failure action:**
  - Set `is_degraded = true`
  - Set `allowed_playbook = No-trade`
  - Set `risk_mode = Defensive`
- **Cross-reference:** Enforces `skills/signals.md` missing data handling

### G4. Dirty Data Exclusion
- **Required:** Signal aggregation MUST exclude snapshots marked dirty (S6)
- **Implementation:**
```python
snapshots = query("""
    SELECT * FROM wallet_snapshots
    WHERE timestamp BETWEEN :start AND :end
      AND asset = :asset
      AND is_dirty = FALSE  -- Exclude dirty
""")
```
- **Threshold:** If dirty rate > 10% of snapshots in window, force Degraded
- **Failure action:** Set `degraded_reason = "high_dirty_rate"`, force No-trade / Defensive
- **Log:** `"High dirty rate for {asset}: {dirty_pct:.1f}%"`

### G5. Bounds Checks
- **Required:**
  - `0 ≤ alignment_score ≤ 100`
  - `0 ≤ dispersion_index ≤ 100`
  - `0 ≤ exit_cluster_score ≤ 100`
  - `alignment_trend ∈ {'rising', 'flat', 'falling'}`
  - `allowed_playbook ∈ {'Long-only', 'Short-only', 'No-trade'}`
  - `risk_mode ∈ {'Normal', 'Reduced', 'Defensive'}`

- **Failure action:** Do not write row, mark run failed
- **Log:** `"Signal bounds violation: {field}={value} out of range"`

### G6. Signal Invariants
Enforce tie-breaker rules from `skills/signals.md`:

| Condition | Required Output |
|-----------|-----------------|
| `dispersion_index >= 60` (High) | `allowed_playbook = No-trade` |
| `exit_cluster_score > 25` (High) | `risk_mode in {Reduced, Defensive}` |
| `exit_cluster_score > 25` | `alignment_score <= 60` (CAS cap) |

- **Failure action:** Mark row invalid, fail run
- **Log:** `"Signal invariant violation: {condition} but {actual_output}"`
- **Cross-reference:** Enforces `skills/signals.md` tie-breaker rules

---

## 4) Alert Engine QA

### A1. No Alerts on Degraded/Stale Data
- **Required:** If `health_state in {Degraded, Stale}`, suppress behavioral alerts
- **Allowed:** System alerts only
- **Failure action:** Block alert emission, log suppression
- **Cross-reference:** Enforces `skills/alerts.md` suppression rules

### A2. Hysteresis Enforcement
Exit Cluster alert must follow hysteresis rules:

| Event | Condition |
|-------|-----------|
| Fire | Cross above 25% AND `is_active = false` |
| Reset | Drop below 20% → set `is_active = false` |
| Suppress | Between 20-25% OR `is_active = true` |

- **Failure action:** Fix state machine, add regression test
- **Cross-reference:** Enforces `skills/alerts.md` Exit Cluster hysteresis

### A3. Cooldown Enforcement
- **Required:** Enforce per alert type cooldown

| Alert Type | Cooldown |
|------------|----------|
| Regime Change | 30 minutes |
| Exit Cluster | 60 minutes |

- **Failure action:** Suppress alert, log with `suppressed = true`
- **Cross-reference:** Enforces `skills/alerts.md` cooldown rules

### A4. Daily Cap
- **Required:** Max 4 alerts per asset per rolling 24-hour window
- **Failure action:** Suppress alert, log with `suppressed = true`
- **Cross-reference:** Enforces `skills/alerts.md` daily limit

### A5. System Stale Alert (Fatal Priority)
- **Condition:** `now() - last_success_snapshot_ts > 10 minutes`
- **Required:**
  - Emit Critical system alert exactly once
  - Silence all behavioral alerts while active
  - Resume only after fresh data received
- **Failure action:** This is a critical bug if not working
- **Cross-reference:** Enforces `skills/alerts.md` System Stale rules

---

## 5) Dashboard QA (Decision Surface)

### D1. Decision Surface Mask (Fatal)
- **Required:** If `health_state == Stale`:
  - Unmount asset panels
  - Unmount behavioral alerts
  - Unmount signal charts
  - Render SYSTEM HALT message
  - Call `st.stop()`
- **Failure action:** Critical bug, block release
- **Cross-reference:** Enforces `skills/dashboard.md` Mask Rule

### D2. No Information Leakage (Fatal)
- **Required:** During Stale state, do NOT show:
  - Last-known playbooks
  - Last-known signals
  - Historical charts
  - Behavioral alerts
- **Rationale:** Stale bullish data could cause harmful trades
- **Failure action:** Critical bug, block release
- **Cross-reference:** Enforces `skills/dashboard.md` Mask Rule

### D3. Stale Mode UI Pattern
- **Required implementation:**
```python
def main():
    render_global_header()
    health_state = compute_health_state()
    
    if health_state == "STALE":
        render_system_halt()
        st.stop()  # CRITICAL: Nothing renders after this
    
    # Only reached if not Stale
    render_decision_surfaces()
```
- **Failure action:** If decision surfaces render during Stale, critical bug
- **Cross-reference:** Enforces `skills/dashboard.md` implementation requirement

### D4. No Price/Indicator Leakage
- **Required:** Dashboard must NOT contain:
  - Price candles
  - RSI, MACD, moving averages
  - Any price-based plots
  - Any external indicator overlays
- **Failure action:** Block release
- **Cross-reference:** Enforces `skills/dashboard.md` Golden Rule #3

---

## Logging and Audit Requirements

All QA failures must produce:

### Structured Log Entry
```python
log.error(
    "QA check failed",
    extra={
        "check_id": "S3",
        "stage": "snapshot_ingestion",
        "severity": "error",
        "details": {"coverage_pct": 72.5, "threshold": 80},
        "action_taken": "forced_stale",
        "timestamp": "2024-01-15T12:34:56Z"
    }
)
```

### Persisted Record
- Write to `ingest_health` for ingestion failures
- Write to `alerts` for system alerts
- Write to `snapshot_anomalies` for dirty detection
- Include human-readable message for debugging

### Audit Trail
- All QA failures must be queryable
- Retain for at least 7 days
- Include enough context to reproduce/debug

---

## Tests (Required)

### Universe Refresh Tests
- [ ] U1: Empty response triggers failure
- [ ] U2: <90% completeness triggers failure
- [ ] U3: Duplicate ranks detected and rejected
- [ ] U4: Empty wallet IDs detected and rejected
- [ ] U5: Churn warning count increments correctly
- [ ] U5: Three consecutive high-churn runs triggers failure

### Snapshot Ingestion Tests
- [ ] S1: Non-aligned timestamp rejected
- [ ] S2: Expected row count computed correctly
- [ ] S3: Coverage <80% forces Stale
- [ ] S3: Coverage 80-90% forces Degraded
- [ ] S4: Duplicate key prevented by constraint
- [ ] S5: Per-asset non-null rate computed correctly
- [ ] S5: Low non-null rate forces appropriate health state
- [ ] S6: Transient collapse pattern detected correctly
- [ ] S6: Dirty snapshots marked but retained
- [ ] S7: >10 minute gap triggers System Stale

### Signal Computation Tests
- [ ] G0: Signal lock blocks computation when Stale
- [ ] G0: Signal lock allows computation when Healthy
- [ ] G0: Mid-computation health transition aborts correctly
- [ ] G1: Non-aligned timestamp rejected
- [ ] G2: <4 snapshots forces skip
- [ ] G2: 4 snapshots allowed with Degraded flag
- [ ] G3: Low coverage forces No-trade/Defensive
- [ ] G4: Dirty snapshots excluded from aggregation
- [ ] G4: High dirty rate forces Degraded
- [ ] G5: Out-of-bounds values rejected
- [ ] G6: High dispersion invariant enforced
- [ ] G6: Exit cluster CAS cap enforced

### Alert Engine Tests
- [ ] A1: Behavioral alerts suppressed when Degraded
- [ ] A1: Behavioral alerts suppressed when Stale
- [ ] A1: System alerts allowed when Stale
- [ ] A2: Exit Cluster fires on cross above 25%
- [ ] A2: Exit Cluster does not re-fire until reset below 20%
- [ ] A2: Oscillation 20-25% produces no alerts
- [ ] A3: Cooldown prevents duplicate alerts
- [ ] A4: Daily cap enforced at 4 per asset
- [ ] A5: System Stale fires exactly once
- [ ] A5: System Stale silences behavioral alerts

### Dashboard Tests
- [ ] D1: Stale state unmounts all decision surfaces
- [ ] D1: Stale state renders SYSTEM HALT
- [ ] D1: st.stop() called in Stale state
- [ ] D2: No last-known data visible during Stale
- [ ] D3: Degraded state shows warning but renders surfaces
- [ ] D4: No price data anywhere in UI
- [ ] D4: No indicator overlays anywhere in UI

### Integration Tests
- [ ] End-to-end: API failure → Stale → SYSTEM HALT
- [ ] End-to-end: Recovery from Stale → signals resume
- [ ] End-to-end: Dirty detection → exclusion from signals
- [ ] End-to-end: High churn → warning → failure after 3x

---

## Definition of Done

- [ ] All QA checks implemented and enforced at each stage
- [ ] Signal Lock prevents computation during unhealthy states
- [ ] Mid-computation health transitions handled correctly
- [ ] Pipeline gates prevent "best guess" behavior
- [ ] Dirty snapshot patterns detected and excluded from signals
- [ ] Dirty snapshots retained for audit
- [ ] Stale data triggers System Halt and suppresses behavioral alerts
- [ ] Per-asset health tracking for non-null rates
- [ ] Universe churn warning state tracked across runs
- [ ] All structured logging in place
- [ ] All test cases pass
- [ ] Cross-references to other skills verified
