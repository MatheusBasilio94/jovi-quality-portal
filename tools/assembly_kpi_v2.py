"""Validated Assembly KPI rules for the September 2026 MES source contract."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Iterable

import pandas as pd


# Bump whenever a validated Assembly classification or responsibility rule
# changes.  It is part of the dashboard cache key in app.py.
ASSEMBLY_KPI_RULE_VERSION = "mes-operation-map-2026-09-16.6"


FUNCTIONAL_OPERATIONS = (
    "Antenna_Non_Signaling_2",
    "Audio-Testing",
    "Audio_Testing_4",
    "Auto-MMI-Testing1",
    "Auto-MMI-Testing2",
    "Auto-MMI-Testing3",
    "Camera",
    "Camera17",
    "Camera_4",
    "Camera-auxiliary-tester",
    "Current",
    "MMI_auxiliary_test_bit",
    "Photosensor_test_Dark",
    "PreAging-Testing",
    "RSE_Station",
    "Ring_light_Test",
    "SARFunctionTest2",
    "SARFunctionTestStation",
    "SIMCard_Auto_Test",
    "Wired_Charging_Automatic",
)

APPEARANCE_OPERATIONS = (
    "Appearance-QC",
    "Assembly seal test Station",
    "Assembly-collection(5)",
    "Assembly_seal_test_Station_1",
    "Glue_dispensing",
    "PCB-Assembly",
    "finish product seal test Station",
)

SMT_DUTY_TYPES = ("SMT equipment", "SMT Mando", "SMT Process", "SMT Test")
EXCLUDED_OPERATIONS = ("Aging-Software-Testing",)
EVENT_KEY_COLUMNS = ("PCB", "TestTime", "TestOperation", "Fault Phenomenon")


def _source_name(source) -> str:
    return Path(getattr(source, "name", str(source))).name


def _read_excel(source, sheet_name: str) -> pd.DataFrame:
    if isinstance(source, Path):
        payload = source
    elif isinstance(source, (bytes, bytearray)):
        payload = BytesIO(source)
    else:
        if hasattr(source, "seek"):
            source.seek(0)
        payload = source
    try:
        return pd.read_excel(payload, sheet_name=sheet_name, dtype=object)
    except ValueError as exc:
        raise RuntimeError(f"{_source_name(source)}: aba obrigatória '{sheet_name}' não encontrada.") from exc
    except ImportError as exc:
        raise RuntimeError("A leitura de arquivos .xls requer a dependência xlrd.") from exc


def _text(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip()


def _norm(series: pd.Series) -> pd.Series:
    return _text(series).str.replace(r"\.0$", "", regex=True).str.casefold()


def _number(series: pd.Series) -> pd.Series:
    text = _text(series).str.replace("\u00a0", "", regex=False).str.replace(" ", "", regex=False)
    comma_decimal = text.str.contains(",", regex=False) & ~text.str.contains(".", regex=False)
    text.loc[comma_decimal] = text.loc[comma_decimal].str.replace(",", ".", regex=False)
    text.loc[~comma_decimal] = text.loc[~comma_decimal].str.replace(",", "", regex=False)
    return pd.to_numeric(text, errors="coerce")


def _datetime(series: pd.Series, *, normalize: bool = False) -> pd.Series:
    text = series.fillna("").astype(str).str.strip()
    year_first = text.str.match(r"^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}", na=False)
    parsed = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
    if year_first.any():
        try:
            parsed.loc[year_first] = pd.to_datetime(
                text.loc[year_first], errors="coerce", yearfirst=True, format="mixed"
            )
        except TypeError:
            parsed.loc[year_first] = pd.to_datetime(
                text.loc[year_first], errors="coerce", yearfirst=True
            )
    remaining = ~year_first
    if remaining.any():
        try:
            parsed.loc[remaining] = pd.to_datetime(
                text.loc[remaining], errors="coerce", dayfirst=True, format="mixed"
            )
        except TypeError:
            parsed.loc[remaining] = pd.to_datetime(
                text.loc[remaining], errors="coerce", dayfirst=True
            )
    return parsed.dt.normalize() if normalize else parsed


def read_daily_input(source, source_order: int = 0) -> pd.DataFrame:
    frame = _read_excel(source, "ModelData")
    required = {"model", "Input", "BeginDate", "EndDate"}
    missing = required - set(frame.columns)
    if missing:
        raise RuntimeError(f"{_source_name(source)}: colunas ausentes em ModelData: {', '.join(sorted(missing))}.")
    result = pd.DataFrame(index=frame.index)
    result["Model"] = _text(frame["model"])
    result["Input"] = _number(frame["Input"])
    result["Date"] = _datetime(frame["BeginDate"], normalize=True)
    result["EndDate"] = _datetime(frame["EndDate"], normalize=True)
    result["SourceFile"] = _source_name(source)
    result["SourceOrder"] = int(source_order)
    invalid = result["Model"].eq("") | result["Input"].isna() | result["Input"].lt(0) | result["Date"].isna()
    result = result.loc[~invalid].copy()
    if result.empty:
        raise RuntimeError(f"{_source_name(source)}: nenhum input válido encontrado.")
    non_daily = result["EndDate"].notna() & result["EndDate"].ne(result["Date"])
    if non_daily.any():
        raise RuntimeError(
            f"{_source_name(source)}: o novo fluxo aceita somente inputs diários "
            "(BeginDate e EndDate devem representar o mesmo dia)."
        )
    result["Input"] = result["Input"].round().astype(int)
    return result[["Date", "Model", "Input", "SourceFile", "SourceOrder"]]


def combine_daily_inputs(sources: Iterable) -> pd.DataFrame:
    frames = [read_daily_input(source, order) for order, source in enumerate(sources)]
    if not frames:
        raise RuntimeError("Carregue pelo menos um input diário de Assembly.")
    raw = pd.concat(frames, ignore_index=True)
    # A newer upload replaces the same day/model without summing snapshots.
    active = raw.sort_values(["Date", "Model", "SourceOrder"]).drop_duplicates(["Date", "Model"], keep="last")
    return active.reset_index(drop=True)


def read_fpy_defects(source) -> pd.DataFrame:
    frame = _read_excel(source, "Detail")
    required = {"PCB", "BadMachEntryTime", "TestTime", "TestOperation", "Fault Phenomenon", "DutyType"}
    missing = required - set(frame.columns)
    if missing:
        raise RuntimeError(f"{_source_name(source)}: colunas ausentes em Detail: {', '.join(sorted(missing))}.")
    result = frame.copy()
    result["SourceFile"] = _source_name(source)
    result["DefectDate"] = _datetime(result["BadMachEntryTime"], normalize=True)
    result["TestTimeParsed"] = _datetime(result["TestTime"])
    result["PCBNormalized"] = _norm(result["PCB"])
    result["Operation"] = _text(result["TestOperation"])
    result["Phenomenon"] = _text(result["Fault Phenomenon"])
    result["Model"] = _text(result["model"]) if "model" in result else ""
    result["FPYDutyType"] = _text(result["DutyType"])
    result = result[result["DefectDate"].notna() & result["PCBNormalized"].ne("")].copy()
    result["EventKey"] = event_key(result)
    result = result.drop_duplicates("EventKey", keep="last").reset_index(drop=True)
    functional = {_normalize_literal(value) for value in FUNCTIONAL_OPERATIONS}
    appearance = {_normalize_literal(value) for value in APPEARANCE_OPERATIONS}
    operation_norm = _norm(result["Operation"])
    result["FailureType"] = "Fora do escopo"
    result.loc[operation_norm.isin(functional), "FailureType"] = "Funcional"
    result.loc[operation_norm.isin(appearance), "FailureType"] = "Aparência"
    return result


def combine_fpy_defects(sources: Iterable) -> pd.DataFrame:
    """Combine full, cumulative or partial FPY uploads; newer copies replace only the same event."""
    source_list = [sources] if isinstance(sources, (str, Path, bytes, bytearray)) else list(sources)
    frames = []
    for source_order, source in enumerate(source_list):
        frame = read_fpy_defects(source).copy()
        frame["SourceOrder"] = source_order
        frames.append(frame)
    if not frames:
        raise RuntimeError("Carregue ao menos um arquivo FPY de defeitos de Assembly.")

    active = pd.concat(frames, ignore_index=True)
    return active.sort_values(["DefectDate", "SourceOrder", "EventKey"]).drop_duplicates(
        "EventKey", keep="last"
    ).reset_index(drop=True)


def read_repair(source) -> pd.DataFrame:
    frame = _read_excel(source, "QueryData")
    required = set(EVENT_KEY_COLUMNS) | {"DutyType", "RepairDate"}
    missing = required - set(frame.columns)
    if missing:
        raise RuntimeError(f"{_source_name(source)}: colunas ausentes em QueryData: {', '.join(sorted(missing))}.")
    result = frame.copy()
    result["EventKey"] = event_key(result)
    result["RepairDutyType"] = _text(result["DutyType"])
    result["RepairDateParsed"] = _datetime(result["RepairDate"])
    if "BadMachEntryTime" in result:
        result["RepairBadMachEntryTime"] = _datetime(result["BadMachEntryTime"])
    else:
        result["RepairBadMachEntryTime"] = pd.NaT
    result["_RowOrder"] = range(len(result))
    result = result.sort_values(
        ["EventKey", "RepairDateParsed", "RepairBadMachEntryTime", "_RowOrder"], na_position="first"
    ).drop_duplicates("EventKey", keep="last")
    return result[["EventKey", "RepairDutyType", "RepairDateParsed"]]


def combine_repairs(sources: Iterable) -> pd.DataFrame:
    """Merge repair uploads incrementally, with the newest record winning for the same event."""
    if sources is None:
        return pd.DataFrame(columns=["EventKey", "RepairDutyType", "RepairDateParsed"])
    source_list = [sources] if isinstance(sources, (str, Path, bytes, bytearray)) else list(sources)
    frames = []
    for source_order, source in enumerate(source_list):
        frame = read_repair(source).copy()
        frame["SourceOrder"] = source_order
        frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=["EventKey", "RepairDutyType", "RepairDateParsed"])
    combined = pd.concat(frames, ignore_index=True).sort_values("SourceOrder")
    return combined.drop_duplicates("EventKey", keep="last").drop(columns="SourceOrder").reset_index(drop=True)


def _normalize_literal(value: object) -> str:
    return str(value).strip().casefold()


def event_key(frame: pd.DataFrame) -> pd.Series:
    key = pd.Series("", index=frame.index, dtype="object")
    for column in EVENT_KEY_COLUMNS:
        key = key + "|" + _norm(frame[column])
    return key.str[1:]


def enrich_responsibility(defects: pd.DataFrame, repair: pd.DataFrame | None) -> pd.DataFrame:
    result = defects.copy()
    if repair is None or repair.empty:
        result["RepairMatched"] = False
        result["RepairDutyType"] = ""
        result["RepairDateParsed"] = pd.NaT
    else:
        result = result.merge(repair, on="EventKey", how="left", validate="one_to_one")
        result["RepairMatched"] = result["EventKey"].isin(set(repair["EventKey"]))
    result["RepairDutyType"] = _text(result["RepairDutyType"])
    result["ResponsibilityPending"] = (
        result["RepairMatched"]
        & (result["RepairDutyType"].eq("") | result["RepairDateParsed"].isna())
    )
    complete = result["RepairMatched"] & ~result["ResponsibilityPending"]
    result["FinalDutyType"] = result["FPYDutyType"]
    result.loc[complete, "FinalDutyType"] = result.loc[complete, "RepairDutyType"]
    duty_norm = _norm(result["FinalDutyType"])
    result["IsFunctionMando"] = (
        result["FailureType"].eq("Funcional")
        & ~result["ResponsibilityPending"]
        & duty_norm.str.contains("mando", regex=False)
        & ~duty_norm.str.startswith("smt")
    )
    result["IsSMTDuty"] = (
        ~result["ResponsibilityPending"]
        & duty_norm.isin({_normalize_literal(value) for value in SMT_DUTY_TYPES})
    )
    return result


def prepare_sources(input_sources: Iterable, defect_source, repair_source) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Read and consolidate the active source files once, before period-level KPI calculations."""
    inputs = combine_daily_inputs(input_sources)
    defects = combine_fpy_defects(defect_source)
    repair = combine_repairs(repair_source)
    defects = enrich_responsibility(defects, repair)
    return inputs, defects


