from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import portal_users as users
from tools.development_assessment import AssessmentStore, comparable_manager, revision
from tools.auth_session import issue_token, verify_token


class PersonalAccountTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cloud = patch('tools.supabase_store.supabase_is_configured', return_value=False)
        self.local = patch.object(users, 'LOCAL', Path(self.temp.name) / 'accounts.json')
        self.cloud.start()
        self.local.start()
        users.registry.clear()
        self.admin = {'authenticated': True, 'auth_role': 'admin', 'authenticated_user': 'admin'}

    def tearDown(self):
        users.registry.clear()
        self.local.stop()
        self.cloud.stop()
        self.temp.cleanup()

    def test_enrollment_starts_pending_and_requires_password_change(self):
        users.enroll('12345')
        user = users.profile('12345')
        self.assertEqual(user['role'], 'viewer')
        self.assertFalse(user['approved'])
        self.assertTrue(user['must_change_password'])
        self.assertTrue(users.password_matches('12345', user['password_hash']))
        self.assertNotIn('12345', user['password_hash'])
        with self.assertRaises(ValueError): users.enroll('12345')
        with self.assertRaises(ValueError): users.enroll('../../escape')

    def test_only_admin_can_approve_or_reset(self):
        users.enroll('12345')
        common = {'authenticated': True, 'auth_role': 'viewer'}
        with self.assertRaises(PermissionError): users.configure_user(common, '12345', 'admin', True, '')
        with self.assertRaises(PermissionError): users.reset_password(common, '12345')
        users.configure_user(self.admin, '12345', 'viewer', True, 'admin')
        self.assertTrue(users.profile('12345')['approved'])

    def test_password_change_and_reset_invalidate_old_tokens(self):
        users.enroll('12345')
        initial = users.profile('12345')
        token = issue_token('12345', initial['password_hash'])
        updated = users.change_password('12345', '12345', 'new-test-password', 'Test Person')
        self.assertFalse(updated['must_change_password'])
        self.assertFalse(verify_token(token, '12345', updated['password_hash']))
        self.assertFalse(users.password_matches('12345', updated['password_hash']))
        token = issue_token('12345', updated['password_hash'])
        users.reset_password(self.admin, '12345')
        reset = users.profile('12345')
        self.assertTrue(reset['must_change_password'])
        self.assertFalse(verify_token(token, '12345', reset['password_hash']))

    def test_invalid_or_wrong_password_cannot_change_credentials(self):
        users.enroll('12345')
        with self.assertRaises(ValueError): users.change_password('12345', 'wrong', 'long-new-password', 'Person')
        with self.assertRaises(ValueError): users.change_password('12345', '12345', '12345', 'Person')

    def test_first_access_and_pending_accounts_cannot_reach_portal(self):
        from streamlit.testing.v1 import AppTest
        users.enroll('12345')
        script = '''
import streamlit as st
from tools.portal_users import first_access, profile
from tools.access_control import Account
from tools.auth_session import issue_token
user = profile('12345')
account = Account('12345', user['password_hash'], user['role'])
first_access(account, issue_token, lambda: None)
st.write('PORTAL_REACHED')
'''
        app = AppTest.from_string(script).run()
        self.assertFalse(app.exception)
        self.assertTrue(any('Set your password' in item.value for item in app.subheader))
        self.assertFalse(any('PORTAL_REACHED' in item.value for item in app.markdown))
        users.change_password('12345', '12345', 'new-test-password', 'Test Person')
        app.run()
        self.assertTrue(any('awaiting administrator approval' in item.value for item in app.info))
        self.assertFalse(any('PORTAL_REACHED' in item.value for item in app.markdown))
        users.configure_user(self.admin, '12345', 'viewer', True, 'admin')
        app.run()
        self.assertFalse(app.exception)
        self.assertTrue(any('PORTAL_REACHED' in item.value for item in app.markdown))

    def test_dynamic_account_roles_and_deactivation(self):
        from tools.access_control import configured_accounts, authenticate
        users.enroll('12345')
        account = authenticate('12345', '12345', configured_accounts())
        self.assertEqual(account.role, 'viewer')
        users.configure_user(self.admin, '12345', 'manager', True, '')
        self.assertEqual(authenticate('12345', '12345', configured_accounts()).role, 'manager')
        users.configure_user(self.admin, '12345', 'manager', True, '', active=False)
        self.assertIsNone(authenticate('12345', '12345', configured_accounts()))

    def test_portal_restore_rechecks_reset_and_role_changes(self):
        import ast
        from types import SimpleNamespace
        from tools.access_control import configured_accounts, account_from_token
        source = (Path(__file__).resolve().parents[1] / 'app.py').read_text(encoding='utf-8')
        node = next(node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == 'restore_authentication')
        code = compile(ast.Module(body=[node], type_ignores=[]), '<portal-restore>', 'exec')
        users.enroll('12345')
        users.configure_user(self.admin, '12345', 'viewer', True, '')
        token = issue_token('12345', users.profile('12345')['password_hash'])
        state = {'authenticated': True, 'authenticated_user': '12345', 'auth_role': 'viewer', 'auth_cookie_token': token}
        namespace = {'st': SimpleNamespace(session_state=state, context=SimpleNamespace(cookies={})),
                     'PORTAL_ACCOUNTS': configured_accounts(), 'account_from_token': account_from_token, 'COOKIE_NAME': 'cookie'}
        exec(code, namespace)
        users.configure_user(self.admin, '12345', 'manager', True, '')
        namespace['PORTAL_ACCOUNTS'] = configured_accounts()
        namespace['restore_authentication']()
        self.assertEqual(state['auth_role'], 'manager')
        users.reset_password(self.admin, '12345')
        namespace['PORTAL_ACCOUNTS'] = configured_accounts()
        namespace['restore_authentication']()
        self.assertFalse(state['authenticated'])

    def test_assigned_manager_ui_shows_review_and_employee_cannot_self_review(self):
        from streamlit.testing.v1 import AppTest
        users.enroll('12345')
        users.configure_user(self.admin, '12345', 'viewer', True, 'boss')
        store = AssessmentStore(self.temp.name, cloud=False)
        from tools.development_assessment import AXES
        store.save('12345', '12345', '2026-10_SMT', 'self', {'status':'submitted','manager':'boss',
            'ratings':{key:{'rating':3,'comment':'Recorded evidence'} for key,_,_ in AXES}})
        script = '''
import streamlit as st
from tools.development_hub import documents
from tools.development_assessment_ui import render
st.session_state.setdefault('authenticated', True)
st.session_state.setdefault('authenticated_user', 'boss')
st.session_state.setdefault('auth_role', 'manager')
render(documents())
'''
        with patch('tools.development_assessment_ui.AssessmentStore', return_value=store):
            app = AppTest.from_string(script).run(timeout=20)
            app.selectbox(key='development_subject').set_value('12345').run(timeout=20)
            self.assertFalse(app.exception)
            review_button = next(button for button in app.button if button.label == 'Complete manager assessment')
            self.assertFalse(review_button.disabled)
            app.session_state['authenticated_user'] = '12345'
            app.session_state['auth_role'] = 'viewer'
            app.run(timeout=20)
            self.assertFalse(app.exception)
            review_button = next(button for button in app.button if button.label == 'Complete manager assessment')
            self.assertTrue(review_button.disabled)


