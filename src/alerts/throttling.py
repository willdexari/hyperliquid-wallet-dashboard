"""Alert throttling: cooldowns and daily limits."""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from src.db import db

logger = logging.getLogger(__name__)


def check_cooldown(asset: str, alert_type: str) -> bool:
    """
    Check if alert is in cooldown period.

    Args:
        asset: Asset symbol or 'SYSTEM'
        alert_type: Alert type (regime_change, exit_cluster, system_stale)

    Returns:
        True if alert is allowed (cooldown expired or no previous trigger)
        False if alert is in cooldown (should be suppressed)
    """
    query = """
        SELECT cooldown_until
        FROM alert_state
        WHERE asset = %(asset)s
          AND alert_type = %(alert_type)s
    """

    with db.get_cursor() as cur:
        cur.execute(query, {'asset': asset, 'alert_type': alert_type})
        result = cur.fetchone()

    if not result:
        # No previous state → not in cooldown
        return True

    cooldown_until = result['cooldown_until']
    if not cooldown_until:
        # No cooldown set → allowed
        return True

    now = datetime.now(timezone.utc)
    if now < cooldown_until:
        # Still in cooldown
        remaining_sec = (cooldown_until - now).total_seconds()
        logger.debug(
            f"Alert {alert_type} for {asset} in cooldown "
            f"({remaining_sec:.0f}s remaining)"
        )
        return False

    # Cooldown expired
    return True


def check_daily_limit(asset: str) -> bool:
    """
    Check if asset has exceeded daily alert limit (4 per rolling 24h).

    Args:
        asset: Asset symbol or 'SYSTEM'

    Returns:
        True if alert is allowed (under limit)
        False if alert should be suppressed (limit reached)
    """
    query = """
        SELECT COUNT(*) as count
        FROM alerts
        WHERE asset = %(asset)s
          AND timestamp > %(cutoff)s
          AND suppressed = FALSE
    """

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    with db.get_cursor() as cur:
        cur.execute(query, {'asset': asset, 'cutoff': cutoff})
        result = cur.fetchone()

    count = result['count'] if result else 0

    if count >= 4:
        logger.warning(
            f"Daily limit reached for {asset}: {count} alerts in last 24h"
        )
        return False

    return True


def should_fire_alert(asset: str, alert_type: str) -> bool:
    """
    Check all throttling rules to determine if alert should fire.

    Args:
        asset: Asset symbol or 'SYSTEM'
        alert_type: Alert type

    Returns:
        True if alert should fire, False if suppressed
    """
    # Check cooldown first (cheapest check)
    if not check_cooldown(asset, alert_type):
        logger.info(f"Alert suppressed (cooldown): {alert_type} for {asset}")
        return False

    # Check daily limit
    if not check_daily_limit(asset):
        logger.info(f"Alert suppressed (daily limit): {alert_type} for {asset}")
        return False

    return True


def get_cooldown_duration(alert_type: str) -> Optional[int]:
    """
    Get cooldown duration in minutes for alert type.

    Args:
        alert_type: Alert type

    Returns:
        Cooldown duration in minutes, or None for no cooldown
    """
    cooldowns = {
        'regime_change': 30,
        'exit_cluster': 60,
        'system_stale': None  # No cooldown (single-fire until resolved)
    }

    return cooldowns.get(alert_type)
