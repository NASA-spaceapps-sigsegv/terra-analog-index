"""Punto de entrada de la app (design 10). Solo lee data/processed/.

Para probar con los datos de prueba:
    TAI_DATA_DIR=tests/fixtures streamlit run streamlit_app.py
"""

import os
from contextlib import contextmanager
from pathlib import Path

import streamlit as st

from tai import services
from tai.errors import (
    CellNotFoundError,
    DataNotAvailableError,
    TargetNotFoundError,
    TaiError,
    ZeroWeightsError,
)
from tai.io import DataBundle, data_signature, load_bundle
from ui import card_view, caves_view, map_view, method_view, ranking_view
from ui.ranking_view import SCROLL_KEY, SELECTED_KEY
from ui.sidebar import SidebarState, render_sidebar

st.set_page_config(page_title="Terra Analog Index", page_icon="🛰️", layout="wide")

DATA_DIR = Path(os.environ.get("TAI_DATA_DIR") or Path(__file__).parent / "data" / "processed")


@st.cache_resource(show_spinner="Cargando datos…")
def get_bundle(path: str, signature: tuple) -> DataBundle:
    """Se carga una vez por proceso. `signature` cambia si se borra o toca un archivo."""
    return load_bundle(path)


@contextmanager
def handle_tai_errors(fatal: bool = False):
    """Único lugar donde la app atrapa TaiError (design 9.3).

    fatal=True: lo que sigue depende de lo que falló, así que la página se corta."""
    try:
        yield
    except DataNotAvailableError as err:
        st.error(f"**No se pueden cargar los datos.** {err.detail}")
        st.stop()
    except ZeroWeightsError:
        st.warning("Subí al menos un peso.")
    except TargetNotFoundError as err:
        st.error(err.detail)
        st.session_state.pop("target_id", None)  # la próxima corrida vuelve al primer objetivo
        if fatal:
            st.stop()
    except CellNotFoundError as err:
        st.warning(err.detail)
        st.session_state[SELECTED_KEY] = None
    except TaiError as err:  # InvalidWeightsError y futuros: error de programación
        st.error(f"{type(err).__name__}: {err.detail}")
        if fatal:
            st.stop()
    else:
        return
    if fatal:
        st.stop()


CARD_HINT = "Elegí una fila del ranking para ver su ficha."
CARD_ANCHOR = "ficha"


def explore_tab(bundle: DataBundle, state: SidebarState) -> None:
    """Mapa arriba; con la capa prendida, la tabla de cuevas; después el ranking y la ficha, todo a lo ancho.

    Cada parte atrapa sus propios errores: con todos los pesos en 0 el ranking avisa y la ficha
    elegida se sigue viendo, con el total nulo."""
    with handle_tai_errors():
        layer = services.get_map_layer(bundle, state.target_id, state.weights)
        caves = services.get_caves(bundle) if state.show_caves else ()
        map_view.render_map(layer, state.projection, st.session_state.get(SELECTED_KEY), caves)
    if state.show_caves:
        with handle_tai_errors():
            table = services.get_caves_table(bundle, state.target_id, state.weights, hide_known=state.hide_known)
            caves_view.render_caves(table, state.target_id, st.session_state.get(SELECTED_KEY))
    st.subheader("Mejores celdas")
    with handle_tai_errors():
        ranking = services.get_ranking(bundle, state.target_id, state.weights, hide_known=state.hide_known)
        csv_text = services.export_ranking_csv(bundle, state.target_id, state.weights, hide_known=state.hide_known)
        ranking_view.render_ranking(ranking, st.session_state.get(SELECTED_KEY), csv_text)
    st.subheader("Ficha", anchor=CARD_ANCHOR)
    with handle_tai_errors():
        selected = st.session_state.get(SELECTED_KEY)
        if selected is None:
            st.info(CARD_HINT)
        else:
            card_view.render_card(services.get_site_card(bundle, selected, state.target_id, state.weights))
    if st.session_state.pop(SCROLL_KEY, False):
        scroll_to(CARD_ANCHOR)


def scroll_to(anchor: str) -> None:
    """Lleva la página hasta el título con ese anchor. Espera un momento para que la ficha ya esté dibujada."""
    st.html(
        f"<script>setTimeout(() => document.getElementById({anchor!r})"
        "?.scrollIntoView({behavior: 'smooth', block: 'start'}), 150);</script>",
        unsafe_allow_javascript=True,
    )


def method_tab(bundle: DataBundle) -> None:
    """Pestaña Método (design 10.7): textos de content/method.md y tablas de los archivos del pipeline."""
    with handle_tai_errors():
        targets = [services.get_target(bundle, t.target_id) for t in services.list_targets(bundle)]
        method_view.render_method(
            services.get_method_text(), targets, services.get_validation(bundle), services.get_manifest(bundle)
        )


def main() -> None:
    with handle_tai_errors(fatal=True):
        bundle = get_bundle(str(DATA_DIR), data_signature(DATA_DIR))
        state = render_sidebar(services.list_targets(bundle))

    tab_explore, tab_method = st.tabs(["Explorar", "Método"])
    with tab_explore:
        explore_tab(bundle, state)
    with tab_method:
        method_tab(bundle)


main()
