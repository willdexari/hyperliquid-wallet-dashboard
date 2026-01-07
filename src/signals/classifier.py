"""Wallet behavioral classification logic."""

import logging
from typing import Dict, List, Optional
from enum import Enum
from statistics import median

from src.signals.aggregator import fetch_24h_history

logger = logging.getLogger(__name__)


class WalletState(str, Enum):
    """Wallet behavioral states."""
    ADDER_LONG = "adder_long"
    ADDER_SHORT = "adder_short"
    REDUCER = "reducer"
    FLAT = "flat"


# Asset-specific epsilon absolute values
EPSILON_ABSOLUTE = {
    'HYPE': 0.01,
    'BTC': 0.0001,
    'ETH': 0.001
}


def calculate_epsilon(wallet_id: str, asset: str, history: Optional[List[Dict]] = None) -> float:
    """
    Calculate epsilon (minimum meaningful change) for a wallet.

    Formula:
        ε = max(ε_absolute, ε_relative)
        where ε_relative = 0.02 × median(|szi|) over last 24h

    Args:
        wallet_id: Wallet address
        asset: Asset symbol (HYPE, BTC, or ETH)
        history: Optional pre-fetched 24h history (for performance)

    Returns:
        Epsilon threshold for this wallet
    """
    epsilon_absolute = EPSILON_ABSOLUTE.get(asset, 0.01)

    # Fetch history if not provided
    if history is None:
        history = fetch_24h_history(wallet_id, asset)

    if len(history) == 0:
        return epsilon_absolute

    # Calculate median absolute szi
    abs_szis = [abs(float(h['position_szi'])) for h in history]
    median_szi = median(abs_szis) if abs_szis else 0

    if median_szi == 0:
        return epsilon_absolute

    epsilon_relative = 0.02 * median_szi

    return max(epsilon_absolute, epsilon_relative)


def classify_wallet(
    szi_current: float,
    szi_previous: Optional[float],
    epsilon: float
) -> WalletState:
    """
    Classify wallet into behavioral state based on position change.

    Classification Rules:
        - Adder (Long):  Δszi > ε AND szi_current > 0
        - Adder (Short): Δszi < −ε AND szi_current < 0
        - Reducer:       |szi_current| < |szi_previous| − ε
        - Flat:          All other cases

    Args:
        szi_current: Current position size (signed)
        szi_previous: Position size 5 minutes ago (signed), or None if missing
        epsilon: Noise threshold

    Returns:
        WalletState classification
    """
    # If no previous data, classify as Flat
    if szi_previous is None:
        return WalletState.FLAT

    # Calculate delta
    delta_szi = szi_current - szi_previous

    # Check for Adder (Long)
    if delta_szi > epsilon and szi_current > 0:
        return WalletState.ADDER_LONG

    # Check for Adder (Short)
    if delta_szi < -epsilon and szi_current < 0:
        return WalletState.ADDER_SHORT

    # Check for Reducer (absolute size decreased)
    if abs(szi_current) < abs(szi_previous) - epsilon:
        return WalletState.REDUCER

    # Default: Flat
    return WalletState.FLAT


def classify_wallets(
    wallet_deltas: Dict[str, Dict],
    asset: str
) -> Dict[str, Dict]:
    """
    Classify all wallets into behavioral states.

    Args:
        wallet_deltas: Dict[wallet_id -> {szi_current, szi_previous, delta_szi, ...}]
        asset: Asset symbol

    Returns:
        Dict[wallet_id -> {
            'state': WalletState,
            'szi_current': float,
            'szi_previous': float,
            'delta_szi': float,
            'epsilon': float
        }]
    """
    classifications = {}

    for wallet_id, delta_info in wallet_deltas.items():
        szi_current = delta_info['szi_current']
        szi_previous = delta_info['szi_previous']
        delta_szi = delta_info['delta_szi']

        # Skip if delta is None (missing previous data)
        if delta_szi is None:
            continue

        # Calculate epsilon for this wallet
        epsilon = calculate_epsilon(wallet_id, asset)

        # Classify
        state = classify_wallet(szi_current, szi_previous, epsilon)

        classifications[wallet_id] = {
            'state': state,
            'szi_current': szi_current,
            'szi_previous': szi_previous,
            'delta_szi': delta_szi,
            'epsilon': epsilon
        }

    return classifications


def aggregate_classifications(
    classifications: Dict[str, Dict]
) -> Dict[str, int]:
    """
    Count wallets in each state.

    Args:
        classifications: Output from classify_wallets()

    Returns:
        Dictionary with counts for each state:
        {
            'n_adder_long': int,
            'n_adder_short': int,
            'n_reducer': int,
            'n_flat': int,
            'n_total': int
        }
    """
    counts = {
        'n_adder_long': 0,
        'n_adder_short': 0,
        'n_reducer': 0,
        'n_flat': 0
    }

    for wallet_data in classifications.values():
        state = wallet_data['state']

        if state == WalletState.ADDER_LONG:
            counts['n_adder_long'] += 1
        elif state == WalletState.ADDER_SHORT:
            counts['n_adder_short'] += 1
        elif state == WalletState.REDUCER:
            counts['n_reducer'] += 1
        elif state == WalletState.FLAT:
            counts['n_flat'] += 1

    counts['n_total'] = len(classifications)

    return counts


def get_wallet_percentages(counts: Dict[str, int]) -> Dict[str, float]:
    """
    Convert counts to percentages.

    Args:
        counts: Output from aggregate_classifications()

    Returns:
        Dictionary with percentages:
        {
            'pct_add_long': float (0-100),
            'pct_add_short': float (0-100),
            'pct_reducers': float (0-100),
            'pct_flat': float (0-100)
        }
    """
    n_total = counts['n_total']

    if n_total == 0:
        return {
            'pct_add_long': 0.0,
            'pct_add_short': 0.0,
            'pct_reducers': 0.0,
            'pct_flat': 0.0
        }

    return {
        'pct_add_long': (counts['n_adder_long'] / n_total) * 100,
        'pct_add_short': (counts['n_adder_short'] / n_total) * 100,
        'pct_reducers': (counts['n_reducer'] / n_total) * 100,
        'pct_flat': (counts['n_flat'] / n_total) * 100
    }
