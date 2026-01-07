# skills/dashboard.md

## Purpose
Define the **UI and interaction rules** for the Hyperliquid Wallet Dashboard.

The dashboard exists to make signals **usable under pressure**:
- One screen
- Instant trust check (freshness + coverage)
- Clear regime gating (Long-only / Short-only / No-trade)
- Minimal charts, minimal clutter

If the UI causes hesitation, second-guessing, or overtrading, it is wrong.

---

## Source of Truth
- For signal definitions, follow `skills/signals.md`.
- For alert logic, follow `skills/alerts.md`.
- This skill defines UI layout, behavior, and acceptance criteria.

---

## Scope (Hard Constraints)
- Assets: **HYPE, BTC, ETH only**
- Data cadence: snapshots 60s, signals 5m
- UI framework: **Streamlit** (MVP)
- **Single-screen** primary view (no multi-page app)
- **Laptop viewport assumed** (no mobile optimization for MVP)
- Dashboard **reads from DB only**; it never computes signals

---

## Golden Rules (Do Not Break)
1. **Health first.** If data is stale or degraded, the UI must dominate attention.
2. **Regime gating over details.** Playbook output is the primary product.
3. **No indicator soup.** No RSI, MACD, moving averages, or candles.
4. **Minimize cognitive load.** Fewer widgets, fewer charts, fewer knobs.
5. **Default to safety.** When uncertain, show No-trade and Defensive.
6. **Avoid flicker.** UI updates must not visually thrash on small changes.
7. **No computation in UI.** All derived values come from backend tables.

---

## Layout Requirements (Single Screen)

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

---

### A) Global Header (Always Visible)

**Required elements:**
| Element | Display | Source |
|---------|---------|--------|
| System Health | Healthy / Degraded / Stale | Computed from health checks |
| Last Snapshot | "Last snapshot: 12:34:56 UTC" | `ingest_runs.last_success_ts` |
| Last Signal | "Signals updated: 12:35:00 UTC" | `signals.max(timestamp)` |
| Wallet Coverage | "Coverage: 98%" | `ingest_runs.coverage_pct` |

**Streamlit implementation:**
```python
header_cols = st.columns([2, 1, 1, 1])
with header_cols[0]:
    st.markdown(f"### {health_icon} {health_state}")
with header_cols[1]:
    st.caption(f"Snapshot: {last_snapshot_ts}")
with header_cols[2]:
    st.caption(f"Signals: {last_signal_ts}")
with header_cols[3]:
    st.caption(f"Coverage: {coverage_pct}%")
```

**Health state banners:**
| State | Banner | Color |
|-------|--------|-------|
| Healthy | None | — |
| Degraded | `st.warning("⚠️ Data quality degraded...")` | Yellow |
| Stale | Full SYSTEM HALT (see Mask Rule) | Red |

---

### B) Asset Summary Row (Decision Surface)

Three side-by-side panels using `st.columns(3)`.

**Each panel displays (in visual priority order):**

| Priority | Element | Style |
|----------|---------|-------|
| 1 | Allowed Playbook | Large text, colored background |
| 2 | Risk Mode | Medium text |
| 3 | Exit Cluster warning | Red badge if High |
| 4 | Dispersion warning | Yellow badge if High |
| 5 | CAS + Trend | Value with arrow (↑ → ↓) |
| 6 | Dispersion State | Low / Medium / High |
| 7 | Exit Cluster State | Low / Medium / High |

**Playbook colors:**
| Playbook | Background | Text |
|----------|------------|------|
| Long-only | Green (muted) | White |
| Short-only | Red (muted) | White |
| No-trade | Gray | White |

**Trend arrows:**
| Trend | Arrow |
|-------|-------|
| Rising | ↑ |
| Flat | → |
| Falling | ↓ |

**Streamlit implementation:**
```python
asset_cols = st.columns(3)
for i, asset in enumerate(["HYPE", "BTC", "ETH"]):
    with asset_cols[i]:
        signals = get_latest_signals(asset)
        
        # Playbook (largest, colored)
        playbook_color = {"Long-only": "green", "Short-only": "red", "No-trade": "gray"}
        st.markdown(f"### {asset}")
        st.markdown(
            f'<div style="background:{playbook_color[signals.playbook]};padding:10px;border-radius:5px;">'
            f'<h2>{signals.allowed_playbook}</h2></div>',
            unsafe_allow_html=True
        )
        
        st.markdown(f"**Risk Mode:** {signals.risk_mode}")
        st.markdown(f"CAS: {signals.alignment_score:.0f} {trend_arrow(signals.alignment_trend)}")
        st.markdown(f"Dispersion: {dispersion_state(signals.dispersion_index)}")
        st.markdown(f"Exit Cluster: {exit_state(signals.exit_cluster_score)}")
```

