"""Brazilian display formats; source values and calculation keys remain untouched."""
from datetime import date, datetime, time
import re
from zoneinfo import ZoneInfo

import pandas as pd
from pandas.api.types import is_datetime64_any_dtype

DATE_FORMAT = '%d/%m/%y'
DATETIME_FORMAT = '%d/%m/%y %H:%M'
PORTAL_ZONE = ZoneInfo('America/Manaus')
# Native date_input supports four-digit years only.
CALENDAR_FORMAT = 'DD/MM/YYYY'

_DATES = {'date', 'day', 'data', 'inputdate', 'inspectiondate', 'perioddate', 'periodstart',
          'periodend', 'periodendexclusive', 'begindate', 'enddateexclusive', 'startdate',
          'enddate', 'duedate', 'originalduedate', 'lastoccurrence', 'latestinput', 'repairday',
          'weekstart', 'weekend', 'completiondate', 'lastseen', 'datainput', 'datainspecao'}
_TIMES = {'created', 'closed', 'createdat', 'updatedat', 'importedat', 'modifiedat', 'lastupdated',
          'lastmodified', 'testtime', 'testtimeparsed', 'repairdate', 'repairdateparsed',
          'entrytime', 'defectentry', 'firsttest', 'repairedat', 'operatetime', 'patchtime',
          'badmachentrytime', 'changedat', 'updated', 'imported', 'modified', 'measuredat'}


def _parse(value, dayfirst=True):
    if value is None or value is pd.NA or value is pd.NaT: return None
    if isinstance(value, (int, float, bool)): return None  # Never turn an SN or a duration into a date.
    if isinstance(value, time): return value
    if isinstance(value, (datetime, date, pd.Timestamp)):
        result = pd.Timestamp(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text or text.casefold() in {'nat', 'nan', 'none', 'null', '-', '—'}: return None
        # ISO is always year-first, regardless of the local display convention.
        if re.match(r'^\d{4}-\d{2}-\d{2}(?:$|[T ])', text):
            try: result = pd.Timestamp(text)
            except ValueError: return None
        else:
            # Avoid reinterpreting two-digit years or existing BR values with a US parser.
            formats = ['%d/%m/%y %H:%M', '%d/%m/%Y %H:%M:%S', '%d/%m/%Y %H:%M', '%d/%m/%y', '%d/%m/%Y']
            if not dayfirst: formats = ['%m/%d/%Y', '%m/%d/%y'] + formats
            result = pd.NaT
            for pattern in formats:
                try:
                    result = pd.Timestamp(datetime.strptime(text, pattern))
                    break
                except ValueError: pass
            if pd.isna(result):
                # Known display columns can also contain older English month names.
                if not re.search(r'\d[/ -].*\d|\d [A-Za-z]{3}', text): return None
                result = pd.to_datetime(text, errors='coerce', dayfirst=dayfirst)
    else:
        return None
    if pd.isna(result): return None
    if result.tzinfo is not None: result = result.tz_convert(PORTAL_ZONE)
    return result


def br_date(value, missing='—', *, dayfirst=True):
    parsed = _parse(value, dayfirst)
    return parsed.strftime(DATE_FORMAT) if parsed is not None and not isinstance(parsed, time) else missing


def br_datetime(value, missing='—', *, dayfirst=True):
    parsed = _parse(value, dayfirst)
    if isinstance(parsed, time): return parsed.strftime('%H:%M')
    return parsed.strftime(DATETIME_FORMAT) if parsed is not None else missing


def _kind(column, values):
    name = re.sub(r'[^a-z0-9]', '', str(column).casefold())
    if name in _DATES: return 'date'
    if name in _TIMES: return 'datetime'
    if is_datetime64_any_dtype(values.dtype): return 'datetime'
    sample = values.dropna().head(20)
    if any(isinstance(v, datetime) for v in sample): return 'datetime'
    if any(isinstance(v, date) for v in sample): return 'date'
    return None


def _display(value, kind):
    parsed = _parse(value)
    if parsed is None:
        return value if value is not None and value is not pd.NaT and value is not pd.NA else '—'
    return parsed.strftime(DATE_FORMAT if kind == 'date' else DATETIME_FORMAT)


def br_frame(data):
    """Format only temporal columns on a copy; preserve row order, IDs and source frames."""
    if isinstance(data, (list, tuple)):
        if not data or not all(isinstance(row, dict) for row in data): return data
        frame = pd.DataFrame(data)
    elif isinstance(data, pd.DataFrame):
        frame = data
    elif hasattr(data, 'data') and isinstance(data.data, pd.DataFrame) and hasattr(data, 'format'):
        for column in data.data.columns:
            kind = _kind(column, data.data[column])
            if kind: data.format(lambda value, k=kind: _display(value, k), subset=[column])
        return data
    else:
        return data
    kinds = {column: _kind(column, frame[column]) for column in frame.columns if isinstance(frame[column], pd.Series)}
    if not any(kinds.values()): return data
    view = frame.copy()
    for column, kind in kinds.items():
        if kind: view[column] = view[column].map(lambda value, k=kind: _display(value, k))
    return view
