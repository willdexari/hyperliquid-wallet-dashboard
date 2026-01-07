"""Database queries for dashboard UI."""

import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional

from src.db import db

logger = logging.getLogger(__name__)


def get_latest_signals() -> List[Dict]:
    """
    Get latest signals for all assets.

    Returns:
        List of signal dictionaries (one per asset)
    """
    query = """
        SELECT
            signal_ts,
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
        FROM signals
        WHERE signal_ts = (SELECT MAX(signal_ts) FROM signals)
        ORDER BY asset
    """

    with db.get_cursor() as cur:
        cur.execute(query)
        results = cur.fetchall()

    return [dict(row) for row in results] if results else []


def get_signal_history(asset: str, hours: int = 6) -> List[Dict]:
    """
    Get signal history for a specific asset.

    Args:
        asset: Asset symbol
        hours: Number of hours of history (6 or 24)

    Returns:
        List of signal dictionaries ordered by timestamp
    """
    query = """
        SELECT
            signal_ts,
            asset,
            alignment_score,
            alignment_trend,
            dispersion_index,
            exit_cluster_score,
            allowed_playbook,
            risk_mode
        FROM signals
        WHERE asset = %(asset)s
          AND signal_ts > %(cutoff)s
        ORDER BY signal_ts ASC
    """

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    with db.get_cursor() as cur:
        cur.execute(query, {'asset': asset, 'cutoff': cutoff})
        results = cur.fetchall()

    return [dict(row) for row in results] if results else []


def get_latest_contributors(asset: str) -> Optional[Dict]:
    """
    Get latest contributor breakdown for an asset.

    Args:
        asset: Asset symbol

    Returns:
        Dictionary with contributor percentages and counts, or None
    """
    query = """
        SELECT
            signal_ts,
            asset,
            pct_add_long,
            pct_add_short,
            pct_reducers,
            pct_flat,
            count_add_long,
            count_add_short,
            count_reducers,
            count_flat,
            total_wallets
        FROM signal_contributors
        WHERE asset = %(asset)s
          AND signal_ts = (
              SELECT MAX(signal_ts)
              FROM signal_contributors
              WHERE asset = %(asset)s
          )
    """

    with db.get_cursor() as cur:
        cur.execute(query, {'asset': asset})
        result = cur.fetchone()

    return dict(result) if result else None


def get_recent_alerts(hours: int = 24, limit: int = 5) -> List[Dict]:
    """
    Get recent alerts from last N hours.

    System Stale alerts are pinned to top.

    Args:
        hours: Number of hours to look back
        limit: Maximum number of alerts to return

    Returns:
        List of alert dictionaries
    """
    query = """
        SELECT
            id,
            alert_ts,
            asset,
            alert_type,
            severity,
            message,
            suppressed
        FROM alerts
        WHERE alert_ts > %(cutoff)s
          AND suppressed = FALSE
        ORDER BY
            CASE WHEN alert_type = 'system_stale' THEN 0 ELSE 1 END,
            alert_ts DESC
        LIMIT %(limit)s
    """

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    with db.get_cursor() as cur:
        cur.execute(query, {'cutoff': cutoff, 'limit': limit})
        results = cur.fetchall()

    return [dict(row) for row in results] if results else []


def get_ingest_health() -> Optional[Dict]:
    """
    Get latest ingestion health status.

    Returns:
        Dictionary with health fields, or None
    """
    query = """
        SELECT
            health_ts,
            last_success_snapshot_ts,
            snapshot_status,
            coverage_pct,
            health_state,
            error
        FROM ingest_health
        ORDER BY health_ts DESC
        LIMIT 1
    """

    with db.get_cursor() as cur:
        cur.execute(query)
        result = cur.fetchone()

    return dict(result) if result else None


def get_latest_signal_timestamp() -> Optional[datetime]:
    """
    Get timestamp of the latest signal computation.

    Returns:
        Latest signal timestamp, or None
    """
    query = """
        SELECT MAX(signal_ts) as latest_signal_ts
        FROM signals
    """

    with db.get_cursor() as cur:
        cur.execute(query)
        result = cur.fetchone()

    return result['latest_signal_ts'] if result and result['latest_signal_ts'] else None


def check_system_stale_alert_active() -> bool:
    """
    Check if System Stale alert is currently active.

    Returns:
        True if System Stale is active, False otherwise
    """
    query = """
        SELECT is_active
        FROM alert_state
        WHERE asset = 'SYSTEM'
          AND alert_type = 'system_stale'
    """

    with db.get_cursor() as cur:
        cur.execute(query)
        result = cur.fetchone()

    return result['is_active'] if result else False
