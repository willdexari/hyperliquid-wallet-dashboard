"""Basic tests for ingestion components."""

import pytest
from datetime import datetime, timezone

from src.ingest.snapshots import get_snapshot_timestamp
from src.ingest.hyperliquid_client import parse_leaderboard_row, parse_position_data


class TestSnapshotTimestamp:
    """Test snapshot timestamp rounding."""

    def test_rounds_to_minute_boundary(self):
        """Timestamp should be floored to 60s boundary."""
        ts = get_snapshot_timestamp()
        assert ts.second == 0
        assert ts.microsecond == 0

    def test_returns_utc(self):
        """Timestamp should be in UTC timezone."""
        ts = get_snapshot_timestamp()
        assert ts.tzinfo == timezone.utc


class TestLeaderboardParsing:
    """Test leaderboard row parsing."""

    def test_parse_valid_row(self):
        """Parse a valid leaderboard row."""
        row = {
            "ethAddress": "0x1234567890abcdef",
            "accountValue": "100000.50",
            "windowPerformances": [
                ["month", {"pnl": "5000.25", "roi": "5.0"}]
            ]
        }

        result = parse_leaderboard_row(row)

        assert result is not None
        assert result["wallet_id"] == "0x1234567890abcdef"
        assert result["account_value"] == 100000.50
        assert result["month_pnl"] == 5000.25
        assert result["month_roi"] == 5.0

    def test_parse_row_missing_eth_address(self):
        """Row without ethAddress should return None."""
        row = {
            "accountValue": "100000",
            "windowPerformances": []
        }

        result = parse_leaderboard_row(row)
        assert result is None

    def test_parse_row_missing_month_window(self):
        """Row without month window should default to 0."""
        row = {
            "ethAddress": "0xabc",
            "windowPerformances": []
        }

        result = parse_leaderboard_row(row)

        assert result is not None
        assert result["month_pnl"] == 0.0
        assert result["month_roi"] == 0.0

    def test_parse_row_none_account_value(self):
        """None account value should be preserved."""
        row = {
            "ethAddress": "0xabc",
            "accountValue": None,
            "windowPerformances": []
        }

        result = parse_leaderboard_row(row)

        assert result is not None
        assert result["account_value"] is None


class TestPositionParsing:
    """Test position data parsing."""

    def test_parse_existing_position(self):
        """Parse a position that exists."""
        clearinghouse_data = {
            "assetPositions": [
                {
                    "position": {
                        "coin": "BTC",
                        "szi": "1.5",
                        "entryPx": "45000.00",
                        "liquidationPx": "40000.00",
                        "leverage": {"value": "5"},
                        "marginUsed": "9000.00"
                    }
                }
            ]
        }

        result = parse_position_data(clearinghouse_data, "BTC")

        assert result["position_szi"] == 1.5
        assert result["entry_px"] == 45000.00
        assert result["liq_px"] == 40000.00
        assert result["leverage"] == 5.0
        assert result["margin_used"] == 9000.00

    def test_parse_no_position(self):
        """Asset with no position should return explicit zero."""
        clearinghouse_data = {
            "assetPositions": [
                {
                    "position": {
                        "coin": "BTC",
                        "szi": "1.0"
                    }
                }
            ]
        }

        result = parse_position_data(clearinghouse_data, "ETH")

        assert result["position_szi"] == 0.0
        assert result["entry_px"] is None
        assert result["liq_px"] is None
        assert result["leverage"] is None
        assert result["margin_used"] is None

    def test_parse_empty_asset_positions(self):
        """Empty asset positions should return zero."""
        clearinghouse_data = {"assetPositions": []}

        result = parse_position_data(clearinghouse_data, "HYPE")

        assert result["position_szi"] == 0.0

    def test_parse_negative_szi(self):
        """Negative szi (short position) should be preserved."""
        clearinghouse_data = {
            "assetPositions": [
                {
                    "position": {
                        "coin": "ETH",
                        "szi": "-2.5"
                    }
                }
            ]
        }

        result = parse_position_data(clearinghouse_data, "ETH")

        assert result["position_szi"] == -2.5


class TestConfiguration:
    """Test configuration loading."""

    def test_assets_are_fixed(self):
        """Assets should be HYPE, BTC, ETH only."""
        from src.config import settings

        assert settings.assets == ["HYPE", "BTC", "ETH"]

    def test_default_concurrency(self):
        """Default concurrency should be 8."""
        from src.config import settings

        assert settings.max_concurrency == 8

    def test_snapshot_interval_is_60(self):
        """Snapshot interval should be 60 seconds."""
        from src.config import settings

        assert settings.snapshot_interval_sec == 60
