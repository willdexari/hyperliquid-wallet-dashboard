"""Configuration management for Hyperliquid Wallet Dashboard."""

import os
from typing import List
from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings

load_dotenv()


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database
    database_url: str = Field(
        default="postgresql://localhost:5432/hyperliquid",
        alias="DATABASE_URL"
    )

    # Assets (fixed for MVP)
    assets: List[str] = ["HYPE", "BTC", "ETH"]

    # Ingestion settings
    max_concurrency: int = Field(default=8, alias="MAX_CONCURRENCY")
    request_timeout_sec: int = Field(default=15, alias="REQUEST_TIMEOUT_SEC")
    universe_size: int = Field(default=200, alias="UNIVERSE_SIZE")

    # Refresh intervals
    universe_refresh_hours: int = Field(default=6, alias="UNIVERSE_REFRESH_HOURS")
    snapshot_interval_sec: int = Field(default=60, alias="SNAPSHOT_INTERVAL_SEC")
    signal_interval_sec: int = Field(default=300, alias="SIGNAL_INTERVAL_SEC")

    # Hyperliquid API endpoints
    hyperliquid_stats_url: str = "https://stats-data.hyperliquid.xyz"
    hyperliquid_api_url: str = "https://api.hyperliquid.xyz"

    # Health thresholds
    coverage_degraded_threshold: float = 0.95  # <95% coverage = degraded
    coverage_failed_threshold: float = 0.80    # <80% coverage = failed
    stale_threshold_minutes: int = 3           # >3 min since last success = stale

    class Config:
        env_file = ".env"
        case_sensitive = False


# Global settings instance
settings = Settings()
