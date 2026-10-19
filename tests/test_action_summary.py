import base64
from datetime import date
import re
import unittest

from tools.action_summary import build_action_summary, copy_summary_html


class ActionSummaryTests(unittest.TestCase):
    def record(self, **changes):
        return {**dict(id='ACT-ABC123', code='SMT-001/1026', title='Adjust glue dispensing parameters', area='SMT', model='PD2607LF_BR',
            owner='Felipe', status='In progress', priority='High', due_date='2026-10-15',
            defect='Disperse glue', root_cause='Under investigation', containment='Inspect affected boards',
            countermeasure='Adjust parameters and validate the next batch', verified=False, evidence=''), **changes}

    def test_open_summary_has_approved_content_br_date_and_overdue(self):
        text = build_action_summary(self.record(), date(2026,10,16))
        for expected in ['📋 *QUALITY ACTION*', '*Code:* SMT-001/1026', '*Owner:* Felipe', '*Due date:* 15/10/26',
                         '🔴 *Overdue:* 1 day', 'Disperse glue', 'Inspect affected boards',
                         'Adjust parameters and validate the next batch', 'Pending —']:
            self.assertIn(expected, text)
        self.assertNotIn('ACT-ABC123', text)
        self.assertNotIn('please update', text)

    def test_closed_summary_uses_verification_and_never_requests_progress(self):
        record = self.record(status='Closed', verified=True, closed_at='2026-10-16T01:30:45+00:00', evidence='300 PCBs validated')
        text = build_action_summary(record, date(2026,10,16))
        self.assertIn('Verified — closed on 15/10/26.', text)
        self.assertIn('300 PCBs validated', text)
        self.assertNotIn('Overdue', text)
        self.assertNotIn('please update', text)

    def test_blank_optional_fields_are_pending_and_due_today_is_not_overdue(self):
        text = build_action_summary(self.record(model='', defect=None, root_cause='  ', containment='', countermeasure='\n', evidence=None), date(2026,10,15))
        for expected in ['*Model:* Pending', '*Related defect*\nPending', '*Problem / root cause*\nPending',
                         '*Containment*\nPending', '*Countermeasure*\nPending', '*Evidence:* Pending']:
            self.assertIn(expected, text)
        self.assertIn('*Due date:* 15/10/26', text)
        self.assertNotIn('Overdue', text)

    def test_missing_fields_and_due_date_are_pending(self):
        text = build_action_summary({'id': 'ACT-ABC123'}, date(2026,10,16))
        for label in ['Action', 'Area', 'Model', 'Owner', 'Priority', 'Status', 'Due date', 'Evidence']:
            self.assertIn(f'*{label}:* Pending', text)
        self.assertNotIn('Overdue', text)

    def test_payload_preserves_unicode_but_cannot_inject_html(self):
        record = self.record(title='Cola — conexão </script><img src=x onerror=alert(1)>')
        html = copy_summary_html(record, date(2026,10,16))
        self.assertNotIn('</script>', html)
        self.assertNotIn('<img', html)
        encoded = re.search(r'data-action-summary="([^"]*)"', html).group(1)
        self.assertEqual(base64.b64decode(encoded).decode('utf-8'), build_action_summary(record, date(2026,10,16)))
        self.assertIn('Copy Summary', html)
        self.assertNotIn(' disabled', html)
        self.assertIn(' disabled', copy_summary_html({}))


if __name__=='__main__': unittest.main()
