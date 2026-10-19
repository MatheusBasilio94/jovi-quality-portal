import ast
from numbers import Number
from pathlib import Path
import unittest

import pandas as pd


APP = Path(__file__).resolve().parents[1] / "app.py"


def dashboard_analysis():
    records = pd.DataFrame({
        "PCB": ["A", "A", "B", "B", "C", "D", "E"],
        "Model": ["M1"] * 6 + ["M2"],
        "Operation": ["SMT-Visual-Inspection"] * 3 + ["PCBA-Testing", "SMT-Visual-Inspection", "AOI-Checking", "SMT-Visual-Inspection"],
        "Phenomenon": ["Disperse glue", " disperse  GLUE ", "Disperse glue", "NG component", "Solder", "Disperse glue", "Disperse glue"],
        "FailureType": ["Appearance Failure"] * 3 + ["Functional Failure"] + ["Appearance Failure"] * 3,
        "DutyType": ["SMT"] * 7,
        "FaultReason": [""] * 7,
        "IsRejudgeOK": [False] * 7,
        "HasExactInputCoverage": [True] * 7,
        "KPIDate": pd.to_datetime(["2026-10-01"] * 7),
    })
    return {
        "raw": records.copy(), "covered_raw": records.copy(),
        "selected_input": pd.DataFrame({
            "Model": ["M1", "M2"], "Input": [100, 20],
            "BeginDate": pd.to_datetime(["2026-10-01"] * 2),
            "EndDateExclusive": pd.to_datetime(["2026-10-02"] * 2),
        }),
        "trend": pd.DataFrame({
            "Period": ["01/10"], "PeriodStart": pd.to_datetime(["2026-10-01"]),
            "PeriodEndExclusive": pd.to_datetime(["2026-10-02"]),
        }),
    }


def functions(*names):
    tree = ast.parse(APP.read_text(encoding="utf-8-sig"))
    return "\n\n".join(ast.unparse(node) for node in tree.body
                        if isinstance(node, ast.FunctionDef) and node.name in names)


class DashboardGlueTests(unittest.TestCase):
    def setUp(self):
        namespace = {"Number": Number}
        exec(functions("_dashboard_defect_key", "_dashboard_priority", "_build_smt_dashboard_view"), namespace)
        self.build = namespace["_build_smt_dashboard_view"]
        self.rules = {"Operation": ["SMT-Visual-Inspection"], "Phenomenon": ["Disperse glue"]}

    def test_glue_hidden_everywhere_without_losing_mixed_boards_or_input(self):
        analysis = dashboard_analysis()
        saved = {key: frame.copy(deep=True) for key, frame in analysis.items()}
        original = self.build(analysis, "All", "All", "All")
        hidden = self.build(analysis, "All", "All", "All", glue_rules=self.rules)
        self.assertEqual((original["confirmed_pcbs"], hidden["confirmed_pcbs"]), (5, 3))
        self.assertEqual((original["produced"], hidden["produced"]), (120, 120))
        self.assertEqual(set(hidden["confirmed"]["PCB"]), {"B", "C", "D"})
        self.assertEqual(hidden["functional_pcbs"], original["functional_pcbs"])
        self.assertAlmostEqual(hidden["overall_ppm"], 3 / 120 * 1e6)
        self.assertEqual(hidden["trend"]["ConfirmedDefectPCBs"].tolist(), [3])
        self.assertEqual(hidden["models"]["NGPCBs"].sum(), 3)
        self.assertEqual(hidden["pareto"]["NGPCBs"].sum(), 3)
        for key in saved:
            pd.testing.assert_frame_equal(analysis[key], saved[key])

    def test_zero_defects_and_model_filter_keep_input_and_valid_zero_ppm(self):
        analysis = dashboard_analysis()
        hidden = self.build(analysis, ["M2"], "All", "All", glue_rules=self.rules)
        self.assertEqual(hidden["produced"], 20)
        self.assertTrue(hidden["confirmed"].empty)
        self.assertEqual(hidden["overall_ppm"], 0)
        self.assertEqual(hidden["trend"]["ProcessPPM"].tolist(), [0])
        no_rules = self.build(analysis, "All", "All", "All", glue_rules={})
        self.assertEqual(no_rules["confirmed_pcbs"], 5)

    def test_control_toggles_scenario_and_preserves_custom_definition(self):
        from streamlit.testing.v1 import AppTest
        script = """
import streamlit as st
from numbers import Number
from tests.test_smt_dashboard_glue import dashboard_analysis
SMT_DEFECT_DIMENSIONS = [("Phenomenon", "Phenomenon", "", "")]
""" + functions("_dashboard_defect_key", "_dashboard_priority", "_build_smt_dashboard_view",
                 "_clear_smt_breakdown_selections", "smt_dashboard_glue_controls") + """
analysis = dashboard_analysis()
rules = smt_dashboard_glue_controls(analysis)
view = _build_smt_dashboard_view(analysis, "All", "All", "All", glue_rules=rules)
st.metric("Defect PCB", view["confirmed_pcbs"])
"""
        app = AppTest.from_string(script).run()
        self.assertFalse(app.exception)
        self.assertEqual(app.metric[0].value, "5")
        app.session_state["smt_breakdown_Phenomenon"] = "Disperse glue"
        app.checkbox(key="smt_quality_v2_hide_glue").check().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.metric[0].value, "3")
        self.assertEqual(app.session_state["smt_breakdown_Phenomenon"], "All")
        app.multiselect(key="smt_quality_v2_glue_rule_Phenomenon").set_value(["Solder"]).run()
        self.assertEqual(app.metric[0].value, "4")
        app.checkbox(key="smt_quality_v2_hide_glue").uncheck().run()
        self.assertEqual(app.metric[0].value, "5")
        app.checkbox(key="smt_quality_v2_hide_glue").check().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.metric[0].value, "4")
        self.assertEqual(app.multiselect(key="smt_quality_v2_glue_rule_Phenomenon").value, ["Solder"])


if __name__ == "__main__":
    unittest.main()
