"""Kanban, filters and action statistics using native Streamlit controls."""
from tools.br_datetime import br_frame, br_date, br_datetime
from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from tools.access_control import is_admin_session, require_admin_access
from tools.action_summary import copy_summary_html
from tools.action_kanban import render_board
from tools.defect_actions import AREAS, PRIORITIES, STATUSES, ActionSyncError, can_delete_action, filter_actions, local_today, overdue, summary


def _timestamp(value):
    return datetime.fromisoformat(value).astimezone(ZoneInfo('America/Manaus')).strftime('%d/%m/%y %H:%M')


@st.dialog('Action details', width='large')
def details(store, record=None, initial_status='Open', legacy_source=None, requested_status=None):
    record = record or {}
    editable = is_admin_session(st.session_state)
    deletable = can_delete_action(st.session_state, record)
    if deletable:
        metadata, delete_control, copy_control = st.columns([3.1, 1.25, 1.4], vertical_alignment='center')
        with delete_control, st.container(key='defect_action_delete'):
            with st.popover('Delete action', icon=':material/delete:', use_container_width=True):
                st.markdown('**Delete this action?**')
                st.write(f"{record['id']} · {record['title']}")
                st.caption('The card will be removed from the board, statistics and exports. A deletion record will remain in the history. Previous report records are preserved.')
                with st.form('delete_action_'+record['id']+'_'+record['revision']):
                    confirmed = st.checkbox('I confirm that I want to delete this action.')
                    if st.form_submit_button('Confirm deletion', type='primary', width='stretch'):
                        try:
                            store.delete(st.session_state, record['id'], record['revision'], confirmed=confirmed)
                            st.session_state['_defect_action_flash'] = 'Action deleted.'
                            st.rerun()
                        except ActionSyncError as exc:
                            st.session_state['_defect_action_unsynced'] = str(exc)
                            st.session_state['_defect_action_sync_actor'] = st.session_state['authenticated_user']
                            st.rerun()
                        except (ValueError, PermissionError, RuntimeError) as exc:
                            st.error(str(exc))
    else:
        metadata, copy_control = st.columns([3.6, 1.4], vertical_alignment='center')
    with metadata:
        if record.get('id'):
            st.caption(f"{record['id']} · Created {_timestamp(record['created_at'])} by {record['created_by']}")
    with copy_control:
        st.html(copy_summary_html(record))
    import streamlit.components.v1 as components
    script = (Path(__file__).resolve().parents[1]/'assets'/'action-summary-copy.js').read_text(encoding='utf-8')
    components.html('<script>' + script + '</script>', height=0, scrolling=False)
    if requested_status == 'Closed':
        st.info('Complete the countermeasure and effectiveness verification, then save to close this action.')
    with st.form('defect_action_form'):
        title = st.text_input('Action title *', record.get('title', ''), max_chars=160, disabled=not editable)
        left, right = st.columns(2)
        with left:
            area = st.selectbox('Area', AREAS, index=AREAS.index(record.get('area', 'SMT')), disabled=not editable)
            owner = st.text_input('Owner *', record.get('owner', ''), max_chars=100, disabled=not editable)
            due_date = st.date_input('Due date *', date.fromisoformat(record['due_date']) if record.get('due_date') else local_today(), format='DD/MM/YYYY', disabled=not editable)
        with right:
            model = st.text_input('Model', record.get('model', ''), placeholder='All models or a specific model', disabled=not editable)
            priority = st.selectbox('Priority', PRIORITIES, index=PRIORITIES.index(record.get('priority', 'Medium')), disabled=not editable)
            status = st.selectbox('Status', STATUSES, index=STATUSES.index(requested_status or record.get('status', initial_status)), disabled=not editable)
        defect = st.text_input('Related defect / issue', record.get('defect', ''), disabled=not editable)
        root_cause = st.text_area('Problem / root cause', record.get('root_cause', ''), disabled=not editable)
        containment = st.text_area('Containment', record.get('containment', ''), disabled=not editable)
        countermeasure = st.text_area('Countermeasure / planned action', record.get('countermeasure', ''), disabled=not editable)
        evidence = st.text_area('Effectiveness verification / evidence', record.get('evidence', ''), placeholder='Describe the result and reference the evidence (document, report or URL).', disabled=not editable)
        verified = st.checkbox('Effectiveness verified — required to close the action', value=record.get('verified', False), disabled=not editable)
        if st.form_submit_button('Save action', type='primary', disabled=not editable, width='stretch'):
            try:
                store.save(st.session_state, dict(title=title, area=area, owner=owner, due_date=due_date.isoformat(),
                    model=model, priority=priority, status=status, defect=defect, root_cause=root_cause,
                    containment=containment, countermeasure=countermeasure, evidence=evidence, verified=verified),
                    action_id=record.get('id'), expected_revision=record.get('revision', ''), legacy_source=legacy_source)
                st.session_state['_defect_action_flash'] = 'Action saved.'
                st.rerun()
            except ActionSyncError as exc:
                st.session_state['_defect_action_unsynced'] = str(exc)
                st.rerun()
            except (ValueError, PermissionError, RuntimeError) as exc:
                st.error(str(exc))
    if not editable:
        st.caption('An administrator can edit action cards.' if deletable else 'Read-only access. An administrator can create and update action cards.')
    if record.get('id'):
        with st.expander('Change history'):
            events = store.history(record['id'])
            for event in events:
                st.markdown(f"**{event['event']} · {_timestamp(event['changed_at'])} · {escape(event['actor'])}**")
                changes = [{'Field': key.replace('_', ' ').title(), 'Before': br_date(value['before']) if key == 'due_date' else str(value['before'] if value['before'] is not None else '—'),
                            'After': br_date(value['after']) if key == 'due_date' else str(value['after'])} for key, value in event['changes'].items()]
                st.dataframe(br_frame(pd.DataFrame(changes)), hide_index=True, width='stretch')


