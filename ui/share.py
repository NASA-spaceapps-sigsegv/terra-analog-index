"""A link that reopens this exact view (TAI-40): target, weights, selected cell, map view and filters in the address.

`apply_query_params` runs once per session, before the widgets exist, and fills the session from the address.
`sync_query_params` runs at the end of every run and writes the current state back, so copying the address is enough;
the button only does that copy with one click.
"""

from __future__ import annotations

import streamlit as st

from tai.constants import DEFAULT_WEIGHTS, DIMENSIONS, WEIGHT_STEP

LOADED_KEY = "_url_loaded"
COPY_LABEL = "Copy link to this view"
VIEWS = ("world", "south_pole", "north_pole")


def _weights_from(text: str | None) -> dict[str, float] | None:
    """"1,1,1,0.5,0.5" in the order of DIMENSIONS; None if it is not exactly that."""
    try:
        values = [float(v) for v in (text or "").split(",")]
    except ValueError:
        return None
    if len(values) != len(DIMENSIONS) or any(not 0.0 <= v <= 1.0 for v in values):
        return None
    return {dim: round(round(v / WEIGHT_STEP) * WEIGHT_STEP, 2) for dim, v in zip(DIMENSIONS, values, strict=True)}


def apply_query_params(target_ids: list[str]) -> None:
    ss, qp = st.session_state, st.query_params
    if ss.get(LOADED_KEY):
        return
    ss[LOADED_KEY] = True
    if qp.get("t") in target_ids:
        ss["target_id"] = qp.get("t")
    weights = _weights_from(qp.get("w"))
    if weights:
        for dim, value in weights.items():
            ss[f"w_{dim}"] = value
    if qp.get("v") in VIEWS:
        ss["projection"] = qp.get("v")
    ss["hide_known"] = qp.get("k") == "1"
    ss["show_caves"] = qp.get("g") == "1"
    cell = qp.get("c", "")
    if cell.isdigit():
        ss["selected_cell_id"] = int(cell)


def query_params_for(target_id: str, weights: dict[str, float], projection: str, hide_known: bool, show_caves: bool,
                     selected_cell_id: int | None, view: str | None = None) -> dict[str, str]:
    params = {"t": target_id, "w": ",".join(f"{weights.get(d, DEFAULT_WEIGHTS[d]):g}" for d in DIMENSIONS), "v": projection}
    if hide_known:
        params["k"] = "1"
    if show_caves:
        params["g"] = "1"
    if selected_cell_id is not None:
        params["c"] = str(int(selected_cell_id))
    if view:
        params["view"] = view  # a forced phone/desktop layout survives
    return params


def sync_query_params(params: dict[str, str]) -> None:
    if dict(st.query_params) != params:
        st.query_params.from_dict(params)


def render_copy_button() -> None:
    """One click copies the address of this view. It needs a secure page (https or localhost), which both are."""
    st.html(
        f"""
        <button id="tai-copy" type="button" style="font: inherit; font-size: 0.9rem; cursor: pointer; padding: 0.4rem 0.9rem;
          color: inherit; background: transparent; border: 1px solid rgba(128,128,128,0.5); border-radius: 0.5rem;">
          {COPY_LABEL}</button>
        <script>
          (() => {{  // in its own scope: Streamlit runs this script again on every rerun
            const button = document.getElementById("tai-copy");
            if (button) button.onclick = async () => {{
              try {{ await navigator.clipboard.writeText(window.location.href); button.textContent = "Link copied"; }}
              catch (e) {{ button.textContent = "Copy it from the address bar"; }}
              setTimeout(() => {{ button.textContent = {COPY_LABEL!r}; }}, 2200);
            }};
          }})();
        </script>
        """,
        unsafe_allow_javascript=True,
    )
