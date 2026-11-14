"""Terra Analog Index: Streamlit entry point.

Stub from TAI-10. TAI-21 replaces it with the real app: load the bundle from
data/processed/ through tai.io (cached with st.cache_resource) and render the
views in ui/. The app never downloads, writes files or calls NCBI.
"""

import streamlit as st

st.set_page_config(page_title="Terra Analog Index", layout="wide")
st.title("Terra Analog Index")
st.info("App skeleton pending (TAI-21).")
