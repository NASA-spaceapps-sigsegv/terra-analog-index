"""Mapa de la pestaña Explorar (design 10.3, TAI-30).

Plotly Scattergeo, no un mapa de teselas: Mercator corta cerca de 85° de latitud y las celdas
antárticas más australes, candidatas naturales a análogo del polo sur lunar, no se verían.

Cada celda se dibuja como un cuadrado de 1° de lado (un polígono), no como un marcador: un marcador
tiene tamaño fijo en píxeles y al hacer zoom las celdas quedaban como puntos sueltos con huecos.
Los polígonos se agrupan en 64 intervalos de color (una traza por intervalo), así son 64 trazas y
no 21 000; el mapa dibuja en unos 2 s en vez de los 5 s de una coropleta con GeoJSON. Los vértices
van en sentido horario: es el que espera d3-geo, y con el contrario las vistas polares se rellenan
enteras. Encima van marcadores transparentes que solo sirven para el texto del cursor.

La selección se hace desde el ranking, no con clic en el mapa.

`build_figure` solo arma la figura (se prueba sin Streamlit); `render_map` la dibuja.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import plotly.colors as pc
import plotly.graph_objects as go

from tai.constants import GRID_RES_DEG

if TYPE_CHECKING:
    from tai.models import MapLayer

GRAY = "#c8c8c8"  # celdas sin datos suficientes
SELECTED_COLOR = "#e53935"  # contorno de la celda elegida
ANALOG_BORDER = "#ffffff"  # anillo de los análogos conocidos
COLORSCALE = "Viridis"
INSUFFICIENT = "Datos insuficientes"
NO_DATA = "sin dato"  # lo que se ve en el cursor si una dimensión es nula
N_BINS = 64  # intervalos de color entre 0 y 1: 1/64 de diferencia no se distingue a simple vista
HOVER_FILL = "rgba(0,0,0,0)"  # transparente: el cursor se calcula con la posición de los datos, no con lo que se ve.
# (Con un alfa de 0,004 se probó y era un error: cerca de los polos se superponen cientos de marcadores y sus alfas
# se suman hasta oscurecer la vista polar, con un agujero negro y anillos concéntricos.)

# Tamaño en píxeles de los marcadores del cursor y de los anillos; las celdas en sí son polígonos.
MARKER_SIZE = {"world": 5, "south_pole": 7, "north_pole": 7}
POLE_LIMIT = 89.99  # latitud máxima de un vértice (ver _squares)
OVERLAP_DEG = 0.08  # cuánto se agranda cada cuadrado (en arco) para que vecinos se superpongan y no queden costuras
MAX_LON_OVERLAP_DEG = 0.8  # tope de ese agrandamiento a lo ancho, que crece hacia los polos (los meridianos convergen)

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

_BIN_COLORS = pc.sample_colorscale(COLORSCALE, [(k + 0.5) / N_BINS for k in range(N_BINS)])


def _place_text(cells) -> np.ndarray:
    """País y, si lo hay, el análogo conocido: es la parte fija del texto al pasar el cursor."""
    country = cells["country"].fillna("Sin país").astype(str)
    analog = cells["known_analog"].fillna("")
    text = country.where(analog == "", country + "<br>Análogo conocido: " + analog)
    return text.to_numpy()


def _scores(cells) -> np.ndarray:
    cols = ["total", "s_terrain", "s_temperature", "s_water_ice", "bio_score"]
    return cells[cols].to_numpy(dtype="float64")


def _squares(lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Los cuadrados de 1° centrados en (lat, lon), como una línea con NaN entre un cuadrado y otro.

    Vértices en sentido horario: SO, NO, NE, SE y de nuevo SO.
    """
    half = GRID_RES_DEG / 2 + OVERLAP_DEG  # un poco más que media celda: ver OVERLAP_DEG
    lat = np.asarray(lat, dtype="float64")
    lon = np.asarray(lon, dtype="float64")
    gap = np.full(len(lat), np.nan)
    # Las celdas de 89° a 90° convergen en el polo: con el vértice justo en 90° la vista polar deja un agujero
    # negro y anillos concéntricos. Quedarse a 0,01° del polo (un kilómetro) lo evita sin que se note.
    south = np.clip(lat - half, -POLE_LIMIT, POLE_LIMIT)
    north = np.clip(lat + half, -POLE_LIMIT, POLE_LIMIT)
    # A lo ancho, el mismo agrandamiento medido en arco: un grado de longitud mide cos(lat) grados de arco.
    wide = GRID_RES_DEG / 2 + np.minimum(OVERLAP_DEG / np.maximum(np.cos(np.radians(lat)), 1e-6), MAX_LON_OVERLAP_DEG)
    west, east = lon - wide, lon + wide
    lons = np.stack([west, west, east, east, west, gap], axis=1).ravel()
    lats = np.stack([south, north, north, south, south, gap], axis=1).ravel()
    return lats, lons


