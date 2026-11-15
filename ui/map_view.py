"""Mapa de la pestaña Explorar (design 10.3, TAI-30).

Las celdas se pintan como una imagen, no como miles de formas vectoriales. Con una traza Scattergeo
(un marcador o un polígono por celda) arrastrar o hacer zoom redibujaba unos 21 000 elementos SVG y el
mapa iba a 2 o 3 cuadros por segundo. Una imagen la compone el navegador en la GPU: mover y ampliar el
mapa es continuo, y al ampliar las celdas siguen siendo cuadrados sin huecos.

- Mundo: un Heatmap de 180 × 360 en ejes de longitud y latitud (proyección equirrectangular). Un píxel
  es una celda, así que el zoom muestra cuadrados exactos, y el texto del cursor viene incluido.
- Polo sur y Polo norte: una imagen PNG calculada con la proyección ortográfica centrada en el polo
  (cada píxel busca su celda), con marcadores WebGL transparentes encima para el texto del cursor.
  Mercator no sirve: corta cerca de 85° y las celdas antárticas más australes no se verían.

La selección se hace desde el ranking, no con clic en el mapa.

`build_figure` solo arma la figura (se prueba sin Streamlit); `render_map` la dibuja.
"""

from __future__ import annotations

import base64
import struct
import zlib
from typing import TYPE_CHECKING

import numpy as np
import plotly.colors as pc
import plotly.graph_objects as go

from tai.constants import GRID_RES_DEG, N_LAT, N_LON

if TYPE_CHECKING:
    from tai.models import MapLayer

GRAY = "#c8c8c8"  # celdas sin datos suficientes
OCEAN = "#14171c"
SELECTED_COLOR = "#e53935"  # contorno de la celda elegida
ANALOG_BORDER = "#ffffff"  # anillo de los análogos conocidos
COLORSCALE = "Viridis"
INSUFFICIENT = "Datos insuficientes"
NO_DATA = "sin dato"  # lo que se ve en el cursor si una dimensión es nula
HOVER_FILL = "rgba(0,0,0,0)"  # marcadores del cursor: el cursor usa la posición de los datos, no lo que se ve
POLAR_PX = 900  # lado de la imagen de las vistas polares, en píxeles (una celda ocupa varios)
RING_SIZE = 20
SELECTED_SIZE = 28

PROJECTIONS = ("world", "south_pole", "north_pole")
_HEMISPHERE = {"south_pole": -1, "north_pole": 1}

_HOVER_ROW = "<b>%{text}</b><br>Lat %{y:.1f}°, lon %{x:.1f}°"


def _viridis_lut() -> np.ndarray:
    """256 colores RGB de la escala, para pintar la imagen sin pasar por Plotly."""
    colors = pc.sample_colorscale(COLORSCALE, [i / 255 for i in range(256)])
    return np.array([[int(v) for v in c[4:-1].split(",")] for c in colors], dtype=np.uint8)


_LUT = _viridis_lut()
_GRAY_RGB = np.array([int(GRAY[i : i + 2], 16) for i in (1, 3, 5)], dtype=np.uint8)
_OCEAN_RGB = np.array([int(OCEAN[i : i + 2], 16) for i in (1, 3, 5)], dtype=np.uint8)


# --- Celdas y texto del cursor -------------------------------------------------


def _index(lat, lon) -> tuple[np.ndarray, np.ndarray]:
    """Fila y columna de la grilla de 1° de cada celda, a partir de su centro."""
    li = np.floor(np.asarray(lat, dtype="float64") / GRID_RES_DEG + N_LAT / 2).astype(int)
    lj = np.floor(np.asarray(lon, dtype="float64") / GRID_RES_DEG + N_LON / 2).astype(int)
    return np.clip(li, 0, N_LAT - 1), np.clip(lj, 0, N_LON - 1)


def _grid(li, lj, values, fill=np.nan, dtype="float64") -> np.ndarray:
    out = np.full((N_LAT, N_LON), fill, dtype=dtype)
    out[li, lj] = values
    return out


