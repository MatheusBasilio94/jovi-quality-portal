import re
from datetime import datetime
from io import BytesIO
from pathlib import Path

import pandas as pd
import streamlit as st


PCB_ALIASES = ["pcb no", "pcb no.", "pcb number", "pcb sn", "sn"]
OPERATE_TIME_ALIASES = ["operate time", "operation time", "input time"]
PN_ALIASES = ["pn", "part number", "model", "product model"]


def compact_header(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).strip().lower())


def find_column(columns, aliases: list[str]):
    by_compact = {compact_header(column): column for column in columns}
    for alias in aliases:
        match = by_compact.get(compact_header(alias))
        if match is not None:
            return match
    return None


def normalize_serial(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip().upper()
    if text.lower() in {"", "nan", "none", "<na>"}:
        return ""
    if re.fullmatch(r"\d+\.0", text):
        text = text[:-2]
    return text


def parse_operate_time(series: pd.Series) -> pd.Series:
    text = series.astype(str).str.strip()
    year_first = text.str.match(r"^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}", na=False)
    parsed = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
    if year_first.any():
        try:
            parsed.loc[year_first] = pd.to_datetime(text.loc[year_first], errors="coerce", yearfirst=True, format="mixed")
        except TypeError:
            parsed.loc[year_first] = pd.to_datetime(text.loc[year_first], errors="coerce", yearfirst=True)
    remaining = ~year_first
    if remaining.any():
        try:
            parsed.loc[remaining] = pd.to_datetime(text.loc[remaining], errors="coerce", dayfirst=True, format="mixed")
        except TypeError:
            parsed.loc[remaining] = pd.to_datetime(text.loc[remaining], errors="coerce", dayfirst=True)
    return parsed


def read_csv_flexible(data: bytes) -> pd.DataFrame:
    last_error = None
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin1"):
        try:
            return pd.read_csv(BytesIO(data), dtype=str, sep=None, engine="python", encoding=encoding)
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"Unable to read CSV: {last_error}")


def read_source(data: bytes, filename: str) -> tuple[pd.DataFrame, int]:
    suffix = Path(filename).suffix.lower()
    if suffix == ".csv":
        frame = read_csv_flexible(data)
        frame.columns = [str(column).strip() for column in frame.columns]
        return frame, 0
    if suffix not in {".xlsx", ".xls"}:
        raise RuntimeError(f"Unsupported input format: {suffix}")

    for header_row in range(10):
        try:
            sample = pd.read_excel(BytesIO(data), dtype=str, header=header_row, nrows=8)
            if find_column(sample.columns, PCB_ALIASES) and find_column(sample.columns, OPERATE_TIME_ALIASES):
                frame = pd.read_excel(BytesIO(data), dtype=str, header=header_row)
                frame.columns = [str(column).strip() for column in frame.columns]
                return frame, header_row
        except Exception:
            continue
    raise RuntimeError("Could not find the PCB No. and Operate Time columns in the uploaded file.")


@st.cache_data(show_spinner=False)
def analyze_smt_input_bytes(data: bytes, filename: str) -> dict:
    frame, header_row = read_source(data, filename)
    pcb_column = find_column(frame.columns, PCB_ALIASES)
    operate_time_column = find_column(frame.columns, OPERATE_TIME_ALIASES)
    pn_column = find_column(frame.columns, PN_ALIASES)
    if pcb_column is None or operate_time_column is None:
        raise RuntimeError("The file must contain PCB No. and Operate Time columns.")

    working = pd.DataFrame(index=frame.index)
    working["SourceRow"] = frame.index + header_row + 2
    working["PCB No."] = frame[pcb_column].map(normalize_serial)
    working["Operate Time"] = parse_operate_time(frame[operate_time_column])
    working["PN"] = frame[pn_column].fillna("Unknown").astype(str).str.strip() if pn_column else "Unknown"
    working.loc[working["PN"].isin({"", "nan", "None", "<NA>"}), "PN"] = "Unknown"

    missing_pcb = int(working["PCB No."].eq("").sum())
    invalid_operate_time = int(working["Operate Time"].isna().sum())
    valid = working[working["PCB No."].ne("") & working["Operate Time"].notna()].copy()
    valid = valid.sort_values(["Operate Time", "SourceRow"]).reset_index(drop=True)
    valid["Input Date"] = valid["Operate Time"].dt.normalize()

    if valid.empty:
        raise RuntimeError("No rows with a valid PCB No. and Operate Time were found.")

    period_analysis = summarize_smt_period(valid, valid["Operate Time"].min(), valid["Operate Time"].max())
    return {
        "filename": filename,
        "raw_rows": int(len(frame)),
        "valid_rows": int(len(valid)),
        "missing_pcb": missing_pcb,
        "invalid_operate_time": invalid_operate_time,
        "minimum_operate_time": valid["Operate Time"].min(),
        "maximum_operate_time": valid["Operate Time"].max(),
        "valid_detail": valid,
        **period_analysis,
    }


