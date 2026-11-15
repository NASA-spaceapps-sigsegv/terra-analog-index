"""Is the visitor on a phone? (TAI-40)

The server never sees the screen width, but the browser says what it is. A phone gets the compact layout: a shorter map
with the color bar below it, one finger scrolls the page and the controls start closed. `?view=phone` or `?view=desktop`
in the address forces one or the other (useful to try the layout from a computer).
"""

from __future__ import annotations

import re

import streamlit as st

_PHONE = re.compile(r"iPhone|iPod|Windows Phone|Android.*Mobile|\bMobi", re.IGNORECASE)


def is_phone() -> bool:
    view = st.query_params.get("view")
    if view in ("phone", "desktop"):
        return view == "phone"
    try:
        agent = st.context.headers.get("User-Agent", "") or ""
    except Exception:  # outside a browser session (tests) there are no headers
        agent = ""
    return bool(_PHONE.search(agent))
