"""Read-only production scenarios, preserving PCB overlaps and KPI scopes."""
from collections import Counter
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

import pandas as pd
from tools.smart_report_rules import kpi_defect_scopes, top_issue_reasons


def rounded_forecast(count, planned, historical_input, reduction=0):
    if historical_input <= 0 or planned <= 0:
        raise ValueError("Historical input and planned production must be positive.")
    reduction = Decimal(str(reduction))
    if not 0 <= reduction <= 100:
        raise ValueError("Expected reductions must be between 0% and 100%.")
    value = Decimal(int(count)) * Decimal(int(planned)) / Decimal(int(historical_input)) * (1 - reduction / 100)
    return int(value.to_integral_value(rounding=ROUND_CEILING))


def history(records, historical_input, area):
    data = records.copy()
    if "IsRejudgeOK" in data:
        data = data.loc[~data["IsRejudgeOK"].fillna(False).astype(bool)].copy()
    data["TopIssue"] = top_issue_reasons(data)
    if "_DefectKey" not in data:
        data["_DefectKey"] = data.get("PCBNormalized", data.get("PCB", pd.Series("", index=data.index)))
    data = data.loc[data["_DefectKey"].notna() & data["_DefectKey"].astype(str).str.strip().ne("")].copy()
    empty = data.iloc[:0]
    scopes = kpi_defect_scopes(data if area == "SMT" else empty, data if area == "Assembly" else empty)
    sources = ["smt_function", "smt_process"] if area == "SMT" else ["assembly_function", "assembly_appearance", "assembly_mando"]
    active = pd.concat([scopes[source] for source in sources]).drop_duplicates() if sources else empty
    if int(historical_input) <= 0:
        raise ValueError("No historical input is available for this model and period.")
    if active["_DefectKey"].nunique() > historical_input:
        raise ValueError("Confirmed NG PCBs exceed the available model input. Review the source data before simulating.")
    date_column = "KPIDate" if "KPIDate" in active else "DefectDate"
    active["_Occurrence"] = pd.to_datetime(active.get(date_column, pd.Series(pd.NaT, index=active.index)), errors="coerce")
    rows = active.groupby("TopIssue", as_index=False).agg(**{"NG PCBs": ("_DefectKey", "nunique"), "Last occurrence": ("_Occurrence", "max")})
    rows["Historical PPM"] = rows["NG PCBs"] / historical_input * 1e6
    rows = rows.rename(columns={"TopIssue": "Defect"}).sort_values(["NG PCBs", "Defect"], ascending=[False, True]).reset_index(drop=True)
    return {"records": active, "scopes": {source: scopes[source] for source in sources}, "issues": rows, "input": int(historical_input), "area": area}


def projected_unique(frame, planned, historical_input, reductions):
    """Round disjoint PCB defect-signature groups; never sum overlapping issues."""
    if frame.empty:
        return 0
    signatures = Counter(tuple(sorted(set(group["TopIssue"]))) for _, group in frame.groupby("_DefectKey"))
    total = 0
    for issues, count in signatures.items():
        eliminated = Decimal(1)
        for issue in issues:
            reduction = Decimal(str(reductions.get(issue, 0)))
            if not 0 <= reduction <= 100:
                raise ValueError("Expected reductions must be between 0% and 100%.")
            eliminated *= reduction / 100
        value = Decimal(count) * Decimal(planned) / Decimal(historical_input) * (1 - eliminated)
        total += int(value.to_integral_value(rounding=ROUND_CEILING))
    return min(planned, total)


def simulate(baseline, planned, reductions):
    planned = int(planned)
    if planned <= 0:
        raise ValueError("Planned production must be positive.")
    rows = baseline["issues"].copy()
    denominator = baseline["input"]
    rows["Without actions"] = [rounded_forecast(count, planned, denominator) for count in rows["NG PCBs"]]
    rows["Expected reduction (%)"] = [float(reductions.get(issue, 0)) for issue in rows["Defect"]]
    rows["With actions"] = [rounded_forecast(count, planned, denominator, reduction) for count, reduction in zip(rows["NG PCBs"], rows["Expected reduction (%)"])]
    metrics = {}
    for source, scope in baseline["scopes"].items():
        counts = [projected_unique(scope, planned, denominator, rules) for rules in ({}, reductions)]
        percent = source in {"smt_function", "assembly_function", "assembly_appearance"}
        metrics[source] = {
            "counts": counts,
            "values": [1 - count / planned if percent else count / planned * 1e6 for count in counts],
        }
    totals = [projected_unique(baseline["records"], planned, denominator, rules) for rules in ({}, reductions)]
    return {"issues": rows, "metrics": metrics, "totals": totals}


def suggest_actions(baseline, planned, item, reductions=None, locked=()):
    """Frequency-first, editable target scenario using the same rounded PCB model."""
    planned = int(planned)
    if planned <= 0:
        raise ValueError("Planned production must be positive.")
    source = item["source"]
    if source not in baseline["scopes"]:
        raise ValueError("This KPI cannot be simulated with the available data.")
    target = Decimal(str(item["target"]))
    allowed = (Decimal(planned) * (1 - target) if item["direction"] == "min"
               else Decimal(planned) * target / Decimal(1000000))
    allowed = int(allowed.to_integral_value(rounding=ROUND_FLOOR))
    if not 0 <= allowed <= planned:
        raise ValueError("The KPI target is outside the valid range.")
    rules = dict(reductions or {})
    locked = set(locked)
    for issue in locked:
        rules[issue] = 0
    scope = baseline["scopes"][source]
    signatures = Counter(tuple(sorted(set(group["TopIssue"]))) for _, group in scope.groupby("_DefectKey"))

    def count():
        total = 0
        for issues, frequency in signatures.items():
            eliminated = Decimal(1)
            for issue in issues:
                reduction = Decimal(str(rules.get(issue, 0)))
                if not 0 <= reduction <= 100:
                    raise ValueError("Expected reductions must be between 0% and 100%.")
                eliminated *= reduction / 100
            value = Decimal(frequency) * planned / baseline["input"] * (1 - eliminated)
            total += int(value.to_integral_value(rounding=ROUND_CEILING))
        return min(planned, total)

    initial = count()
    ranking = scope.groupby("TopIssue")["_DefectKey"].nunique()
    priority = sorted((issue for issue in ranking.index if issue not in locked), key=lambda issue: (-ranking[issue], issue))
    selected = []
    for issue in priority:
        if count() <= allowed:
            break
        if rules.get(issue, 0) < 100:
            selected.append((issue, float(rules.get(issue, 0))))
            rules[issue] = 100
    achieved = count() <= allowed
    if achieved:
        # Remove redundant increases and find whole-percent reductions that still
        # meet the target, including boards with several defects.
        for issue, original in reversed(selected):
            low, high = int(Decimal(str(original)).to_integral_value(rounding=ROUND_CEILING)), 100
            while low < high:
                middle = (low + high) // 2
                rules[issue] = middle
                if count() <= allowed:
                    high = middle
                else:
                    low = middle + 1
            rules[issue] = low
    return {"reductions": rules, "achieved": achieved, "allowed": allowed,
            "before": initial, "after": count()}
