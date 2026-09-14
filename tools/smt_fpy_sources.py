"""MES FPY source contract. The MES, not the portal, selects eligible defects."""
import json
from io import BytesIO
from pathlib import Path

import pandas as pd


def read_detail(data: bytes, filename: str) -> tuple[pd.DataFrame, dict]:
    try:
        frame = pd.read_excel(BytesIO(data), sheet_name="Detail", dtype=object)
        summary = pd.read_excel(BytesIO(data), sheet_name="BadMachine", dtype=object)
    except Exception as exc:
        raise ValueError(f"{filename}: upload the MES FPY detail export with Detail and BadMachine sheets. General QueryData defect exports are no longer accepted.") from exc
    required = {"PCB", "model", "BadMachEntryTime", "TestOperation"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"{filename}: missing FPY columns: {', '.join(sorted(missing))}.")
    pcb = frame["PCB"].fillna("").astype(str).str.strip()
    model = frame["model"].fillna("").astype(str).str.strip()
    entry = pd.to_datetime(frame["BadMachEntryTime"], format="mixed", errors="coerce")
    if (pcb.eq("") | model.eq("") | entry.isna()).any():
        raise ValueError(f"{filename}: every FPY row must have PCB, model and a valid BadMachEntryTime. No rows were discarded.")
    columns = ["OnceDamage", "2TimesDamage", "3TimesDamage", "4TimesDamage", "5TimesDamage", "6TimesDamage"]
    if len(summary) != 1 or not set(columns).issubset(summary.columns):
        raise ValueError(f"{filename}: invalid BadMachine summary.")
    counts = pd.to_numeric(summary.iloc[0][columns], errors="coerce")
    if counts.isna().any() or counts.lt(0).any() or counts.mod(1).ne(0).any():
        raise ValueError(f"{filename}: invalid BadMachine counts.")
    expected_boards = int(counts.sum())
    expected_rows = int(sum((i + 1) * value for i, value in enumerate(counts)))
    histogram = pcb.value_counts().value_counts()
    if len(frame) != expected_rows or pcb.nunique() != expected_boards or any(int(histogram.get(i + 1, 0)) != int(n) for i, n in enumerate(counts)):
        raise ValueError(f"{filename}: Detail is incomplete or inconsistent with BadMachine (expected {expected_rows} records / {expected_boards} PCBs; found {len(frame)} / {pcb.nunique()}). Export the complete report again.")
    return frame, {"MESBadMachine": expected_boards, "MESDetailRecords": expected_rows}


def validate_pair(model: pd.DataFrame, org_audit: dict, detail: pd.DataFrame) -> dict:
    """Require the two reports to describe the same full period and model population."""
    if not org_audit["OrgReconciles"] or org_audit["InvalidRows"]:
        raise ValueError("Input summary is incomplete or ModelData and OrgDisplay do not reconcile.")
    periods = model[["BeginDate", "EndDateExclusive"]].drop_duplicates()
    if len(periods) != 1 or model["Model"].duplicated().any():
        raise ValueError("Upload one complete FPY summary per period, with one row per model.")
    begin, end = periods.iloc[0]
    if not detail.empty and (~detail["EntryTime"].ge(begin) | ~detail["EntryTime"].lt(end)).any():
        raise ValueError("FPY detail includes entries outside the input summary period. Check the MES query dates.")
    expected = model.set_index("Model")["BadMachine"]
    actual = detail.groupby("Model")["PCB"].nunique()
    check = pd.concat([expected.rename("Expected"), actual.rename("Actual")], axis=1).fillna(0)
    missing_models = set(actual.index) - set(expected.index)
    mismatches = check[check.Expected.ne(check.Actual)]
    if missing_models or not mismatches.empty:
        items = [f"{name}: summary {int(row.Expected)}, detail {int(row.Actual)}" for name, row in mismatches.iterrows()]
        raise ValueError("FPY summary/detail do not reconcile by model. " + "; ".join(items[:12]))
    return {"start": begin.date().isoformat(), "end": (end - pd.Timedelta(days=1)).date().isoformat(), "input": int(model.Input.sum()), "bad_machine": int(expected.sum()), "records": len(detail)}


def active_pairs(directory: Path) -> list[dict]:
    """A manifest is written last, so incomplete uploads cannot enter calculations."""
    latest = {}
    for path in sorted(directory.glob("*.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("schema") != "mes-fpy-pair-v1":
            raise ValueError(f"Invalid FPY pair manifest: {path.name}")
        for field in ("input_file", "detail_file"):
            name = value[field]
            if Path(name).name != name or "/" in name or "\\" in name:
                raise ValueError("Invalid FPY source path.")
        value["manifest_file"] = path.name
        key = (value["start"], value["end"])
        previous = latest.get(key)
        if previous is None or (value["uploaded_at"], path.name) > (previous["uploaded_at"], previous["manifest_file"]):
            latest[key] = value
    pairs = sorted(latest.values(), key=lambda x: x["start"])
    for left, right in zip(pairs, pairs[1:]):
        if left["end"] >= right["start"]:
            raise ValueError("FPY source periods overlap. Replace a report for the same complete period or remove the overlapping pair.")
    return pairs
