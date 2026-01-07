"""Detail section with signal charts and contributors."""

import streamlit as st
from typing import List, Dict, Optional

from src.ui.data_loader import get_signal_history, get_latest_contributors
from src.ui.charts import create_signal_chart


def render_detail_section(selected_asset: str, time_range: str):
    """
    Render detail section with signal history charts and contributors.

    Args:
        selected_asset: Asset symbol to display
        time_range: "6h" or "24h"
    """
    st.subheader(f"{selected_asset} Signal History")

    # Time range selector
    hours = 6 if time_range == "6h" else 24

    # Fetch signal history
    history = get_signal_history(selected_asset, hours=hours)

    if not history:
        st.warning(f"No signal history available for {selected_asset}")
        return

    # CAS Chart
    fig_cas = create_signal_chart(
        history,
        metric="alignment_score",
        title="Consensus Alignment Score",
        thresholds=[25, 75]
    )
    st.plotly_chart(fig_cas, use_container_width=True)

    # Dispersion Chart
    fig_disp = create_signal_chart(
        history,
        metric="dispersion_index",
        title="Dispersion Index",
        thresholds=[40, 60]
    )
    st.plotly_chart(fig_disp, use_container_width=True)

    # Exit Cluster Chart
    fig_exit = create_signal_chart(
        history,
        metric="exit_cluster_score",
        title="Exit Cluster Score",
        thresholds=[20, 25]
    )
    st.plotly_chart(fig_exit, use_container_width=True)

    # Contributors summary (collapsed by default)
    render_contributors_summary(selected_asset)


def render_contributors_summary(asset: str):
    """
    Render wallet behavior breakdown in expandable section.

    Args:
        asset: Asset symbol
    """
    with st.expander("Wallet Behavior Breakdown"):
        contrib = get_latest_contributors(asset)

        if not contrib:
            st.info("No contributor data available")
            return

        # Display as metrics in columns
        cols = st.columns(4)

        with cols[0]:
            st.metric(
                "Adding Long",
                f"{contrib['pct_add_long']:.1f}%",
                delta=f"{contrib['count_add_long']} wallets"
            )

        with cols[1]:
            st.metric(
                "Adding Short",
                f"{contrib['pct_add_short']:.1f}%",
                delta=f"{contrib['count_add_short']} wallets"
            )

        with cols[2]:
            st.metric(
                "Reducing",
                f"{contrib['pct_reducers']:.1f}%",
                delta=f"{contrib['count_reducers']} wallets"
            )

        with cols[3]:
            st.metric(
                "Flat",
                f"{contrib['pct_flat']:.1f}%",
                delta=f"{contrib['count_flat']} wallets"
            )

        st.caption(f"Total: {contrib['total_wallets']} wallets")
