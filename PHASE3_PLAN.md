# Phase 3 Implementation Plan

## Overview

Phase 3 adds the **alerting layer** and **dashboard UI** to complete the MVP.

**Components:**
- **Phase 3A**: Alert evaluation with hysteresis and throttling
- **Phase 3B**: Streamlit dashboard with single-screen layout

**Date Started:** 2026-01-06

---

## Phase 3A: Alerts

### Objectives
- Implement 3 alert types: Regime Change, Exit Cluster, System Stale
- Add hysteresis to prevent flicker
- Enforce cooldowns and daily limits
- Persist alert state for resumption across restarts
- Integrate with signal computation runner

### Alert Types

#### 1. Regime Change Alert
- **Trigger**: `allowed_playbook` changes value AND persists for 2 consecutive signal periods (10 minutes)
- **Hysteresis**: 2-period persistence requirement
- **Cooldown**: 30 minutes per asset
- **Severity**: Medium
- **Message**: `[{asset}] Regime Change: Playbook switched to {allowed_playbook}. Risk Mode: {risk_mode}.`

#### 2. Exit Cluster Alert
- **Trigger**: `exit_cluster_score` crosses above 25%
- **Hysteresis**: Trigger >25%, Reset <20% (5% buffer)
- **Cooldown**: 60 minutes per asset
- **Severity**: High
- **Message**: `[{asset}] Smart Money De-risking: Exit Cluster elevated ({exit_cluster_score:.1f}%). Stop adding exposure. Tighten stops.`

#### 3. System Stale Alert
- **Trigger**: `now() - ingest_health.last_success_ts > 10 minutes`
- **Hysteresis**: None (time-based)
- **Cooldown**: None (single-fire until resolved)
- **Severity**: Critical
- **Asset**: SYSTEM
- **Behavior**: Suppresses all behavioral alerts while active
- **Message**: `[SYSTEM] Data Stale: Ingestion has not succeeded for {minutes_stale} minutes. All behavioral alerts suppressed. Do not trade until resolved.`

### Throttling Rules

**Daily Limit:**
- Maximum 4 alerts per asset per rolling 24-hour window
- When limit reached: suppress new alerts, log with `suppressed = true`
- Window is rolling from first alert timestamp

**Cooldown Enforcement:**
- Per (asset, alert_type) pair
- Alerts during cooldown are suppressed, not queued
- Suppressed alerts logged with `suppressed = true`

### Database Tables

Already exist in schema (from db/schema.sql):

```sql
CREATE TABLE alerts (
    id              SERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL,
    asset           TEXT NOT NULL,
    alert_type      TEXT NOT NULL,
    severity        TEXT NOT NULL,
    message         TEXT NOT NULL,
    signal_snapshot JSONB,
    cooldown_until  TIMESTAMPTZ NOT NULL,
    suppressed      BOOLEAN DEFAULT FALSE
);

CREATE TABLE alert_state (
    asset           TEXT NOT NULL,
    alert_type      TEXT NOT NULL,
    is_active       BOOLEAN DEFAULT FALSE,
    last_triggered  TIMESTAMPTZ,
    cooldown_until  TIMESTAMPTZ,
    daily_count     INTEGER DEFAULT 0,
    daily_window_start TIMESTAMPTZ,
    PRIMARY KEY (asset, alert_type)
);
```

### Module Structure

```
src/alerts/
├── __init__.py
├── evaluator.py          # Main alert evaluation logic
├── regime_change.py      # Regime Change alert with 2-period persistence
├── exit_cluster.py       # Exit Cluster alert with hysteresis
├── system_stale.py       # System Stale alert
├── throttling.py         # Cooldown and daily limit enforcement
├── persistence.py        # Alert and alert_state persistence
└── runner.py             # Integration with signal computation
```

### Implementation Steps

1. **Create throttling module** (`src/alerts/throttling.py`)
   - Check cooldown per (asset, alert_type)
   - Check daily limit per asset
   - Return suppression decision

2. **Create persistence module** (`src/alerts/persistence.py`)
   - `persist_alert()` - Write to alerts table with signal snapshot
   - `persist_alert_state()` - Update alert_state table
   - `get_alert_state()` - Load current state for hysteresis

3. **Create regime_change module** (`src/alerts/regime_change.py`)
   - Track `allowed_playbook` changes
   - Require 2-period persistence before firing
   - Use alert_state to track pending regime change

