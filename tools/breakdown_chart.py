"""Report charts using the same unique-PCB counts as dashboard cards."""
from html import escape

import plotly.graph_objects as go


def category_counts(source, column, selections):
    scope = source
    for field, category in selections.items():
        if field != column and category != "All":
            scope = scope[scope[field].eq(category)]
    return scope.groupby(column)["_DefectKey"].nunique().sort_values(ascending=False, kind="stable")


def build_breakdown_chart(counts, title, *, angle=45, show_values=True):
    categories = counts.index.astype(str).tolist()
    labels = [escape(value if len(value) <= 38 else value[:35] + "…") for value in categories]
    figure = go.Figure(go.Bar(
        x=list(range(len(counts))), y=counts.tolist(), width=0.38,
        marker_color="#4472C4", customdata=[escape(value) for value in categories],
        text=counts.tolist() if show_values else None,
        textposition="outside", textfont=dict(size=18, color="#404040"),
        cliponaxis=False, hovertemplate="%{customdata}<br>Defect PCB: %{y:,.0f}<extra></extra>",
    ))
    figure.update_layout(
        title=dict(text=escape(title), x=0.5, xanchor="center", font=dict(size=24, color="#404040")),
        height=520, margin=dict(l=76, r=34, t=68, b=150),
        paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
        font=dict(family="Arial", color="#404040", size=16),
        showlegend=False, bargap=0.6, meta={"jovi_report_export": "breakdown"},
    )
    figure.update_xaxes(
        tickmode="array", tickvals=list(range(len(counts))), ticktext=labels,
        tickangle=angle, range=[-0.65, max(len(counts) - 1, 0) + 0.65],
        showgrid=False, zeroline=False, showline=True, linecolor="#BFBFBF",
        fixedrange=True,
    )
    maximum = max(int(counts.max()), 1) if not counts.empty else 1
    figure.update_yaxes(
        title_text="Defect PCB", range=[0, maximum * 1.2],
        tickformat=",.0f", dtick=1 if maximum <= 10 else None,
        showgrid=False, showline=False, zeroline=False, fixedrange=True,
    )
    return figure
