"""Global header component."""

import streamlit as st
from datetime import datetime, timezone


def render_global_header(health_state: str, health_info: dict, latest_signal_ts: datetime):
    """
    Render global header with health status, timestamps, and coverage.

    Args:
        health_state: "HEALTHY", "DEGRADED", or "STALE"
        health_info: Dictionary with health details
        latest_signal_ts: Latest signal computation timestamp
    """
    # Health icons
    health_icons = {
        'HEALTHY': '✅',
        'DEGRADED': '⚠️',
        'STALE': '🚨'
    }

    health_icon = health_icons.get(health_state, '❓')

    # Create header columns
    header_cols = st.columns([2, 1, 1, 1])

    with header_cols[0]:
        st.markdown(f"### {health_icon} System: {health_state}")

    with header_cols[1]:
        last_snapshot_ts = health_info.get('last_snapshot_ts')
        if last_snapshot_ts:
            age_min = health_info.get('snapshot_age_minutes', 0)
            st.caption(f"Snapshot: {age_min}m ago")
        else:
            st.caption("Snapshot: N/A")

    with header_cols[2]:
        if latest_signal_ts:
            now = datetime.now(timezone.utc)
            signal_age_min = int((now - latest_signal_ts).total_seconds() / 60)
            st.caption(f"Signals: {signal_age_min}m ago")
        else:
            st.caption("Signals: N/A")

    with header_cols[3]:
        coverage = health_info.get('coverage_pct', 0)
        st.caption(f"Coverage: {coverage:.0f}%")

    # Show degraded warning banner if applicable
    if health_state == "DEGRADED":
        st.warning(
            "⚠️ Data quality degraded. Coverage or freshness below optimal. "
            "Signals may be less reliable."
        )