def _card(store, action, today):
    with st.container(key='action_card_'+action['id']):
        pcolor, pbg = {'High': ('#B91C1C', '#FEE7E7'), 'Medium': ('#93600B', '#FFF2D8'), 'Low': ('#496A8D', '#EDF3F9')}[action['priority']]
        st.markdown(f'<div class="action-tags"><span class="action-tag">{escape(action["area"])}</span><span class="action-tag" style="color:{pcolor};background:{pbg}">{escape(action["priority"])} priority</span></div><div class="action-title">{escape(action["title"])}</div><div class="action-model">{escape(action["model"] or "All models")} · {escape(action["id"])}</div><div class="action-owner"><span class="owner-circle">{escape(action["owner"][0].upper())}</span>{escape(action["owner"])}</div>', unsafe_allow_html=True)
        due = date.fromisoformat(action['due_date'])
        if action['status'] == 'Closed':
            text, color, bg = '✓ Closed · effectiveness verified', '#07854B', '#E1F6EB'
        elif overdue(action, today):
            text, color, bg = f'◷ {due:%d/%m} · {(today-due).days}d overdue', '#B91C1C', '#FEE7E7'
        else:
            text, color, bg = f'◷ Due {due:%d/%m/%y}', '#496A8D', '#EFF4FA'
        st.markdown(f'<div class="action-due" style="color:{color};background:{bg}">{text}</div>', unsafe_allow_html=True)
        if st.button('Open action ↗', key='defect_open_'+action['id'], width='stretch'):
            details(store, store.get(action['id']))


def _table(records):
    columns = {'id': 'Action ID', 'title': 'Action', 'area': 'Area', 'model': 'Model', 'defect': 'Defect', 'owner': 'Owner',
               'priority': 'Priority', 'status': 'Status', 'due_date': 'Due date', 'created_at': 'Created', 'closed_at': 'Closed',
               'root_cause': 'Root cause', 'containment': 'Containment', 'countermeasure': 'Countermeasure', 'evidence': 'Evidence'}
    return pd.DataFrame([{columns[key]: record.get(key) or '' for key in columns} for record in records], columns=list(columns.values()))


def _statistics(records, today):
    if not records:
        st.info('No actions match the selected filters.')
        return
    stats = summary(records, today)
    left, right = st.columns(2)
    left.metric('Closure rate', f"{stats['closure_rate']:.0%}")
    right.metric('Closed on time', f"{stats['on_time_rate']:.0%}" if stats['on_time_rate'] is not None else '—')
    st.caption('Statistics follow the current filters. Closed on time compares the latest closure date to the current due date. Reopened actions are counted as active.')
    by_status, by_area = st.columns(2)
    with by_status:
        st.markdown('**Actions by status**')
        st.bar_chart(pd.Series({status: sum(r['status']==status for r in records) for status in STATUSES}, name='Actions'), color='#2563EB')
    with by_area:
        st.markdown('**Actions by area**')
        st.bar_chart(pd.Series({area: sum(r['area']==area for r in records) for area in AREAS if any(r['area']==area for r in records)}, name='Actions'), color='#7752D9')
    owners = []
    for owner in sorted({r['owner'] for r in records}):
        scoped = [r for r in records if r['owner']==owner]
        result = summary(scoped, today)
        owners.append({'Owner': owner, 'Created': result['created'], 'Active': result['active'], 'Overdue': result['overdue'], 'Closed': result['closed']})
    st.markdown('**Actions by owner**')
    st.dataframe(br_frame(pd.DataFrame(owners)), hide_index=True, width='stretch')
    created, closed = {}, {}
    for record in records:
        day = datetime.fromisoformat(record['created_at']).astimezone(ZoneInfo('America/Manaus')).date()
        created[day] = created.get(day, 0) + 1
        if record['closed_at']:
            day = datetime.fromisoformat(record['closed_at']).astimezone(ZoneInfo('America/Manaus')).date()
            closed[day] = closed.get(day, 0) + 1
    days = pd.date_range(min([*created, *closed]), max([*created, *closed]))
    trend = pd.DataFrame({'Created': [created.get(d.date(), 0) for d in days], 'Closed': [closed.get(d.date(), 0) for d in days]}, index=days)
    st.markdown('**Actions created and closed over time**')
    st.bar_chart(trend, color=['#2563EB', '#07854B'])


