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


def get_current_positioning(asset: str) -> Optional[Dict]:
    """
    Get current wallet positioning for an asset.

    This shows what wallets are actually holding, not behavioral changes.
    Computed from the most recent snapshot.

    Args:
        asset: Asset symbol (HYPE, BTC, ETH)

    Returns:
        Dictionary with positioning metrics:
        - snapshot_ts: Timestamp of snapshot
        - net_exposure: Total long szi - total short szi
        - long_count: Number of wallets with long positions
        - short_count: Number of wallets with short positions
        - flat_count: Number of wallets with no position
        - total_wallets: Total wallets in snapshot
        - long_pct: Percentage of positioned wallets that are long
        - short_pct: Percentage of positioned wallets that are short
        - top10_concentration: Percentage of total exposure held by top 10
        - top10_net_exposure: Net exposure of top 10 wallets
    """
    query = """
        WITH latest_snapshot AS (
            SELECT MAX(snapshot_ts) as ts
            FROM wallet_snapshots
            WHERE asset = %(asset)s
        ),
        wallet_positions AS (
            SELECT
                ws.snapshot_ts,
                ws.wallet_id,
                ws.position_szi,
                CASE
                    WHEN ws.position_szi > 0 THEN 'long'
                    WHEN ws.position_szi < 0 THEN 'short'
                    ELSE 'flat'
                END as position_type,
                ABS(ws.position_szi) as abs_position
            FROM wallet_snapshots ws
            INNER JOIN latest_snapshot ls ON ws.snapshot_ts = ls.ts
            WHERE ws.asset = %(asset)s
        ),
        top_10 AS (
            SELECT
                wallet_id,
                position_szi
            FROM wallet_positions
            ORDER BY abs_position DESC
            LIMIT 10
        )
        SELECT
            wp.snapshot_ts,
            COALESCE(SUM(wp.position_szi), 0) as net_exposure,
            COUNT(*) FILTER (WHERE wp.position_type = 'long') as long_count,
            COUNT(*) FILTER (WHERE wp.position_type = 'short') as short_count,
            COUNT(*) FILTER (WHERE wp.position_type = 'flat') as flat_count,
            COUNT(*) as total_wallets,
            COALESCE(SUM(t10.position_szi), 0) as top10_net_exposure,
            COALESCE(SUM(ABS(t10.position_szi)), 0) as top10_total_exposure,
            COALESCE(SUM(wp.abs_position), 0) as total_exposure
        FROM wallet_positions wp
        LEFT JOIN top_10 t10 ON wp.wallet_id = t10.wallet_id
        GROUP BY wp.snapshot_ts
    """

    with db.get_cursor() as cur:
        cur.execute(query, {'asset': asset})
        result = cur.fetchone()

    if not result or result['total_wallets'] == 0:
        return None

    # Calculate percentages
    positioned_wallets = result['long_count'] + result['short_count']
    long_pct = (result['long_count'] / positioned_wallets * 100) if positioned_wallets > 0 else 0
    short_pct = (result['short_count'] / positioned_wallets * 100) if positioned_wallets > 0 else 0

    # Calculate concentration (percentage of total exposure held by top 10)
    top10_concentration = (
        result['top10_total_exposure'] / result['total_exposure'] * 100
        if result['total_exposure'] > 0 else 0
    )

    return {
        'snapshot_ts': result['snapshot_ts'],
        'net_exposure': float(result['net_exposure']),
        'long_count': result['long_count'],
        'short_count': result['short_count'],
        'flat_count': result['flat_count'],
        'total_wallets': result['total_wallets'],
        'long_pct': round(long_pct, 1),
        'short_pct': round(short_pct, 1),
        'top10_concentration': round(top10_concentration, 1),
        'top10_net_exposure': float(result['top10_net_exposure'])
    }
