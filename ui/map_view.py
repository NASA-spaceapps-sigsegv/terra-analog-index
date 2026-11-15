"""Mapa de la pestaña Explorar (design 10.3, TAI-30).

Plotly Scattergeo, no un mapa de teselas: Mercator corta cerca de 85° de latitud y las celdas
antárticas más australes, candidatas naturales a análogo del polo sur lunar, no se verían.
Un marcador cuadrado por celda, en su centro; la selección se hace desde el ranking, no con clic.

`build_figure` solo arma la figura (se prueba sin Streamlit); `render_map` la dibuja.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import plotly.graph_objects as go

if TYPE_CHECKING:
    from tai.models import MapLayer

GRAY = "#c8c8c8"  # celdas sin datos suficientes
SELECTED_COLOR = "#e53935"  # borde de la celda elegida
ANALOG_BORDER = "#ffffff"  # borde de los análogos conocidos
COLORSCALE = "Viridis"
INSUFFICIENT = "Datos insuficientes"
NO_DATA = "sin dato"  # lo que se ve en el cursor si una dimensión es nula

# Tamaño del marcador en píxeles: 1° de longitud ocupa menos en el mapa mundial que en la vista polar.
MARKER_SIZE = {"world": 5, "south_pole": 7, "north_pole": 7}

_GEO_BASE = dict(
    bgcolor="rgba(0,0,0,0)",
    showland=True,
    landcolor="#262a32",
    showocean=True,
    oceancolor="#14171c",
    showcoastlines=True,
    coastlinecolor="#59606b",
    coastlinewidth=0.6,
    showframe=False,
)
_GEO_BY_PROJECTION = {
    "world": dict(projection=dict(type="natural earth")),
    "south_pole": dict(projection=dict(type="orthographic", rotation=dict(lon=0, lat=-90, roll=0))),
    "north_pole": dict(projection=dict(type="orthographic", rotation=dict(lon=0, lat=90, roll=0))),
}

_HOVER_LOCATION = "<b>%{text}</b><br>Lat %{lat:.1f}°, lon %{lon:.1f}°"
_HOVER_SCORES = (
    "<br>Puntaje total: <b>%{customdata[0]:.2f}</b>"
    "<br>Terreno: %{customdata[1]:.2f}"
    "<br>Temperatura: %{customdata[2]:.2f}"
    "<br>Agua y hielo: %{customdata[3]:.2f}"
    "<br>Astrobiología: %{customdata[4]:.2f}"
)


def _place_text(cells) -> np.ndarray:
    """País y, si lo hay, el análogo conocido: es la parte fija del texto al pasar el cursor."""
    country = cells["country"].fillna("Sin país").astype(str)
    analog = cells["known_analog"].fillna("")
    text = country.where(analog == "", country + "<br>Análogo conocido: " + analog)
    return text.to_numpy()


def _scores(cells) -> np.ndarray:
    cols = ["total", "s_terrain", "s_temperature", "s_water_ice", "bio_score"]
    return cells[cols].to_numpy(dtype="float64")


def _marker(size: int, **kwargs) -> dict:
    return dict(symbol="square", size=size, **kwargs)


def _analog_centers(cells) -> tuple[np.ndarray, np.ndarray]:
    """Un punto por análogo conocido: el centro de las celdas que caen dentro de su radio.

    La longitud se promedia como ángulo para no fallar cerca de ±180°.
    """
    lat, lon = [], []
    for _, g in cells[cells["known_analog"].notna()].groupby("known_analog"):
        rad = np.radians(g["lon"].to_numpy(dtype="float64"))
        lat.append(float(g["lat"].mean()))
        lon.append(float(np.degrees(np.arctan2(np.sin(rad).mean(), np.cos(rad).mean()))))
    return np.array(lat), np.array(lon)


def build_figure(layer: MapLayer, projection: str = "world", selected_cell_id: int | None = None) -> go.Figure:
    """Cuatro trazas: sin datos (gris), elegibles (Viridis de 0 a 1), análogos conocidos y la celda elegida."""
    if projection not in _GEO_BY_PROJECTION:
        raise ValueError(f"projection debe ser una de {list(_GEO_BY_PROJECTION)}, no {projection!r}")
    cells = layer.cells
    size = MARKER_SIZE[projection]
    has_total = cells["total"].notna().to_numpy()
    place = _place_text(cells)
    scores = _scores(cells)

    def rows(mask):
        return dict(lat=cells["lat"].to_numpy()[mask], lon=cells["lon"].to_numpy()[mask])

    fig = go.Figure()

    gray = ~has_total
    fig.add_trace(
        go.Scattergeo(
            name=INSUFFICIENT,
            mode="markers",
            **rows(gray),
            text=place[gray],
            marker=_marker(size, color=GRAY, line=dict(width=0)),
            hovertemplate=_HOVER_LOCATION + f"<br>{INSUFFICIENT}<extra></extra>",
            showlegend=True,
        )
    )

    fig.add_trace(
        go.Scattergeo(
            name="Celdas elegibles",
            mode="markers",
            **rows(has_total),
            text=place[has_total],
            customdata=scores[has_total],
            marker=_marker(
                size,
                color=scores[has_total, 0],
                colorscale=COLORSCALE,
                cmin=0,
                cmax=1,
                line=dict(width=0),
                colorbar=dict(title=dict(text="Puntaje total"), thickness=12, len=0.7),
            ),
            hovertemplate=_HOVER_LOCATION + _HOVER_SCORES + "<extra></extra>",
            hovertemplatefallback=NO_DATA,
            showlegend=False,
        )
    )

    # Un anillo blanco por análogo, centrado en sus celdas, en vez de un borde en cada celda: cerca de
    # los polos las celdas vecinas se superponen y sus bordes se fundían en una mancha blanca que
    # tapaba el puntaje. En un símbolo "open" el trazo toma `marker.color`. El texto del cursor del
    # análogo ya sale de la traza de celdas, que lleva su nombre en todas las celdas de su radio.
    a_lat, a_lon = _analog_centers(cells)
    fig.add_trace(
        go.Scattergeo(
            name="Análogo conocido",
            mode="markers",
            lat=a_lat,
            lon=a_lon,
            marker=dict(symbol="circle-open", size=size * 3 + 3, color=ANALOG_BORDER, line=dict(width=2.5)),
            hoverinfo="skip",
            showlegend=True,
        )
    )

    chosen = cells["cell_id"].to_numpy() == selected_cell_id if selected_cell_id is not None else np.zeros(len(cells), bool)
    fig.add_trace(
        go.Scattergeo(
            name="Celda elegida",
            mode="markers",
            **rows(chosen),
            marker=dict(symbol="square-open", size=size * 3 + 7, color=SELECTED_COLOR, line=dict(width=3, color=SELECTED_COLOR)),
            hoverinfo="skip",
            showlegend=False,
        )
    )

    fig.update_geos(**_GEO_BASE, **_GEO_BY_PROJECTION[projection])
    fig.update_layout(
        height=520,
        margin=dict(l=0, r=0, t=28, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0.0),  # sobre el mapa, no sobre la Antártida
        uirevision=projection,  # conserva el zoom al mover pesos; la vista se reinicia al cambiar de proyección
    )
    return fig


def render_map(layer: MapLayer, projection: str, selected_cell_id: int | None) -> None:
    import streamlit as st

    st.plotly_chart(
        build_figure(layer, projection, selected_cell_id),
        width="stretch",
        config={"displaylogo": False, "scrollZoom": True},
    )
