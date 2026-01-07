# skills/signals.md

## Purpose
Define the **signal computation and state logic** for the Hyperliquid Wallet Dashboard.

Signals transform raw wallet snapshots into **actionable regime information**.  
They do **not** generate entries or predict price.

This layer answers one question only:

> "What type of trading behavior is statistically allowed right now?"

---

## Constraint (Critical)
Formulas in this document are **conceptual references only**.

**Implementations MUST follow the state-based definitions, thresholds, and tie-breaker rules exactly.**  
Do **not** optimize, refactor, or alter logic without updating this document.

This file defines **state machines and decision rules**, not mathematical optimization targets.

---

## Source of Truth
- For business intent and constraints, follow `docs/`.
- This skill defines computation logic and acceptance criteria for signal changes.

---

## Scope (Hard Constraints)
- Assets: **HYPE, BTC, ETH only**
- Input cadence: **60s wallet snapshots**
- Output cadence: **5-minute signals**
- Signals are computed **per asset**
- **Behavior-only** signals (no price indicators)

---

## Inputs
From ingestion (via aggregation):
- `wallet_id`
- `asset`
- `timestamp`
- `position_szi` (signed size in units — canonical)

Optional fields (non-canonical, for debugging):
- leverage
- margin
- entry price
- USD notional

---

## Outputs
Every 5 minutes, per asset:

### Raw Signals
| Signal | Type | Range |
|--------|------|-------|
| `alignment_score` | float | 0–100 |
| `alignment_trend` | enum | rising / flat / falling |
| `dispersion_index` | float | 0–100 |
| `exit_cluster_score` | float | 0–100 |

### Derived Labels
| Label | Type | Values |
|-------|------|--------|
| `allowed_playbook` | enum | Long-only / Short-only / No-trade |
| `risk_mode` | enum | Normal / Reduced / Defensive |
| `add_exposure` | bool | Yes / No |
| `tighten_stops` | bool | Yes / No |

---

## Golden Rules (Do Not Break)
1. **Signals describe regimes, not entries**
2. **No price-based indicators** (RSI, MACD, MAs)
3. **SZI is canonical** (signed unit size, not USD)
4. **Reducers must be handled explicitly** (feed Exit Cluster, not CAS)
5. **Dispersion and exits override consensus** (tie-breaker rules)
6. **Signals must degrade safely with missing data**
7. **All outputs must be bounded and deterministic**

---

## Definitions

### Epsilon (ε) — Minimum Meaningful Change

Epsilon filters noise from position changes.

**Calculation:**
```
ε = max(ε_absolute, ε_relative)

where:
  ε_absolute = 0.01 units (default, asset-agnostic)
  ε_relative = 0.02 × median(|szi|) over wallet's last 24h
```

**Asset-specific overrides (optional):**
| Asset | ε_absolute | Notes |
|-------|-----------|-------|
| HYPE  | 0.01      | Default |
| BTC   | 0.0001    | Smaller unit size |
| ETH   | 0.001     | Smaller unit size |

**Edge cases:**
- If wallet has no 24h history: use `ε_absolute` only
- If `median(|szi|) = 0`: use `ε_absolute` only

---

## 1. Wallet State Classification (Pre-Computation)

Before computing any signals, classify **every wallet** into exactly one state based on 5-minute Δszi.

```
Δszi = szi_current - szi_5m_ago
```

| State | Definition | Role in Signals |
|-------|------------|-----------------|
| **Adder (Long)** | Δszi > ε AND szi_current > 0 | Increases Bullish CAS |
| **Adder (Short)** | Δszi < −ε AND szi_current < 0 | Increases Bearish CAS |
| **Reducer** | \|szi_current\| < \|szi_5m_ago\| − ε | Feeds Exit Cluster only |
| **Flat** | All other cases | Neutral (no contribution) |

**Critical rules:**
- Reducers **never** contribute to directional CAS
- Each wallet is classified into **exactly one** state
- Classification happens **per asset**

**Edge cases:**
- If `szi_5m_ago` is missing: classify as Flat
- If `szi_current` is NULL: exclude wallet from computation, count as missing

---

## 2. Canonical Signal Definitions

### A. Consensus Alignment Score (CAS)

**Purpose:** Measures net directional intensity of wallets actively adding exposure.

**Formula:**
```
CAS = 50 + ((N_add_long - N_add_short) / N_total × 50)
```

**Bounds:** `0 ≤ CAS ≤ 100`

| CAS Value | Interpretation |
|-----------|----------------|
| 75–100 | Strong bullish consensus |
| 60–75 | Moderate bullish lean |
| 40–60 | Neutral / mixed |
| 25–40 | Moderate bearish lean |
| 0–25 | Strong bearish consensus |

#### Edge Cases
| Condition | CAS Value | Risk Mode |
|-----------|-----------|-----------|
| N_total = 0 | 50 | Defensive |
| All wallets Flat | 50 | Reduced |
| N_add_long = N_add_short | 50 | (use other signals) |

#### Reducer Penalty (Critical)
When large-scale de-risking is occurring, CAS becomes unreliable.

