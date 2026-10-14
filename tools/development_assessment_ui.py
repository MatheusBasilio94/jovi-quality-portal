"""Individual self assessment, assigned-manager review and comparison."""
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from tools.access_control import configured_accounts, is_admin_session
from tools.development_assessment import AXES, SCALE, AssessmentStore, comparable_manager, revision
from tools.portal_users import administration, development_access, profile, registry

MONTH_NAMES = ['January','February','March','April','May','June','July','August','September','October','November','December']


@st.cache_data(ttl=30, show_spinner=False)
def _month_statuses(subject, year, scope, cloud, root, _store):
    return _store.month_statuses(subject, year, scope)


def _save(store, actor, subject, cycle, part, data, old):
    try:
        store.save(actor, subject, cycle, part, data, revision(old), session=st.session_state)
        _month_statuses.clear()
        st.session_state['development_notice'] = 'Saved successfully.'
        st.rerun()
    except (ValueError, PermissionError, RuntimeError) as exc:
        st.error(str(exc))


def _assessment_form(store, actor, subject, cycle, part, own, review, manager):
    record = own if part == 'self' else review
    reviewer_allowed = is_admin_session(st.session_state) or (actor == manager and own.get('manager') == manager)
    can_edit = actor == subject if part == 'self' else actor != subject and reviewer_allowed and own.get('status') == 'submitted'
    st.caption('Self Assessment' if part == 'self' else 'Manager Assessment')
    if part == 'self' and not manager:
        st.info('Save a draft now. An administrator must assign your manager before you can submit the assessment.')
    if own.get('status') == 'submitted' and own.get('manager') != manager:
        st.info('Your assigned manager changed. Submit your self assessment again to route the review to the new manager.')
    st.caption('1: Needs significant development · 2: Partially meets expectations · 3: Meets expectations · 4: Exceeds expectations · 5: Role model · Not assessed: insufficient information')
    if part == 'manager':
        if actor == subject:
            st.info('Your assigned manager completes this assessment using their own account.')
        elif own.get('status') != 'submitted':
            st.info('The employee must submit the self assessment before the manager can review it.')
    rows = []
    for key, label, definition in AXES:
        item = record.get('ratings', {}).get(key, {})
        rows.append({'Development area': label, 'Rating': str(item['rating']) if item.get('rating') is not None else 'Not assessed',
                     'Comment / Analysis': item.get('comment', ''), 'Evidence / Results': item.get('evidence', '')})
    with st.expander('What each development area covers'):
        for _, label, definition in AXES:
            st.markdown(f'**{label}:** {definition}')
    if part == 'manager':
        st.markdown('### Your manager assessment')
        st.caption('Select your rating for each development area and add your feedback below. The employee ratings are available for reference at the end of this section.')
    with st.form(f'development_{part}_{subject}_{cycle}_{revision(record)}'):
        manager_values = {}
        if part == 'manager':
            for index, (key, label, definition) in enumerate(AXES):
                existing = rows[index]
                prefix = f'manager_rating_{subject}_{cycle}_{revision(record)}_{key}'
                left, right = st.columns([1, 2])
                with left:
                    rating = st.selectbox(label, SCALE, index=SCALE.index(existing['Rating']), disabled=not can_edit, key=prefix)
                    self_rating = own.get('ratings', {}).get(key, {}).get('rating')
                    st.caption(f"Self rating: {self_rating if self_rating is not None else 'Not assessed'}")
                with right:
                    comment = st.text_input('Manager feedback', value=existing['Comment / Analysis'], disabled=not can_edit, key=prefix+'_comment')
                    evidence = st.text_input('Evidence / Results', value=existing['Evidence / Results'], disabled=not can_edit, key=prefix+'_evidence')
                manager_values[key] = {'rating': int(rating) if rating != 'Not assessed' else None, 'comment': comment, 'evidence': evidence}
        else:
            edited = st.data_editor(pd.DataFrame(rows), hide_index=True, width='stretch', height=325,
                disabled=True if not can_edit else ['Development area'],
                column_config={'Development area': st.column_config.TextColumn(width=310),
                    'Rating': st.column_config.SelectboxColumn(options=SCALE, width=125, required=True),
                    'Comment / Analysis': st.column_config.TextColumn(width=390),
                    'Evidence / Results': st.column_config.TextColumn(width=390)})
        st.caption('Add a comment or evidence for every rated area. Unrated areas remain Not assessed.')
        first, second = st.columns(2)
        with first: draft = st.form_submit_button('Save draft', disabled=not can_edit, width='stretch')
        with second: submit = st.form_submit_button('Submit self assessment' if part == 'self' else 'Complete manager assessment', disabled=not can_edit or (part == 'self' and not manager), type='primary', width='stretch')
    if draft or submit:
        ratings = manager_values if part == 'manager' else {key: {'rating': int(edited.iloc[index]['Rating']) if edited.iloc[index]['Rating'] != 'Not assessed' else None,
                         'comment': edited.iloc[index]['Comment / Analysis'], 'evidence': edited.iloc[index]['Evidence / Results']}
                   for index, (key, _, _) in enumerate(AXES)}
        data = {'status': 'submitted' if submit else 'draft', 'ratings': ratings}
        if part == 'self': data['manager'] = manager
        else: data['self_revision'] = revision(own)
        _save(store, actor, subject, cycle, part, data, record)
    st.caption(f"Status: {record.get('status', 'Not started').title()} · Assigned manager: {manager or 'Not assigned'}")
    if part == 'manager' and own.get('ratings'):
        with st.expander('Submitted self assessment · reference only'):
            st.dataframe([{'Development area': label, 'Self rating': own['ratings'].get(key, {}).get('rating'),
                           'Comment': own['ratings'].get(key, {}).get('comment', ''), 'Evidence': own['ratings'].get(key, {}).get('evidence', '')}
                          for key, label, _ in AXES], hide_index=True, width='stretch')


