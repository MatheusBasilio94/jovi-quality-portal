import hashlib
import re
from datetime import timedelta
from html import escape
from io import BytesIO
from pathlib import Path

import pandas as pd
import streamlit as st

from tools.supabase_store import (
    bump_cloud_data_version,
    cloud_store_is_active,
    cloud_store_status,
    delete_object,
    ensure_cloud_data_version,
    sync_prefix_from_cloud,
    upload_bytes,
)
from tools.trend_rules import requested_trend_grain


TOOL_VERSION = "v1.3.1"
SMT_FAILURE_RULE_VERSION = "2026-08-18.1"
PROJECT_DIR = Path(__file__).resolve().parents[1]
SMT_STORE_DIR = PROJECT_DIR / "data_store" / "smt"
SMT_INPUT_DIR = SMT_STORE_DIR / "input"
SMT_DEFECT_DIR = SMT_STORE_DIR / "defects"

MODEL_ALIASES = ["model", "pn", "part number", "product model"]
INPUT_ALIASES = ["input", "produced", "production", "qty"]
BAD_MACHINE_ALIASES = ["badmachine", "bad machine", "bad qty"]
BEGIN_DATE_ALIASES = ["begindate", "begin date", "startdate", "start date"]
END_DATE_ALIASES = ["enddate", "end date"]
LINE_ALIASES = ["displaymode", "display mode", "line"]

SMT_FUNCTIONAL_STATIONS = (
    "Download",
    "PCBA-Testing",
    "Calibration",
    "RF-Testing",
)
SMT_APPEARANCE_STATIONS = (
    "AOI-Checking",
    "Glue dispensing",
    "SMT-Visual-Inspection",
    "depanel station",
    "SMT test Appearance inspection station",
    "X-Ray_Sampling_Station",
)
SMT_FAILURE_TYPE_ORDER = ("Functional Failure", "Appearance Failure", "Unclassified")
SMT_FAILURE_TYPE_COLORS = {
    "Functional Failure": "#C2410C",
    "Appearance Failure": "#1D5FBF",
    "Unclassified": "#64748B",
}


def refresh_chart_period_labels(trend: pd.DataFrame) -> pd.DataFrame:
    """Apply compact display dates after cached calculations are loaded."""
    refreshed = trend.copy()
    if refreshed.empty or "PeriodStart" not in refreshed.columns:
        return refreshed
    grains = refreshed.get("Granularity", pd.Series("Daily", index=refreshed.index)).fillna("Daily").astype(str).str.lower()
    starts = pd.to_datetime(refreshed["PeriodStart"], errors="coerce")
    refreshed["Period"] = starts.dt.strftime("%d/%m")
    monthly = grains.str.startswith("month")
    refreshed.loc[monthly, "Period"] = starts.loc[monthly].dt.strftime("%m/%y")
    return refreshed


def init_smt_store() -> None:
    SMT_INPUT_DIR.mkdir(parents=True, exist_ok=True)
    SMT_DEFECT_DIR.mkdir(parents=True, exist_ok=True)
    cloud_active = cloud_store_is_active()
    if cloud_active:
        data_version = ensure_cloud_data_version()
        sync_prefix_from_cloud(
            "smt/input", SMT_INPUT_DIR, data_version=data_version, cloud_active=True
        )
        sync_prefix_from_cloud(
            "smt/defects", SMT_DEFECT_DIR, data_version=data_version, cloud_active=True
        )


def require_persistent_store_for_smt_writes() -> None:
    status = cloud_store_status()
    if bool(status["configured"]) and not bool(status["active"]):
        raise RuntimeError(
            "Supabase is configured but the portal data has not been migrated yet. "
            "Open About > Cloud data storage and complete the migration before adding or deleting data."
        )


def compact_header(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).strip().lower())


def classify_smt_failure_type(operation: object) -> str:
    normalized_operation = compact_header(clean_text(operation))
    functional = {compact_header(station) for station in SMT_FUNCTIONAL_STATIONS}
    appearance = {compact_header(station) for station in SMT_APPEARANCE_STATIONS}
    if normalized_operation in functional:
        return "Functional Failure"
    if normalized_operation in appearance:
        return "Appearance Failure"
    return "Unclassified"


def find_column(columns, aliases: list[str]):
    by_compact = {compact_header(column): column for column in columns}
    for alias in aliases:
        match = by_compact.get(compact_header(alias))
        if match is not None:
            return match
    return None


def clean_text(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"", "nan", "none", "<na>"} else text


def normalize_code(value: object) -> str:
    text = clean_text(value).upper()
    if re.fullmatch(r"\d+\.0", text):
        text = text[:-2]
    return text


def normalize_model(value: object) -> str:
    return normalize_code(value)


def parse_number_series(series: pd.Series) -> pd.Series:
    text = series.fillna("").astype(str).str.strip().str.replace(" ", "", regex=False)
    both = text.str.contains(",", regex=False) & text.str.contains(".", regex=False)
    comma_decimal = both & (text.str.rfind(",") > text.str.rfind("."))
    text.loc[comma_decimal] = text.loc[comma_decimal].str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
    text.loc[both & ~comma_decimal] = text.loc[both & ~comma_decimal].str.replace(",", "", regex=False)
    comma_only = text.str.contains(",", regex=False) & ~text.str.contains(".", regex=False)
    text.loc[comma_only] = text.loc[comma_only].str.replace(",", ".", regex=False)
    return pd.to_numeric(text, errors="coerce")


def parse_date_series(series: pd.Series) -> pd.Series:
    text = series.fillna("").astype(str).str.strip()
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
    return parsed.dt.normalize()


def period_granularity(start: pd.Timestamp, end_exclusive: pd.Timestamp) -> str:
    duration = int((end_exclusive - start).days)
    if duration == 1:
        return "daily"
    if duration == 7:
        return "weekly"
    if start.day == 1 and end_exclusive.day == 1 and end_exclusive == start + pd.offsets.MonthBegin(1):
        return "monthly"
    return "custom"


def _standardize_input_sheet(frame: pd.DataFrame, source_file: str, sheet_type: str) -> tuple[pd.DataFrame, dict]:
    frame = frame.copy()
    frame.columns = [str(column).strip() for column in frame.columns]
    model_column = find_column(frame.columns, MODEL_ALIASES)
    input_column = find_column(frame.columns, INPUT_ALIASES)
    bad_column = find_column(frame.columns, BAD_MACHINE_ALIASES)
    begin_column = find_column(frame.columns, BEGIN_DATE_ALIASES)
    end_column = find_column(frame.columns, END_DATE_ALIASES)
    line_column = find_column(frame.columns, LINE_ALIASES) if sheet_type == "org" else None
    required = {
        "model": model_column,
        "Input": input_column,
        "BeginDate": begin_column,
        "EndDate": end_column,
    }
    missing = [label for label, column in required.items() if column is None]
    if missing:
        raise RuntimeError(f"{source_file}: missing required {sheet_type} column(s): {', '.join(missing)}")

    result = pd.DataFrame(index=frame.index)
    result["Model"] = frame[model_column].map(normalize_model)
    result["Input"] = parse_number_series(frame[input_column])
    result["BadMachine"] = parse_number_series(frame[bad_column]).fillna(0) if bad_column else 0.0
    result["BeginDate"] = parse_date_series(frame[begin_column])
    raw_end = parse_date_series(frame[end_column])
    result["EndDateExclusive"] = raw_end.where(raw_end > result["BeginDate"], result["BeginDate"] + pd.Timedelta(days=1))
    result["Line"] = frame[line_column].map(clean_text) if line_column else ""
    result["SourceFile"] = source_file
    result["SourceRow"] = frame.index + 2
    invalid_model = result["Model"].eq("")
    invalid_input = result["Input"].isna() | result["Input"].lt(0)
    invalid_dates = result["BeginDate"].isna() | result["EndDateExclusive"].isna()
    valid = result[~invalid_model & ~invalid_input & ~invalid_dates].copy()
    valid["Input"] = valid["Input"].round().astype(int)
    valid["BadMachine"] = valid["BadMachine"].round().astype(int)
    valid["Granularity"] = [period_granularity(start, end) for start, end in zip(valid["BeginDate"], valid["EndDateExclusive"])]
    return valid.reset_index(drop=True), {
        "raw_rows": int(len(frame)),
        "valid_rows": int(len(valid)),
        "invalid_model": int(invalid_model.sum()),
        "invalid_input": int(invalid_input.sum()),
        "invalid_dates": int(invalid_dates.sum()),
        "bad_greater_than_input": int((valid["BadMachine"] > valid["Input"]).sum()),
    }


