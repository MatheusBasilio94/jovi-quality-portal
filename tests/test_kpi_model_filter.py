import ast
from datetime import date
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from tools import assembly_kpi_v2, smt_quality_dashboard
from tools.kpi_model_filter import filter_model_records, model_options
from tools.smt_glue_scenario import apply_glue_exclusion


APP = Path(__file__).resolve().parents[1] / "app.py"


def load_functions(*names, **namespace):
    tree = ast.parse(APP.read_text(encoding="utf-8-sig"))
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    for node in selected:
        node.decorator_list = []
    namespace.setdefault("date", date)
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(APP), "exec"), namespace)
    return namespace


class KPIModelTests(unittest.TestCase):
    def test_inspections_match_model_and_never_fall_back_to_all_records(self):
        records = pd.DataFrame({"Model": ["M1", " m1 ", "M2", None], "OK": [98, 95, 190, 500]})
        self.assertEqual(model_options(records), ["M1", "M2"])
        self.assertEqual(filter_model_records(records, "m1")["OK"].sum(), 193)
        self.assertTrue(filter_model_records(records, "M3").empty)
        self.assertTrue(filter_model_records(records.drop(columns="Model"), "M1").empty)
        pd.testing.assert_frame_equal(filter_model_records(records), records)

    def test_smt_model_scopes_input_defects_trends_and_glue_simulation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            input_path, defect_path = root / "input.xlsx", root / "defects.xlsx"
            inputs = pd.DataFrame({
                "model": ["M1", "M2", "M3"], "Input": [100, 200, 50], "BadMachine": [2, 3, 0],
                "BeginDate": ["2026-10-01"] * 3, "EndDate": ["2026-10-01"] * 3,
            })
            with pd.ExcelWriter(input_path, engine="openpyxl") as writer:
                inputs.to_excel(writer, sheet_name="ModelData", index=False)
                inputs.assign(DisplayMode="Line 1").to_excel(writer, sheet_name="OrgDisplay", index=False)
            defects = pd.DataFrame({
                "PCB": ["A", "B", "C", "D", "E"], "model": ["M1", "M1", "M2", "M2", "M2"],
                "TestOperation": ["Download", "SMT-Visual-Inspection", "Download", "Download", "AOI-Checking"],
                "Fault Phenomenon": ["Functional", "Disperse glue", "Functional", "Functional", "Solder"],
                "BadMachEntryTime": ["2026-10-01 08:00"] * 5, "TestTime": ["2026-10-01 08:00"] * 5,
                "DutyType": ["SMT Process"] * 5,
            })
            with pd.ExcelWriter(defect_path, engine="openpyxl") as writer:
                defects.to_excel(writer, sheet_name="Detail", index=False)
                summary = {"OnceDamage": [5], **{f"{count}TimesDamage": [0] for count in range(2, 7)}}
                pd.DataFrame(summary).to_excel(writer, sheet_name="BadMachine", index=False)
            signatures = tuple((smt_quality_dashboard.path_signature(path),) for path in [input_path, defect_path])
            def calculate(model=None):
                return smt_quality_dashboard.analyze_smt_quality_paths(
                    *signatures, "2026-10-01", "2026-10-01", model=model,
                )
            all_models = calculate()
            selected = calculate("M1")
            self.assertEqual(all_models["totals"]["Produced"], 350)
            self.assertEqual(all_models["totals"]["ClassifiedDefectPCBs"], 5)
            self.assertEqual(selected["totals"]["Produced"], 100)
            self.assertEqual(selected["totals"]["FunctionPassRate"], .99)
            self.assertEqual(selected["trend"]["SMTProcessNGRatePPM"].tolist(), [20000])
            self.assertEqual(set(selected["covered_raw"]["Model"]), {"M1"})
            self.assertEqual(set(selected["selected_org"]["Model"]), {"M1"})
            simulated = apply_glue_exclusion(selected, {"Operation": ["SMT-Visual-Inspection"], "Phenomenon": ["Disperse glue"]})
            self.assertEqual(simulated["totals"]["SMTProcessNGRatePPM"], 10000)
            zero = calculate("M3")
            self.assertEqual(zero["totals"]["FunctionPassRate"], 1)
            self.assertEqual(zero["trend"]["SMTProcessNGRatePPM"].tolist(), [0])
            self.assertEqual(calculate()["totals"]["ClassifiedDefectPCBs"], 5)

    def test_assembly_model_scopes_input_mando_and_smt_duty(self):
        inputs = pd.DataFrame({"Date": pd.to_datetime(["2026-10-01"] * 3),
                               "Model": ["M1", "M2", "M3"], "Input": [100, 200, 50]})
        defects = pd.DataFrame({
            "DefectDate": pd.to_datetime(["2026-10-01"] * 3), "Model": ["M1", "M1", "M2"],
            "PCBNormalized": ["A", "B", "C"], "FailureType": ["Funcional", "Aparência", "Funcional"],
            "Operation": ["Audio-Testing", "Appearance-QC", "Audio-Testing"],
            "IsFunctionMando": [False, False, True], "IsSMTDuty": [True, False, False],
            "ResponsibilityPending": [False] * 3, "FinalDutyType": ["SMT Process", "Other", "Mando"],
        })
        ns = load_functions("calculate_assembly_kpi_metrics_cached", "calculate_assembly_smt_duty_kpi",
                            assembly_kpi_v2=assembly_kpi_v2,
                            prepare_assembly_kpi_sources_cached=lambda *_: (inputs, defects))
        def calculate(start=date(2026, 10, 1), end=date(2026, 10, 1), *, model=None):
            return ns["calculate_assembly_kpi_metrics_cached"](
                (), (), (), start.isoformat(), end.isoformat(), "test", model=model)
        ns["calculate_assembly_kpi_metrics"] = calculate
        selected = calculate(model="M1")
        self.assertEqual(selected["produced"], 100)
        self.assertEqual(selected["function_pass_rate"], .99)
        self.assertEqual(selected["appearance_pass_rate"], .99)
        self.assertEqual(selected["function_mando_ppm"], 0)
        self.assertEqual(selected["trend"]["SMTDutyPPM"].tolist(), [10000])
        self.assertEqual(set(selected["defects"]["Model"]), {"M1"})
        duty = ns["calculate_assembly_smt_duty_kpi"](date(2026, 10, 1), date(2026, 10, 1), model="M1")
        self.assertEqual((duty["produced"], duty["duty_defects"], duty["duty_ppm"]), (100, 1, 10000))
        zero = calculate(model="M3")
        self.assertEqual((zero["produced"], zero["function_pass_rate"], zero["function_mando_ppm"]), (50, 1, 0))
        self.assertEqual(calculate()["produced"], 350)
        self.assertEqual(len(inputs), 3)
        self.assertEqual(len(defects), 3)

    def test_model_control_selection_and_period_change(self):
        from streamlit.testing.v1 import AppTest
        tree = ast.parse(APP.read_text(encoding="utf-8-sig"))
        control = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "kpi_track_model_control")
        script = "import streamlit as st\nimport pandas as pd\n" + ast.unparse(control) + """
models = st.session_state.get("test_models", ["M1", "M2"])
selected = kpi_track_model_control(pd.DataFrame({"Model": models}), "test_model")
st.text(selected or "all")
"""
        app = AppTest.from_string(script).run()
        self.assertFalse(app.exception)
        self.assertEqual(app.selectbox[0].options, ["All models", "M1", "M2"])
        app.selectbox[0].select("M1").run()
        self.assertEqual(app.text[0].value, "M1")
        app.session_state["test_models"] = ["M2"]
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(app.selectbox[0].value, "All models")


if __name__ == "__main__":
    unittest.main()
