"""Main signal computation runner.

Run with:
    python -m src.signals.runner
"""

import asyncio
import logging
import sys
from datetime import datetime, timezone, timedelta
from typing import Optional

from src.config import settings
from src.db import db, execute_schema
from src.signals.aggregator import (
    get_signal_timestamp,
    aggregate_for_signal_period,
    check_signal_lock
)
from src.signals.classifier import (
    classify_wallets,
    aggregate_classifications,
    get_wallet_percentages
)
from src.signals.core import compute_all_signals
from src.signals.playbook import apply_playbook_logic
from src.signals.persistence import persist_signal, persist_contributors
from src.alerts.evaluator import evaluate_all_alerts, evaluate_system_alerts

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


class SignalRunner:
    """Orchestrates 5-minute signal computation."""

    def __init__(self):
        """Initialize the signal runner."""
        self.assets = settings.assets
        self.running = False

    async def initialize(self):
        """Initialize the database connection."""
        logger.info("Initializing database connection...")
        db.initialize()
        logger.info("Initialization complete")

    async def compute_signal_for_asset(
        self,
        signal_ts: datetime,
        asset: str
    ) -> Optional[dict]:
        """
        Compute signals for a single asset.

        Args:
            signal_ts: Signal timestamp (5-minute boundary)
            asset: Asset symbol

        Returns:
            Dictionary with signal results or None if computation failed
        """
        start_time = datetime.now(timezone.utc)

        try:
            logger.info(f"=" * 60)
            logger.info(f"Computing signals for {asset} at {signal_ts}")
            logger.info(f"=" * 60)

            # 1. Aggregate snapshots
            wallet_deltas, wallet_count, missing_count = aggregate_for_signal_period(
                signal_ts, asset
            )

            # Check for graceful degradation
            total_expected = 200  # Universe size
            coverage_pct = (wallet_count / total_expected * 100) if total_expected > 0 else 0

            if coverage_pct < 90:
                logger.warning(
                    f"{asset}: Low coverage ({coverage_pct:.1f}%) - forcing conservative signals"
                )
                # TODO: Force conservative signals (CAS=50, No-trade, Defensive)
                # For now, continue with available data

            # 2. Classify wallets
            classifications = classify_wallets(wallet_deltas, asset)
            counts = aggregate_classifications(classifications)
            percentages = get_wallet_percentages(counts)

            logger.info(
                f"{asset} wallet states: "
                f"Add Long={counts['n_adder_long']} ({percentages['pct_add_long']:.1f}%), "
                f"Add Short={counts['n_adder_short']} ({percentages['pct_add_short']:.1f}%), "
                f"Reducers={counts['n_reducer']} ({percentages['pct_reducers']:.1f}%), "
                f"Flat={counts['n_flat']} ({percentages['pct_flat']:.1f}%)"
            )

            # 3. Compute core signals
            core_signals = compute_all_signals(counts, classifications, asset)

            logger.info(
                f"{asset} signals: "
                f"CAS={core_signals['alignment_score']:.1f}, "
                f"Trend={core_signals['alignment_trend']}, "
                f"Di={core_signals['dispersion_index']:.1f}, "
                f"EC={core_signals['exit_cluster_score']:.1f}"
            )

            # 4. Apply playbook logic
            full_signals = apply_playbook_logic(core_signals)

            logger.info(
                f"{asset} playbook: "
                f"{full_signals['allowed_playbook']} / {full_signals['risk_mode']} "
                f"(add_exposure={full_signals['add_exposure']}, "
                f"tighten_stops={full_signals['tighten_stops']})"
            )

            # 5. Calculate computation duration
            duration_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)

            # 6. Persist signals
            persist_signal(signal_ts, asset, full_signals, counts, missing_count, duration_ms)

            # Only persist contributors if N_total > 0 (avoids check constraint violation)
            if counts['n_total'] > 0:
                persist_contributors(signal_ts, asset, counts, percentages)
            else:
                logger.debug(f"{asset}: Skipping contributor persistence (N_total=0)")

            logger.info(f"{asset}: Signal computation completed in {duration_ms}ms")

            return {
                'asset': asset,
                'signals': full_signals,
                'counts': counts,
                'percentages': percentages,
                'wallet_count': wallet_count,
                'missing_count': missing_count,
                'duration_ms': duration_ms
            }

        except Exception as e:
            logger.error(f"Signal computation failed for {asset}: {e}", exc_info=True)
            return None

    async def run_signal_computation(self):
        """Run signal computation for all assets."""
        signal_ts = get_signal_timestamp()

        logger.info("")
        logger.info("=" * 60)
        logger.info(f"SIGNAL COMPUTATION CYCLE: {signal_ts}")
        logger.info("=" * 60)

        # Check Signal Lock
        if not check_signal_lock():
            logger.warning("Signal Lock engaged - skipping computation")
            return

        # Compute signals for each asset
        results = []
        for asset in self.assets:
            result = await self.compute_signal_for_asset(signal_ts, asset)
            if result:
                results.append(result)

        # Summary
        logger.info("")
        logger.info("=" * 60)
        logger.info(f"SIGNAL COMPUTATION COMPLETE: {len(results)}/{len(self.assets)} assets")
        logger.info("=" * 60)

        for result in results:
            logger.info(
                f"{result['asset']:4s}: {result['signals']['allowed_playbook']:10s} / "
                f"{result['signals']['risk_mode']:10s} | "
                f"CAS={result['signals']['alignment_score']:5.1f} | "
                f"{result['duration_ms']:4d}ms"
            )

        logger.info("")

        # Evaluate alerts after signal computation
        logger.info("=" * 60)
        logger.info("ALERT EVALUATION")
        logger.info("=" * 60)

        # Build signals_by_asset dictionary for behavioral alerts
        signals_by_asset = {
            result['asset']: result['signals']
            for result in results
        }

        # Evaluate all alerts (system + behavioral)
        alert_results = evaluate_all_alerts(signal_ts, self.assets, signals_by_asset)

        # Summary of alerts
        total_alerts = sum(len(alerts) for alerts in alert_results.values())
        if total_alerts > 0:
            logger.info("")
            logger.info(f"ALERTS FIRED: {total_alerts} total")
            for asset, alerts in alert_results.items():
                logger.info(f"  {asset}: {', '.join(alerts)}")
        else:
            logger.info("No alerts fired")

        logger.info("")

    async def wait_until_next_5minute(self):
        """
        Wait until the start of the next 5-minute boundary.

        This ensures signals are aligned to 5-minute boundaries.
        """
        now = datetime.now(timezone.utc)
        # Calculate next 5-minute boundary
        minutes_to_next = 5 - (now.minute % 5)
        next_boundary = (now + timedelta(minutes=minutes_to_next)).replace(second=0, microsecond=0)

        wait_seconds = (next_boundary - now).total_seconds()

        if wait_seconds > 0:
            logger.info(f"Waiting {wait_seconds:.1f}s until next 5-minute boundary...")
            await asyncio.sleep(wait_seconds)

    async def run_forever(self):
        """
        Run the signal computation loop forever.

        Process:
            1. Initialize database
            2. Wait until next 5-minute boundary
            3. Compute signals
            4. Repeat from step 2
        """
        await self.initialize()

        logger.info("")
        logger.info("=" * 60)
        logger.info("STARTING SIGNAL COMPUTATION LOOP")
        logger.info(f"Signal interval: {settings.signal_interval_sec}s (5 minutes)")
        logger.info(f"Assets: {', '.join(self.assets)}")
        logger.info("=" * 60)
        logger.info("")

        self.running = True

        try:
            while self.running:
                # Wait until next 5-minute boundary
                await self.wait_until_next_5minute()

                # Run signal computation
                await self.run_signal_computation()

        except KeyboardInterrupt:
            logger.info("Received shutdown signal")
            self.running = False
        finally:
            logger.info("Shutting down...")
            db.close()
            logger.info("Shutdown complete")

    async def run_once(self):
        """
        Run a single signal computation cycle (for testing).
        """
        await self.initialize()
        await self.run_signal_computation()
        db.close()


async def main():
    """Main entry point."""
    runner = SignalRunner()

    # Check if running in test mode
    if len(sys.argv) > 1 and sys.argv[1] == "--once":
        logger.info("Running in single-shot mode")
        await runner.run_once()
    else:
        logger.info("Running in continuous mode (use --once for single run)")
        await runner.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
