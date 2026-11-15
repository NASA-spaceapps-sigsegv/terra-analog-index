"""Site card (design 11.1, TAI-32). Draws the SiteCard model; it neither computes nor words anything.

The nine parts, in order: header, manual text, radar, variables table, similar in, different in,
astrobiological interest, limits and sources.

`radar_figure` and `variables_table` are tested without Streamlit; `render_card` draws.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from tai.cards import DIMENSION_LABELS, unit_value
from tai.constants import DIMENSIONS, SCORE_DECIMALS_UI

if TYPE_CHECKING:
    from tai.models import SiteCard

NO_DATA = "no data"
MANUAL_HEADING = "What it is good for in exploration"
LIMITS_HEADING = "Limits no site on Earth replicates"
RADAR_COLOR = "#21918c"  # green from the map's Viridis scale
OTHER_COLOR = "#e8833a"  # the other target in the comparison: orange, which is not in Viridis
RADAR_GRID = "rgba(128,128,128,0.45)"  # semi-transparent gray: visible in light and dark themes
RADAR_TICKS = (0.3, 0.7, 1.0)  # the "different" and "similar" thresholds, and the maximum
# Fixed row height of the variables table, in pixels. st.dataframe only wraps text if the height
# exceeds 64 px (4rem), and it is the same for every row: 84 px fits three lines of "Reading".
VARIABLE_ROW_HEIGHT = 84
# With height="auto" st.dataframe is cut at 400 px and you have to scroll inside the table. The height
# is fixed so that every row fits: 35 px header (2.1875rem), the rows and the 1 px border at the top
# and bottom.
HEADER_HEIGHT = 35
# Starting widths, in pixels. The table takes the full width and each column grows equally to fill it,
# so the sum (725) has to fit in the card column to avoid horizontal scrolling.
# With 260 px or more, the longest "Reading" phrase takes three lines.
COLUMN_WIDTHS = {"Variable": 140, "Earth": 90, "Target": 115, "Score": 120, "Reading": 260}
TABLE_BORDERS = 2


CAVES_HEADING = "Caves and lava tubes in this cell"
CAVES_NOTE = "Studied as analogs of the Moon and Mars. They are informational: they do not change the cell's score."


def table_height(n_rows: int, row_height: int = VARIABLE_ROW_HEIGHT) -> int:
    return HEADER_HEIGHT + n_rows * row_height + TABLE_BORDERS

VARIABLE_COLUMNS = ("Variable", "Earth", "Target", "Score", "Reading")


def _score_text(x: float | None) -> str:
    return NO_DATA if x is None else f"{x:.{SCORE_DECIMALS_UI}f}"


def _present(card: SiteCard) -> set[str]:
    return {v.dimension for v in card.variables} | {"biology"}


def radar_axes(card: SiteCard, dims: Sequence[str] | None = None) -> tuple[list[str], list[float]]:
    """Axis labels and values: one per target dimension (dust and wind only if it has it).

    A null dimension goes at 0 with "(no data)" in the label. `dims`: draw exactly these axes, so two cards can share them."""
    present = _present(card)
    labels, values = [], []
    for dim in DIMENSIONS if dims is None else dims:
        if dims is None and dim not in present:
            continue
        score = getattr(card.scores, dim)
        labels.append(DIMENSION_LABELS[dim] + (f" ({NO_DATA})" if score is None else ""))
        values.append(0.0 if score is None else score)
    return labels, values


def radar_figure(card: SiteCard, other: SiteCard | None = None) -> go.Figure:
    """The radar of the card. With `other` (the same cell for the other target) both polygons share the axes (TAI-40)."""
    dims = None if other is None else [d for d in DIMENSIONS if d in _present(card) | _present(other)]
    labels, values = radar_axes(card, dims)
    hover = "%{theta}: %{r:.2f}<extra></extra>"
    fig = go.Figure(
        go.Scatterpolar(
            r=values + values[:1],  # close the polygon
            theta=labels + labels[:1],
            fill="toself",
            line=dict(color=RADAR_COLOR),
            hovertemplate=hover,
            name=card.header.label if other is None else card.target_label,
        )
    )
    if other is not None:
        _, other_values = radar_axes(other, dims)
        fig.add_trace(
            go.Scatterpolar(
                r=other_values + other_values[:1], theta=labels + labels[:1], fill="toself",
                line=dict(color=OTHER_COLOR, dash="dash"), fillcolor="rgba(232,131,58,0.18)", hovertemplate=hover,
                name=other.target_label,
            )
        )
    fig.update_layout(
        polar=dict(
            # Transparent background: it takes the theme's, so the theme's text (light on dark) is readable.
            bgcolor="rgba(0,0,0,0)",
            radialaxis=dict(
                range=[0, 1],
                tickvals=RADAR_TICKS,
                ticktext=[_score_text(t) for t in RADAR_TICKS],
                # Between Terrain (0°) and Temperature (90°): the numbers sit neither on an axis nor under a vertex.
                angle=45,
                tickangle=0,
                showline=False,
                gridcolor=RADAR_GRID,
                tickfont=dict(size=12),
            ),
            angularaxis=dict(gridcolor=RADAR_GRID, linecolor=RADAR_GRID, tickfont=dict(size=11)),  # small enough for "Water and ice" on a phone
        ),
        showlegend=other is not None,
        legend=dict(orientation="v", yanchor="top", y=1.0, xanchor="left", x=0.0),  # top left: nothing else is drawn there
        height=320,
        margin=dict(l=72, r=72, t=30, b=30),
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def variables_table(card: SiteCard) -> pd.DataFrame:
    rows = []
    for v in card.variables:
        earth = NO_DATA if v.earth_value is None else f"{unit_value(v.earth_value, v.unit)} {v.unit}"
        if v.target_std > 0:
            target = f"{unit_value(v.target_mean, v.unit)} ± {unit_value(v.target_std, v.unit)} {v.unit}"
        else:
            target = f"{unit_value(v.target_mean, v.unit)} {v.unit}"
        rows.append((v.label, earth, target, v.score, v.phrase))
    return pd.DataFrame(rows, columns=list(VARIABLE_COLUMNS))


def _dimension_list(title: str, items, empty_phrase: str | None) -> None:
    st.markdown(f"**{title}**")
    if items:
        st.markdown("\n".join(f"- {d.label} ({_score_text(d.score)})" for d in items))
    else:
        st.caption(empty_phrase)


def render_summary(card: SiteCard, anchor: str) -> None:
    """The selected cell in a few lines for the first screen: its total and its scores as bars. The full card is below."""
    place = card.header.label + (f" · {card.header.country}" if card.header.country else "")
    with st.container(border=True):
        st.markdown(f"**Selected: {place}**  \nTotal vs. {card.target_label}: **{_score_text(card.scores.total)}**")
        for label, value in zip(*radar_axes(card), strict=True):
            st.progress(float(value), text=f"{label}: {value:.{SCORE_DECIMALS_UI}f}")
        st.markdown(f"[Read the full card ↓](#{anchor})")


def render_card(card: SiteCard, other: SiteCard | None = None) -> None:
    """`other`: the same cell for the other target; its polygon is drawn over the radar."""
    # 1. Header
    head, total = st.columns([3, 1])
    with head:
        place = card.header.label + (f" · {card.header.country}" if card.header.country else "")
        st.markdown(f"#### Cell {place}")
        if card.header.known_analog:
            a = card.header.known_analog
            st.markdown(f":blue-badge[Known analog: {a.name}]")
            if a.basis:
                st.caption(a.basis)
    with total:
        st.metric(f"Total vs. {card.target_label}", _score_text(card.scores.total))

    # 2. Manual text
    if card.manual:
        st.markdown(f"##### {MANUAL_HEADING}")
        st.markdown(f"**{card.manual.title}**")
        st.markdown(card.manual.body_md)

    # 3. Radar
    st.plotly_chart(radar_figure(card, other), width="stretch", config={"displayModeBar": False})

    # 4. Variables table
    st.dataframe(
        variables_table(card),
        hide_index=True,
        placeholder=NO_DATA,
        row_height=VARIABLE_ROW_HEIGHT,
        height=table_height(len(card.variables)),
        column_config={
            "Variable": st.column_config.TextColumn("Variable", width=COLUMN_WIDTHS["Variable"]),
            "Earth": st.column_config.TextColumn("Earth", width=COLUMN_WIDTHS["Earth"]),
            "Target": st.column_config.TextColumn("Target", width=COLUMN_WIDTHS["Target"]),
            "Score": st.column_config.ProgressColumn(
                "Score", format=f"%.{SCORE_DECIMALS_UI}f", min_value=0.0, max_value=1.0,
                width=COLUMN_WIDTHS["Score"],
            ),
            "Reading": st.column_config.TextColumn("Reading", width=COLUMN_WIDTHS["Reading"]),
        },
    )
    for note in card.notes:
        st.caption(note)

    # 5 and 6. Similar in, different in
    similar, different = st.columns(2)
    with similar:
        _dimension_list("Similar in", card.similar_in, card.similar_empty_phrase)
    with different:
        _dimension_list("Different in", card.different_in, card.different_empty_phrase)

    # 7. Astrobiological interest
    st.markdown("**Astrobiological interest**")
    st.markdown(card.biology.phrase)
    st.caption(card.biology.sampling_note)

    # 7b. Caves and lava tubes in the cell (TAI-53): informational, it does not change the score
    if card.caves:
        st.markdown(f"**{CAVES_HEADING}**")
        st.markdown("\n".join(
            f"- **{c.name}** ({c.kind_label.lower()}). {c.relevance}. *Source: {c.source}*" for c in card.caves
        ))
        st.caption(CAVES_NOTE)

    # 8. Limits, always
    st.markdown(f"**{LIMITS_HEADING}**")
    st.markdown("\n".join(f"- {limit}" for limit in card.unreplicable))

    # 9. Sources
    with st.expander("Sources", expanded=False):
        labels = {v.variable: v.label for v in card.variables}
        labels |= {"bio_records": "biological records", "bio_types": "extremophile types"}
        lines = []
        for s in card.sources:
            used = ", ".join(dict.fromkeys(labels.get(u, u) for u in s.used_for))
            name = card.biology.source if s.name == "NCBI BioSample" else s.name
            lines.append(f"- {name} — *{used}*")
        st.markdown("\n".join(lines))