**Rule:** If `exit_cluster_score > 25`, cap CAS at **60**.

```python
if exit_cluster_score > 25:
    cas = min(cas, 60)
```

This prevents false high-consensus readings during distribution phases.

#### Graceful Degradation
If **<90% of wallets** return valid data for this asset:
- CAS defaults to **50**
- Risk Mode must be at least **Reduced**
- Log degradation event

---

### B. Alignment Trend

**Purpose:** Detects whether consensus is strengthening or weakening.

**Method:** Compare current CAS to rolling average, with dead-zone to prevent noise.

**Rolling Average:**
```
CAS_avg_15m = mean(CAS at t-5m, CAS at t-10m, CAS at t-15m)
```
This uses the **last 3 signal periods**, not raw snapshots.

**State Determination:**
| State | Condition |
|-------|-----------|
| **Rising** | CAS_current > CAS_avg_15m + 5 |
| **Falling** | CAS_current < CAS_avg_15m − 5 |
| **Flat** | Otherwise (within ±5 dead-zone) |

**Edge cases:**
- If fewer than 3 historical CAS values exist: Trend = Flat
- Dead-zone of ±5 prevents flip-flopping on noise

---

### C. Dispersion Index (Di)

**Purpose:** Measures disagreement among wallet behaviors. High dispersion = conflicting views = chop risk.

**Step 1: Compute per-wallet change ratio**
```
ratio_i = Δszi_i / max(|szi_initial_i|, ε)
```

**Step 2: Clamp outliers**
```
ratio_clamped_i = clamp(ratio_i, -2.0, +2.0)
```
This prevents tiny positions from exploding variance.

**Step 3: Compute standard deviation**
```
σ = stdev(ratio_clamped for all wallets)
```

**Step 4: Normalize to 0–100**
```
Di = min(σ / 1.0 × 100, 100)

where:
  σ = 0.0  →  Di = 0
  σ = 0.5  →  Di = 50
  σ ≥ 1.0  →  Di = 100
```

**Dispersion States:**
| State | Di Range | Interpretation |
|-------|----------|----------------|
| **Low** | 0–39 | Clean consensus, trend-friendly |
| **Medium** | 40–59 | Mixed signals, reduce aggression |
| **High** | 60–100 | Whales split, high chop risk |

**Edge cases:**
- If fewer than 5 wallets have valid ratios: Di = 50 (assume medium)
- If all ratios are identical: Di = 0

---

### D. Exit Cluster Score

**Purpose:** Detects coordinated de-risking before price turns.

**Formula:**
```
exit_cluster_score = (N_reducers / N_total) × 100
```

**Bounds:** `0 ≤ exit_cluster_score ≤ 100`

**Thresholds:**
| Level | Score | Interpretation |
|-------|-------|----------------|
| **Low** | 0–15 | Normal activity |
| **Medium** | 16–25 | Elevated caution |
| **High** | >25 | Active de-risking, distribution risk |

**Critical:** This signal is **behavior-only**. Do not reference price, profit, or external data.

**Edge cases:**
- If N_total = 0: exit_cluster_score = 0, but flag as degraded
- Reducers are counted regardless of direction (long reducing or short reducing)

---

## 3. Playbook Decision Matrix

The matrix maps signal combinations to actionable outputs.

### Primary Matrix

| CAS | Trend | Dispersion | Exit Cluster | Allowed Playbook | Risk Mode |
|-----|-------|------------|--------------|------------------|-----------|
| >75 | Rising | Low | Low | Long-only | Normal |
| >75 | Rising | Low | Medium | Long-only | Reduced |
| >75 | Flat | Low | Low | Long-only | Reduced |
| 60–75 | Rising | Low | Low | Long-only | Reduced |
| 60–75 | Any | Medium | Low | Long-only | Reduced |
| <25 | Falling | Low | Low | Short-only | Normal |
| <25 | Falling | Low | Medium | Short-only | Reduced |
| <25 | Flat | Low | Low | Short-only | Reduced |
| 25–40 | Falling | Low | Low | Short-only | Reduced |
| 25–40 | Any | Medium | Low | Short-only | Reduced |
| 40–60 | Any | Any | Any | No-trade | Defensive |
| Any | Any | High | Any | No-trade | Defensive |
| Any | Falling | Any | High | No-trade | Defensive |
| Any | Any | Any | High | No-trade | Defensive |

### Default Case
If no row matches:
```
allowed_playbook = No-trade
risk_mode = Reduced
```

This ensures safety when signals fall into edge cases.

---

## 4. Tie-Breaker Rules (Order Matters)

When signals conflict, apply rules **in strict order**:

### Priority 1: Dispersion Override
```
IF dispersion = High:
    allowed_playbook = No-trade
    risk_mode = Defensive
    (stop evaluation)
```

### Priority 2: Exit Cluster Override
```
IF exit_cluster = High:
    allowed_playbook = No-trade
    risk_mode = Defensive
    (stop evaluation)
```

