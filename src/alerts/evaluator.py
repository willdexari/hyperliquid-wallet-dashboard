"""Main alert evaluator - orchestrates all alert types."""

import logging
from datetime import datetime
from typing import Dict, List

from src.alerts.system_stale import evaluate_system_stale_alert, is_system_stale_active
from src.alerts.regime_change import evaluate_regime_change_alert
from src.alerts.exit_cluster import evaluate_exit_cluster_alert

logger = logging.getLogger(__name__)


def evaluate_alerts(signal_ts: datetime, asset: str, signals: Dict) -> List[str]:
    """
    Evaluate all alerts for a single asset.

    Evaluation order:
        1. System Stale (checked once globally, not per asset)
        2. Regime Change (if not suppressed)
        3. Exit Cluster (if not suppressed)

    Args:
        signal_ts: Signal timestamp
        asset: Asset symbol
        signals: Dictionary with all signal values

    Returns:
        List of alert types that fired
    """
    alerts_fired = []

    # Note: System Stale is checked globally, not per asset
    # We check suppression status here
    suppressed_by_system = is_system_stale_active()

    if suppressed_by_system:
        logger.info(
            f"Behavioral alerts suppressed for {asset} (System Stale active)"
        )
        return alerts_fired

    # Evaluate Regime Change
    try:
        if evaluate_regime_change_alert(asset, signals, suppressed_by_system):
            alerts_fired.append('regime_change')
    except Exception as e:
        logger.error(f"Regime Change evaluation failed for {asset}: {e}", exc_info=True)

    # Evaluate Exit Cluster
    try:
        if evaluate_exit_cluster_alert(asset, signals, suppressed_by_system):
            alerts_fired.append('exit_cluster')
    except Exception as e:
        logger.error(f"Exit Cluster evaluation failed for {asset}: {e}", exc_info=True)

    if alerts_fired:
        logger.info(
            f"{asset}: {len(alerts_fired)} alert(s) fired: {', '.join(alerts_fired)}"
        )

    return alerts_fired


def evaluate_system_alerts() -> List[str]:
    """
    Evaluate system-level alerts (System Stale).

    This should be called once per signal computation cycle,
    not once per asset.

    Returns:
        List of alert types that fired (contains 'system_stale' if fired)
    """
    alerts_fired = []

    try:
        if evaluate_system_stale_alert():
            alerts_fired.append('system_stale')
    except Exception as e:
        logger.error(f"System Stale evaluation failed: {e}", exc_info=True)

    return alerts_fired


def evaluate_all_alerts(
    signal_ts: datetime,
    assets: List[str],
    signals_by_asset: Dict[str, Dict]
) -> Dict[str, List[str]]:
    """
    Evaluate all alerts for all assets.

    Args:
        signal_ts: Signal timestamp
        assets: List of asset symbols
        signals_by_asset: Dictionary mapping asset -> signals dict

    Returns:
        Dictionary mapping asset -> list of alert types that fired
        Includes 'SYSTEM' key for system-level alerts
    """
    results = {}

    # 1. Evaluate System Stale first (global)
    logger.info(f"=== Evaluating System Alerts at {signal_ts} ===")
    system_alerts = evaluate_system_alerts()
    if system_alerts:
        results['SYSTEM'] = system_alerts

    # 2. Evaluate behavioral alerts per asset
    for asset in assets:
        if asset not in signals_by_asset:
            logger.warning(f"No signals found for {asset}, skipping alert evaluation")
            continue

        logger.info(f"=== Evaluating Alerts for {asset} ===")
        asset_alerts = evaluate_alerts(signal_ts, asset, signals_by_asset[asset])

        if asset_alerts:
            results[asset] = asset_alerts

    # Summary
    total_alerts = sum(len(alerts) for alerts in results.values())
    logger.info(
        f"Alert evaluation complete: {total_alerts} alert(s) fired across "
        f"{len(results)} asset(s)/system"
    )

    return results
