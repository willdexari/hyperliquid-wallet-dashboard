# skills/ingestion.md

## Purpose
Implement and modify the ingestion layer for the **Hyperliquid Wallet Dashboard**.

Ingestion has two responsibilities:
1) **Universe refresh (slow cadence):** fetch the current **top N wallets by 30D PnL** from the Hyperliquid leaderboard and persist the tracked universe.
2) **Snapshot ingest (fast cadence):** every **60 seconds**, fetch exposures/positions for the tracked wallets for **HYPE, BTC, ETH**, and write snapshot rows to the database.

Ingestion must be reliable, idempotent, rate-limit aware, and observable. It must never silently drop data.

---

## Source of Truth
- For business intent and constraints, follow `docs/`.
- This skill defines implementation guardrails and acceptance criteria for ingestion changes.

---

## Inputs and Outputs

### Inputs
- Assets: `["HYPE", "BTC", "ETH"]`
- Universe size: `N = 200` (default)
- Universe refresh cadence: `6 hours` (default)
- Snapshot cadence: `60 seconds` (fixed)

### API Endpoints

#### Leaderboard (Universe Refresh)
Primary:
- `GET https://stats-data.hyperliquid.xyz/Mainnet/leaderboard`

Fallback:
- `POST https://api.hyperliquid.xyz/info`
- Body: `{"type": "leaderboard", ...}` (shape depends on client)

#### Wallet Positions (Snapshot Ingest)
- `POST https://api.hyperliquid.xyz/info`
- Body: `{"type": "clearinghouseState", "user": "<wallet_address>"}`
- Returns: `assetPositions` array containing position objects with:
  - `position.coin` — asset symbol
  - `position.szi` — signed size in units (canonical)
  - `position.entryPx` — entry price
  - `position.liquidationPx` — liquidation price
  - `position.marginUsed` — margin allocated
  - `position.leverage` — leverage info

### Asset Symbol Mapping
Hyperliquid uses specific coin symbols. Map as follows:

| Dashboard Asset | Hyperliquid Symbol |
|-----------------|-------------------|
| `HYPE`          | `HYPE`            |
| `BTC`           | `BTC`             |
| `ETH`           | `ETH`             |

If Hyperliquid changes symbols (e.g., `WBTC` instead of `BTC`), update this mapping in config. Do not hardcode in multiple places.

### Outputs
- Persisted wallet universe:
  - current active universe (top N by 30D PnL)
  - refresh run history + membership + diffs
- Snapshot rows (every 60 seconds):
  - per `(timestamp, wallet_id, asset)` store **position proxy** (standardized below)
- Health state:
  - last successful universe refresh timestamp
  - last successful snapshot timestamp
  - partial/failed run markers + missing counts

---

## Golden Rules (Do Not Break)
1) **Assets are fixed:** ONLY HYPE, BTC, ETH.
2) **Snapshot cadence is fixed:** every 60 seconds.
3) **Universe source is leaderboard-based:** do not require manual lists for MVP.
4) **Idempotency:** rerunning the same timestamp must not create duplicates.
5) **No silent drops:** missing data must be counted and surfaced (logs + health table).
6) **Ingestion stores facts, not signals:** no regime logic in ingestion.
7) **Rate-limit safety:** never fire 200 wallet requests concurrently.
8) **Explicit zeros:** always write a row for each wallet/asset pair, even if no position exists.

---

## Leaderboard Universe Refresh

### Primary: stats-data endpoint
Fetch:
- `GET https://stats-data.hyperliquid.xyz/Mainnet/leaderboard`

Parse:
- `leaderboardRows`
- `wallet_id = row["ethAddress"]`
- `account_value = row.get("accountValue")`
- Convert `windowPerformances` list of pairs into dict:
  - `windows = dict(row.get("windowPerformances", []))`
- 30D pnl/roi:
  - `month_pnl = float(windows["month"]["pnl"])` when present else `0`
  - `month_roi = float(windows["month"]["roi"])` when present else `0`

Select:
- Sort by `month_pnl` desc
- Take top `N`