def _scores_text(cells) -> np.ndarray:
    """"<br>Terreno: 0.62<br>…": lo que no depende de los pesos, listo para el cursor."""

    def two(col):
        v = cells[col].to_numpy(dtype="float64")
        return np.where(np.isnan(v), NO_DATA, np.char.mod("%.2f", v))

    return (
        np.char.add("<br>Terreno: ", two("s_terrain"))
        + np.char.add("<br>Temperatura: ", two("s_temperature"))
        + np.char.add("<br>Agua y hielo: ", two("s_water_ice"))
        + np.char.add("<br>Astrobiología: ", two("bio_score"))
    )


def _place_text(cells) -> np.ndarray:
    """País y, si lo hay, el análogo conocido: el encabezado del cursor."""
    country = cells["country"].fillna("Sin país").astype(str)
    analog = cells["known_analog"].fillna("")
    return country.where(analog == "", country + "<br>Análogo conocido: " + analog).to_numpy()


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


def _cell_outline(lat: float, lon: float, steps: int = 1) -> tuple[np.ndarray, np.ndarray]:
    """El cuadrado de 1° centrado en (lat, lon), cerrado, con `steps` tramos por lado."""
    h = GRID_RES_DEG / 2
    t = np.linspace(0.0, 1.0, steps + 1)
    south, north, west, east = lat - h, lat + h, lon - h, lon + h
    lats = np.concatenate([south + 2 * h * t, np.full(steps, north), north - 2 * h * t[1:], np.full(steps - 1, south)])
    lons = np.concatenate([np.full(steps + 1, west), west + 2 * h * t[1:], np.full(steps, east), east - 2 * h * t[1:-1]])
    n = min(len(lats), len(lons))
    return np.append(lats[:n], lats[0]), np.append(lons[:n], lons[0])


# --- Proyección polar ortográfica ----------------------------------------------


def _project(lat, lon, hemisphere: int) -> tuple[np.ndarray, np.ndarray]:
    """(x, y) en el disco unitario de una vista ortográfica centrada en el polo.

    Sur: el meridiano 0 hacia arriba y el este en sentido horario. Norte: el meridiano 0 hacia abajo y el
    este en sentido antihorario, como en Scattergeo con la misma rotación.
    """
    rho = np.cos(np.radians(np.asarray(lat, dtype="float64")))
    lam = np.radians(np.asarray(lon, dtype="float64"))
    sign = 1.0 if hemisphere < 0 else -1.0
    return rho * np.sin(lam), sign * rho * np.cos(lam)


def _png_uri(rgba: np.ndarray) -> str:
    """PNG RGBA de 8 bits como data URI, sin depender de Pillow."""
    h, w, _ = rgba.shape
    raw = np.concatenate([np.zeros((h, 1), np.uint8), rgba.reshape(h, w * 4)], axis=1).tobytes()  # filtro 0 por fila

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 3))
        + chunk(b"IEND", b"")
    )
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def _polar_image(total_grid: np.ndarray, painted: np.ndarray, hemisphere: int) -> str:
    """Imagen del polo: cada píxel del disco busca la celda de 1° que le toca.

    `total_grid` tiene el total (NaN donde no hay valor) y `painted` dice dónde hay celda; las que tienen
    celda pero no total salen en gris, y donde no hay celda (el mar) queda transparente.
    """
    axis = (np.arange(POLAR_PX) + 0.5) / POLAR_PX * 2 - 1
    x, y = np.meshgrid(axis, -axis)  # la primera fila de la imagen es la de arriba, y = +1
    rho = np.hypot(x, y)
    inside = rho <= 1
    lat = hemisphere * np.degrees(np.arccos(np.clip(rho, 0, 1)))
    lon = np.degrees(np.arctan2(x, y if hemisphere < 0 else -y))
    li, lj = _index(lat, lon)
    lj = np.floor(lon + N_LON / 2).astype(int) % N_LON
    total = total_grid[li, lj]
    rgba = np.zeros((POLAR_PX, POLAR_PX, 4), dtype=np.uint8)
    rgba[inside, :3] = _OCEAN_RGB  # el mar del disco, opaco: las imágenes de Plotly quedan debajo de las demás trazas
    rgba[inside, 3] = 255
    has_total = inside & ~np.isnan(total)
    rgba[has_total, :3] = _LUT[np.clip(np.rint(total[has_total] * 255), 0, 255).astype(int)]
    gray = inside & painted[li, lj] & np.isnan(total)
    rgba[gray, :3] = _GRAY_RGB
    # Plotly pone la primera fila de la imagen en y0 y sigue hacia arriba: se la da vuelta para que el sur quede abajo.
    return _png_uri(rgba[::-1].copy())


