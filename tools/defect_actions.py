"""Persistent action cards and their audit history, separate from MES/KPI records."""
from datetime import date, datetime, timezone
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from threading import RLock
from uuid import uuid4
from zoneinfo import ZoneInfo

from tools.access_control import require_admin_access

STATUSES = ['Open', 'In progress', 'Pending verification', 'Closed']
AREAS = ['SMT', 'Assembly', 'IQC', 'Lab', 'Other']
PRIORITIES = ['High', 'Medium', 'Low']
FIELDS = ['title', 'area', 'model', 'defect', 'owner', 'priority', 'due_date', 'status',
          'root_cause', 'containment', 'countermeasure', 'evidence', 'verified']
_LOCK = RLock()


def can_delete_action(session, record):
    actor = str(session.get('authenticated_user', '')).strip()
    return bool(session.get('authenticated') is True and actor and record.get('id')
                and not record.get('deleted_at') and (
                    session.get('auth_role') in {'admin', 'manager'}
                    or str(record.get('created_by', '')).strip().casefold() == actor.casefold()))


def local_today():
    return datetime.now(ZoneInfo('America/Manaus')).date()


def overdue(record, today):
    return record['status'] != 'Closed' and date.fromisoformat(record['due_date']) < today


def filter_actions(records, today, area='All areas', owner='All owners', priority='All priorities',
                   deadline='Any deadline', search='', models=None, statuses=None, created_range=None):
    result = []
    for item in records:
        if area != 'All areas' and item['area'] != area: continue
        if owner != 'All owners' and item['owner'] != owner: continue
        if priority != 'All priorities' and item['priority'] != priority: continue
        if models and item['model'] not in models: continue
        if statuses is not None and item['status'] not in statuses: continue
        if search.strip().casefold() not in ' '.join(str(item.get(key, '')) for key in ['id', 'title', 'model', 'defect', 'owner', 'root_cause', 'countermeasure']).casefold(): continue
        delta = (date.fromisoformat(item['due_date']) - today).days
        if deadline == 'Overdue' and not overdue(item, today): continue
        if deadline == 'Next 7 days' and (item['status'] == 'Closed' or not 0 <= delta <= 7): continue
        if created_range:
            created = datetime.fromisoformat(item['created_at']).astimezone(ZoneInfo('America/Manaus')).date()
            if not created_range[0] <= created <= created_range[1]: continue
        result.append(item)
    return sorted(result, key=lambda item: (item['due_date'], item['created_at']))


def summary(records, today):
    closed = [r for r in records if r['status'] == 'Closed']
    on_time = sum(datetime.fromisoformat(r['closed_at']).astimezone(ZoneInfo('America/Manaus')).date()
                  <= date.fromisoformat(r['due_date']) for r in closed)
    return {'created': len(records), 'active': len(records) - len(closed), 'closed': len(closed),
            'overdue': sum(overdue(r, today) for r in records),
            'verification': sum(r['status'] == 'Pending verification' for r in records),
            'on_time_rate': on_time / len(closed) if closed else None,
            'closure_rate': len(closed) / len(records) if records else None}


class ActionSyncError(RuntimeError):
    """The database committed locally but its upload did not complete."""