@st.cache_data(show_spinner=False)
def read_summary_input_bytes(data: bytes, filename: str) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    suffix = Path(filename).suffix.lower()
    if suffix not in {".xls", ".xlsx"}:
        raise RuntimeError(f"{filename}: summarized SMT input must be .xls or .xlsx")
    try:
        model_raw = pd.read_excel(BytesIO(data), sheet_name="ModelData", dtype=object)
        org_raw = pd.read_excel(BytesIO(data), sheet_name="OrgDisplay", dtype=object)
    except Exception as exc:
        raise RuntimeError(f"{filename}: unable to read ModelData/OrgDisplay: {exc}") from exc
    model, model_audit = _standardize_input_sheet(model_raw, filename, "model")
    org, org_audit = _standardize_input_sheet(org_raw, filename, "org")
    model_input = int(model["Input"].sum())
    org_input = int(org["Input"].sum())
    model_bad = int(model["BadMachine"].sum())
    org_bad = int(org["BadMachine"].sum())
    audit = {
        "SourceFile": filename,
        "ModelRows": model_audit["valid_rows"],
        "OrgRows": org_audit["valid_rows"],
        "Input": model_input,
        "BadMachine": model_bad,
        "OrgInput": org_input,
        "OrgBadMachine": org_bad,
        "OrgReconciles": model_input == org_input and model_bad == org_bad,
        "BadGreaterThanInputRows": model_audit["bad_greater_than_input"],
        "InvalidRows": model_audit["raw_rows"] - model_audit["valid_rows"],
    }
    return model, org, audit


@st.cache_data(show_spinner=False)
def read_input_path_cached(path_text: str, file_size: int, modified_ns: int):
    path = Path(path_text)
    return read_summary_input_bytes(path.read_bytes(), path.name)


def _series_from_alias(frame: pd.DataFrame, aliases: list[str], default: object = "") -> pd.Series:
    column = find_column(frame.columns, aliases)
    if column is None:
        return pd.Series(default, index=frame.index)
    return frame[column]


@st.cache_data(show_spinner=False)
def read_defect_bytes(data: bytes, filename: str) -> tuple[pd.DataFrame, dict]:
    try:
        frame = pd.read_excel(BytesIO(data), sheet_name="QueryData", dtype=object)
    except Exception as exc:
        raise RuntimeError(f"{filename}: unable to read QueryData: {exc}") from exc
    frame.columns = [str(column).strip() for column in frame.columns]
    aliases = {
        "Item": ["item"],
        "PCB": ["pcb", "pcb no", "barcode"],
        "Barcode": ["barcode", "pcb", "pcb no"],
        "Model": ["model", "pn"],
        "Line": ["testline", "test line"],
        "Operation": ["testoperation", "test operation"],
        "Phenomenon": ["fault phenomenon", "phenomenon"],
        "FaultReason": ["fault reason", "reason"],
        "RepairRemark": ["repaireremark", "repair remark", "repairer remark"],
        "DutyType": ["dutytype", "duty type"],
        "Maintenance": ["maintenance"],
        "Location": ["badmachlocation", "bad mach location", "location"],
        "FaultArea": ["fault area"],
        "TestPosition": ["test position"],
        "TestTime": ["testtime", "test time"],
        "EntryTime": ["badmachentrytime", "bad mach entry time"],
        "RepairDate": ["repairdate", "repair date"],
        "Repairer": ["repairer"],
        "RepairTimes": ["repairtimes", "repair times"],
        "LastNGOpcode": ["last ng opcode", "lastngopcode", "last ng op code"],
        "BackflowOP": ["backflowop", "backflow op"],
        "ItemCode": ["itemcode", "item code"],
        "ItemDesc": ["itemdesc", "item desc"],
        "Supplier": ["supplier"],
        "PatchTime": ["patchtime", "patch time"],
        "PatchLine": ["patchline", "patch line"],
    }
    result = pd.DataFrame(index=frame.index)
    for target, candidates in aliases.items():
        result[target] = _series_from_alias(frame, candidates)
    result["PCB"] = result["PCB"].map(normalize_code)
    result["Barcode"] = result["Barcode"].map(normalize_code)
    result["Model"] = result["Model"].map(normalize_model)
    for column in ["Line", "Operation", "Phenomenon", "FaultReason", "RepairRemark", "DutyType", "Maintenance", "Location", "FaultArea", "TestPosition", "Repairer", "LastNGOpcode", "BackflowOP", "ItemCode", "ItemDesc", "Supplier", "PatchLine"]:
        result[column] = result[column].map(clean_text)
    result["FailureType"] = result["Operation"].map(classify_smt_failure_type)
    for column in ["TestTime", "EntryTime", "RepairDate", "PatchTime"]:
        result[column] = parse_date_series(result[column]) if column != "TestTime" else _parse_timestamp_series(result[column])
    result["SourceFile"] = filename
    result["SourceRow"] = frame.index + 2
    maintenance = result["Maintenance"].str.lower().str.replace(r"\s+", " ", regex=True)
    rejudge_mask = maintenance.str.contains(r"re\s*[-_]?\s*judge\s*ok", regex=True, na=False)
    redownload_mask = maintenance.str.contains(r"re\s*[-_]?\s*download", regex=True, na=False)
    recalibration_mask = maintenance.str.contains(r"re\s*[-_]?\s*calibration", regex=True, na=False)
    retest_ok_mask = result["RepairRemark"].str.contains(r"re\s*[-_]?\s*test\s*ok", case=False, regex=True, na=False)
    last_ng_opcode = result["LastNGOpcode"].str.lower().str.replace(r"[^a-z0-9]+", "", regex=True)
    aoi_last_ng_mask = last_ng_opcode.eq("aoichecking")
    repair_times = pd.to_numeric(result["RepairTimes"], errors="coerce")
    repeat_repair_mask = repair_times.gt(1)
    result["ExclusionReason"] = ""
    result.loc[rejudge_mask, "ExclusionReason"] = "Re-Judge OK"
    result.loc[redownload_mask, "ExclusionReason"] = "Re-Download"
    result.loc[recalibration_mask, "ExclusionReason"] = "Re-Calibration"
    result.loc[retest_ok_mask, "ExclusionReason"] = "Retest OK"
    result.loc[aoi_last_ng_mask, "ExclusionReason"] = "Last NG Opcode: AOI-Checking"
    result.loc[repeat_repair_mask, "ExclusionReason"] = "Repeat repair"
    # The existing field name is retained for compatibility; it represents every MES-confirmed exclusion.
    result["IsRejudgeOK"] = (
        rejudge_mask
        | redownload_mask
        | recalibration_mask
        | retest_ok_mask
        | aoi_last_ng_mask
        | repeat_repair_mask
    )
    result["ValidDefect"] = result["PCB"].ne("") & result["Model"].ne("") & result["TestTime"].notna()
    result["ConfirmedRecord"] = result["ValidDefect"] & ~result["IsRejudgeOK"]
    audit = {
        "RawRows": int(len(frame)),
        "ValidRows": int(result["ValidDefect"].sum()),
        "MissingPCB": int(result["PCB"].eq("").sum()),
        "MissingModel": int(result["Model"].eq("").sum()),
        "InvalidTestTime": int(result["TestTime"].isna().sum()),
        "MissingRepairDate": int(result["RepairDate"].isna().sum()),
        "UnknownReason": int(result["FaultReason"].str.lower().isin({"", "unknownothers", "unknown"}).sum()),
        "UnknownLocation": int(result["Location"].str.lower().isin({"", "unknown"}).sum()),
        "RetestOK": int(retest_ok_mask.sum()),
        "LastNGAOI": int(aoi_last_ng_mask.sum()),
        "RepeatRepair": int(repeat_repair_mask.sum()),
    }
    return result, audit


def _parse_timestamp_series(series: pd.Series) -> pd.Series:
    text = series.fillna("").astype(str).str.strip()
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


@st.cache_data(show_spinner=False)
def read_defect_path_cached(path_text: str, file_size: int, modified_ns: int, failure_rule_version: str):
    _ = failure_rule_version
    path = Path(path_text)
    return read_defect_bytes(path.read_bytes(), path.name)


def consolidate_defect_sources(
    defect_signatures: tuple[tuple[str, int, int], ...],
    failure_rule_version: str,
) -> tuple[pd.DataFrame, dict]:
    """Combine cumulative and incremental defect files, keeping the most recent duplicate."""
    frames = []
    audits = []
    for signature in defect_signatures:
        frame, audit = read_defect_path_cached(*signature, failure_rule_version)
        source = frame.copy()
        source["SourceModified"] = signature[2]
        frames.append(source)
        audits.append(audit)
    if not frames:
        raise RuntimeError("No SMT defect files are available.")

    combined = pd.concat(frames, ignore_index=True).sort_values("SourceModified")
    merge_keys = ["PCB", "TestTime", "Operation", "Phenomenon"]
    duplicate_rows = int(combined.duplicated(merge_keys, keep="last").sum())
    combined = combined.drop_duplicates(merge_keys, keep="last").reset_index(drop=True)
    audit_keys = ["RawRows", "ValidRows", "MissingPCB", "MissingModel", "InvalidTestTime", "MissingRepairDate", "UnknownReason", "UnknownLocation"]
    audit = {key: int(sum(int(item.get(key, 0)) for item in audits)) for key in audit_keys}
    audit["SourceFiles"] = len(defect_signatures)
    audit["DuplicateRowsRemoved"] = duplicate_rows
    return combined.drop(columns=["SourceModified"]), audit