def _globe_outline(hemisphere: int) -> go.Scatter:
    """El borde del globo y una cuadrícula tenue cada 30°, para dar contexto sin mapa de fondo."""
    t = np.radians(np.linspace(0, 360, 181))
    xs, ys = [np.sin(t)], [np.cos(t)]
    for lat in (hemisphere * 30.0, hemisphere * 60.0):  # paralelos
        r = np.cos(np.radians(lat))
        xs += [np.array([np.nan]), r * np.sin(t)]
        ys += [np.array([np.nan]), r * np.cos(t)]
    for lon in range(0, 360, 30):  # meridianos
        x, y = _project(np.array([0.0, hemisphere * 89.9]), np.array([lon, lon]), hemisphere)
        xs += [np.array([np.nan]), x]
        ys += [np.array([np.nan]), y]
    return go.Scatter(
        x=np.concatenate(xs), y=np.concatenate(ys), mode="lines", line=dict(width=0.6, color="rgba(255,255,255,0.14)"),
        hoverinfo="skip", showlegend=False,
    )


# --- Trazas comunes -------------------------------------------------------------


def _colorbar_trace() -> go.Scatter:
    """Barra de color de las vistas polares: una traza de un punto fuera del mapa que solo aporta la escala."""
    return go.Scatter(
        x=[None],
        y=[None],
        mode="markers",
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
        name="Puntaje total",
    )


def _legend_gray_trace() -> go.Scatter:
    return go.Scatter(
        x=[None], y=[None], mode="markers", marker=dict(symbol="square", size=10, color=GRAY), name=INSUFFICIENT,
        hoverinfo="skip", showlegend=True,
    )


def _rings_trace(x, y) -> go.Scatter:
    return go.Scatter(
        x=x, y=y, mode="markers", name="Análogo conocido",
        marker=dict(symbol="circle-open", size=RING_SIZE, color=ANALOG_BORDER, line=dict(width=2.5)),
        hoverinfo="skip", showlegend=True,
    )


def _selected_traces(x_outline, y_outline, x, y) -> list[go.Scatter]:
    """La celda elegida: su contorno, que escala con el zoom, y un marcador más grande que el anillo."""
    return [
        go.Scatter(
            x=x_outline, y=y_outline, mode="lines", name="Contorno de la celda elegida",
            line=dict(width=2.5, color=SELECTED_COLOR), hoverinfo="skip", showlegend=False,
        ),
        go.Scatter(
            x=x, y=y, mode="markers", name="Celda elegida",
            marker=dict(symbol="square-open", size=SELECTED_SIZE, color=SELECTED_COLOR, line=dict(width=3, color=SELECTED_COLOR)),
            hoverinfo="skip", showlegend=False,
        ),
    ]


# --- Figura ---------------------------------------------------------------------


