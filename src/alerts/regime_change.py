"""Regime Change alert with 2-period persistence requirement."""

import logging
from typing import Dict, Optional

from src.alerts.persistence import (
    get_regime_tracking_state,
    update_regime_tracking_state,
    persist_alert,
    update_alert_state
)
from src.alerts.throttling import should_fire_alert, get_cooldown_duration

logger = logging.getLogger(__name__)


def evaluate_regime_change_alert(
    asset: str,
    signals: Dict,
    suppressed_by_system: bool = False
) -> bool:
    """
    Evaluate Regime Change alert with 2-period persistence.

    Fires when:
        - allowed_playbook changes value
        - AND new value persists for 2 consecutive signal periods (10 minutes)

    Args:
        asset: Asset symbol
        signals: Dictionary with signal values (allowed_playbook, risk_mode, ...)
        suppressed_by_system: If True, suppress behavioral alerts

    Returns:
        True if alert fired, False otherwise
    """
    if suppressed_by_system:
        logger.debug(f"Regime Change alert suppressed by System Stale for {asset}")
        return False

    current_playbook = signals['allowed_playbook']
    alert_type = 'regime_change'

    # Get tracking state
    tracking = get_regime_tracking_state(asset)

    if not tracking:
        # First time seeing this asset → initialize tracking
        logger.debug(f"{asset}: Initializing regime tracking with {current_playbook}")
        update_regime_tracking_state(
            asset=asset,
            pending_playbook=None,
            periods_at_new=0,
            previous_playbook=current_playbook
        )
        return False

    previous_playbook = tracking['previous_playbook']
    pending_playbook = tracking['pending_playbook']
    periods_at_new = tracking['periods_at_new']

    logger.debug(
        f"{asset}: Regime check: current={current_playbook}, "
        f"previous={previous_playbook}, pending={pending_playbook}, "
        f"periods={periods_at_new}"
    )

    # Detect playbook change
    playbook_changed = (current_playbook != previous_playbook)

    if playbook_changed:
        # Playbook changed from previous
        if pending_playbook == current_playbook:
            # Still at the same pending playbook → increment period count
            periods_at_new += 1
            logger.info(
                f"{asset}: Regime change pending: {current_playbook} "
                f"(period {periods_at_new}/2)"
            )

            if periods_at_new >= 2:
                # 2-period persistence achieved → fire alert
                logger.info(
                    f"{asset}: Regime change confirmed: "
                    f"{previous_playbook} → {current_playbook} (2 periods)"
                )

                # Check throttling
                cooldown_minutes = get_cooldown_duration(alert_type)
                if not should_fire_alert(asset, alert_type):
                    # Log suppressed alert
                    persist_alert(
                        asset=asset,
                        alert_type=alert_type,
                        severity='medium',
                        message=f"[{asset}] Regime Change: Playbook switched to {current_playbook}. Risk Mode: {signals['risk_mode']}.",
                        signal_snapshot=signals,
                        cooldown_minutes=cooldown_minutes,
                        suppressed=True
                    )

                    # Still update tracking state (regime change confirmed)
                    update_regime_tracking_state(
                        asset=asset,
                        pending_playbook=None,
                        periods_at_new=0,
                        previous_playbook=current_playbook
                    )
                    return False

                # Fire alert
                persist_alert(
                    asset=asset,
                    alert_type=alert_type,
                    severity='medium',
                    message=f"[{asset}] Regime Change: Playbook switched to {current_playbook}. Risk Mode: {signals['risk_mode']}.",
                    signal_snapshot=signals,
                    cooldown_minutes=cooldown_minutes,
                    suppressed=False
                )

                # Update alert_state for cooldown tracking
                update_alert_state(asset, alert_type, is_active=False, cooldown_minutes=cooldown_minutes)

                # Update tracking: reset pending, update previous
                update_regime_tracking_state(
                    asset=asset,
                    pending_playbook=None,
                    periods_at_new=0,
                    previous_playbook=current_playbook
                )

                return True

            else:
                # Still waiting for 2nd period
                update_regime_tracking_state(
                    asset=asset,
                    pending_playbook=current_playbook,
                    periods_at_new=periods_at_new,
                    previous_playbook=previous_playbook
                )
                return False

        else:
            # New playbook different from pending → restart tracking
            logger.info(
                f"{asset}: Regime change started: "
                f"{previous_playbook} → {current_playbook} (period 1/2)"
            )
            update_regime_tracking_state(
                asset=asset,
                pending_playbook=current_playbook,
                periods_at_new=1,
                previous_playbook=previous_playbook
            )
            return False

    else:
        # Playbook same as previous (no change)
        if pending_playbook == current_playbook:
            # We're at a pending playbook and it's still current → increment
            periods_at_new += 1
            logger.debug(
                f"{asset}: Regime at pending playbook: {current_playbook} "
                f"(period {periods_at_new}/2)"
            )

            if periods_at_new >= 2:
                # This should not happen (we would have fired above)
                # But handle it just in case
                logger.warning(
                    f"{asset}: Regime tracking anomaly: periods={periods_at_new} "
                    f"but playbook_changed=False"
                )
                # Treat as stable → reset pending
                update_regime_tracking_state(
                    asset=asset,
                    pending_playbook=None,
                    periods_at_new=0,
                    previous_playbook=current_playbook
                )

            else:
                update_regime_tracking_state(
                    asset=asset,
                    pending_playbook=pending_playbook,
                    periods_at_new=periods_at_new,
                    previous_playbook=previous_playbook
                )

            return False

        elif pending_playbook is not None:
            # We had a pending playbook but reverted to previous → cancel pending
            logger.info(
                f"{asset}: Regime change cancelled: reverted to {current_playbook}"
            )
            update_regime_tracking_state(
                asset=asset,
                pending_playbook=None,
                periods_at_new=0,
                previous_playbook=current_playbook
            )
            return False

        else:
            # No pending, no change → stable
            # No update needed (but update anyway to refresh state)
            update_regime_tracking_state(
                asset=asset,
                pending_playbook=None,
                periods_at_new=0,
                previous_playbook=current_playbook
            )
            return False