4. **Create exit_cluster module** (`src/alerts/exit_cluster.py`)
   - Hysteresis: trigger >25%, reset <20%
   - Use `is_active` flag in alert_state
   - Fire once, suppress until reset

5. **Create system_stale module** (`src/alerts/system_stale.py`)
   - Check `now() - last_success_ts > 10 minutes`
   - Single-fire until resolved
   - Set global suppression flag for behavioral alerts

6. **Create evaluator module** (`src/alerts/evaluator.py`)
   - Orchestrate all alert checks
   - Check System Stale first (suppresses behavioral alerts)
   - Apply throttling before firing
   - Persist alerts and state

7. **Integrate with signal runner** (`src/signals/runner.py`)
   - Call alert evaluator after signal persistence
   - Pass signal snapshot to alert layer
   - Log alert decisions

### Edge Cases

- **Cold start**: No previous signal to compare → no Regime Change alert on first run
- **N_total = 0**: Conservative signals → may trigger System Stale if prolonged
- **Alert state persistence**: Must survive process restart
- **Cooldown overlap**: Different alert types can fire within each other's cooldowns
- **Daily limit reset**: Use rolling window, not calendar day

---

## Phase 3B: Dashboard

### Objectives
- Build single-screen Streamlit dashboard
- Display latest signals per asset
- Show 6h/24h signal history charts
- Display recent alerts (last 24h)
- Health status with STALE/DEGRADED/HEALTHY states
- Auto-refresh every 30 seconds

### Layout Structure

```
┌─────────────────────────────────────────────────────────────────┐
│ [A] GLOBAL HEADER - Health Status / Last Update / Coverage      │
├─────────────────────┬─────────────────────┬─────────────────────┤
│ [B] HYPE            │ [B] BTC             │ [B] ETH             │
│ Playbook: Long-only │ Playbook: No-trade  │ Playbook: Short-only│
│ Risk: Normal        │ Risk: Defensive     │ Risk: Reduced       │
│ CAS: 78 ↑           │ CAS: 52 →           │ CAS: 22 ↓           │
│ Dispersion: Low     │ Dispersion: High    │ Dispersion: Low     │
│ Exit Cluster: Low   │ Exit Cluster: Med   │ Exit Cluster: Low   │
├─────────────────────┴─────────────────────┴─────────────────────┤
│ [C] ALERTS - Recent alerts (max 5 from last 24h)                │
├─────────────────────────────────────────────────────────────────┤
│ [D] DETAIL SECTION - Selected Asset (default: HYPE)             │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ CAS Time Series (6h)                                        │ │
│ ├─────────────────────────────────────────────────────────────┤ │
│ │ Dispersion Time Series (6h)                                 │ │
│ ├─────────────────────────────────────────────────────────────┤ │
│ │ Exit Cluster Time Series (6h)                               │ │
│ └─────────────────────────────────────────────────────────────┘ │
│ [Collapsed: Contributors Summary]                               │
└─────────────────────────────────────────────────────────────────┘
```

### Module Structure

```
src/ui/
├── __init__.py
├── app.py                # Main Streamlit entry point
├── data_loader.py        # Database queries for UI
├── health.py             # Health state computation
├── components/
│   ├── __init__.py
│   ├── header.py         # Global header
│   ├── asset_panel.py    # Asset summary panels
│   ├── alerts_panel.py   # Recent alerts
│   ├── detail_section.py # Charts and contributors
│   └── system_halt.py    # STALE state mask
└── charts.py             # Chart creation utilities
```

### Health State Logic

```python
def compute_health_state() -> str:
    snapshot_age = now() - last_successful_snapshot_ts
    coverage_pct = get_latest_coverage()
    system_stale_active = check_system_stale_alert()

    if system_stale_active:
        return "STALE"
    if snapshot_age > timedelta(minutes=10):
        return "STALE"
    if coverage_pct < 80:
        return "STALE"
    if snapshot_age > timedelta(minutes=2) or coverage_pct < 90:
        return "DEGRADED"
    return "HEALTHY"
```

### Health State Thresholds

| Condition | State |
|-----------|-------|
| snapshot ≤ 2m AND coverage ≥ 90% | HEALTHY |
| snapshot 2–10m OR coverage 80–90% | DEGRADED |
| snapshot > 10m OR coverage < 80% OR System Stale alert | STALE |

### Decision Surface Mask (CRITICAL)

When `health_state == "STALE"`:
1. **Do NOT render** any Decision Surface components
2. **Replace** main content with SYSTEM HALT view
3. **Call `st.stop()`** to prevent further rendering

