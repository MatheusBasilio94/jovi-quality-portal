import tempfile
import unittest
from unittest.mock import patch

from tools.development_assessment import AssessmentStore, revision
from tools.portal_notifications import ReadState, collect


class NotificationTests(unittest.TestCase):
    def test_personal_and_manager_scopes_and_read_state(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AssessmentStore(directory, cloud=False)
            users = {'worker':{'username':'worker','display_name':'Worker','manager':'boss','active':True,'approved':True},
                     'other':{'username':'other','manager':'other-boss','active':True,'approved':True},
                     'pending':{'username':'pending','active':True,'approved':False,'created_at':'2026-10-14T10:00:00+00:00'}}
            payload = {'status':'submitted','manager':'boss','ratings':{'results':{'rating':3,'comment':'private analysis'}}}
            own = store.save('worker','worker','2026-10_SMT','self',payload)
            store.save('other','other','2026-10_SMT','self',{**payload,'manager':'other-boss'})
            inbox = collect('boss','manager',users,store)
            self.assertEqual(len(inbox),1)
            self.assertEqual(inbox[0]['subject'],'worker')
            self.assertNotIn('private analysis',str(inbox))
            self.assertEqual(collect('worker','viewer',users,store),[])
            self.assertEqual(len(collect('administrator','admin',users,store)),3)
            state = ReadState(store)
            state.mark('boss',[inbox[0]['id']])
            self.assertEqual(state.read('boss'),{inbox[0]['id']})
            self.assertEqual(state.read('other-boss'),set())
            review = store.save('boss','worker','2026-10_SMT','manager',{**payload,'self_revision':revision(own)})
            self.assertEqual(collect('boss','manager',users,store),[])
            personal = collect('worker','viewer',users,store)
            self.assertEqual(len(personal),1)
            first = personal[0]['id']
            self.assertEqual(collect('worker','viewer',users,store)[0]['id'],first)
            state.mark('worker',[first])
            store.save('boss','worker','2026-10_SMT','manager',{**payload,'self_revision':revision(own)},revision(review))
            second = collect('worker','viewer',users,store)[0]['id']
            self.assertNotEqual(first,second)
            self.assertNotIn(second,state.read('worker'))

    def test_draft_does_not_generate_assessment_notice(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AssessmentStore(directory, cloud=False)
            store.save('worker','worker','2026-10_SMT','self',{'status':'draft','manager':'boss','ratings':{}})
            users = {'worker':{'username':'worker','manager':'boss','active':True,'approved':True}}
            self.assertEqual(collect('boss','manager',users,store),[])

    def test_open_marks_read_and_targets_the_correct_assessment(self):
        from streamlit.testing.v1 import AppTest
        with tempfile.TemporaryDirectory() as directory:
            store = AssessmentStore(directory, cloud=False)
            users = {'worker':{'username':'worker','display_name':'Worker','manager':'boss','active':True,'approved':True}}
            store.save('worker','worker','2026-09_Assembly','self',{'status':'submitted','manager':'boss','ratings':{'results':{'rating':3,'comment':'Evidence'}}})
            notice = collect('boss','manager',users,store)[0]
            script = '''
import streamlit as st
from tools.portal_notifications import render
st.session_state['authenticated'] = True
st.session_state['authenticated_user'] = 'boss'
st.session_state['auth_role'] = 'manager'
def navigate(module, tab):
    st.session_state['destination_module'] = module
render(navigate)
'''
            with patch('tools.portal_notifications.AssessmentStore',return_value=store), patch('tools.portal_notifications.registry',return_value={'users':users}):
                app = AppTest.from_string(script).run(timeout=20)
                self.assertFalse(app.exception)
                app.button(key='notification_open_'+notice['id']).click().run(timeout=20)
                self.assertFalse(app.exception)
                self.assertEqual(app.session_state['destination_module'],'Development Hub')
                self.assertEqual(app.session_state['_development_notification']['cycle'],'2026-09_Assembly')
                self.assertEqual(app.session_state['_development_notification']['subject'],'worker')
                self.assertIn(notice['id'],ReadState(store).read('boss'))


if __name__=='__main__': unittest.main()