class AssessmentRulesTests(unittest.TestCase):
    def test_administrator_reviews_any_other_employee_but_not_self(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AssessmentStore(directory, cloud=False)
            cycle = '2026-10_SMT'
            payload = {'status':'submitted','manager':'boss','ratings':{'results':{'rating':3,'comment':'Evidence'}}}
            own = store.save('person','person',cycle,'self',payload)
            admin = {'authenticated':True,'auth_role':'admin','authenticated_user':'admin'}
            review = store.save('admin','person',cycle,'manager',{**payload,'self_revision':revision(own)},session=admin)
            self.assertTrue(comparable_manager(own,review))
            store.save('admin','admin',cycle,'self',payload)
            with self.assertRaises(PermissionError):
                store.save('admin','admin',cycle,'manager',payload,session=admin)
            with self.assertRaises(PermissionError):
                store.save('intruder','person',cycle,'manager',payload,session=admin)

    def test_independent_reviews_and_access_control(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AssessmentStore(directory, cloud=False)
            cycle = '2026-10_SMT'
            payload = {'status': 'submitted', 'manager': 'boss', 'ratings': {'results': {'rating': 3, 'comment': 'Result evidence'}}}
            own = store.save('person', 'person', cycle, 'self', payload)
            with self.assertRaises(PermissionError): store.save('intruder', 'person', cycle, 'self', payload)
            with self.assertRaises(PermissionError): store.save('person', 'person', cycle, 'manager', payload)
            with self.assertRaises(PermissionError): store.save('other', 'person', cycle, 'manager', payload)
            review = store.save('boss', 'person', cycle, 'manager', {**payload, 'self_revision': revision(own)})
            self.assertTrue(comparable_manager(own, review))
            new = store.save('person', 'person', cycle, 'self', payload, revision(own))
            self.assertFalse(comparable_manager(new, review))
            with self.assertRaises(ValueError): store.save('person', 'person', cycle, 'self', payload, revision(own))

    def test_missing_evidence_and_invalid_ratings_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AssessmentStore(directory, cloud=False)
            for rating in [0, 6, 2.5, True]:
                with self.assertRaises(ValueError):
                    store.save('person', 'person', '2026-10_SMT', 'self', {'status': 'draft', 'ratings': {'results': {'rating': rating}}})
            with self.assertRaises(ValueError):
                store.save('person', 'person', '2026-10_SMT', 'self', {'status': 'submitted', 'ratings': {'results': {'rating': 3}}})


if __name__ == '__main__': unittest.main()
