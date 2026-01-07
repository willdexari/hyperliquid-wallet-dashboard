"""Hyperliquid API client for fetching wallet and position data."""

import asyncio
import logging
from typing import Dict, List, Optional
from datetime import datetime, timezone

import httpx

from src.config import settings

logger = logging.getLogger(__name__)


class HyperliquidClient:
    """Client for interacting with Hyperliquid APIs."""

    def __init__(self):
        """Initialize the client with default settings."""
        self.stats_url = settings.hyperliquid_stats_url
        self.api_url = settings.hyperliquid_api_url
        self.timeout = settings.request_timeout_sec

    async def fetch_leaderboard(self) -> List[Dict]:
        """
        Fetch the leaderboard from Hyperliquid.

        Returns:
            List of leaderboard rows with wallet data

        Raises:
            Exception: If both primary and fallback endpoints fail
        """
        # Try primary endpoint first
        try:
            return await self._fetch_leaderboard_stats()
        except Exception as e:
            logger.warning(f"Primary leaderboard endpoint failed: {e}")
            logger.info("Attempting fallback leaderboard endpoint")

        # Try fallback endpoint
        try:
            return await self._fetch_leaderboard_info_api()
        except Exception as e:
            logger.error(f"Fallback leaderboard endpoint also failed: {e}")
            raise Exception("Both leaderboard endpoints failed")

    async def _fetch_leaderboard_stats(self) -> List[Dict]:
        """Fetch leaderboard from stats-data endpoint (primary)."""
        url = f"{self.stats_url}/Mainnet/leaderboard"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()

        if "leaderboardRows" not in data:
            raise ValueError("Missing leaderboardRows in response")

        return data["leaderboardRows"]

    async def _fetch_leaderboard_info_api(self) -> List[Dict]:
        """Fetch leaderboard from info API (fallback)."""
        url = f"{self.api_url}/info"
        payload = {"type": "leaderboard"}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()

        # The fallback response structure may vary
        # Adjust this based on actual API response
        return data if isinstance(data, list) else data.get("leaderboard", [])

    async def fetch_wallet_positions(
        self, wallet_address: str
    ) -> Optional[Dict]:
        """
        Fetch positions for a single wallet.

        Args:
            wallet_address: The wallet address to query

        Returns:
            Clearinghouse state data or None if failed

        The response contains:
            - assetPositions: List of position objects
              - position.coin: Asset symbol
              - position.szi: Signed size in units
              - position.entryPx: Entry price
              - position.liquidationPx: Liquidation price
              - position.marginUsed: Margin allocated
              - position.leverage: Leverage info
        """
        url = f"{self.api_url}/info"
        payload = {
            "type": "clearinghouseState",
            "user": wallet_address
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                return response.json()
        except httpx.TimeoutException:
            logger.warning(f"Timeout fetching positions for {wallet_address}")
            return None
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                logger.warning(f"Rate limited on wallet {wallet_address}")
            else:
                logger.warning(
                    f"HTTP {e.response.status_code} for wallet {wallet_address}"
                )
            return None
        except Exception as e:
            logger.warning(f"Error fetching wallet {wallet_address}: {e}")
            return None

    async def fetch_multiple_wallets(
        self, wallet_addresses: List[str], max_concurrency: int = None
    ) -> Dict[str, Optional[Dict]]:
        """
        Fetch positions for multiple wallets with concurrency control.

        Args:
            wallet_addresses: List of wallet addresses
            max_concurrency: Maximum concurrent requests (defaults to config)

        Returns:
            Dictionary mapping wallet_address -> position data (or None if failed)
        """
        if max_concurrency is None:
            max_concurrency = settings.max_concurrency

        semaphore = asyncio.Semaphore(max_concurrency)

        async def fetch_with_semaphore(wallet_address: str):
            async with semaphore:
                data = await self.fetch_wallet_positions(wallet_address)
                return wallet_address, data

        tasks = [fetch_with_semaphore(addr) for addr in wallet_addresses]
        results = await asyncio.gather(*tasks)

        return dict(results)


def parse_leaderboard_row(row: Dict) -> Optional[Dict]:
    """
    Parse a leaderboard row into standardized wallet data.

    Args:
        row: Raw leaderboard row

    Returns:
        Parsed wallet data or None if invalid

    Expected output:
        {
            "wallet_id": str,
            "account_value": float or None,
            "month_pnl": float,
            "month_roi": float
        }
    """
    try:
        wallet_id = row.get("ethAddress")
        if not wallet_id:
            return None

        # Parse window performances
        window_performances = row.get("windowPerformances", [])
        windows = dict(window_performances) if window_performances else {}

        # Extract month data
        month_data = windows.get("month", {})
        month_pnl = float(month_data.get("pnl", 0)) if month_data else 0.0
        month_roi = float(month_data.get("roi", 0)) if month_data else 0.0

        # Account value (may be None)
        account_value = row.get("accountValue")
        if account_value is not None:
            account_value = float(account_value)

        return {
            "wallet_id": wallet_id,
            "account_value": account_value,
            "month_pnl": month_pnl,
            "month_roi": month_roi
        }
    except Exception as e:
        logger.warning(f"Failed to parse leaderboard row: {e}")
        return None


def parse_position_data(
    clearinghouse_data: Dict, asset: str
) -> Dict:
    """
    Extract position data for a specific asset from clearinghouse response.

    Args:
        clearinghouse_data: Response from clearinghouseState endpoint
        asset: Asset symbol (HYPE, BTC, or ETH)

    Returns:
        Position data dictionary with keys:
            - position_szi: Signed size (0 if no position)
            - entry_px: Entry price or None
            - liq_px: Liquidation price or None
            - leverage: Leverage or None
            - margin_used: Margin used or None
    """
    asset_positions = clearinghouse_data.get("assetPositions", [])

    # Find position for this asset
    position = None
    for pos in asset_positions:
        if pos.get("position", {}).get("coin") == asset:
            position = pos.get("position", {})
            break

    # If no position found, return explicit zero
    if position is None:
        return {
            "position_szi": 0.0,
            "entry_px": None,
            "liq_px": None,
            "leverage": None,
            "margin_used": None
        }

    # Extract position fields
    try:
        szi = float(position.get("szi", 0))
        entry_px = position.get("entryPx")
        liq_px = position.get("liquidationPx")
        leverage_data = position.get("leverage", {})
        margin_used = position.get("marginUsed")

        return {
            "position_szi": szi,
            "entry_px": float(entry_px) if entry_px is not None else None,
            "liq_px": float(liq_px) if liq_px is not None else None,
            "leverage": float(leverage_data.get("value", 0)) if isinstance(leverage_data, dict) else (
                float(leverage_data) if leverage_data is not None else None
            ),
            "margin_used": float(margin_used) if margin_used is not None else None
        }
    except Exception as e:
        logger.warning(f"Failed to parse position for {asset}: {e}")
        return {
            "position_szi": 0.0,
            "entry_px": None,
            "liq_px": None,
            "leverage": None,
            "margin_used": None
        }
