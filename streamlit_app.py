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
from ui import map_view, ranking_view
from ui.ranking_view import SELECTED_KEY
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


def cell_label(bundle: DataBundle, cell_id: int) -> str:
    """Encabezado de la ficha (design 11.1): "Celda 24,5°S 69,5°O · Chile"."""
    if cell_id not in bundle.grid.index:
        raise CellNotFoundError(f"La celda {cell_id} no está en la grilla.")
    row = bundle.grid.loc[cell_id]
    lat = f"{abs(row.lat):.1f}°{'S' if row.lat < 0 else 'N'}".replace(".", ",")
    lon = f"{abs(row.lon):.1f}°{'O' if row.lon < 0 else 'E'}".replace(".", ",")
    country = row.country if isinstance(row.country, str) else None
    return f"Celda {lat} {lon}" + (f" · {country}" if country else "")


def explore_tab(bundle: DataBundle, state: SidebarState) -> None:
    layer = services.get_map_layer(bundle, state.target_id, state.weights)
    map_view.render_map(
        layer, state.projection, st.session_state.get(SELECTED_KEY), show_analogs=not state.hide_known
    )
    left, right = st.columns([4, 6])
    with left:
        st.subheader("Mejores celdas")
        ranking = services.get_ranking(bundle, state.target_id, state.weights, hide_known=state.hide_known)
        ranking_view.render_ranking(ranking, st.session_state.get(SELECTED_KEY))
    with right:
        st.subheader("Ficha")
        selected = st.session_state.get(SELECTED_KEY)
        if selected is None:
            st.info("Elegí una fila del ranking para ver su ficha.")
        else:
            st.markdown(f"**{cell_label(bundle, selected)}**")
            st.caption("La ficha completa llega con TAI-32.")


def main() -> None:
    with handle_tai_errors(fatal=True):
        bundle = get_bundle(str(DATA_DIR), data_signature(DATA_DIR))
        state = render_sidebar(services.list_targets(bundle))

    tab_explore, tab_method = st.tabs(["Explorar", "Método"])
    with tab_explore:
        with handle_tai_errors():
            explore_tab(bundle, state)
    with tab_method:
        st.info("La pestaña Método llega el domingo (TAI-34).")


main()