def _world(fig: go.Figure, cells, selected_cell_id) -> None:
    lat = cells["lat"].to_numpy(dtype="float64")
    lon = cells["lon"].to_numpy(dtype="float64")
    total = cells["total"].to_numpy(dtype="float64")
    has_total = ~np.isnan(total)
    li, lj = _index(lat, lon)
    head = _place_text(cells)

    xs = np.arange(N_LON) * GRID_RES_DEG - 180 + GRID_RES_DEG / 2
    ys = np.arange(N_LAT) * GRID_RES_DEG - 90 + GRID_RES_DEG / 2

    # Sin datos: una capa gris, debajo, solo si hay celdas así (con los datos reales no hay ninguna y se ahorra
    # un megabyte). Solo hay cursor donde hay celda (hoverongaps=False).
    gray = ~has_total
    if gray.any():
        fig.add_trace(
            go.Heatmap(
                name=INSUFFICIENT, x=xs, y=ys, z=_grid(li[gray], lj[gray], 1.0), zmin=0, zmax=1,
                colorscale=[[0, GRAY], [1, GRAY]], showscale=False, hoverongaps=False,
                text=_grid(li[gray], lj[gray], head[gray], fill="", dtype=object),
                hovertemplate=_HOVER_ROW + f"<br>{INSUFFICIENT}<extra></extra>",
            )
        )
    fig.add_trace(
        go.Heatmap(
            name="Celdas elegibles", x=xs, y=ys, z=_grid(li[has_total], lj[has_total], total[has_total]), zmin=0, zmax=1,
            colorscale=COLORSCALE, hoverongaps=False,
            text=_grid(li[has_total], lj[has_total], head[has_total], fill="", dtype=object),
            customdata=_grid(li[has_total], lj[has_total], _scores_text(cells)[has_total], fill="", dtype=object),
            hovertemplate=_HOVER_ROW + "<br>Puntaje total: <b>%{z:.2f}</b>%{customdata}<extra></extra>",
            colorbar=dict(title=dict(text="Puntaje total"), thickness=12, len=0.7),
        )
    )
    if gray.any():
        fig.add_trace(_legend_gray_trace())

    a_lat, a_lon = _analog_centers(cells)
    fig.add_trace(_rings_trace(a_lon, a_lat))

    chosen = cells["cell_id"].to_numpy() == selected_cell_id if selected_cell_id is not None else np.zeros(len(cells), bool)
    if chosen.any():
        o_lat, o_lon = _cell_outline(float(lat[chosen][0]), float(lon[chosen][0]))
    else:
        o_lat = o_lon = np.array([])
    for t in _selected_traces(o_lon, o_lat, lon[chosen], lat[chosen]):
        fig.add_trace(t)

    ticks_x = list(range(-180, 181, 60))
    fig.update_xaxes(
        range=[-180, 180], tickvals=ticks_x, constrain="domain", showgrid=True, gridcolor="rgba(255,255,255,0.07)",
        ticktext=[f"{abs(v)}°{'O' if v < 0 else 'E' if v > 0 else ''}" for v in ticks_x], zeroline=False, showline=False,
        tickfont=dict(size=10, color="#8b929c"),
    )
    ticks_y = [-60, -30, 0, 30, 60]
    fig.update_yaxes(
        range=[-90, 90], scaleanchor="x", scaleratio=1, tickvals=ticks_y, constrain="domain", showgrid=True,
        gridcolor="rgba(255,255,255,0.07)", zeroline=False, showline=False, tickfont=dict(size=10, color="#8b929c"),
        ticktext=[f"{abs(v)}°{'S' if v < 0 else 'N' if v > 0 else ''}" for v in ticks_y],
    )
    fig.update_layout(plot_bgcolor=OCEAN)


