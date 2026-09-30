"""Compact, model-scoped daily KPI trends for the Home page."""

from __future__ import annotations

from html import escape

import pandas as pd

def _daily_input(rows: pd.DataFrame, date_column: str) -> pd.DataFrame:
    if rows.empty:
        return pd.DataFrame(columns=["Model", "Date", "Input"])
    daily = rows[["Model", date_column, "Input"]].copy()
    daily["Date"] = pd.to_datetime(daily[date_column], errors="coerce").dt.normalize()
    daily["Input"] = pd.to_numeric(daily["Input"], errors="coerce").fillna(0)
    daily = daily[daily["Date"].notna() & daily["Input"].gt(0)]
    return daily.groupby(["Model", "Date"], as_index=False)["Input"].sum()


def _distinct_boards(rows: pd.DataFrame, date_column: str, pcb_column: str) -> pd.DataFrame:
    if rows.empty:
        return pd.DataFrame(columns=["Model", "Date", "Defects"])
    defects = rows[["Model", date_column, pcb_column]].copy()
    defects["Date"] = pd.to_datetime(defects[date_column], errors="coerce").dt.normalize()
    defects = defects[defects["Date"].notna()]
    return (
        defects.groupby(["Model", "Date"], as_index=False)[pcb_column]
        .nunique()
        .rename(columns={pcb_column: "Defects"})
    )


def _finish_daily(
    inputs: pd.DataFrame,
    defects: pd.DataFrame,
    validation: pd.DataFrame,
    coverage_start,
    coverage_end,
) -> pd.DataFrame:
    daily = inputs.merge(defects, on=["Model", "Date"], how="left")
    daily = daily.merge(
        validation.rename(columns={"Defects": "ValidationDefects"}),
        on=["Model", "Date"], how="left",
    )
    for column in ("Defects", "ValidationDefects"):
        daily[column] = daily[column].fillna(0).astype(int)
    covered = (
        daily["Date"].between(pd.Timestamp(coverage_start), pd.Timestamp(coverage_end))
        if coverage_start is not None and coverage_end is not None
        else pd.Series(False, index=daily.index)
    )
    daily["Status"] = "Valid"
    daily.loc[~covered, "Status"] = "Awaiting FPY defects"
    daily.loc[daily["ValidationDefects"].gt(daily["Input"]) & covered, "Status"] = "Defects exceed input"
    daily["PPM"] = daily["Defects"] / daily["Input"] * 1_000_000
    daily.loc[daily["Status"].ne("Valid"), "PPM"] = float("nan")
    return daily.sort_values(["Model", "Date"]).reset_index(drop=True)


def smt_model_daily(analysis: dict) -> pd.DataFrame:
    """Use the validated SMT Process scope: unique classified NG PCBs per day/model."""
    source_input = analysis["selected_input"]
    if "Granularity" in source_input:
        source_input = source_input[source_input["Granularity"].eq("daily")]
    inputs = _daily_input(source_input, "BeginDate")
    confirmed = analysis["covered_raw"]
    confirmed = confirmed[~confirmed["IsRejudgeOK"].fillna(False).astype(bool)]
    classified = confirmed[confirmed["FailureType"].isin(("Functional Failure", "Appearance Failure"))]
    defects = _distinct_boards(classified, "KPIDate", "PCB")
    return _finish_daily(
        inputs, defects, defects,
        analysis.get("source_defect_start"), analysis.get("source_defect_end"),
    )


def assembly_model_daily(metrics: dict) -> pd.DataFrame:
    """Use the validated Assembly Function Mando scope and daily input check."""
    inputs = _daily_input(metrics["inputs"], "Date")
    confirmed = metrics["defects"]
    mando = confirmed[confirmed["IsFunctionMando"].fillna(False).astype(bool)]
    classified = confirmed[confirmed["FailureType"].isin(("Funcional", "Aparência"))]
    return _finish_daily(
        inputs,
        _distinct_boards(mando, "DefectDate", "PCBNormalized"),
        _distinct_boards(classified, "DefectDate", "PCBNormalized"),
        metrics.get("source_defect_start"), metrics.get("source_defect_end"),
    )


