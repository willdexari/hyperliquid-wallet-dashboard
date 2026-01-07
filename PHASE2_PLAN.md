# Phase 2 Implementation Plan: Signal Computation

## Overview

Phase 2 transforms raw 60-second wallet snapshots into 5-minute regime signals that answer:
> "What type of trading behavior is statistically allowed right now?"

---

## Scope

### Inputs
- 60-second wallet snapshots from `wallet_snapshots` table
- Ingest health state from `ingest_health` table

### Outputs (Every 5 Minutes, Per Asset)
**Raw Signals:**
- Consensus Alignment Score (CAS): 0-100
- Alignment Trend: rising / flat / falling
- Dispersion Index: 0-100 (wallet disagreement)
- Exit Cluster Score: 0-100 (de-risking %)

**Derived Labels:**
- Allowed Playbook: Long-only / Short-only / No-trade
- Risk Mode: Normal / Reduced / Defensive
- Add Exposure: Yes / No
- Tighten Stops: Yes / No

**Metadata:**
- Wallet count, missing count, dirty count
- Computation duration
- Degradation flags

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Every 5 Minutes (Signal Cadence)                      │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│  1. Check Signal Lock (Ingest Health)                  │
│     - If stale/failed: skip computation, log           │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│  2. Aggregate Snapshots (5-Minute Window)              │
│     - Get snapshots from last 5 minutes                │
│     - Get snapshots from 5-10 minutes ago (for deltas) │
│     - Filter out dirty snapshots                       │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│  3. Classify Wallets (Per Asset)                       │
│     - Calculate Δszi = szi_current - szi_5m_ago        │
│     - Apply epsilon threshold                          │
│     - Classify: Adder (Long/Short) / Reducer / Flat    │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│  4. Compute Core Signals (Per Asset)                   │
│     - CAS (with reducer penalty if Exit Cluster high)  │
│     - Alignment Trend (3-period rolling avg)           │
│     - Dispersion Index (stdev of position changes)     │
│     - Exit Cluster Score (% reducers)                  │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│  5. Apply Playbook Decision Matrix                     │
│     - Check tie-breaker priorities                     │
│     - Determine allowed_playbook                       │
│     - Determine risk_mode                              │
│     - Calculate add_exposure, tighten_stops            │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│  6. Persist Signals                                     │
│     - Write to `signals` table                         │
│     - Write to `signal_contributors` table             │
│     - Update computation metadata                      │
└─────────────────────────────────────────────────────────┘
```

---

## Implementation Modules

### Module 1: `src/signals/aggregator.py`
**Purpose:** Aggregate 60s snapshots into 5-minute windows

**Functions:**
- `get_snapshot_timestamp()` → floored to 5-minute boundary
- `fetch_snapshots_for_window(signal_ts, asset)` → snapshots for current 5m
- `fetch_previous_snapshots(signal_ts, asset)` → snapshots from 5-10m ago
- `build_wallet_deltas(current, previous)` → Δszi per wallet

---

### Module 2: `src/signals/classifier.py`
**Purpose:** Classify wallets into behavioral states

**Functions:**
- `calculate_epsilon(wallet_history)` → ε for noise filtering
- `classify_wallet(szi_current, szi_previous, epsilon)` → Adder(Long)/Adder(Short)/Reducer/Flat

**States:**
- **Adder (Long):** Δszi > ε AND szi_current > 0
- **Adder (Short):** Δszi < −ε AND szi_current < 0
- **Reducer:** |szi_current| < |szi_previous| − ε
- **Flat:** All other cases

---

### Module 3: `src/signals/core.py`
**Purpose:** Compute the four core signals

**Functions:**
- `compute_cas(classifications, exit_cluster_score)` → CAS (0-100)
  - Handle N_total = 0
  - Apply reducer penalty if exit_cluster > 25
  - Graceful degradation on <90% valid data

- `compute_alignment_trend(current_cas, historical_cas)` → rising/flat/falling
  - 3-period rolling average
  - ±5 dead-zone

- `compute_dispersion_index(wallet_deltas)` → Di (0-100)
  - Per-wallet change ratios
  - Clamp to ±2.0
  - Normalize stdev to 0-100

- `compute_exit_cluster_score(classifications)` → EC (0-100)
  - % of wallets that are Reducers

---

### Module 4: `src/signals/playbook.py`
**Purpose:** Apply decision matrix and tie-breaker rules

**Functions:**
- `determine_playbook(cas, trend, dispersion, exit_cluster)` → (playbook, risk_mode)
  - Priority 1: Dispersion override (Di ≥ 60 → No-trade/Defensive)
  - Priority 2: Exit Cluster override (EC > 25 → No-trade/Defensive)
  - Priority 3: Trend override (Falling + CAS > 60 → No-trade/Reduced)
  - Priority 4: Apply playbook matrix

- `compute_derived_outputs(signals)` → (add_exposure, tighten_stops)
  - add_exposure: Rising + Low EC + Di ≠ High
  - tighten_stops: High EC OR Falling trend OR High Di

---

### Module 5: `src/signals/persistence.py`
**Purpose:** Write signals to database

**Functions:**
- `persist_signal(asset, signals, metadata)` → write to `signals` table
- `persist_contributors(asset, classifications)` → write to `signal_contributors` table

---

### Module 6: `src/signals/runner.py`
**Purpose:** Main signal computation loop

**Functions:**
- `check_signal_lock()` → verify ingest health
- `run_signal_computation()` → orchestrate all modules
- `main_loop()` → 5-minute cadence with alignment to boundaries

---

## Key Implementation Details

### Signal Lock
Before computing signals, check ingest health:
```python
health = get_latest_health()
if health.health_state == 'stale':
    log.warning("Skipping signal computation: data is stale")
    return