def _deleted_history(store):
    actor = str(st.session_state.get('authenticated_user', '')).casefold()
    privileged = st.session_state.get('authenticated') is True and st.session_state.get('auth_role') in {'admin', 'manager'}
    rows = [r for r in store.deleted() if privileged or str(r.get('created_by', '')).casefold() == actor]
    if rows:
        with st.expander('Deleted actions · History'):
            st.dataframe([{'Action ID': r['id'], 'Action': r['title'], 'Area': r['area'],
                           'Deleted at': br_datetime(r['deleted_at']), 'Deleted by': r['deleted_by']}
                          for r in rows], hide_index=True, width='stretch')
            st.caption('Deleted cards are excluded from the current board, statistics and exports. Their change history is retained.')


def _previous(store):
    _deleted_history(store)
    rows = store.legacy()
    st.caption('Original report records are preserved. Converting a record creates an independent card; it does not change the original report.')
    if not rows:
        st.info('No previous report actions were found.')
        return
    display = pd.DataFrame([{key: (br_date(row.get(key), dayfirst=False) if key == 'due_date' else row.get(key)) for key in ['area', 'period_key', 'defect_name', 'owner', 'due_date', 'root_cause', 'containment', 'countermeasure', 'imported']} for row in rows])
    st.dataframe(br_frame(display.rename(columns={'area': 'Area', 'period_key': 'Report period', 'defect_name': 'Defect', 'owner': 'Owner', 'due_date': 'Original due date',
        'root_cause': 'Root cause', 'containment': 'Containment', 'countermeasure': 'Countermeasure', 'imported': 'Card created'})), hide_index=True, width='stretch')
    available = [r for r in rows if not r['imported']]
    if available and is_admin_session(st.session_state):
        chosen = st.selectbox('Previous action to convert', range(len(available)), format_func=lambda i: f"{available[i]['area']} · {available[i]['period_key']} · {available[i]['defect_name']}", key='defect_legacy_choice')
        if st.button('Create card from previous action', key='defect_import_previous'):
            row = available[chosen]
            due = ''
            for fmt in ['%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y']:
                try:
                    due = datetime.strptime(str(row.get('due_date') or '').strip(), fmt).date().isoformat()
                    break
                except ValueError: pass
            record = {'title': row['defect_name'], 'defect': row['defect_name'], 'owner': row.get('owner') or '',
                      'area': row['area'] if row['area'] in AREAS else 'Other', 'due_date': due,
                      'root_cause': row.get('root_cause') or '', 'containment': row.get('containment') or '',
                      'countermeasure': row.get('countermeasure') or ''}
            details(store, record, legacy_source=row['source_key'])