**Allowed in Stale State:**
- Global header (health status)
- Last snapshot timestamp
- Gap duration
- Troubleshooting hints

**Forbidden in Stale State:**
- ❌ Last-known playbooks
- ❌ Last-known signals
- ❌ Historical charts
- ❌ Behavioral alerts
- ❌ Contributors summary

### Auto-Refresh

- Refresh interval: 30 seconds
- Use `streamlit-autorefresh` or manual timer
- Preserve user selections: `selected_asset`, `time_range`
- No visible flicker on refresh

### Implementation Steps

1. **Create data_loader module** (`src/ui/data_loader.py`)
   - Query functions for latest signals
   - Query functions for signal history
   - Query functions for alerts
   - Query functions for health state
   - Query functions for contributors

2. **Create health module** (`src/ui/health.py`)
   - `compute_health_state()` function
   - Health state thresholds

3. **Create chart utilities** (`src/ui/charts.py`)
   - `create_signal_chart()` - Generic time series chart with thresholds
   - Fixed Y-axis 0-100
   - Threshold lines

4. **Create header component** (`src/ui/components/header.py`)
   - Health status indicator
   - Last snapshot timestamp
   - Last signal timestamp
   - Wallet coverage

5. **Create asset_panel component** (`src/ui/components/asset_panel.py`)
   - Playbook with colored background
   - Risk mode
   - CAS with trend arrow
   - Dispersion state
   - Exit cluster state

6. **Create alerts_panel component** (`src/ui/components/alerts_panel.py`)
   - Show max 5 alerts from last 24h
   - Pin System Stale to top
   - Severity icons

7. **Create detail_section component** (`src/ui/components/detail_section.py`)
   - Asset selection (default: HYPE)
   - Time range toggle (6h/24h)
   - 3 signal charts
   - Contributors summary (collapsed)

8. **Create system_halt component** (`src/ui/components/system_halt.py`)
   - SYSTEM HALT view
   - Red border, large text
   - Last snapshot info
   - Troubleshooting steps
   - Call `st.stop()`

9. **Create main app** (`src/ui/app.py`)
   - Initialize session state
   - Auto-refresh logic
   - Render header
   - Check health state
   - If STALE: render SYSTEM HALT and stop
   - If DEGRADED: show warning banner
   - Render asset panels, alerts, detail section

### Dependencies

```
streamlit==1.31.0
plotly==5.18.0
psycopg2-binary==2.9.9
streamlit-autorefresh==1.0.1  # Optional
```

### Edge Cases

- **No signals in DB**: Show "No data available" message
- **No alerts in 24h**: Show "No recent alerts"
- **Empty signal history**: Show empty chart with message
- **Auto-refresh during user interaction**: Preserve state

---

## Integration Points

### Signal Runner → Alert Evaluator

After signal persistence in `src/signals/runner.py`:

```python
from src.alerts.evaluator import evaluate_alerts

async def compute_signal_for_asset(self, signal_ts, asset):
    # ... existing signal computation ...

    # Persist signals
    persist_signal(signal_ts, asset, full_signals, counts, missing_count, duration_ms)
    persist_contributors(signal_ts, asset, counts, percentages)

    # NEW: Evaluate alerts
    alerts_fired = evaluate_alerts(signal_ts, asset, full_signals)

    return {
        'asset': asset,
        'signals': full_signals,
        'alerts_fired': alerts_fired,
        # ...
    }
```

### Dashboard → Database (Read-Only)

Dashboard queries:
- `signals` table (latest + history)
- `signal_contributors` table (latest)
- `alerts` table (last 24h)
- `ingest_health` table (latest)
- `alert_state` table (for System Stale check)

**No computation in UI.** All derived values come from backend tables.

---

## Testing Strategy

### Phase 3A (Alerts) Tests

1. **Regime Change Tests**
   - [ ] Alert fires on playbook change after 2 consecutive periods
   - [ ] Alert does NOT fire on single-period change
   - [ ] Cooldown (30m) enforced
   - [ ] Suppressed during System Stale

2. **Exit Cluster Tests**
   - [ ] Alert fires once when crossing above 25%
   - [ ] Alert does NOT re-fire while still above 20%
   - [ ] Alert resets when dropping below 20%
   - [ ] Oscillation between 20-25% produces zero alerts
   - [ ] Cooldown (60m) enforced

