from __future__ import annotations

from typing import Iterable

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


RED = "#DC2626"
NAVY = "#0B1F3A"
SLATE = "#64748B"
GRID = "#DDE5F0"
PLOT_BG = "#F8FAFD"
DASHBOARD_CHART_HEIGHT = 465


def shorten_label(value: object, limit: int = 20) -> str:
    """Return a compact axis label while the chart hover keeps the full value."""
    text = "Unknown" if value is None else " ".join(str(value).strip().split())
    if not text:
        text = "Unknown"
    replacements = {
        "INSUFFICIENT": "Insuff.",
        "COMPONENT": "Comp.",
        "APPEARANCE": "Appear.",
        "FUNCTIONAL": "Funct.",
        "INSPECTION": "Inspect.",
        "CALIBRATION": "Calib.",
        "EQUIPMENT": "Equip.",
        "PROCESS": "Proc.",
        "STATION": "Stn.",
        "CONNECTOR": "Conn.",
        "SOLDER": "Sldr.",
        "MISSING": "Miss.",
        "DISPENSING": "Disp.",
    }
    words = [replacements.get(word.upper(), word) for word in text.split()]
    compact = " ".join(words)
    if len(compact) <= limit:
        return compact
    return compact[: max(limit - 1, 1)].rstrip() + "…"


def _base_layout(
    chart: go.Figure,
    title: str,
    height: int = 410,
    margin: dict | None = None,
    legend_y: float = -0.18,
) -> go.Figure:
    chart.update_layout(
        title=title,
        template="plotly_white",
        height=height,
        autosize=True,
        paper_bgcolor="#FFFFFF",
        plot_bgcolor=PLOT_BG,
        font=dict(color=NAVY),
        margin=margin or dict(l=55, r=35, t=75, b=80),
        legend=dict(
            orientation="h",
            yanchor="top",
            y=legend_y,
            xanchor="center",
            x=0.5,
        ),
        hoverlabel=dict(bgcolor="#FFFFFF", font_color=NAVY),
        uniformtext_minsize=9,
        uniformtext_mode="show",
    )
    chart.update_xaxes(
        showgrid=False,
        linecolor="#C8D3E3",
        tickfont=dict(color=NAVY),
        automargin=True,
    )
    chart.update_yaxes(
        gridcolor=GRID,
        linecolor="#C8D3E3",
        tickfont=dict(color=NAVY),
        automargin=True,
    )
    return chart


def ppm_trend_chart(
    frame: pd.DataFrame,
    title: str,
    series: Iterable[tuple[str, str, str]],
    target_value: float | None = None,
    exception_mask: pd.Series | None = None,
) -> go.Figure:
    chart = go.Figure()
    frame = frame.copy()
    maximum = float(target_value or 0)
    dense = len(frame) >= 7
    palette_series = list(series)
    for series_index, (column, label, color) in enumerate(palette_series):
        values = pd.to_numeric(frame.get(column), errors="coerce")
        if values.notna().any():
            maximum = max(maximum, float(values.max()))
        positions = [
            (
                "top center"
                if not dense or (index + series_index) % 2 == 0
                else "bottom center"
            )
            for index in range(len(values))
        ]
        chart.add_trace(
            go.Scatter(
                x=frame["Period"],
                y=values,
                name=label,
                mode="lines+markers+text",
                line=dict(color=color, width=3),
                marker=dict(color=color, size=8),
                text=["" if pd.isna(value) else f"{float(value):,.0f}" for value in values],
                textposition=positions,
                textfont=dict(color=color, size=10),
                cliponaxis=False,
                hovertemplate=f"%{{x}}<br>{label}: %{{y:,.0f}} PPM<extra></extra>",
            )
        )

    axis_top = maximum * 1.28 if maximum > 0 else 1
    if exception_mask is not None and bool(exception_mask.any()):
        exception_rows = frame.loc[exception_mask]
        chart.add_trace(
            go.Scatter(
                x=exception_rows["Period"],
                y=[axis_top * 0.92] * len(exception_rows),
                name="Data exception",
                mode="markers",
                marker=dict(color=RED, size=13, symbol="x"),
                customdata=exception_rows[["Input", "ClassifiedDefectPCBs"]].to_numpy()
                if {"Input", "ClassifiedDefectPCBs"}.issubset(exception_rows.columns)
                else None,
                hovertemplate=(
                    "<b>Data consistency exception</b><br>"
                    "Input: %{customdata[0]:,.0f}<br>"
                    "Classified NG PCBs: %{customdata[1]:,.0f}<extra></extra>"
                ),
            )
        )

    _base_layout(
        chart,
        title,
        height=DASHBOARD_CHART_HEIGHT,
        margin=dict(l=55, r=35, t=75, b=80),
    )
    chart.update_xaxes(tickangle=-35 if len(frame) > 10 else 0)
    chart.update_yaxes(title_text="PPM", range=[0, axis_top], tickformat=",.0f")
    if target_value is not None:
        chart.add_hline(
            y=target_value,
            line_color=RED,
            line_width=2,
            line_dash="dash",
            annotation_text=f"{target_value:,.0f}",
            annotation_position="top right",
            annotation_font=dict(color=RED, size=11),
            annotation_bgcolor="rgba(0,0,0,0)",
            annotation_borderwidth=0,
        )
    return chart


