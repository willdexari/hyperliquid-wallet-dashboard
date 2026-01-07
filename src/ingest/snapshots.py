"""Snapshot ingestion logic for wallet positions."""

import logging
from datetime import datetime, timezone
from typing import List, Dict, Optional

from src.config import settings
from src.db import db
from src.ingest.hyperliquid_client import HyperliquidClient, parse_position_data

logger = logging.getLogger(__name__)


def get_snapshot_timestamp() -> datetime:
    """
    Return current UTC time floored to 60s boundary.

    Returns:
        Datetime floored to the nearest minute
    """
    now = datetime.now(timezone.utc)
    return now.replace(second=0, microsecond=0)


class SnapshotIngester:
    """Manages the 60-second snapshot ingestion process."""

    def __init__(self):
        """Initialize the snapshot ingester."""
        self.client = HyperliquidClient()
        self.assets = settings.assets

    async def ingest_snapshot(self) -> Dict:
        """
        Ingest a single snapshot for all tracked wallets and assets.

        Returns:
            Dictionary with ingestion run metadata

        Process:
            1. Get current universe of wallets
            2. Fetch positions for all wallets (with concurrency control)
            3. Extract position data for each asset (HYPE, BTC, ETH)
            4. Write snapshot rows (upsert for idempotency)
            5. Record run metadata and health state
        """
        start_time = datetime.now(timezone.utc)
        snapshot_ts = get_snapshot_timestamp()

        logger.info(f"Starting snapshot ingestion for {snapshot_ts}")

        # Initialize run metadata
        run_metadata = {
            "snapshot_ts": snapshot_ts,
            "status": "failed",
            "wallets_expected": 0,
            "wallets_succeeded": 0,
            "wallets_failed": 0,
            "rows_expected": 0,
            "rows_written": 0,
            "coverage_pct": 0.0,
            "duration_ms": 0,
            "error": None
        }

        try:
            # 1. Get current universe
            wallets = self._get_current_universe()
            wallet_count = len(wallets)
            wallet_addresses = [w["wallet_id"] for w in wallets]

            run_metadata["wallets_expected"] = wallet_count
            run_metadata["rows_expected"] = wallet_count * len(self.assets)

            if wallet_count == 0:
                error_msg = "No wallets in universe"
                logger.warning(error_msg)
                run_metadata["error"] = error_msg
                run_metadata["status"] = "failed"

                duration_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
                run_metadata["duration_ms"] = duration_ms

                run_id = self._persist_run_metadata(run_metadata)
                self._update_health_state(run_metadata, run_id)

                return run_metadata

            # 2. Fetch positions for all wallets
            logger.info(f"Fetching positions for {wallet_count} wallets...")
            wallet_positions = await self.client.fetch_multiple_wallets(wallet_addresses)

            # Count successes and failures
            wallets_succeeded = sum(1 for data in wallet_positions.values() if data is not None)
            wallets_failed = wallet_count - wallets_succeeded

            run_metadata["wallets_succeeded"] = wallets_succeeded
            run_metadata["wallets_failed"] = wallets_failed
            run_metadata["coverage_pct"] = (wallets_succeeded / wallet_count * 100) if wallet_count > 0 else 0

            logger.info(
                f"Wallet fetch complete: {wallets_succeeded} succeeded, "
                f"{wallets_failed} failed ({run_metadata['coverage_pct']:.1f}% coverage)"
            )

            # 3. Extract and write snapshot rows
            rows_written = 0

            with db.get_cursor() as cur:
                for wallet_id, position_data in wallet_positions.items():
                    for asset in self.assets:
                        # Parse position for this asset
                        if position_data is None:
                            # Wallet fetch failed - skip this wallet entirely
                            continue

                        position = parse_position_data(position_data, asset)

                        # Upsert snapshot row
                        cur.execute(
                            """
                            INSERT INTO wallet_snapshots (
                                snapshot_ts, wallet_id, asset,
                                position_szi, entry_px, liq_px,
                                leverage, margin_used
                            )
                            VALUES (
                                %(snapshot_ts)s, %(wallet_id)s, %(asset)s,
                                %(position_szi)s, %(entry_px)s, %(liq_px)s,
                                %(leverage)s, %(margin_used)s
                            )
                            ON CONFLICT (snapshot_ts, wallet_id, asset)
                            DO UPDATE SET
                                position_szi = EXCLUDED.position_szi,
                                entry_px = EXCLUDED.entry_px,
                                liq_px = EXCLUDED.liq_px,
                                leverage = EXCLUDED.leverage,
                                margin_used = EXCLUDED.margin_used,
                                created_at = NOW()
                            """,
                            {
                                "snapshot_ts": snapshot_ts,
                                "wallet_id": wallet_id,
                                "asset": asset,
                                "position_szi": position["position_szi"],
                                "entry_px": position["entry_px"],
                                "liq_px": position["liq_px"],
                                "leverage": position["leverage"],
                                "margin_used": position["margin_used"]
                            }
                        )
                        rows_written += 1

            run_metadata["rows_written"] = rows_written

            # 4. Determine status
            if run_metadata["coverage_pct"] >= 95:
                run_metadata["status"] = "success"
            elif run_metadata["coverage_pct"] >= 5:
                run_metadata["status"] = "partial"
            else:
                run_metadata["status"] = "failed"
                run_metadata["error"] = f"Coverage too low: {run_metadata['coverage_pct']:.1f}%"

            duration_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
            run_metadata["duration_ms"] = duration_ms

            # 5. Persist run metadata and update health
            run_id = self._persist_run_metadata(run_metadata)
            self._update_health_state(run_metadata, run_id)

            logger.info(
                f"Snapshot ingestion completed: status={run_metadata['status']}, "
                f"rows={rows_written}, duration={duration_ms}ms"
            )

            return run_metadata

        except Exception as e:
            error_msg = f"Snapshot ingestion failed: {str(e)}"
            logger.error(error_msg, exc_info=True)

            run_metadata["error"] = error_msg
            run_metadata["status"] = "failed"
            duration_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
            run_metadata["duration_ms"] = duration_ms

            # Record failed run
            run_id = self._persist_run_metadata(run_metadata)
            self._update_health_state(run_metadata, run_id)

            return run_metadata

    def _get_current_universe(self) -> List[Dict]:
        """
        Fetch the current wallet universe from the database.

        Returns:
            List of wallet dictionaries
        """
        query = """
            SELECT wallet_id, rank
            FROM wallet_universe_current
            ORDER BY rank
        """

        with db.get_cursor() as cur:
            cur.execute(query)
            return cur.fetchall()

    def _persist_run_metadata(self, run_metadata: Dict) -> int:
        """
        Persist ingestion run metadata.

        Args:
            run_metadata: Run metadata dictionary

        Returns:
            run_id of the created run
        """
        with db.get_cursor() as cur:
            cur.execute(
                """
                INSERT INTO ingest_runs (
                    snapshot_ts, status,
                    wallets_expected, wallets_succeeded, wallets_failed,
                    rows_expected, rows_written,
                    coverage_pct,
                    duration_ms, error
                )
                VALUES (
                    %(snapshot_ts)s, %(status)s,
                    %(wallets_expected)s, %(wallets_succeeded)s, %(wallets_failed)s,
                    %(rows_expected)s, %(rows_written)s,
                    %(coverage_pct)s,
                    %(duration_ms)s, %(error)s
                )
                ON CONFLICT (snapshot_ts)
                DO UPDATE SET
                    status = EXCLUDED.status,
                    wallets_succeeded = EXCLUDED.wallets_succeeded,
                    wallets_failed = EXCLUDED.wallets_failed,
                    rows_written = EXCLUDED.rows_written,
                    coverage_pct = EXCLUDED.coverage_pct,
                    duration_ms = EXCLUDED.duration_ms,
                    error = EXCLUDED.error
                RETURNING run_id
                """,
                run_metadata
            )
            result = cur.fetchone()
            return result["run_id"]

    def _update_health_state(self, run_metadata: Dict, run_id: int):
        """
        Update the ingest_health table based on run results.

        Args:
            run_metadata: Run metadata dictionary
            run_id: The run ID

        Health state logic:
            - healthy: status=success, coverage>=95%
            - degraded: status=partial, coverage>=80%
            - stale: last success >3 minutes ago OR status=failed
        """
        snapshot_ts = run_metadata["snapshot_ts"]
        status = run_metadata["status"]
        coverage_pct = run_metadata["coverage_pct"]
        error = run_metadata["error"]

        # Get last successful snapshot
        with db.get_cursor() as cur:
            cur.execute(
                """
                SELECT snapshot_ts
                FROM ingest_runs
                WHERE status = 'success'
                ORDER BY snapshot_ts DESC
                LIMIT 1
                """
            )
            result = cur.fetchone()
            last_success_ts = result["snapshot_ts"] if result else snapshot_ts

            # Determine health state
            if status == "success":
                health_state = "healthy"
            elif status == "partial" and coverage_pct >= 80:
                health_state = "degraded"
            else:
                health_state = "stale"

            # Also check time since last success
            time_since_success = (datetime.now(timezone.utc) - last_success_ts).total_seconds() / 60
            if time_since_success > settings.stale_threshold_minutes:
                health_state = "stale"

            # Upsert health state
            cur.execute(
                """
                INSERT INTO ingest_health (
                    health_ts,
                    last_success_snapshot_ts,
                    snapshot_status,
                    coverage_pct,
                    health_state,
                    error
                )
                VALUES (
                    %(health_ts)s,
                    %(last_success_snapshot_ts)s,
                    %(snapshot_status)s,
                    %(coverage_pct)s,
                    %(health_state)s,
                    %(error)s
                )
                ON CONFLICT (health_ts)
                DO UPDATE SET
                    last_success_snapshot_ts = EXCLUDED.last_success_snapshot_ts,
                    snapshot_status = EXCLUDED.snapshot_status,
                    coverage_pct = EXCLUDED.coverage_pct,
                    health_state = EXCLUDED.health_state,
                    error = EXCLUDED.error
                """,
                {
                    "health_ts": snapshot_ts,
                    "last_success_snapshot_ts": last_success_ts,
                    "snapshot_status": status,
                    "coverage_pct": coverage_pct,
                    "health_state": health_state,
                    "error": error
                }
            )

            logger.info(f"Health state updated: {health_state}")
