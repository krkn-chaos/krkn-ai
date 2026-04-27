import streamlit as st


def render_config(config_data):
    st.header("Krkn-AI Configuration")
    if config_data:
        st.json(config_data)
    else:
        st.write("Configuration file not found.")