def _polar(fig: go.Figure, cells, projection: str, selected_cell_id) -> None:
    hemi = _HEMISPHERE[projection]
    lat = cells["lat"].to_numpy(dtype="float64")
    lon = cells["lon"].to_numpy(dtype="float64")
    total = cells["total"].to_numpy(dtype="float64")
    has_total = ~np.isnan(total)
    li, lj = _index(lat, lon)

    total_grid = _grid(li, lj, total)
    painted = _grid(li, lj, True, fill=False, dtype=bool)

    # Imagen del globo con sus celdas, y encima la cuadrícula.
    step = 2 / POLAR_PX
    fig.add_trace(
        go.Image(source=_png_uri_cached(total_grid, painted, hemi), x0=-1 + step / 2, dx=step, y0=-1 + step / 2, dy=step,
                 hoverinfo="skip", name="Celdas")
    )
    fig.add_trace(_globe_outline(hemi))

    # Cursor: marcadores transparentes en WebGL, solo en las celdas del hemisferio visible.
    visible = lat * hemi > 0
    x, y = _project(lat, lon, hemi)
    head = _place_text(cells)
    tail = _scores_text(cells)
    lat_s, lon_s = np.char.mod("%.1f", lat), np.char.mod("%.1f", lon)
    place = "<b>" + head + "</b><br>Lat " + lat_s + "°, lon " + lon_s + "°"
    text = np.where(
        has_total,
        place + "<br>Puntaje total: <b>" + np.char.mod("%.2f", np.where(has_total, total, 0.0)) + "</b>" + tail,
        place + f"<br>{INSUFFICIENT}",
    )
    fig.add_trace(
        go.Scattergl(
            x=x[visible], y=y[visible], mode="markers", name="Celdas elegibles", hovertext=text[visible], hoverinfo="text",
            marker=dict(symbol="square", size=10, color=HOVER_FILL), showlegend=False,
        )
    )
    if (~has_total).any():
        fig.add_trace(_legend_gray_trace())
    fig.add_trace(_colorbar_trace())

    a_lat, a_lon = _analog_centers(cells)
    keep = a_lat * hemi > 0
    ax, ay = _project(a_lat[keep], a_lon[keep], hemi)
    fig.add_trace(_rings_trace(ax, ay))

    chosen = (cells["cell_id"].to_numpy() == selected_cell_id) & visible if selected_cell_id is not None else np.zeros(len(cells), bool)
    if chosen.any():
        o_lat, o_lon = _cell_outline(float(lat[chosen][0]), float(lon[chosen][0]), steps=6)
        o_x, o_y = _project(o_lat, o_lon, hemi)
    else:
        o_x = o_y = np.array([])
    for tr in _selected_traces(o_x, o_y, x[chosen], y[chosen]):
        fig.add_trace(tr)

    fig.update_xaxes(range=[-1.03, 1.03], visible=False, constrain="domain")
    fig.update_yaxes(range=[-1.03, 1.03], scaleanchor="x", scaleratio=1, visible=False, constrain="domain")
    fig.update_layout(plot_bgcolor="rgba(0,0,0,0)")


_IMAGE_CACHE: dict = {}


def _png_uri_cached(total_grid, painted, hemisphere) -> str:
    """La imagen polar de los mismos totales no se recalcula (Streamlit vuelve a correr la página a cada clic)."""
    key = (hemisphere, hash(total_grid.tobytes()), hash(painted.tobytes()))
    if key not in _IMAGE_CACHE:
        if len(_IMAGE_CACHE) > 16:
            _IMAGE_CACHE.clear()
        _IMAGE_CACHE[key] = _polar_image(total_grid, painted, hemisphere)
    return _IMAGE_CACHE[key]


def build_figure(layer: MapLayer, projection: str = "world", selected_cell_id: int | None = None) -> go.Figure:
    """Mundo: un Heatmap de longitud y latitud. Polos: una imagen con la proyección ortográfica."""
    if projection not in PROJECTIONS:
        raise ValueError(f"projection debe ser una de {list(PROJECTIONS)}, no {projection!r}")
    fig = go.Figure()
    if projection == "world":
        _world(fig, layer.cells, selected_cell_id)
    else:
        _polar(fig, layer.cells, projection, selected_cell_id)
    fig.update_layout(
        height=520,
        margin=dict(l=0, r=0, t=28, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0.0),
        hoverlabel=dict(align="left"),
        dragmode="pan",
        uirevision=projection,  # conserva el zoom al mover pesos; la vista se reinicia al cambiar de proyección
    )
    return fig


def render_map(layer: MapLayer, projection: str, selected_cell_id: int | None) -> None:
    import streamlit as st

    st.plotly_chart(
        build_figure(layer, projection, selected_cell_id),
        width="stretch",
        config={"displaylogo": False, "scrollZoom": True, "modeBarButtonsToRemove": ["select2d", "lasso2d"]},
    )
