from datetime import date
import unittest

import pandas as pd

from tools.quality_notifications import build_points, collect_kpi_signals, collect_recurrences

DAY = date(2026, 10, 13)
DIRECTORY = [
    {'source': 'smt_process', 'area': 'SMT', 'kpi': 'Process NG', 'target': 5000, 'direction': 'max'},
    {'source': 'smt_function', 'area': 'SMT', 'kpi': 'Functional Pass Rate', 'target': .9966, 'direction': 'min'},
]


class QualityNotificationTests(unittest.TestCase):
    def test_minimum_input_valid_zero_direction_and_stable_identity(self):
        points = [{'source': 'smt_process', 'model': 'M', 'day': f'2026-10-{d}', 'input': n, 'value': v}
                  for d, n, v in [(9, 100, 0), (10, 99, 90000), (11, 100, 1000), (12, 0, 0), (13, 100, 6000), (14, 100, 0)]]
        events = collect_kpi_signals(points, DIRECTORY, DAY)
        self.assertEqual({e['kind'] for e in events}, {'target', 'trend'})
        self.assertIn('09 Oct: 0 PPM', next(e for e in events if e['kind']=='trend')['message'])
        self.assertEqual(events, collect_kpi_signals(points, DIRECTORY, DAY))
        points[-2]['value'] = 5000
        self.assertEqual([e['kind'] for e in collect_kpi_signals(points, DIRECTORY, DAY)], ['trend'])

    def test_pass_rate_decreases_and_no_data_is_not_zero(self):
        points = [{'source': 'smt_function', 'model': 'All models', 'day': f'2026-10-{d}', 'input': 500, 'value': v}
                  for d, v in [(9, 1), (11, .998), (12, None), (13, .99)]]
        self.assertEqual({e['kind'] for e in collect_kpi_signals(points, DIRECTORY, DAY)}, {'target', 'trend'})
        for p in points:
            p['day'] = '2026-09-30'
        self.assertEqual(collect_kpi_signals(points, DIRECTORY, DAY), [])

    def test_recurrence_counts_unique_boards_and_calendar_window(self):
        records = pd.DataFrame([
            {'day': d, 'model': 'M', 'pcb': sn, 'defect': 'Damage', 'component': 'ItemCode: A'}
            for d, sn in [('2026-10-06', 'old'), ('2026-10-12', '1'), ('2026-10-13', '1'), ('2026-10-13', '2')]])
        self.assertEqual(collect_recurrences(records, 'Assembly', DAY), [])
        records.loc[len(records)] = ['2026-10-13', 'M', '3', 'Damage', 'ItemCode: A']
        events = collect_recurrences(records, 'Assembly', DAY)
        self.assertEqual(len(events), 4)  # General and model, defect and component.
        self.assertEqual({e['model'] for e in events}, {'All models', 'M'})
        self.assertTrue(all('3 distinct PCBs' in e['message'] for e in events))

    def test_smt_observed_daily_input_coverage_and_model_inspections(self):
        inputs = pd.DataFrame([
            {'Model': 'M', 'BeginDate': pd.Timestamp('2026-10-12'), 'EndDateExclusive': pd.Timestamp('2026-10-13'), 'Input': 200, 'Granularity': 'daily'},
            {'Model': 'M', 'BeginDate': pd.Timestamp('2026-10-13'), 'EndDateExclusive': pd.Timestamp('2026-10-14'), 'Input': 100, 'Granularity': 'daily'},
            {'Model': 'Coarse', 'BeginDate': pd.Timestamp('2026-10-13'), 'EndDateExclusive': pd.Timestamp('2026-10-20'), 'Input': 700, 'Granularity': 'weekly'}])
        defects = pd.DataFrame([{'Model': 'M', 'KPIDate': pd.Timestamp('2026-10-13'), 'PCB': '1',
            'FailureType': 'Functional Failure', 'IsRejudgeOK': False, 'Phenomenon': 'Failure'}])
        smt = {'selected_input': inputs, 'covered_raw': defects,
               'source_defect_start': pd.Timestamp('2026-10-13'), 'source_defect_end': pd.Timestamp('2026-10-13')}
        inspections = pd.DataFrame([{'Model': 'M', 'InspectionDate': pd.Timestamp('2026-10-13'), 'Inspected': 10, 'OK': 9}])
        points, _ = build_points(smt, None, {'SMT': inspections}, DAY)
        process = [p for p in points if p['source']=='smt_process']
        self.assertEqual(len(process), 1)
        self.assertEqual(process[0]['model'], 'M')  # General excludes incomplete/coarse daily denominator.
        self.assertEqual(process[0]['value'], 10000)
        inspection = next(p for p in points if p['source']=='smt_oqc' and p['model']=='M')
        self.assertEqual(inspection['input'], 100)
        self.assertEqual(inspection['value'], .9)

    def test_assembly_points_match_validated_engine_and_duty_uses_assembly_input(self):
        from tools.assembly_kpi_v2 import calculate_from_prepared
        inputs = pd.DataFrame([{'Date': pd.Timestamp('2026-10-13'), 'Model': 'M', 'Input': 100}])
        defects = pd.DataFrame([{'DefectDate': pd.Timestamp('2026-10-13'), 'Model': 'M', 'PCBNormalized': '1',
            'FailureType': 'Funcional', 'IsFunctionMando': False, 'IsSMTDuty': True,
            'ResponsibilityPending': False, 'Phenomenon': 'Damage'}])
        assembly = calculate_from_prepared(inputs, defects, DAY, DAY)
        points, _ = build_points(None, assembly, {}, DAY)
        values = {p['source']: p for p in points if p['model']=='M'}
        self.assertEqual(values['assembly_function']['value'], .99)
        self.assertEqual(values['assembly_mando']['value'], 0)
        self.assertEqual(values['smt_assembly_duty']['value'], 10000)
        self.assertEqual(values['smt_assembly_duty']['input'], 100)

    def test_common_user_sees_quality_alert_and_open_preserves_assessment_privacy(self):
        import tempfile
        from unittest.mock import patch
        from streamlit.testing.v1 import AppTest
        from tools.development_assessment import AssessmentStore
        from tools.portal_notifications import ReadState
        with tempfile.TemporaryDirectory() as folder:
            store = AssessmentStore(folder, cloud=False)
            notice = collect_kpi_signals([{'source': 'smt_process', 'model': 'M', 'day': DAY,
                                         'input': 100, 'value': 10000}], DIRECTORY, DAY)[0]
            script = '''
import streamlit as st
from tools.portal_notifications import render
st.session_state['authenticated'] = True
st.session_state['authenticated_user'] = 'jovi'
st.session_state['auth_role'] = 'viewer'
def navigate(module, tab):
    st.session_state['destination_module'] = module
    st.session_state['destination_tab'] = tab
def quality(refresh=False):
    return st.session_state['test_notices'], []
render(navigate, quality)
'''
            with patch('tools.portal_notifications.AssessmentStore', return_value=store), patch('tools.portal_notifications.development_access', return_value=False):
                app = AppTest.from_string(script)
                app.session_state['test_notices'] = [notice]
                app.run(timeout=20)
                self.assertFalse(app.exception)
                app.button(key='notification_open_'+notice['id']).click().run(timeout=20)
                self.assertFalse(app.exception)
                self.assertEqual(app.session_state['destination_module'], 'SMT')
                self.assertEqual(app.session_state['destination_tab'], 'KPI Track')
                self.assertIn(notice['id'], ReadState(store).read('jovi'))


if __name__ == '__main__':
    unittest.main()