def _fill_trace(name: str, lat, lon, color: str, *, showlegend: bool = False) -> go.Scattergeo:
    lats, lons = _squares(lat, lon)
    return go.Scattergeo(
        name=name,
        mode="lines",
        lat=lats,
        lon=lons,
        fill="toself",
        fillcolor=color,
        line=dict(width=1.0, color=color),  # el trazo del mismo color tapa las costuras entre celdas vecinas
        hoverinfo="skip",
        showlegend=showlegend,
    )


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
    """Celdas como cuadrados de 1°: sin datos en gris, el resto en Viridis de 0 a 1; encima, los anillos
    de los análogos conocidos y la celda elegida."""
    if projection not in _GEO_BY_PROJECTION:
        raise ValueError(f"projection debe ser una de {list(_GEO_BY_PROJECTION)}, no {projection!r}")
    cells = layer.cells
    size = MARKER_SIZE[projection]
    lat = cells["lat"].to_numpy(dtype="float64")
    lon = cells["lon"].to_numpy(dtype="float64")
    total = cells["total"].to_numpy(dtype="float64")
    has_total = ~np.isnan(total)
    place = _place_text(cells)
    scores = _scores(cells)

    fig = go.Figure()

    # 1) Relleno: los cuadrados de 1°. Primero los grises, debajo del resto.
    gray = ~has_total
    fig.add_trace(_fill_trace(INSUFFICIENT, lat[gray], lon[gray], GRAY, showlegend=True))
    bins = np.clip((np.where(has_total, total, 0) * N_BINS).astype(int), 0, N_BINS - 1)
    for k in range(N_BINS):
        in_bin = has_total & (bins == k)
        if in_bin.any():
            lo, hi = k / N_BINS, (k + 1) / N_BINS
            fig.add_trace(_fill_trace(f"Puntaje {lo:.2f} a {hi:.2f}", lat[in_bin], lon[in_bin], _BIN_COLORS[k]))

    # 2) Cursor: un marcador transparente por celda, con el texto. En las celdas sin datos dice "Datos insuficientes".
    hover_marker = dict(symbol="square", size=size + 2, color=HOVER_FILL, line=dict(width=0))
    fig.add_trace(
        go.Scattergeo(
            name=INSUFFICIENT + " (cursor)",
            mode="markers",
            lat=lat[gray],
            lon=lon[gray],
            text=place[gray],
            marker=hover_marker,
            hovertemplate=_HOVER_LOCATION + f"<br>{INSUFFICIENT}<extra></extra>",
            showlegend=False,
        )
    )
    fig.add_trace(
        go.Scattergeo(
            name="Celdas elegibles",
            mode="markers",
            lat=lat[has_total],
            lon=lon[has_total],
            text=place[has_total],
            customdata=scores[has_total],
            marker=hover_marker,
            hovertemplate=_HOVER_LOCATION + _HOVER_SCORES + "<extra></extra>",
            hovertemplatefallback=NO_DATA,
            showlegend=False,
        )
    )

    # 3) Barra de color: una traza de un punto fuera del mapa que solo aporta la escala.
    fig.add_trace(
        go.Scattergeo(
            name="Puntaje total",
            mode="markers",
            lat=[None],
            lon=[None],
            marker=dict(
                color=[0.0],
                colorscale=COLORSCALE,
                cmin=0,
                cmax=1,
                showscale=True,
                colorbar=dict(title=dict(text="Puntaje total"), thickness=12, len=0.7),
            ),
            hoverinfo="skip",
            showlegend=False,
        )
    )

    # 4) Un anillo blanco por análogo, centrado en sus celdas. El nombre sale del cursor de las celdas.
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

    # 5) Celda elegida: su contorno (que escala con el zoom) y un marcador más grande que el anillo para
    # que se vea también en el mapa mundial.
    chosen = cells["cell_id"].to_numpy() == selected_cell_id if selected_cell_id is not None else np.zeros(len(cells), bool)
    c_lats, c_lons = _squares(lat[chosen], lon[chosen])
    fig.add_trace(
        go.Scattergeo(
            name="Contorno de la celda elegida",
            mode="lines",
            lat=c_lats,
            lon=c_lons,
            line=dict(width=2.5, color=SELECTED_COLOR),
            hoverinfo="skip",
            showlegend=False,
        )
    )
    fig.add_trace(
        go.Scattergeo(
            name="Celda elegida",
            mode="markers",
            lat=lat[chosen],
            lon=lon[chosen],
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
        hoverlabel=dict(align="left"),
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
