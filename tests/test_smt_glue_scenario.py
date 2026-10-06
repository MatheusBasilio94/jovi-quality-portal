import unittest
import ast
from pathlib import Path

import pandas as pd

from tools.smt_glue_scenario import build_glue_scenarios


class GlueScenarioTests(unittest.TestCase):
    def analysis(self):
        data = pd.DataFrame({
            "PCB": ["A", "A", "B", "B", "C", "D", "E"],
            "Operation": ["Glue dispensing", "Glue dispensing", "Glue dispensing", "AOI", "AOI", "Glue dispensing", "Glue dispensing"],
            "FailureType": ["Appearance Failure"] * 6 + ["Unclassified"],
            "IsRejudgeOK": [False] * 5 + [True, False],
            "KPIDate": pd.to_datetime(["2026-09-01"] * 3 + ["2026-09-02"] * 4),
        })
        trend = pd.DataFrame({
            "PeriodStart": pd.to_datetime(["2026-09-01", "2026-09-02"]),
            "PeriodEndExclusive": pd.to_datetime(["2026-09-02", "2026-09-03"]),
            "Input": [10, 20],
        })
        return {"covered_raw": data, "trend": trend, "totals": {"Produced": 30}}

    def test_preserves_mixed_boards_and_uses_distinct_pcbs(self):
        original = self.analysis()
        result = build_glue_scenarios(original, {"Operation": [" glue  dispensing "]})
        totals = result["totals"]
        self.assertEqual((totals["WithGlueNG"], totals["WithoutGlueNG"]), (3, 2))
        self.assertEqual((totals["GlueOnlyNG"], totals["GlueMixedNG"]), (1, 1))
        self.assertAlmostEqual(totals["WithoutGluePPM"], 2 / 30 * 1_000_000)
        self.assertEqual(result["trend"]["WithoutGlueNG"].tolist(), [0, 2])
        self.assertNotIn("ScenarioGlueRecord", original["covered_raw"])
        self.assertEqual(set(result["audit"]["PCB"]), {"A", "B"})

    def test_no_rules_preserves_original_and_invalid_denominators(self):
        analysis = self.analysis()
        analysis["totals"]["Produced"] = 0
        analysis["trend"]["Input"] = [1, 0]
        result = build_glue_scenarios(analysis, {})
        self.assertEqual(result["totals"]["WithGlueNG"], result["totals"]["WithoutGlueNG"])
        self.assertIsNone(result["totals"]["WithoutGluePPM"])
        self.assertTrue(result["trend"]["WithoutGluePPM"].isna().all())

    def test_station_and_phenomenon_must_both_match(self):
        analysis = self.analysis()
        records = analysis["covered_raw"]
        records["Operation"] = "SMT-Visual-Inspection"
        records["Phenomenon"] = ["Disperse glue", "Disperse glue", "Disperse glue", "Solder", "Solder", "Disperse glue", "Disperse glue"]
        result = build_glue_scenarios(analysis, {
            "Operation": ["SMT-Visual-Inspection"], "Phenomenon": ["Disperse glue"],
        })
        self.assertEqual(result["totals"]["WithoutGlueNG"], 2)
        self.assertEqual(result["totals"]["GlueOnlyNG"], 1)

    def test_controls_render_include_exclude_and_compare(self):
        from streamlit.testing.v1 import AppTest
        app_path = Path(__file__).resolve().parents[1] / "app.py"
        tree = ast.parse(app_path.read_text(encoding="utf-8-sig"))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "smt_glue_scenario_controls")
        script = '''
import streamlit as st
import pandas as pd
def fmt_ppm(value):
    return f"{value:,.0f}"
def styled_table(frame):
    st.dataframe(frame)
analysis = {
    "totals": {"Produced": 10},
    "covered_raw": pd.DataFrame({
        "PCB": ["A", "B"], "Operation": ["SMT-Visual-Inspection"] * 2,
        "Phenomenon": ["Disperse glue", "Solder"],
        "IsRejudgeOK": [False, False], "FailureType": ["Appearance Failure"] * 2,
        "KPIDate": pd.to_datetime(["2026-09-01"] * 2),
    }),
    "trend": pd.DataFrame({
        "Period": ["01/09"], "Input": [10],
        "PeriodStart": pd.to_datetime(["2026-09-01"]),
        "PeriodEndExclusive": pd.to_datetime(["2026-09-02"]),
    }),
}
'''
        app = AppTest.from_string(script + ast.unparse(function) + "\nsmt_glue_scenario_controls(analysis)\n").run()
        self.assertEqual(len(app.exception), 0)
        for mode in ("Exclude glue defects", "Compare scenarios", "Include glue defects"):
            app.selectbox(key="smt_glue_scenario_mode").set_value(mode).run()
            self.assertEqual(len(app.exception), 0)
            if mode != "Include glue defects":
                summary = app.dataframe[0].value
                self.assertEqual(summary["Process NG PCB"].tolist(), [2, 1])


if __name__ == "__main__":
    unittest.main()
