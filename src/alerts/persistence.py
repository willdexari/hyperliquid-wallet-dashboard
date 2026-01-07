"""Alert persistence to database."""

import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional
import json

from src.db import db

logger = logging.getLogger(__name__)


def persist_alert(
    asset: str,
    alert_type: str,
    severity: str,
    message: str,
    signal_snapshot: Dict,
    cooldown_minutes: Optional[int],
    suppressed: bool = False
) -> int:
    """
    Persist alert to database.

    Args:
        asset: Asset symbol or 'SYSTEM'
        alert_type: Alert type (regime_change, exit_cluster, system_stale)
        severity: Severity level (medium, high, critical)
        message: Alert message
        signal_snapshot: Dictionary with signal values at fire time
        cooldown_minutes: Cooldown duration in minutes, or None
        suppressed: Whether alert was suppressed by throttling

    Returns:
        Alert ID
    """
    now = datetime.now(timezone.utc)
    cooldown_until = now + timedelta(minutes=cooldown_minutes) if cooldown_minutes else now

    query = """
        INSERT INTO alerts (
            alert_ts,
            asset,
            alert_type,
            severity,
            message,
            signal_snapshot,
            cooldown_until,
            suppressed
        ) VALUES (
            %(alert_ts)s,
            %(asset)s,
            %(alert_type)s,
            %(severity)s,
            %(message)s,
            %(signal_snapshot)s,
            %(cooldown_until)s,
            %(suppressed)s
        )
        RETURNING id
    """

    # Handle SYSTEM asset (NULL in database for system-level alerts)
    asset_value = None if asset == 'SYSTEM' else asset

    params = {
        'alert_ts': now,
        'asset': asset_value,
        'alert_type': alert_type,
        'severity': severity,
        'message': message,
        'signal_snapshot': json.dumps(signal_snapshot),
        'cooldown_until': cooldown_until,
        'suppressed': suppressed
    }

    with db.get_cursor() as cur:
        cur.execute(query, params)
        alert_id = cur.fetchone()['id']

    if not suppressed:
        logger.info(
            f"Alert fired: [{asset}] {alert_type} ({severity}) - {message}"
        )
    else:
        logger.debug(
            f"Alert suppressed: [{asset}] {alert_type} - {message}"
        )

    return alert_id


def update_alert_state(
    asset: str,
    alert_type: str,
    is_active: bool,
    cooldown_minutes: Optional[int] = None
) -> None:
    """
    Update alert state for hysteresis tracking.

    Args:
        asset: Asset symbol or 'SYSTEM'
        alert_type: Alert type
        is_active: Whether condition is currently triggered
        cooldown_minutes: Cooldown duration in minutes, or None
    """
    now = datetime.now(timezone.utc)
    cooldown_until = now + timedelta(minutes=cooldown_minutes) if cooldown_minutes else None

    query = """
        INSERT INTO alert_state (
            asset,
            alert_type,
            is_active,
            last_triggered_ts,
            cooldown_until
        ) VALUES (
            %(asset)s,
            %(alert_type)s,
            %(is_active)s,
            %(last_triggered_ts)s,
            %(cooldown_until)s
        )
        ON CONFLICT (asset, alert_type)
        DO UPDATE SET
            is_active = EXCLUDED.is_active,
            last_triggered_ts = EXCLUDED.last_triggered_ts,
            cooldown_until = EXCLUDED.cooldown_until,
            updated_at = NOW()
    """

    params = {
        'asset': asset,
        'alert_type': alert_type,
        'is_active': is_active,
        'last_triggered_ts': now if is_active else None,
        'cooldown_until': cooldown_until
    }

    with db.get_cursor() as cur:
        cur.execute(query, params)

    logger.debug(
        f"Alert state updated: {asset}/{alert_type} → is_active={is_active}"
    )


def get_alert_state(asset: str, alert_type: str) -> Optional[Dict]:
    """
    Get current alert state for hysteresis tracking.

    Args:
        asset: Asset symbol or 'SYSTEM'
        alert_type: Alert type

    Returns:
        Dictionary with state fields, or None if no state exists
    """
    query = """
        SELECT
            is_active,
            last_triggered_ts,
            cooldown_until
        FROM alert_state
        WHERE asset = %(asset)s
          AND alert_type = %(alert_type)s
    """

    with db.get_cursor() as cur:
        cur.execute(query, {'asset': asset, 'alert_type': alert_type})
        result = cur.fetchone()

    if not result:
        return None

    return {
        'is_active': result['is_active'],
        'last_triggered_ts': result['last_triggered_ts'],
        'cooldown_until': result['cooldown_until']
    }


def get_regime_tracking_state(asset: str) -> Optional[Dict]:
    """
    Get regime change tracking state from alert_state table.

    Uses pending_playbook and pending_periods columns.

    Args:
        asset: Asset symbol

    Returns:
        Dictionary with tracking state, or None
    """
    query = """
        SELECT
            pending_playbook,
            pending_periods,
            signal_snapshot
        FROM alert_state
        WHERE asset = %(asset)s
          AND alert_type = 'regime_change'
    """

    with db.get_cursor() as cur:
        cur.execute(query, {'asset': asset})
        result = cur.fetchone()

    if not result:
        return None

    # Extract previous_playbook from signal_snapshot if exists
    previous_playbook = None
    if result['signal_snapshot']:
        previous_playbook = result['signal_snapshot'].get('previous_playbook')

    return {
        'pending_playbook': result['pending_playbook'],
        'periods_at_new': result['pending_periods'],
        'previous_playbook': previous_playbook
    }


def update_regime_tracking_state(
    asset: str,
    pending_playbook: Optional[str],
    periods_at_new: int,
    previous_playbook: Optional[str]
) -> None:
    """
    Update regime change tracking state.

    Args:
        asset: Asset symbol
        pending_playbook: Playbook waiting for 2-period persistence, or None
        periods_at_new: Number of periods at pending_playbook
        previous_playbook: Last confirmed playbook
    """
    query = """
        INSERT INTO alert_state (
            asset,
            alert_type,
            is_active,
            pending_playbook,
            pending_periods,
            signal_snapshot
        ) VALUES (
            %(asset)s,
            'regime_change',
            FALSE,
            %(pending_playbook)s,
            %(pending_periods)s,
            %(signal_snapshot)s
        )
        ON CONFLICT (asset, alert_type)
        DO UPDATE SET
            pending_playbook = EXCLUDED.pending_playbook,
            pending_periods = EXCLUDED.pending_periods,
            signal_snapshot = EXCLUDED.signal_snapshot,
            updated_at = NOW()
    """

    # Store previous_playbook in signal_snapshot for reference
    snapshot = {'previous_playbook': previous_playbook}

    with db.get_cursor() as cur:
        cur.execute(query, {
            'asset': asset,
            'pending_playbook': pending_playbook,
            'pending_periods': periods_at_new,
            'signal_snapshot': json.dumps(snapshot)
        })

    logger.debug(
        f"Regime tracking updated: {asset} → pending={pending_playbook}, "
        f"periods={periods_at_new}, previous={previous_playbook}"
    )
