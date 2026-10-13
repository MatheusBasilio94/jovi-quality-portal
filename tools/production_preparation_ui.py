"""Streamlit view for the read-only production preparation simulator."""
from datetime import datetime, timedelta
from hashlib import sha1
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from tools.production_preparation import history, simulate


def _select_period():
    today = datetime.now(ZoneInfo("America/Manaus")).date()
    preset = st.session_state.get("production_quick", "Last 2 months")
    start = (pd.Timestamp(today) - pd.DateOffset(months=2)).date() + timedelta(days=1)
    if preset == "Last 30 days": start = today - timedelta(days=29)
    elif preset == "Last 7 days": start = today - timedelta(days=6)
    elif preset == "This month": start = today.replace(day=1)
    elif preset == "Custom period": return
    st.session_state["production_period"] = (start, today)
    st.session_state["_production_period"] = (start, today)


def _remember_period():
    st.session_state["_production_period"] = st.session_state["production_period"]
    st.session_state["production_quick"] = "Custom period"


def _save_actions(editor_key, context, issues):
    saved = dict(st.session_state.get("_production_actions", {}))
    actions = dict(saved.get(context, {}))
    for index, changes in st.session_state.get(editor_key, {}).get("edited_rows", {}).items():
        issue = issues[int(index)]
        settings = dict(actions.get(issue, {}))
        settings.update(changes)
        if settings.get("Expected reduction (%)") is None: settings["Expected reduction (%)"] = 0.0
        if settings.get("Planned action") is None: settings["Planned action"] = ""
        actions[issue] = settings
    saved[context] = actions
    st.session_state["_production_actions"] = saved


def _reset_actions(context):
    saved = dict(st.session_state.get("_production_actions", {}))
    saved[context] = {issue: {**values, "Expected reduction (%)": 0.0} for issue, values in saved.get(context, {}).items()}
    st.session_state["_production_actions"] = saved
    st.session_state["_production_reset"] = st.session_state.get("_production_reset", 0) + 1


