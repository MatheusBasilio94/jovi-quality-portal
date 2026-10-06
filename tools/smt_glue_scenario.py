"""Non-destructive SMT Process NG simulations using the existing input scope."""
import pandas as pd


RULE_FIELDS = ("Operation", "Phenomenon", "FaultReason", "RepairRemark")


def normalize_category(values):
    return values.fillna("").astype(str).str.strip().str.replace(r"\s+", " ", regex=True).str.casefold()


def glue_mask(records, rules):
    matched = pd.Series(True, index=records.index)
    has_rule = False
    for column in RULE_FIELDS:
        selected = rules.get(column, [])
        if selected:
            has_rule = True
            if column not in records:
                return pd.Series(False, index=records.index)
            normalized = normalize_category(pd.Series(selected)).tolist()
            matched &= normalize_category(records[column]).isin(normalized)
    return matched if has_rule else pd.Series(False, index=records.index)


def process_counts(records, input_count):
    glue = records.loc[records["ScenarioGlueRecord"], "PCB"]
    other = records.loc[~records["ScenarioGlueRecord"], "PCB"]
    all_boards = set(records["PCB"].dropna())
    glue_boards = set(glue.dropna())
    other_boards = set(other.dropna())
    with_ng = len(all_boards)
    without_ng = len(other_boards)
    def ppm(count):
        return count / input_count * 1_000_000 if input_count > 0 and count <= input_count else None
    return {
        "WithGlueNG": with_ng, "WithoutGlueNG": without_ng,
        "GlueOnlyNG": len(glue_boards - other_boards),
        "GlueMixedNG": len(glue_boards & other_boards),
        "WithGluePPM": ppm(with_ng), "WithoutGluePPM": ppm(without_ng),
        "WithGlueStatus": "Valid" if ppm(with_ng) is not None else "Blocked: no input or classified NG PCB exceeds input",
        "WithoutGlueStatus": "Valid" if ppm(without_ng) is not None else "Blocked: no input or classified NG PCB exceeds input",
    }


def build_glue_scenarios(analysis, rules):
    records = analysis["covered_raw"].copy()
    records = records.loc[
        ~records["IsRejudgeOK"].fillna(False).astype(bool)
        & records["FailureType"].isin(["Functional Failure", "Appearance Failure"])
    ].copy()
    records["ScenarioGlueRecord"] = glue_mask(records, rules)
    totals = process_counts(records, int(analysis["totals"]["Produced"]))
    trend = analysis["trend"].copy()
    dates = pd.to_datetime(records["KPIDate"], errors="coerce")
    results = []
    for row in trend.itertuples(index=False):
        scope = records.loc[dates.ge(row.PeriodStart) & dates.lt(row.PeriodEndExclusive)]
        results.append(process_counts(scope, int(row.Input)))
    for column in totals:
        trend[column] = [row[column] for row in results]
    glue_boards = set(records.loc[records["ScenarioGlueRecord"], "PCB"])
    other_boards = set(records.loc[~records["ScenarioGlueRecord"], "PCB"])
    audit = records.loc[records["PCB"].isin(glue_boards)].copy()
    audit["ScenarioDisposition"] = audit["PCB"].map(
        lambda pcb: "Retained NG: also has other defects" if pcb in other_boards else "Excluded: glue-only PCB"
    )
    return {"totals": totals, "trend": trend, "audit": audit}
