"""Model-level Home trends using the portal's validated source rows.

The input and defect frames must come from the existing SMT/Assembly KPI flows.
No summarized input is spread across days to manufacture a daily KPI.
"""

from __future__ import annotations

from datetime import date

import pandas as pd


KPI_OPTIONS = {
    "SMT": ("Functional Pass Rate", "SMT Process NG Rate (PPM)", "Assembly SMT Process Duty NG Rate (PPM)"),
    "Assembly": ("Functional Pass Rate", "Appearance Pass Rate", "Function Mando (PPM)"),
}

KPI_TARGETS = {
    ("SMT", "Functional Pass Rate"): "smt_function",
    ("SMT", "SMT Process NG Rate (PPM)"): "smt_process",
    ("SMT", "Assembly SMT Process Duty NG Rate (PPM)"): "smt_assembly_duty",
    ("Assembly", "Functional Pass Rate"): "assembly_function",
    ("Assembly", "Appearance Pass Rate"): "assembly_appearance",
    ("Assembly", "Function Mando (PPM)"): "assembly_mando",
}


def _period(timestamp, grain: str):
    day = pd.Timestamp(timestamp).normalize()
    if grain == "Days":
        return day
    return day.to_period("W-SUN" if grain == "Weeks" else "M").start_time


def period_label(period, grain: str) -> str:
    day = pd.Timestamp(period)
    if grain == "Days":
        return day.strftime("%d/%m")
    if grain == "Weeks":
        return f"WK{day.isocalendar().week:02d}"
    return day.strftime("%b %Y")


def _period_end(period, grain: str):
    day = pd.Timestamp(period)
    if grain == "Days":
        return day + pd.Timedelta(days=1)
    if grain == "Weeks":
        return day + pd.Timedelta(days=7)
    return day + pd.offsets.MonthBegin(1)


def _input_by_period(source: pd.DataFrame, area: str, grain: str):
    if source is None or source.empty:
        return {}, set()
    rows = source.copy()
    start_col = "BeginDate" if area == "SMT" else "Date"
    rows["_Start"] = pd.to_datetime(rows[start_col], errors="coerce").dt.normalize()
    rows = rows.dropna(subset=["_Start"])
    rows["_Period"] = rows["_Start"].map(lambda value: _period(value, grain))
    if area == "SMT":
        rows["_End"] = pd.to_datetime(rows["EndDateExclusive"], errors="coerce")
        incompatible = rows["_End"].gt(rows["_Period"].map(lambda value: _period_end(value, grain)))
        if "Granularity" in rows:
            source_level = rows["Granularity"].fillna("daily").astype(str).str.lower().map(
                {"daily": 0, "weekly": 1, "monthly": 2}
            ).fillna(2)
            requested_level = {"Days": 0, "Weeks": 1, "Months": 2}[grain]
            incompatible |= source_level.gt(requested_level)
    else:
        incompatible = pd.Series(False, index=rows.index)
    omitted = set(zip(rows.loc[incompatible, "Model"], rows.loc[incompatible, "_Period"]))
    rows = rows.loc[~incompatible]
    grouped = rows.groupby(["Model", "_Period"], observed=True)["Input"].sum()
    return {(str(model), period): int(value) for (model, period), value in grouped.items()}, omitted


