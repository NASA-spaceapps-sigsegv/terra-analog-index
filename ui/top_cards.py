"""The five best cells as cards, next to the map (TAI-40).

On a wide screen they sit beside the map, so the best cells are on the first screen; on a phone they stack under it, one
card per cell, instead of a table that does not fit. Each card opens the full card below, like picking its row.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import streamlit as st

if TYPE_CHECKING:
    from tai.models import Ranking

TOP_CARDS = 5
HEADING = f"Top {TOP_CARDS} cells"


def render_top_cards(ranking: Ranking, selected_cell_id: int | None, on_pick: Callable[[int], None],
                     compact: bool = False) -> None:
    """One card per cell. On a wide screen the text and the button share a row; on a phone they are stacked, one under the other."""
    st.markdown(f"##### {HEADING}")
    for item in ranking.items[:TOP_CARDS]:
        is_open = item.cell_id == selected_cell_id
        where = f"{item.lat:.1f}°, {item.lon:.1f}°"
        detail = f"{item.known_analog.name} · {where}" if item.known_analog else where
        title = f"**#{item.rank} · {item.country or 'No country'}** · {item.total:.2f}"
        with st.container(border=True):
            if compact:
                text, action = st.container(), st.container()
                text.markdown(f"{title}  \n:gray[{detail}]")
            else:
                text, action = st.columns([3, 2], vertical_alignment="center", gap="small")
                text.markdown(title)
                text.caption(detail)
            action.button(
                "Shown below" if is_open else "Open card",
                key=f"top_{ranking.target_id}_{item.cell_id}",
                on_click=on_pick,
                args=(item.cell_id,),
                help=f"Open the card of cell #{item.rank}",
                type="primary" if is_open else "secondary",
                icon=":material/check:" if is_open else ":material/open_in_full:",
                width="stretch",
            )
