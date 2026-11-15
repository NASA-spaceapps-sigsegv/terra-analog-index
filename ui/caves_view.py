"""Tabla de cuevas y tubos de lava (TAI-53), debajo del mapa cuando la capa está prendida.

Cada fila dice en qué puesto del ranking actual está la celda de la cueva. Elegir una fila abre la ficha de
esa celda, igual que el ranking: guarda su cell_id en st.session_state["selected_cell_id"]. La clave del
widget sigue el mismo criterio que la del ranking (ui/ranking_view.py): cambia con el orden de las filas y
con la celda elegida, así la fila marcada siempre es la de la ficha que se ve.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from tai.constants import SCORE_DECIMALS_UI
from ui.ranking_view import NO_DATA, SCROLL_KEY, SELECTED_KEY, table_key

HEADING = "Cuevas y tubos de lava"
CAPTION = (
    "Sitios subterráneos estudiados como análogos de la Luna y Marte. No cambian los puntajes: el puesto y el "
    "total son los de la celda donde cae cada uno. Elegí una fila para ver la ficha de esa celda."
)
ROW_HEIGHT = 84  # entran tres renglones de "Por qué interesa"
HEADER_HEIGHT = 38
TABLE_BORDERS = 3


def table_height(n_rows: int) -> int:
    """Alto exacto para que no haya que desplazarse dentro de la tabla."""
    return HEADER_HEIGHT + n_rows * ROW_HEIGHT + TABLE_BORDERS


def column_config() -> dict:
    return {
        "Cueva": st.column_config.TextColumn("Cueva", width=260),
        "Tipo": st.column_config.TextColumn("Tipo", width=110),
        "Puesto": st.column_config.NumberColumn("Puesto", width=70, help="Puesto de su celda entre todas las elegibles"),
        "Total": st.column_config.ProgressColumn(
            "Total", format=f"%.{SCORE_DECIMALS_UI}f", min_value=0.0, max_value=1.0, width=130
        ),
        "Por qué interesa": st.column_config.TextColumn("Por qué interesa", width="large"),
        "Fuente": st.column_config.TextColumn("Fuente", width=260),
    }


def selected_rows(cell_ids: tuple[int | None, ...], selected: int | None) -> list[int]:
    """La fila a marcar: la primera cueva de la celda elegida. Sin celda elegida, ninguna (aunque haya cuevas
    sin celda: None no es una celda)."""
    if selected is None or selected not in cell_ids:
        return []
    return [cell_ids.index(selected)]


def _on_select(key: str, cell_ids: tuple[int | None, ...]) -> None:
    """Una fila con celda abre su ficha; una sin celda (isla chica) no cambia nada."""
    state = st.session_state.get(key)
    rows = state["selection"]["rows"] if state else []
    if not rows or not 0 <= rows[0] < len(cell_ids) or cell_ids[rows[0]] is None:
        return
    st.session_state[SELECTED_KEY] = cell_ids[rows[0]]
    st.session_state[SCROLL_KEY] = True


def render_caves(table: pd.DataFrame, target_id: str, selected_cell_id: int | None) -> None:
    st.subheader(HEADING)
    cell_ids = tuple(None if pd.isna(c) else int(c) for c in table["cell_id"])
    key = f"{table_key('caves_' + target_id, [c or 0 for c in cell_ids])}_{selected_cell_id}"
    st.dataframe(
        table,
        hide_index=True,
        column_order=[c for c in table.columns if c != "cell_id"],
        column_config=column_config(),
        placeholder=NO_DATA,
        row_height=ROW_HEIGHT,
        height=table_height(len(table)),
        key=key,
        on_select=lambda: _on_select(key, cell_ids),
        selection_mode="single-row",
        selection_default={"selection": {"rows": selected_rows(cell_ids, selected_cell_id)}},
    )
    st.caption(CAPTION)