def recent_models(smt_daily: pd.DataFrame, assembly_daily: pd.DataFrame) -> list[dict]:
    """Rank by latest FPY input date, then that day's input and model name."""
    combined = pd.concat(
        [frame[["Model", "Date", "Input"]] for frame in (smt_daily, assembly_daily) if not frame.empty],
        ignore_index=True,
    ) if not smt_daily.empty or not assembly_daily.empty else pd.DataFrame(columns=["Model", "Date", "Input"])
    if combined.empty:
        return []
    latest = combined.groupby("Model")["Date"].max().rename("LatestInput")
    latest_volume = combined.merge(latest, on="Model")
    latest_volume = latest_volume[latest_volume["Date"].eq(latest_volume["LatestInput"])]
    latest_volume = latest_volume.groupby("Model")["Input"].sum().rename("LatestDayInput")
    ranking = pd.concat([latest, latest_volume], axis=1).reset_index()
    ranking = ranking[ranking["Model"].astype(str).str.strip().ne("")]
    ranking = ranking.sort_values(
        ["LatestInput", "LatestDayInput", "Model"], ascending=[False, False, True]
    )
    return ranking.to_dict("records")


def mini_trend_svg(daily: pd.DataFrame, target: float, color: str) -> str:
    """Small responsive SVG; missing/blocked days break the trend line."""
    recent = daily.tail(10).reset_index(drop=True)
    if recent.empty:
        return '<div class="home-model-empty">No FPY input for this model in the selected period.</div>'
    values = pd.to_numeric(recent["PPM"], errors="coerce")
    top = max(float(target) * 1.2, float(values.max()) * 1.15 if values.notna().any() else 0, 1)
    left, right, top_y, bottom_y = 38, 493, 11, 77

    def x_at(index: int) -> float:
        return left + (right - left) * (index + 0.5) / len(recent)

    def y_at(value: float) -> float:
        return bottom_y - min(value / top, 1) * (bottom_y - top_y)

    target_y = y_at(float(target))
    elements = [
        '<svg class="home-model-svg" viewBox="0 0 500 105" role="img" '
        'aria-label="Daily PPM trend with target line">',
        f'<line x1="{left}" y1="{bottom_y}" x2="{right}" y2="{bottom_y}" stroke="#CAD7E7"/>',
        f'<line x1="{left}" y1="{target_y:.1f}" x2="{right}" y2="{target_y:.1f}" '
        'stroke="#E56B2F" stroke-width="1.5" stroke-dasharray="5 4"/>',
        f'<text x="2" y="{target_y + 3:.1f}" fill="#BA5627" font-size="9">'
        f'{target:,.0f}</text>',
    ]
    segment = []

    def flush_segment() -> None:
        if len(segment) >= 2:
            points = " ".join(f"{x:.1f},{y:.1f}" for x, y in segment)
            elements.append(
                f'<polyline points="{points}" fill="none" stroke="{color}" '
                'stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>'
            )
        segment.clear()

    for index, row in recent.iterrows():
        value = values.iloc[index]
        if pd.isna(value):
            flush_segment()
        else:
            point = (x_at(index), y_at(float(value)))
            segment.append(point)
            elements.append(
                f'<circle cx="{point[0]:.1f}" cy="{point[1]:.1f}" r="3.6" '
                f'fill="{color}" stroke="white" stroke-width="1"/>'
            )
        if index == 0 or index == len(recent) - 1 or index % 2 == 0:
            label = pd.Timestamp(row["Date"]).strftime("%d/%m")
            elements.append(
                f'<text x="{x_at(index):.1f}" y="99" text-anchor="middle" '
                f'fill="#6B7F9B" font-size="9">{escape(label)}</text>'
            )
    flush_segment()
    elements.append("</svg>")
    return "".join(elements)
