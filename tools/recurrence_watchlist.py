"""Historical recurrence signals for the defect-analysis dashboards."""

from __future__ import annotations

from datetime import date

import pandas as pd

from tools.smart_report_rules import top_issue_reasons


def _distinct_context(values: pd.Series, limit: int = 2) -> str:
    """Return the most affected context values without turning the table into a list."""
    cleaned = values.fillna("").astype(str).str.strip()
    cleaned = cleaned[cleaned.ne("")]
    if cleaned.empty:
        return "—"
    return " · ".join(cleaned.value_counts().head(limit).index.tolist())


def build_recurrence_watchlist(
    confirmed: pd.DataFrame,
    history_start: date,
    history_end: date,
) -> dict[str, pd.DataFrame | dict[str, int]]:
    """Find repair reasons that recur across distinct calendar weeks.

    The watchlist counts unique PCBs per repair reason and week.  It therefore
    flags a problem recurring in production without inflating the signal when
    MES contains multiple rows for the same board in the same week.
    """
    watchlist_columns = [
        "Priority",
        "TopIssue",
        "AffectedPCBs",
        "ActiveWeeks",
        "CurrentWeekPCBs",
        "RecidivistPCBs",
        "Trend",
        "LastSeen",
        "Stations",
        "Models",
    ]
    weekly_columns = ["TopIssue", "WeekStart", "Week", "NGPCBs"]
    empty_watchlist = pd.DataFrame(columns=watchlist_columns)
    empty_weekly = pd.DataFrame(columns=weekly_columns)
    if confirmed is None or confirmed.empty:
        return {
            "watchlist": empty_watchlist,
            "weekly": empty_weekly,
            "summary": {"history_weeks": 0, "recurring_issues": 0, "persistent_issues": 0, "recidivist_pcbs": 0},
        }

    data = confirmed.copy()
    date_column = next((column for column in ("KPIDate", "TestTime", "EntryTime") if column in data.columns), None)
    if date_column is None:
        return {
            "watchlist": empty_watchlist,
            "weekly": empty_weekly,
            "summary": {"history_weeks": 0, "recurring_issues": 0, "persistent_issues": 0, "recidivist_pcbs": 0},
        }
    data["_RecurrenceDate"] = pd.to_datetime(data[date_column], errors="coerce").dt.normalize()
    start = pd.Timestamp(history_start).normalize()
    end = pd.Timestamp(history_end).normalize()
    data = data[data["_RecurrenceDate"].between(start, end)].copy()
    if data.empty:
        return {
            "watchlist": empty_watchlist,
            "weekly": empty_weekly,
            "summary": {"history_weeks": 0, "recurring_issues": 0, "persistent_issues": 0, "recidivist_pcbs": 0},
        }

    board = data.get("PCB", data.get("Barcode", pd.Series("", index=data.index)))
    data["_BoardKey"] = board.fillna("").astype(str).str.strip()
    data.loc[data["_BoardKey"].eq(""), "_BoardKey"] = data.index.astype(str)
    if "Model" in data.columns:
        data["_BoardKey"] = data["Model"].fillna("").astype(str).str.strip() + "::" + data["_BoardKey"]
    data["TopIssue"] = top_issue_reasons(data)
    data["WeekStart"] = data["_RecurrenceDate"] - pd.to_timedelta(data["_RecurrenceDate"].dt.weekday, unit="D")
    data["Week"] = data["WeekStart"].dt.strftime("WK%V · %d/%m")
    current_week = end - pd.Timedelta(days=end.weekday())
    recent_start = max(start, end - pd.Timedelta(days=27))
    prior_start = max(start, recent_start - pd.Timedelta(days=28))

    weekly = (
        data.groupby(["TopIssue", "WeekStart", "Week"], as_index=False)
        .agg(NGPCBs=("_BoardKey", "nunique"))
        .sort_values(["TopIssue", "WeekStart"])
    )
    rows = []
    for issue, issue_data in data.groupby("TopIssue", sort=False):
        issue_weekly = weekly[weekly["TopIssue"].eq(issue)]
        active_weeks = int(issue_weekly["WeekStart"].nunique())
        if active_weeks < 2:
            continue
        current_week_pcbs = int(
            issue_weekly.loc[issue_weekly["WeekStart"].eq(current_week), "NGPCBs"].sum()
        )
        recent_activity = int(
            issue_weekly.loc[issue_weekly["WeekStart"].ge(recent_start), "NGPCBs"].sum()
        )
        prior_activity = int(
            issue_weekly.loc[
                issue_weekly["WeekStart"].ge(prior_start)
                & issue_weekly["WeekStart"].lt(recent_start),
                "NGPCBs",
            ].sum()
        )
        if prior_activity == 0:
            trend = "New"
        elif recent_activity > prior_activity:
            trend = "Increasing"
        elif recent_activity < prior_activity:
            trend = "Decreasing"
        else:
            trend = "Stable"
        board_weeks = issue_data.groupby("_BoardKey")["WeekStart"].nunique()
        recidivist_pcbs = int((board_weeks > 1).sum())
        priority = "Critical" if active_weeks >= 3 and current_week_pcbs else "Attention"
        rows.append(
            {
                "Priority": priority,
                "TopIssue": issue,
                "AffectedPCBs": int(issue_data["_BoardKey"].nunique()),
                "ActiveWeeks": active_weeks,
                "CurrentWeekPCBs": current_week_pcbs,
                "RecidivistPCBs": recidivist_pcbs,
                "Trend": trend,
                "LastSeen": issue_data["_RecurrenceDate"].max().strftime("%d/%m/%Y"),
                "Stations": _distinct_context(issue_data.get("Operation", pd.Series("", index=issue_data.index))),
                "Models": _distinct_context(issue_data.get("Model", pd.Series("", index=issue_data.index))),
            }
        )
    watchlist = pd.DataFrame(rows, columns=watchlist_columns)
    if watchlist.empty:
        return {
            "watchlist": empty_watchlist,
            "weekly": empty_weekly,
            "summary": {"history_weeks": int(weekly["WeekStart"].nunique()), "recurring_issues": 0, "persistent_issues": 0, "recidivist_pcbs": 0},
        }
    priority_rank = {"Critical": 0, "Attention": 1}
    watchlist["_PriorityRank"] = watchlist["Priority"].map(priority_rank).fillna(2)
    watchlist = watchlist.sort_values(
        ["_PriorityRank", "ActiveWeeks", "AffectedPCBs", "TopIssue"],
        ascending=[True, False, False, True],
    ).drop(columns="_PriorityRank")
    watched_issues = set(watchlist["TopIssue"])
    weekly = weekly[weekly["TopIssue"].isin(watched_issues)].copy()
    return {
        "watchlist": watchlist,
        "weekly": weekly,
        "summary": {
            "history_weeks": int(data["WeekStart"].nunique()),
            "recurring_issues": int(len(watchlist)),
            "persistent_issues": int(watchlist["Priority"].eq("Critical").sum()),
            "recidivist_pcbs": int(watchlist["RecidivistPCBs"].sum()),
        },
    }
