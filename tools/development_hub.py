"""Administrator-only quality procedure reference library."""
from tools.br_datetime import br_frame, br_date, br_datetime
import json
from pathlib import Path

import pandas as pd
import streamlit as st

from tools.access_control import is_admin_session


def documents():
    path = Path(__file__).resolve().parents[1] / 'assets/development_documents.json'
    return json.loads(path.read_text(encoding='utf-8'))


def render():
    from tools.development_assessment_ui import render as render_assessment
    render_assessment(documents())


def render_catalog():
    records = documents()
    st.markdown("<div class='smart-report-title'>Development Hub</div><div class='smart-report-subtitle'>Quality specialist procedures and work instructions.</div>", unsafe_allow_html=True)
    st.html("<span style='display:inline-block;background:#E7EEFF;color:#2354AA;border:1px solid #B7CEF0;border-radius:6px;padding:4px 10px;font-size:12px;font-weight:600;'>Administrator only</span>")
    st.html("<style>.st-key-development_filters{background:#E8F1FF;border:1px solid #B7CEF0;border-left:4px solid #2563EB;border-radius:8px;padding:10px 16px;}</style>")
    with st.container(key='development_filters'):
        first, second = st.columns([1, 3])
        with first:
            area = st.selectbox('Area', ['All areas', 'SMT', 'Assembly', 'IQC', 'Lab'], key='development_area', persist_state='session')
        with second:
            search = st.text_input('Search document title', placeholder='Search procedures and work instructions...', key='development_search', persist_state='session')
    st.caption('86 documents · 3 job manuals and 83 process documents · IQC corresponds to Material in the source list.')
    kind = st.radio('Document type', ['Process Documents', 'Job Manuals'], horizontal=True, label_visibility='collapsed', key='development_type', persist_state='session')
    selected = [item for item in records if item['type'] == kind
                and (area == 'All areas' or area in item['areas'])
                and search.strip().casefold() in item['title'].casefold()]
    rows = [{'No.': item['number'], 'Document title': item['title'], 'Document': item['url'],
             **{name: '✓' if name in item['areas'] else '—' for name in ['SMT', 'Assembly', 'IQC', 'Lab']}}
            for item in selected]
    frame = pd.DataFrame(rows, columns=['No.', 'Document title', 'Document', 'SMT', 'Assembly', 'IQC', 'Lab'])
    st.dataframe(br_frame(frame), hide_index=True, width='stretch', height=608, row_height=37,
        column_config={
            'No.': st.column_config.NumberColumn(width=55, alignment='center', format='%d'),
            'Document title': st.column_config.TextColumn(width=765),
            'Document': st.column_config.LinkColumn(display_text='Open document', width=120),
            **{name: st.column_config.TextColumn(width=90, alignment='center') for name in ['SMT', 'Assembly', 'IQC', 'Lab']}})
    st.caption(f'{len(selected)} documents shown · ✓ Applicable · — Not marked in the source list')
    st.caption('Document links open the Vivo system and use your existing access permissions. Four documents have no link in the source list.')
