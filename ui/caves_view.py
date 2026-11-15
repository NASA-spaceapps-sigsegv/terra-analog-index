"""Caves and lava tubes table (TAI-53), below the map when the layer is on.

Each row says at which rank of the current ranking the cave's cell sits. Picking a row opens that cell's
card, just like the ranking: it stores its cell_id in st.session_state["selected_cell_id"]. The widget key
follows the same rule as the ranking's (ui/ranking_view.py): it changes with the row order and with the
selected cell, so the checked row is always the one of the card being shown.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from tai.constants import SCORE_DECIMALS_UI
from ui.ranking_view import NO_DATA, SCROLL_KEY, SELECTED_KEY, table_key

HEADING = "Caves and lava tubes"
CAPTION = (
    "Underground sites studied as analogs of the Moon and Mars. They do not change the scores: the rank and "
    "total are those of the cell each one falls in. Pick a row to see that cell's card."
)
ROW_HEIGHT = 84  # fits three lines of "Why it matters"
HEADER_HEIGHT = 38
TABLE_BORDERS = 3


def table_height(n_rows: int) -> int:
    """Exact height so there is no need to scroll inside the table."""
    return HEADER_HEIGHT + n_rows * ROW_HEIGHT + TABLE_BORDERS


def column_config() -> dict:
    return {
        "Cave": st.column_config.TextColumn("Cave", width=260),
        "Type": st.column_config.TextColumn("Type", width=110),
        "Rank": st.column_config.NumberColumn("Rank", width=70, help="Rank of its cell among all eligible cells"),
        "Total": st.column_config.ProgressColumn(
            "Total", format=f"%.{SCORE_DECIMALS_UI}f", min_value=0.0, max_value=1.0, width=130
        ),
        "Why it matters": st.column_config.TextColumn("Why it matters", width="large"),
        "Source": st.column_config.TextColumn("Source", width=260),
    }


def selected_rows(cell_ids: tuple[int | None, ...], selected: int | None) -> list[int]:
    """The row to check: the first cave in the selected cell. With no selected cell, none (even if there are
    caves without a cell: None is not a cell)."""
    if selected is None or selected not in cell_ids:
        return []
    return [cell_ids.index(selected)]


def _on_select(key: str, cell_ids: tuple[int | None, ...]) -> None:
    """A row with a cell opens its card; one without a cell (small island) changes nothing."""
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
