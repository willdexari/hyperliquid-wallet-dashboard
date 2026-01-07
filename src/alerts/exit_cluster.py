"""Exit Cluster alert with hysteresis (trigger >25%, reset <20%)."""

import logging
from typing import Dict, Optional

from src.alerts.persistence import (
    get_alert_state,
    update_alert_state,
    persist_alert
)
from src.alerts.throttling import should_fire_alert, get_cooldown_duration

logger = logging.getLogger(__name__)


def evaluate_exit_cluster_alert(
    asset: str,
    signals: Dict,
    suppressed_by_system: bool = False
) -> bool:
    """
    Evaluate Exit Cluster alert with hysteresis.

    Hysteresis Logic:
        - Trigger: exit_cluster_score > 25%
        - Reset: exit_cluster_score < 20%
        - Buffer: 20-25% (no action in this zone)

    Args:
        asset: Asset symbol
        signals: Dictionary with signal values (exit_cluster_score, ...)
        suppressed_by_system: If True, suppress behavioral alerts

    Returns:
        True if alert fired, False otherwise
    """
    if suppressed_by_system:
        logger.debug(f"Exit Cluster alert suppressed by System Stale for {asset}")
        return False

    exit_cluster_score = signals['exit_cluster_score']
    alert_type = 'exit_cluster'

    # Get current hysteresis state
    state = get_alert_state(asset, alert_type)
    is_active = state['is_active'] if state else False

    logger.debug(
        f"{asset}: Exit Cluster check: score={exit_cluster_score:.1f}, "
        f"is_active={is_active}"
    )

    # Hysteresis logic
    should_trigger = False

    if not is_active and exit_cluster_score > 25:
        # Condition crossed above trigger threshold
        should_trigger = True
        new_is_active = True
        logger.info(
            f"{asset}: Exit Cluster crossed above 25% "
            f"({exit_cluster_score:.1f}%) → triggering alert"
        )

    elif is_active and exit_cluster_score < 20:
        # Condition crossed below reset threshold
        new_is_active = False
        logger.info(
            f"{asset}: Exit Cluster dropped below 20% "
            f"({exit_cluster_score:.1f}%) → resetting state"
        )

    else:
        # No state change (either in buffer zone or condition unchanged)
        new_is_active = is_active
        if is_active:
            logger.debug(
                f"{asset}: Exit Cluster still active "
                f"({exit_cluster_score:.1f}%), waiting for reset <20%"
            )

    # Update state
    cooldown_minutes = get_cooldown_duration(alert_type)
    update_alert_state(asset, alert_type, new_is_active, cooldown_minutes if should_trigger else None)

    # Fire alert if triggered
    if should_trigger:
        # Check throttling
        if not should_fire_alert(asset, alert_type):
            # Log suppressed alert
            persist_alert(
                asset=asset,
                alert_type=alert_type,
                severity='high',
                message=f"[{asset}] Smart Money De-risking: Exit Cluster elevated ({exit_cluster_score:.1f}%). Stop adding exposure. Tighten stops.",
                signal_snapshot=signals,
                cooldown_minutes=cooldown_minutes,
                suppressed=True
            )
            return False

        # Fire alert
        persist_alert(
            asset=asset,
            alert_type=alert_type,
            severity='high',
            message=f"[{asset}] Smart Money De-risking: Exit Cluster elevated ({exit_cluster_score:.1f}%). Stop adding exposure. Tighten stops.",
            signal_snapshot=signals,
            cooldown_minutes=cooldown_minutes,
            suppressed=False
        )
        return True

    return False
