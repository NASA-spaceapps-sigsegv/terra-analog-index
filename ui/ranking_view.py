"""Ranking de la pestaña Explorar (design 10.4, TAI-31).

La ficha se abre desde acá, no desde el mapa: elegir una fila guarda su cell_id en
st.session_state["selected_cell_id"].

st.dataframe recuerda la selección como posición de fila, no como celda. Si un slider cambia el
orden, esa posición apuntaría a otra celda. Por eso la clave del widget depende del objetivo y del
orden de las celdas: un orden nuevo es un widget nuevo, que arranca con la fila de la celda elegida
marcada si sigue en la tabla. Si salió del ranking no se marca ninguna fila, pero selected_cell_id
se conserva y la ficha sigue visible (design 10.5).

La celda se guarda en un callback, que corre antes que el resto del script: el mapa, que se dibuja
arriba del ranking, ya resalta la celda nueva en la misma corrida.

Las funciones puras (tabla, clave, filas) se prueban sin Streamlit; `render_ranking` dibuja.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import TYPE_CHECKING

import pandas as pd
import streamlit as st

from tai.constants import SCORE_DECIMALS_UI

if TYPE_CHECKING:
    from tai.models import Ranking

SELECTED_KEY = "selected_cell_id"
NO_DATA = "sin dato"
EMPTY_FILTER = "No quedan celdas con este filtro."

COLUMNS = {
    "rank": "Puesto",
    "lat": "Lat",
    "lon": "Lon",
    "country": "País",
    "total": "Total",
    "s_terrain": "Terreno",
    "s_temperature": "Temperatura",
    "s_water_ice": "Agua y hielo",
    "bio_score": "Astrobiología",
    "known_analog": "Análogo conocido",
}
SCORE_COLUMNS = ("Total", "Terreno", "Temperatura", "Agua y hielo", "Astrobiología")


def ranking_table(ranking: Ranking) -> pd.DataFrame:
    """Una fila por celda, en el orden del ranking, con los nombres de columna de la interfaz.

    Los puntajes nulos quedan como NaN: la tabla los muestra como "sin dato"."""
    rows = [item.model_dump() for item in ranking.items]
    df = pd.DataFrame(rows, columns=list(COLUMNS))
    df["known_analog"] = [a["name"] if a else None for a in df["known_analog"]]
    for col in ("total", "s_terrain", "s_temperature", "s_water_ice", "bio_score"):
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
    return df.rename(columns=COLUMNS).reset_index(drop=True)


def column_config() -> dict:
    fmt = f"%.{SCORE_DECIMALS_UI}f"
    config = {
        c: st.column_config.ProgressColumn(c, format=fmt, min_value=0.0, max_value=1.0) for c in SCORE_COLUMNS
    }
    config["Lat"] = st.column_config.NumberColumn("Lat", format="%.1f°")
    config["Lon"] = st.column_config.NumberColumn("Lon", format="%.1f°")
    return config


def table_key(target_id: str, cell_ids: Sequence[int]) -> str:
    """Clave del widget: cambia si cambia el objetivo o el orden de las celdas."""
    digest = hashlib.sha1(",".join(map(str, cell_ids)).encode()).hexdigest()[:12]
    return f"ranking_{target_id}_{digest}"


def default_rows(cell_ids: Sequence[int], selected: int | None) -> list[int]:
    """Fila a marcar al dibujar: la de la celda elegida, si está en la tabla."""
    ids = list(cell_ids)
    return [ids.index(selected)] if selected in ids else []


def cell_from_rows(rows: Sequence[int], cell_ids: Sequence[int]) -> int | None:
    """La celda de la fila elegida; None si se deseleccionó o la fila no existe."""
    if not rows:
        return None
    row = rows[0]
    return int(cell_ids[row]) if 0 <= row < len(cell_ids) else None


def _on_select(key: str, cell_ids: tuple[int, ...]) -> None:
    state = st.session_state.get(key)
    rows = state["selection"]["rows"] if state else []
    st.session_state[SELECTED_KEY] = cell_from_rows(rows, cell_ids)


def render_ranking(ranking: Ranking, selected_cell_id: int | None) -> None:
    if not ranking.items:
        st.info(EMPTY_FILTER)
        return

    cell_ids = tuple(item.cell_id for item in ranking.items)
    key = table_key(ranking.target_id, cell_ids)
    st.dataframe(
        ranking_table(ranking),
        hide_index=True,
        column_config=column_config(),
        placeholder=NO_DATA,
        key=key,
        on_select=lambda: _on_select(key, cell_ids),
        selection_mode="single-row",
        selection_default={"selection": {"rows": default_rows(cell_ids, selected_cell_id)}},
    )
    st.caption(
        f"Las {len(ranking.items)} mejores de {ranking.total_eligible} celdas elegibles. "
        "Elegí una fila para ver su ficha."
    )