def path_signature(path: Path) -> tuple[str, int, int]:
    stat = path.stat()
    return str(path), int(stat.st_size), int(stat.st_mtime_ns)


def stored_smt_sources() -> tuple[list[Path], list[Path]]:
    init_smt_store()
    input_files = sorted([path for path in SMT_INPUT_DIR.iterdir() if path.suffix.lower() in {".xls", ".xlsx"}])
    defect_files = sorted([path for path in SMT_DEFECT_DIR.iterdir() if path.suffix.lower() == ".xlsx"])
    return input_files, defect_files


def smt_store_status() -> dict:
    inputs, defects = stored_smt_sources()
    files = [*inputs, *defects]
    latest = max((path.stat().st_mtime for path in files), default=None)
    latest_text = pd.Timestamp(latest, unit="s").strftime("%d/%m/%Y %H:%M") if latest else "-"
    return {
        "inputs": len(inputs),
        "defects": len(defects),
        "bytes": sum(path.stat().st_size for path in files),
        "latest": latest_text,
        "ready": bool(inputs and defects),
    }


def safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._() -]+", "_", Path(name).name).strip(" .")
    return cleaned or "source_file"


def persist_smt_source(uploaded, data_type: str) -> dict:
    require_persistent_store_for_smt_writes()
    target_dir = SMT_INPUT_DIR if data_type == "input" else SMT_DEFECT_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    data = uploaded.getvalue()
    digest = hashlib.sha256(data).hexdigest()[:12]
    target = target_dir / f"{digest}_{safe_filename(uploaded.name)}"
    if target.exists():
        return {"status": "duplicate", "file": uploaded.name, "message": "Identical file is already stored."}
    cloud_active = cloud_store_is_active()
    if cloud_active:
        upload_bytes(f"smt/{data_type}/{target.name}", data, upsert=True)
    target.write_bytes(data)
    if cloud_active:
        bump_cloud_data_version("SMT source upload")
    st.cache_data.clear()
    message = "Saved to Supabase persistent storage." if cloud_active else "Saved to the local SMT data store."
    return {"status": "imported", "file": uploaded.name, "message": message}


def smt_source_records() -> list[dict]:
    """Return stored SMT source files with user-facing metadata."""
    inputs, defects = stored_smt_sources()
    records = []
    for data_type, paths in (("input", inputs), ("defects", defects)):
        for path in paths:
            stat = path.stat()
            records.append(
                {
                    "key": f"{data_type}:{path.name}",
                    "data_type": data_type,
                    "stored_name": path.name,
                    "original_name": re.sub(r"^[0-9a-f]{12}_", "", path.name),
                    "file_size": int(stat.st_size),
                    "modified_at": pd.Timestamp(stat.st_mtime, unit="s").strftime("%d/%m/%Y %H:%M"),
                    "modified_sort": float(stat.st_mtime),
                }
            )
    return sorted(records, key=lambda item: item["modified_sort"], reverse=True)


def delete_smt_source(data_type: str, stored_name: str) -> dict:
    """Delete one managed SMT source file without allowing paths outside its data store."""
    require_persistent_store_for_smt_writes()
    directories = {"input": SMT_INPUT_DIR, "defects": SMT_DEFECT_DIR}
    if data_type not in directories:
        raise ValueError("Unsupported SMT source type.")
    if Path(stored_name).name != stored_name:
        raise ValueError("Invalid SMT source file.")

    target = directories[data_type] / stored_name
    if not target.is_file():
        raise ValueError("The selected SMT source file was not found.")
    cloud_active = cloud_store_is_active()
    if cloud_active:
        delete_object(f"smt/{data_type}/{stored_name}")
    try:
        target.unlink()
    except OSError as exc:
        raise RuntimeError(f"Unable to delete the selected SMT source file: {exc}") from exc
    if cloud_active:
        bump_cloud_data_version("SMT source deletion")
    st.cache_data.clear()
    return {"data_type": data_type, "original_name": re.sub(r"^[0-9a-f]{12}_", "", stored_name)}


def render_smt_source_manager() -> None:
    """Render the confirmed, individual source-file deletion workflow."""
    records = smt_source_records()
    with st.expander("Manage stored files"):
        st.caption(
            "Review the portal's stored SMT source files before deleting one. "
            "Deletion changes the data used by dashboards and Smart Report and cannot be undone."
        )
        if not records:
            st.info("No SMT source files are currently stored.")
            return

        file_types = {"input": "Production input", "defects": "Defects"}
        table = pd.DataFrame(
            [
                {
                    "Type": file_types[record["data_type"]],
                    "Source file": record["original_name"],
                    "Last updated": record["modified_at"],
                    "Size": f"{record['file_size'] / 1024 / 1024:.2f} MB",
                }
                for record in records
            ]
        )
        st.dataframe(table, use_container_width=True, hide_index=True, height="content")

        record_by_key = {record["key"]: record for record in records}
        selected_key = st.selectbox(
            "Source file to delete",
            options=list(record_by_key),
            format_func=lambda key: (
                f"{file_types[record_by_key[key]['data_type']]} · "
                f"{record_by_key[key]['original_name']} · {record_by_key[key]['modified_at']}"
            ),
            key="smt_source_delete_selection",
        )
        selected = record_by_key[selected_key]
        confirmed = st.checkbox(
            "I understand that this permanently removes the selected SMT source file from this portal.",
            key=f"smt_source_delete_confirm_{selected_key}",
        )
        if st.button(
            "Delete selected source file",
            type="secondary",
            disabled=not confirmed,
            use_container_width=True,
            key="smt_source_delete_button",
        ):
            try:
                deleted = delete_smt_source(selected["data_type"], selected["stored_name"])
            except (RuntimeError, ValueError) as exc:
                st.error(str(exc))
            else:
                st.session_state.pop("smt_last_import_results", None)
                st.success(f"Deleted SMT {file_types[deleted['data_type']].lower()} source: {deleted['original_name']}.")
                st.rerun()


def _coverage_mask(
    defects: pd.DataFrame,
    input_rows: pd.DataFrame,
    *,
    allow_period_pooling: bool = False,
) -> pd.Series:
    mask = pd.Series(False, index=defects.index)
    if defects.empty or input_rows.empty:
        return mask
    for model, group in input_rows.groupby("Model"):
        model_rows = defects[defects["Model"].eq(model)]
        if model_rows.empty:
            continue
        model_mask = pd.Series(False, index=model_rows.index)
        for begin, end in group[["BeginDate", "EndDateExclusive"]].drop_duplicates().itertuples(index=False, name=None):
            model_mask |= model_rows["TestTime"].ge(begin) & model_rows["TestTime"].lt(end)
        mask.loc[model_mask.index] |= model_mask
    if allow_period_pooling:
        period_input_by_model = input_rows.groupby("Model")["Input"].sum()
        eligible_models = set(period_input_by_model[period_input_by_model.gt(0)].index)
        mask |= defects["Model"].isin(eligible_models)
    return mask


def distribute_smt_input_to_days(input_rows: pd.DataFrame) -> pd.DataFrame:
    if input_rows.empty:
        return input_rows.copy()

    daily_rows = []
    for _, row in input_rows.iterrows():
        start = pd.Timestamp(row["BeginDate"]).normalize()
        end_exclusive = pd.Timestamp(row["EndDateExclusive"]).normalize()
        dates = pd.date_range(start, end_exclusive - pd.Timedelta(days=1), freq="D")
        if dates.empty:
            dates = pd.DatetimeIndex([start])

        def allocate(total_value):
            total = max(int(round(float(total_value))), 0)
            base, remainder = divmod(total, len(dates))
            return [base + (1 if index < remainder else 0) for index in range(len(dates))]

        input_by_day = allocate(row.get("Input", 0))
        bad_machine_by_day = allocate(row.get("BadMachine", 0))
        for index, input_date in enumerate(dates):
            daily_row = row.to_dict()
            daily_row["BeginDate"] = input_date
            daily_row["EndDateExclusive"] = input_date + pd.Timedelta(days=1)
            daily_row["Input"] = input_by_day[index]
            daily_row["BadMachine"] = bad_machine_by_day[index]
            daily_row["Granularity"] = "daily"
            daily_rows.append(daily_row)
    return pd.DataFrame(daily_rows)


def select_smt_input_period(
    input_rows: pd.DataFrame,
    start: pd.Timestamp,
    end_exclusive: pd.Timestamp,
) -> tuple[pd.DataFrame, dict]:
    """Select an arbitrary period without silently dropping monthly/weekly source rows."""
    if input_rows.empty:
        return input_rows.copy(), {"SourceRowsOutsidePeriod": 0, "SourceRowsProrated": 0}

    overlapping = input_rows[
        input_rows["BeginDate"].lt(end_exclusive)
        & input_rows["EndDateExclusive"].gt(start)
    ].copy()
    outside_count = int(len(input_rows) - len(overlapping))
    prorated_count = int(
        (
            overlapping["BeginDate"].lt(start)
            | overlapping["EndDateExclusive"].gt(end_exclusive)
        ).sum()
    )
    if overlapping.empty:
        return overlapping, {
            "SourceRowsOutsidePeriod": outside_count,
            "SourceRowsProrated": prorated_count,
        }

    daily = distribute_smt_input_to_days(overlapping)
    selected = daily[
        daily["BeginDate"].ge(start)
        & daily["BeginDate"].lt(end_exclusive)
    ].copy()
    return selected.reset_index(drop=True), {
        "SourceRowsOutsidePeriod": outside_count,
        "SourceRowsProrated": prorated_count,
    }