### Priority 3: Trend Override
```
IF trend = Falling AND CAS > 60:
    # Distribution phase - high CAS is misleading
    allowed_playbook = No-trade
    risk_mode = Reduced
```

### Priority 4: Apply Matrix
If no override triggered, use the Playbook Decision Matrix.

**These rules are mandatory and non-negotiable.**

---

## 5. Derived Behavioral Outputs

### Add Exposure
| Condition | Value |
|-----------|-------|
| Trend = Rising AND Exit Cluster = Low AND Dispersion ≠ High | **Yes** |
| Otherwise | **No** |

### Tighten Stops
| Condition | Value |
|-----------|-------|
| Exit Cluster = High | **Yes** |
| Trend = Falling (from Rising or Flat) | **Yes** |
| Dispersion = High | **Yes** |
| Otherwise | **No** |

---

## 6. Missing Data Handling

### Threshold
Missing data threshold: **10% of wallets** (equivalent to <90% valid data).

### Behavior
| Missing % | CAS | Playbook | Risk Mode | Action |
|-----------|-----|----------|-----------|--------|
| 0–10% | Computed normally | From matrix | From matrix | Normal operation |
| 10–25% | 50 (forced) | No-trade | Reduced | Log warning |
| >25% | 50 (forced) | No-trade | Defensive | Log error, alert |

### Rules
- Never emit high-confidence regimes with incomplete data
- Dashboard must display data quality indicator
- Missing data events must be logged with counts

---

## 7. Signal Persistence

### Storage Contract
Every 5 minutes, write one row per asset to `signals` table:

```sql
INSERT INTO signals (
    timestamp,
    asset,
    alignment_score,
    alignment_trend,
    dispersion_index,
    exit_cluster_score,
    allowed_playbook,
    risk_mode,
    add_exposure,
    tighten_stops,
    wallet_count,
    missing_count,
    computation_ms
) VALUES (...);
```

### Historical Retention
- Keep at least **7 days** of signal history for charting
- Older data can be aggregated or archived

---

## 8. The Moat

This system's value is **Regime Gating**.

It separates:
- **Intent** (unit accumulation or distribution)
- from **Outcome** (price movement)

By using **signed unit size (szi)** instead of USD notional, it eliminates fake consensus caused by price fluctuations and forces discipline when large traders are conflicted or exiting.

**This is not prediction. This is structural cooperation detection.**

The edge comes from:
1. Behavioral classification (Adder/Reducer/Flat) not position size
2. Explicit reducer handling via Exit Cluster
3. Dispersion as a first-class override
4. Tie-breaker hierarchy that respects uncertainty

---

## 9. Tests (Minimum Required)

### Wallet Classification Tests
- Adder (Long) correctly identified when Δszi > ε and szi > 0
- Adder (Short) correctly identified when Δszi < -ε and szi < 0
- Reducer correctly identified when |szi_current| < |szi_5m_ago| - ε
- Flat assigned for changes within ε
- Missing szi_5m_ago → Flat classification

### CAS Tests
- CAS = 50 when N_add_long = N_add_short
- CAS = 100 when all wallets are Adder (Long)
- CAS = 0 when all wallets are Adder (Short)
- CAS capped at 60 when exit_cluster > 25
- CAS = 50 when N_total = 0
- Graceful degradation when <90% valid data

### Alignment Trend Tests
- Rising when CAS > avg + 5
- Falling when CAS < avg - 5
- Flat when within dead-zone
- Flat when insufficient history (<3 periods)

### Dispersion Tests
- Di = 0 when all ratios identical
- Di = 100 when σ ≥ 1.0
- Ratios clamped to ±200%
- Di = 50 when fewer than 5 valid wallets

### Exit Cluster Tests
- Correct percentage calculation
- High threshold at >25%
- Reducers counted regardless of direction

### Playbook Matrix Tests
- Each matrix row produces expected output
- Default case returns No-trade / Reduced
- Tie-breaker priority order enforced
- Dispersion override takes precedence
- Exit Cluster override takes precedence over Trend

### Derived Output Tests
- Add Exposure = Yes only when conditions met
- Tighten Stops = Yes on Exit Cluster High
- Tighten Stops = Yes on Trend transition to Falling

### Missing Data Tests
- >10% missing forces No-trade
- >25% missing forces Defensive
- Counts logged correctly

---

## Definition of Done

- [ ] Wallet states (Adder/Reducer/Flat) classified correctly per asset
- [ ] Epsilon calculated with absolute and relative components
- [ ] CAS computed with reducer penalty applied
- [ ] CAS gracefully degrades on missing data
- [ ] Alignment Trend uses 3-period rolling average with ±5 dead-zone
- [ ] Dispersion Index normalized to 0–100 with σ=1.0 ceiling
- [ ] Exit Cluster Score computed as reducer percentage
- [ ] Playbook matrix covers all signal combinations
- [ ] Tie-breaker rules applied in strict priority order
- [ ] Derived outputs (Add Exposure, Tighten Stops) computed correctly
- [ ] Missing data forces conservative outputs
- [ ] Signals persist every 5 minutes per asset
- [ ] All tests pass
- [ ] No price indicators introduced