def failure_donut_chart(
    functional: int,
    appearance: int,
    title: str = "Functional vs Appearance",
    both: int | None = None,
) -> go.Figure:
    values = [max(int(functional), 0), max(int(appearance), 0)]
    labels = ["Functional", "Appearance"]
    colors = ["#0D7A45", "#1D5FBF"]
    if both is not None:
        values.append(max(int(both), 0))
        labels = ["Functional only", "Appearance only", "Both types"]
        colors.append("#C2410C")
    chart = go.Figure(
        data=[
            go.Pie(
                labels=labels,
                values=values,
                hole=0.62,
                marker=dict(colors=colors, line=dict(color="#FFFFFF", width=2)),
                textinfo="percent",
                textposition="inside",
                insidetextorientation="horizontal",
                textfont=dict(size=12, color="#FFFFFF"),
                hovertemplate="%{label}<br>NG PCBs: %{value:,.0f}<br>%{percent}<extra></extra>",
                sort=False,
            )
        ]
    )
    _base_layout(
        chart,
        title,
        height=DASHBOARD_CHART_HEIGHT,
        margin=dict(l=20, r=20, t=70, b=70),
        legend_y=-0.08,
    )
    chart.update_layout(
        annotations=[
            dict(
                text=f"<b>{sum(values):,}</b><br>classified NG PCBs",
                x=0.5,
                y=0.5,
                showarrow=False,
                font=dict(size=15, color=NAVY),
            )
        ]
    )
    return chart


def pareto_chart(
    frame: pd.DataFrame,
    category: str,
    value: str,
    title: str,
    color: str,
    max_items: int = 8,
) -> go.Figure:
    data = frame[[category, value]].copy()
    data[value] = pd.to_numeric(data[value], errors="coerce").fillna(0)
    data = data.sort_values(value, ascending=False)
    total = float(data[value].sum())
    data = data.head(max_items)
    data["CumulativeShare"] = data[value].cumsum() / total if total else 0.0
    data["AxisLabel"] = data[category].map(lambda item: shorten_label(item, 18))
    chart = make_subplots(specs=[[{"secondary_y": True}]])
    chart.add_trace(
        go.Bar(
            x=data["AxisLabel"],
            y=data[value],
            name="NG PCBs",
            marker_color=color,
            text=[f"{float(item):,.0f}" for item in data[value]],
            textposition="outside",
            textfont=dict(color=NAVY, size=10),
            cliponaxis=False,
            customdata=data[[category]].to_numpy(),
            hovertemplate="%{customdata[0]}<br>NG PCBs: %{y:,.0f}<extra></extra>",
        ),
        secondary_y=False,
    )
    chart.add_trace(
        go.Scatter(
            x=data["AxisLabel"],
            y=data["CumulativeShare"],
            name="Cumulative %",
            mode="lines+markers+text",
            line=dict(color="#64748B", width=2),
            marker=dict(color="#64748B", size=7),
            text=[f"{value:.1%}" for value in data["CumulativeShare"]],
            textposition="top center",
            textfont=dict(color=NAVY, size=9),
            cliponaxis=False,
            customdata=data[[category]].to_numpy(),
            hovertemplate="%{customdata[0]}<br>Cumulative: %{y:.1%}<extra></extra>",
        ),
        secondary_y=True,
    )
    _base_layout(
        chart,
        title,
        height=DASHBOARD_CHART_HEIGHT,
        margin=dict(l=50, r=88, t=75, b=150),
        legend_y=-0.30,
    )
    bar_max = float(data[value].max()) if not data.empty else 0
    chart.update_yaxes(
        title_text="NG PCBs",
        range=[0, bar_max * 1.25] if bar_max > 0 else None,
        secondary_y=False,
    )
    chart.update_yaxes(
        title_text="Cumulative %",
        tickformat=".0%",
        range=[0, 1.14],
        secondary_y=True,
        showgrid=False,
    )
    chart.add_hline(
        y=0.8,
        secondary_y=True,
        line_color=RED,
        line_dash="dash",
        line_width=1.5,
    )
    chart.update_xaxes(tickangle=-25)
    return chart


