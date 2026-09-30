"""Keep an uploaded analysis source while switching portal tabs in one session."""

import streamlit as st


def retain_upload(uploaded, key: str):
    if uploaded is not None:
        st.session_state[key] = uploaded
        return uploaded
    previous = st.session_state.get(key)
    if previous is not None:
        previous.seek(0)
    return previous