def _collapse_date_gaps(start: pd.Timestamp, end_exclusive: pd.Timestamp, intervals: pd.DataFrame) -> list[str]:
    dates = pd.date_range(start.normalize(), end_exclusive.normalize() - pd.Timedelta(days=1), freq="D")
    covered = set()
    for begin, end in intervals[["BeginDate", "EndDateExclusive"]].drop_duplicates().itertuples(index=False, name=None):
        covered.update(pd.date_range(begin, end - pd.Timedelta(days=1), freq="D"))
    missing = [date for date in dates if date not in covered]
    if not missing:
        return []
    groups = []
    group_start = previous = missing[0]
    for value in missing[1:]:
        if value - previous > pd.Timedelta(days=1):
            groups.append((group_start, previous))
            group_start = value
        previous = value
    groups.append((group_start, previous))
    return [
        start_value.strftime("%d/%m/%Y") if start_value == end_value else f"{start_value.strftime('%d/%m/%Y')}–{end_value.strftime('%d/%m/%Y')}"
        for start_value, end_value in groups
    ]


def _pareto(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    values = frame[column].replace("", "Unknown").fillna("Unknown")
    result = values.value_counts().rename_axis(column).reset_index(name="DefectRecords")
    total = result["DefectRecords"].sum()
    result["Share"] = result["DefectRecords"] / total if total else 0.0
    result["CumulativeShare"] = result["Share"].cumsum()
    return result


@st.cache_data(show_spinner=False)
def analyze_smt_quality_paths(
    input_signatures: tuple[tuple[str, int, int], ...],
    defect_signatures: tuple[tuple[str, int, int], ...],
    start_text: str,
    end_text: str,
    failure_rule_version: str = SMT_FAILURE_RULE_VERSION,
) -> dict:
    model_parts = []
    org_parts = []
    input_audits = []
    for signature in input_signatures:
        model, org, audit = read_input_path_cached(*signature)
        modified_ns = signature[2]
        model = model.copy()
        org = org.copy()
        model["SourceModified"] = modified_ns
        org["SourceModified"] = modified_ns
        model_parts.append(model)
        org_parts.append(org)
        input_audits.append(audit)
    input_model = pd.concat(model_parts, ignore_index=True)
    input_org = pd.concat(org_parts, ignore_index=True)
    exact_keys = ["Model", "BeginDate", "EndDateExclusive"]
    input_model = input_model.sort_values("SourceModified")
    exact_duplicate_rows = int(input_model.duplicated(exact_keys, keep="last").sum())
    input_model = input_model.drop_duplicates(exact_keys, keep="last").reset_index(drop=True)

    overlap_conflicts = []
    for model, group in input_model.groupby("Model"):
        rows = group.sort_values("BeginDate")
        values = list(rows[["BeginDate", "EndDateExclusive", "SourceFile"]].itertuples(index=False, name=None))
        for index, left in enumerate(values):
            for right in values[index + 1 :]:
                if left[0] < right[1] and right[0] < left[1]:
                    overlap_conflicts.append({"Model": model, "LeftFile": left[2], "RightFile": right[2]})

    defects, defect_audit = consolidate_defect_sources(defect_signatures, failure_rule_version)
    defects = defects.copy()
    defects["FailureType"] = defects["Operation"].map(classify_smt_failure_type)
    defects = defects[defects["ValidDefect"]].copy()
    start = pd.Timestamp(start_text).normalize()
    end_exclusive = pd.Timestamp(end_text).normalize() + pd.Timedelta(days=1)
    input_source_rows_in_scope = input_model[
        input_model["BeginDate"].lt(end_exclusive)
        & input_model["EndDateExclusive"].gt(start)
    ].copy()
    selected_input, input_selection_audit = select_smt_input_period(
        input_model, start, end_exclusive
    )
    selected_org, _ = select_smt_input_period(input_org, start, end_exclusive)
    calendar_defects = defects[defects["TestTime"].ge(start) & defects["TestTime"].lt(end_exclusive)].copy()
    exact_coverage = _coverage_mask(calendar_defects, selected_input)
    allow_period_pooling = int((end_exclusive - start).days) > 1
    calendar_defects["HasExactInputCoverage"] = exact_coverage
    calendar_defects["HasInputCoverage"] = _coverage_mask(
        calendar_defects,
        selected_input,
        allow_period_pooling=allow_period_pooling,
    )
    calendar_defects["UsesPeriodPooledInput"] = (
        calendar_defects["HasInputCoverage"]
        & ~calendar_defects["HasExactInputCoverage"]
    )
    covered_defects = calendar_defects[calendar_defects["HasInputCoverage"]].copy()
    confirmed = covered_defects[~covered_defects["IsRejudgeOK"]].copy()
    rejudge = covered_defects[covered_defects["IsRejudgeOK"]].copy()

    period_rows = []
    requested_grain = requested_trend_grain(start, end_exclusive - pd.Timedelta(days=1))
    input_granularities = set(selected_input["Granularity"].dropna().astype(str))
    if input_granularities and input_granularities.issubset({"daily"}):
        available_grain = "day"
    elif input_granularities and input_granularities.issubset({"daily", "weekly"}):
        available_grain = "week"
    else:
        available_grain = "month"
    grain_order = {"day": 0, "week": 1, "month": 2}
    input_distributed = grain_order[available_grain] > grain_order[requested_grain]
    trend_grain = requested_grain
    trend_frequency = {"day": "D", "week": "W-SUN", "month": "M"}[trend_grain]
    trend_input = distribute_smt_input_to_days(selected_input) if input_distributed else selected_input.copy()
    trend_input["TrendPeriod"] = trend_input["BeginDate"].dt.to_period(trend_frequency)
    for trend_period, period_input in trend_input.groupby("TrendPeriod", sort=True):
        begin = trend_period.start_time
        if trend_grain == "day":
            end = begin + pd.Timedelta(days=1)
        elif trend_grain == "week":
            end = begin + pd.Timedelta(days=7)
        else:
            end = begin + pd.offsets.MonthBegin(1)
        period_label = begin.strftime("%m/%y") if trend_grain == "month" else begin.strftime("%d/%m")
        period_defects = covered_defects[
            covered_defects["TestTime"].ge(begin)
            & covered_defects["TestTime"].lt(end)
        ]
        period_confirmed = period_defects[~period_defects["IsRejudgeOK"]]
        produced = int(period_input["Input"].sum())
        confirmed_pcbs = int(period_confirmed["PCB"].nunique())
        functional_pcbs = int(period_confirmed.loc[period_confirmed["FailureType"].eq("Functional Failure"), "PCB"].nunique())
        appearance_pcbs = int(period_confirmed.loc[period_confirmed["FailureType"].eq("Appearance Failure"), "PCB"].nunique())
        unclassified_pcbs = int(period_confirmed.loc[period_confirmed["FailureType"].eq("Unclassified"), "PCB"].nunique())
        classified_pcbs = int(
            period_confirmed.loc[
                period_confirmed["FailureType"].isin(["Functional Failure", "Appearance Failure"]),
                "PCB",
            ].nunique()
        )
        ppm_valid = bool(produced and confirmed_pcbs <= produced)
        function_pass_valid = bool(produced and functional_pcbs <= produced)
        process_ng_valid = bool(produced and classified_pcbs <= produced)
        period_rows.append(
            {
                "PeriodStart": begin,
                "PeriodEndExclusive": end,
                "Period": period_label,
                "Granularity": trend_grain.title(),
                "Input": produced,
                "BadMachineAudit": int(period_input["BadMachine"].sum()),
                "DefectRecords": int(len(period_defects)),
                "ConfirmedDefectPCBs": confirmed_pcbs,
                "FunctionalDefectPCBs": functional_pcbs,
                "AppearanceDefectPCBs": appearance_pcbs,
                "UnclassifiedDefectPCBs": unclassified_pcbs,
                "ClassifiedDefectPCBs": classified_pcbs,
                "RejudgeOKRecords": int(period_defects["IsRejudgeOK"].sum()),
                "ConfirmedPPM": (confirmed_pcbs / produced * 1_000_000) if ppm_valid else None,
                "FunctionalPPM": (functional_pcbs / produced * 1_000_000) if ppm_valid else None,
                "AppearancePPM": (appearance_pcbs / produced * 1_000_000) if ppm_valid else None,
                "FunctionPassRate": ((produced - functional_pcbs) / produced) if function_pass_valid else None,
                "FunctionPassStatus": "Valid" if function_pass_valid else "Blocked: functional NG PCB exceeds input",
                "SMTProcessNGRate": (classified_pcbs / produced) if process_ng_valid else None,
                "SMTProcessNGRatePPM": (classified_pcbs / produced * 1_000_000) if process_ng_valid else None,
                "SMTProcessStatus": "Valid" if process_ng_valid else "Blocked: classified NG PCB exceeds input",
                "PPMStatus": "Valid" if ppm_valid else "Blocked: confirmed PCB exceeds input",
            }
        )
    trend = pd.DataFrame(period_rows)

    model_rows = []
    model_names = sorted(set(selected_input["Model"]) | set(covered_defects["Model"]))
    for model in model_names:
        model_input = selected_input[selected_input["Model"].eq(model)]
        model_defects = covered_defects[covered_defects["Model"].eq(model)]
        model_confirmed = model_defects[~model_defects["IsRejudgeOK"]]
        produced = int(model_input["Input"].sum())
        confirmed_pcbs = int(model_confirmed["PCB"].nunique())
        functional_pcbs = int(model_confirmed.loc[model_confirmed["FailureType"].eq("Functional Failure"), "PCB"].nunique())
        appearance_pcbs = int(model_confirmed.loc[model_confirmed["FailureType"].eq("Appearance Failure"), "PCB"].nunique())
        unclassified_pcbs = int(model_confirmed.loc[model_confirmed["FailureType"].eq("Unclassified"), "PCB"].nunique())
        ppm_valid = bool(produced and confirmed_pcbs <= produced)
        model_rows.append(
            {
                "Model": model,
                "Input": produced,
                "DefectRecords": int(len(model_defects)),
                "ConfirmedDefectPCBs": confirmed_pcbs,
                "FunctionalDefectPCBs": functional_pcbs,
                "AppearanceDefectPCBs": appearance_pcbs,
                "UnclassifiedDefectPCBs": unclassified_pcbs,
                "RejudgeOKRecords": int(model_defects["IsRejudgeOK"].sum()),
                "ConfirmedPPM": (confirmed_pcbs / produced * 1_000_000) if ppm_valid else None,
                "FunctionalPPM": (functional_pcbs / produced * 1_000_000) if ppm_valid else None,
                "AppearancePPM": (appearance_pcbs / produced * 1_000_000) if ppm_valid else None,
                "PPMStatus": "Valid" if ppm_valid else "Blocked: confirmed PCB exceeds input",
            }
        )
    model_summary = pd.DataFrame(model_rows).sort_values(["ConfirmedDefectPCBs", "ConfirmedPPM"], ascending=[False, False])

    operation_summary = _pareto(confirmed, "Operation")
    line_summary = _pareto(confirmed, "Line")
    duty_summary = _pareto(confirmed, "DutyType")
    phenomenon_pareto = _pareto(confirmed, "Phenomenon")
    reason_pareto = _pareto(confirmed, "FaultReason")
    rejudge_pareto = _pareto(rejudge, "Phenomenon")
    functional_confirmed = confirmed[confirmed["FailureType"].eq("Functional Failure")].copy()
    appearance_confirmed = confirmed[confirmed["FailureType"].eq("Appearance Failure")].copy()
    unclassified_confirmed = confirmed[confirmed["FailureType"].eq("Unclassified")].copy()
    classified_confirmed = confirmed[
        confirmed["FailureType"].isin(["Functional Failure", "Appearance Failure"])
    ].copy()
    functional_phenomenon_pareto = _pareto(functional_confirmed, "Phenomenon")
    appearance_phenomenon_pareto = _pareto(appearance_confirmed, "Phenomenon")
    produced = int(selected_input["Input"].sum())
    failure_type_rows = []
    for failure_type in SMT_FAILURE_TYPE_ORDER:
        typed_records = confirmed[confirmed["FailureType"].eq(failure_type)]
        typed_pcbs = int(typed_records["PCB"].nunique())
        ppm_valid = bool(produced and typed_pcbs <= produced)
        failure_type_rows.append(
            {
                "FailureType": failure_type,
                "DefectRecords": int(len(typed_records)),
                "ConfirmedDefectPCBs": typed_pcbs,
                "RecordShare": len(typed_records) / len(confirmed) if len(confirmed) else 0.0,
                "ConfirmedPPM": (typed_pcbs / produced * 1_000_000) if ppm_valid else None,
                "PPMStatus": "Valid" if ppm_valid else "Blocked: confirmed PCB exceeds input",
            }
        )
    failure_type_summary = pd.DataFrame(failure_type_rows)
    station_summary = (
        confirmed.groupby(["FailureType", "Operation"], as_index=False)
        .agg(DefectRecords=("PCB", "size"), ConfirmedDefectPCBs=("PCB", "nunique"))
        .sort_values(["FailureType", "DefectRecords"], ascending=[True, False])
    )
    station_summary["RecordShare"] = station_summary["DefectRecords"] / len(confirmed) if len(confirmed) else 0.0
    unclassified_stations = station_summary[station_summary["FailureType"].eq("Unclassified")].copy()
    frequency = covered_defects.groupby("PCB").size().sort_values(ascending=False)
    repeated_pcbs = frequency[frequency > 1]
    repeat_detail = covered_defects[covered_defects["PCB"].isin(repeated_pcbs.index)].copy()
    repeat_detail["OccurrencesInPeriod"] = repeat_detail["PCB"].map(repeated_pcbs)
    repeat_detail = repeat_detail.sort_values(["OccurrencesInPeriod", "PCB", "TestTime"], ascending=[False, True, True])

    confirmed_pcbs = int(confirmed["PCB"].nunique())
    functional_pcbs = int(functional_confirmed["PCB"].nunique())
    appearance_pcbs = int(appearance_confirmed["PCB"].nunique())
    unclassified_pcbs = int(unclassified_confirmed["PCB"].nunique())
    classified_pcbs = int(classified_confirmed["PCB"].nunique())
    intervals = selected_input[["BeginDate", "EndDateExclusive"]].drop_duplicates()
    function_pass_valid = bool(produced and functional_pcbs <= produced)
    process_ng_valid = bool(produced and classified_pcbs <= produced)
    confirmed_ppm_valid = bool(produced and confirmed_pcbs <= produced)
    appearance_ppm_valid = bool(produced and appearance_pcbs <= produced)
    totals = {
        "Produced": produced,
        "ConfirmedDefectPCBs": confirmed_pcbs,
        "ConfirmedPPM": (confirmed_pcbs / produced * 1_000_000) if confirmed_ppm_valid else None,
        "FunctionalDefectRecords": int(len(functional_confirmed)),
        "FunctionalDefectPCBs": functional_pcbs,
        "FunctionalPPM": (functional_pcbs / produced * 1_000_000) if function_pass_valid else None,
        "AppearanceDefectRecords": int(len(appearance_confirmed)),
        "AppearanceDefectPCBs": appearance_pcbs,
        "AppearancePPM": (appearance_pcbs / produced * 1_000_000) if appearance_ppm_valid else None,
        "UnclassifiedDefectRecords": int(len(unclassified_confirmed)),
        "UnclassifiedDefectPCBs": unclassified_pcbs,
        "ClassifiedDefectPCBs": classified_pcbs,
        "FunctionPassRate": ((produced - functional_pcbs) / produced) if function_pass_valid else None,
        "FunctionPassStatus": "Valid" if function_pass_valid else "Blocked: functional NG PCB exceeds input",
        "SMTProcessNGRate": (classified_pcbs / produced) if process_ng_valid else None,
        "SMTProcessNGRatePPM": (classified_pcbs / produced * 1_000_000) if process_ng_valid else None,
        "SMTProcessStatus": "Valid" if process_ng_valid else "Blocked: classified NG PCB exceeds input",
        "ClassifiedRecordRate": (len(functional_confirmed) + len(appearance_confirmed)) / len(confirmed) if len(confirmed) else 0.0,
        "CoveredDefectRecords": int(len(covered_defects)),
        "CalendarDefectRecords": int(len(calendar_defects)),
        "RejudgeOKRecords": int(len(rejudge)),
        "RejudgeOKPCBs": int(rejudge["PCB"].nunique()),
        "RejudgeRate": len(rejudge) / len(covered_defects) if len(covered_defects) else 0.0,
        "RepeatedPCBs": int(len(repeated_pcbs)),
        "PeriodPooledDefectRecords": int(calendar_defects["UsesPeriodPooledInput"].sum()),
        "PeriodPooledDefectPCBs": int(
            calendar_defects.loc[calendar_defects["UsesPeriodPooledInput"], "PCB"].nunique()
        ),
        "UncoveredDefectRecords": int((~calendar_defects["HasInputCoverage"]).sum()),
        "InputFiles": len(input_signatures),
        "DefectFiles": len(defect_signatures),
    }
    quality = {
        "InputAudit": pd.DataFrame(input_audits),
        "DefectAudit": defect_audit,
        "ExactInputRowsReplaced": exact_duplicate_rows,
        "InputOverlapConflicts": overlap_conflicts,
        "BadGreaterThanInputRows": int(
            (input_source_rows_in_scope["BadMachine"] > input_source_rows_in_scope["Input"]).sum()
        ),
        "BlockedPPMPeriods": int(trend["ConfirmedPPM"].isna().sum()) if not trend.empty else 0,
        "InputRowsExcludedByPartialPeriod": 0,
        "InputSourceRowsOutsidePeriod": input_selection_audit["SourceRowsOutsidePeriod"],
        "InputSourceRowsProrated": input_selection_audit["SourceRowsProrated"],
        "CoverageGaps": _collapse_date_gaps(start, end_exclusive, intervals),
        "UncoveredDefects": calendar_defects[~calendar_defects["HasInputCoverage"]].copy(),
        "PeriodPooledDefects": calendar_defects[calendar_defects["UsesPeriodPooledInput"]].copy(),
        "UnclassifiedStations": unclassified_stations,
    }
    return {
        "totals": totals,
        "trend": trend,
        "models": model_summary,
        "phenomenon_pareto": phenomenon_pareto,
        "reason_pareto": reason_pareto,
        "failure_type_summary": failure_type_summary,
        "station_failure_summary": station_summary,
        "functional_phenomenon_pareto": functional_phenomenon_pareto,
        "appearance_phenomenon_pareto": appearance_phenomenon_pareto,
        "duty_summary": duty_summary,
        "operation_summary": operation_summary,
        "line_summary": line_summary,
        "rejudge_pareto": rejudge_pareto,
        "repeat_detail": repeat_detail,
        "raw": calendar_defects,
        "covered_raw": covered_defects,
        "selected_input": selected_input,
        "selected_org": selected_org,
        "quality": quality,
        "date_start": start,
        "date_end": end_exclusive - pd.Timedelta(days=1),
    }


def input_bounds(input_signatures: tuple[tuple[str, int, int], ...]) -> tuple[pd.Timestamp, pd.Timestamp]:
    begins = []
    ends = []
    for signature in input_signatures:
        model, _, _ = read_input_path_cached(*signature)
        begins.append(model["BeginDate"].min())
        ends.append(model["EndDateExclusive"].max() - pd.Timedelta(days=1))
    return min(begins), max(ends)


def fmt_int(value: object) -> str:
    return f"{int(value or 0):,}"


def fmt_ppm(value: object) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    return f"{float(value):,.0f}"


def fmt_pct(value: object) -> str:
    return f"{float(value or 0) * 100:.2f}%"


def metric_card(label: str, value: str, note: str, color: str) -> None:
    st.markdown(
        f"<div class='metric-card'><div class='metric-label'>{escape(label)}</div><div class='metric-value' style='color:{color};'>{escape(value)}</div><div class='small-muted'>{escape(note)}</div></div>",
        unsafe_allow_html=True,
    )


def show_table(frame: pd.DataFrame) -> None:
    view = frame.copy()
    for column in ["Share", "RecordShare"]:
        if column in view.columns:
            view[column] = (view[column] * 100).round(2)
    if "CumulativeShare" in view.columns:
        view["CumulativeShare"] = (view["CumulativeShare"] * 100).round(2)
    for column in ["ConfirmedPPM", "FunctionalPPM", "AppearancePPM"]:
        if column in view.columns:
            view[column] = view[column].round(0)
    st.dataframe(view, use_container_width=True, hide_index=True, height="content")


def trend_chart(frame: pd.DataFrame, color: str):
    from plotly.subplots import make_subplots
    import plotly.graph_objects as go

    chart = make_subplots(specs=[[{"secondary_y": True}]])
    input_labels = [f"{float(value):,.0f}" for value in frame["Input"]]
    ppm_labels = ["" if pd.isna(value) else f"{float(value):,.0f}" for value in frame["ConfirmedPPM"]]
    chart.add_trace(
        go.Bar(
            x=frame["Period"],
            y=frame["Input"],
            name="Input",
            marker_color="#9CC8AF",
            text=input_labels,
            textposition="inside",
            insidetextanchor="start",
            textfont=dict(color="#0B1F3A", size=11),
            hovertemplate="%{x}<br>Input: %{y:,.0f}<extra></extra>",
        ),
        secondary_y=False,
    )
    chart.add_trace(
        go.Scatter(
            x=frame["Period"],
            y=frame["ConfirmedPPM"],
            name="Confirmed PPM",
            mode="lines+markers+text",
            line=dict(color=color, width=3),
            marker=dict(size=8, color=color),
            text=ppm_labels,
            textposition="top center",
            textfont=dict(color=color, size=11),
            cliponaxis=False,
            hovertemplate="%{x}<br>Confirmed PPM: %{y:,.0f}<extra></extra>",
        ),
        secondary_y=True,
    )
    chart.update_layout(
        title="SMT input and confirmed PPM by available source period",
        height=480,
        margin=dict(l=45, r=65, t=80, b=90),
        paper_bgcolor="white",
        plot_bgcolor="white",
        legend=dict(orientation="h", y=-0.22, x=0.5, xanchor="center"),
        uniformtext_minsize=9,
        uniformtext_mode="show",
    )
    chart.update_yaxes(title_text="Input", secondary_y=False)
    ppm_max = pd.to_numeric(frame["ConfirmedPPM"], errors="coerce").max()
    chart.update_yaxes(
        title_text="PPM",
        range=[0, float(ppm_max) * 1.22] if pd.notna(ppm_max) and ppm_max > 0 else None,
        secondary_y=True,
    )
    chart.update_xaxes(automargin=True)
    return chart


def failure_type_trend_chart(frame: pd.DataFrame):
    import plotly.graph_objects as go

    chart = go.Figure()
    functional_values = pd.to_numeric(frame["FunctionalPPM"], errors="coerce")
    appearance_values = pd.to_numeric(frame["AppearancePPM"], errors="coerce")
    functional_positions = []
    appearance_positions = []
    for functional_value, appearance_value in zip(functional_values, appearance_values):
        if pd.isna(functional_value) or pd.isna(appearance_value):
            functional_positions.append("top left")
            appearance_positions.append("top right")
        elif float(functional_value) == float(appearance_value):
            functional_positions.append("top left")
            appearance_positions.append("top right")
        elif functional_value < appearance_value:
            functional_positions.append("bottom center" if functional_value > 0 else "middle left")
            appearance_positions.append("top center")
        else:
            functional_positions.append("top center")
            appearance_positions.append("bottom center" if appearance_value > 0 else "middle right")
    series = (
        ("FunctionalPPM", "Functional Failure", SMT_FAILURE_TYPE_COLORS["Functional Failure"], functional_positions),
        ("AppearancePPM", "Appearance Failure", SMT_FAILURE_TYPE_COLORS["Appearance Failure"], appearance_positions),
    )
    maximum_value = 0.0
    for column, label, color, positions in series:
        values = pd.to_numeric(frame[column], errors="coerce")
        if values.notna().any():
            maximum_value = max(maximum_value, float(values.max()))
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
                textfont=dict(color=color, size=11),
                cliponaxis=False,
                hovertemplate=f"%{{x}}<br>{label} PPM: %{{y:,.0f}}<extra></extra>",
            )
        )
    chart.update_layout(
        title="Functional vs appearance confirmed PPM",
        height=480,
        margin=dict(l=55, r=35, t=80, b=90),
        paper_bgcolor="white",
        plot_bgcolor="white",
        legend=dict(orientation="h", y=-0.2, x=0.5, xanchor="center"),
    )
    chart.update_xaxes(automargin=True)
    chart.update_yaxes(
        title_text="PPM",
        range=[0, maximum_value * 1.25] if maximum_value > 0 else None,
        automargin=True,
    )
    return chart


