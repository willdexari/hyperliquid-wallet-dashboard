"""Health state computation for dashboard."""

import logging
from datetime import datetime, timezone, timedelta
from typing import Tuple

from src.ui.data_loader import get_ingest_health, check_system_stale_alert_active

logger = logging.getLogger(__name__)


def compute_health_state() -> Tuple[str, dict]:
    """
    Compute overall system health state.

    Health State Thresholds:
        HEALTHY:  snapshot ≤ 2m AND coverage ≥ 90%
        DEGRADED: snapshot 2-10m OR coverage 80-90%
        STALE:    snapshot > 10m OR coverage < 80% OR System Stale alert

    Returns:
        Tuple of (health_state, health_info)
        - health_state: "HEALTHY", "DEGRADED", or "STALE"
        - health_info: Dictionary with health details
    """
    health = get_ingest_health()

    if not health:
        logger.warning("No ingest health data found")
        return "STALE", {
            'last_snapshot_ts': None,
            'snapshot_age_minutes': None,
            'coverage_pct': 0,
            'error': 'No health data available'
        }

    # Check if System Stale alert is active
    system_stale_active = check_system_stale_alert_active()

    # Calculate snapshot age
    last_snapshot_ts = health['last_success_snapshot_ts']
    now = datetime.now(timezone.utc)

    if last_snapshot_ts:
        snapshot_age = now - last_snapshot_ts
        snapshot_age_minutes = int(snapshot_age.total_seconds() / 60)
    else:
        snapshot_age_minutes = None

    coverage_pct = health['coverage_pct']

    # Build health info
    health_info = {
        'last_snapshot_ts': last_snapshot_ts,
        'snapshot_age_minutes': snapshot_age_minutes,
        'coverage_pct': coverage_pct,
        'snapshot_status': health['snapshot_status'],
        'health_state_db': health['health_state'],
        'error': health.get('error'),
        'system_stale_active': system_stale_active
    }

    # Determine health state
    if system_stale_active:
        return "STALE", health_info

    if snapshot_age_minutes is None or snapshot_age_minutes > 10:
        return "STALE", health_info

    if coverage_pct < 80:
        return "STALE", health_info

    if snapshot_age_minutes > 2 or coverage_pct < 90:
        return "DEGRADED", health_info

    return "HEALTHY", health_info