**Clicking an asset panel selects it for the Detail Section.**

---

### C) Alerts Panel (Compact)

**Display rules:**
- Show up to **5 most recent alerts from the last 24 hours**
- If no alerts in 24h: show "No recent alerts"
- If System Stale alert exists: **pin to top** regardless of timestamp

**Fields per alert:**
| Field | Example |
|-------|---------|
| Timestamp | 12:34 UTC |
| Asset | HYPE |
| Type | Exit Cluster |
| Severity | High |
| Message | (truncated to 50 chars) |

**Severity indicators:**
| Severity | Icon |
|----------|------|
| Medium | ⚠️ |
| High | 🔴 |
| Critical | 🚨 |

**Streamlit implementation:**
```python
st.subheader("Recent Alerts")
alerts = get_recent_alerts(hours=24, limit=5)

if not alerts:
    st.info("No recent alerts")
else:
    for alert in alerts:
        severity_icon = {"medium": "⚠️", "high": "🔴", "critical": "🚨"}[alert.severity]
        st.markdown(
            f"{severity_icon} **{alert.timestamp.strftime('%H:%M')}** "
            f"[{alert.asset}] {alert.alert_type}: {alert.message[:50]}"
        )
```

---

### D) Detail Section (Below the Fold)

**Asset selection:**
- Default: HYPE
- User can select by clicking asset panel or using radio buttons
- Selection persists across auto-refreshes (see State Persistence)

**Signal time series charts:**

| Chart | Y-Axis | Range |
|-------|--------|-------|
| CAS | Fixed | 0–100 |
| Dispersion Index | Fixed | 0–100 |
| Exit Cluster Score | Fixed | 0–100 |

**Chart specifications:**
- X-axis: Time
- Default window: 6 hours
- Toggle option: 24 hours
- Current value highlighted at right edge with label
- Horizontal threshold lines:
  - CAS: 25, 75 (regime boundaries)
  - Dispersion: 40, 60 (state boundaries)
  - Exit Cluster: 20, 25 (hysteresis boundaries)
- Minimal chrome: no gridlines, no legends (label in title)

**Streamlit implementation:**
```python
st.subheader(f"{selected_asset} Signal History")

time_range = st.radio("Time Range", ["6h", "24h"], horizontal=True, key="time_range")
hours = 6 if time_range == "6h" else 24

history = get_signal_history(selected_asset, hours=hours)

# CAS Chart
fig_cas = create_signal_chart(
    history, 
    metric="alignment_score", 
    title="Consensus Alignment Score",
    thresholds=[25, 75]
)
st.plotly_chart(fig_cas, use_container_width=True)

# Dispersion Chart
fig_disp = create_signal_chart(
    history,
    metric="dispersion_index",
    title="Dispersion Index", 
    thresholds=[40, 60]
)
st.plotly_chart(fig_disp, use_container_width=True)

# Exit Cluster Chart
fig_exit = create_signal_chart(
    history,
    metric="exit_cluster_score",
    title="Exit Cluster Score",
    thresholds=[20, 25]
)
st.plotly_chart(fig_exit, use_container_width=True)
```

**Contributors summary (collapsed by default):**
```python
with st.expander("Wallet Behavior Breakdown"):
    contrib = get_contributor_summary(selected_asset)  # From backend table
    st.metric("Adding Long", f"{contrib.pct_add_long:.1f}%")
    st.metric("Adding Short", f"{contrib.pct_add_short:.1f}%")
    st.metric("Reducing", f"{contrib.pct_reducers:.1f}%")
    st.metric("Flat", f"{contrib.pct_flat:.1f}%")
```

**Note:** Contributors summary is pre-computed in the aggregation layer and stored in `signal_contributors` table. The UI only reads; it does not compute.

---

## Auto-Refresh Mechanism

### Implementation
Use `streamlit-autorefresh` or manual timer pattern:

```python
from streamlit_autorefresh import st_autorefresh

# Refresh every 30 seconds
st_autorefresh(interval=30_000, limit=None, key="dashboard_refresh")
```

**Alternative (without external package):**
```python
import time

if "last_refresh" not in st.session_state:
    st.session_state.last_refresh = time.time()

if time.time() - st.session_state.last_refresh > 30:
    st.session_state.last_refresh = time.time()
    st.rerun()
```

### Rules
- Default interval: **30 seconds**
- Refresh must NOT reset user's selected asset
- Refresh must NOT reset time range toggle
- Refresh must NOT cause visible flicker (data should update smoothly)

---

## State Persistence

Use `st.session_state` to persist user selections across refreshes.

```python
# Initialize defaults
if "selected_asset" not in st.session_state:
    st.session_state.selected_asset = "HYPE"

if "time_range" not in st.session_state:
    st.session_state.time_range = "6h"

# Use in components
selected_asset = st.session_state.selected_asset
```

