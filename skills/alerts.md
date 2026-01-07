# skills/alerts.md

## Purpose
Define the **alerting layer** for the Hyperliquid Wallet Dashboard.

Alerts exist to:
- Surface **regime changes** you might miss
- Warn of **early de-risking** by top wallets
- Protect you from acting on **stale or invalid data**

Alerts do **not**:
- Generate trade entries
- Predict price direction
- Fire on every signal update

Alerts are **rare, high-signal, behavior-driven, and safety-first**.

---

## Constraint (Critical)
Alerts must be:
- **Derived only from signals**, never raw data
- **State-change based**, not level-based
- **Heavily throttled with hysteresis**

If an alert fires often, it is broken.

---

## Source of Truth
- For business intent and constraints, follow `docs/`.
- For signal definitions, follow `skills/signals.md`.
- This skill defines alert logic and acceptance criteria.

---

## Inputs
From `signals` table (per asset, 5m cadence):
- `alignment_score`
- `alignment_trend`
- `dispersion_index`
- `exit_cluster_score`
- `allowed_playbook`
- `risk_mode`

From system health:
- `ingest_health.last_success_ts`
- `ingest_health.status` (success / partial / failed)

No other inputs are allowed.

---

## Outputs

### Alert Events
Written to `alerts` table:

```sql
CREATE TABLE alerts (
    id              SERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL,
    asset           TEXT NOT NULL,          -- 'HYPE', 'BTC', 'ETH', or 'SYSTEM'
    alert_type      TEXT NOT NULL,          -- 'regime_change', 'exit_cluster', 'system_stale'
    severity        TEXT NOT NULL,          -- 'medium', 'high', 'critical'
    message         TEXT NOT NULL,
    signal_snapshot JSONB,                  -- signals at fire time (for debugging)
    cooldown_until  TIMESTAMPTZ NOT NULL,
    suppressed      BOOLEAN DEFAULT FALSE   -- true if fired during cooldown/limit
);
```

### Alert State (for hysteresis)
```sql
CREATE TABLE alert_state (
    asset           TEXT NOT NULL,
    alert_type      TEXT NOT NULL,
    is_active       BOOLEAN DEFAULT FALSE,  -- condition currently triggered
    last_triggered  TIMESTAMPTZ,
    cooldown_until  TIMESTAMPTZ,
    daily_count     INTEGER DEFAULT 0,
    daily_window_start TIMESTAMPTZ,
    PRIMARY KEY (asset, alert_type)
);
```

### Optional Delivery
- Console log
- Local system notification
- Webhook (post-MVP)

---

## Golden Rules (Do Not Break)
1. **State transitions only** — no repeated alerts for same state
2. **Hysteresis is mandatory** — for all threshold-based alerts
3. **Persistence hysteresis** — state changes must persist before alerting
4. **Maximum 4 alerts per asset per rolling 24h window**
5. **Cooldowns are mandatory and enforced**
6. **No price conditions**
7. **Alerts must map to a clear action**
8. **System alerts override behavioral alerts**

---

## Alert Types (MVP)

Only three alert types exist. Do not add more without updating this document.

---

### 1. Regime Change Alert

**Purpose**  
Notify when the **allowed trading playbook changes**.

**Trigger**
Fire when:
- `allowed_playbook` changes value (Long-only ↔ Short-only ↔ No-trade)
- AND the new value has **persisted for 2 consecutive signal periods (10 minutes)**

The persistence requirement prevents alerting on single-period noise.

**Implementation:**
```python
# Track pending regime changes
if playbook_changed:
    if pending_regime_change == new_playbook and periods_at_new >= 2:
        fire_alert()
        pending_regime_change = None
    else:
        pending_regime_change = new_playbook
        periods_at_new = 1
else:
    if pending_regime_change == current_playbook:
        periods_at_new += 1
    else:
        pending_regime_change = None
```

**Severity**
| Transition | Severity |
|------------|----------|
| Long-only ↔ Short-only | Medium |
| Long-only ↔ No-trade | Medium |
| Short-only ↔ No-trade | Medium |

**Cooldown**
- 30 minutes per asset

**Message Template**
```
[{asset}] Regime Change:
Playbook switched to {allowed_playbook}.
Risk Mode: {risk_mode}.
```

**Expected Action**
- Re-evaluate directional bias
- Stop forcing setups inconsistent with new playbook
- Review open positions against new regime

---

### 2. Exit Cluster Alert (Early Distribution Warning)

**Purpose**  
Warn when **top wallets begin coordinated de-risking**.

**Trigger (with Hysteresis)**