3. **System Stale Tests**
   - [ ] Fires when last_success_ts > 10 minutes old
   - [ ] Only fires once until resolved
   - [ ] Suppresses all behavioral alerts while active
   - [ ] Clears when fresh data arrives

4. **Throttling Tests**
   - [ ] Daily limit (4 per asset per 24h) enforced
   - [ ] Rolling window correctly expires old alerts
   - [ ] Suppressed alerts logged with `suppressed = true`
   - [ ] Cooldown overlap: different alert types can fire within each other's cooldowns

5. **State Persistence Tests**
   - [ ] Alert state survives process restart
   - [ ] Hysteresis state (`is_active`) persists correctly
   - [ ] Cooldown state persists correctly

### Phase 3B (Dashboard) Tests

1. **Health State Tests**
   - [ ] STALE state triggers full Decision Surface mask
   - [ ] STALE state shows SYSTEM HALT view
   - [ ] DEGRADED state shows yellow warning banner
   - [ ] HEALTHY state shows no warnings

2. **Asset Panel Tests**
   - [ ] All three assets display side-by-side
   - [ ] Playbook colors are correct (green/red/gray)
   - [ ] Trend arrows display correctly (↑ → ↓)
   - [ ] CAS value displays as integer

3. **Alerts Panel Tests**
   - [ ] Shows max 5 alerts from last 24h
   - [ ] System Stale alert pinned to top
   - [ ] "No recent alerts" shown when empty

4. **Detail Section Tests**
   - [ ] Default asset is HYPE
   - [ ] Asset selection persists across refresh
   - [ ] Charts have fixed Y-axis (0-100)
   - [ ] Threshold lines visible on charts

5. **Auto-Refresh Tests**
   - [ ] Dashboard refreshes every 30 seconds
   - [ ] Selected asset not reset on refresh
   - [ ] Time range not reset on refresh

---

## Implementation Order

### Day 1: Alerts Foundation
1. ✅ Create implementation plan (this file)
2. Create throttling module
3. Create persistence module
4. Create basic evaluator skeleton

### Day 1: Alert Types
5. Implement Exit Cluster alert (simplest - pure hysteresis)
6. Implement System Stale alert
7. Implement Regime Change alert (most complex - 2-period persistence)

### Day 1: Alert Integration
8. Integrate with signal runner
9. Test alert evaluation with `--once` mode
10. Verify alert persistence to database

### Day 2: Dashboard Foundation
11. Create data_loader module
12. Create health module
13. Create chart utilities
14. Set up basic Streamlit app structure

### Day 2: Dashboard Components
15. Implement header component
16. Implement asset_panel component
17. Implement alerts_panel component
18. Implement detail_section component
19. Implement system_halt component

### Day 2: Dashboard Integration
20. Wire up main app logic
21. Add auto-refresh
22. Test with real signal data
23. Verify STALE/DEGRADED/HEALTHY states

---

## Success Criteria

### Phase 3A: Alerts
- [ ] All 3 alert types implemented and tested
- [ ] Hysteresis prevents flicker
- [ ] Cooldowns enforced correctly
- [ ] Daily limit (4 per asset per 24h) enforced
- [ ] System Stale suppresses behavioral alerts
- [ ] Alert state persists across restarts
- [ ] Alerts integrated with signal runner
- [ ] Alerts fire correctly in test runs

### Phase 3B: Dashboard
- [ ] Single-screen layout implemented
- [ ] Health status dominates when STALE/DEGRADED
- [ ] Asset panels show playbook as primary element
- [ ] Recent alerts display (max 5)
- [ ] Signal charts with threshold lines
- [ ] Auto-refresh every 30 seconds
- [ ] State persistence across refreshes
- [ ] No price data anywhere
- [ ] Initial render < 2 seconds

### Overall MVP Completion
- [ ] Full data pipeline: Ingestion (60s) → Signals (5m) → Alerts → Dashboard
- [ ] System runs continuously without errors
- [ ] Dashboard provides clear regime gating
- [ ] Alerts are rare and actionable
- [ ] Health monitoring prevents stale data usage
- [ ] All documentation complete

---

## Next Steps

After creating this plan:
1. Start with Phase 3A (Alerts)
2. Build modules in order listed above
3. Test each alert type individually
4. Integrate with signal runner
5. Move to Phase 3B (Dashboard)
6. Wire up components
7. Test full system end-to-end
8. Create PHASE3_COMPLETE.md

**Let's begin!**
