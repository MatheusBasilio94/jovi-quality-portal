"""Native bidirectional Streamlit component for persisted Kanban status changes."""
from pathlib import Path

import streamlit as st

from tools.access_control import is_admin_session
from tools.br_datetime import br_date
from tools.defect_actions import STATUSES, ActionSyncError, ActionVerificationRequired, can_move_action, overdue

ASSETS = Path(__file__).resolve().parents[1]/'assets'
KEY = 'defect_drag_board'


@st.cache_resource(show_spinner=False)
def component(js_version, css_version):
    import streamlit.components.v2 as components
    return components.component('jovi_action_kanban', html='<div class="kanban-root"></div>',
        css=(ASSETS/'action-kanban.css').read_text(encoding='utf-8'),
        js=(ASSETS/'action-kanban.js').read_text(encoding='utf-8'))


def handle_event(store):
    event = st.session_state.get(KEY, {}).get('event')
    if not isinstance(event, dict) or not event.get('token'):
        return
    if event['token'] == st.session_state.get('_defect_kanban_ack'):
        return
    st.session_state['_defect_kanban_ack'] = event['token']
    kind = event.get('kind')
    try:
        if kind == 'move':
            store.move(st.session_state, event.get('id'), event.get('status'), event.get('revision'))
            st.session_state['_defect_kanban_notice'] = ('success', 'Action status updated.')
        elif kind == 'open':
            if not store.get(event.get('id')):
                raise ValueError('This action no longer exists. Refresh the board.')
            st.session_state['_defect_kanban_dialog'] = {'id': event['id']}
        elif kind == 'new':
            if not is_admin_session(st.session_state):
                raise PermissionError('Administrator access is required to create an action.')
            if event.get('status') not in STATUSES:
                raise ValueError('Select a valid action status.')
            st.session_state['_defect_kanban_dialog'] = {'status': event['status']}
    except ActionVerificationRequired:
        st.session_state['_defect_kanban_dialog'] = {'id': event['id'], 'requested_status': 'Closed'}
    except ActionSyncError as exc:
        st.session_state['_defect_action_unsynced'] = str(exc)
        st.session_state['_defect_action_sync_actor'] = st.session_state['authenticated_user']
        st.session_state['_defect_action_sync_kind'] = 'move'
    except (ValueError, PermissionError, RuntimeError) as exc:
        st.session_state['_defect_kanban_notice'] = ('error', str(exc))


def render_board(store, records, today):
    cards = []
    for record in records:
        card = {key: record.get(key, '') for key in ['id','code','revision','title','area','model','owner','priority','status']}
        due = br_date(record['due_date'])
        if record['status'] == 'Notification':
            card.update(due_label='Recorded '+br_date(record['created_at']), due_kind='notification')
        elif record['status'] == 'Closed':
            card.update(due_label='✓ Closed · effectiveness verified', due_kind='closed')
        elif overdue(record, today):
            from datetime import date
            late = (today-date.fromisoformat(record['due_date'])).days
            card.update(due_label=f'◷ {due} · {late}d overdue', due_kind='overdue')
        else:
            card.update(due_label='◷ Due '+due, due_kind='normal')
        cards.append(card)
    component((ASSETS/'action-kanban.js').stat().st_mtime_ns, (ASSETS/'action-kanban.css').stat().st_mtime_ns)(
                data={'cards': cards, 'statuses': STATUSES, 'editable': is_admin_session(st.session_state),
                      'movable': can_move_action(st.session_state),
                      'ack': st.session_state.get('_defect_kanban_ack')}, key=KEY,
                on_event_change=lambda: handle_event(store))