def _comparison(own, review):
    st.markdown('### Assessment comparison')
    current_review = comparable_manager(own, review)
    if review and not current_review:
        st.info('The manager assessment is pending or relates to an earlier self assessment. Complete a new review to compare current evaluations.')
    if current_review:
        st.caption(f"Manager assessment completed by: {review.get('actor', '—')}")
    labels = [label.replace(' & ', ' &<br>') for _, label, _ in AXES]
    fig = go.Figure()
    for record, name, color in [(own, 'Self Assessment', '#2563EB'), (review if current_review else {}, 'Manager Assessment', '#7C3AED')]:
        values = [record.get('ratings', {}).get(key, {}).get('rating') for key, _, _ in AXES]
        if any(value is not None for value in values):
            fig.add_trace(go.Scatterpolar(r=values+[values[0]], theta=labels+[labels[0]], name=name,
                mode='lines+markers', connectgaps=False, fill='toself' if all(v is not None for v in values) else 'none',
                line=dict(color=color, width=3), marker=dict(size=7), hovertemplate='%{theta}: %{r}/5<extra>%{fullData.name}</extra>'))
    if not fig.data:
        st.info('Start your self assessment to see your radar. Missing ratings are not treated as zero.')
    else:
        fig.update_layout(height=430, margin=dict(l=135,r=135,t=45,b=55), paper_bgcolor='white',
            legend=dict(orientation='h', y=-.15), font=dict(size=12,color='#0B2D61'),
            polar=dict(bgcolor='white', radialaxis=dict(range=[0,5],tickvals=[1,2,3,4,5],gridcolor='#D8E4F4'),
                       angularaxis=dict(rotation=90,direction='clockwise',gridcolor='#D8E4F4')))
        st.plotly_chart(fig, width='stretch', key='development_comparison_radar')
    rows = []
    for key, label, _ in AXES:
        left = own.get('ratings', {}).get(key, {})
        right = review.get('ratings', {}).get(key, {}) if current_review else {}
        a, b = left.get('rating'), right.get('rating')
        rows.append({'Development area': label, 'Self Assessment': str(a) if a is not None else 'Not assessed',
            'Manager Assessment': str(b) if b is not None else 'Not assessed',
            'Gap (Manager − Self)': f'{b-a:+d}' if a is not None and b is not None else '—',
            'Self analysis': left.get('comment', ''), 'Manager feedback': right.get('comment', '')})
    frame = pd.DataFrame(rows)
    def gap_color(value):
        try:
            gap = int(value)
        except (ValueError, TypeError):
            return ''
        if gap > 0:
            return 'background-color: #D9FBE7; color: #08703B; font-weight: 700;'
        if gap < 0:
            return 'background-color: #FFE2E2; color: #B91C1C; font-weight: 700;'
        return ''
    table = (frame.style.hide(axis='index').format(escape='html')
        .map(gap_color, subset=['Gap (Manager − Self)'])
        .set_properties(subset=['Development area'], **{'text-align':'left'})
        .set_properties(subset=list(frame.columns[1:]), **{'text-align':'center'})
        .set_table_styles([
            {'selector':'', 'props':[('width','100%'),('min-width','1000px'),('border-collapse','collapse'),('table-layout','fixed'),('font-size','13px'),('color','#0B2D61')]},
            {'selector':'th', 'props':[('text-align','center'),('background','#E8EEF7'),('color','#607C9F'),('font-weight','500'),('padding','10px 8px'),('border','1px solid #DFE7F1')]},
            {'selector':'td', 'props':[('padding','9px 8px'),('border','1px solid #DFE7F1'),('vertical-align','middle'),('overflow-wrap','anywhere')]},
            {'selector':'th:nth-child(1)', 'props':[('width','24%')]},
            {'selector':'th:nth-child(2)', 'props':[('width','14%')]},
            {'selector':'th:nth-child(3)', 'props':[('width','16%')]},
            {'selector':'th:nth-child(4)', 'props':[('width','16%')]},
            {'selector':'th:nth-child(5)', 'props':[('width','15%')]},
            {'selector':'th:nth-child(6)', 'props':[('width','15%')]},
        ]))
    st.html("<div style='overflow-x:auto;border-radius:8px;border:1px solid #DFE7F1;'>"+table.to_html()+"</div>")
    st.caption('Differences identify topics for discussion, not automatic penalties. This radar is separate from the official company assessment and its 60/15/15/10 weighting.')


