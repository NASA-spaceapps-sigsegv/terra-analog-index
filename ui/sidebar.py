"""Barra lateral (design 10.2). Dibuja los controles y devuelve su estado.

No lee archivos ni calcula puntajes: recibe la lista de objetivos ya cargada.
"""

from dataclasses import dataclass

import streamlit as st

from tai.constants import DEFAULT_WEIGHTS, DIMENSIONS, WEIGHT_STEP
from tai.models import TargetSummary

PROJECTIONS = {"world": "Mundo", "south_pole": "Polo sur", "north_pole": "Polo norte"}
WEIGHT_LABELS = {
    "terrain": "Terreno",
    "temperature": "Temperatura",
    "water_ice": "Agua y hielo",
    "dust_wind": "Polvo y viento",
    "biology": "Interés astrobiológico",
}
BIOLOGY_NOTE = "No mide parecido con el objetivo: mide registros de vida en ambientes extremos."
CAVES_HELP = "Sitios subterráneos estudiados como análogos de los tubos de lava de la Luna y Marte. Solo informativos: no cambian los puntajes."
DUST_WIND_NOTE = "Solo Marte: la Luna no tiene atmósfera, ni viento ni polvo en suspensión."


def weight_key(dim: str) -> str:
    return f"w_{dim}"


@dataclass(frozen=True)
class SidebarState:
    target_id: str
    weights: dict[str, float]
    hide_known: bool
    show_caves: bool  # capa de cuevas y tubos de lava (TAI-53), apagada al abrir
    projection: str  # world, south_pole, north_pole


def _init_session(target_ids: list[str]) -> None:
    ss = st.session_state
    if ss.get("target_id") not in target_ids:  # primera vez, o un objetivo que ya no existe
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
            "Sitio objetivo",
            options=list(labels),
            format_func=labels.get,
            key="target_id",
            on_change=_clear_selection,  # cambiar de objetivo limpia la celda elegida
        )

        st.subheader("Pesos")
        for dim in DIMENSIONS:
            st.slider(WEIGHT_LABELS[dim], 0.0, 1.0, step=WEIGHT_STEP, key=weight_key(dim))
            if dim == "biology":
                st.caption(BIOLOGY_NOTE)
            elif dim == "dust_wind":
                st.caption(DUST_WIND_NOTE)
        st.button("Restablecer pesos", on_click=_reset_weights)

        st.checkbox("Ocultar análogos conocidos", key="hide_known")
        st.checkbox("Mostrar cuevas y tubos de lava", key="show_caves", help=CAVES_HELP)
        st.radio("Vista del mapa", options=list(PROJECTIONS), format_func=PROJECTIONS.get, key="projection")

    ss = st.session_state
    return SidebarState(
        target_id=ss["target_id"],
        weights={dim: round(float(ss[weight_key(dim)]), 2) for dim in DIMENSIONS},
        hide_known=bool(ss["hide_known"]),
        show_caves=bool(ss["show_caves"]),
        projection=ss["projection"],
    )
