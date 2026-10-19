"""Consistent model scoping for production, defect and inspection records."""


def model_options(frame):
    if "Model" not in frame:
        return []
    return sorted({str(value).strip().upper() for value in frame["Model"].dropna()
                   if str(value).strip()})


def filter_model_records(frame, model=None):
    if model is None:
        return frame.copy()
    if "Model" not in frame:
        return frame.iloc[:0].copy()
    values = frame["Model"].fillna("").astype(str).str.strip().str.casefold()
    return frame.loc[values.eq(str(model).strip().casefold())].copy()
