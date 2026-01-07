"""Recent alerts panel component."""

import streamlit as st
from typing import List, Dict


def render_alerts_panel(alerts: List[Dict]):
    """
    Render recent alerts panel.

    Shows up to 5 most recent alerts from last 24h.
    System Stale alerts are pinned to top.

    Args:
        alerts: List of alert dictionaries
    """
    st.subheader("Recent Alerts")

    if not alerts:
        st.info("No recent alerts")
        return

    # Severity icons
    severity_icons = {
        'medium': '⚠️',
        'high': '🔴',
        'critical': '🚨'
    }

    for alert in alerts:
        icon = severity_icons.get(alert['severity'], '❓')
        alert_ts = alert['alert_ts']
        asset = alert['asset'] if alert['asset'] else 'SYSTEM'
        alert_type = alert['alert_type']
        message = alert['message']

        # Truncate message to 100 chars
        message_truncated = message[:100] + "..." if len(message) > 100 else message

        # Format timestamp
        time_str = alert_ts.strftime('%H:%M UTC')

        # Render alert
        st.markdown(
            f"{icon} **{time_str}** [{asset}] {alert_type}: {message_truncated}"
        )