if health.snapshot_status == 'failed':
    log.warning("Skipping signal computation: last ingestion failed")
    return
```

### Epsilon Calculation
```python
def calculate_epsilon(wallet_id, asset):
    """Calculate epsilon for noise filtering."""
    epsilon_absolute = {
        'HYPE': 0.01,
        'BTC': 0.0001,
        'ETH': 0.001
    }[asset]

    # Get 24h history for this wallet/asset
    history = fetch_24h_history(wallet_id, asset)
    if len(history) == 0:
        return epsilon_absolute

    median_szi = median(abs(h.position_szi) for h in history)
    if median_szi == 0:
        return epsilon_absolute

    epsilon_relative = 0.02 * median_szi
    return max(epsilon_absolute, epsilon_relative)
```

### CAS with Reducer Penalty
```python
def compute_cas(n_add_long, n_add_short, n_total, exit_cluster_score):
    """Compute Consensus Alignment Score."""
    if n_total == 0:
        return 50.0  # Neutral when no data

    cas = 50 + ((n_add_long - n_add_short) / n_total * 50)

    # Apply reducer penalty
    if exit_cluster_score > 25:
        cas = min(cas, 60)

    return max(0, min(100, cas))
```

### Playbook Matrix Implementation
```python
def determine_playbook(cas, trend, dispersion, exit_cluster):
    """Apply decision matrix with strict priority order."""

    # Priority 1: Dispersion override
    if dispersion >= 60:
        return 'No-trade', 'Defensive'

    # Priority 2: Exit Cluster override
    if exit_cluster > 25:
        return 'No-trade', 'Defensive'

    # Priority 3: Trend override
    if trend == 'falling' and cas > 60:
        return 'No-trade', 'Reduced'

    # Priority 4: Apply matrix
    if cas > 75 and trend == 'rising' and dispersion < 40 and exit_cluster < 16:
        return 'Long-only', 'Normal'
    # ... (full matrix)

    # Default: conservative
    return 'No-trade', 'Reduced'
```

---

## Testing Strategy

### Unit Tests
- Epsilon calculation with various histories
- Wallet classification edge cases
- CAS computation (all N_total scenarios)
- Reducer penalty application
- Alignment trend with <3 periods
- Dispersion with <5 wallets
- Exit cluster percentage
- Playbook matrix coverage
- Tie-breaker priority order

### Integration Tests
- Full signal computation with mock snapshots
- Signal Lock respect (skip when stale)
- Graceful degradation (<90% coverage)
- 5-minute boundary alignment
- Database persistence
- Signal contributors table

### Data Validation
- Run on real ingested data
- Compare CAS range (should be 0-100)
- Verify playbook transitions make sense
- Check for signal spam (should be stable)
- Validate contributor percentages sum to 100

---

## Success Criteria (Phase 2)

- [ ] Signals compute every 5 minutes for HYPE, BTC, ETH
- [ ] Signal Lock prevents computation on stale/failed data
- [ ] Wallet classification matches spec exactly
- [ ] CAS computed with reducer penalty
- [ ] Alignment trend uses 3-period rolling average
- [ ] Dispersion Index normalized correctly
- [ ] Exit Cluster Score tracks reducers
- [ ] Playbook decision matrix fully implemented
- [ ] Tie-breaker rules enforced in priority order
- [ ] Signals persist to database
- [ ] Signal contributors persist to database
- [ ] All unit tests pass
- [ ] Integration test with real data passes
- [ ] No price indicators introduced
- [ ] Graceful degradation on missing data

---

## Next: Phase 3 (Alerts + Dashboard)

After Phase 2 is complete:
1. Implement alert evaluation (regime_change, exit_cluster, system_stale)
2. Build Streamlit dashboard
3. Add historical charts
4. Implement alert throttling and hysteresis

---

**Ready to start implementation!**
