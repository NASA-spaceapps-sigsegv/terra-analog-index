"""Sidebar (design 10.2). Draws the controls and returns their state.

It computes no scores and reads no data: it receives the already loaded list of targets. The only file it touches is the
logo image shown at the top.
"""

import base64
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import streamlit as st

from tai.constants import DEFAULT_WEIGHTS, DIMENSIONS, WEIGHT_STEP
from tai.models import TargetSummary
from ui import share
from ui.map_view import FOCUS_KEY

PROJECTIONS = {"world": "World", "south_pole": "South pole", "north_pole": "North pole"}
WEIGHT_LABELS = {
    "terrain": "Terrain",
    "temperature": "Temperature",
    "water_ice": "Water and ice",
    "dust_wind": "Dust and wind",
    "biology": "Astrobiological interest",
}
LOGO_PATH = Path(__file__).resolve().parents[1] / "docs" / "img" / "logo" / "logo-dark.svg"
BIOLOGY_NOTE = "It does not measure similarity to the target: it measures records of life in extreme environments."
CAVES_HELP = "Underground sites studied as analogs of lava tubes on the Moon and Mars. Informational only: they do not change the scores."
DUST_WIND_NOTE = "Mars only: the Moon has no atmosphere, no wind and no airborne dust."
# One click sets the five weights (one rerun instead of five). The balanced one is the default, so it is also the reset.
PRESETS = {
    "balanced": ("Default", dict(DEFAULT_WEIGHTS), "The balanced default weights: also what resets the sliders."),
    "physical": ("Physical", {**DEFAULT_WEIGHTS, "biology": 0.0}, "Physical similarity only: astrobiology at 0."),
    "biology": (
        "Biology",
        {"terrain": 0.3, "temperature": 0.3, "water_ice": 0.5, "dust_wind": 0.2, "biology": 1.0},
        "Astrobiological interest first, with the physical dimensions at a lower weight.",
    ),
}


@lru_cache(maxsize=1)
def logo_html() -> str | None:
    """The logo as a plain <img> tag. st.image would add a full-screen button on hover, which a logo does not need."""
    if not LOGO_PATH.is_file():
        return None
    data = base64.b64encode(LOGO_PATH.read_bytes()).decode("ascii")
    return (
        f'<img src="data:image/svg+xml;base64,{data}" alt="Terra Analog Index" '
        'style="display:block;width:100%;height:auto;margin:0 0 0.75rem 0">'
    )


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
    share.apply_query_params(target_ids)  # the first time, what the address says (a shared link) goes first
    if ss.get("target_id") not in target_ids:  # first time, or a target that no longer exists
        ss["target_id"] = target_ids[0]
    for dim in DIMENSIONS:
        ss.setdefault(weight_key(dim), DEFAULT_WEIGHTS[dim])
    ss.setdefault("hide_known", False)
    ss.setdefault("show_caves", False)
    ss.setdefault("projection", "world")
    ss.setdefault("selected_cell_id", None)


def _apply_preset(preset: str) -> None:
    for dim, value in PRESETS[preset][1].items():
        st.session_state[weight_key(dim)] = value


def _clear_selection() -> None:
    st.session_state["selected_cell_id"] = None
    st.session_state.pop(FOCUS_KEY, None)  # and the map goes back to the whole world


def render_sidebar(targets: list[TargetSummary]) -> SidebarState:
    labels = {t.target_id: t.label for t in targets}
    _init_session(list(labels))

    with st.sidebar:
        logo = logo_html()
        if logo:  # logo with the name; the plain title is the fallback if the file is missing
            st.markdown(logo, unsafe_allow_html=True)
        else:
            st.header("Terra Analog Index")
        st.radio(
            "Target site",
            options=list(labels),
            format_func=labels.get,
            key="target_id",
            on_change=_clear_selection,  # changing target clears the selected cell
        )

        st.subheader("Weights")
        for column, (preset, (label, _, tip)) in zip(st.columns(len(PRESETS)), PRESETS.items(), strict=True):
            column.button(label, key=f"preset_{preset}", help=tip, on_click=_apply_preset, args=(preset,), width="stretch")
        for dim in DIMENSIONS:
            st.slider(WEIGHT_LABELS[dim], 0.0, 1.0, step=WEIGHT_STEP, key=weight_key(dim))
            if dim == "biology":
                st.caption(BIOLOGY_NOTE)
            elif dim == "dust_wind":
                st.caption(DUST_WIND_NOTE)

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
