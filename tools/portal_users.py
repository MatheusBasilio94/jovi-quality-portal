"""Private personal account registry, enrollment and credential lifecycle."""
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
from threading import RLock

import streamlit as st

_LOCK = RLock()
OBJECT = 'development/accounts.json'
LOCAL = Path(__file__).resolve().parents[1] / 'data_store' / 'development' / 'accounts.json'
ROLES = {'viewer', 'employee', 'manager', 'admin'}


def password_hash(password):
    salt = os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 240000).hex()
    return f'pbkdf2$240000${salt}${digest}'


def password_matches(password, encoded):
    if encoded.startswith('pbkdf2$'):
        try:
            _, rounds, salt, expected = encoded.split('$')
            actual = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), int(rounds)).hex()
            return hmac.compare_digest(actual, expected)
        except (ValueError, TypeError):
            return False
    return hmac.compare_digest(hashlib.sha256(password.encode()).hexdigest(), encoded)


@st.cache_data(ttl=15, show_spinner=False)
def registry():
    from tools.supabase_store import download_bytes, supabase_is_configured
    if supabase_is_configured():
        raw = download_bytes(OBJECT)
    else:
        raw = LOCAL.read_bytes() if LOCAL.exists() else None
    return json.loads(raw) if raw else {'users': {}}


def _write(data):
    from tools.supabase_store import upload_bytes, supabase_is_configured
    raw = json.dumps(data, ensure_ascii=False).encode()
    if supabase_is_configured():
        upload_bytes(OBJECT, raw)
    else:
        LOCAL.parent.mkdir(parents=True, exist_ok=True)
        temporary = LOCAL.with_suffix('.tmp')
        temporary.write_bytes(raw)
        temporary.replace(LOCAL)
    registry.clear()


def _admin(session):
    if session.get('authenticated') is not True or session.get('auth_role') != 'admin':
        raise PermissionError('Administrator access is required.')


def enroll(employee_id, reserved=()):
    employee_id = employee_id.strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{2,40}', employee_id):
        raise ValueError('Use your employee ID, with letters, numbers, hyphens or underscores.')
    with _LOCK:
        registry.clear()
        data = registry()
        key = employee_id.casefold()
        if key in data['users'] or key in {name.casefold() for name in reserved}:
            raise ValueError('This employee ID already has an account.')
        data['users'][key] = {'username': employee_id, 'display_name': employee_id,
            'password_hash': password_hash(employee_id), 'role': 'viewer', 'approved': False,
            'must_change_password': True, 'active': True, 'manager': '', 'individual': True,
            'created_at': datetime.now(timezone.utc).isoformat()}
        _write(data)


def change_password(username, old_password, new_password, name):
    if len(new_password) < 8 or new_password == username:
        raise ValueError('Choose a password with at least 8 characters, different from your employee ID.')
    if not name.strip():
        raise ValueError('Enter your display name.')
    with _LOCK:
        registry.clear()
        data = registry()
        user = data['users'].get(username.casefold())
        if not user or not password_matches(old_password, user['password_hash']):
            raise ValueError('The current password is incorrect.')
        user.update(password_hash=password_hash(new_password), display_name=name.strip()[:100], must_change_password=False)
        _write(data)
        return dict(user)


def configure_user(session, username, role, approved, manager, active=True, fallback=None):
    _admin(session)
    if role not in ROLES:
        raise ValueError('Invalid access level.')
    with _LOCK:
        registry.clear()
        data = registry()
        user = data['users'].get(username.casefold())
        if not user and fallback:
            user = dict(fallback)
            data['users'][username.casefold()] = user
        if not user:
            raise ValueError('The account was not found.')
        if username.casefold() == str(session.get('authenticated_user', '')).casefold() and (role != user['role'] or not approved or not active):
            raise ValueError('You cannot change your own access level or deactivate your own account.')
        if manager.casefold() == username.casefold():
            raise ValueError('The user cannot be their own manager.')
        user.update(role=role, approved=bool(approved), manager=manager, active=bool(active))
        _write(data)


def reset_password(session, username, fallback=None):
    _admin(session)
    with _LOCK:
        registry.clear()
        data = registry()
        key = username.casefold()
        user = data['users'].get(key)
        if not user:
            if not fallback:
                raise ValueError('The account was not found.')
            user = dict(fallback)
            data['users'][key] = user
        user.update(password_hash=password_hash(username), must_change_password=True)
        _write(data)


def profile(username):
    return registry()['users'].get(username.casefold(), {})


def development_access(session):
    if session.get('authenticated') is not True:
        return False
    if session.get('auth_role') in {'admin', 'employee', 'manager'}:
        return True
    user = profile(str(session.get('authenticated_user', '')))
    return bool(user.get('approved') and user.get('active') and user.get('individual'))