def calculate_from_prepared(inputs: pd.DataFrame, defects: pd.DataFrame, start_date, end_date) -> dict:
    """Calculate one period from the already consolidated source data."""
    start = pd.Timestamp(start_date).normalize()
    end = pd.Timestamp(end_date).normalize()
    selected_input = inputs[inputs["Date"].between(start, end)].copy()
    selected_defects = defects[defects["DefectDate"].between(start, end)].copy()
    if selected_input.empty:
        raise RuntimeError("Nenhum input diário foi encontrado no período selecionado.")
    input_daily = selected_input.groupby("Date", as_index=False)["Input"].sum()
    source_defect_dates = pd.to_datetime(defects["DefectDate"], errors="coerce").dropna()

    def pcb_count(frame: pd.DataFrame) -> int:
        return int(frame["PCBNormalized"].nunique()) if not frame.empty else 0

    rows = []
    for row in input_daily.itertuples(index=False):
        day_defects = selected_defects[selected_defects["DefectDate"].eq(row.Date)]
        functional = day_defects[day_defects["FailureType"].eq("Funcional")]
        appearance = day_defects[day_defects["FailureType"].eq("Aparência")]
        mando = day_defects[day_defects["IsFunctionMando"]]
        smt_duty = day_defects[day_defects["IsSMTDuty"]]
        pending = day_defects[day_defects["ResponsibilityPending"] & day_defects["FailureType"].eq("Funcional")]
        functional_count = pcb_count(functional)
        appearance_count = pcb_count(appearance)
        mando_count = pcb_count(mando)
        smt_count = pcb_count(smt_duty)
        produced = int(row.Input)
        rows.append(
            {
                "Date": row.Date,
                "Input": produced,
                "FunctionalNGPCBs": functional_count,
                "AppearanceNGPCBs": appearance_count,
                "FunctionMandoPCBs": mando_count,
                "SMTDutyPCBs": smt_count,
                "PendingResponsibilityPCBs": pcb_count(pending),
                "FunctionPassRate": (produced - functional_count) / produced if produced else None,
                "AppearancePassRate": (produced - appearance_count) / produced if produced else None,
                "FunctionMandoPPM": mando_count / produced * 1_000_000 if produced else None,
                "SMTDutyPPM": smt_count / produced * 1_000_000 if produced else None,
            }
        )
    daily = pd.DataFrame(rows)
    produced = int(input_daily["Input"].sum())
    functional = selected_defects[selected_defects["FailureType"].eq("Funcional")]
    appearance = selected_defects[selected_defects["FailureType"].eq("Aparência")]
    mando = selected_defects[selected_defects["IsFunctionMando"]]
    smt_duty = selected_defects[selected_defects["IsSMTDuty"]]
    pending = selected_defects[
        selected_defects["ResponsibilityPending"] & selected_defects["FailureType"].eq("Funcional")
    ]
    counts = {
        "functional": pcb_count(functional),
        "appearance": pcb_count(appearance),
        "mando": pcb_count(mando),
        "smt_duty": pcb_count(smt_duty),
        "pending": pcb_count(pending),
    }
    return {
        "produced": produced,
        "function_pass_rate": (produced - counts["functional"]) / produced if produced else None,
        "appearance_pass_rate": (produced - counts["appearance"]) / produced if produced else None,
        "function_mando_ppm": counts["mando"] / produced * 1_000_000 if produced else None,
        "smt_duty_ppm": counts["smt_duty"] / produced * 1_000_000 if produced else None,
        "functional_pcbs": counts["functional"],
        "appearance_pcbs": counts["appearance"],
        "function_mando_pcbs": counts["mando"],
        "smt_duty_pcbs": counts["smt_duty"],
        "pending_responsibility_pcbs": counts["pending"],
        "daily": daily,
        "defects": selected_defects,
        "inputs": selected_input,
        "unclassified": selected_defects[selected_defects["FailureType"].eq("Fora do escopo")].copy(),
        "source_defect_start": source_defect_dates.min().date() if not source_defect_dates.empty else None,
        "source_defect_end": source_defect_dates.max().date() if not source_defect_dates.empty else None,
    }


def calculate(
    input_sources: Iterable,
    defect_source,
    repair_source,
    start_date,
    end_date,
) -> dict:
    inputs, defects = prepare_sources(input_sources, defect_source, repair_source)
    return calculate_from_prepared(inputs, defects, start_date, end_date)