def summarize_smt_period(valid: pd.DataFrame, start, end) -> dict:
    start_time = pd.Timestamp(start)
    end_time = pd.Timestamp(end)
    period = valid[valid["Operate Time"].between(start_time, end_time, inclusive="both")].copy()
    period = period.sort_values(["Operate Time", "SourceRow"]).reset_index(drop=True)

    first_by_serial = period.drop_duplicates(subset=["PCB No."], keep="first").copy()
    first_time_map = first_by_serial.set_index("PCB No.")["Operate Time"]
    duplicate_rows = period[period.duplicated(subset=["PCB No."], keep="first")].copy()
    duplicate_rows["First Operate Time"] = duplicate_rows["PCB No."].map(first_time_map)
    duplicate_rows["Repeated Across Date"] = (
        duplicate_rows["Operate Time"].dt.normalize() != duplicate_rows["First Operate Time"].dt.normalize()
    )

    repeated_serials = period[period.duplicated(subset=["PCB No."], keep=False)]["PCB No."].nunique()
    cross_date_serials = (
        period.groupby("PCB No.")["Input Date"].nunique().gt(1).sum()
        if not period.empty
        else 0
    )

    daily = (
        first_by_serial.groupby("Input Date", as_index=False)
        .agg(Input=("PCB No.", "count"), Models=("PN", "nunique"))
        .sort_values("Input Date")
    )
    by_model = (
        first_by_serial.groupby("PN", as_index=False)
        .agg(Input=("PCB No.", "count"))
        .sort_values("Input", ascending=False)
    )
    daily_by_model = (
        first_by_serial.groupby(["Input Date", "PN"], as_index=False)
        .agg(Input=("PCB No.", "count"))
        .sort_values(["Input Date", "Input"], ascending=[True, False])
    )

    return {
        "period_start": start_time,
        "period_end": end_time,
        "period_rows": int(len(period)),
        "unique_input": int(len(first_by_serial)),
        "duplicates_removed": int(len(duplicate_rows)),
        "repeated_serials": int(repeated_serials),
        "cross_date_serials": int(cross_date_serials),
        "daily": daily,
        "by_model": by_model,
        "daily_by_model": daily_by_model,
        "unique_detail": first_by_serial,
        "duplicate_detail": duplicate_rows,
    }


def metric_card(label: str, value: str, note: str, color: str) -> None:
    st.markdown(
        f"<div class='metric-card'><div class='metric-label'>{label}</div><div class='metric-value' style='color:{color};'>{value}</div><div class='small-muted'>{note}</div></div>",
        unsafe_allow_html=True,
    )


def input_chart(frame: pd.DataFrame, color: str):
    import plotly.graph_objects as go

    chart = go.Figure()
    chart.add_bar(
        x=frame["Input Date"],
        y=frame["Input"],
        marker_color=color,
        text=frame["Input"],
        textposition="outside",
        hovertemplate="%{x|%d/%m/%Y}<br>Input: %{y:,}<extra></extra>",
    )
    chart.update_layout(
        title="Unique SMT input by day",
        height=430,
        margin=dict(l=20, r=20, t=60, b=30),
        xaxis_title="Operate Time date",
        yaxis_title="Unique PCB No.",
        showlegend=False,
        paper_bgcolor="white",
        plot_bgcolor="white",
    )
    return chart


