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

STATUSES = ['Open', 'In progress', 'Pending verification', 'Closed', 'Notification']
AREAS = ['SMT', 'Assembly', 'IQC', 'Lab', 'Other']
AREA_CODES = {'SMT': 'SMT', 'Assembly': 'ASSY', 'IQC': 'IQC', 'Lab': 'LAB', 'Other': 'OTH'}
PRIORITIES = ['High', 'Medium', 'Low']
FIELDS = ['title', 'area', 'model', 'defect', 'owner', 'priority', 'due_date', 'status',
          'root_cause', 'containment', 'countermeasure', 'evidence', 'verified']
_LOCK = RLock()


def action_code(record):
    return str(record.get('code') or record.get('id') or '')


def _creation_time(value):
    timestamp = datetime.fromisoformat(value)
    return timestamp.replace(tzinfo=ZoneInfo('America/Manaus')) if timestamp.tzinfo is None else timestamp


def can_move_action(session):
    actor = session.get('authenticated_user')
    return session.get('authenticated') is True and isinstance(actor, str) and bool(actor.strip())


def can_delete_action(session, record):
    actor = str(session.get('authenticated_user', '')).strip()
    return bool(session.get('authenticated') is True and actor and record.get('id')
                and not record.get('deleted_at') and (
                    session.get('auth_role') in {'admin', 'manager'}
                    or str(record.get('created_by', '')).strip().casefold() == actor.casefold()))


def local_today():
    return datetime.now(ZoneInfo('America/Manaus')).date()


def overdue(record, today):
    return bool(record['status'] not in {'Closed', 'Notification'} and record.get('due_date')
                and date.fromisoformat(record['due_date']) < today)


def filter_actions(records, today, area='All areas', owner='All owners', priority='All priorities',
                   deadline='Any deadline', search='', models=None, statuses=None, created_range=None):
    result = []
    for item in records:
        if area != 'All areas' and item['area'] != area: continue
        if owner != 'All owners' and item['owner'] != owner: continue
        if priority != 'All priorities' and item['priority'] != priority: continue
        if models and item['model'] not in models: continue
        if statuses is not None and item['status'] not in statuses: continue
        if search.strip().casefold() not in ' '.join(str(item.get(key, '')) for key in ['code', 'id', 'title', 'model', 'defect', 'owner', 'root_cause', 'countermeasure']).casefold(): continue
        delta = (date.fromisoformat(item['due_date']) - today).days if item.get('due_date') else None
        if deadline == 'Overdue' and not overdue(item, today): continue
        if deadline == 'Next 7 days' and (item['status'] in {'Closed', 'Notification'} or delta is None or not 0 <= delta <= 7): continue
        if created_range:
            created = datetime.fromisoformat(item['created_at']).astimezone(ZoneInfo('America/Manaus')).date()
            if not created_range[0] <= created <= created_range[1]: continue
        result.append(item)
    return sorted(result, key=lambda item: (item.get('due_date') or '9999-12-31', item['created_at']))


def summary(records, today):
    actions = [r for r in records if r['status'] != 'Notification']
    closed = [r for r in actions if r['status'] == 'Closed']
    on_time = sum(datetime.fromisoformat(r['closed_at']).astimezone(ZoneInfo('America/Manaus')).date()
                  <= date.fromisoformat(r['due_date']) for r in closed)
    return {'created': len(actions), 'active': len(actions) - len(closed), 'closed': len(closed),
            'notifications': len(records) - len(actions),
            'overdue': sum(overdue(r, today) for r in records),
            'verification': sum(r['status'] == 'Pending verification' for r in records),
            'on_time_rate': on_time / len(closed) if closed else None,
            'closure_rate': len(closed) / len(actions) if actions else None}


class ActionSyncError(RuntimeError):
    """The database committed locally but its upload did not complete."""


class ActionVerificationRequired(ValueError):
    """Closing an active card requires recorded effectiveness verification."""


