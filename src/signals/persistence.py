"""Signal persistence to database."""

import logging
from datetime import datetime
from typing import Dict

from src.db import db

logger = logging.getLogger(__name__)


def persist_signal(
    signal_ts: datetime,
    asset: str,
    signals: Dict,
    counts: Dict,
    missing_count: int,
    computation_ms: int
) -> int:
    """
    Persist signal to database.

    Args:
        signal_ts: Signal timestamp (5-minute boundary)
        asset: Asset symbol
        signals: Dictionary with all signal values
        counts: Wallet state counts
        missing_count: Number of wallets without valid data
        computation_ms: Signal computation duration

    Returns:
        Number of rows affected (should be 1)
    """
    query = """
        INSERT INTO signals (
            signal_ts,
            asset,
            alignment_score,
            alignment_trend,
            dispersion_index,
            exit_cluster_score,
            allowed_playbook,
            risk_mode,
            add_exposure,
            tighten_stops,
            wallet_count,
            missing_count,
            computation_ms
        ) VALUES (
            %(signal_ts)s,
            %(asset)s,
            %(alignment_score)s,
            %(alignment_trend)s,
            %(dispersion_index)s,
            %(exit_cluster_score)s,
            %(allowed_playbook)s,
            %(risk_mode)s,
            %(add_exposure)s,
            %(tighten_stops)s,
            %(wallet_count)s,
            %(missing_count)s,
            %(computation_ms)s
        )
        ON CONFLICT (signal_ts, asset)
        DO UPDATE SET
            alignment_score = EXCLUDED.alignment_score,
            alignment_trend = EXCLUDED.alignment_trend,
            dispersion_index = EXCLUDED.dispersion_index,
            exit_cluster_score = EXCLUDED.exit_cluster_score,
            allowed_playbook = EXCLUDED.allowed_playbook,
            risk_mode = EXCLUDED.risk_mode,
            add_exposure = EXCLUDED.add_exposure,
            tighten_stops = EXCLUDED.tighten_stops,
            wallet_count = EXCLUDED.wallet_count,
            missing_count = EXCLUDED.missing_count,
            computation_ms = EXCLUDED.computation_ms,
            created_at = NOW()
    """

    params = {
        'signal_ts': signal_ts,
        'asset': asset,
        'alignment_score': signals['alignment_score'],
        'alignment_trend': signals['alignment_trend'],
        'dispersion_index': signals['dispersion_index'],
        'exit_cluster_score': signals['exit_cluster_score'],
        'allowed_playbook': signals['allowed_playbook'],
        'risk_mode': signals['risk_mode'],
        'add_exposure': signals['add_exposure'],
        'tighten_stops': signals['tighten_stops'],
        'wallet_count': counts['n_total'],
        'missing_count': missing_count,
        'computation_ms': computation_ms
    }

    with db.get_cursor() as cur:
        cur.execute(query, params)
        affected = cur.rowcount

    logger.info(
        f"Persisted signal for {asset}: "
        f"playbook={signals['allowed_playbook']}, "
        f"risk={signals['risk_mode']}, "
        f"CAS={signals['alignment_score']:.1f}"
    )

    return affected


def persist_contributors(
    signal_ts: datetime,
    asset: str,
    counts: Dict,
    percentages: Dict
) -> int:
    """
    Persist signal contributors (wallet behavior breakdown).

    Args:
        signal_ts: Signal timestamp
        asset: Asset symbol
        counts: Wallet state counts
        percentages: Wallet state percentages

    Returns:
        Number of rows affected (should be 1)
    """
    query = """
        INSERT INTO signal_contributors (
            signal_ts,
            asset,
            pct_add_long,
            pct_add_short,
            pct_reducers,
            pct_flat,
            count_add_long,
            count_add_short,
            count_reducers,
            count_flat,
            total_wallets
        ) VALUES (
            %(signal_ts)s,
            %(asset)s,
            %(pct_add_long)s,
            %(pct_add_short)s,
            %(pct_reducers)s,
            %(pct_flat)s,
            %(count_add_long)s,
            %(count_add_short)s,
            %(count_reducers)s,
            %(count_flat)s,
            %(total_wallets)s
        )
        ON CONFLICT (signal_ts, asset)
        DO UPDATE SET
            pct_add_long = EXCLUDED.pct_add_long,
            pct_add_short = EXCLUDED.pct_add_short,
            pct_reducers = EXCLUDED.pct_reducers,
            pct_flat = EXCLUDED.pct_flat,
            count_add_long = EXCLUDED.count_add_long,
            count_add_short = EXCLUDED.count_add_short,
            count_reducers = EXCLUDED.count_reducers,
            count_flat = EXCLUDED.count_flat,
            total_wallets = EXCLUDED.total_wallets,
            created_at = NOW()
    """

    params = {
        'signal_ts': signal_ts,
        'asset': asset,
        'pct_add_long': percentages['pct_add_long'],
        'pct_add_short': percentages['pct_add_short'],
        'pct_reducers': percentages['pct_reducers'],
        'pct_flat': percentages['pct_flat'],
        'count_add_long': counts['n_adder_long'],
        'count_add_short': counts['n_adder_short'],
        'count_reducers': counts['n_reducer'],
        'count_flat': counts['n_flat'],
        'total_wallets': counts['n_total']
    }

    with db.get_cursor() as cur:
        cur.execute(query, params)
        affected = cur.rowcount

    logger.debug(
        f"Persisted contributors for {asset}: "
        f"long={percentages['pct_add_long']:.1f}%, "
        f"short={percentages['pct_add_short']:.1f}%, "
        f"reducers={percentages['pct_reducers']:.1f}%, "
        f"flat={percentages['pct_flat']:.1f}%"
    )

    return affected
