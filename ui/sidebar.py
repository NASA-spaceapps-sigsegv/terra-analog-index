"""Sidebar (design 10.2). Draws the controls and returns their state.

It reads no files and computes no scores: it receives the already loaded list of targets.
"""

from dataclasses import dataclass

import streamlit as st

from tai.constants import DEFAULT_WEIGHTS, DIMENSIONS, WEIGHT_STEP
from tai.models import TargetSummary

PROJECTIONS = {"world": "World", "south_pole": "South pole", "north_pole": "North pole"}
WEIGHT_LABELS = {
    "terrain": "Terrain",
    "temperature": "Temperature",
    "water_ice": "Water and ice",
    "dust_wind": "Dust and wind",
    "biology": "Astrobiological interest",
}
BIOLOGY_NOTE = "It does not measure similarity to the target: it measures records of life in extreme environments."
CAVES_HELP = "Underground sites studied as analogs of lava tubes on the Moon and Mars. Informational only: they do not change the scores."
DUST_WIND_NOTE = "Mars only: the Moon has no atmosphere, no wind and no airborne dust."


def weight_key(dim: str) -> str:
    return f"w_{dim}"


@dataclass(frozen=True)
class SidebarState:
    target_id: str
    weights: dict[str, float]
    hide_known: bool
    show_caves: bool  # caves and lava tubes layer (TAI-53), off on open
    projection: str  # world, south_pole, north_pole


def _init_session(target_ids: list[str]) -> None:
    ss = st.session_state
    if ss.get("target_id") not in target_ids:  # first time, or a target that no longer exists
        ss["target_id"] = target_ids[0]
    for dim in DIMENSIONS:
        ss.setdefault(weight_key(dim), DEFAULT_WEIGHTS[dim])
    ss.setdefault("hide_known", False)
    ss.setdefault("show_caves", False)
    ss.setdefault("projection", "world")
    ss.setdefault("selected_cell_id", None)


def _reset_weights() -> None:
    for dim in DIMENSIONS:
        st.session_state[weight_key(dim)] = DEFAULT_WEIGHTS[dim]


def _clear_selection() -> None:
    st.session_state["selected_cell_id"] = None


def render_sidebar(targets: list[TargetSummary]) -> SidebarState:
    labels = {t.target_id: t.label for t in targets}
    _init_session(list(labels))

    with st.sidebar:
        st.header("Terra Analog Index")
        st.radio(
            "Target site",
            options=list(labels),
            format_func=labels.get,
            key="target_id",
            on_change=_clear_selection,  # changing target clears the selected cell
        )

        st.subheader("Weights")
        for dim in DIMENSIONS:
            st.slider(WEIGHT_LABELS[dim], 0.0, 1.0, step=WEIGHT_STEP, key=weight_key(dim))
            if dim == "biology":
                st.caption(BIOLOGY_NOTE)
            elif dim == "dust_wind":
                st.caption(DUST_WIND_NOTE)
        st.button("Reset weights", on_click=_reset_weights)

        st.checkbox("Hide known analogs", key="hide_known")
        st.checkbox("Show caves and lava tubes", key="show_caves", help=CAVES_HELP)
        st.radio("Map view", options=list(PROJECTIONS), format_func=PROJECTIONS.get, key="projection")

    ss = st.session_state
    return SidebarState(
        target_id=ss["target_id"],
        weights={dim: round(float(ss[weight_key(dim)]), 2) for dim in DIMENSIONS},
        hide_known=bool(ss["hide_known"]),
        show_caves=bool(ss["show_caves"]),
        projection=ss["projection"],
    )
