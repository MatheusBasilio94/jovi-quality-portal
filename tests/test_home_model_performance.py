import unittest

import pandas as pd

from tools.home_model_performance import (
    assembly_model_daily, mini_trend_svg, recent_models, smt_model_daily,
)


class HomeModelPerformanceTests(unittest.TestCase):
    def test_smt_uses_unique_classified_pcbs_and_blocks_missing_coverage(self):
        inputs = pd.DataFrame([
            {"Model": "A", "BeginDate": "2026-09-28", "EndDateExclusive": "2026-09-29", "Input": 100},
            {"Model": "A", "BeginDate": "2026-09-29", "EndDateExclusive": "2026-09-30", "Input": 50},
            {"Model": "B", "BeginDate": "2026-09-28", "EndDateExclusive": "2026-09-29", "Input": 10},
        ])
        defects = pd.DataFrame([
            {"Model": "A", "KPIDate": "2026-09-28", "PCB": "P1", "FailureType": "Functional Failure", "IsRejudgeOK": False},
            {"Model": "A", "KPIDate": "2026-09-28", "PCB": "P1", "FailureType": "Appearance Failure", "IsRejudgeOK": False},
            {"Model": "A", "KPIDate": "2026-09-28", "PCB": "P2", "FailureType": "Unclassified", "IsRejudgeOK": False},
            {"Model": "A", "KPIDate": "2026-09-28", "PCB": "P3", "FailureType": "Functional Failure", "IsRejudgeOK": True},
        ])
        result = smt_model_daily({
            "selected_input": inputs,
            "covered_raw": defects,
            "source_defect_start": "2026-09-28",
            "source_defect_end": "2026-09-28",
        })
        first = result[(result["Model"] == "A") & (result["Date"] == pd.Timestamp("2026-09-28"))].iloc[0]
        self.assertEqual(first["Defects"], 1)
        self.assertEqual(first["PPM"], 10_000)
        latest = result[(result["Model"] == "A") & (result["Date"] == pd.Timestamp("2026-09-29"))].iloc[0]
        self.assertEqual(latest["Status"], "Awaiting FPY defects")
        self.assertTrue(pd.isna(latest["PPM"]))
        model_b = result[result["Model"] == "B"].iloc[0]
        self.assertEqual(model_b["PPM"], 0)

    def test_assembly_mando_uses_unique_pcbs_and_classified_input_validation(self):
        inputs = pd.DataFrame([
            {"Model": "A", "Date": "2026-09-28", "Input": 10},
            {"Model": "B", "Date": "2026-09-28", "Input": 1},
        ])
        defects = pd.DataFrame([
            {"Model": "A", "DefectDate": "2026-09-28", "PCBNormalized": "P1", "FailureType": "Funcional", "IsFunctionMando": True},
            {"Model": "A", "DefectDate": "2026-09-28", "PCBNormalized": "P1", "FailureType": "Funcional", "IsFunctionMando": True},
            {"Model": "B", "DefectDate": "2026-09-28", "PCBNormalized": "P2", "FailureType": "Funcional", "IsFunctionMando": True},
            {"Model": "B", "DefectDate": "2026-09-28", "PCBNormalized": "P3", "FailureType": "Aparência", "IsFunctionMando": False},
        ])
        result = assembly_model_daily({
            "inputs": inputs,
            "defects": defects,
            "source_defect_start": "2026-09-28",
            "source_defect_end": "2026-09-28",
        })
        self.assertEqual(result[result["Model"] == "A"].iloc[0]["PPM"], 100_000)
        blocked = result[result["Model"] == "B"].iloc[0]
        self.assertEqual(blocked["Status"], "Defects exceed input")
        self.assertTrue(pd.isna(blocked["PPM"]))

    def test_smt_does_not_invent_daily_input_from_weekly_source(self):
        inputs = pd.DataFrame([
            {"Model": "Weekly", "BeginDate": "2026-09-21", "Input": 500, "Granularity": "weekly"},
            {"Model": "Daily", "BeginDate": "2026-09-29", "Input": 100, "Granularity": "daily"},
        ])
        result = smt_model_daily({
            "selected_input": inputs,
            "covered_raw": pd.DataFrame(columns=["Model", "KPIDate", "PCB", "FailureType", "IsRejudgeOK"]),
            "source_defect_start": "2026-09-29",
            "source_defect_end": "2026-09-29",
        })
        self.assertEqual(result["Model"].tolist(), ["Daily"])

    def test_models_rank_by_latest_input_then_that_days_volume(self):
        smt = pd.DataFrame([
            {"Model": "Older", "Date": pd.Timestamp("2026-09-28"), "Input": 1000},
            {"Model": "Recent", "Date": pd.Timestamp("2026-09-29"), "Input": 10},
            {"Model": "SameDay", "Date": pd.Timestamp("2026-09-29"), "Input": 30},
        ])
        assembly = pd.DataFrame([
            {"Model": "Recent", "Date": pd.Timestamp("2026-09-29"), "Input": 40},
        ])
        self.assertEqual(
            [row["Model"] for row in recent_models(smt, assembly)],
            ["Recent", "SameDay", "Older"],
        )

    def test_missing_daily_kpi_breaks_chart_line(self):
        daily = pd.DataFrame([
            {"Date": "2026-09-28", "PPM": 100},
            {"Date": "2026-09-29", "PPM": float("nan")},
            {"Date": "2026-09-30", "PPM": 150},
        ])
        self.assertNotIn("<polyline", mini_trend_svg(daily, 5000, "#087A8C"))


if __name__ == "__main__":
    unittest.main()
