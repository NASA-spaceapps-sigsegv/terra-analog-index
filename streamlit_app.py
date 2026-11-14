"""Punto de entrada de la app (design 10). Solo lee data/processed/.

Para probar con los datos de prueba:
    TAI_DATA_DIR=tests/fixtures streamlit run streamlit_app.py
"""

import os
from contextlib import contextmanager
from pathlib import Path

import pandas as pd
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
from tai.constants import SCORE_DECIMALS_UI
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
        st.session_state["selected_cell_id"] = None
    except TaiError as err:  # InvalidWeightsError y futuros: error de programación
        st.error(f"{type(err).__name__}: {err.detail}")
        if fatal:
            st.stop()
    else:
        return
    if fatal:
        st.stop()


def ranking_table(ranking) -> pd.DataFrame:
    df = pd.DataFrame([r.model_dump() for r in ranking.rows])
    df = df.rename(
        columns={
            "rank": "Puesto", "lat": "Lat", "lon": "Lon", "country": "País", "total": "Total",
            "terrain": "Terreno", "temperature": "Temperatura", "water_ice": "Agua y hielo",
            "biology": "Astrobiología", "known_analog": "Análogo conocido",
        }
    )
    return df[["Puesto", "Lat", "Lon", "País", "Total", "Terreno", "Temperatura", "Agua y hielo", "Astrobiología", "Análogo conocido"]]


def explore_tab(bundle: DataBundle, state: SidebarState) -> None:
    st.info("El mapa llega el domingo (TAI-30).")
    left, right = st.columns([4, 6])
    with left:
        st.subheader("Mejores celdas")
        ranking = services.get_ranking(bundle, state.target_id, state.weights, hide_known=state.hide_known)
        if not ranking.rows:
            st.info("No quedan celdas con este filtro.")
        else:
            fmt = f"%.{SCORE_DECIMALS_UI}f"
            scores = ["Total", "Terreno", "Temperatura", "Agua y hielo", "Astrobiología"]
            st.dataframe(
                ranking_table(ranking),
                hide_index=True,
                column_config={c: st.column_config.NumberColumn(format=fmt) for c in scores},
            )
    with right:
        st.subheader("Ficha")
        st.info("Elegí una fila del ranking para ver su ficha.")


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
