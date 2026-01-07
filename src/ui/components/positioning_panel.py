"""Current Positioning Panel component."""

import streamlit as st
from typing import Dict, Optional


def format_exposure(exposure: float, asset: str) -> str:
    """
    Format exposure value for display.

    Args:
        exposure: Net exposure value (szi)
        asset: Asset symbol

    Returns:
        Formatted string (e.g., "+1.2M HYPE", "-500K BTC")
    """
    sign = "+" if exposure >= 0 else ""
    abs_exp = abs(exposure)

    if abs_exp >= 1_000_000:
        return f"{sign}{abs_exp / 1_000_000:.1f}M {asset}"
    elif abs_exp >= 1_000:
        return f"{sign}{abs_exp / 1_000:.1f}K {asset}"
    else:
        return f"{sign}{abs_exp:.1f} {asset}"


def get_positioning_color(long_pct: float, short_pct: float, flat_count: int, total_wallets: int) -> str:
    """
    Determine background color based on positioning.

    Args:
        long_pct: Percentage of positioned wallets that are long
        short_pct: Percentage of positioned wallets that are short
        flat_count: Number of flat wallets
        total_wallets: Total wallets

    Returns:
        CSS color string
    """
    positioned_wallets = total_wallets - flat_count

    # If most wallets are flat, use gray
    if flat_count / total_wallets > 0.6:
        return "#404040"  # Gray

    # If balanced positioning (within 60-40 range), use gray
    if 40 <= long_pct <= 60:
        return "#404040"  # Gray

    # Majority long
    if long_pct > 60:
        return "#2d5016"  # Muted green

    # Majority short
    if short_pct > 60:
        return "#5c1a1a"  # Muted red

    return "#404040"  # Default gray


def render_positioning_panel(positioning: Optional[Dict], asset: str):
    """
    Render positioning panel for a single asset.

    Args:
        positioning: Positioning metrics dictionary from get_current_positioning()
        asset: Asset symbol
    """
    if not positioning:
        st.warning(f"No positioning data available for {asset}")
        return

    # Extract metrics
    net_exposure = positioning['net_exposure']
    long_count = positioning['long_count']
    short_count = positioning['short_count']
    flat_count = positioning['flat_count']
    total_wallets = positioning['total_wallets']
    long_pct = positioning['long_pct']
    short_pct = positioning['short_pct']
    top10_concentration = positioning['top10_concentration']

    # Determine color based on positioning
    bg_color = get_positioning_color(long_pct, short_pct, flat_count, total_wallets)

    # Container with colored background
    st.markdown(
        f"""
        <div style="
            background: {bg_color};
            padding: 15px;
            border-radius: 8px;
            border: 1px solid #555;
        ">
            <h3 style="margin: 0 0 10px 0; color: white;">{asset}</h3>
        </div>
        """,
        unsafe_allow_html=True
    )

    # Metrics in columns
    col1, col2 = st.columns(2)

    with col1:
        st.metric(
            "Net Exposure",
            format_exposure(net_exposure, asset),
            help="Total long szi minus total short szi"
        )

        st.metric(
            "Long/Short Ratio",
            f"{long_pct:.0f}% / {short_pct:.0f}%",
            help="Percentage of positioned wallets (excludes flat wallets)"
        )

    with col2:
        st.metric(
            "Positioning Breakdown",
            f"{long_count}L / {short_count}S / {flat_count}F",
            help=f"Wallets: {long_count} long, {short_count} short, {flat_count} flat"
        )

        # Concentration warning
        concentration_delta = None
        concentration_color = "normal"
        if top10_concentration > 70:
            concentration_delta = "High concentration"
            concentration_color = "inverse"

        st.metric(
            "Top 10 Concentration",
            f"{top10_concentration:.1f}%",
            delta=concentration_delta,
            delta_color=concentration_color,
            help="Percentage of total exposure held by top 10 wallets"
        )

    # Context note
    st.caption("⚠️ Context only - not a playbook signal. Shows current holdings, not behavioral changes.")


def render_positioning_section(assets: list):
    """
    Render the Current Positioning section for all assets.

    Args:
        assets: List of asset symbols (typically ['HYPE', 'BTC', 'ETH'])
    """
    from src.ui.data_loader import get_current_positioning

    st.subheader("Current Positioning")
    st.caption("What top wallets are holding right now (separate from behavioral signals)")

    # Create three columns for side-by-side display
    cols = st.columns(3)

    for i, asset in enumerate(assets):
        with cols[i]:
            positioning = get_current_positioning(asset)
            render_positioning_panel(positioning, asset)