def _defects_by_period(source: pd.DataFrame, area: str, grain: str):
    if source is None or source.empty:
        return {}
    rows = source.copy()
    date_col = "KPIDate" if area == "SMT" else "DefectDate"
    pcb_col = "PCB" if area == "SMT" else "PCBNormalized"
    rows["_Date"] = pd.to_datetime(rows[date_col], errors="coerce").dt.normalize()
    rows = rows.dropna(subset=["_Date"])
    if area == "SMT":
        rows = rows.loc[~rows["IsRejudgeOK"].fillna(False)]
    rows["_Period"] = rows["_Date"].map(lambda value: _period(value, grain))
    result = {}
    for (model, period), group in rows.groupby(["Model", "_Period"], observed=True):
        if area == "SMT":
            functional = group["FailureType"].eq("Functional Failure")
            classified = group["FailureType"].isin(["Functional Failure", "Appearance Failure"])
            mando = pd.Series(False, index=group.index)
            appearance = group["FailureType"].eq("Appearance Failure")
            smt_duty = pd.Series(False, index=group.index)
        else:
            functional = group["FailureType"].eq("Funcional")
            classified = group["FailureType"].isin(["Funcional", "Aparência"])
            mando = group["IsFunctionMando"].fillna(False)
            appearance = group["FailureType"].eq("Aparência")
            smt_duty = group["IsSMTDuty"].fillna(False)
        result[(str(model), period)] = {
            "functional": int(group.loc[functional, pcb_col].nunique()),
            "appearance": int(group.loc[appearance, pcb_col].nunique()),
            "classified": int(group.loc[classified, pcb_col].nunique()),
            "mando": int(group.loc[mando, pcb_col].nunique()),
            "smt_duty": int(group.loc[smt_duty, pcb_col].nunique()),
        }
    return result


def build_home_kpi_rows(
    area: str,
    kpi: str,
    grain: str,
    models: list[str],
    start_date: date,
    end_date: date,
    inputs: pd.DataFrame,
    defects: pd.DataFrame,
) -> pd.DataFrame:
    """One row per model and observed period; rates are recalculated from counts."""
    if area not in KPI_OPTIONS or kpi not in KPI_OPTIONS[area]:
        raise ValueError(f"Unknown Home KPI: {area} / {kpi}")
    if grain not in {"Days", "Weeks", "Months"}:
        raise ValueError(f"Unknown time scale: {grain}")
    source_area = "Assembly" if kpi == "Assembly SMT Process Duty NG Rate (PPM)" else area
    input_map, omitted = _input_by_period(inputs, source_area, grain)
    defect_map = _defects_by_period(defects, source_area, grain)
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    periods = sorted({period for model, period in input_map if model in models and start <= _period_end(period, grain) - pd.Timedelta(days=1) and period <= end})
    records = []
    for model in models:
        for period in periods:
            key = (model, period)
            count = input_map.get(key, 0)
            ng = 0
            status = "No data"
            value = None
            if key in omitted:
                status = "Input resolution unavailable"
            elif key in input_map and count:
                counts = defect_map.get(key, {"functional": 0, "appearance": 0, "classified": 0,
                                              "mando": 0, "smt_duty": 0})
                if kpi == "Assembly SMT Process Duty NG Rate (PPM)":
                    ng = counts["smt_duty"]
                    if ng > count:
                        status = "Blocked: SMT-duty NG PCB exceeds input"
                    else:
                        value = ng / count * 1_000_000
                        status = "Valid"
                elif counts["classified"] > count:
                    status = "Blocked: classified NG PCB exceeds input"
                elif kpi == "Functional Pass Rate":
                    ng = counts["functional"]
                    value = (count - ng) / count
                    status = "Valid"
                elif kpi == "Appearance Pass Rate":
                    ng = counts["appearance"]
                    value = (count - ng) / count
                    status = "Valid"
                elif kpi == "SMT Process NG Rate (PPM)":
                    ng = counts["classified"]
                    value = ng / count * 1_000_000
                    status = "Valid"
                else:
                    ng = counts["mando"]
                    value = ng / count * 1_000_000
                    status = "Valid"
            records.append({
                "Area": area, "Model": model, "PeriodDate": period,
                "Period": period_label(period, grain), "KPI": kpi, "Value": value,
                "DefectPCBs": ng, "Input": count, "Status": status,
            })
    return pd.DataFrame.from_records(records, columns=[
        "Area", "Model", "PeriodDate", "Period", "KPI", "Value",
        "DefectPCBs", "Input", "Status",
    ])
