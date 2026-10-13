import ast
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from contextlib import nullcontext
from types import SimpleNamespace

import pandas as pd

from tools import smt_quality_dashboard
from tools.smt_glue_scenario import apply_glue_exclusion


APP = Path(__file__).resolve().parents[1] / "app.py"


def load_functions(*names, **namespace):
    tree = ast.parse(APP.read_text(encoding="utf-8-sig"))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    namespace.setdefault("date", date)
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(APP), "exec"), namespace)
    return namespace


def analysis():
    return {
        "totals": {"Produced": 30, "FunctionPassRate": .95, "FunctionPassStatus": "Valid",
                   "SMTProcessNGRatePPM": 100000, "SMTProcessStatus": "Valid"},
        "covered_raw": pd.DataFrame({
            "PCB": ["A", "B", "B", "C"],
            "Operation": ["Glue", "Glue", "AOI", "AOI"],
            "FailureType": ["Appearance Failure"] * 4,
            "IsRejudgeOK": [False] * 4,
            "KPIDate": pd.to_datetime(["2026-09-01", "2026-09-02", "2026-09-02", "2026-09-02"]),
        }),
        "trend": pd.DataFrame({
            "PeriodStart": pd.to_datetime(["2026-09-01", "2026-09-02"]),
            "PeriodEndExclusive": pd.to_datetime(["2026-09-02", "2026-09-03"]),
            "Input": [10, 20], "FunctionPassRate": [.9, 1], "FunctionPassStatus": ["Valid"] * 2,
            "SMTProcessNGRatePPM": [100000, 100000], "SMTProcessStatus": ["Valid"] * 2,
        }),
    }


class ReviewGlueTests(unittest.TestCase):
    def test_comparison_charts_keep_all_periods_and_zero_values(self):
        captured = []
        ns = load_functions("kpi_review_glue_comparison", "monthly_kpi_slide_panels",
                            st=SimpleNamespace(expander=lambda *_args, **_kwargs: nullcontext(),
                                               tabs=lambda names: [nullcontext() for _ in names]),
                            kpi_review_table=lambda *_: None,
                            build_kpi_panel_chart=lambda panel: panel,
                            show_chart=lambda panel, **_: captured.append(panel))
        directory = ({"source": "smt_process", "kpi": "Process NG", "target": 5000, "direction": "max"},)
        original = [("WK40", {"smt_process": 1000}, {}), ("WK41", {"smt_process": 2000}, {})]
        excluded = [("WK40", {"smt_process": 0}, {}), ("WK41", {"smt_process": 500}, {})]
        days = [date(2026, 9, day) for day in (1, 2, 3)]
        ns["kpi_review_glue_comparison"](
            directory, original, excluded,
            {"smt_function": dict.fromkeys(days[:2], 1), "smt_process": {days[0]: 3000, days[1]: 0}},
            {"smt_process": {days[0]: 0, days[1]: 0}}, days, {}, {}, "weekly_test",
        )
        self.assertEqual(len(captured), 2)
        self.assertEqual(captured[0]["frame"]["Period"].tolist(), ["WK40", "WK41", "01-Sep", "02-Sep"])
        self.assertEqual(captured[1]["frame"]["Value"].tolist(), [0, 500, 0, 0])
        captured.clear()
        original.append(("Oct", {"smt_process": 3000}, {}))
        excluded.append(("Oct", {"smt_process": 1000}, {}))
        ns["kpi_review_glue_comparison"](directory, original, excluded, {}, {}, [], {}, {}, "monthly_test")
        self.assertEqual(captured[1]["frame"]["Value"].tolist(), [0, 500, 1000])

    def test_simulation_preserves_other_kpis_and_cached_source(self):
        original = analysis()
        simulated = apply_glue_exclusion(original, {"Operation": ["Glue"]})
        self.assertEqual(simulated["totals"]["ClassifiedDefectPCBs"], 2)
        self.assertEqual(simulated["trend"]["SMTProcessNGRatePPM"].tolist(), [0, 100000])
        self.assertEqual(simulated["totals"]["FunctionPassRate"], .95)
        self.assertEqual(original["totals"]["SMTProcessNGRatePPM"], 100000)
        self.assertEqual(original["trend"]["SMTProcessNGRatePPM"].tolist(), [100000, 100000])

    def test_report_total_and_daily_values_use_same_scenario(self):
        directory = tuple({"source": source} for source in ["smt_function", "smt_process", "smt_oqc", "smt_assembly_duty", "assembly_function", "assembly_appearance", "assembly_mando", "assembly_oqc_fqc"])
        ns = load_functions("weekly_kpi_review_data", WEEKLY_KPI_DIRECTORY=directory,
                            load_smt_oqc_inspections=lambda *_: pd.DataFrame(),
                            calculate_assembly_kpi_metrics=lambda *_: {"function_pass_rate": .98, "appearance_pass_rate": .99, "function_mando_ppm": 2000},
                            calculate_assembly_smt_duty_kpi=lambda *_: {"duty_ppm": 200},
                            load_assembly_oqc_fqc_inspections=lambda *_: pd.DataFrame())
        with patch.object(smt_quality_dashboard, "stored_smt_sources", return_value=(["input"], ["defect"])), \
             patch.object(smt_quality_dashboard, "path_signature", side_effect=lambda value: value), \
             patch.object(smt_quality_dashboard, "analyze_smt_quality_paths", return_value=analysis()):
            original = ns["weekly_kpi_review_data"](date(2026, 9, 1), date(2026, 9, 2))
            excluded = ns["weekly_kpi_review_data"](date(2026, 9, 1), date(2026, 9, 2), glue_rules={"Operation": ["Glue"]})
        self.assertFalse(excluded[2])
        self.assertAlmostEqual(excluded[0]["smt_process"], 2 / 30 * 1e6)
        self.assertEqual(excluded[1]["smt_process"][date(2026, 9, 1)], 0)
        self.assertEqual(excluded[1]["smt_process"][date(2026, 9, 2)], 100000)
        for source in original[0]:
            if source != "smt_process":
                self.assertEqual(original[0][source], excluded[0][source])
        self.assertEqual(original[1]["smt_function"], excluded[1]["smt_function"])

    def test_report_controls_include_exclude_compare(self):
        from streamlit.testing.v1 import AppTest
        tree = ast.parse(APP.read_text(encoding="utf-8-sig"))
        control = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "kpi_review_glue_controls")
        script = "import streamlit as st\nfrom datetime import date\nfrom tools import smt_quality_dashboard\nsmt_quality_dashboard.stored_smt_sources = lambda: ([], [])\n" + ast.unparse(control)
        script += "\nmode, rules = kpi_review_glue_controls(date(2026, 9, 1), date(2026, 9, 30), 'test_review')\nst.json(rules)"
        app = AppTest.from_string(script).run()
        for mode in ["Exclude glue defects", "Compare scenarios", "Include glue defects"]:
            app.segmented_control(key="test_review_glue_mode").set_value(mode).run()
            self.assertFalse(app.exception)
            self.assertEqual(app.multiselect(key="test_review_glue_rule_Phenomenon").value, ["Disperse glue"])


if __name__ == "__main__":
    unittest.main()