**Persisted state:**
| Key | Default | Purpose |
|-----|---------|---------|
| `selected_asset` | "HYPE" | Detail section focus |
| `time_range` | "6h" | Chart time window |

**Not persisted (recomputed each render):**
- Health state
- Signal values
- Alerts list

---

## Data Freshness and Trust Surfaces

### Health State Computation

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

---

## Degraded State Visual Treatment

When `health_state == "DEGRADED"`:

| Element | Change |
|---------|--------|
| Banner | Yellow warning banner at top |
| Asset panel borders | Yellow border (2px) |
| Playbook labels | Append "(degraded)" suffix |
| Risk Mode | Show actual value (already forced to Reduced+ by signals) |
| Charts | Show normally but with yellow border |
| Alerts | Show normally |

**Implementation:**
```python
if health_state == "DEGRADED":
    st.warning("⚠️ Data quality degraded. Coverage or freshness below optimal. Signals may be less reliable.")
    panel_border_color = "orange"
    playbook_suffix = " (degraded)"
else:
    panel_border_color = None
    playbook_suffix = ""
```

---

## Decision Surface Mask (Force-of-Law)

### Definition
The **Decision Surface** includes:
- Asset summary panels (Section B)
- Alerts panel (Section C)
- Signal charts (Section D)
- Any component that could influence a trade decision

### Mask Rule (Hard Stop)

If `health_state == "STALE"`:

1. **Do NOT render** any Decision Surface components
2. **Replace** main content with SYSTEM HALT view
3. **Call `st.stop()`** to prevent further rendering

**SYSTEM HALT view:**
```python
def render_system_halt(last_snapshot_ts: datetime, gap_minutes: int):
    st.error("🚨 SYSTEM HALT: DATA STALE")
    
    st.markdown(
        """
        <div style="text-align:center;padding:50px;background:#1a1a1a;border:3px solid red;border-radius:10px;">
            <h1 style="color:red;">⛔ SYSTEM HALT</h1>
            <h2 style="color:white;">DATA STALE</h2>
            <p style="color:#aaa;">Signals and alerts are suppressed until ingestion resumes.</p>
        </div>
        """,
        unsafe_allow_html=True
    )
    
    st.markdown("---")
    st.markdown(f"**Last successful snapshot:** {last_snapshot_ts} UTC")
    st.markdown(f"**Data gap:** {gap_minutes} minutes")
    st.markdown("---")
    st.markdown("**Troubleshooting:**")
    st.markdown("1. Check ingestion process: `python -m src.ingest.fetch`")
    st.markdown("2. Check API status: https://api.hyperliquid.xyz/info")
    st.markdown("3. See `docs/runbooks/local_dev.md` for debugging steps")
    
    st.stop()  # CRITICAL: Prevents any further rendering
```

### Allowed in Stale State
- Global header (health status)
- Last snapshot timestamp
- Gap duration
- Troubleshooting hints

### Forbidden in Stale State
- ❌ Last-known playbooks
- ❌ Last-known signals
- ❌ Historical charts
- ❌ Behavioral alerts
- ❌ Contributors summary

**Rationale:** Showing stale bullish data could cause harmful trade decisions. Full mask is the only safe option.

### Implementation (Top-Level)

```python
def main():
    # 1. Always render header first
    render_global_header()
    
    # 2. Compute health state
    health_state = compute_health_state()
    
    # 3. HARD STOP if stale
    if health_state == "STALE":
        render_system_halt(
            last_snapshot_ts=get_last_snapshot_ts(),
            gap_minutes=get_snapshot_gap_minutes()
        )
        # st.stop() called inside render_system_halt
        # Nothing below this executes
    
    # 4. Show degraded warning if applicable
    if health_state == "DEGRADED":
        st.warning("⚠️ Data quality degraded...")
    
    # 5. Render decision surfaces
    render_asset_panels()
    render_alerts_panel()
    render_detail_section()


if __name__ == "__main__":
    main()
```

---

## Interaction Rules

| Rule | Rationale |
|------|-----------|
| No sliders for thresholds | Prevents live tuning / overfitting |
| No knobs or advanced controls | Reduces cognitive load |
| No editable fields | Dashboard is read-only |
| Click asset to select for detail | Simple, intuitive interaction |
| Radio buttons for time range | Binary choice, no sliders |

---

## Performance Requirements

| Metric | Target |
|--------|--------|
| Initial render | < 2 seconds |
| Auto-refresh cycle | < 1 second |
| Chart render | < 500ms |

### Optimization Rules
- **No wallet-level queries** on main render path
- **Pre-aggregate** contributor summaries in backend
- **Limit chart data** to 6h/24h windows
- **Cache health state** within render cycle