class ActionStore:
    def __init__(self, database, prepare_write=lambda: None, persist=lambda: None, prepare_delete=None, prepare_move=None):
        self.database = Path(database)
        self.prepare_write = prepare_write
        self.persist = persist
        self.prepare_delete = prepare_delete or prepare_write
        self.prepare_move = prepare_move or prepare_write
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('''CREATE TABLE IF NOT EXISTS defect_action_cards (
                id TEXT PRIMARY KEY, revision TEXT NOT NULL, legacy_source TEXT UNIQUE,
                payload TEXT NOT NULL)''')
            conn.execute('''CREATE TABLE IF NOT EXISTS defect_action_history (
                revision TEXT PRIMARY KEY, action_id TEXT NOT NULL, actor TEXT NOT NULL,
                changed_at TEXT NOT NULL, payload TEXT NOT NULL)''')
            conn.execute('''CREATE TABLE IF NOT EXISTS defect_action_codes (
                action_id TEXT PRIMARY KEY, area_code TEXT NOT NULL, period TEXT NOT NULL,
                number INTEGER NOT NULL, code TEXT NOT NULL UNIQUE,
                UNIQUE(area_code, period, number))''')
            # Preserve UUIDs, revisions and history. Deterministic backfill also
            # avoids an extra cloud upload on a read-only visit after deployment.
            missing = [json.loads(row[0]) for row in conn.execute('''
                SELECT c.payload FROM defect_action_cards c
                LEFT JOIN defect_action_codes n ON n.action_id=c.id WHERE n.action_id IS NULL''')]
            for record in sorted(missing, key=lambda r: (_creation_time(r['created_at']), r['id'])):
                self._assign_code(conn, record['id'], record['area'], _creation_time(record['created_at']))

    @staticmethod
    def _assign_code(conn, action_id, area, created_at):
        existing = conn.execute('SELECT code FROM defect_action_codes WHERE action_id=?', (action_id,)).fetchone()
        if existing:
            return existing[0]
        prefix = AREA_CODES.get(area, 'OTH')
        local = created_at.astimezone(ZoneInfo('America/Manaus'))
        period = local.strftime('%Y-%m')
        number = conn.execute('SELECT COALESCE(MAX(number),0)+1 FROM defect_action_codes WHERE area_code=? AND period=?',
                              (prefix, period)).fetchone()[0]
        code = f'{prefix}-{number:03d}/{local:%m%y}'
        conn.execute('INSERT INTO defect_action_codes VALUES (?,?,?,?,?)', (action_id, prefix, period, number, code))
        return code

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
            records = [{**json.loads(row[0]), 'code': row[1]} for row in conn.execute('''
                SELECT c.payload, n.code FROM defect_action_cards c JOIN defect_action_codes n ON n.action_id=c.id''')]
            return records if include_deleted else [row for row in records if not row.get('deleted_at')]

    def deleted(self):
        return sorted([row for row in self.all(include_deleted=True) if row.get('deleted_at')],
                      key=lambda row: row['deleted_at'], reverse=True)

    def get(self, action_id):
        with self.connect() as conn:
            row = conn.execute('''SELECT c.payload, n.code FROM defect_action_cards c
                JOIN defect_action_codes n ON n.action_id=c.id WHERE c.id=?''', (action_id,)).fetchone()
            record = {**json.loads(row[0]), 'code': row[1]} if row else {}
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
        required = [('title', 'Action title')]
        if clean['status'] != 'Notification':
            required += [('owner', 'Owner'), ('due_date', 'Due date')]
        for key, label in required:
            if not clean[key]: raise ValueError(f'{label} is required.')
        if clean['area'] not in AREAS or clean['status'] not in STATUSES or clean['priority'] not in PRIORITIES:
            raise ValueError('Select a valid area, status and priority.')
        try:
            if clean['due_date']: date.fromisoformat(clean['due_date'])
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
            code = self._assign_code(conn, identifier, clean['area'], datetime.fromisoformat(current.get('created_at', now)))
            record = {**clean, 'id': identifier, 'code': code, 'revision': uuid4().hex,
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

    def move(self, session, action_id, status, expected_revision, *, countermeasure=None, evidence=None, verified=False):
        if not can_move_action(session):
            raise PermissionError('Sign in before moving an action.')
        if status not in STATUSES:
            raise ValueError('Select a valid action status.')
        current = self.get(action_id)
        if not current:
            raise ValueError('This action no longer exists. Refresh the board.')
        if not expected_revision or current['revision'] != expected_revision:
            raise ValueError('Another update was saved after this card was opened. Refresh the board and try again.')
        if current['status'] == status:
            return current
        if status != 'Notification' and (not current.get('owner') or not current.get('due_date')):
            raise ValueError('An administrator must set an owner and due date in the card before changing it to an action status.')
        self.prepare_move()
        with _LOCK, self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT payload FROM defect_action_cards WHERE id=?', (action_id,)).fetchone()
            current = json.loads(row[0]) if row else {}
            if not current or current.get('deleted_at'):
                raise ValueError('This action no longer exists. Refresh the board.')
            if current['revision'] != expected_revision:
                raise ValueError('Another update was saved after this card was opened. Refresh the board and try again.')
            changes = {'status': status, 'verified': False, 'closed_at': None}
            if status == 'Closed':
                measure = str(current.get('countermeasure', '') if countermeasure is None else countermeasure).strip()
                proof = str(current.get('evidence', '') if evidence is None else evidence).strip()
                if not (verified is True and measure and proof):
                    raise ActionVerificationRequired('Complete the countermeasure and effectiveness verification before closing the action.')
                if max(len(measure), len(proof)) > 10000:
                    raise ValueError('Use a shorter countermeasure or evidence description.')
                changes.update(countermeasure=measure, evidence=proof, verified=True)
            actor = str(session['authenticated_user']).strip()
            now = datetime.now(timezone.utc).isoformat(timespec='microseconds')
            if status == 'Closed': changes['closed_at'] = now
            code = self._assign_code(conn, action_id, current['area'], _creation_time(current['created_at']))
            record = {**current, **changes, 'code': code, 'revision': uuid4().hex, 'updated_at': now, 'updated_by': actor}
            conn.execute('UPDATE defect_action_cards SET revision=?, payload=? WHERE id=?',
                         (record['revision'], json.dumps(record, ensure_ascii=False), action_id))
            event = {'revision': record['revision'], 'actor': actor, 'changed_at': now, 'event': 'Updated',
                     'changes': {key: {'before': current.get(key), 'after': record[key]}
                                 for key in FIELDS if current.get(key) != record[key]}}
            conn.execute('INSERT INTO defect_action_history VALUES (?,?,?,?,?)',
                         (record['revision'], action_id, actor, now, json.dumps(event, ensure_ascii=False)))
        try:
            self.persist()
        except Exception as exc:
            raise ActionSyncError('The status was saved locally, but cloud synchronization was not confirmed. Retry synchronization before leaving this page.') from exc
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
            current['code'] = self._assign_code(conn, action_id, current['area'], _creation_time(current['created_at']))
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
