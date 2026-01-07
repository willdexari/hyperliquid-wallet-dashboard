"""Asset summary panel component."""

import streamlit as st
from src.ui.charts import (
    get_trend_arrow,
    get_dispersion_state,
    get_exit_state,
    get_playbook_color
)


def render_asset_panel(signal: dict, health_state: str):
    """
    Render a single asset summary panel.

    Args:
        signal: Signal dictionary with all signal values
        health_state: "HEALTHY", "DEGRADED", or "STALE"
    """
    asset = signal['asset']
    playbook = signal['allowed_playbook']
    risk_mode = signal['risk_mode']
    cas = signal['alignment_score']
    trend = signal['alignment_trend']
    dispersion = signal['dispersion_index']
    exit_cluster = signal['exit_cluster_score']

    # Playbook color
    bg_color = get_playbook_color(playbook)

    # Degraded suffix
    playbook_suffix = " (degraded)" if health_state == "DEGRADED" else ""

    # Border color for degraded state
    border_style = "border: 2px solid orange;" if health_state == "DEGRADED" else ""

    # Render panel
    st.markdown(
        f"""
        <div style="padding:15px;background:{bg_color};border-radius:8px;{border_style}">
            <h3 style="margin:0;color:white;">{asset}</h3>
            <h2 style="margin:10px 0;color:white;">{playbook}{playbook_suffix}</h2>
            <p style="margin:5px 0;color:#ddd;font-size:16px;"><strong>Risk:</strong> {risk_mode}</p>
        </div>
        """,
        unsafe_allow_html=True
    )

    # Signal details
    trend_arrow = get_trend_arrow(trend)
    dispersion_state = get_dispersion_state(dispersion)
    exit_state = get_exit_state(exit_cluster)

    st.markdown(f"**CAS:** {cas:.0f} {trend_arrow}")
    st.markdown(f"**Dispersion:** {dispersion_state}")
    st.markdown(f"**Exit Cluster:** {exit_state}")

    # Warnings
    if exit_state == "High":
        st.markdown("🔴 **DE-RISKING**")

    if dispersion_state == "High":
        st.markdown("⚠️ **High Disagreement**")
