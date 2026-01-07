"""Universe refresh logic for tracking top wallets."""

import logging
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple

from src.config import settings
from src.db import db
from src.ingest.hyperliquid_client import HyperliquidClient, parse_leaderboard_row

logger = logging.getLogger(__name__)


class UniverseRefresher:
    """Manages the wallet universe refresh process."""

    def __init__(self):
        """Initialize the universe refresher."""
        self.client = HyperliquidClient()
        self.universe_size = settings.universe_size

    async def refresh_universe(self) -> Dict:
        """
        Refresh the wallet universe from Hyperliquid leaderboard.

        Returns:
            Dictionary with refresh run metadata

        Process:
            1. Fetch leaderboard data
            2. Parse and rank top N wallets by 30D PnL
            3. Compare with previous universe (calculate diffs)
            4. Persist new universe and run metadata
        """
        start_time = datetime.now(timezone.utc)
        as_of_ts = start_time
        run_metadata = {
            "as_of_ts": as_of_ts,
            "status": "failed",
            "source": "unknown",
            "n_requested": self.universe_size,
            "n_received": 0,
            "entered_count": 0,
            "exited_count": 0,
            "duration_ms": 0,
            "error": None
        }

        try:
            # Fetch leaderboard
            logger.info("Fetching leaderboard data...")
            leaderboard_rows = await self.client.fetch_leaderboard()

            # Determine source (primary vs fallback)
            # This is simplified - in production, track which endpoint succeeded
            run_metadata["source"] = "stats-data"

            # Parse and filter valid rows
            logger.info(f"Parsing {len(leaderboard_rows)} leaderboard rows...")
            parsed_wallets = []
            for row in leaderboard_rows:
                parsed = parse_leaderboard_row(row)
                if parsed:
                    parsed_wallets.append(parsed)

            # Sort by month_pnl descending and take top N
            parsed_wallets.sort(key=lambda w: w["month_pnl"], reverse=True)
            top_wallets = parsed_wallets[:self.universe_size]

            run_metadata["n_received"] = len(top_wallets)

            # Validate: require at least 90% of requested wallets
            min_required = int(self.universe_size * 0.9)
            if len(top_wallets) < min_required:
                error_msg = (
                    f"Insufficient valid wallets: {len(top_wallets)} < {min_required}. "
                    "Keeping existing universe."
                )
                logger.error(error_msg)
                run_metadata["error"] = error_msg

                # Record failed run but don't update universe
                duration_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
                run_metadata["duration_ms"] = duration_ms
                self._persist_run_metadata(run_metadata)

                return run_metadata

            # Get previous universe for diff calculation
            previous_universe = self._get_current_universe()
            previous_wallet_ids = set(w["wallet_id"] for w in previous_universe)
            new_wallet_ids = set(w["wallet_id"] for w in top_wallets)

            # Calculate diffs
            entered = new_wallet_ids - previous_wallet_ids
            exited = previous_wallet_ids - new_wallet_ids

            run_metadata["entered_count"] = len(entered)
            run_metadata["exited_count"] = len(exited)

            logger.info(
                f"Universe diff: {len(entered)} entered, {len(exited)} exited "
                f"(out of {len(top_wallets)} total)"
            )

            # Persist the new universe
            run_id = self._persist_universe(top_wallets, run_metadata)

            # Mark success
            run_metadata["status"] = "success"
            duration_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
            run_metadata["duration_ms"] = duration_ms

            logger.info(
                f"Universe refresh completed successfully in {duration_ms}ms. "
                f"Run ID: {run_id}"
            )

            return run_metadata

        except Exception as e:
            error_msg = f"Universe refresh failed: {str(e)}"
            logger.error(error_msg, exc_info=True)

            run_metadata["error"] = error_msg
            duration_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
            run_metadata["duration_ms"] = duration_ms

            # Record failed run
            self._persist_run_metadata(run_metadata)

            return run_metadata

    def _get_current_universe(self) -> List[Dict]:
        """
        Fetch the current wallet universe from the database.

        Returns:
            List of wallet dictionaries from wallet_universe_current
        """
        query = """
            SELECT wallet_id, rank, month_pnl, month_roi, account_value
            FROM wallet_universe_current
            ORDER BY rank
        """

        with db.get_cursor() as cur:
            cur.execute(query)
            return cur.fetchall()

    def _persist_universe(self, wallets: List[Dict], run_metadata: Dict) -> int:
        """
        Persist the new universe to the database.

        Args:
            wallets: List of wallet dictionaries (already ranked)
            run_metadata: Run metadata

        Returns:
            run_id of the created run

        Persists to:
            - wallet_universe_runs (run metadata)
            - wallet_universe_members (historical membership)
            - wallet_universe_current (active universe, replace)
        """
        with db.get_cursor() as cur:
            # 1. Insert run metadata
            cur.execute(
                """
                INSERT INTO wallet_universe_runs (
                    as_of_ts, status, source,
                    n_requested, n_received,
                    entered_count, exited_count,
                    duration_ms, error
                )
                VALUES (
                    %(as_of_ts)s, %(status)s, %(source)s,
                    %(n_requested)s, %(n_received)s,
                    %(entered_count)s, %(exited_count)s,
                    %(duration_ms)s, %(error)s
                )
                RETURNING run_id
                """,
                run_metadata
            )
            run_id = cur.fetchone()["run_id"]

            # 2. Insert universe members
            for rank, wallet in enumerate(wallets, start=1):
                cur.execute(
                    """
                    INSERT INTO wallet_universe_members (
                        run_id, wallet_id, rank,
                        month_pnl, month_roi, account_value
                    )
                    VALUES (
                        %(run_id)s, %(wallet_id)s, %(rank)s,
                        %(month_pnl)s, %(month_roi)s, %(account_value)s
                    )
                    """,
                    {
                        "run_id": run_id,
                        "wallet_id": wallet["wallet_id"],
                        "rank": rank,
                        "month_pnl": wallet["month_pnl"],
                        "month_roi": wallet["month_roi"],
                        "account_value": wallet["account_value"]
                    }
                )

            # 3. Replace current universe (delete + insert)
            cur.execute("DELETE FROM wallet_universe_current")

            for rank, wallet in enumerate(wallets, start=1):
                cur.execute(
                    """
                    INSERT INTO wallet_universe_current (
                        wallet_id, rank,
                        month_pnl, month_roi, account_value,
                        as_of_ts
                    )
                    VALUES (
                        %(wallet_id)s, %(rank)s,
                        %(month_pnl)s, %(month_roi)s, %(account_value)s,
                        %(as_of_ts)s
                    )
                    """,
                    {
                        "wallet_id": wallet["wallet_id"],
                        "rank": rank,
                        "month_pnl": wallet["month_pnl"],
                        "month_roi": wallet["month_roi"],
                        "account_value": wallet["account_value"],
                        "as_of_ts": run_metadata["as_of_ts"]
                    }
                )

        return run_id

    def _persist_run_metadata(self, run_metadata: Dict):
        """
        Persist only the run metadata (for failed runs).

        Args:
            run_metadata: Run metadata dictionary
        """
        with db.get_cursor() as cur:
            cur.execute(
                """
                INSERT INTO wallet_universe_runs (
                    as_of_ts, status, source,
                    n_requested, n_received,
                    entered_count, exited_count,
                    duration_ms, error
                )
                VALUES (
                    %(as_of_ts)s, %(status)s, %(source)s,
                    %(n_requested)s, %(n_received)s,
                    %(entered_count)s, %(exited_count)s,
                    %(duration_ms)s, %(error)s
                )
                """,
                run_metadata
            )
