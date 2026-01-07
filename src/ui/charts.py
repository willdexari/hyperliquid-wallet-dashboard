"""Chart creation utilities for dashboard."""

import logging
from typing import List, Dict, Optional
import plotly.graph_objects as go
from plotly.subplots import make_subplots

logger = logging.getLogger(__name__)


def create_signal_chart(
    history: List[Dict],
    metric: str,
    title: str,
    thresholds: Optional[List[float]] = None,
    y_range: tuple = (0, 100)
) -> go.Figure:
    """
    Create a time series chart for a signal metric.

    Args:
        history: List of signal dictionaries with timestamp and metric values
        metric: Name of the metric field to plot
        title: Chart title
        thresholds: Optional list of threshold values to draw as horizontal lines
        y_range: Y-axis range (default 0-100)

    Returns:
        Plotly figure
    """
    if not history:
        # Empty chart with message
        fig = go.Figure()
        fig.add_annotation(
            text="No data available",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font=dict(size=16, color="gray")
        )
        fig.update_layout(
            title=title,
            height=250,
            margin=dict(l=50, r=20, t=40, b=40),
            xaxis=dict(visible=False),
            yaxis=dict(visible=False)
        )
        return fig

    # Extract timestamps and values
    timestamps = [row['signal_ts'] for row in history]
    values = [row[metric] for row in history]

    # Create figure
    fig = go.Figure()

    # Add main line
    fig.add_trace(go.Scatter(
        x=timestamps,
        y=values,
        mode='lines+markers',
        name=title,
        line=dict(color='#1f77b4', width=2),
        marker=dict(size=4),
        hovertemplate='%{y:.1f}<extra></extra>'
    ))

    # Add threshold lines if specified
    if thresholds:
        threshold_colors = ['rgba(255, 0, 0, 0.3)', 'rgba(0, 255, 0, 0.3)', 'rgba(255, 165, 0, 0.3)']
        for i, threshold in enumerate(thresholds):
            color = threshold_colors[i % len(threshold_colors)]
            fig.add_hline(
                y=threshold,
                line_dash="dot",
                line_color=color,
                annotation_text=str(threshold),
                annotation_position="right"
            )

    # Update layout
    fig.update_layout(
        title=title,
        height=250,
        margin=dict(l=50, r=20, t=40, b=40),
        xaxis=dict(
            title="",
            showgrid=False,
            fixedrange=True
        ),
        yaxis=dict(
            title="",
            range=y_range,
            showgrid=True,
            gridcolor='rgba(128, 128, 128, 0.2)',
            fixedrange=True
        ),
        hovermode='x unified',
        showlegend=False,
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)'
    )

    return fig


def get_trend_arrow(trend: str) -> str:
    """
    Get arrow symbol for alignment trend.

    Args:
        trend: "rising", "flat", or "falling"

    Returns:
        Arrow character
    """
    arrows = {
        'rising': '↑',
        'flat': '→',
        'falling': '↓'
    }
    return arrows.get(trend, '→')


def get_dispersion_state(dispersion_index: float) -> str:
    """
    Get dispersion state label.

    Args:
        dispersion_index: Dispersion index (0-100)

    Returns:
        "Low", "Medium", or "High"
    """
    if dispersion_index < 40:
        return "Low"
    elif dispersion_index < 60:
        return "Medium"
    else:
        return "High"


def get_exit_state(exit_cluster_score: float) -> str:
    """
    Get exit cluster state label.

    Args:
        exit_cluster_score: Exit cluster score (0-100)

    Returns:
        "Low", "Medium", or "High"
    """
    if exit_cluster_score < 16:
        return "Low"
    elif exit_cluster_score <= 25:
        return "Medium"
    else:
        return "High"


def get_playbook_color(playbook: str) -> str:
    """
    Get background color for playbook label.

    Args:
        playbook: "Long-only", "Short-only", or "No-trade"

    Returns:
        CSS color string
    """
    colors = {
        'Long-only': '#2d5f2e',  # Muted green
        'Short-only': '#5f2d2e',  # Muted red
        'No-trade': '#4a4a4a'     # Gray
    }
    return colors.get(playbook, '#4a4a4a')
