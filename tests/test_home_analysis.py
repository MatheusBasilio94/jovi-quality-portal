import unittest
from datetime import date

import pandas as pd

from tools.home_analysis import KPI_OPTIONS, build_home_kpi_rows


class HomeAnalysisTests(unittest.TestCase):
    def test_home_only_offers_the_six_requested_kpis(self):
        self.assertEqual(KPI_OPTIONS["SMT"], (
            "Functional Pass Rate", "SMT Process NG Rate (PPM)",
            "Assembly SMT Process Duty NG Rate (PPM)",
        ))
        self.assertEqual(KPI_OPTIONS["Assembly"], (
            "Functional Pass Rate", "Appearance Pass Rate", "Function Mando (PPM)",
        ))

    def test_assembly_week_recalculates_unique_pcbs_instead_of_adding_daily_rates(self):
        inputs = pd.DataFrame([
            {"Date": pd.Timestamp("2026-09-21"), "Model": "A", "Input": 100},
            {"Date": pd.Timestamp("2026-09-22"), "Model": "A", "Input": 200},
        ])
        defects = pd.DataFrame([
            {"DefectDate": pd.Timestamp(day), "Model": "A", "PCBNormalized": "SN1",
             "FailureType": "Funcional", "IsFunctionMando": True, "IsSMTDuty": False}
            for day in ("2026-09-21", "2026-09-22")
        ])
        frame = build_home_kpi_rows("Assembly", "Function Mando (PPM)", "Weeks", ["A"],
                                    date(2026, 9, 21), date(2026, 9, 22),
                                    inputs, defects)
        self.assertEqual(frame["Period"].tolist(), ["WK39"])
        self.assertEqual(frame.iloc[0]["DefectPCBs"], 1)
        self.assertAlmostEqual(frame.iloc[0]["Value"], 1_000_000 / 300)

    def test_smt_summary_input_is_not_turned_into_daily_input(self):
        inputs = pd.DataFrame([{"BeginDate": pd.Timestamp("2026-09-21"),
                                "EndDateExclusive": pd.Timestamp("2026-09-28"),
                                "Model": "A", "Input": 1000}])
        defects = pd.DataFrame(columns=["KPIDate", "Model", "PCB", "FailureType", "IsRejudgeOK"])
        daily = build_home_kpi_rows("SMT", "Functional Pass Rate", "Days", ["A"], date(2026, 9, 21),
                                    date(2026, 9, 27), inputs, defects)
        weekly = build_home_kpi_rows("SMT", "Functional Pass Rate", "Weeks", ["A"], date(2026, 9, 21),
                                     date(2026, 9, 27), inputs, defects)
        self.assertTrue(daily.empty)
        self.assertEqual(weekly.iloc[0]["Input"], 1000)
        self.assertEqual(weekly.iloc[0]["Value"], 1)

    def test_smt_pre_distributed_weekly_input_stays_unavailable_daily(self):
        inputs = pd.DataFrame([
            {"BeginDate": pd.Timestamp(f"2026-09-{day:02d}"),
             "EndDateExclusive": pd.Timestamp(f"2026-09-{day + 1:02d}"),
             "Model": "A", "Input": 100, "Granularity": "weekly"}
            for day in range(21, 28)
        ])
        defects = pd.DataFrame(columns=["KPIDate", "Model", "PCB", "FailureType", "IsRejudgeOK"])
        daily = build_home_kpi_rows("SMT", "SMT Process NG Rate (PPM)", "Days", ["A"],
                                    date(2026, 9, 21), date(2026, 9, 27), inputs, defects)
        weekly = build_home_kpi_rows("SMT", "SMT Process NG Rate (PPM)", "Weeks", ["A"],
                                     date(2026, 9, 21), date(2026, 9, 27), inputs, defects)
        self.assertTrue(daily.empty)
        self.assertEqual(weekly.iloc[0]["Input"], 700)

    def test_appearance_rate_uses_unique_appearance_pcbs(self):
        inputs = pd.DataFrame([{"Date": pd.Timestamp("2026-09-21"), "Model": "A", "Input": 100}])
        defects = pd.DataFrame([
            {"DefectDate": pd.Timestamp("2026-09-21"), "Model": "A", "PCBNormalized": pcb,
             "FailureType": "Aparência", "IsFunctionMando": False, "IsSMTDuty": False}
            for pcb in ("SN1", "SN1", "SN2")
        ])
        frame = build_home_kpi_rows("Assembly", "Appearance Pass Rate", "Days", ["A"],
                                    date(2026, 9, 21), date(2026, 9, 21), inputs, defects)
        self.assertEqual(frame.iloc[0]["DefectPCBs"], 2)
        self.assertEqual(frame.iloc[0]["Value"], .98)

    def test_smt_duty_uses_assembly_input_and_its_own_validity_rule(self):
        inputs = pd.DataFrame([{"Date": pd.Timestamp("2026-09-21"), "Model": "A", "Input": 100}])
        defects = pd.DataFrame([
            {"DefectDate": pd.Timestamp("2026-09-21"), "Model": "A", "PCBNormalized": pcb,
             "FailureType": "Funcional", "IsFunctionMando": False, "IsSMTDuty": pcb == "SN1"}
            for pcb in ("SN1", "SN1", *(f"SN{index}" for index in range(2, 102)))
        ])
        frame = build_home_kpi_rows("SMT", "Assembly SMT Process Duty NG Rate (PPM)", "Days", ["A"],
                                    date(2026, 9, 21), date(2026, 9, 21), inputs, defects)
        self.assertEqual(frame.iloc[0]["DefectPCBs"], 1)
        self.assertEqual(frame.iloc[0]["Value"], 10000)
        self.assertEqual(frame.iloc[0]["Status"], "Valid")

    def test_unavailable_kpi_when_defects_exceed_input(self):
        inputs = pd.DataFrame([{"Date": pd.Timestamp("2026-09-21"), "Model": "A", "Input": 1}])
        defects = pd.DataFrame([
            {"DefectDate": pd.Timestamp("2026-09-21"), "Model": "A", "PCBNormalized": sn,
             "FailureType": "Funcional", "IsFunctionMando": True, "IsSMTDuty": False}
            for sn in ("SN1", "SN2")
        ])
        frame = build_home_kpi_rows("Assembly", "Functional Pass Rate", "Days", ["A"],
                                    date(2026, 9, 21), date(2026, 9, 21),
                                    inputs, defects)
        self.assertTrue(pd.isna(frame.iloc[0]["Value"]))
        self.assertIn("Blocked", frame.iloc[0]["Status"])


if __name__ == "__main__":
    unittest.main()