| Event | Condition | Action |
|-------|-----------|--------|
| Fire | `exit_cluster_score` crosses **above 25%** | Alert fires, `is_active = true` |
| Reset | `exit_cluster_score` drops **below 20%** | `is_active = false`, can fire again |
| Suppress | Score oscillates between 20-25% | No alert (hysteresis buffer) |

```python
# Hysteresis logic
if not is_active and exit_cluster_score > 25:
    fire_alert()
    is_active = True
elif is_active and exit_cluster_score < 20:
    is_active = False
# else: no action (in buffer zone or already active)
```

**Cross-reference:** When this alert fires, CAS is already capped at 60 per `skills/signals.md`. The alert reinforces what the signal layer is already doing.

**Severity**
- **High**

**Cooldown**
- 60 minutes per asset

**Message Template**
```
[{asset}] Smart Money De-risking:
Exit Cluster elevated ({exit_cluster_score:.1f}%).
Stop adding exposure. Tighten stops.
```

**Expected Action**
- Stop adding to positions
- Tighten stops on existing positions
- Prepare for potential distribution / reversal

---

### 3. System Stale Alert (Dead Man's Switch)

**Purpose**  
Prevent acting on **stale or invalid data**.

**Trigger**
Fire when:
- `now() - ingest_health.last_success_ts > 10 minutes`

**Clarification:** This alert triggers on **time-based staleness only**. Partial or degraded ingestion (>5% missing) is surfaced via Risk Mode (Reduced/Defensive) in the signals layer, not via alerts.

**Severity**
- **Critical**

**Behavior**
When active:
1. Emit System Alert
2. **Suppress all behavioral alerts** (Regime Change, Exit Cluster)
3. Force dashboard into Stale Mode
4. Continue checking every signal period

When resolved:
1. Clear stale state
2. Resume behavioral alerts
3. Log recovery event

**Cooldown**
- None (always fires immediately when condition met)
- But only fires once until resolved and re-triggered

**Message Template**
```
[SYSTEM] Data Stale:
Ingestion has not succeeded for {minutes_stale} minutes.
All behavioral alerts suppressed.
Do not trade until resolved.
```

**Expected Action**
- Do not trade
- Investigate ingestion / API health
- Resume only once data is fresh

---

## Explicit Non-Alerts (Do NOT Implement)

Do not alert on:
- Raw CAS values or small CAS changes
- Dispersion changes alone
- Alignment trend changes alone (captured in Regime Change via playbook)
- Price moves or volatility
- Individual wallet behavior
- Partial ingestion (handled by Risk Mode)

If an alert cannot be tied to a **decision change**, it does not belong here.

---

## Alert Throttling & Guardrails

### Hysteresis (Flicker Guard)
All threshold-based alerts must implement hysteresis:

| Alert Type | Trigger Threshold | Reset Threshold | Buffer |
|------------|-------------------|-----------------|--------|
| Exit Cluster | >25% | <20% | 5% |
| Regime Change | 2 periods at new state | state changes | 10 min |

**Rule:** Never re-fire alerts on minor oscillations around thresholds.

### Daily Limit
- Maximum **4 alerts per asset per rolling 24-hour window**
- Window starts from the timestamp of the first alert of the current window
- When limit reached: suppress new alerts, log suppression, set `suppressed = true`
- Window reset: when oldest alert in window falls outside 24h

```python
def check_daily_limit(asset: str, alert_type: str) -> bool:
    """Returns True if alert is allowed, False if suppressed."""
    cutoff = now() - timedelta(hours=24)
    recent_count = count_alerts(asset, since=cutoff, suppressed=False)
    return recent_count < 4
```

### Cooldown Enforcement
Each alert type enforces its own cooldown per asset:

| Alert Type | Cooldown |
|------------|----------|
| Regime Change | 30 minutes |
| Exit Cluster | 60 minutes |
| System Stale | None (but single-fire until resolved) |

**Rules:**
- Alerts during cooldown are **suppressed, not queued**
- Suppressed alerts are logged with `suppressed = true`
- Cooldown is per (asset, alert_type) pair

### Deduplication
If the same `alert_type` would fire with semantically identical conditions:
- Suppress the duplicate
- Only fire again after:
  - State reset (hysteresis condition cleared)
  - Cooldown expiry
  - New trigger event

---

## Severity Mapping & UI Actions

| Alert Type | Severity | UI Action |
|------------|----------|-----------|
| Regime Change | Medium | Yellow border on asset panel; playbook label updates; brief highlight |
| Exit Cluster | High | Red accent on asset header; "DE-RISKING" badge visible; persist until reset |
| System Stale | Critical | Full dashboard overlay with "DATA STALE" watermark; all panels grayed |

