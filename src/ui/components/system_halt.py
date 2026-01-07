"""System HALT view for stale data state."""

import streamlit as st
from datetime import datetime


def render_system_halt(health_info: dict):
    """
    Render SYSTEM HALT view when data is stale.

    This completely replaces the decision surface to prevent
    trading on stale data.

    Args:
        health_info: Dictionary with health details
    """
    st.error("🚨 SYSTEM HALT: DATA STALE")

    # Large warning box
    st.markdown(
        """
        <div style="text-align:center;padding:50px;background:#1a1a1a;border:3px solid red;border-radius:10px;margin:20px 0;">
            <h1 style="color:red;">⛔ SYSTEM HALT</h1>
            <h2 style="color:white;">DATA STALE</h2>
            <p style="color:#aaa;font-size:18px;">Signals and alerts are suppressed until ingestion resumes.</p>
        </div>
        """,
        unsafe_allow_html=True
    )

    st.markdown("---")

    # Details
    last_snapshot_ts = health_info.get('last_snapshot_ts')
    age_minutes = health_info.get('snapshot_age_minutes')

    if last_snapshot_ts:
        st.markdown(f"**Last successful snapshot:** {last_snapshot_ts.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    else:
        st.markdown("**Last successful snapshot:** None")

    if age_minutes:
        st.markdown(f"**Data gap:** {age_minutes} minutes")
    else:
        st.markdown("**Data gap:** Unknown")

    error = health_info.get('error')
    if error:
        st.markdown(f"**Error:** {error}")

    st.markdown("---")

    # Troubleshooting
    st.markdown("**Troubleshooting:**")
    st.markdown("1. Check ingestion process: `python -m src.ingest.fetch`")
    st.markdown("2. Check API status: https://api.hyperliquid.xyz/info")
    st.markdown("3. See `docs/runbooks/local_dev.md` for debugging steps")
    st.markdown("4. Review logs for errors")

    # CRITICAL: Stop rendering here
    st.stop()
