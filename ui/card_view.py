"""Ficha de sitio (design 11.1, TAI-32). Dibuja el modelo SiteCard; no calcula ni redacta.

Las nueve partes, en orden: encabezado, texto manual, radar, tabla de variables, se parece en,
se aleja en, interés astrobiológico, límites y fuentes.

`radar_figure` y `variables_table` se prueban sin Streamlit; `render_card` dibuja.
"""

from __future__ import annotations

import html
from typing import TYPE_CHECKING

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from tai.cards import DIMENSION_LABELS, unit_value
from tai.constants import DIMENSIONS, SCORE_DECIMALS_UI

if TYPE_CHECKING:
    from tai.models import SiteCard

NO_DATA = "sin dato"
MANUAL_HEADING = "Para qué sirve en la exploración"
LIMITS_HEADING = "Límites que ningún sitio terrestre replica"
RADAR_COLOR = "#21918c"  # verde de la escala Viridis del mapa
BAR_FALLBACK = "#E07A3F"  # primaryColor de .streamlit/config.toml, si la opción no está

# La tabla de variables va en HTML y no en st.dataframe: la grilla de st.dataframe solo parte el texto
# si todas las filas tienen la misma altura fija, y la columna "Lectura" necesita que cada fila crezca
# lo que necesite su frase. Los colores usan currentColor para seguir el tema claro u oscuro.
TABLE_CSS = """
<style>
.tai-vars { width: 100%; border-collapse: collapse; font-size: 0.875rem; line-height: 1.35; }
.tai-vars th, .tai-vars td { padding: 0.45rem 0.6rem; text-align: left; vertical-align: top;
  border-bottom: 1px solid color-mix(in srgb, currentColor 15%, transparent); }
.tai-vars th { font-weight: 400; opacity: 0.7; white-space: nowrap; }
.tai-vars td.num { white-space: nowrap; }
.tai-vars td.reading { overflow-wrap: anywhere; }
.tai-bar { display: flex; align-items: center; gap: 0.5rem; min-width: 7rem; }
.tai-bar .track { flex: 1; height: 0.4rem; border-radius: 0.2rem;
  background: color-mix(in srgb, currentColor 15%, transparent); }
.tai-bar .fill { height: 100%; border-radius: 0.2rem; }
.tai-bar .value { font-size: 0.8rem; min-width: 2.2rem; text-align: right; }
</style>
"""

VARIABLE_COLUMNS = ("Variable", "Tierra", "Objetivo", "Puntaje", "Lectura")


def _score_text(x: float | None) -> str:
    return NO_DATA if x is None else f"{x:.{SCORE_DECIMALS_UI}f}".replace(".", ",")


def radar_axes(card: SiteCard) -> tuple[list[str], list[float]]:
    """Etiquetas y valores de los cuatro ejes. Una dimensión nula va en 0 con "(sin dato)" en la etiqueta."""
    labels, values = [], []
    for dim in DIMENSIONS:
        score = getattr(card.scores, dim)
        labels.append(DIMENSION_LABELS[dim] + (f" ({NO_DATA})" if score is None else ""))
        values.append(0.0 if score is None else score)
    return labels, values


def radar_figure(card: SiteCard) -> go.Figure:
    labels, values = radar_axes(card)
    fig = go.Figure(
        go.Scatterpolar(
            r=values + values[:1],  # cerrar el polígono
            theta=labels + labels[:1],
            fill="toself",
            line=dict(color=RADAR_COLOR),
            hovertemplate="%{theta}: %{r:.2f}<extra></extra>",
            name=card.header.label,
        )
    )
    fig.update_layout(
        polar=dict(radialaxis=dict(range=[0, 1], tickvals=[0.3, 0.7, 1.0], angle=90, tickangle=90)),
        showlegend=False,
        height=320,
        margin=dict(l=60, r=60, t=30, b=30),
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


def _bar(score: float | None, color: str) -> str:
    if score is None or score != score:  # nulo o NaN
        return f'<span style="opacity:0.6">{NO_DATA}</span>'
    pct = max(0.0, min(1.0, score)) * 100
    return (
        f'<div class="tai-bar"><div class="track"><div class="fill" style="width:{pct:.0f}%;background:{color}">'
        f'</div></div><span class="value">{_score_text(score)}</span></div>'
    )


def variables_html(card: SiteCard, bar_color: str = BAR_FALLBACK) -> str:
    """La tabla de variables como HTML: el texto largo se parte y la fila crece."""
    df = variables_table(card)
    e = html.escape
    head = "".join(f"<th>{e(c)}</th>" for c in VARIABLE_COLUMNS)
    rows = "".join(
        "<tr>"
        f"<td>{e(r.Variable)}</td><td class=\"num\">{e(r.Tierra)}</td><td class=\"num\">{e(r.Objetivo)}</td>"
        f"<td>{_bar(r.Puntaje, bar_color)}</td><td class=\"reading\">{e(r.Lectura)}</td>"
        "</tr>"
        for r in df.itertuples(index=False)
    )
    return f'{TABLE_CSS}<table class="tai-vars"><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>'


def _dimension_list(title: str, items, empty_phrase: str | None) -> None:
    st.markdown(f"**{title}**")
    if items:
        st.markdown("\n".join(f"- {d.label} ({_score_text(d.score)})" for d in items))
    else:
        st.caption(empty_phrase)


def render_card(card: SiteCard) -> None:
    # 1. Encabezado
    head, total = st.columns([3, 1])
    with head:
        place = card.header.label + (f" · {card.header.country}" if card.header.country else "")
        st.markdown(f"#### Celda {place}")
        if card.header.known_analog:
            a = card.header.known_analog
            st.markdown(f":blue-badge[Análogo conocido: {a.name}]")
            if a.basis:
                st.caption(a.basis)
    with total:
        st.metric(f"Total frente a {card.target_label}", _score_text(card.scores.total))

    # 2. Texto manual
    if card.manual:
        st.markdown(f"##### {MANUAL_HEADING}")
        st.markdown(f"**{card.manual.title}**")
        st.markdown(card.manual.body_md)

    # 3. Radar
    st.plotly_chart(radar_figure(card), width="stretch", config={"displayModeBar": False})

    # 4. Tabla de variables
    st.html(variables_html(card, st.get_option("theme.primaryColor") or BAR_FALLBACK))
    for note in card.notes:
        st.caption(note)

    # 5 y 6. Se parece en, se aleja en
    similar, different = st.columns(2)
    with similar:
        _dimension_list("Se parece en", card.similar_in, card.similar_empty_phrase)
    with different:
        _dimension_list("Se aleja en", card.different_in, card.different_empty_phrase)

    # 7. Interés astrobiológico
    st.markdown("**Interés astrobiológico**")
    st.markdown(card.biology.phrase)
    st.caption(card.biology.sampling_note)

    # 8. Límites, siempre
    st.markdown(f"**{LIMITS_HEADING}**")
    st.markdown("\n".join(f"- {limit}" for limit in card.unreplicable))

    # 9. Fuentes
    with st.expander("Fuentes", expanded=False):
        labels = {v.variable: v.label for v in card.variables}
        labels |= {"bio_records": "registros biológicos", "bio_types": "tipos de extremófilos"}
        lines = []
        for s in card.sources:
            used = ", ".join(dict.fromkeys(labels.get(u, u) for u in s.used_for))
            name = card.biology.source if s.name == "NCBI BioSample" else s.name
            lines.append(f"- {name} — *{used}*")
        st.markdown("\n".join(lines))
