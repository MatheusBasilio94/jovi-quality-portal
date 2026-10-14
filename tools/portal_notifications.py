"""Role-scoped notifications derived from saved records, with private read state."""
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
from threading import RLock
from uuid import uuid4
from zoneinfo import ZoneInfo

import streamlit as st

from tools.development_assessment import AssessmentStore
from tools.portal_users import development_access, registry

_LOCK = RLock()


def event_id(kind, subject, marker):
    return sha256(f'{kind}|{subject.casefold()}|{marker}'.encode()).hexdigest()


def collect(actor, role, users, store):
    """No assessment comments or ratings are copied into notifications."""
    notices = []
    people = {actor}
    if role == 'admin':
        people |= {u['username'] for u in users.values() if u.get('active') and u.get('approved')}
        for user in users.values():
            if user.get('active') and not user.get('approved'):
                notices.append({'id':event_id('account',user['username'],user.get('created_at','')),
                    'title':'Account awaiting approval','message':f"Employee ID {user['username']} requested access.",
                    'date':user.get('created_at',''),'subject':actor,'cycle':'','tab':'User Administration','account':user['username']})
    elif role == 'manager':
        people |= {u['username'] for u in users.values() if u.get('active') and u.get('approved') and u.get('manager')==actor}
    for subject in sorted(people):
        name = users.get(subject.casefold(),{}).get('display_name',subject)
        for cycle in store.cycles(subject):
            if subject == actor:
                review = store.load(subject,cycle,'manager')
                if review.get('status') == 'submitted':
                    notices.append({'id':event_id('review',subject,review['revision']),
                        'title':'Manager assessment completed or updated',
                        'message':f'Your review for {cycle[:7]} · {cycle[8:]} is available.',
                        'date':review.get('updated_at',''),'subject':subject,'cycle':cycle,'tab':'Assessment Comparison'})
            else:
                own = store.load(subject,cycle,'self')
                if own.get('status') != 'submitted': continue
                if role != 'admin' and own.get('manager') != actor: continue
                review = store.load(subject,cycle,'manager')
                from tools.development_assessment import comparable_manager
                if not comparable_manager(own,review):
                    notices.append({'id':event_id('self',subject,own['revision']),
                        'title':'Self assessment ready for review',
                        'message':f'{name} submitted {cycle[:7]} · {cycle[8:]}.',
                        'date':own.get('updated_at',''),'subject':subject,'cycle':cycle,'tab':'Manager Assessment'})
    return sorted(notices,key=lambda item:item['date'],reverse=True)


@st.cache_data(ttl=30,show_spinner=False)
def _events(actor, role, users_json, cloud, root):
    return collect(actor,role,json.loads(users_json),AssessmentStore(root,cloud=cloud))


def invalidate():
    _events.clear()


class ReadState:
    def __init__(self, store):
        self.store = store

    def path(self, actor):
        return f'notifications/{sha256(actor.casefold().encode()).hexdigest()}/read.json'

    def read(self, actor):
        path = self.path(actor)
        if self.store.cloud:
            from tools.supabase_store import download_bytes
            raw = download_bytes(path)
        else:
            file = self.store.local_root / path
            raw = file.read_bytes() if file.exists() else None
        return set(json.loads(raw).get('read',[])) if raw else set()

    def mark(self, actor, ids):
        with _LOCK:
            read = self.read(actor) | set(ids)
            raw = json.dumps({'read':sorted(read)}).encode()
            path = self.path(actor)
            if self.store.cloud:
                from tools.supabase_store import upload_bytes
                upload_bytes(path,raw)
            else:
                file = self.store.local_root / path
                file.parent.mkdir(parents=True,exist_ok=True)
                temp = file.with_name(file.name+'.'+uuid4().hex+'.tmp')
                temp.write_bytes(raw)
                temp.replace(file)


