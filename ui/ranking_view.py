"""Ranking in the Explore tab (design 10.4, TAI-31).

The card is opened from here, not from the map: picking a row stores its cell_id in
st.session_state["selected_cell_id"].

st.dataframe remembers the selection as a row position, not as a cell. If a slider changes the
order, that position would point at another cell. That is why the widget key depends on the target
and on the order of the cells: a new order is a new widget, which starts with the selected cell's
row checked if it is still in the table. If it left the ranking no row is checked, but
selected_cell_id is kept and the card stays visible (design 10.5).

The cell is stored in a callback, which runs before the rest of the script: the map, drawn above
the ranking, already highlights the new cell in the same run.

The pure functions (table, key, rows) are tested without Streamlit; `render_ranking` draws.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

import pandas as pd
import streamlit as st

from tai.constants import CSV_TOP_N, SCORE_DECIMALS_UI
from tai.tables import COLUMNS, OPTIONAL_COLUMNS, SCORE_COLUMNS, ranking_table, visible_columns  # noqa: F401

if TYPE_CHECKING:
    from tai.models import Ranking

SELECTED_KEY = "selected_cell_id"
NO_DATA = "no data"
EMPTY_FILTER = "No cells are left with this filter."

# Widths in px. The scores get by with the short bar and the number; the rest goes to the analog,
# so the longest name in known_analogs.csv fits (Licancabur).
SCORE_WIDTH = 110
TOTAL_WIDTH = 150
KNOWN_ANALOG_WIDTH = 420

# Picking a row scrolls the page to the card. It happens once: the next run (a slider, for
# example) does not scroll again.
SCROLL_KEY = "scroll_to_card"


def csv_filename(ranking: Ranking, top: int | None = None) -> str:
    """ranking_mars_jezero.csv; with the known-analogs filter, ranking_mars_jezero_no_known.csv.

    With `top`, the long download: ranking_mars_jezero_top2000.csv."""
    size = f"_top{top}" if top else ""
    return f"ranking_{ranking.target_id}{size}{'_no_known' if ranking.hide_known else ''}.csv"


def _utf8_bom(data: str | Callable[[], str]) -> bytes | Callable[[], bytes]:
    """With a BOM, Excel opens the file as UTF-8 and accented names (Río Tinto, Mývatn) show correctly."""
    if callable(data):
        return lambda: data().encode("utf-8-sig")
    return data.encode("utf-8-sig")


def column_config() -> dict:
    fmt = f"%.{SCORE_DECIMALS_UI}f"
    config = {
        c: st.column_config.ProgressColumn(c, format=fmt, min_value=0.0, max_value=1.0, width=SCORE_WIDTH)
        for c in SCORE_COLUMNS
    }
    config["Total"] = st.column_config.ProgressColumn(
        "Total", format=fmt, min_value=0.0, max_value=1.0, width=TOTAL_WIDTH
    )
    config["Lat"] = st.column_config.NumberColumn("Lat", format="%.1f°")
    config["Lon"] = st.column_config.NumberColumn("Lon", format="%.1f°")
    config["Known analog"] = st.column_config.TextColumn("Known analog", width=KNOWN_ANALOG_WIDTH)
    return config


def table_key(target_id: str, cell_ids: Sequence[int]) -> str:
    """Widget key: it changes if the target or the order of the cells changes."""
    digest = hashlib.sha1(",".join(map(str, cell_ids)).encode()).hexdigest()[:12]
    return f"ranking_{target_id}_{digest}"


def default_rows(cell_ids: Sequence[int], selected: int | None) -> list[int]:
    """Row to check when drawing: the selected cell's, if it is in the table."""
    ids = list(cell_ids)
    return [ids.index(selected)] if selected in ids else []


def cell_from_rows(rows: Sequence[int], cell_ids: Sequence[int]) -> int | None:
    """The cell of the picked row; None if it was deselected or the row does not exist."""
    if not rows:
        return None
    row = rows[0]
    return int(cell_ids[row]) if 0 <= row < len(cell_ids) else None


def select_cell(cell_id: int) -> None:
    """Open this cell's card (from a numbered dot on the map) and scroll to it."""
    st.session_state[SELECTED_KEY] = int(cell_id)
    st.session_state[SCROLL_KEY] = True


def _on_select(key: str, cell_ids: tuple[int, ...]) -> None:
    state = st.session_state.get(key)
    rows = state["selection"]["rows"] if state else []
    st.session_state[SELECTED_KEY] = cell_from_rows(rows, cell_ids)
    st.session_state[SCROLL_KEY] = st.session_state[SELECTED_KEY] is not None


def render_ranking(
    ranking: Ranking,
    selected_cell_id: int | None,
    csv_text: str | Callable[[], str] | None = None,
    csv_long: Callable[[], str] | None = None,
) -> None:
    """`csv_text`: the table as CSV (text, or a function that builds it on click). `csv_long`: builds the top-CSV_TOP_N CSV; called only on click."""
    if not ranking.items:
        st.info(EMPTY_FILTER)
        return

    cell_ids = tuple(item.cell_id for item in ranking.items)
    # With the selected cell in the key, the checked row follows the card even when picked from the caves table.
    key = f"{table_key(ranking.target_id, cell_ids)}_{selected_cell_id}"
    table = ranking_table(ranking)
    st.dataframe(
        table,
        hide_index=True,
        column_order=visible_columns(table),
        column_config=column_config(),
        placeholder=NO_DATA,
        key=key,
        on_select=lambda: _on_select(key, cell_ids),
        selection_mode="single-row",
        selection_default={"selection": {"rows": default_rows(cell_ids, selected_cell_id)}},
    )
    st.caption(
        f"The best {len(ranking.items)} of {ranking.total_eligible} eligible cells. "
        "Pick a row to see its card."
    )
    buttons = []
    if csv_text is not None:
        buttons.append(("Download CSV", csv_text, csv_filename(ranking), "The rows of this table"))
    if csv_long is not None:
        buttons.append((f"Download top {CSV_TOP_N:,} (CSV)", csv_long, csv_filename(ranking, CSV_TOP_N),
                        f"The best {CSV_TOP_N:,} eligible cells with the current weights and filter, same columns"))
    if not buttons:
        return
    with st.container(horizontal=True):
        for label, data, name, tip in buttons:
            st.download_button(label, data=_utf8_bom(data), file_name=name, mime="text/csv",
                               icon=":material/download:", help=tip, on_click="ignore")
