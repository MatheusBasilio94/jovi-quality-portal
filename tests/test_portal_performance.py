"""Workload regressions: hidden pages and cached notification reads."""
import ast
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.development_assessment import AssessmentStore
from tools.portal_notifications import ReadState, _read_state


ROOT = Path(__file__).resolve().parents[1]


def app_functions(*names):
    tree = ast.parse((ROOT/'app.py').read_text(encoding='utf-8-sig'))
    return '\n\n'.join(ast.unparse(node) for node in tree.body
                        if isinstance(node, ast.FunctionDef) and node.name in names)


class PerformanceTests(unittest.TestCase):
    def test_only_active_smart_report_page_executes(self):
        from streamlit.testing.v1 import AppTest
        names = ['Weekly KPI Review', 'Monthly KPI Review', 'Defect Action Report', 'Production Preparation']
        script = '''
import streamlit as st
def page(name):
    st.session_state['rendered'] = st.session_state.get('rendered', []) + [name]
    st.write(name)
weekly_kpi_review_page = lambda: page('Weekly KPI Review')
monthly_kpi_review_page = lambda: page('Monthly KPI Review')
defect_action_report_page = lambda: page('Defect Action Report')
_production_preparation_renderer = lambda release: lambda *args: page('Production Preparation')
production_preparation_sources = None
configured_kpi_directory = lambda: ()
APP_VERSION = 'test'
'''+app_functions('remember_smart_report_section', 'smart_report_page')+'\nsmart_report_page()'
        for name in names:
            with self.subTest(name=name):
                app = AppTest.from_string(script)
                app.session_state['_smart_report_section'] = name
                app.session_state['smart_report_section'] = name
                app.run(timeout=20)
                self.assertFalse(app.exception)
                self.assertEqual(app.session_state['rendered'], [name])

    def test_read_display_cache_is_private_and_mark_merges_durable_state(self):
        _read_state.clear()
        self.addCleanup(_read_state.clear)
        with tempfile.TemporaryDirectory() as root:
            store = AssessmentStore(root, cloud=True)
            state = ReadState(store)
            durable = {'read': ['first']}
            with patch('tools.supabase_store.download_bytes', side_effect=lambda _: json.dumps(durable).encode()) as get, \
                 patch('tools.supabase_store.upload_bytes') as put:
                self.assertEqual(state.read('person'), {'first'})
                self.assertEqual(state.read('person'), {'first'})
                self.assertEqual(get.call_count, 1)
                # Simulate another session marking an item after our cached read.
                durable['read'].append('other-session')
                state.mark('person', ['new'])
                saved = json.loads(put.call_args.args[1])
                self.assertEqual(set(saved['read']), {'first','other-session','new'})
                durable.update(saved)
                self.assertEqual(state.read('person'), set(saved['read']))
                self.assertEqual(get.call_count, 3)
                state.read('other-person')
                self.assertEqual(get.call_count, 4)

    def test_local_quality_alert_cache_key_changes_with_source_revision(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)/'source.csv'
            path.write_text('Input\n100\n')
            calls = []
            ns = dict(DATA_STORE_DIR=Path(root), APP_VERSION='test', cloud_store_is_active=lambda: False,
                      quality_notification_events=lambda *args: calls.append(args))
            exec(compile(app_functions('load_quality_notifications'), 'load-alerts', 'exec'), ns)
            ns['load_quality_notifications']()
            path.write_text('Input\n200\n300\n')
            ns['load_quality_notifications']()
            self.assertNotEqual(calls[0][2], calls[1][2])
            ns['cloud_store_is_active'] = lambda: True
            ns['ensure_cloud_data_version'] = lambda: 'new-cloud-revision'
            ns['load_quality_notifications']()
            self.assertEqual(calls[-1][2], 'new-cloud-revision')


if __name__ == '__main__': unittest.main()