@st.fragment(key='defect_action_board')
def render(store):
    """Keep card, view and filter interactions out of the full Smart Report rerun."""
    st.html('<style>' + (Path(__file__).resolve().parents[1]/'assets'/'defect-actions.css').read_text(encoding='utf-8') + '</style>')
    try:
        actions = store.all()
    except Exception:
        st.error('Action cards could not be loaded. Refresh the page and try again.')
        return
    today = local_today()
    editable = is_admin_session(st.session_state)
    flash = st.session_state.pop('_defect_action_flash', None)
    if flash:
        st.success(flash)
    notice = st.session_state.pop('_defect_kanban_notice', None)
    if notice:
        getattr(st, notice[0])(notice[1])
    if st.session_state.get('_defect_action_unsynced'):
        st.warning(st.session_state['_defect_action_unsynced'])
        can_retry = editable or (st.session_state.get('authenticated') is True and st.session_state.get('_defect_action_sync_actor') == st.session_state.get('authenticated_user'))
        if can_retry and st.button('Retry cloud synchronization', key='defect_retry_sync'):
            try:
                if editable: require_admin_access(st.session_state)
                else: store.prepare_delete()
                store.persist()
                del st.session_state['_defect_action_unsynced']
                st.session_state.pop('_defect_action_sync_actor', None)
                st.rerun(scope='fragment')
            except Exception: st.error('Cloud synchronization is still unavailable. Please try again.')
    with st.container(key='defect_action_head'):
        heading, new = st.columns([5, 1])
        with heading:
            st.title('Defect Action Report')
            st.caption('Track countermeasures, owners and deadlines — from investigation to verified closure.')
        with new:
            if st.button('＋ New action', type='primary', key='defect_new_action', disabled=not editable, width='stretch'):
                details(store)
    with st.container(key='defect_action_filters'):
        f1, f2, f3, f4, f5 = st.columns([1, 1.15, 1, 1.2, 2])
        area = f1.selectbox('Area', ['All areas', *AREAS], key='defect_filter_area')
        owner = f2.selectbox('Owner', ['All owners', *sorted({a['owner'] for a in actions})], key='defect_filter_owner')
        priority = f3.selectbox('Priority', ['All priorities', *PRIORITIES], key='defect_filter_priority')
        deadline = f4.selectbox('Deadline', ['Any deadline', 'Overdue', 'Next 7 days'], key='defect_filter_due')
        search = f5.text_input('Search action, defect or model', placeholder='Type to search...', key='defect_filter_search')
    with st.expander('More filters · Model, status and creation period'):
        c1, c2 = st.columns(2)
        models = c1.multiselect('Model', sorted({a['model'] for a in actions if a['model']}), key='defect_filter_models')
        statuses = c2.multiselect('Status', STATUSES, default=STATUSES, key='defect_filter_statuses')
        creation_filter = st.checkbox('Filter by creation period', key='defect_filter_creation_enabled')
        created_range = None
        if creation_filter:
            bounds = st.date_input('Created between', (today-timedelta(days=60), today), key='defect_filter_created', format='DD/MM/YYYY')
            if len(bounds) == 2: created_range = bounds
            else: st.caption('Select both dates to apply the creation period filter.')
    filtered = filter_actions(actions, today, area, owner, priority, deadline, search, models, statuses, created_range)
    stats = summary(filtered, today)
    metrics = [('ACTIONS CREATED', stats['created'], 'In the selected scope', '#2563EB'),
               ('ACTIVE ACTIONS', stats['active'], 'Open + in progress + verification', '#2563EB'),
               ('OVERDUE', stats['overdue'], 'Deadline passed · action still active', '#DC2626'),
               ('AWAITING VERIFICATION', stats['verification'], 'Countermeasure effectiveness', '#B77909'),
               ('CLOSED', stats['closed'], 'Completed and verified', '#07854B')]
    for column, (label, value, note, tone) in zip(st.columns(5), metrics):
        column.markdown(f'<div class="action-metric" style="--tone:{tone}"><div class="action-metric-label">{label}</div><div class="action-metric-value">{value}</div><div class="action-metric-note">{note}</div></div>', unsafe_allow_html=True)
    board, statistics, previous = st.tabs(['Action Board', 'Statistics', 'Previous report actions'])
    with board:
        left, right = st.columns([4, 1])
        left.caption(f'{len(filtered)} actions · Sorted by due date within each status')
        view = right.segmented_control('View', ['Kanban', 'Table'], default='Kanban', key='defect_action_view', label_visibility='collapsed')
        if not actions:
            st.info('Create your first action card, or convert an existing record in Previous report actions.')
        elif not filtered:
            st.info('No actions match the selected filters.')
        if view == 'Table':
            st.dataframe(br_frame(_table(filtered)), hide_index=True, width='stretch')
            if filtered:
                chosen = st.selectbox('Action details', [r['id'] for r in filtered], format_func=lambda value: next(r['title'] for r in filtered if r['id']==value), key='defect_table_choice')
                if st.button('Open selected action', key='defect_table_open'):
                    details(store, store.get(chosen))
        else:
            render_board(store, filtered, today)
        export = br_frame(_table(filtered)).to_csv(index=False).encode('utf-8-sig')
        st.download_button('Export filtered actions · CSV', export, file_name='defect-actions.csv', mime='text/csv', key='defect_export', disabled=not filtered, on_click='ignore')
    with statistics: _statistics(filtered, today)
    with previous: _previous(store)
    st.caption('All indicators follow the selected filters. ' + ('Only administrators can create or update actions.' if not editable else 'Drag a card to another column or use Move to. Closure requires a countermeasure and effectiveness verification.'))
    request = st.session_state.pop('_defect_kanban_dialog', None)
    if request:
        if request.get('id'):
            record = store.get(request['id'])
            if record:
                details(store, record, requested_status=request.get('requested_status'))
            else:
                st.error('This action no longer exists. Refresh the board.')
        else:
            details(store, initial_status=request['status'])