### Fallback: official info API
If stats-data fails, attempt:
- `POST https://api.hyperliquid.xyz/info` with a leaderboard request body supported by your client/script.
- The fallback must return enough data to identify wallets and rank by 30D pnl (or closest available window).

Rules:
- If both primary and fallback fail, keep last known good universe and mark refresh run failed.

### Persisting the universe
Write:
- `wallet_universe_runs(run_id, as_of_ts, n, source, status, entered_count, exited_count, duration_ms, error)`
- `wallet_universe_members(run_id, wallet_id, rank, month_pnl, month_roi, account_value)`
- `wallet_universe_current(wallet_id PRIMARY KEY, rank, month_pnl, month_roi, account_value, as_of_ts)`

### Stickiness (reduce churn)
- Refresh every 6 hours (default).
- Do not rebuild universe every minute.
- If refresh returns < 90% of expected valid entries, treat as failed and keep current universe.

### Universe diffs (required)
On each refresh:
- entered wallets (new in current, not in prior)
- exited wallets (in prior, not in new)

Persist and log:
- entered_count / exited_count
- (optional) top 10 entered/exited by rank/pnl

---

## Snapshot Ingest (60s)

### Timestamping (required)
Use **floor rounding** to the nearest 60-second boundary:

```python
from datetime import datetime, timezone

def get_snapshot_timestamp() -> datetime:
    """Return current UTC time floored to 60s boundary."""
    now = datetime.now(timezone.utc)
    return now.replace(second=0, microsecond=0)
```

Rules:
- Store timestamps in UTC.
- Always upsert by `(timestamp, wallet_id, asset)`.
- Floor rounding ensures consistency—snapshots always represent the minute that just started.

### Standardize the Position Proxy (critical)
Hyperliquid returns multiple fields (entry price, size, notional). For this project:

**Canonical position proxy = `szi` (size in units), signed.**

Rationale:
- `szi` reflects behavior (add/reduce/flip) without being distorted by price moves.
- USD notional can change even if the wallet does nothing.

Rules:
- Store `szi` as `position_szi` (signed).
- If needed for UI/debugging, also store:
  - `entry_px` (entry price) when available
  - `position_usd` or notional as a derived/optional field, but do not treat it as canonical

If the upstream does not expose `szi` for a wallet/asset:
- Store `position_szi = NULL`
- Optionally store a secondary proxy in separate columns (do not overload `position_szi`)
- Record missingness and treat as partial if widespread

### Zero Position Handling (required)
When a wallet has **no position** in an asset:
- **Always write a row** with `position_szi = 0`
- Do NOT skip the row or leave it missing

Rationale:
- Downstream aggregation needs consistent wallet counts per asset.
- A missing row is ambiguous (no position vs fetch failed). Explicit zero removes ambiguity.
- Behavioral deltas (flat → long, long → flat) require the "flat" state to exist.

Implementation:
```python
# For each wallet, for each asset in ["HYPE", "BTC", "ETH"]:
# - If position exists in response: store position.szi
# - If position does not exist: store position_szi = 0
```

### Snapshot row contract
Minimum per `(timestamp, wallet_id, asset)`:
- `timestamp` (UTC, floored to 60s)
- `wallet_id`
- `asset`
- `position_szi` (signed; canonical; 0 if no position)

Optional (store if available):
- `entry_px`
- `liq_px`
- `margin_used`
- `leverage`
- `position_usd` (debug only)
- `source_latency_ms`
- `ingest_run_id`

---

## Rate Limits and the "200 Requests" Bottleneck

### Problem
Fetching `clearinghouseState` for 200 wallets every 60s can trigger rate limits on public RPCs (commonly ~120/min). If you fire 200 concurrent async calls, you will get 429s immediately.

### Hard constraints (required)
- Implement a concurrency limiter for wallet fetches:
  - Use a semaphore / worker pool
  - Concurrency must be configurable
