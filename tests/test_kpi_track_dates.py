import ast
import unittest
from datetime import date
from html import escape
from pathlib import Path

import pandas as pd

from tools.trend_rules import analysis_period_days, requested_trend_grain, trend_grain_labels


def load_chart_functions():
    """Load the pure chart builders without starting the Streamlit application."""
    source = Path(__file__).resolve().parents[1] / "app.py"
    module = ast.parse(source.read_text(encoding="utf-8"))
    names = {
        "parse_date_series", "add_trend_period", "format_trend_period",
        "build_smt_oqc_trend", "build_assembly_oqc_fqc_trend", "smt_kpi_line_chart",
    }
    functions = [node for node in module.body if isinstance(node, ast.FunctionDef) and node.name in names]
    namespace = {
        "date": date,
        "escape": escape,
        "analysis_period_days": analysis_period_days,
        "requested_trend_grain": requested_trend_grain,
    }
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), "exec"), namespace)
    namespace["trend_granularity"] = lambda start, end: {
        "grain": requested_trend_grain(start, end),
        "label": trend_grain_labels(requested_trend_grain(start, end))[0],
    }
    return namespace


class KPITrackDatesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.builders = load_chart_functions()

    def test_months_up_to_31_days_use_daily_grain(self):
        self.assertEqual(requested_trend_grain(date(2026, 9, 1), date(2026, 9, 30)), "day")
        self.assertEqual(requested_trend_grain(date(2026, 10, 1), date(2026, 10, 31)), "day")
        self.assertEqual(requested_trend_grain(date(2026, 9, 1), date(2026, 10, 2)), "week")

    def test_smt_oqc_excludes_august_and_clips_partial_week(self):
        records = pd.DataFrame({
            "InspectionDate": ["2026-08-31", "2026-09-01", "2026-09-30"],
            "Inspected": [10, 10, 10], "OK": [9, 8, 10], "NG": [1, 2, 0],
        })
        build = self.builders["build_smt_oqc_trend"]
        daily, settings = build(records, date(2026, 9, 1), date(2026, 9, 30))
        self.assertEqual(settings["grain"], "day")
        self.assertEqual(daily["Period"].tolist(), ["01/09", "30/09"])
        self.assertEqual(daily["Inspected"].sum(), 20)
        weekly, settings = build(records, date(2026, 9, 1), date(2026, 10, 2))
        self.assertEqual(settings["grain"], "week")
        self.assertEqual(weekly["Period"].iloc[0], "01/09")

    def test_assembly_inspection_excludes_august(self):
        records = pd.DataFrame({
            "InspectionDate": ["2026-08-31", "2026-09-01", "2026-09-30"],
            "OQCInspected": [10, 10, 10], "OQCOK": [9, 8, 10],
            "FQCInspected": [10, 10, 10], "FQCOK": [9, 9, 10],
        })
        trend, settings = self.builders["build_assembly_oqc_fqc_trend"](
            records, date(2026, 9, 1), date(2026, 9, 30)
        )
        self.assertEqual(settings["grain"], "day")
        self.assertEqual(trend["Period"].tolist(), ["01/09", "30/09"])

    def test_daily_chart_shows_only_days_with_input(self):
        frame = pd.DataFrame({
            "PeriodDate": pd.to_datetime(["2026-09-01", "2026-09-02", "2026-09-30"]),
            "Period": ["01/09", "02/09", "30/09"],
            "Inspected": [10, 0, 20],
            "PassRate": [0.99, None, 0.98],
        })
        chart = self.builders["smt_kpi_line_chart"](
            frame, "Period", "PassRate", "OQC", "#1D5FBF", "percent",
            period_start=date(2026, 9, 1), period_end=date(2026, 9, 30),
            input_columns=("Inspected",),
        )
        self.assertEqual(chart.layout.xaxis.type, "category")
        self.assertEqual(len(chart.layout.xaxis.tickvals), 2)
        self.assertEqual(chart.layout.xaxis.ticktext[0], "01/09")
        self.assertEqual(chart.layout.xaxis.ticktext[-1], "30/09")
        self.assertEqual(len(chart.data[0].x), 2)
        self.assertEqual(list(chart.data[0].y), [0.99, 0.98])
        self.assertEqual(chart.data[0].mode, "lines+markers+text")
        self.assertEqual(chart.data[0].y[-1], 0.98)

    def test_zero_ppm_with_positive_input_remains_visible(self):
        frame = pd.DataFrame({
            "PeriodDate": pd.to_datetime(["2026-09-01", "2026-09-02", "2026-09-03"]),
            "Period": ["01/09", "02/09", "03/09"],
            "Input": [100, 0, 50],
            "PPM": [1200.0, 0.0, 0.0],
        })
        chart = self.builders["smt_kpi_line_chart"](
            frame, "Period", "PPM", "Process NG", "#0D7A45", "ppm",
            period_start=date(2026, 9, 1), period_end=date(2026, 9, 3),
            input_columns=("Input",),
        )
        self.assertEqual(list(chart.layout.xaxis.ticktext), ["01/09", "03/09"])
        self.assertEqual(list(chart.data[0].y), [1200.0, 0.0])

    def test_combined_inspection_needs_both_inputs(self):
        frame = pd.DataFrame({
            "PeriodDate": pd.to_datetime(["2026-09-01", "2026-09-02", "2026-09-03"]),
            "Period": ["01/09", "02/09", "03/09"],
            "OQCInspected": [10, 10, 0],
            "FQCInspected": [10, 0, 10],
            "CombinedPassRate": [0.99, None, None],
        })
        chart = self.builders["smt_kpi_line_chart"](
            frame, "Period", "CombinedPassRate", "OQC × FQC", "#0D7A45", "percent",
            period_start=date(2026, 9, 1), period_end=date(2026, 9, 3),
            input_columns=("OQCInspected", "FQCInspected"),
        )
        self.assertEqual(list(chart.layout.xaxis.ticktext), ["01/09"])


if __name__ == "__main__":
    unittest.main()