def _procedures(store, actor, subject, records, scope):
    cycle = '2000-01_SMT'  # Lifelong checklist, independent of monthly reviews.
    record = store.load(subject, cycle, 'progress')
    state = record.get('documents', {})
    eligible = [item for item in records if any(area in item['areas'] for area in (['IQC','Lab'] if scope == 'IQC-Lab' else [scope]))]
    learned = sum(bool(state.get(f"{item['type']}:{item['number']}", {}).get('understood')) for item in eligible)
    st.metric('Procedures understood', f'{learned} / {len(eligible)}')
    st.caption('Checklist progress supports your Procedures assessment. Reading does not automatically assign a radar rating.')
    area, search = st.columns([1,3])
    with area: chosen = st.selectbox('Area', ['All areas','SMT','Assembly','IQC','Lab'], key='development_area', persist_state='session')
    with search: query = st.text_input('Search document title', key='development_search', persist_state='session')
    kind = st.radio('Document type', ['Process Documents','Job Manuals'], horizontal=True, key='development_type', persist_state='session')
    selected = [item for item in records if item['type'] == kind and (chosen == 'All areas' or chosen in item['areas']) and query.casefold() in item['title'].casefold()]
    rows = []
    for item in selected:
        values = state.get(f"{item['type']}:{item['number']}", {})
        rows.append({'Document title': item['title'], 'Area': ', '.join(item['areas']), 'Read': bool(values.get('read')),
            'Understood': bool(values.get('understood')), 'Document': item['url']})
    frame = pd.DataFrame(rows, columns=['Document title','Area','Read','Understood','Document'])
    with st.form(f'development_progress_{subject}_{revision(record)}'):
        edited = st.data_editor(frame, hide_index=True, width='stretch', height=450,
            disabled=True if actor != subject else ['Document title','Area','Document'],
            column_config={'Document title':st.column_config.TextColumn(width=760), 'Area':st.column_config.TextColumn(width=180),
                'Read':st.column_config.CheckboxColumn(width=75), 'Understood':st.column_config.CheckboxColumn(width=105),
                'Document':st.column_config.LinkColumn(display_text='Open document',width=120)})
        save = st.form_submit_button('Save procedure progress', disabled=actor != subject)
    if save:
        for index, item in enumerate(selected):
            understood = bool(edited.iloc[index]['Understood'])
            state[f"{item['type']}:{item['number']}"] = {'read': bool(edited.iloc[index]['Read']) or understood, 'understood': understood}
        _save(store, actor, subject, cycle, 'progress', {'documents': state}, record)
    st.caption('Read and Understood are personal declarations. Four source documents have no document link.')