- Default settings:
  - `MAX_CONCURRENCY = 8` (start conservative)
  - `REQUEST_TIMEOUT_SEC = 10–20`
  - `MAX_ATTEMPTS = 3`
  - Backoff with jitter: 0.5s → 1.5s → 4s (+ jitter)
- Implement a per-cycle budget:
  - If you cannot complete the snapshot run before the next minute boundary, mark the run partial/failed and move on.

### Practical guidance
- Prefer batching endpoints if available (one request returning multiple wallets). If not, use controlled concurrency.
- If rate limited (429):
  - reduce concurrency automatically (optional)
  - increase backoff
  - log the event with counts

---

## Missing Data Handling

### Required behavior
For each snapshot run:
- expected_rows = `wallet_count * asset_count` (always 200 × 3 = 600 for full universe)
- written_rows
- missing_rows = expected - written

Rules:
- Missing data is never ignored.
- If missing > 5%:
  - mark run as `partial`
  - dashboard must show degraded health
- If the run fails completely:
  - mark run as `failed`
  - do not write partial garbage
  - dashboard must show stale

Also track:
- number of wallets that returned successfully
- number of wallets that failed
- number of assets missing `szi` values (should be 0 with explicit zeros)

---

## Idempotent Writes
- Use `UPSERT` (INSERT ... ON CONFLICT UPDATE) on `(timestamp, wallet_id, asset)` for snapshot rows.
- A rerun for the same timestamp must produce the same final DB state.
- Never create duplicate rows for the same (timestamp, wallet_id, asset) tuple.

---

## Observability and Health (must exist)

### Universe Refresh Run Record
Each universe refresh run must record:
- `run_id`
- `as_of_ts`
- `status`: success / failed
- `n_requested`, `n_received`
- `entered_count`, `exited_count`
- `duration_ms`
- `source`: stats-data / info-api-fallback
- `error` (string, if failed)

### Snapshot Ingest Run Record
Each snapshot ingest run must record:
- `run_id`
- `snapshot_ts`
- `status`: success / partial / failed
- `expected_rows`, `written_rows`, `missing_rows`
- `wallet_success_count`, `wallet_fail_count`
- `duration_ms`
- `error` (string, if failed)

### Dashboard Health Display
UI must display:
- Last successful universe refresh time
- Last successful snapshot time
- Current health: **healthy** / **partial** / **stale**
- Time since last successful snapshot (highlight if > 2 minutes)

---

## Tests (minimum required for ingestion changes)

### Leaderboard Tests
- Parses `leaderboardRows` into wallet list correctly
- Sorts by `month_pnl` descending correctly
- Handles missing month window safely (treat as 0)
- Handles missing `ethAddress` safely (skip invalid row)
- Diff calculation correctness (entered/exited counts)
- Fallback path is invoked when primary fails (mock)
- < 90% valid entries triggers failure status

### Snapshot Tests
- Timestamp rounding floors to 60s boundary
- Semaphore/concurrency limiter is enforced (mock fetch, count in-flight)
- Upsert idempotency on repeated runs (same timestamp → same state)
- Zero positions are written explicitly (no missing rows for flat wallets)
- Missing row detection and status classification (partial vs failed)
- 429 behavior: backoff/retry and proper run status if still failing
- Asset symbol mapping applied correctly

---

## Definition of Done (for any ingestion task)
- [ ] Universe refresh persists top 200 by 30D PnL using stats-data, with info API fallback.
- [ ] Snapshot ingest runs every 60s for HYPE/BTC/ETH using the current universe.
- [ ] Wallet positions fetched via `clearinghouseState` endpoint.
- [ ] Asset symbols mapped correctly (HYPE, BTC, ETH).
- [ ] Snapshot uses **signed `szi`** as canonical position proxy.
- [ ] Zero positions written explicitly (no missing rows).
- [ ] Timestamps floored to 60s boundary in UTC.
- [ ] Concurrency limits prevent immediate rate limiting.
- [ ] Missing data is surfaced via counts + health state.
- [ ] Re-running the same minute does not create duplicate snapshot rows.
- [ ] Dashboard can detect stale/partial from health markers.
