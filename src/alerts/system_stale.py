"""System Stale alert (dead man's switch)."""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple

from src.db import db
from src.alerts.persistence import (
    get_alert_state,
    update_alert_state,
    persist_alert
)

logger = logging.getLogger(__name__)


def check_system_stale() -> Tuple[bool, Optional[int]]:
    """
    Check if ingestion is stale (>10 minutes since last success).

    Returns:
        Tuple of (is_stale, minutes_stale)
        - is_stale: True if data is stale
        - minutes_stale: Minutes since last success, or None if not stale
    """
    query = """
        SELECT last_success_snapshot_ts
        FROM ingest_health
        ORDER BY health_ts DESC
        LIMIT 1
    """

    with db.get_cursor() as cur:
        cur.execute(query)
        result = cur.fetchone()

    if not result or not result['last_success_snapshot_ts']:
        # No successful ingestion yet → treat as stale
        logger.warning("No successful ingestion found in ingest_health")
        return True, None

    last_success_ts = result['last_success_snapshot_ts']
    now = datetime.now(timezone.utc)
    age = now - last_success_ts
    age_minutes = int(age.total_seconds() / 60)

    is_stale = age > timedelta(minutes=10)

    if is_stale:
        logger.warning(f"System STALE: {age_minutes} minutes since last ingestion")

    return is_stale, age_minutes if is_stale else None


def evaluate_system_stale_alert() -> bool:
    """
    Evaluate System Stale alert.

    Fires when:
        - now() - last_success_ts > 10 minutes

    Behavior:
        - No cooldown (always checks)
        - Single-fire until resolved
        - Uses is_active to track whether already fired

    Returns:
        True if alert fired, False otherwise
    """
    asset = 'SYSTEM'
    alert_type = 'system_stale'

    is_stale, minutes_stale = check_system_stale()

    # Get current state
    state = get_alert_state(asset, alert_type)
    is_active = state['is_active'] if state else False

    logger.debug(f"System Stale check: is_stale={is_stale}, is_active={is_active}")

    if is_stale and not is_active:
        # System is stale and we haven't fired yet → fire alert
        logger.warning(
            f"System Stale alert firing: {minutes_stale} minutes since last success"
        )

        # Update state to active (prevents re-firing)
        update_alert_state(asset, alert_type, is_active=True, cooldown_minutes=None)

        # Fire alert
        persist_alert(
            asset=asset,
            alert_type=alert_type,
            severity='critical',
            message=f"[SYSTEM] Data Stale: Ingestion has not succeeded for {minutes_stale} minutes. All behavioral alerts suppressed. Do not trade until resolved.",
            signal_snapshot={
                'minutes_stale': minutes_stale,
                'last_success_ts': None  # Could add timestamp if needed
            },
            cooldown_minutes=None,
            suppressed=False
        )
        return True

    elif not is_stale and is_active:
        # System recovered → reset state
        logger.info("System recovered from stale state")
        update_alert_state(asset, alert_type, is_active=False, cooldown_minutes=None)
        return False

    else:
        # No change (either still stale+active, or fresh+inactive)
        return False


def is_system_stale_active() -> bool:
    """
    Check if System Stale alert is currently active.

    This is used by other alerts to determine if they should be suppressed.

    Returns:
        True if System Stale is active, False otherwise
    """
    state = get_alert_state('SYSTEM', 'system_stale')
    return state['is_active'] if state else False