def render(navigate, quality_source=None):
    actor = str(st.session_state.get('authenticated_user',''))
    role = str(st.session_state.get('auth_role',''))
    notices, read, error = [], set(), False
    store = AssessmentStore()
    state = ReadState(store)
    try:
        if actor and development_access(st.session_state):
            users = registry()['users']
            # Restrict registry metadata to the people relevant to this inbox.
            fields = ['username','display_name','active','approved','manager','created_at']
            permitted = {key:{field:u.get(field) for field in fields} for key,u in users.items() if role=='admin' or u['username']==actor or (role=='manager' and u.get('manager')==actor)}
            notices = _events(actor,role,json.dumps(permitted,sort_keys=True),store.cloud,str(store.local_root))
    except Exception:
        error = True
    unavailable = []
    if actor and quality_source is not None:
        try:
            quality, unavailable = quality_source()
            notices.extend(quality)
        except Exception:
            unavailable = ['quality sources']
    try:
        if actor:
            read = state.read(actor)
    except Exception:
        error = True
    notices.sort(key=lambda item: item['date'], reverse=True)
    unread = [item for item in notices if item['id'] not in read]
    with st.popover(f'🔔 {len(unread)}' if unread else '🔔',help='Notifications',use_container_width=True):
        st.markdown('### Notifications')
        if error:
            st.info('Some notifications or read statuses could not be loaded. Your other portal functions remain available.')
        if unavailable:
            st.caption('Quality alerts unavailable for: ' + ', '.join(unavailable) + '. Check the uploaded sources.')
        if quality_source is not None:
            with st.expander('Quality alert rules'):
                st.caption('SMT and Assembly · General and per model · Completed days only. Daily KPI alerts require at least 100 input PCBs. The latest eligible day must be within the last 7 days. Trends use 3 eligible production days (2 consecutive changes).')
                st.caption('Recurrence: at least 3 distinct PCBs in 7 calendar days, independent of input. Component alerts match the recorded ItemCode, or location when no code exists. Official KPI rules apply, including glue defects; simulations do not change alerts. Daily alerts require observed daily input, not estimated weekly/monthly input.')
        if not notices:
            st.caption('No notifications at the moment.')
        else:
            st.caption(f'{len(unread)} unread · Quality and assessment updates')
            areas = ['All notifications', 'SMT', 'Assembly', 'Assessments and accounts']
            selected = st.selectbox('Notification scope', areas, key='notification_scope') if quality_source else areas[0]
            visible = [item for item in notices if selected == areas[0] or item.get('area') == selected or (selected == areas[-1] and not item.get('area'))]
            limit = 30
            if len(visible) > 30:
                options = sorted({30, min(60, len(visible)), len(visible)})
                limit = st.selectbox('Notifications to display', options, key='notification_display_count')
            if st.button('Mark all as read',disabled=not unread,key='notifications_read_all',width='stretch'):
                try:
                    state.mark(actor,[item['id'] for item in notices])
                    st.rerun()
                except Exception: st.error('Read status could not be saved. Try again.')
            for item in sorted(visible,key=lambda n:(n['id'] in read, notices.index(n)))[:limit]:
                with st.container(border=True):
                    st.markdown(('**New · '+item['title']+'**') if item['id'] not in read else item['title'])
                    st.write(item['message'])
                    try:
                        date = datetime.fromisoformat(item['date']).astimezone(ZoneInfo('America/Manaus'))
                        st.caption(date.strftime('%d/%m/%Y %H:%M'))
                    except (ValueError,TypeError): pass
                    if st.button('Open',key='notification_open_'+item['id'],width='stretch'):
                        try:
                            state.mark(actor,[item['id']])
                            if item.get('destination'):
                                navigate(item['destination'], item['tab'])
                            else:
                                st.session_state['_development_notification'] = {key:item[key] for key in ['subject','cycle','tab']}
                                if item.get('account'):
                                    st.session_state['_development_notification']['account'] = item['account']
                                navigate('Development Hub','')
                            st.rerun()
                        except Exception: st.error('The notification could not be opened. Try again.')
        if st.button('Refresh notifications',key='notifications_refresh',width='stretch'):
            invalidate()
            if quality_source is not None:
                quality_source(refresh=True)
            st.rerun()
