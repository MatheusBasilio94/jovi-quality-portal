"""Personal development rules and private, independently saved assessment parts."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from threading import RLock
from uuid import uuid4

AXES = [
    ('procedures', 'Procedures & Technical Knowledge', 'Knowledge of applicable procedures and evidence of practical application.'),
    ('results', 'Quality Results', 'Results attributable to your responsibilities, supported by indicators and cases.'),
    ('risks', 'Risk Prevention & Problem Solving', 'Risk detection, containment, root cause analysis and verified corrective actions.'),
    ('improvements', 'Improvement & Innovation', 'Completed improvements with demonstrated quality, efficiency or cost benefits.'),
    ('execution', 'Execution & Initiative', 'Timely deliveries, initiative, follow-through and early communication of obstacles.'),
    ('collaboration', 'Collaboration & Communication', 'Cooperation, constructive contributions and clear communication with stakeholders.'),
    ('learning', 'Learning & Knowledge Sharing', 'Application of learning, documented experience, training and support for colleagues.'),
]
SCALE = ['Not assessed', '1', '2', '3', '4', '5']
PARTS = {'self', 'manager', 'plan', 'progress', 'achievements'}
_LOCK = RLock()


def revision(record):
    return (record or {}).get('revision', '')


def validate_ratings(rows, submitting=False):
    cleaned = {}
    for key, _, _ in AXES:
        values = rows.get(key, {})
        rating = values.get('rating')
        if rating is not None and (type(rating) is not int or rating not in range(1, 6)):
            raise ValueError('Ratings must be whole numbers from 1 to 5, or Not assessed.')
        comment = str(values.get('comment') or '').strip()[:5000]
        evidence = str(values.get('evidence') or '').strip()[:5000]
        if submitting and rating is not None and not (comment or evidence):
            raise ValueError('Add a comment or evidence for each rated development area.')
        cleaned[key] = {'rating': rating, 'comment': comment, 'evidence': evidence}
    if submitting and not any(row['rating'] is not None for row in cleaned.values()):
        raise ValueError('Rate at least one development area before submitting.')
    return cleaned


def authorize(actor, subject, part, self_record=None, session=None):
    if not actor:
        raise PermissionError('An individual authenticated account is required.')
    if part == 'manager':
        if actor.casefold() == subject.casefold():
            raise PermissionError('You cannot complete your own manager assessment.')
        if not self_record or self_record.get('status') != 'submitted':
            raise PermissionError('A submitted self assessment is required before manager review.')
        from tools.access_control import is_admin_session
        administrator = is_admin_session(session or {}) and str((session or {}).get('authenticated_user', '')).casefold() == actor.casefold()
        if not administrator and actor.casefold() != str(self_record.get('manager') or '').casefold():
            raise PermissionError('Only the assigned manager or an administrator can complete this review.')
    elif actor.casefold() != subject.casefold():
        raise PermissionError('You can only change your own development records.')


class AssessmentStore:
    def __init__(self, local_root=None, cloud=None):
        if cloud is None:
            from tools.supabase_store import supabase_is_configured
            cloud = supabase_is_configured()
        self.cloud = cloud
        self.local_root = Path(local_root or Path(__file__).resolve().parents[1] / 'data_store' / 'development')

    def path(self, subject, cycle, part):
        if part not in PARTS or not subject:
            raise ValueError('Invalid development record.')
        if not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])_(SMT|Assembly|IQC-Lab)', cycle):
            raise ValueError('Select a valid assessment month and role.')
        person = sha256(subject.strip().casefold().encode()).hexdigest()
        return f'development/{person}/{cycle}/{part}.json'

    def load(self, subject, cycle, part):
        path = self.path(subject, cycle, part)
        if self.cloud:
            from tools.supabase_store import download_bytes
            raw = download_bytes(path)
        else:
            target = self.local_root / path
            raw = target.read_bytes() if target.exists() else None
        if raw is None:
            return {}
        record = json.loads(raw)
        if not isinstance(record, dict):
            raise ValueError('The saved development record could not be read.')
        return record

    def month_statuses(self, subject, year, scope):
        """Inspect existing monthly records only; 0=draft/absent, 1=self, 2=reviewed."""
        first = self.path(subject, f'{year:04d}-01_{scope}', 'self')
        prefix = first.rsplit('/', 2)[0]
        if self.cloud:
            from tools.supabase_store import _storage, _remote_object_path, _download_with_retry
            storage, _ = _storage()
            folders = []
            offset = 0
            while True:
                batch = storage.list(_remote_object_path(prefix), {'limit':1000, 'offset':offset})
                folders += [str(row.get('name', '')) for row in batch if isinstance(row, dict)]
                if len(batch) < 1000:
                    break
                offset += 1000
        else:
            directory = self.local_root / prefix
            folders = [p.name for p in directory.iterdir() if p.is_dir()] if directory.exists() else []
        statuses = {month:0 for month in range(1,13)}
        for month in statuses:
            cycle = f'{year:04d}-{month:02d}_{scope}'
            if cycle not in folders:
                continue
            if self.cloud:
                listed = storage.list(_remote_object_path(f'{prefix}/{cycle}'), {'limit':100})
                names = {row.get('name') for row in listed if isinstance(row, dict)}
                records = {}
                for part in ['self','manager']:
                    if f'{part}.json' in names:
                        raw = _download_with_retry(storage, self.path(subject,cycle,part))
                        records[part] = json.loads(raw)
                    else:
                        records[part] = {}
            else:
                records = {part:self.load(subject,cycle,part) for part in ['self','manager']}
            own, review = records['self'], records['manager']
            if own.get('status') == 'submitted':
                statuses[month] = 2 if comparable_manager(own,review) else 1
        return statuses

    def cycles(self, subject):
        prefix = self.path(subject, '2000-01_SMT', 'self').rsplit('/',2)[0]
        if self.cloud:
            from tools.supabase_store import _storage, _remote_object_path
            storage, _ = _storage()
            names = []
            offset = 0
            while True:
                batch = storage.list(_remote_object_path(prefix), {'limit':1000,'offset':offset})
                names += [str(row.get('name','')) for row in batch if isinstance(row,dict)]
                if len(batch)<1000: break
                offset += 1000
        else:
            directory = self.local_root / prefix
            names = [p.name for p in directory.iterdir() if p.is_dir()] if directory.exists() else []
        return sorted([name for name in names if re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])_(SMT|Assembly|IQC-Lab)',name) and not name.startswith('2000-01_')], reverse=True)

    def save(self, actor, subject, cycle, part, payload, expected_revision='', session=None):
        with _LOCK:
            self_record = self.load(subject, cycle, 'self') if part == 'manager' else None
            authorize(actor, subject, part, self_record, session)
            if part == 'manager' and payload.get('self_revision') != revision(self_record):
                raise ValueError('The self assessment changed. Reload it before saving the manager review.')
            current = self.load(subject, cycle, part)
            if revision(current) != expected_revision:
                raise ValueError('This record was updated in another session. Reload before saving.')
            record = {**payload, 'subject': subject, 'actor': actor, 'revision': uuid4().hex,
                      'updated_at': datetime.now(timezone.utc).isoformat()}
            if part in {'self', 'manager'}:
                if record.get('status') not in {'draft', 'submitted'}:
                    raise ValueError('Invalid assessment status.')
                record['ratings'] = validate_ratings(record.get('ratings', {}), record['status'] == 'submitted')
            raw = json.dumps(record, ensure_ascii=False).encode()
            path = self.path(subject, cycle, part)
            if self.cloud:
                from tools.supabase_store import upload_bytes
                upload_bytes(path, raw)
            else:
                target = self.local_root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_name(target.name + '.' + uuid4().hex + '.tmp')
                temporary.write_bytes(raw)
                temporary.replace(target)
            if part in {'self','manager'}:
                from tools.portal_notifications import invalidate
                invalidate()
            return record


def comparable_manager(self_record, manager_record):
    return bool(self_record.get('status') == 'submitted' and manager_record.get('status') == 'submitted'
                and manager_record.get('self_revision') == revision(self_record))
