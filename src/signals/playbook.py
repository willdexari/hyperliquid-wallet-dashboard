"""Playbook decision matrix and derived outputs."""

import logging
from typing import Dict, Tuple

logger = logging.getLogger(__name__)


def determine_playbook(
    cas: float,
    trend: str,
    dispersion: float,
    exit_cluster: float
) -> Tuple[str, str]:
    """
    Determine allowed playbook and risk mode using decision matrix with tie-breaker rules.

    Tie-Breaker Priority (STRICT ORDER):
        1. Dispersion Override:  Di ≥ 60 → No-trade / Defensive
        2. Exit Cluster Override: EC > 25 → No-trade / Defensive
        3. Trend Override: Falling + CAS > 60 → No-trade / Reduced
        4. Apply Playbook Matrix

    Args:
        cas: Consensus Alignment Score (0-100)
        trend: Alignment trend ("rising", "flat", "falling")
        dispersion: Dispersion Index (0-100)
        exit_cluster: Exit Cluster Score (0-100)

    Returns:
        Tuple of (allowed_playbook, risk_mode)
        - allowed_playbook: "Long-only", "Short-only", or "No-trade"
        - risk_mode: "Normal", "Reduced", or "Defensive"
    """
    # ===========================================================
    # PRIORITY 1: Dispersion Override
    # ===========================================================
    if dispersion >= 60:
        logger.info(f"Dispersion override: Di={dispersion:.1f} → No-trade/Defensive")
        return "No-trade", "Defensive"

    # ===========================================================
    # PRIORITY 2: Exit Cluster Override
    # ===========================================================
    if exit_cluster > 25:
        logger.info(f"Exit Cluster override: EC={exit_cluster:.1f} → No-trade/Defensive")
        return "No-trade", "Defensive"

    # ===========================================================
    # PRIORITY 3: Trend Override (Distribution Detection)
    # ===========================================================
    if trend == "falling" and cas > 60:
        logger.info(f"Trend override: Falling + CAS={cas:.1f} → No-trade/Reduced (distribution phase)")
        return "No-trade", "Reduced"

    # ===========================================================
    # PRIORITY 4: Apply Playbook Decision Matrix
    # ===========================================================

    # Define dispersion levels
    di_low = dispersion < 40
    di_medium = 40 <= dispersion < 60
    di_high = dispersion >= 60  # Already handled above

    # Define exit cluster levels
    ec_low = exit_cluster < 16
    ec_medium = 16 <= exit_cluster <= 25
    ec_high = exit_cluster > 25  # Already handled above

    # --- LONG-ONLY PLAYBOOK ---

    # Strong bullish: CAS >75, Rising, Low Di, Low EC
    if cas > 75 and trend == "rising" and di_low and ec_low:
        return "Long-only", "Normal"

    # Strong bullish with caution: CAS >75, Rising, Low Di, Medium EC
    if cas > 75 and trend == "rising" and di_low and ec_medium:
        return "Long-only", "Reduced"

    # Strong bullish, stable: CAS >75, Flat, Low Di, Low EC
    if cas > 75 and trend == "flat" and di_low and ec_low:
        return "Long-only", "Reduced"

    # Moderate bullish, building: CAS 60-75, Rising, Low Di, Low EC
    if 60 <= cas <= 75 and trend == "rising" and di_low and ec_low:
        return "Long-only", "Reduced"

    # Moderate bullish, mixed signals: CAS 60-75, Any trend, Medium Di, Low EC
    if 60 <= cas <= 75 and di_medium and ec_low:
        return "Long-only", "Reduced"

    # --- SHORT-ONLY PLAYBOOK ---

    # Strong bearish: CAS <25, Falling, Low Di, Low EC
    if cas < 25 and trend == "falling" and di_low and ec_low:
        return "Short-only", "Normal"

    # Strong bearish with caution: CAS <25, Falling, Low Di, Medium EC
    if cas < 25 and trend == "falling" and di_low and ec_medium:
        return "Short-only", "Reduced"

    # Strong bearish, stable: CAS <25, Flat, Low Di, Low EC
    if cas < 25 and trend == "flat" and di_low and ec_low:
        return "Short-only", "Reduced"

    # Moderate bearish, building: CAS 25-40, Falling, Low Di, Low EC
    if 25 <= cas < 40 and trend == "falling" and di_low and ec_low:
        return "Short-only", "Reduced"

    # Moderate bearish, mixed signals: CAS 25-40, Any trend, Medium Di, Low EC
    if 25 <= cas < 40 and di_medium and ec_low:
        return "Short-only", "Reduced"

    # --- NO-TRADE PLAYBOOK ---

    # Neutral zone: CAS 40-60 (regardless of other signals)
    if 40 <= cas <= 60:
        return "No-trade", "Defensive"

    # --- DEFAULT CASE (Safety Fallback) ---

    logger.info(
        f"No matrix match: CAS={cas:.1f}, Trend={trend}, Di={dispersion:.1f}, EC={exit_cluster:.1f} "
        "→ Default: No-trade/Reduced"
    )
    return "No-trade", "Reduced"


def compute_derived_outputs(signals: Dict) -> Dict:
    """
    Compute derived behavioral outputs.

    Rules:
        - add_exposure = Yes IF:
            Trend = Rising AND Exit Cluster = Low AND Dispersion ≠ High
        - tighten_stops = Yes IF:
            Exit Cluster = High OR Trend = Falling OR Dispersion = High

    Args:
        signals: Dictionary with alignment_trend, dispersion_index, exit_cluster_score

    Returns:
        Dictionary with:
        {
            'add_exposure': bool,
            'tighten_stops': bool
        }
    """
    trend = signals['alignment_trend']
    dispersion = signals['dispersion_index']
    exit_cluster = signals['exit_cluster_score']

    # Add Exposure
    add_exposure = (
        trend == "rising"
        and exit_cluster < 16  # Low
        and dispersion < 60    # Not High
    )

    # Tighten Stops
    tighten_stops = (
        exit_cluster > 25      # High
        or trend == "falling"
        or dispersion >= 60    # High
    )

    return {
        'add_exposure': add_exposure,
        'tighten_stops': tighten_stops
    }


def apply_playbook_logic(signals: Dict) -> Dict:
    """
    Apply full playbook logic: decision matrix + derived outputs.

    Args:
        signals: Dictionary with:
            - alignment_score
            - alignment_trend
            - dispersion_index
            - exit_cluster_score

    Returns:
        Dictionary with all signals plus:
            - allowed_playbook
            - risk_mode
            - add_exposure
            - tighten_stops
    """
    # Determine playbook and risk mode
    allowed_playbook, risk_mode = determine_playbook(
        signals['alignment_score'],
        signals['alignment_trend'],
        signals['dispersion_index'],
        signals['exit_cluster_score']
    )

    # Compute derived outputs
    derived = compute_derived_outputs(signals)

    # Return full signal set
    return {
        **signals,
        'allowed_playbook': allowed_playbook,
        'risk_mode': risk_mode,
        'add_exposure': derived['add_exposure'],
        'tighten_stops': derived['tighten_stops']
    }