def model_ppm_input_chart(
    frame: pd.DataFrame,
    title: str,
    color: str,
    max_items: int = 7,
) -> go.Figure:
    data = frame[["Model", "Input", "PPM"]].copy()
    data[["Input", "PPM"]] = data[["Input", "PPM"]].apply(pd.to_numeric, errors="coerce").fillna(0)
    data = data[data["Input"] > 0].sort_values(["PPM", "Input"], ascending=[False, False]).head(max_items)
    data["AxisLabel"] = data["Model"].map(lambda item: shorten_label(item, 16))
    chart = make_subplots(specs=[[{"secondary_y": True}]])
    chart.add_trace(
        go.Bar(
            x=data["AxisLabel"],
            y=data["PPM"],
            name="PPM",
            marker_color=color,
            text=[f"{value:,.0f}" for value in data["PPM"]],
            textposition="outside",
            cliponaxis=False,
            textfont=dict(color=color, size=10),
            customdata=data[["Model"]].to_numpy(),
            hovertemplate="%{customdata[0]}<br>PPM: %{y:,.0f}<extra></extra>",
            offsetgroup="ppm",
        ),
        secondary_y=False,
    )
    chart.add_trace(
        go.Bar(
            x=data["AxisLabel"],
            y=data["Input"],
            name="Input",
            marker_color="#D8DEE9",
            text=[f"{value:,.0f}" for value in data["Input"]],
            textposition="outside",
            cliponaxis=False,
            textfont=dict(color=SLATE, size=9),
            customdata=data[["Model"]].to_numpy(),
            hovertemplate="%{customdata[0]}<br>Input: %{y:,.0f}<extra></extra>",
            offsetgroup="input",
        ),
        secondary_y=True,
    )
    _base_layout(
        chart,
        title,
        height=DASHBOARD_CHART_HEIGHT,
        margin=dict(l=50, r=82, t=75, b=90),
    )
    chart.update_layout(barmode="group")
    ppm_max = float(data["PPM"].max()) if not data.empty else 0
    input_max = float(data["Input"].max()) if not data.empty else 0
    chart.update_yaxes(
        title_text="PPM",
        range=[0, ppm_max * 1.25] if ppm_max > 0 else None,
        secondary_y=False,
    )
    chart.update_yaxes(
        title_text="Input",
        range=[0, input_max * 1.25] if input_max > 0 else None,
        secondary_y=True,
        showgrid=False,
    )
    chart.update_xaxes(tickangle=-20)
    return chart


def heatmap_chart(
    matrix: pd.DataFrame,
    title: str,
    color_scale: str = "YlOrRd",
) -> go.Figure:
    data = matrix.copy()
    full_rows = [str(item) for item in data.index]
    full_columns = [str(item) for item in data.columns]
    row_labels = [shorten_label(item, 15) for item in full_rows]
    column_labels = [shorten_label(item, 13) for item in full_columns]
    values = data.to_numpy(dtype=float) if not data.empty else []
    chart = go.Figure(
        data=[
            go.Heatmap(
                z=values,
                x=column_labels,
                y=row_labels,
                colorscale=color_scale,
                text=[[f"{value:,.0f}" for value in row] for row in values] if len(values) else None,
                texttemplate="%{text}",
                textfont=dict(size=10),
                customdata=[
                    [[full_rows[row_index], full_columns[column_index]] for column_index in range(len(full_columns))]
                    for row_index in range(len(full_rows))
                ]
                if full_rows and full_columns
                else None,
                hovertemplate="%{customdata[0]} × %{customdata[1]}<br>PPM: %{z:,.0f}<extra></extra>",
                colorbar=dict(title="PPM", thickness=12),
            )
        ]
    )
    _base_layout(
        chart,
        title,
        height=DASHBOARD_CHART_HEIGHT,
        margin=dict(l=85, r=82, t=75, b=90),
    )
    chart.update_yaxes(autorange="reversed")
    chart.update_xaxes(tickangle=-25)
    return chart


def ranked_bar_chart(
    frame: pd.DataFrame,
    category: str,
    value: str,
    title: str,
    color: str,
    max_items: int = 8,
    value_suffix: str = "",
) -> go.Figure:
    data = frame[[category, value]].copy()
    data[value] = pd.to_numeric(data[value], errors="coerce").fillna(0)
    data = data.sort_values(value, ascending=False).head(max_items).sort_values(value)
    labels = data[category].map(lambda item: shorten_label(item, 22))
    chart = go.Figure(
        data=[
            go.Bar(
                x=data[value],
                y=labels,
                orientation="h",
                marker_color=color,
                text=[f"{item:,.0f}{value_suffix}" for item in data[value]],
                textposition="outside",
                textfont=dict(color=NAVY, size=10),
                cliponaxis=False,
                customdata=data[[category]].to_numpy(),
                hovertemplate=f"%{{customdata[0]}}<br>{value}: %{{x:,.0f}}{value_suffix}<extra></extra>",
            )
        ]
    )
    maximum = float(data[value].max()) if not data.empty else 0
    _base_layout(
        chart,
        title,
        height=DASHBOARD_CHART_HEIGHT,
        margin=dict(l=35, r=95, t=75, b=50),
    )
    chart.update_xaxes(range=[0, maximum * 1.24] if maximum > 0 else None)
    return chart