class ActionStore:
    def __init__(self, database, prepare_write=lambda: None, persist=lambda: None, prepare_delete=None):
        self.database = Path(database)
        self.prepare_write = prepare_write
        self.persist = persist
        self.prepare_delete = prepare_delete or prepare_write
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS defect_action_cards (
                id TEXT PRIMARY KEY, revision TEXT NOT NULL, legacy_source TEXT UNIQUE,
                payload TEXT NOT NULL)''')
            conn.execute('''CREATE TABLE IF NOT EXISTS defect_action_history (
                revision TEXT PRIMARY KEY, action_id TEXT NOT NULL, actor TEXT NOT NULL,
                changed_at TEXT NOT NULL, payload TEXT NOT NULL)''')

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.database, timeout=30)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def all(self, include_deleted=False):
        with self.connect() as conn:
            records = [json.loads(row[0]) for row in conn.execute('SELECT payload FROM defect_action_cards')]
            return records if include_deleted else [row for row in records if not row.get('deleted_at')]

    def deleted(self):
        return sorted([row for row in self.all(include_deleted=True) if row.get('deleted_at')],
                      key=lambda row: row['deleted_at'], reverse=True)

    def get(self, action_id):
        with self.connect() as conn:
            row = conn.execute('SELECT payload FROM defect_action_cards WHERE id=?', (action_id,)).fetchone()
            record = json.loads(row[0]) if row else {}
            return {} if record.get('deleted_at') else record

    def history(self, action_id):
        with self.connect() as conn:
            return [json.loads(row[0]) for row in conn.execute(
                'SELECT payload FROM defect_action_history WHERE action_id=? ORDER BY changed_at DESC, rowid DESC', (action_id,))]

    def legacy(self):
        with self.connect() as conn:
            conn.row_factory = sqlite3.Row
            exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='smart_report_actions'").fetchone()
            if not exists: return []
            imported = {row[0] for row in conn.execute('SELECT legacy_source FROM defect_action_cards WHERE legacy_source IS NOT NULL')}
            rows = [dict(row) for row in conn.execute('SELECT * FROM smart_report_actions ORDER BY updated_at DESC')]
        for row in rows:
            # Preserve report period and original key, rather than merging unrelated actions.
            row['source_key'] = json.dumps([row['area'], row['period_key'], row['failure_type'], row['defect_name']])
            row['imported'] = row['source_key'] in imported
        return rows

    def save(self, session, values, action_id=None, expected_revision='', legacy_source=None):
        require_admin_access(session)
        actor = str(session.get('authenticated_user', '')).strip()
        if not actor: raise PermissionError('Sign in before saving an action.')
        clean = {key: str(values.get(key, '') or '').strip() for key in FIELDS if key != 'verified'}
        clean['verified'] = values.get('verified') is True
        for key, label in [('title', 'Action title'), ('owner', 'Owner'), ('due_date', 'Due date')]:
            if not clean[key]: raise ValueError(f'{label} is required.')
        if clean['area'] not in AREAS or clean['status'] not in STATUSES or clean['priority'] not in PRIORITIES:
            raise ValueError('Select a valid area, status and priority.')
        try: date.fromisoformat(clean['due_date'])
        except ValueError: raise ValueError('Select a valid due date.') from None
        if len(clean['title']) > 160 or len(clean['owner']) > 100 or any(len(v) > 10000 for v in clean.values() if isinstance(v, str)):
            raise ValueError('Use a shorter title, owner or description.')
        if clean['status'] == 'Closed' and not (clean['verified'] and clean['evidence'] and clean['countermeasure']):
            raise ValueError('To close the action, enter the countermeasure, record verification evidence and confirm effectiveness.')
        if clean['status'] != 'Closed': clean['verified'] = False
        self.prepare_write()
        with _LOCK, self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT payload FROM defect_action_cards WHERE id=?', (action_id,)).fetchone() if action_id else None
            current = json.loads(row[0]) if row else {}
            if action_id and not current: raise ValueError('This action no longer exists. Refresh the board.')
            if current.get('deleted_at'): raise ValueError('This action was deleted. Refresh the board.')
            if current.get('revision', '') != expected_revision:
                raise ValueError('Another update was saved after this card was opened. Close it, refresh the board and try again.')
            now = datetime.now(timezone.utc).isoformat(timespec='microseconds')
            identifier = action_id or 'ACT-' + uuid4().hex[:12].upper()
            record = {**clean, 'id': identifier, 'revision': uuid4().hex,
                      'created_at': current.get('created_at', now), 'created_by': current.get('created_by', actor),
                      'updated_at': now, 'updated_by': actor,
                      'closed_at': (current.get('closed_at') or now) if clean['status'] == 'Closed' else None,
                      'legacy_source': current.get('legacy_source') or legacy_source}
            raw = json.dumps(record, ensure_ascii=False)
            try:
                conn.execute('''INSERT INTO defect_action_cards (id, revision, legacy_source, payload) VALUES (?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET revision=excluded.revision, payload=excluded.payload''',
                    (identifier, record['revision'], record['legacy_source'], raw))
            except sqlite3.IntegrityError:
                raise ValueError('This previous report action was already converted into a card.') from None
            changes = {key: {'before': current.get(key), 'after': record[key]}
                       for key in FIELDS if current.get(key) != record[key]}
            event = {'revision': record['revision'], 'actor': actor, 'changed_at': now,
                     'event': 'Created' if not current else 'Updated', 'changes': changes}
            conn.execute('INSERT INTO defect_action_history VALUES (?,?,?,?,?)',
                         (record['revision'], identifier, actor, now, json.dumps(event, ensure_ascii=False)))
        try:
            self.persist()
        except Exception as exc:
            raise ActionSyncError('The action was saved locally, but cloud synchronization was not confirmed. Retry synchronization before leaving this page.') from exc
        return record

    def delete(self, session, action_id, expected_revision, *, confirmed=False):
        # Re-read the persisted creator; the browser's copy cannot grant permission.
        current = self.get(action_id)
        if not can_delete_action(session, current):
            raise PermissionError('Only the action creator, a manager or an administrator can delete this action.')
        if confirmed is not True:
            raise ValueError('Confirm that you want to delete this action.')
        self.prepare_delete()
        with _LOCK, self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT payload FROM defect_action_cards WHERE id=?', (action_id,)).fetchone()
            current = json.loads(row[0]) if row else {}
            if not can_delete_action(session, current):
                raise PermissionError('This action was deleted or you no longer have permission to delete it.')
            if not expected_revision or current.get('revision') != expected_revision:
                raise ValueError('Another update was saved after this card was opened. Close it, refresh the board and try again.')
            now = datetime.now(timezone.utc).isoformat(timespec='microseconds')
            actor = str(session['authenticated_user']).strip()
            record = {**current, 'revision': uuid4().hex, 'deleted_at': now, 'deleted_by': actor,
                      'updated_at': now, 'updated_by': actor}
            conn.execute('UPDATE defect_action_cards SET revision=?, legacy_source=NULL, payload=? WHERE id=?',
                         (record['revision'], json.dumps(record, ensure_ascii=False), action_id))
            event = {'revision': record['revision'], 'actor': actor, 'changed_at': now, 'event': 'Deleted',
                     'changes': {'deleted': {'before': False, 'after': True}}, 'snapshot': current}
            conn.execute('INSERT INTO defect_action_history VALUES (?,?,?,?,?)',
                         (record['revision'], action_id, actor, now, json.dumps(event, ensure_ascii=False)))
        try:
            self.persist()
        except Exception as exc:
            raise ActionSyncError('The action was removed locally, but cloud synchronization was not confirmed. Retry synchronization before leaving this page.') from exc
        return record