def first_access(account, issue_token, logout):
    user = profile(account.username)
    if user.get('must_change_password'):
        st.button('Sign out', key='first_access_logout', on_click=logout)
        st.subheader('Set your password and display name')
        st.caption('Your employee ID remains your login. Change the initial or reset password before continuing.')
        with st.form('first_access_password'):
            current = st.text_input('Current password', type='password')
            name = st.text_input('Display name', value=user.get('display_name', account.username))
            new = st.text_input('New password', type='password')
            confirm = st.text_input('Confirm new password', type='password')
            save = st.form_submit_button('Save and continue')
        if save:
            try:
                if new != confirm:
                    raise ValueError('The new passwords do not match.')
                updated = change_password(account.username, current, new, name)
                st.session_state['auth_cookie_token'] = issue_token(account.username, updated['password_hash'])
                st.rerun()
            except (ValueError, RuntimeError) as exc:
                st.error(str(exc))
        st.stop()
    if user and not user.get('approved'):
        st.info('Your account is awaiting administrator approval. Your password and profile have been saved.')
        st.button('Sign out', key='pending_account_logout', on_click=logout)
        st.stop()


def administration(accounts):
    _admin(st.session_state)
    st.markdown('### User administration')
    users = registry()['users']
    rows = [{'Employee ID / Login': a.username, 'Display name': users.get(a.username.casefold(), {}).get('display_name', a.username),
             'Access level': a.role, 'Approved': users.get(a.username.casefold(), {}).get('approved', True),
             'Password change required': users.get(a.username.casefold(), {}).get('must_change_password', False),
             'Active': users.get(a.username.casefold(), {}).get('active', True)} for a in accounts]
    listed = {a.username.casefold() for a in accounts}
    rows += [{'Employee ID / Login': u['username'], 'Display name': u.get('display_name', u['username']),
              'Access level': u['role'], 'Approved': u.get('approved', False),
              'Password change required': u.get('must_change_password', False), 'Active': u.get('active', True)}
             for key, u in users.items() if key not in listed]
    st.dataframe(rows, hide_index=True, width='stretch')
    with st.form('create_individual_account'):
        employee_id = st.text_input('New employee ID')
        create = st.form_submit_button('Create pending account')
    if create:
        try:
            enroll(employee_id, [a.username for a in accounts])
            st.success('Account created with employee ID as initial password. Approval and password change are required.')
            st.rerun()
        except (ValueError, RuntimeError) as exc:
            st.error(str(exc))
    usernames = sorted({a.username for a in accounts} | {u['username'] for u in users.values()})
    chosen = st.selectbox('Manage account', usernames, key='manage_development_user')
    user = users.get(chosen.casefold())
    account = next((a for a in accounts if a.username == chosen), None)
    fallback = {'username': chosen, 'display_name': chosen, 'password_hash': account.password_hash, 'role': account.role, 'approved': True, 'active': True, 'must_change_password': False, 'manager': ''} if account else None
    user = user or fallback
    if user:
        labels = {'viewer': 'Common user · personal Development Hub', 'manager': 'Manager · assigned employee reviews', 'admin': 'Administrator · full access'}
        managers = [''] + [a.username for a in accounts if a.role in {'manager', 'admin'} and a.username.casefold() != chosen.casefold()]
        with st.form('configure_development_user'):
            role = st.selectbox('Access level', list(labels), index=list(labels).index(user['role']) if user['role'] in labels else 0, format_func=labels.get)
            approved = st.checkbox('Approve account', value=user.get('approved', False))
            active = st.checkbox('Active account', value=user.get('active', True))
            manager = st.selectbox('Assigned manager', managers, index=managers.index(user.get('manager', '')) if user.get('manager', '') in managers else 0, format_func=lambda x: x or 'Not assigned')
            save = st.form_submit_button('Save access settings')
        if save:
            try:
                configure_user(st.session_state, chosen, role, approved, manager, active, fallback=fallback)
                st.rerun()
            except (ValueError, PermissionError, RuntimeError) as exc:
                st.error(str(exc))
    else:
        st.caption('Existing portal account. You can reset its password; existing access is preserved.')
    if st.button('Reset password to employee ID / login', key='reset_individual_password'):
        try:
            fallback = {'username': chosen, 'display_name': chosen, 'role': account.role, 'approved': True, 'active': True, 'manager': ''} if account else None
            reset_password(st.session_state, chosen, fallback)
            st.success('Password reset. Existing sign-in tokens are invalidated; a new password is required at the next access.')
        except (ValueError, PermissionError, RuntimeError) as exc:
            st.error(str(exc))