### UI Queries (Allowed)
```sql
-- Latest signals per asset (3 rows)
SELECT * FROM signals 
WHERE timestamp = (SELECT MAX(timestamp) FROM signals)
ORDER BY asset;

-- Signal history for detail section
SELECT * FROM signals 
WHERE asset = :selected_asset 
  AND timestamp > NOW() - INTERVAL ':hours hours'
ORDER BY timestamp;

-- Health state
SELECT * FROM ingest_runs 
ORDER BY timestamp DESC LIMIT 1;

-- Recent alerts (5 rows max)
SELECT * FROM alerts 
WHERE timestamp > NOW() - INTERVAL '24 hours'
  AND suppressed = FALSE
ORDER BY 
  CASE WHEN alert_type = 'system_stale' THEN 0 ELSE 1 END,
  timestamp DESC
LIMIT 5;

-- Contributor summary (pre-computed)
SELECT * FROM signal_contributors
WHERE asset = :selected_asset
  AND timestamp = (SELECT MAX(timestamp) FROM signal_contributors WHERE asset = :selected_asset);
```

---

## Explicit Non-Features (Do NOT Build)

| Feature | Reason |
|---------|--------|
| Wallet tables on main screen | Cognitive overload |
| Leaderboards | Not actionable |
| Price candles or charts | No price indicators |
| RSI/MACD/MA overlays | No indicator soup |
| Trade buttons | No execution in MVP |
| Multi-page navigation | Single-screen constraint |
| Advanced filters/search | MVP simplicity |
| Threshold configuration UI | Prevents live tuning |
| Dark/light mode toggle | MVP simplicity |
| Export/download buttons | MVP simplicity |

---

## Tests / QA Checklist

### Health State Tests
- [ ] STALE state triggers full Decision Surface mask
- [ ] STALE state shows SYSTEM HALT view
- [ ] STALE state calls `st.stop()` (nothing renders below)
- [ ] DEGRADED state shows yellow warning banner
- [ ] DEGRADED state adds yellow borders to panels
- [ ] DEGRADED state appends "(degraded)" to playbook labels
- [ ] HEALTHY state shows no banners or warnings

### Asset Panel Tests
- [ ] All three assets display side-by-side
- [ ] Playbook is visually largest element
- [ ] Playbook colors are correct (green/red/gray)
- [ ] Trend arrows display correctly (↑ → ↓)
- [ ] CAS value displays as integer
- [ ] Dispersion/Exit states map correctly (Low/Medium/High)
- [ ] Clicking panel selects asset for detail section

### Alerts Panel Tests
- [ ] Shows max 5 alerts from last 24h
- [ ] System Stale alert pinned to top
- [ ] "No recent alerts" shown when empty
- [ ] Severity icons display correctly
- [ ] Timestamps formatted as HH:MM UTC

### Detail Section Tests
- [ ] Default asset is HYPE
- [ ] Asset selection persists across refresh
- [ ] Time range toggle works (6h/24h)
- [ ] Time range persists across refresh
- [ ] Charts have fixed Y-axis (0-100)
- [ ] Threshold lines visible on charts
- [ ] Current value labeled at right edge
- [ ] Contributors summary loads from backend (no UI computation)

### Auto-Refresh Tests
- [ ] Dashboard refreshes every 30 seconds
- [ ] Selected asset not reset on refresh
- [ ] Time range not reset on refresh
- [ ] No visible flicker on refresh

### Performance Tests
- [ ] Initial render < 2 seconds
- [ ] No wallet-level queries in render path
- [ ] Chart render < 500ms

### No-Price Tests
- [ ] No price data anywhere in UI
- [ ] No candle charts
- [ ] No indicator overlays

---

## Definition of Done

- [ ] Single-screen dashboard implemented in Streamlit
- [ ] Global header shows health, timestamps, coverage
- [ ] Three asset panels with playbook as primary element
- [ ] Alerts panel shows 5 most recent (24h window)
- [ ] Detail section with 3 signal time series charts
- [ ] Auto-refresh every 30 seconds
- [ ] State persistence for selected asset and time range
- [ ] STALE state fully masks Decision Surface
- [ ] DEGRADED state visually downgrades confidence
- [ ] No price data, candles, or indicators
- [ ] No execution controls
- [ ] No threshold configuration UI
- [ ] Initial render < 2 seconds
- [ ] All QA checklist items pass

---

## Design Philosophy

A good dashboard **reduces** actions, not increases them.

| If the dashboard... | It has... |
|---------------------|-----------|
| Makes you want to trade more | Failed |
| Makes you trade less but better | Succeeded |
| Makes you second-guess your read | Failed |
| Makes regime clear in 3 seconds | Succeeded |
| Shows you everything | Failed |
| Shows you only what matters | Succeeded |

**The best trade is often no trade. The dashboard should make that obvious.**
