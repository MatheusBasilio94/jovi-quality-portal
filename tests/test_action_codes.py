from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.defect_actions import ActionStore, filter_actions, local_today
from tests.test_defect_actions import ADMIN, VIEWER, payload


def clock(value):
    fixed = datetime.fromisoformat(value)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None)
    return patch('tools.defect_actions.datetime', Clock)


class ActionCodeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'cards.db'
        self.store = ActionStore(self.path)

    def test_sequences_are_per_area_and_month_and_never_reused(self):
        with clock('2026-10-16T15:00:00+00:00'):
            first = self.store.save(ADMIN, payload(code='FORGED'))
            second = self.store.save(ADMIN, payload())
            self.assertEqual([first['code'],second['code']], ['SMT-001/1026','SMT-002/1026'])
            for area,prefix in [('Assembly','ASSY'),('IQC','IQC'),('Lab','LAB'),('Other','OTH')]:
                row = self.store.save(ADMIN,{**payload(),'area':area})
                self.assertEqual(row['code'], f'{prefix}-001/1026')
            self.store.delete(ADMIN,second['id'],second['revision'],confirmed=True)
            self.assertEqual(self.store.save(ADMIN,payload())['code'],'SMT-003/1026')
        with clock('2026-11-01T15:00:00+00:00'):
            self.assertEqual(self.store.save(ADMIN,payload())['code'],'SMT-001/1126')
        with clock('2027-01-01T15:00:00+00:00'):
            self.assertEqual(self.store.save(ADMIN,payload())['code'],'SMT-001/0127')

    def test_code_stays_fixed_on_edits_moves_and_area_changes(self):
        with clock('2026-10-16T15:00:00+00:00'):
            first = self.store.save(ADMIN,payload())
        with clock('2026-11-16T15:00:00+00:00'):
            edited = self.store.save(ADMIN,{**first,'code':'FORGED','area':'Assembly','title':'Edited'},first['id'],first['revision'])
            moved = self.store.move(VIEWER,edited['id'],'In progress',edited['revision'])
            self.assertEqual(moved['code'],'SMT-001/1026')
            self.assertEqual(moved['id'],first['id'])
            self.assertEqual(ActionStore(self.path).get(first['id'])['code'],first['code'])
            self.assertEqual(filter_actions([moved],local_today(),search='SMT-001/1026'),[moved])

    def test_period_uses_creation_time_in_manaus_not_due_date_or_utc_month(self):
        with clock('2026-10-01T02:00:00+00:00'):
            record = self.store.save(ADMIN,payload())
            self.assertEqual(record['code'],'SMT-001/0926')

    def test_backfill_keeps_internal_ids_revisions_history_and_deleted_reservations(self):
        one = self.store.save(ADMIN,payload())
        two = self.store.save(ADMIN,payload())
        deleted = self.store.delete(ADMIN,two['id'],two['revision'],confirmed=True)
        history = self.store.history(one['id'])
        with self.store.connect() as conn:
            conn.execute('DELETE FROM defect_action_codes')
            for record,created in [(one,'2026-10-02T10:00:00+00:00'),(deleted,'2026-10-01T10:00:00+00:00')]:
                old = {key:value for key,value in record.items() if key!='code'}
                old['created_at'] = created
                conn.execute('UPDATE defect_action_cards SET payload=? WHERE id=?',(json.dumps(old),old['id']))
        migrated = ActionStore(self.path)
        self.assertEqual(migrated.get(one['id'])['code'],'SMT-002/1026')
        self.assertEqual(migrated.get(one['id'])['revision'],one['revision'])
        self.assertEqual(migrated.history(one['id']),history)
        self.assertEqual(migrated.deleted()[0]['code'],'SMT-001/1026')
        with clock('2026-10-16T15:00:00+00:00'):
            self.assertEqual(migrated.save(ADMIN,payload())['code'],'SMT-003/1026')
        self.assertEqual(ActionStore(self.path).get(one['id'])['code'],'SMT-002/1026')

    def test_simultaneous_creations_get_unique_sequential_codes(self):
        def create(_):
            return ActionStore(self.path).save(ADMIN,payload())['code']
        with clock('2026-10-16T15:00:00+00:00'), ThreadPoolExecutor(max_workers=4) as pool:
            codes = list(pool.map(create,range(12)))
        self.assertEqual(sorted(codes),[f'SMT-{n:03d}/1026' for n in range(1,13)])

    def test_failed_creation_does_not_consume_a_sequence(self):
        with clock('2026-10-16T15:00:00+00:00'):
            self.store.save(ADMIN,payload(),legacy_source='report')
            with self.assertRaises(ValueError):
                self.store.save(ADMIN,payload(),legacy_source='report')
            self.assertEqual(self.store.save(ADMIN,payload())['code'],'SMT-002/1026')


if __name__=='__main__': unittest.main()