### Severity Hierarchy
```
Critical > High > Medium
```

Critical alerts (System Stale) take visual precedence over all others.

---

## Failure & Degradation Handling

### Suppression Conditions
Suppress all behavioral alerts (Regime Change, Exit Cluster) when:
- System Stale alert is active
- Missing wallet data >10% (Risk Mode forced to Defensive)
- Signal computation failed

### Suppression Behavior
- Behavioral alerts are **not evaluated** during suppression
- Only System alerts may fire
- Log: `"Behavioral alerts suppressed: {reason}"`

### Recovery
Resume behavioral alerting only after:
- System Stale resolved (fresh data received)
- Data quality restored (>90% wallets reporting)
- At least one successful signal computation

---

## Alert Persistence Contract

### On Alert Fire
```python
def persist_alert(
    asset: str,
    alert_type: str,
    severity: str,
    message: str,
    signals: dict,
    cooldown_minutes: int,
    suppressed: bool = False
):
    insert_into_alerts(
        timestamp=now(),
        asset=asset,
        alert_type=alert_type,
        severity=severity,
        message=message,
        signal_snapshot=json.dumps(signals),
        cooldown_until=now() + timedelta(minutes=cooldown_minutes),
        suppressed=suppressed
    )
    
    update_alert_state(
        asset=asset,
        alert_type=alert_type,
        is_active=True,
        last_triggered=now(),
        cooldown_until=now() + timedelta(minutes=cooldown_minutes)
    )
```

### Signal Snapshot Contents
```json
{
    "alignment_score": 72.5,
    "alignment_trend": "falling",
    "dispersion_index": 45.2,
    "exit_cluster_score": 28.3,
    "allowed_playbook": "No-trade",
    "risk_mode": "Defensive",
    "wallet_count": 200,
    "missing_count": 5
}
```

---

## Tests (Required)

### Regime Change Tests
- Alert fires on playbook change after 2 consecutive periods
- Alert does NOT fire on single-period change
- Cooldown (30m) enforced
- Suppressed during System Stale

### Exit Cluster Tests
- Alert fires once when crossing above 25%
- Alert does NOT re-fire while still above 20%
- Alert resets when dropping below 20%
- Alert can fire again after reset + crossing 25%
- Cooldown (60m) enforced
- Oscillation between 20-25% produces zero alerts

### System Stale Tests
- Fires when last_success_ts > 10 minutes old
- Only fires once until resolved
- Suppresses all behavioral alerts while active
- Clears when fresh data arrives
- Dashboard enters Stale Mode

### Throttling Tests
- Daily limit (4 per asset per 24h) enforced
- Rolling window correctly expires old alerts
- Suppressed alerts logged with `suppressed = true`
- Cooldown overlap: two different alert types can fire within each other's cooldowns
- Same alert type respects its own cooldown

### State Persistence Tests
- Alert state survives process restart
- Hysteresis state (`is_active`) persists correctly
- Cooldown state persists correctly
- Daily count persists correctly

### Integration Tests
- Regime flip produces exactly one alert (after persistence period)
- Exit cluster spike produces exactly one alert
- Rapid signal changes do not produce alert spam
- Ingest outage → System Stale → behavioral alerts suppressed
- Ingest recovery → behavioral alerts resume

---

## Definition of Done

- [ ] Only three alert types exist (Regime Change, Exit Cluster, System Stale)
- [ ] Regime Change requires 2-period persistence before firing
- [ ] Exit Cluster implements hysteresis (trigger >25%, reset <20%)
- [ ] System Stale fires on >10 minute data gap
- [ ] System Stale suppresses all behavioral alerts
- [ ] Cooldowns enforced per (asset, alert_type)
- [ ] Daily limit (4 per asset per rolling 24h) enforced
- [ ] Suppressed alerts logged with `suppressed = true`
- [ ] Alert state table tracks hysteresis and cooldowns
- [ ] Signal snapshot persisted with each alert
- [ ] All tests pass
- [ ] Alerts are rare, trusted, and actionable

---

## Design Philosophy

Alerts are a **seatbelt**, not a steering wheel.

They exist to:
- Catch regime shifts you might miss while focused on charts
- Warn you before distribution traps you
- Protect you from acting on bad data

They do NOT exist to:
- Tell you when to enter trades
- Predict price direction
- Fire constantly to feel "active"

**If you ever think: "I should add another alert..."**

Fix the **signals** or **ingestion health** first. The alert layer is the last resort, not the first solution.
