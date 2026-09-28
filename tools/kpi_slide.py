"""Presentation-ready KPI slide charts."""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


TREND_COLOR = "#126A94"
TARGET_COLOR = "#F05A19"
EXCEPTION_COLOR = "#DC2626"


def _value_range(values: pd.Series, value_type: str, target: float | None) -> list[float]:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    if target is not None:
        numeric = pd.concat([numeric, pd.Series([target])], ignore_index=True)
    if value_type == "percent":
        if numeric.empty:
            return [0.9, 1.0]
        lower, upper = float(numeric.min()), float(numeric.max())
        span = max(upper - lower, 0.005)
        return [max(0.0, lower - span * 1.2), min(1.0, upper + span * 1.8)]
    if numeric.empty or float(numeric.max()) <= 0:
        return [0.0, max(float(target or 0) * 1.2, 1.0)]
    return [0.0, float(numeric.max()) * 1.18]


def _labels(values: pd.Series, value_type: str) -> list[str]:
    if value_type == "percent":
        return ["" if pd.isna(value) else f"{float(value) * 100:.2f}%" for value in values]
    return ["" if pd.isna(value) else f"{float(value):,.0f}" for value in values]


def _target_label(value: float, value_type: str) -> str:
    return f"{value * 100:.2f}%" if value_type == "percent" else f"{value:,.0f}"


def build_kpi_slide(period_label: str, panels: list[dict[str, Any]]) -> go.Figure:
    """Build a four-panel 16:9 KPI slide from already-calculated trend data.

    Each panel expects ``title``, ``frame``, ``x_column``, ``y_column``,
    ``value_type`` (``percent`` or ``ppm``), and ``target``. Optional
    ``exceptions`` rows produce a red × without connecting the trend to zero.
    """
    if len(panels) != 4:
        raise ValueError("A KPI slide requires exactly four panels.")

    titles = [str(panel["title"]) for panel in panels]
    figure = make_subplots(
        rows=2,
        cols=2,
        subplot_titles=titles,
        horizontal_spacing=0.08,
        vertical_spacing=0.18,
    )
    for annotation in figure.layout.annotations:
        annotation.font = dict(size=16, color="#111111", family="Arial")

    for index, panel in enumerate(panels):
        row, column = divmod(index, 2)
        row += 1
        column += 1
        frame = panel["frame"].copy()
        x_column = str(panel["x_column"])
        y_column = str(panel["y_column"])
        value_type = str(panel["value_type"])
        target = panel.get("target")
        target = float(target) if target is not None else None
        values = pd.to_numeric(frame.get(y_column, pd.Series(dtype="float64")), errors="coerce")
        labels = _labels(values, value_type)
        range_values = _value_range(values, value_type, target)
        x_values = frame.get(x_column, pd.Series(dtype="object"))
        chart_values = values.astype(object).where(values.notna(), None)
        dense = len(frame) >= 7
        positions = ["bottom center" if dense and number % 2 else "top center" for number in range(len(frame))]

        figure.add_trace(
            go.Scatter(
                x=x_values,
                y=chart_values,
                mode="lines+markers+text",
                connectgaps=False,
                line=dict(color=TREND_COLOR, width=3),
                marker=dict(color=TREND_COLOR, size=8),
                text=labels,
                textposition=positions,
                textfont=dict(color="#111111", size=11, family="Arial"),
                cliponaxis=False,
                hovertemplate=(
                    "%{x}<br>Pass rate: %{y:.2%}<extra></extra>"
                    if value_type == "percent"
                    else "%{x}<br>PPM: %{y:,.0f}<extra></extra>"
                ),
                showlegend=False,
            ),
            row=row,
            col=column,
        )

        exceptions = panel.get("exceptions")
        if isinstance(exceptions, pd.DataFrame) and not exceptions.empty:
            exception_x = exceptions.get(x_column, pd.Series(dtype="object"))
            exception_y = range_values[1] - (range_values[1] - range_values[0]) * 0.05
            figure.add_trace(
                go.Scatter(
                    x=exception_x,
                    y=[exception_y] * len(exceptions),
                    mode="markers",
                    marker=dict(color=EXCEPTION_COLOR, size=15, symbol="x"),
                    name="Data exception",
                    hovertemplate="<b>Data consistency exception</b><extra></extra>",
                    showlegend=False,
                ),
                row=row,
                col=column,
            )

        figure.update_xaxes(
            title_text="Date",
            tickangle=-25 if len(frame) > 7 else 0,
            showline=True,
            linecolor="#111111",
            linewidth=1,
            mirror=True,
            ticks="outside",
            tickfont=dict(size=10, color="#111111"),
            row=row,
            col=column,
        )
        figure.update_yaxes(
            title_text="Pass rate" if value_type == "percent" else "PPM",
            range=range_values,
            tickformat=".1%" if value_type == "percent" else ",.0f",
            showgrid=True,
            gridcolor="#D9DDE3",
            showline=True,
            linecolor="#111111",
            linewidth=1,
            mirror=True,
            tickfont=dict(size=10, color="#111111"),
            row=row,
            col=column,
        )
        if target is not None:
            figure.add_hline(
                y=target,
                line_color=TARGET_COLOR,
                line_width=2,
                row=row,
                col=column,
            )
            suffix = "" if index == 0 else str(index + 1)
            figure.add_annotation(
                x=0.985,
                xref=f"x{suffix} domain",
                y=target,
                yref=f"y{suffix}",
                text=_target_label(target, value_type),
                showarrow=False,
                xanchor="right",
                yanchor="bottom",
                font=dict(color="#C2410C", size=11, family="Arial"),
                bgcolor="rgba(255,255,255,0.82)",
            )

    figure.update_layout(
        width=1600,
        height=900,
        margin=dict(l=42, r=42, t=125, b=58),
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        font=dict(family="Arial", color="#111111"),
        showlegend=False,
        hovermode="closest",
    )
    figure.add_annotation(
        x=0.0,
        y=1.105,
        xref="paper",
        yref="paper",
        text=f"<b>Quality – SMT – {period_label}</b>",
        showarrow=False,
        xanchor="left",
        yanchor="middle",
        font=dict(size=30, color="#252525", family="Arial"),
    )
    figure.add_annotation(
        x=0.985,
        y=1.105,
        xref="paper",
        yref="paper",
        text="<b>JOVI</b>",
        showarrow=False,
        xanchor="right",
        yanchor="middle",
        font=dict(size=30, color="#FFFFFF", family="Arial"),
        bgcolor="#0C54C2",
        borderpad=10,
    )
    return figure
