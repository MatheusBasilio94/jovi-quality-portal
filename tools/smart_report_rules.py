"""KPI-specific defect scopes used by Weekly and Monthly KPI Review narratives."""

from __future__ import annotations

import pandas as pd


def top_issue_reasons(frame: pd.DataFrame) -> pd.Series:
    """Use the repair conclusion as the report issue, falling back to phenomenon."""
    result = pd.Series("", index=frame.index, dtype="object")
    for column in ("RepaireRemark", "RepairRemark"):
        if column not in frame.columns:
            continue
        values = frame[column].fillna("").astype(str).str.strip()
        result = result.where(result.ne(""), values)
    phenomenon = frame.get("Phenomenon", pd.Series("Unknown", index=frame.index))
    phenomenon = phenomenon.fillna("").astype(str).str.strip().replace("", "Unknown")
    return result.where(result.ne(""), phenomenon)


def kpi_defect_scopes(
    smt_confirmed: pd.DataFrame,
    assembly_confirmed: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    """Return only the defect records that can detract from each KPI."""
    empty_smt = smt_confirmed.iloc[0:0].copy()
    empty_assembly = assembly_confirmed.iloc[0:0].copy()

    smt_failure_type = smt_confirmed.get("FailureType", pd.Series("", index=smt_confirmed.index))
    assembly_failure_type = assembly_confirmed.get(
        "FailureType", pd.Series("", index=assembly_confirmed.index)
    )
    function_mando = assembly_confirmed.get(
        "IsFunctionMando", pd.Series(False, index=assembly_confirmed.index)
    ).fillna(False).astype(bool)
    smt_duty = assembly_confirmed.get(
        "IsSMTDuty", pd.Series(False, index=assembly_confirmed.index)
    ).fillna(False).astype(bool)

    return {
        "smt_function": smt_confirmed[smt_failure_type.eq("Functional Failure")].copy(),
        "smt_process": smt_confirmed[
            smt_failure_type.isin(["Functional Failure", "Appearance Failure"])
        ].copy(),
        "smt_assembly_duty": assembly_confirmed[smt_duty].copy(),
        "smt_oqc": empty_smt,
        "assembly_function": assembly_confirmed[assembly_failure_type.eq("Funcional")].copy(),
        "assembly_appearance": assembly_confirmed[assembly_failure_type.eq("Aparência")].copy(),
        "assembly_mando": assembly_confirmed[function_mando].copy(),
        "assembly_oqc_fqc": empty_assembly,
    }
