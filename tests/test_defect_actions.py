from datetime import date
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools.defect_actions import ActionStore, ActionSyncError, filter_actions, summary

ADMIN = {'authenticated': True, 'auth_role': 'admin', 'authenticated_user': 'admin'}
VIEWER = {'authenticated': True, 'auth_role': 'viewer', 'authenticated_user': 'jovi'}


def payload(**overrides):
    return dict(title='Reduce glue defects', owner='Felipe', area='SMT', model='M', defect='Disperse glue',
                priority='High', due_date='2026-10-14', status='Open', countermeasure='', **overrides)


class ActionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'actions.db'
        self.persist = Mock()
        self.store = ActionStore(self.path, persist=self.persist)

    def test_persistence_updates_history_and_stale_edit(self):
        initial = self.store.save(ADMIN, payload())
        reopened_store = ActionStore(self.path)
        self.assertEqual(reopened_store.get(initial['id']), initial)
        updated = self.store.save(ADMIN, {**initial, 'status': 'In progress', 'countermeasure': 'Adjust parameters'}, initial['id'], initial['revision'])
        self.assertEqual(updated['created_at'], initial['created_at'])
        self.assertEqual(len(self.store.all()), 1)
        self.assertEqual(len(self.store.history(initial['id'])), 2)
        self.assertEqual(self.store.history(initial['id'])[0]['changes']['status'], {'before':'Open','after':'In progress'})
        with self.assertRaisesRegex(ValueError, 'Another update'):
            self.store.save(ADMIN, initial, initial['id'], initial['revision'])
        self.assertEqual(self.persist.call_count, 2)

    def test_permissions_validation_and_verified_closure(self):
        for session in [VIEWER, {**ADMIN, 'authenticated':False}, {**ADMIN, 'authenticated_user':''}]:
            with self.assertRaises(PermissionError): self.store.save(session, payload())
        for change in [{'owner':''}, {'due_date':'wrong'}, {'status':'Unknown'}, {'status':'Closed'}]:
            with self.assertRaises(ValueError): self.store.save(ADMIN, {**payload(), **change})
        self.assertEqual(self.store.all(), [])
        closed = self.store.save(ADMIN, {**payload(), 'status':'Closed', 'verified':True, 'countermeasure':'Adjusted', 'evidence':'Passed 300 PCBs'})
        self.assertTrue(closed['closed_at'])
        reopened = self.store.save(ADMIN, {**closed, 'status':'In progress'}, closed['id'], closed['revision'])
        self.assertIsNone(reopened['closed_at'])
        self.assertFalse(reopened['verified'])
        stats = summary([reopened], date(2026,10,15))
        self.assertEqual((stats['active'], stats['closed'], stats['overdue']), (1, 0, 1))

    def test_filters_and_counts_do_not_treat_closed_as_overdue(self):
        a = self.store.save(ADMIN, payload())
        b = self.store.save(ADMIN, {**payload(), 'owner':'Key', 'area':'Assembly', 'due_date':'2026-10-20'})
        c = self.store.save(ADMIN, {**payload(), 'status':'Closed', 'verified':True, 'countermeasure':'Adjusted', 'evidence':'Validated'})
        records = [a,b,c]
        today = date(2026,10,15)
        self.assertEqual(summary(records,today)['overdue'], 1)
        self.assertEqual(filter_actions(records,today,deadline='Overdue'), [a])
        self.assertEqual(filter_actions(records,today,deadline='Next 7 days'), [b])
        self.assertEqual(filter_actions(records,today,owner='Key',area='Assembly',search='glue'), [b])
        self.assertEqual(filter_actions(records,today,statuses=[]), [])

    def test_previous_report_conversion_is_unique_and_original_is_preserved(self):
        with self.store.connect() as conn:
            conn.execute('CREATE TABLE smart_report_actions (id INTEGER, area TEXT, period_key TEXT, defect_name TEXT, failure_type TEXT, updated_at TEXT)')
            conn.execute("INSERT INTO smart_report_actions VALUES (1,'SMT','WK41','Glue','Appearance','2026-10-10')")
        legacy = self.store.legacy()[0]
        self.store.save(ADMIN, payload(), legacy_source=legacy['source_key'])
        with self.assertRaisesRegex(ValueError, 'already converted'):
            self.store.save(ADMIN, payload(), legacy_source=legacy['source_key'])
        self.assertTrue(self.store.legacy()[0]['imported'])
        with self.store.connect() as conn:
            self.assertEqual(conn.execute('SELECT defect_name FROM smart_report_actions').fetchone()[0], 'Glue')

    def test_sync_failure_is_reported_without_losing_local_record(self):
        self.persist.side_effect = RuntimeError('Unavailable')
        with self.assertRaises(ActionSyncError): self.store.save(ADMIN, payload())
        self.assertEqual(len(self.store.all()), 1)

    def test_ui_filters_and_viewer_read_only_access(self):
        from streamlit.testing.v1 import AppTest
        record = self.store.save(ADMIN, payload())
        script = """
import streamlit as st
from tools.defect_actions import ActionStore
from tools.defect_actions_ui import render
store = ActionStore(st.session_state['database'])
render(store)
"""
        app = AppTest.from_string(script)
        app.session_state['database'] = str(self.path)
        for key,value in VIEWER.items(): app.session_state[key] = value
        with patch('tools.defect_actions_ui.local_today', return_value=date(2026,10,15)):
            app.run(timeout=20)
            self.assertFalse(app.exception)
            self.assertTrue(app.button(key='defect_new_action').disabled)
            app.selectbox(key='defect_filter_area').select('Assembly').run(timeout=20)
            self.assertFalse(app.exception)
            self.assertTrue(any('No actions match' in x.value for x in app.info))
            app.selectbox(key='defect_filter_area').select('All areas').run(timeout=20)
            app.button(key='defect_open_'+record['id']).click().run(timeout=20)
            self.assertFalse(app.exception)
            self.assertTrue(next(x for x in app.button if x.label=='Save action').disabled)


if __name__ == '__main__': unittest.main()