def bar_chart(frame: pd.DataFrame, category: str, value: str, title: str, color: str):
    import plotly.express as px

    chart_frame = frame.sort_values(value, ascending=True).tail(15)
    chart = px.bar(chart_frame, x=value, y=category, orientation="h", title=title, color_discrete_sequence=[color])
    chart.update_traces(
        text=[f"{float(item):,.0f}" for item in chart_frame[value]],
        textposition="outside",
        cliponaxis=False,
        textfont=dict(size=11, color="#0B1F3A"),
        hovertemplate=f"%{{y}}<br>{value}: %{{x:,.0f}}<extra></extra>",
    )
    value_max = pd.to_numeric(chart_frame[value], errors="coerce").max()
    chart.update_layout(
        height=max(450, len(chart_frame) * 34 + 120),
        margin=dict(l=35, r=90, t=70, b=45),
        paper_bgcolor="white",
        plot_bgcolor="white",
        showlegend=False,
        uniformtext_minsize=9,
        uniformtext_mode="show",
    )
    chart.update_xaxes(
        range=[0, float(value_max) * 1.24] if pd.notna(value_max) and value_max > 0 else None,
        automargin=True,
    )
    chart.update_yaxes(automargin=True)
    return chart


def _upload_section(color: str) -> None:
    status = smt_store_status()
    st.markdown("### Upload Data")
    st.caption("Accepted input: summarized SMT workbooks with ModelData and OrgDisplay. Accepted defects: QueryData .xlsx export.")
    columns = st.columns(4)
    with columns[0]:
        metric_card("Input files", fmt_int(status["inputs"]), "Local store", color)
    with columns[1]:
        metric_card("Defect files", fmt_int(status["defects"]), "Latest cumulative file is used", color)
    with columns[2]:
        metric_card("Stored size", f"{status['bytes'] / 1024 / 1024:.2f} MB", "Local files", color)
    with columns[3]:
        metric_card("Latest update", status["latest"], "Local store", color)
    uploaded_inputs = st.file_uploader("SMT input files", type=["xls", "xlsx"], accept_multiple_files=True, key="smt_summary_inputs_upload")
    uploaded_defect = st.file_uploader("SMT cumulative defect file", type=["xlsx"], key="smt_defect_upload")
    if uploaded_inputs or uploaded_defect:
        if st.button("Save files to the local SMT data store", use_container_width=True):
            results = [persist_smt_source(uploaded, "input") for uploaded in uploaded_inputs]
            if uploaded_defect:
                results.append(persist_smt_source(uploaded_defect, "defects"))
            st.session_state["smt_last_import_results"] = results
            st.success("SMT files processed.")
            st.rerun()
    if "smt_last_import_results" in st.session_state:
        st.dataframe(
            pd.DataFrame(st.session_state["smt_last_import_results"]),
            use_container_width=True,
            hide_index=True,
            height="content",
        )
    render_smt_source_manager()
    st.info(
        "Shared trend rule: periods shorter than 30 calendar days are daily, 30 to 180 days are weekly, "
        "and longer periods are monthly. Summarized input is distributed across calendar days while preserving "
        "the exact source-period total."
    )