def render(records):
    if not development_access(st.session_state):
        st.error('An approved individual account is required for Development Hub.')
        return
    actor = str(st.session_state.get('authenticated_user') or 'Matheus')
    users = registry()['users']
    subjects = [actor]
    if is_admin_session(st.session_state):
        subjects += [u['username'] for u in users.values() if u.get('approved') and u.get('active') and u['username'] != actor]
    elif st.session_state.get('auth_role') == 'manager':
        subjects += [u['username'] for u in users.values() if u.get('approved') and u.get('active') and u.get('manager') == actor and u['username'] != actor]
    target = st.session_state.pop('_development_notification', None)
    if target and target.get('subject') in subjects:
        st.session_state['development_subject'] = target['subject']
        if target.get('cycle'):
            year_month, scope_name = target['cycle'].split('_',1)
            year_value, month_value = year_month.split('-')
            st.session_state['development_scope'] = scope_name
            st.session_state['development_year'] = int(year_value)
            st.session_state['development_month_choice'] = int(month_value)
        st.session_state['_development_tab_default'] = target['tab']
        if target.get('account') and is_admin_session(st.session_state):
            st.session_state['manage_development_user'] = target['account']
    st.markdown("<div class='smart-report-title'>Development Hub</div><div class='smart-report-subtitle'>Self assessment, manager feedback and your development plan.</div>", unsafe_allow_html=True)
    columns = st.columns([1.4,1,.65,1])
    with columns[0]: subject = st.selectbox('Employee', subjects, format_func=lambda x: users.get(x.casefold(), {}).get('display_name', x), key='development_subject')
    with columns[1]: scope = st.selectbox('Role / scope', ['SMT','Assembly','IQC-Lab'], key='development_scope')
    today = datetime.now(ZoneInfo('America/Manaus')).date()
    store = AssessmentStore()
    with columns[2]: year = int(st.number_input('Assessment year', min_value=1900, max_value=9999, value=today.year, step=1, key='development_year'))
    try:
        statuses = _month_statuses(subject, year, scope, store.cloud, str(store.local_root), store)
    except Exception:
        statuses = {}
        st.warning('Assessment month statuses could not be loaded. Select a month to open its assessment.')
    with columns[3]:
        selected_month = st.selectbox('Assessment month', range(1,13), index=today.month-1,
            format_func=lambda value: MONTH_NAMES[value-1] + (' ✅✅' if statuses.get(value)==2 else ' ✅' if statuses.get(value)==1 else ''),
            key='development_month_choice', persist_state='session')
    month = today.replace(year=year, month=selected_month, day=1)
    cycle = f'{year:04d}-{selected_month:02d}_{scope}'
    st.caption('✅ Self assessment submitted · ✅✅ Manager assessment completed · No check: no submitted assessment. Status applies to the selected employee, role and year.')
    try:
        own = store.load(subject, cycle, 'self')
        review = store.load(subject, cycle, 'manager')
    except (ValueError, RuntimeError) as exc:
        st.error(f'The development records could not be loaded: {exc}')
        return
    manager = users.get(subject.casefold(), {}).get('manager', '')
    st.caption(f"Profile: {users.get(subject.casefold(), {}).get('display_name', subject)} · Manager: {manager or 'Not assigned'} · {month:%B %Y}")
    if st.session_state.pop('development_notice', None): st.success('Saved successfully.')
    names = ['Assessment Comparison','Self Assessment','Manager Assessment','Procedures','Achievements','Development Plan']
    if is_admin_session(st.session_state): names.append('User Administration')
    default_tab = st.session_state.get('_development_tab_default')
    tabs = dict(zip(names, st.tabs(names, default=default_tab if default_tab in names else names[0])))
    with tabs['Assessment Comparison']: _comparison(own, review)
    with tabs['Self Assessment']: _assessment_form(store, actor, subject, cycle, 'self', own, review, manager)
    with tabs['Manager Assessment']: _assessment_form(store, actor, subject, cycle, 'manager', own, review, manager)
    with tabs['Procedures']: _procedures(store, actor, subject, records, scope)
    with tabs['Achievements']:
        record = store.load(subject, cycle, 'achievements')
        entries = record.get('entries', [])
        st.caption('Record completed achievements and supporting evidence. These records do not automatically change your ratings.')
        if entries: st.dataframe(entries, hide_index=True, width='stretch')
        with st.form(f'add_development_achievement_{subject}_{cycle}'):
            title = st.text_input('Achievement title')
            axis = st.selectbox('Development area', [label for _,label,_ in AXES])
            date = st.date_input('Completion date', value=today)
            evidence = st.text_area('Result and evidence')
            add = st.form_submit_button('Add achievement', disabled=actor != subject)
        if add:
            if not title.strip() or not evidence.strip(): st.error('Enter a title and result / evidence.')
            else: _save(store, actor, subject, cycle, 'achievements', {'entries':entries+[{'Title':title.strip(),'Development area':axis,'Date':date.isoformat(),'Result / Evidence':evidence.strip(),'Status':'Self reported'}]}, record)
    with tabs['Development Plan']:
        record = store.load(subject, cycle, 'plan')
        st.caption('After discussing differences, record the actions agreed with your manager.')
        with st.form(f'development_plan_{subject}_{cycle}_{revision(record)}'):
            plan = st.text_area('Agreed actions, goals, deadlines and discussion notes', value=record.get('notes',''), height=200, disabled=actor != subject)
            save = st.form_submit_button('Save development plan', disabled=actor != subject)
        if save: _save(store, actor, subject, cycle, 'plan', {'notes':plan}, record)
    if 'User Administration' in tabs:
        with tabs['User Administration']: administration(configured_accounts())
