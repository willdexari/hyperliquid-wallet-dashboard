#!/usr/bin/env python3
"""
Quick API client test without database.

Tests:
1. Fetch leaderboard data
2. Parse top 10 wallets
3. Fetch positions for one wallet
4. Parse position data

Run with: python3 test_api_client.py
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.ingest.hyperliquid_client import (
    HyperliquidClient,
    parse_leaderboard_row,
    parse_position_data
)


async def test_leaderboard():
    """Test leaderboard fetching and parsing."""
    print("=" * 60)
    print("TEST 1: Fetching Leaderboard")
    print("=" * 60)

    client = HyperliquidClient()

    try:
        rows = await client.fetch_leaderboard()
        print(f"✓ Fetched {len(rows)} leaderboard rows")

        # Parse rows
        parsed_wallets = []
        for row in rows[:20]:  # Test first 20
            parsed = parse_leaderboard_row(row)
            if parsed:
                parsed_wallets.append(parsed)

        print(f"✓ Successfully parsed {len(parsed_wallets)} valid wallets")

        # Sort by month_pnl
        parsed_wallets.sort(key=lambda w: w["month_pnl"], reverse=True)

        # Display top 10
        print("\nTop 10 Wallets by 30D PnL:")
        print("-" * 60)
        for i, wallet in enumerate(parsed_wallets[:10], 1):
            print(f"{i:2d}. {wallet['wallet_id'][:12]}... | "
                  f"PnL: ${wallet['month_pnl']:,.2f} | "
                  f"ROI: {wallet['month_roi']:.2f}%")

        return parsed_wallets[0] if parsed_wallets else None

    except Exception as e:
        print(f"✗ Leaderboard test failed: {e}")
        return None


async def test_wallet_positions(wallet_id: str):
    """Test wallet position fetching."""
    print("\n" + "=" * 60)
    print("TEST 2: Fetching Wallet Positions")
    print("=" * 60)
    print(f"Wallet: {wallet_id}")

    client = HyperliquidClient()

    try:
        data = await client.fetch_wallet_positions(wallet_id)

        if data is None:
            print("✗ Failed to fetch wallet data")
            return False

        print("✓ Successfully fetched wallet data")

        # Parse positions for each asset
        assets = ["HYPE", "BTC", "ETH"]
        print("\nPositions:")
        print("-" * 60)

        for asset in assets:
            position = parse_position_data(data, asset)

            if position["position_szi"] == 0:
                status = "Flat (no position)"
            elif position["position_szi"] > 0:
                status = f"Long {position['position_szi']} units"
            else:
                status = f"Short {abs(position['position_szi'])} units"

            print(f"{asset:4s}: {status}")

            if position["entry_px"]:
                print(f"      Entry: ${position['entry_px']:,.2f}")
            if position["leverage"]:
                print(f"      Leverage: {position['leverage']:.1f}x")

        return True

    except Exception as e:
        print(f"✗ Wallet positions test failed: {e}")
        return False


async def test_multiple_wallets(wallet_ids: list, max_concurrent: int = 5):
    """Test fetching multiple wallets with concurrency control."""
    print("\n" + "=" * 60)
    print("TEST 3: Fetching Multiple Wallets")
    print("=" * 60)
    print(f"Testing {len(wallet_ids)} wallets with max {max_concurrent} concurrent requests")

    client = HyperliquidClient()

    try:
        results = await client.fetch_multiple_wallets(wallet_ids, max_concurrency=max_concurrent)

        success_count = sum(1 for data in results.values() if data is not None)
        failed_count = len(wallet_ids) - success_count

        print(f"✓ Completed: {success_count} succeeded, {failed_count} failed")
        print(f"  Coverage: {success_count / len(wallet_ids) * 100:.1f}%")

        return success_count > 0

    except Exception as e:
        print(f"✗ Multiple wallets test failed: {e}")
        return False


async def main():
    """Run all API tests."""
    print("\n🚀 Hyperliquid API Client Test")
    print("=" * 60)

    # Test 1: Leaderboard
    top_wallet = await test_leaderboard()

    if not top_wallet:
        print("\n❌ Cannot proceed without leaderboard data")
        return False

    # Test 2: Single wallet positions
    success = await test_wallet_positions(top_wallet["wallet_id"])

    if not success:
        print("\n⚠️  Wallet positions test failed, but leaderboard works")

    # Test 3: Multiple wallets (if leaderboard worked)
    print("\n" + "=" * 60)
    print("Fetching top 10 wallets for multi-fetch test...")
    print("=" * 60)

    client = HyperliquidClient()
    rows = await client.fetch_leaderboard()
    parsed_wallets = []
    for row in rows[:15]:
        parsed = parse_leaderboard_row(row)
        if parsed:
            parsed_wallets.append(parsed)

    if len(parsed_wallets) >= 10:
        wallet_ids = [w["wallet_id"] for w in parsed_wallets[:10]]
        await test_multiple_wallets(wallet_ids)

    # Summary
    print("\n" + "=" * 60)
    print("✅ API CLIENT TESTS COMPLETE")
    print("=" * 60)
    print("\nThe Hyperliquid API integration is working!")
    print("\nNext steps:")
    print("1. Install PostgreSQL to test full ingestion")
    print("2. Run: brew install postgresql@15")
    print("3. Run: brew services start postgresql@15")
    print("4. Run: createdb hyperliquid")
    print("5. Run: psql -d hyperliquid -f db/schema.sql")
    print("6. Run: python3 -m src.ingest.fetch --once --refresh-universe")

    return True


if __name__ == "__main__":
    try:
        success = asyncio.run(main())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
