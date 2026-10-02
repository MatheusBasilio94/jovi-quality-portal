"""Read-only repair throughput and elapsed-time analysis from stored MES exports."""

from __future__ import annotations

from pathlib import Path
import re

import pandas as pd


DISPLAY_COLUMNS = [
    "PCB SN", "Device Barcode", "Area", "Model", "Defect entry", "Repair date",
    "Elapsed (h)", "Repairer", "Repair #", "TestOperation", "Fault Phenomenon",
    "Fault reason", "RepaireRemark", "DutyType",
]


def _text(series: pd.Series) -> pd.Series:
    values = series.fillna("").astype(str).str.strip()
    return values.str.replace(r"\.0$", "", regex=True).replace({"nan": "", "None": "", "NaT": ""})


def _column(frame: pd.DataFrame, *names: str) -> pd.Series:
    by_name = {re.sub(r"[^a-z0-9]", "", str(name).casefold()): name for name in frame.columns}
    for name in names:
        actual = by_name.get(re.sub(r"[^a-z0-9]", "", name.casefold()))
        if actual is not None:
            return frame[actual]
    return pd.Series("", index=frame.index, dtype="object")


def _datetime(series: pd.Series) -> pd.Series:
    text = series.fillna("").astype(str).str.strip()
    year_first = text.str.match(r"^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}", na=False)
    parsed = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
    for mask, kwargs in ((year_first, {"yearfirst": True}), (~year_first, {"dayfirst": True})):
        if not mask.any():
            continue
        try:
            parsed.loc[mask] = pd.to_datetime(text.loc[mask], errors="coerce", format="mixed", **kwargs)
        except TypeError:
            parsed.loc[mask] = pd.to_datetime(text.loc[mask], errors="coerce", **kwargs)
    return parsed


def read_repair_file(path: Path, area: str) -> pd.DataFrame:
    frame = pd.read_excel(path, sheet_name="QueryData", dtype=object)
    if _column(frame, "PCB").eq("").all() and "PCB" not in frame.columns:
        raise ValueError(f"{path.name}: QueryData is missing PCB.")
    if "RepairDate" not in frame.columns:
        raise ValueError(f"{path.name}: QueryData is missing RepairDate.")
    result = pd.DataFrame(index=frame.index)
    result["Area"] = area
    result["PCB SN"] = _text(_column(frame, "PCB"))
    result["Device Barcode"] = _text(_column(frame, "Barcode"))
    result["Model"] = _text(_column(frame, "model", "Model"))
    result["Repairer"] = _text(_column(frame, "Repairer"))
    result["Repair #"] = pd.to_numeric(_column(frame, "RepairTimes"), errors="coerce")
    result["TestOperation"] = _text(_column(frame, "TestOperation"))
    result["Fault Phenomenon"] = _text(_column(frame, "Fault Phenomenon"))
    result["Fault reason"] = _text(_column(frame, "Fault reason", "FaultReason"))
    result["RepaireRemark"] = _text(_column(frame, "RepaireRemark", "RepairRemark"))
    result["DutyType"] = _text(_column(frame, "DutyType"))
    result["Defect entry"] = _datetime(_column(frame, "BadMachEntryTime"))
    result["Repair date"] = _datetime(_column(frame, "RepairDate"))
    test_time = _datetime(_column(frame, "TestTime"))
    # A repair export is a snapshot. Match the same MES event across uploads,
    # while keeping separate defects/repair attempts for the same PCB.
    event_parts = [
        result["PCB SN"].str.casefold(),
        test_time.dt.strftime("%Y-%m-%d %H:%M:%S").fillna(""),
        result["TestOperation"].str.casefold(),
        result["Fault Phenomenon"].str.casefold(),
    ]
    result["EventKey"] = event_parts[0]
    for part in event_parts[1:]:
        result["EventKey"] += "|" + part
    missing_test = test_time.isna()
    result.loc[missing_test, "EventKey"] += (
        "|" + result.loc[missing_test, "Defect entry"].dt.strftime("%Y-%m-%d %H:%M:%S").fillna("")
    )
    result["SourceFile"] = path.name
    result["SourceRow"] = frame.index + 2
    return result


def combine_repair_files(sources: dict[str, list[Path]]) -> tuple[pd.DataFrame, dict]:
    frames: list[pd.DataFrame] = []
    errors: list[str] = []
    file_count = 0
    for area in ("SMT", "Assembly"):
        paths = sorted(sources.get(area, []), key=lambda path: (path.stat().st_mtime_ns, path.name))
        for path in paths:
            try:
                source = read_repair_file(path, area)
            except Exception as exc:
                errors.append(f"{area} · {path.name}: {exc}")
                continue
            source["SourceOrder"] = file_count
            frames.append(source)
            file_count += 1
    if not frames:
        return pd.DataFrame(), {"files": 0, "errors": errors, "duplicates": 0, "undated": 0}
    combined = pd.concat(frames, ignore_index=True)
    combined = combined[combined["PCB SN"].ne("")].copy()
    combined.sort_values(["Area", "SourceOrder", "SourceRow"], inplace=True)
    duplicates = int(combined.duplicated(["Area", "EventKey"], keep="last").sum())
    combined.drop_duplicates(["Area", "EventKey"], keep="last", inplace=True)
    undated = int(combined["Repair date"].isna().sum())
    combined = combined[combined["Repair date"].notna()].copy()
    combined["Repair day"] = combined["Repair date"].dt.normalize()
    duration = (combined["Repair date"] - combined["Defect entry"]).dt.total_seconds() / 3600
    combined["Elapsed (h)"] = duration.where(duration.ge(0))
    combined.reset_index(drop=True, inplace=True)
    return combined, {"files": file_count, "errors": errors, "duplicates": duplicates, "undated": undated}


def repair_summary(events: pd.DataFrame) -> dict:
    if events.empty:
        return {"pcbs": 0, "events": 0, "avg_h": None, "median_h": None, "p90_h": None,
                "within_24_pct": None, "coverage_pct": None, "near_zero_pct": None}
    duration = events["Elapsed (h)"].dropna()
    pcbs = events[["Area", "PCB SN"]].drop_duplicates().shape[0]
    return {
        "pcbs": int(pcbs), "events": int(len(events)),
        "avg_h": float(duration.mean()) if not duration.empty else None,
        "median_h": float(duration.median()) if not duration.empty else None,
        "p90_h": float(duration.quantile(.9)) if not duration.empty else None,
        "within_24_pct": float(duration.le(24).mean() * 100) if not duration.empty else None,
        "coverage_pct": float(len(duration) / len(events) * 100),
        "near_zero_pct": float(duration.lt(1 / 60).mean() * 100) if not duration.empty else None,
    }


def daily_summary(events: pd.DataFrame, start_date, end_date) -> pd.DataFrame:
    days = pd.date_range(start_date, end_date, freq="D")
    rows = []
    for day in days:
        day_events = events[events["Repair day"].eq(day)]
        metrics = repair_summary(day_events)
        rows.append({"Date": day, "SMT": int(day_events.loc[day_events["Area"].eq("SMT"), "PCB SN"].nunique()),
                     "Assembly": int(day_events.loc[day_events["Area"].eq("Assembly"), "PCB SN"].nunique()),
                     "Total PCBs": metrics["pcbs"], "Repair events": metrics["events"],
                     "Avg elapsed (h)": metrics["avg_h"], "Median (h)": metrics["median_h"],
                     "P90 (h)": metrics["p90_h"], "Coverage (%)": metrics["coverage_pct"]})
    return pd.DataFrame(rows)