def render_smt_quality_dashboard(color: str) -> None:
    st.markdown(f"<h1 class='section-title' style='color:{color};'>SMT · Quality Dashboard</h1>", unsafe_allow_html=True)
    st.markdown(
        "<div class='card'><h3>Daily input rule</h3><p class='small-muted'>Operate Time defines the input date. "
        "PCB No. is the unique serial identifier. The period is filtered first; repeated serials are then counted only once inside that selected period.</p></div>",
        unsafe_allow_html=True,
    )
    uploaded = st.file_uploader(
        "SMT input file",
        type=["xlsx", "xls", "csv"],
        key="smt_input_upload",
        help="Required columns: PCB No. and Operate Time. PN is optional and is used for model breakdown.",
    )
    if uploaded is None:
        st.info("Upload the SMT input file to calculate the real daily input without estimating or distributing totals.")
        return

    try:
        source_analysis = analyze_smt_input_bytes(uploaded.getvalue(), uploaded.name)
    except Exception as exc:
        st.error(f"Unable to analyze the SMT input file: {exc}")
        return

    minimum_time = source_analysis["minimum_operate_time"]
    maximum_time = source_analysis["maximum_operate_time"]
    date_columns = st.columns(4)
    with date_columns[0]:
        start_date = st.date_input(
            "Start date",
            value=minimum_time.date(),
            min_value=minimum_time.date(),
            max_value=maximum_time.date(),
            key="smt_input_start_date",
        )
    with date_columns[1]:
        start_clock = st.time_input("Start time", value=minimum_time.time(), key="smt_input_start_time")
    with date_columns[2]:
        end_date = st.date_input(
            "End date",
            value=maximum_time.date(),
            min_value=minimum_time.date(),
            max_value=maximum_time.date(),
            key="smt_input_end_date",
        )
    with date_columns[3]:
        end_clock = st.time_input("End time", value=maximum_time.time(), key="smt_input_end_time")

    selected_start = pd.Timestamp(datetime.combine(start_date, start_clock))
    selected_end = pd.Timestamp(datetime.combine(end_date, end_clock))
    if selected_end < selected_start:
        st.error("End date/time must be after start date/time.")
        return

    period_analysis = summarize_smt_period(source_analysis["valid_detail"], selected_start, selected_end)
    analysis = {**source_analysis, **period_analysis}
    st.caption(
        f"Active period: {selected_start.strftime('%d/%m/%Y %H:%M:%S')} to "
        f"{selected_end.strftime('%d/%m/%Y %H:%M:%S')} · duplicates are removed only inside this interval."
    )

    columns = st.columns(4)
    with columns[0]:
        metric_card("Unique SMT Input", f"{analysis['unique_input']:,}", "One PCB No. = one input", color)
    with columns[1]:
        metric_card("Rows in Period", f"{analysis['period_rows']:,}", analysis["filename"], color)
    with columns[2]:
        metric_card("Duplicates Removed", f"{analysis['duplicates_removed']:,}", f"{analysis['repeated_serials']:,} repeated SNs", color)
    with columns[3]:
        metric_card("Cross-date Repeats", f"{analysis['cross_date_serials']:,}", "Within selected period", color)

    if analysis["missing_pcb"] or analysis["invalid_operate_time"]:
        st.warning(
            f"Rows excluded due to invalid required data: {analysis['missing_pcb']} without PCB No. and "
            f"{analysis['invalid_operate_time']} without a valid Operate Time."
        )
    if analysis["cross_date_serials"]:
        st.info(
            f"{analysis['cross_date_serials']} repeated PCB No. value(s) appeared on different dates. "
            "Each was counted once at its earliest Operate Time inside the selected period."
        )

    overview_tab, model_tab, duplicates_tab, details_tab = st.tabs(["Daily Input", "Models", "Duplicate Audit", "Unique Detail"])
    with overview_tab:
        st.plotly_chart(input_chart(analysis["daily"], color), use_container_width=True, config={"displayModeBar": False})
        daily_view = analysis["daily"].copy()
        daily_view["Input Date"] = daily_view["Input Date"].dt.strftime("%d/%m/%Y")
        st.dataframe(daily_view, use_container_width=True, hide_index=True)
    with model_tab:
        st.dataframe(analysis["by_model"], use_container_width=True, hide_index=True, height=390)
        model_daily_view = analysis["daily_by_model"].copy()
        model_daily_view["Input Date"] = model_daily_view["Input Date"].dt.strftime("%d/%m/%Y")
        st.dataframe(model_daily_view, use_container_width=True, hide_index=True, height=390)
    with duplicates_tab:
        if analysis["duplicate_detail"].empty:
            st.success("No repeated PCB No. values were found.")
        else:
            duplicate_view = analysis["duplicate_detail"].copy()
            for column in ["Operate Time", "First Operate Time"]:
                duplicate_view[column] = duplicate_view[column].dt.strftime("%Y-%m-%d %H:%M:%S")
            st.dataframe(duplicate_view, use_container_width=True, hide_index=True, height=430)
            st.download_button(
                "Download duplicate audit CSV",
                data=duplicate_view.to_csv(index=False).encode("utf-8-sig"),
                file_name="smt_input_duplicate_audit.csv",
                mime="text/csv",
                use_container_width=True,
            )
    with details_tab:
        unique_view = analysis["unique_detail"].copy()
        unique_view["Operate Time"] = unique_view["Operate Time"].dt.strftime("%Y-%m-%d %H:%M:%S")
        unique_view["Input Date"] = unique_view["Input Date"].dt.strftime("%Y-%m-%d")
        st.dataframe(unique_view, use_container_width=True, hide_index=True, height=430)
        st.download_button(
            "Download unique SMT input CSV",
            data=unique_view.to_csv(index=False).encode("utf-8-sig"),
            file_name="smt_unique_daily_input.csv",
            mime="text/csv",
            use_container_width=True,
        )
