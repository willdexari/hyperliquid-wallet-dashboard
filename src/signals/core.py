"""Core signal computation: CAS, Trend, Dispersion, Exit Cluster."""

import logging
from typing import Dict, List, Optional
from statistics import stdev
from datetime import datetime, timedelta

from src.db import db

logger = logging.getLogger(__name__)


def compute_cas(
    n_adder_long: int,
    n_adder_short: int,
    n_total: int,
    exit_cluster_score: float
) -> float:
    """
    Compute Consensus Alignment Score (CAS).

    Formula:
        CAS = 50 + ((N_add_long - N_add_short) / N_total × 50)

    With reducer penalty:
        If exit_cluster_score > 25: CAS = min(CAS, 60)

    Args:
        n_adder_long: Number of wallets adding long exposure
        n_adder_short: Number of wallets adding short exposure
        n_total: Total number of wallets with valid data
        exit_cluster_score: Exit cluster score (0-100)

    Returns:
        CAS value (0-100)
    """
    if n_total == 0:
        logger.warning("CAS computation: N_total = 0, returning 50 (neutral)")
        return 50.0

    # Calculate raw CAS
    cas = 50 + ((n_adder_long - n_adder_short) / n_total * 50)

    # Apply reducer penalty
    if exit_cluster_score > 25:
        cas = min(cas, 60)
        logger.info(f"Reducer penalty applied: CAS capped at 60 (exit_cluster={exit_cluster_score:.1f})")

    # Ensure bounds
    return max(0, min(100, cas))


def fetch_historical_cas(asset: str, periods: int = 3) -> List[float]:
    """
    Fetch recent historical CAS values for trend computation.

    Args:
        asset: Asset symbol
        periods: Number of historical periods to fetch

    Returns:
        List of CAS values (most recent first), may be shorter than periods
    """
    query = """
        SELECT alignment_score
        FROM signals
        WHERE asset = %(asset)s
        ORDER BY signal_ts DESC
        LIMIT %(limit)s
    """

    with db.get_cursor() as cur:
        cur.execute(query, {'asset': asset, 'limit': periods})
        results = cur.fetchall()

    return [float(row['alignment_score']) for row in results]


def compute_alignment_trend(
    current_cas: float,
    asset: str
) -> str:
    """
    Compute alignment trend based on 3-period rolling average.

    Rules:
        - Rising:  CAS_current > CAS_avg_15m + 5
        - Falling: CAS_current < CAS_avg_15m − 5
        - Flat:    Otherwise (within ±5 dead-zone)

    Args:
        current_cas: Current CAS value
        asset: Asset symbol (for fetching history)

    Returns:
        "rising", "flat", or "falling"
    """
    # Fetch last 3 CAS values (excluding current)
    historical_cas = fetch_historical_cas(asset, periods=3)

    if len(historical_cas) < 3:
        logger.info(f"Insufficient CAS history ({len(historical_cas)}/3) - defaulting to 'flat'")
        return "flat"

    # Calculate 15-minute rolling average (3 × 5-minute periods)
    cas_avg_15m = sum(historical_cas) / len(historical_cas)

    logger.debug(f"CAS trend calc: current={current_cas:.1f}, avg_15m={cas_avg_15m:.1f}")

    # Determine trend with ±5 dead-zone
    if current_cas > cas_avg_15m + 5:
        return "rising"
    elif current_cas < cas_avg_15m - 5:
        return "falling"
    else:
        return "flat"


def compute_dispersion_index(classifications: Dict[str, Dict]) -> float:
    """
    Compute Dispersion Index (wallet disagreement).

    Steps:
        1. Compute per-wallet change ratio: ratio_i = Δszi_i / max(|szi_initial_i|, ε)
        2. Clamp outliers: ratio_clamped_i = clamp(ratio_i, -2.0, +2.0)
        3. Compute standard deviation: σ = stdev(ratio_clamped)
        4. Normalize to 0–100: Di = min(σ / 1.0 × 100, 100)

    Args:
        classifications: Dict[wallet_id -> {szi_current, szi_previous, delta_szi, epsilon, ...}]

    Returns:
        Dispersion Index (0-100)
    """
    ratios = []

    for wallet_data in classifications.values():
        szi_previous = wallet_data['szi_previous']
        delta_szi = wallet_data['delta_szi']
        epsilon = wallet_data['epsilon']

        if szi_previous is None or delta_szi is None:
            continue

        # Calculate change ratio
        denominator = max(abs(szi_previous), epsilon)
        ratio = delta_szi / denominator

        # Clamp to ±2.0 (±200%)
        ratio_clamped = max(-2.0, min(2.0, ratio))

        ratios.append(ratio_clamped)

    # Edge case: fewer than 5 wallets
    if len(ratios) < 5:
        logger.warning(f"Dispersion: only {len(ratios)} valid ratios, defaulting to 50 (medium)")
        return 50.0

    # Edge case: all ratios identical
    if len(set(ratios)) == 1:
        logger.info("Dispersion: all ratios identical, returning 0")
        return 0.0

    # Compute standard deviation
    sigma = stdev(ratios)

    # Normalize to 0-100 (σ=1.0 maps to Di=100)
    di = min(sigma / 1.0 * 100, 100)

    logger.debug(f"Dispersion: σ={sigma:.3f}, Di={di:.1f}, n_ratios={len(ratios)}")

    return di


def compute_exit_cluster_score(n_reducer: int, n_total: int) -> float:
    """
    Compute Exit Cluster Score (de-risking percentage).

    Formula:
        exit_cluster_score = (N_reducers / N_total) × 100

    Args:
        n_reducer: Number of wallets reducing exposure
        n_total: Total number of wallets with valid data

    Returns:
        Exit Cluster Score (0-100)
    """
    if n_total == 0:
        logger.warning("Exit Cluster: N_total = 0, returning 0")
        return 0.0

    ec = (n_reducer / n_total) * 100

    logger.debug(f"Exit Cluster: {n_reducer}/{n_total} reducers = {ec:.1f}%")

    return ec


def compute_all_signals(
    counts: Dict[str, int],
    classifications: Dict[str, Dict],
    asset: str
) -> Dict:
    """
    Compute all core signals.

    Args:
        counts: Wallet state counts from classifier
        classifications: Full wallet classifications
        asset: Asset symbol

    Returns:
        Dictionary with all signal values:
        {
            'alignment_score': float,
            'alignment_trend': str,
            'dispersion_index': float,
            'exit_cluster_score': float
        }
    """
    # 1. Compute Exit Cluster Score first (needed for CAS reducer penalty)
    exit_cluster_score = compute_exit_cluster_score(
        counts['n_reducer'],
        counts['n_total']
    )

    # 2. Compute CAS (with reducer penalty)
    cas = compute_cas(
        counts['n_adder_long'],
        counts['n_adder_short'],
        counts['n_total'],
        exit_cluster_score
    )

    # 3. Compute Alignment Trend
    trend = compute_alignment_trend(cas, asset)

    # 4. Compute Dispersion Index
    di = compute_dispersion_index(classifications)

    return {
        'alignment_score': cas,
        'alignment_trend': trend,
        'dispersion_index': di,
        'exit_cluster_score': exit_cluster_score
    }
