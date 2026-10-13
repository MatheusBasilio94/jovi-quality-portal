import unittest
import pandas as pd
from tools.production_preparation import history, rounded_forecast, simulate, suggest_actions


def records(area="SMT"):
    return pd.DataFrame({
        "Model": ["MODEL"] * 4,
        "PCB": ["A", "A", "B", "C"], "PCBNormalized": ["A", "A", "B", "C"],
        "Phenomenon": ["Glue", "Functional", "Glue", "Rejudged"],
        "FailureType": (["Appearance Failure", "Functional Failure", "Appearance Failure", "Functional Failure"]
                        if area == "SMT" else ["Aparência", "Funcional", "Aparência", "Funcional"]),
        "IsRejudgeOK": [False, False, False, True],
        "IsFunctionMando": [False, True, False, True], "IsSMTDuty": [False] * 4,
        "KPIDate": pd.to_datetime(["2026-10-01"] * 4),
    })


class ProductionPreparationTests(unittest.TestCase):
    def test_suggestion_reaches_target_with_rounded_counts(self):
        base = history(records(), 10, "SMT")
        item = {"source": "smt_process", "direction": "max", "target": 50000}
        suggestion = suggest_actions(base, 100, item)
        self.assertTrue(suggestion["achieved"])
        self.assertLessEqual(simulate(base, 100, suggestion["reductions"])["metrics"]["smt_process"]["counts"][1], 5)
        self.assertEqual(suggestion["allowed"], 5)

    def test_locked_mixed_defect_can_make_target_unreachable(self):
        base = history(records(), 10, "SMT")
        item = {"source": "smt_process", "direction": "max", "target": 50000}
        suggestion = suggest_actions(base, 100, item, {"Functional": 60}, locked=["Functional"])
        self.assertFalse(suggestion["achieved"])
        self.assertEqual(suggestion["reductions"]["Functional"], 0)
        self.assertEqual(suggestion["after"], 10)

    def test_percentage_target_and_unrelated_actions(self):
        base = history(records(), 10, "SMT")
        item = {"source": "smt_function", "direction": "min", "target": .9966}
        suggestion = suggest_actions(base, 100, item, {"Glue": 35})
        self.assertTrue(suggestion["achieved"])
        self.assertEqual(suggestion["allowed"], 0)
        self.assertEqual(suggestion["reductions"]["Functional"], 100)
        self.assertEqual(suggestion["reductions"]["Glue"], 35)
        with self.assertRaises(ValueError):
            suggest_actions(base, 100, {**item, "source": "smt_oqc"})

    def test_already_met_target_keeps_existing_actions(self):
        base = history(records(), 10, "SMT")
        item = {"source": "smt_function", "direction": "min", "target": .8}
        suggestion = suggest_actions(base, 100, item, {"Glue": 25})
        self.assertEqual(suggestion["reductions"], {"Glue": 25})
        self.assertTrue(suggestion["achieved"])

    def test_forecasts_are_ceilings_without_float_artifacts(self):
        self.assertEqual(rounded_forecast(21, 100, 1000), 3)
        self.assertEqual(rounded_forecast(5, 100, 100, 50), 3)
        self.assertEqual(rounded_forecast(30, 100, 100, 80), 6)
        self.assertEqual(rounded_forecast(5, 100, 100, 100), 0)

    def test_mixed_pcb_is_retained_until_all_issues_eliminated(self):
        base = history(records(), 10, "SMT")
        result = simulate(base, 100, {"Glue": 100})
        self.assertEqual(result["totals"], [20, 10])
        self.assertEqual(result["metrics"]["smt_function"]["counts"], [10, 10])
        self.assertEqual(simulate(base, 100, {"Glue": 100, "Functional": 100})["totals"], [20, 0])

    def test_partial_reductions_do_not_double_count_boards(self):
        result = simulate(history(records(), 10, "SMT"), 100, {"Glue": 50, "Functional": 50})
        self.assertEqual(result["totals"], [20, 13])  # mixed group ceil(7.5) + glue-only group 5
        self.assertEqual(result["metrics"]["smt_function"]["values"], [.9, .95])
        self.assertEqual(result["issues"]["With actions"].tolist(), [10, 5])

    def test_assembly_scopes_and_100_percent_reduction(self):
        result = simulate(history(records("Assembly"), 10, "Assembly"), 100, {"Functional": 100})
        self.assertEqual(result["metrics"]["assembly_function"]["values"], [.9, 1])
        self.assertEqual(result["metrics"]["assembly_appearance"]["counts"], [20, 20])
        self.assertEqual(result["metrics"]["assembly_mando"]["counts"], [10, 0])

    def test_invalid_input_and_counts_are_blocked(self):
        for count in [0, 1]:
            with self.assertRaises(ValueError): history(records(), count, "SMT")
        with self.assertRaises(ValueError): rounded_forecast(1, 1, 10, 101)
        with self.assertRaises(ValueError): simulate(history(records(), 10, "SMT"), 0, {})
        self.assertLessEqual(simulate(history(records(), 10, "SMT"), 1, {})["totals"][0], 1)

    def test_zero_defects_is_valid_with_input(self):
        result = simulate(history(records().iloc[:0], 10, "SMT"), 100, {})
        self.assertEqual(result["totals"], [0, 0])
        self.assertEqual(result["metrics"]["smt_function"]["values"], [1, 1])

    def test_streamlit_view_renders_both_areas(self):
        from streamlit.testing.v1 import AppTest
        script = '''
import pandas as pd
from datetime import datetime
from tools.production_preparation_ui import render
def load(area, start, end):
    records = pd.DataFrame({'Model':['MODEL','MODEL'], 'PCB':['A','B'],
        'FailureType': ['Functional Failure','Appearance Failure'] if area=='SMT' else ['Funcional','Aparência'],
        'IsFunctionMando':[True,False], 'IsSMTDuty':[False,False],
        'Phenomenon':['Functional','Appearance'], 'KPIDate':pd.to_datetime(['2026-10-01']*2)})
    inputs = pd.DataFrame({'Model':['MODEL'], 'Input':[100], 'Date':pd.to_datetime(['2026-10-01'])})
    return {'records':records,'inputs':inputs}
directory = [{'area':'SMT','source':'smt_process','direction':'max','kpi':'Process','target':5000},
             {'area':'Assembly','source':'assembly_function','direction':'min','kpi':'Function','target':.9905}]
render(load, directory)
'''
        app = AppTest.from_string(script).run(timeout=20)
        self.assertFalse(app.exception)
        self.assertTrue(any("#### Suggest actions to reach target" == entry.value for entry in app.markdown))
        app.button(key="production_suggest_button").click().run(timeout=20)
        self.assertFalse(app.exception)
        self.assertTrue(app.success)
        self.assertTrue(app.session_state["_production_actions"])
        app.selectbox(key="production_area").set_value("Assembly").run(timeout=20)
        self.assertFalse(app.exception)


if __name__ == "__main__": unittest.main()