def render_smt_quality_dashboard(color: str) -> None:
    init_smt_store()
    st.markdown(f"<h1 class='section-title' style='color:{color};'>SMT · Quality Dashboard</h1>", unsafe_allow_html=True)
    sections = ["Overview", "Failure Types", "Models", "Defects / Pareto", "Process", "Excluded MES rules / Repeats", "Data Quality", "Upload Data", "Details", "About"]
    active_section = st.radio("SMT dashboard section", sections, horizontal=True, label_visibility="collapsed", key="smt_quality_dashboard_section")
    if active_section == "Upload Data":
        _upload_section(color)
        return

    input_paths, defect_paths = stored_smt_sources()
    if not input_paths or not defect_paths:
        st.warning("SMT stored data is incomplete. Open Upload Data and add at least one input file and one cumulative defect file.")
        return
    input_signatures = tuple(path_signature(path) for path in input_paths)
    defect_signatures = tuple(path_signature(path) for path in defect_paths)
    minimum_date, maximum_date = input_bounds(input_signatures)

    date_columns = st.columns(2)
    with date_columns[0]:
        start_date = st.date_input("Start date", value=minimum_date.date(), min_value=minimum_date.date(), max_value=maximum_date.date(), key="smt_quality_start")
    with date_columns[1]:
        end_date = st.date_input("End date", value=maximum_date.date(), min_value=minimum_date.date(), max_value=maximum_date.date(), key="smt_quality_end")
    if end_date < start_date:
        st.error("End date must be on or after start date.")
        return

    try:
        analysis = analyze_smt_quality_paths(
            input_signatures,
            defect_signatures,
            start_date.isoformat(),
            end_date.isoformat(),
            SMT_FAILURE_RULE_VERSION,
        )
    except Exception as exc:
        st.error(f"Unable to calculate the SMT dashboard: {exc}")
        return
    analysis = {**analysis, "trend": refresh_chart_period_labels(analysis["trend"])}
    totals = analysis["totals"]
    quality = analysis["quality"]
    period_note = f"{start_date.strftime('%d/%m/%Y')} to {end_date.strftime('%d/%m/%Y')}"
    st.caption(f"Source: {len(input_paths)} stored input files · {len(defect_paths)} consolidated defect file(s) · dashboard tool {TOOL_VERSION}")
    st.caption("MES-aligned rule: confirmed defects exclude Re-Judge OK, Re-Download, Re-Calibration, Retest OK, Last NG Opcode = AOI-Checking, and repeat repairs (RepairTimes > 1).")
    if quality["CoverageGaps"]:
        st.warning("Input coverage gap(s): " + ", ".join(quality["CoverageGaps"]) + ". PPM excludes defects without matching input coverage by date and model.")
    if quality["InputOverlapConflicts"]:
        st.error(f"{len(quality['InputOverlapConflicts'])} overlapping input period conflict(s) detected. Review Data Quality before using PPM.")
    if quality["BlockedPPMPeriods"]:
        st.warning(f"PPM was blocked for {quality['BlockedPPMPeriods']} source period(s) where confirmed PCB exceeded the available input denominator.")

    if active_section == "Overview":
        columns = st.columns(4)
        with columns[0]:
            metric_card("SMT Input", fmt_int(totals["Produced"]), period_note, color)
        with columns[1]:
            metric_card("Confirmed defect PCBs", fmt_int(totals["ConfirmedDefectPCBs"]), "Unique PCB with covered input", color)
        with columns[2]:
            metric_card("Confirmed PPM", fmt_ppm(totals["ConfirmedPPM"]), "Confirmed PCB / input × 1,000,000", color)
        with columns[3]:
            metric_card("Excluded MES rules", fmt_int(totals["RejudgeOKRecords"]), fmt_pct(totals["RejudgeRate"]), color)
        columns = st.columns(4)
        with columns[0]:
            metric_card("Covered defect records", fmt_int(totals["CoveredDefectRecords"]), "Date and model matched", color)
        with columns[1]:
            metric_card("Repeated PCBs", fmt_int(totals["RepeatedPCBs"]), "More than one record", color)
        with columns[2]:
            metric_card("Uncovered records", fmt_int(totals["UncoveredDefectRecords"]), "Excluded from PPM", color)
        with columns[3]:
            metric_card("Input files", fmt_int(totals["InputFiles"]), "No overlapping periods", color)
        if not analysis["trend"].empty:
            st.plotly_chart(trend_chart(analysis["trend"], color), use_container_width=True, config={"displayModeBar": False})
            show_table(analysis["trend"][["Period", "Granularity", "Input", "DefectRecords", "ConfirmedDefectPCBs", "RejudgeOKRecords", "ConfirmedPPM", "PPMStatus"]])

    if active_section == "Failure Types":
        st.caption("SMT-only rule. Assembly will use its own station criteria when that classification is defined.")
        left, right = st.columns(2)
        with left:
            st.markdown("#### Functional Failure · more critical")
            st.info("Stations: " + ", ".join(SMT_FUNCTIONAL_STATIONS))
        with right:
            st.markdown("#### Appearance Failure")
            st.info("Stations: " + ", ".join(SMT_APPEARANCE_STATIONS))

        columns = st.columns(4)
        with columns[0]:
            metric_card(
                "Functional defect PCBs",
                fmt_int(totals["FunctionalDefectPCBs"]),
                f"{fmt_int(totals['FunctionalDefectRecords'])} confirmed records",
                SMT_FAILURE_TYPE_COLORS["Functional Failure"],
            )
        with columns[1]:
            metric_card(
                "Functional PPM",
                fmt_ppm(totals["FunctionalPPM"]),
                "More critical station group",
                SMT_FAILURE_TYPE_COLORS["Functional Failure"],
            )
        with columns[2]:
            metric_card(
                "Appearance defect PCBs",
                fmt_int(totals["AppearanceDefectPCBs"]),
                f"{fmt_int(totals['AppearanceDefectRecords'])} confirmed records",
                SMT_FAILURE_TYPE_COLORS["Appearance Failure"],
            )
        with columns[3]:
            metric_card(
                "Appearance PPM",
                fmt_ppm(totals["AppearancePPM"]),
                "Appearance station group",
                SMT_FAILURE_TYPE_COLORS["Appearance Failure"],
            )
        st.caption(
            f"Classification coverage: {fmt_pct(totals['ClassifiedRecordRate'])}. "
            "A PCB can appear in both categories when it has confirmed records at stations from both groups."
        )
        if totals["UnclassifiedDefectRecords"]:
            st.warning(
                f"{fmt_int(totals['UnclassifiedDefectRecords'])} confirmed record(s) from "
                f"{fmt_int(len(quality['UnclassifiedStations']))} station(s) remain Unclassified and are excluded from the functional/appearance split."
            )

        if not analysis["trend"].empty:
            st.plotly_chart(
                failure_type_trend_chart(analysis["trend"]),
                use_container_width=True,
                config={"displayModeBar": False},
            )
        left, right = st.columns(2)
        with left:
            st.plotly_chart(
                bar_chart(
                    analysis["functional_phenomenon_pareto"],
                    "Phenomenon",
                    "DefectRecords",
                    "Functional failure phenomena",
                    SMT_FAILURE_TYPE_COLORS["Functional Failure"],
                ),
                use_container_width=True,
                config={"displayModeBar": False},
            )
        with right:
            st.plotly_chart(
                bar_chart(
                    analysis["appearance_phenomenon_pareto"],
                    "Phenomenon",
                    "DefectRecords",
                    "Appearance failure phenomena",
                    SMT_FAILURE_TYPE_COLORS["Appearance Failure"],
                ),
                use_container_width=True,
                config={"displayModeBar": False},
            )
        st.markdown("#### Classification summary")
        show_table(analysis["failure_type_summary"])
        st.markdown("#### Station classification")
        show_table(analysis["station_failure_summary"])

    if active_section == "Models":
        model_view = analysis["models"].copy()
        eligible = model_view[model_view["Input"] > 0].copy()
        st.plotly_chart(bar_chart(eligible, "Model", "ConfirmedPPM", "Models by confirmed PPM", color), use_container_width=True, config={"displayModeBar": False})
        show_table(model_view)

    if active_section == "Defects / Pareto":
        left, right = st.columns(2)
        with left:
            st.plotly_chart(bar_chart(analysis["phenomenon_pareto"], "Phenomenon", "DefectRecords", "Confirmed defect phenomena", color), use_container_width=True, config={"displayModeBar": False})
        with right:
            st.plotly_chart(bar_chart(analysis["reason_pareto"], "FaultReason", "DefectRecords", "Confirmed fault reasons", color), use_container_width=True, config={"displayModeBar": False})
        show_table(analysis["phenomenon_pareto"])

    if active_section == "Process":
        st.info("PPM by line is not calculated because monthly input is not broken down by production line. These views show confirmed defect volume and share.")
        left, right = st.columns(2)
        with left:
            st.plotly_chart(bar_chart(analysis["operation_summary"], "Operation", "DefectRecords", "Confirmed defects by operation", color), use_container_width=True, config={"displayModeBar": False})
            show_table(analysis["operation_summary"])
        with right:
            st.plotly_chart(bar_chart(analysis["line_summary"], "Line", "DefectRecords", "Confirmed defects by test line", color), use_container_width=True, config={"displayModeBar": False})
            show_table(analysis["line_summary"])
        st.markdown("#### Responsibility / duty type")
        show_table(analysis["duty_summary"])

    if active_section == "Excluded MES rules / Repeats":
        columns = st.columns(3)
        with columns[0]:
            metric_card("Excluded MES records", fmt_int(totals["RejudgeOKRecords"]), period_note, color)
        with columns[1]:
            metric_card("Excluded MES PCBs", fmt_int(totals["RejudgeOKPCBs"]), "Unique PCB", color)
        with columns[2]:
            metric_card("Repeated PCBs", fmt_int(totals["RepeatedPCBs"]), "All covered records", color)
        left, right = st.columns(2)
        with left:
            st.plotly_chart(bar_chart(analysis["rejudge_pareto"], "Phenomenon", "DefectRecords", "Excluded MES phenomena", color), use_container_width=True, config={"displayModeBar": False})
        with right:
            show_table(analysis["rejudge_pareto"])
        repeat_columns = ["PCB", "Model", "TestTime", "Operation", "FailureType", "Phenomenon", "Maintenance", "OccurrencesInPeriod"]
        show_table(analysis["repeat_detail"][[column for column in repeat_columns if column in analysis["repeat_detail"].columns]])

    if active_section == "Data Quality":
        defect_audit = quality["DefectAudit"]
        columns = st.columns(6)
        with columns[0]:
            metric_card("Input rows replaced", fmt_int(quality["ExactInputRowsReplaced"]), "Same model and period", color)
        with columns[1]:
            metric_card("Overlap conflicts", fmt_int(len(quality["InputOverlapConflicts"])), "Must be zero", color)
        with columns[2]:
            metric_card("BadMachine > Input", fmt_int(quality["BadGreaterThanInputRows"]), "Audit only; not used in PPM", color)
        with columns[3]:
            metric_card("Missing repair date", fmt_int(defect_audit["MissingRepairDate"]), "Defect records", color)
        with columns[4]:
            metric_card("Blocked PPM periods", fmt_int(quality["BlockedPPMPeriods"]), "Confirmed PCB > input", color)
        with columns[5]:
            metric_card("Unclassified SMT records", fmt_int(totals["UnclassifiedDefectRecords"]), "Station rule review", SMT_FAILURE_TYPE_COLORS["Unclassified"])
        st.markdown("#### Input source audit")
        show_table(quality["InputAudit"])
        if not quality["UnclassifiedStations"].empty:
            st.markdown("#### Unclassified SMT stations")
            st.caption("These stations are intentionally not inferred. Add them to a category only after the SMT rule is confirmed.")
            show_table(quality["UnclassifiedStations"])
        st.markdown("#### Coverage")
        coverage_view = analysis["selected_input"].groupby(["BeginDate", "EndDateExclusive", "Granularity"], as_index=False).agg(Input=("Input", "sum"), Models=("Model", "nunique"), Files=("SourceFile", "nunique"))
        show_table(coverage_view)
        st.caption(f"Unknown/blank fault reason: {fmt_int(defect_audit['UnknownReason'])} · Unknown/blank component location: {fmt_int(defect_audit['UnknownLocation'])} · Invalid TestTime: {fmt_int(defect_audit['InvalidTestTime'])} · Retest OK: {fmt_int(defect_audit['RetestOK'])} · Last NG AOI: {fmt_int(defect_audit['LastNGAOI'])} · Repeat repair: {fmt_int(defect_audit['RepeatRepair'])}.")
        if not quality["UncoveredDefects"].empty:
            st.markdown("#### Defects outside matching input coverage")
            uncovered_columns = ["PCB", "Model", "TestTime", "Operation", "FailureType", "Phenomenon", "Maintenance"]
            show_table(quality["UncoveredDefects"][[column for column in uncovered_columns if column in quality["UncoveredDefects"].columns]])

    if active_section == "Details":
        raw = analysis["raw"].copy()
        model_options = ["All", *sorted(raw["Model"].dropna().unique())]
        selected_model = st.selectbox("Model", model_options, key="smt_detail_model")
        record_type = st.selectbox(
            "Record type",
            ["All", "Confirmed", "Functional Failure", "Appearance Failure", "Unclassified Station", "Excluded MES rule", "Without input coverage"],
            key="smt_detail_type",
        )
        view = raw
        if selected_model != "All":
            view = view[view["Model"].eq(selected_model)]
        if record_type == "Confirmed":
            view = view[view["HasInputCoverage"] & ~view["IsRejudgeOK"]]
        elif record_type == "Functional Failure":
            view = view[view["HasInputCoverage"] & ~view["IsRejudgeOK"] & view["FailureType"].eq("Functional Failure")]
        elif record_type == "Appearance Failure":
            view = view[view["HasInputCoverage"] & ~view["IsRejudgeOK"] & view["FailureType"].eq("Appearance Failure")]
        elif record_type == "Unclassified Station":
            view = view[view["HasInputCoverage"] & ~view["IsRejudgeOK"] & view["FailureType"].eq("Unclassified")]
        elif record_type == "Excluded MES rule":
            view = view[view["HasInputCoverage"] & view["IsRejudgeOK"]]
        elif record_type == "Without input coverage":
            view = view[~view["HasInputCoverage"]]
        visible_columns = ["PCB", "Barcode", "TestTime", "Model", "Line", "Operation", "LastNGOpcode", "FailureType", "Phenomenon", "FaultReason", "DutyType", "Maintenance", "RepairRemark", "RepairTimes", "ExclusionReason", "Location", "RepairDate", "Repairer", "HasInputCoverage", "IsRejudgeOK"]
        visible = view[[column for column in visible_columns if column in view.columns]].copy()
        st.caption(f"{fmt_int(len(visible))} records match the filters.")
        page_size = 200
        page_count = max(1, (len(visible) + page_size - 1) // page_size)
        if page_count > 1:
            page_number = st.selectbox(
                "Detail page",
                options=range(1, page_count + 1),
                format_func=lambda page: f"Page {page} of {page_count}",
                key=f"smt_detail_page_{selected_model}_{record_type}",
            )
        else:
            page_number = 1
        page_start = (page_number - 1) * page_size
        page_view = visible.iloc[page_start : page_start + page_size]
        st.dataframe(page_view, use_container_width=True, hide_index=True, height="content")
        st.download_button("Download filtered SMT detail CSV", data=visible.to_csv(index=False).encode("utf-8-sig"), file_name="smt_quality_filtered_detail.csv", mime="text/csv", use_container_width=True)

    if active_section == "About":
        st.markdown(
            f"""
            <div class='card'>
                <h3>SMT Quality Dashboard {TOOL_VERSION}</h3>
                <p class='small-muted'>Real SMT quality analysis using summarized production input and cumulative defect records. Trend granularity follows the shared portal rule, and any summarized input distribution preserves the exact source-period total.</p>
                <p><b>MES-aligned confirmed defect rule:</b> valid PCB record excluding Re-Judge OK, Re-Download, Re-Calibration, Retest OK, Last NG Opcode = AOI-Checking, and repeat repairs (RepairTimes &gt; 1).</p>
                <p><b>PPM rule:</b> unique confirmed PCB / SMT input × 1,000,000.</p>
                <p><b>SMT failure type rule:</b> Functional Failure = {", ".join(SMT_FUNCTIONAL_STATIONS)}. Appearance Failure = {", ".join(SMT_APPEARANCE_STATIONS)}. Other stations remain Unclassified.</p>
                <p><b>Scope:</b> this station rule applies only to SMT. Assembly will use separate criteria.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
