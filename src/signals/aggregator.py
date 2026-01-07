"""Snapshot aggregation for 5-minute signal windows."""

import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional, Tuple
from collections import defaultdict

from src.db import db

logger = logging.getLogger(__name__)


def get_signal_timestamp() -> datetime:
    """
    Return current UTC time floored to 5-minute boundary.

    Returns:
        Datetime floored to the nearest 5 minutes
    """
    now = datetime.now(timezone.utc)
    # Floor to 5-minute boundary
    minutes = (now.minute // 5) * 5
    return now.replace(minute=minutes, second=0, microsecond=0)


def fetch_snapshots_for_window(
    signal_ts: datetime,
    asset: str,
    window_minutes: int = 5
) -> List[Dict]:
    """
    Fetch wallet snapshots for a specific time window.

    Args:
        signal_ts: The signal timestamp (5-minute boundary)
        asset: Asset symbol (HYPE, BTC, or ETH)
        window_minutes: Window size in minutes (default: 5)

    Returns:
        List of snapshot dictionaries with wallet_id, position_szi, snapshot_ts
    """
    window_start = signal_ts - timedelta(minutes=window_minutes)

    query = """
        SELECT
            wallet_id,
            position_szi,
            snapshot_ts,
            entry_px,
            leverage,
            margin_used,
            is_dirty
        FROM wallet_snapshots
        WHERE asset = %(asset)s
          AND snapshot_ts > %(window_start)s
          AND snapshot_ts <= %(signal_ts)s
          AND is_dirty = FALSE
        ORDER BY wallet_id, snapshot_ts DESC
    """

    with db.get_cursor() as cur:
        cur.execute(query, {
            'asset': asset,
            'window_start': window_start,
            'signal_ts': signal_ts
        })
        return cur.fetchall()


def get_latest_snapshot_per_wallet(
    snapshots: List[Dict]
) -> Dict[str, Dict]:
    """
    Get the most recent snapshot for each wallet.

    Args:
        snapshots: List of snapshots (must be ordered by snapshot_ts DESC)

    Returns:
        Dictionary mapping wallet_id -> latest snapshot
    """
    latest = {}
    for snapshot in snapshots:
        wallet_id = snapshot['wallet_id']
        if wallet_id not in latest:
            latest[wallet_id] = snapshot
    return latest


def build_wallet_deltas(
    current_snapshots: Dict[str, Dict],
    previous_snapshots: Dict[str, Dict]
) -> Dict[str, Dict]:
    """
    Build position deltas for each wallet.

    Args:
        current_snapshots: Latest snapshots (wallet_id -> snapshot)
        previous_snapshots: Snapshots from 5 minutes ago (wallet_id -> snapshot)

    Returns:
        Dictionary mapping wallet_id -> {
            'szi_current': float,
            'szi_previous': float,
            'delta_szi': float,
            'snapshot_ts_current': datetime,
            'snapshot_ts_previous': datetime or None
        }
    """
    deltas = {}

    # Get all wallet IDs from both windows
    all_wallet_ids = set(current_snapshots.keys()) | set(previous_snapshots.keys())

    for wallet_id in all_wallet_ids:
        current = current_snapshots.get(wallet_id)
        previous = previous_snapshots.get(wallet_id)

        if current is None:
            # Wallet exists in previous but not current (missing data)
            logger.warning(f"Wallet {wallet_id} missing from current window")
            continue

        szi_current = float(current['position_szi'])
        szi_previous = float(previous['position_szi']) if previous else None
        snapshot_ts_current = current['snapshot_ts']
        snapshot_ts_previous = previous['snapshot_ts'] if previous else None

        # Calculate delta
        if szi_previous is not None:
            delta_szi = szi_current - szi_previous
        else:
            # No previous data - cannot calculate delta
            delta_szi = None

        deltas[wallet_id] = {
            'szi_current': szi_current,
            'szi_previous': szi_previous,
            'delta_szi': delta_szi,
            'snapshot_ts_current': snapshot_ts_current,
            'snapshot_ts_previous': snapshot_ts_previous
        }

    return deltas


def fetch_24h_history(wallet_id: str, asset: str) -> List[Dict]:
    """
    Fetch 24-hour position history for epsilon calculation.

    Args:
        wallet_id: Wallet address
        asset: Asset symbol

    Returns:
        List of snapshots from the last 24 hours
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    query = """
        SELECT
            position_szi,
            snapshot_ts
        FROM wallet_snapshots
        WHERE wallet_id = %(wallet_id)s
          AND asset = %(asset)s
          AND snapshot_ts > %(cutoff)s
          AND is_dirty = FALSE
        ORDER BY snapshot_ts DESC
    """

    with db.get_cursor() as cur:
        cur.execute(query, {
            'wallet_id': wallet_id,
            'asset': asset,
            'cutoff': cutoff
        })
        return cur.fetchall()


def aggregate_for_signal_period(
    signal_ts: datetime,
    asset: str
) -> Tuple[Dict[str, Dict], int, int]:
    """
    Aggregate snapshots for a signal computation period.

    Args:
        signal_ts: Signal timestamp (5-minute boundary)
        asset: Asset symbol

    Returns:
        Tuple of:
        - wallet_deltas: Dict[wallet_id -> delta info]
        - wallet_count: Number of wallets with valid data
        - missing_count: Number of wallets without sufficient data
    """
    logger.info(f"Aggregating snapshots for {asset} at {signal_ts}")

    # Fetch current window (0-5 minutes ago)
    current_snapshots_list = fetch_snapshots_for_window(signal_ts, asset, window_minutes=5)

    # Fetch previous window (5-10 minutes ago)
    previous_ts = signal_ts - timedelta(minutes=5)
    previous_snapshots_list = fetch_snapshots_for_window(previous_ts, asset, window_minutes=5)

    # Get latest snapshot per wallet in each window
    current_snapshots = get_latest_snapshot_per_wallet(current_snapshots_list)
    previous_snapshots = get_latest_snapshot_per_wallet(previous_snapshots_list)

    # Build deltas
    wallet_deltas = build_wallet_deltas(current_snapshots, previous_snapshots)

    # Count valid vs missing
    wallet_count = len([d for d in wallet_deltas.values() if d['delta_szi'] is not None])
    missing_count = len([d for d in wallet_deltas.values() if d['delta_szi'] is None])

    logger.info(
        f"{asset}: {wallet_count} wallets with valid deltas, "
        f"{missing_count} missing previous data"
    )

    return wallet_deltas, wallet_count, missing_count


def check_signal_lock() -> bool:
    """
    Check if signal computation should proceed based on ingest health.

    Returns:
        True if signals should be computed, False if locked

    Signal Lock Rules:
        - If health_state = 'stale': Lock (do not compute)
        - If snapshot_status = 'failed': Lock (do not compute)
        - Otherwise: Proceed
    """
    query = """
        SELECT
            health_state,
            snapshot_status,
            last_success_snapshot_ts,
            coverage_pct
        FROM ingest_health
        ORDER BY health_ts DESC
        LIMIT 1
    """

    with db.get_cursor() as cur:
        cur.execute(query)
        health = cur.fetchone()

    if not health:
        logger.warning("No health state found - signal lock engaged")
        return False

    if health['health_state'] == 'stale':
        logger.warning(
            f"Signal lock engaged: data is stale "
            f"(last success: {health['last_success_snapshot_ts']})"
        )
        return False

    if health['snapshot_status'] == 'failed':
        logger.warning("Signal lock engaged: last ingestion failed")
        return False

    logger.info(
        f"Signal lock check passed: {health['health_state']}, "
        f"coverage {health['coverage_pct']:.1f}%"
    )
    return True
