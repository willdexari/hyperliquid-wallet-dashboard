"""Main ingestion runner for Hyperliquid wallet data.

This module orchestrates:
1. Universe refresh (every 6 hours)
2. Snapshot ingestion (every 60 seconds)

Run with:
    python -m src.ingest.fetch
"""

import asyncio
import logging
import sys
from datetime import datetime, timezone, timedelta
from typing import Optional

from src.config import settings
from src.db import db, execute_schema
from src.ingest.universe import UniverseRefresher
from src.ingest.snapshots import SnapshotIngester, get_snapshot_timestamp

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


class IngestionRunner:
    """Orchestrates universe refresh and snapshot ingestion."""

    def __init__(self):
        """Initialize the ingestion runner."""
        self.universe_refresher = UniverseRefresher()
        self.snapshot_ingester = SnapshotIngester()
        self.last_universe_refresh: Optional[datetime] = None
        self.running = False

    async def initialize(self):
        """Initialize the database connection and schema."""
        logger.info("Initializing database connection...")
        db.initialize()

        logger.info("Ensuring database schema is up to date...")
        try:
            execute_schema()
        except Exception as e:
            logger.warning(f"Schema execution had issues (may be normal): {e}")

        logger.info("Initialization complete")

    async def should_refresh_universe(self) -> bool:
        """
        Check if universe refresh is needed.

        Returns:
            True if refresh is needed

        Criteria:
            - First run (last_universe_refresh is None)
            - More than UNIVERSE_REFRESH_HOURS hours since last refresh
        """
        if self.last_universe_refresh is None:
            return True

        hours_since_refresh = (
            datetime.now(timezone.utc) - self.last_universe_refresh
        ).total_seconds() / 3600

        return hours_since_refresh >= settings.universe_refresh_hours

    async def run_universe_refresh(self):
        """Run the universe refresh process."""
        try:
            logger.info("=" * 60)
            logger.info("UNIVERSE REFRESH STARTING")
            logger.info("=" * 60)

            result = await self.universe_refresher.refresh_universe()

            if result["status"] == "success":
                self.last_universe_refresh = datetime.now(timezone.utc)
                logger.info(f"Universe refresh successful: {result['n_received']} wallets")
            else:
                logger.error(f"Universe refresh failed: {result.get('error', 'Unknown error')}")

            logger.info("=" * 60)

        except Exception as e:
            logger.error(f"Universe refresh exception: {e}", exc_info=True)

    async def run_snapshot_ingestion(self):
        """Run the snapshot ingestion process."""
        try:
            result = await self.snapshot_ingester.ingest_snapshot()

            status_icon = {
                "success": "✓",
                "partial": "⚠",
                "failed": "✗"
            }.get(result["status"], "?")

            logger.info(
                f"{status_icon} Snapshot {result['snapshot_ts']}: "
                f"{result['status']} | "
                f"coverage={result['coverage_pct']:.1f}% | "
                f"rows={result['rows_written']} | "
                f"time={result['duration_ms']}ms"
            )

        except Exception as e:
            logger.error(f"Snapshot ingestion exception: {e}", exc_info=True)

    async def wait_until_next_minute(self):
        """
        Wait until the start of the next minute boundary.

        This ensures snapshots are aligned to 60-second boundaries.
        """
        now = datetime.now(timezone.utc)
        next_minute = (now + timedelta(minutes=1)).replace(second=0, microsecond=0)
        wait_seconds = (next_minute - now).total_seconds()

        if wait_seconds > 0:
            logger.info(f"Waiting {wait_seconds:.1f}s until next minute boundary...")
            await asyncio.sleep(wait_seconds)

    async def run_forever(self):
        """
        Run the ingestion loop forever.

        Process:
            1. Initialize database
            2. Refresh universe (if needed)
            3. Wait until next minute boundary
            4. Ingest snapshot
            5. Repeat from step 2
        """
        await self.initialize()

        # Initial universe refresh
        await self.run_universe_refresh()

        logger.info("")
        logger.info("=" * 60)
        logger.info("STARTING SNAPSHOT INGESTION LOOP")
        logger.info(f"Snapshot interval: {settings.snapshot_interval_sec}s")
        logger.info(f"Universe refresh interval: {settings.universe_refresh_hours}h")
        logger.info("=" * 60)
        logger.info("")

        self.running = True

        try:
            while self.running:
                # Check if universe refresh is needed
                if await self.should_refresh_universe():
                    await self.run_universe_refresh()

                # Wait until next minute boundary
                await self.wait_until_next_minute()

                # Run snapshot ingestion
                await self.run_snapshot_ingestion()

        except KeyboardInterrupt:
            logger.info("Received shutdown signal")
            self.running = False
        finally:
            logger.info("Shutting down...")
            db.close()
            logger.info("Shutdown complete")

    async def run_once(self, refresh_universe: bool = False):
        """
        Run a single ingestion cycle (for testing).

        Args:
            refresh_universe: Whether to refresh universe before snapshot
        """
        await self.initialize()

        if refresh_universe:
            await self.run_universe_refresh()

        await self.run_snapshot_ingestion()

        db.close()


async def main():
    """Main entry point."""
    runner = IngestionRunner()

    # Check if running in test mode
    if len(sys.argv) > 1 and sys.argv[1] == "--once":
        logger.info("Running in single-shot mode")
        refresh_universe = "--refresh-universe" in sys.argv
        await runner.run_once(refresh_universe=refresh_universe)
    else:
        logger.info("Running in continuous mode (use --once for single run)")
        await runner.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
