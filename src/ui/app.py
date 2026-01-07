"""Main Streamlit dashboard application."""

import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import streamlit as st
import logging
from datetime import datetime, timezone

from src.db import db
from src.ui.data_loader import (
    get_latest_signals,
    get_recent_alerts,
    get_latest_signal_timestamp
)
from src.ui.health import compute_health_state
from src.ui.components.header import render_global_header
from src.ui.components.system_halt import render_system_halt
from src.ui.components.asset_panel import render_asset_panel
from src.ui.components.alerts_panel import render_alerts_panel
from src.ui.components.detail_section import render_detail_section

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def initialize_session_state():
    """Initialize session state variables."""
    if 'selected_asset' not in st.session_state:
        st.session_state.selected_asset = 'HYPE'

    if 'time_range' not in st.session_state:
        st.session_state.time_range = '6h'


def main():
    """Main dashboard entry point."""
    # Page config
    st.set_page_config(
        page_title="Hyperliquid Wallet Dashboard",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="collapsed"
    )

    # Title
    st.title("📊 Hyperliquid Wallet Dashboard")

    # Initialize session state
    initialize_session_state()

    # Initialize database
    db.initialize()

    try:
        # 1. Fetch data
        latest_signals = get_latest_signals()
        latest_signal_ts = get_latest_signal_timestamp()

        # 2. Compute health state
        health_state, health_info = compute_health_state()

        # 3. Render header (always visible)
        render_global_header(health_state, health_info, latest_signal_ts)

        st.markdown("---")

        # 4. HARD STOP if stale
        if health_state == "STALE":
            render_system_halt(health_info)
            # st.stop() is called inside render_system_halt
            # Nothing below this executes

        # 5. Render asset panels (Decision Surface)
        st.subheader("Asset Signals")

        if not latest_signals:
            st.warning("No signal data available")
            return

        # Display 3 asset panels side-by-side
        asset_cols = st.columns(3)

        for i, signal in enumerate(latest_signals):
            with asset_cols[i]:
                render_asset_panel(signal, health_state)

                # Asset selection button
                if st.button(f"Show {signal['asset']} Details", key=f"btn_{signal['asset']}"):
                    st.session_state.selected_asset = signal['asset']

        st.markdown("---")

        # 6. Render alerts panel
        alerts = get_recent_alerts(hours=24, limit=5)
        render_alerts_panel(alerts)

        st.markdown("---")

        # 7. Render detail section
        st.subheader("Signal Details")

        # Asset selector (alternative to buttons)
        selected_asset = st.selectbox(
            "Select Asset",
            options=['HYPE', 'BTC', 'ETH'],
            index=['HYPE', 'BTC', 'ETH'].index(st.session_state.selected_asset),
            key='asset_selector'
        )

        # Update session state if changed
        if selected_asset != st.session_state.selected_asset:
            st.session_state.selected_asset = selected_asset

        # Time range selector
        time_range = st.radio(
            "Time Range",
            options=['6h', '24h'],
            index=0 if st.session_state.time_range == '6h' else 1,
            horizontal=True,
            key='time_range_selector'
        )

        # Update session state if changed
        if time_range != st.session_state.time_range:
            st.session_state.time_range = time_range

        # Render charts
        render_detail_section(st.session_state.selected_asset, st.session_state.time_range)

        # Auto-refresh info
        st.markdown("---")
        st.caption("Dashboard refreshes automatically every 30 seconds")

    except Exception as e:
        logger.error(f"Dashboard error: {e}", exc_info=True)
        st.error(f"Dashboard error: {e}")

    finally:
        # Clean up database connection
        # Note: In Streamlit, connections should be managed per session
        # We'll keep the pool open for the session
        pass


if __name__ == "__main__":
    # Auto-refresh every 30 seconds
    # Using manual timer pattern (no external dependency)
    import time

    if 'last_refresh' not in st.session_state:
        st.session_state.last_refresh = time.time()

    # Check if 30 seconds have passed
    if time.time() - st.session_state.last_refresh > 30:
        st.session_state.last_refresh = time.time()
        st.rerun()

    main()