@st.fragment
def render(load_data, directory):
    st.markdown("<div class='smart-report-title'>Production Preparation</div><div class='smart-report-subtitle'>Review recent model defects and simulate the impact of your planned corrective actions.</div>", unsafe_allow_html=True)
    st.html("<style>.st-key-production_filters{background:#E8F1FF;border:1px solid #B7CEF0;border-left:4px solid #2563EB;border-radius:8px;padding:10px 16px;} .st-key-production_filters [data-testid='stWidgetLabel'] p{font-size:13px;font-weight:650;color:#08244C;}</style>")
    today = datetime.now(ZoneInfo("America/Manaus")).date()
    default = ((pd.Timestamp(today) - pd.DateOffset(months=2)).date() + timedelta(days=1), today)
    if "production_period" not in st.session_state:
        st.session_state["production_period"] = st.session_state.get("_production_period", default)
    with st.container(key="production_filters"):
        columns = st.columns([.65, 1.2, 1.55, .85, 1])
        with columns[0]: area = st.selectbox("Area", ["SMT", "Assembly"], key="production_area", persist_state="session")
        with columns[2]: period = st.date_input("Historical period", key="production_period", format="DD/MM/YYYY", on_change=_remember_period, persist_state="session")
        with columns[3]: planned = int(st.number_input("Next production quantity", min_value=1, max_value=100000000, value=5000, step=100, key="production_quantity", persist_state="session"))
        with columns[4]: st.selectbox("Quick selection", ["Last 2 months", "Last 30 days", "Last 7 days", "This month", "Custom period"], key="production_quick", on_change=_select_period, persist_state="session")
        if len(period) != 2:
            st.info("Select both the start and end dates.")
            return
        start, end = sorted(period)
        try:
            data = load_data(area, start, end)
        except Exception as exc:
            st.info(f"{area} source data could not be loaded: {exc}")
            return
        inputs = data["inputs"]
        active = inputs.loc[inputs["Input"].gt(0)]
        models = active.groupby("Model")["Date"].max().sort_values(ascending=False).index.tolist()
        if not models:
            st.info("No model input is available in this period. Adjust the historical dates.")
            return
        model_key = f"production_model_{area.lower()}"
        if st.session_state.get(model_key) not in models: st.session_state[model_key] = models[0]
        with columns[1]: model = st.selectbox("Model", models, key=model_key, persist_state="session")
    selected_input = active.loc[active["Model"].eq(model)]
    total_input = int(selected_input["Input"].sum())
    records = data["records"].loc[data["records"]["Model"].eq(model)].copy()
    try:
        baseline = history(records, total_input, area)
    except ValueError as exc:
        st.warning(str(exc))
        return
    latest = pd.Timestamp(selected_input["Date"].max()).strftime("%d %b %Y")
    st.caption(f"Historical input: {total_input:,} PCBs · {baseline['records']['_DefectKey'].nunique():,} unique classified NG PCBs · Latest input: {latest}")
    st.markdown("### Action simulation by defect")
    st.caption("Edit Expected reduction (%) and Planned action. Results update after confirming an edit. 0% = no improvement · 100% = expected elimination.")
    context = f"{area}|{model}|{start}|{end}"
    saved = st.session_state.get("_production_actions", {}).get(context, {})
    reductions = {issue: values.get("Expected reduction (%)", 0) for issue, values in saved.items()}
    result = simulate(baseline, planned, reductions)
    rows = result["issues"].copy()
    rows["Last occurrence"] = pd.to_datetime(rows["Last occurrence"]).dt.strftime("%d %b %Y").fillna("Unavailable")
    rows["Historical PPM"] = rows["Historical PPM"].round().astype(int)
    rows["Planned action"] = [saved.get(issue, {}).get("Planned action", "") for issue in rows["Defect"]]
    rows = rows[["Defect", "NG PCBs", "Historical PPM", "Last occurrence", "Without actions", "Expected reduction (%)", "With actions", "Planned action"]]
    fingerprint = sha1((context + str(planned) + str(st.session_state.get('_production_reset', 0)) + rows[['Defect','NG PCBs','Last occurrence']].to_json()).encode()).hexdigest()[:16]
    editor_key = f"production_editor_{fingerprint}"
    if rows.empty:
        st.info("No classified defects were recorded for this model and period. The historical forecast is zero; this does not establish that future production will be defect-free.")
    else:
        st.data_editor(rows, hide_index=True, width="stretch", height=min(440, 36 * (len(rows) + 1) + 3), key=editor_key,
            on_change=_save_actions, args=(editor_key, context, rows["Defect"].tolist()),
            disabled=["Defect", "NG PCBs", "Historical PPM", "Last occurrence", "Without actions", "With actions"],
            column_config={"Defect":st.column_config.TextColumn(width="medium"),
                "NG PCBs":st.column_config.NumberColumn(format="%d",width="small"),
                "Historical PPM":st.column_config.NumberColumn(format="%d",width="small"),
                "Without actions":st.column_config.NumberColumn("Forecast · No action",format="%d",width="small"),
                "Expected reduction (%)":st.column_config.NumberColumn("Reduction (%) ✎",min_value=0,max_value=100,step=1,format="%.0f%%",width="small"),
                "With actions":st.column_config.NumberColumn("Forecast · Adjusted",format="%d",width="small"),
                "Planned action":st.column_config.TextColumn("Planned action ✎",width="large")})
    st.markdown(f"### Scenario summary · {area}")
    summary = []
    for item in directory:
        if item["area"] != area: continue
        source = item["source"]
        metric = result["metrics"].get(source)
        pct = item["direction"] == "min"
        target = f"≥ {item['target']*100:.2f}%" if pct else f"≤ {item['target']:,.0f} PPM"
        if metric:
            before, after = metric["values"]
            values = [f"{value*100:.2f}%" if pct else f"{value:,.0f} PPM" for value in (before, after)]
            impact = f"{(after-before)*100:+.2f} pp" if pct else f"{after-before:+,.0f} PPM"
        else:
            values = ["Not simulated"] * 2
            impact = "Requires Assembly input + duty defects" if source == "smt_assembly_duty" else "Requires model inspection data"
        summary.append({"KPI / Indicator":item["kpi"], "Target":target, "Without actions":values[0], "With actions":values[1], "Impact":impact})
    before, after = result["totals"]
    improvement = f"{(1-after/before)*100:.0f}%" if before else "0%"
    summary.extend([
        {"KPI / Indicator":"Expected classified NG PCBs", "Target":"—", "Without actions":str(before), "With actions":str(after), "Impact":f"{after-before:+d} PCBs"},
        {"KPI / Indicator":"Expected improvement", "Target":"—", "Without actions":"—", "With actions":improvement, "Impact":f"{before-after} fewer expected NG PCBs"},
    ])
    st.dataframe(pd.DataFrame(summary), hide_index=True, width="stretch", height=255)
    st.caption("Forecasts are rounded up; KPIs use the rounded unique-PCB estimates. Overlapping defects are not added together. For mixed-defect PCBs, reductions are assumed independent and every defect must be eliminated for the PCB to pass. Estimates cannot exceed planned input.")
    controls = st.columns([4, 1])
    with controls[0]: st.markdown("### Expected defects in the next production")
    with controls[1]: st.button("Reset reductions", on_click=_reset_actions, args=(context,), width="stretch", key="production_reset_button")
    if not rows.empty:
        chart_rows = result["issues"].head(15).iloc[::-1]
        figure = go.Figure()
        for label, column, color in [("Without actions", "Without actions", "#AFC3DE"), ("With actions", "With actions", "#2563EB")]:
            figure.add_bar(name=label, y=chart_rows["Defect"], x=chart_rows[column], orientation="h", marker_color=color, text=chart_rows[column], textposition="outside", cliponaxis=False)
        figure.update_layout(height=max(270, 55*len(chart_rows)), barmode="group", bargap=.24,
            margin=dict(l=5,r=45,t=30,b=5),paper_bgcolor="white",plot_bgcolor="white",
            font=dict(family="Segoe UI, Arial",size=13,color="#14243B"), legend=dict(orientation="h",y=1.1,x=0),
            xaxis=dict(title="Expected defect PCBs",rangemode="tozero",gridcolor="#E4ECF7"),yaxis=dict(showgrid=False))
        st.plotly_chart(figure, width="stretch", key="production_forecast_chart")
        if len(rows)>15: st.caption("Chart shows the 15 most frequent defects. All defects remain available in the table and KPI calculations.")
    st.caption("Simulation assumptions, not measured results. Grouping uses repair conclusion, falling back to defect phenomenon. Last occurrence uses the failure date; historical uploads and official KPIs are unchanged.")
