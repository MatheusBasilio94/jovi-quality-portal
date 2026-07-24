from datetime import date, datetime


DAILY_TREND_LIMIT_DAYS = 30
WEEKLY_TREND_LIMIT_DAYS = 180


def _as_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if hasattr(value, "date"):
        return value.date()
    return date.fromisoformat(str(value)[:10])


def analysis_period_days(start, end) -> int:
    start_date = _as_date(start)
    end_date = _as_date(end)
    if end_date < start_date:
        start_date, end_date = end_date, start_date
    return max((end_date - start_date).days + 1, 1)


def requested_trend_grain(start, end) -> str:
    days = analysis_period_days(start, end)
    if days < DAILY_TREND_LIMIT_DAYS:
        return "day"
    if days <= WEEKLY_TREND_LIMIT_DAYS:
        return "week"
    return "month"


def trend_grain_labels(grain: str) -> tuple[str, str]:
    return {
        "day": ("Daily", "by day"),
        "week": ("Weekly", "by week"),
        "month": ("Monthly", "by month"),
    }[grain]
