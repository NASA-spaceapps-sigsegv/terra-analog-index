"""Map in the Explore tab (design 10.3, TAI-30).

The cells are painted as an image, not as thousands of vector shapes. With a Scattergeo trace (one
marker or polygon per cell) dragging or zooming redrew about 21,000 SVG elements and the map ran at
2 or 3 frames per second. An image is composited by the browser on the GPU: panning and zooming the
map is smooth, and when zoomed in the cells are still squares with no gaps.

- World: a 180 × 360 Heatmap on longitude and latitude axes (equirectangular projection). One pixel
  is one cell, so zooming shows exact squares, and the hover text comes built in.
- South pole and North pole: a PNG image computed with the orthographic projection centered on the
  pole (each pixel looks up its cell), with transparent WebGL markers on top for the hover text.
  Mercator does not work: it cuts off near 85° and the southernmost Antarctic cells would not show.

Selection is done from the ranking, not by clicking on the map.

`build_figure` only builds the figure (tested without Streamlit); `render_map` draws it.
"""

from __future__ import annotations

import base64
import html
import struct
import textwrap
import zlib
from collections.abc import Sequence
from typing import TYPE_CHECKING

import numpy as np
import plotly.colors as pc
import plotly.graph_objects as go

from tai.caves import CAVE_KINDS
from tai.constants import GRID_RES_DEG, N_LAT, N_LON

if TYPE_CHECKING:
    from tai.models import Cave, MapLayer

GRAY = "#c8c8c8"  # cells without enough data
OCEAN = "#14171c"
SELECTED_COLOR = "#e53935"  # outline of the selected cell
ANALOG_BORDER = "#ffffff"  # ring of the known analogs
COLORSCALE = "Viridis"
INSUFFICIENT = "Insufficient data"
NO_DATA = "no data"  # what the hover shows if a dimension is null
HOVER_FILL = "rgba(0,0,0,0)"  # hover markers: the hover uses the data position, not what is visible
POLAR_PX = 900  # side of the polar views image, in pixels (one cell spans several)
RING_SIZE = 20
CAVE_COLOR = "#ff5ec4"  # caves and lava tubes (TAI-53): pink, which appears neither in Viridis nor in the gray
CAVE_SIZE = 13
CAVES_NAME = "Caves and lava tubes"
HOVER_WRAP = 60  # characters per line in a cave's hover
SELECTED_SIZE = 28

PROJECTIONS = ("world", "south_pole", "north_pole")
_HEMISPHERE = {"south_pole": -1, "north_pole": 1}

_HOVER_ROW = "<b>%{text}</b><br>Lat %{y:.1f}°, lon %{x:.1f}°"


def _viridis_lut() -> np.ndarray:
    """256 RGB colors of the scale, to paint the image without going through Plotly."""
    colors = pc.sample_colorscale(COLORSCALE, [i / 255 for i in range(256)])
    return np.array([[int(v) for v in c[4:-1].split(",")] for c in colors], dtype=np.uint8)


_LUT = _viridis_lut()
_GRAY_RGB = np.array([int(GRAY[i : i + 2], 16) for i in (1, 3, 5)], dtype=np.uint8)
_OCEAN_RGB = np.array([int(OCEAN[i : i + 2], 16) for i in (1, 3, 5)], dtype=np.uint8)


# --- Cells and hover text ------------------------------------------------------


def _index(lat, lon) -> tuple[np.ndarray, np.ndarray]:
    """Row and column in the 1° grid of each cell, from its center."""
    li = np.floor(np.asarray(lat, dtype="float64") / GRID_RES_DEG + N_LAT / 2).astype(int)
    lj = np.floor(np.asarray(lon, dtype="float64") / GRID_RES_DEG + N_LON / 2).astype(int)
    return np.clip(li, 0, N_LAT - 1), np.clip(lj, 0, N_LON - 1)


def _grid(li, lj, values, fill=np.nan, dtype="float64") -> np.ndarray:
    out = np.full((N_LAT, N_LON), fill, dtype=dtype)
    out[li, lj] = values
    return out


def _scores_text(cells) -> np.ndarray:
    """"<br>Terrain: 0.62<br>…": what does not depend on the weights, ready for the hover."""

    def two(col):
        v = cells[col].to_numpy(dtype="float64")
        return np.where(np.isnan(v), NO_DATA, np.char.mod("%.2f", v))

    text = (
        np.char.add("<br>Terrain: ", two("s_terrain"))
        + np.char.add("<br>Temperature: ", two("s_temperature"))
        + np.char.add("<br>Water and ice: ", two("s_water_ice"))
    )
    # Dust and wind (TAI-52) only if the target has the dimension: on the Moon it would be "no data" everywhere.
    if cells["s_dust_wind"].notna().any():
        text = text + np.char.add("<br>Dust and wind: ", two("s_dust_wind"))
    return text + np.char.add("<br>Astrobiology: ", two("bio_score"))


def _place_text(cells) -> np.ndarray:
    """Country and, if any, the known analog: the hover header."""
    country = cells["country"].fillna("No country").astype(str)
    analog = cells["known_analog"].fillna("")
    return country.where(analog == "", country + "<br>Known analog: " + analog).to_numpy()


def _analog_centers(cells) -> tuple[np.ndarray, np.ndarray]:
    """One point per known analog: the center of the cells that fall within its radius.

    Longitude is averaged as an angle so it does not break near ±180°.
    """
    lat, lon = [], []
    for _, g in cells[cells["known_analog"].notna()].groupby("known_analog"):
        rad = np.radians(g["lon"].to_numpy(dtype="float64"))
        lat.append(float(g["lat"].mean()))
        lon.append(float(np.degrees(np.arctan2(np.sin(rad).mean(), np.cos(rad).mean()))))
    return np.array(lat), np.array(lon)


def _cell_outline(lat: float, lon: float, steps: int = 1) -> tuple[np.ndarray, np.ndarray]:
    """The 1° square centered on (lat, lon), closed, with `steps` segments per side."""
    h = GRID_RES_DEG / 2
    t = np.linspace(0.0, 1.0, steps + 1)
    south, north, west, east = lat - h, lat + h, lon - h, lon + h
    lats = np.concatenate([south + 2 * h * t, np.full(steps, north), north - 2 * h * t[1:], np.full(steps - 1, south)])
    lons = np.concatenate([np.full(steps + 1, west), west + 2 * h * t[1:], np.full(steps, east), east - 2 * h * t[1:-1]])
    n = min(len(lats), len(lons))
    return np.append(lats[:n], lats[0]), np.append(lons[:n], lons[0])


# --- Polar orthographic projection ---------------------------------------------


def _project(lat, lon, hemisphere: int) -> tuple[np.ndarray, np.ndarray]:
    """(x, y) on the unit disk of an orthographic view centered on the pole.

    South: meridian 0 pointing up and east clockwise. North: meridian 0 pointing down and east
    counterclockwise, as in Scattergeo with the same rotation.
    """
    rho = np.cos(np.radians(np.asarray(lat, dtype="float64")))
    lam = np.radians(np.asarray(lon, dtype="float64"))
    sign = 1.0 if hemisphere < 0 else -1.0
    return rho * np.sin(lam), sign * rho * np.cos(lam)


def _png_uri(rgba: np.ndarray) -> str:
    """8-bit RGBA PNG as a data URI, without depending on Pillow."""
    h, w, _ = rgba.shape
    raw = np.concatenate([np.zeros((h, 1), np.uint8), rgba.reshape(h, w * 4)], axis=1).tobytes()  # filter 0 per row

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
    """Image of the pole: each pixel of the disk looks up the 1° cell it belongs to.

    `total_grid` holds the total (NaN where there is no value) and `painted` says where there is a cell;
    those with a cell but no total come out gray, and where there is no cell (the sea) it stays transparent.
    """
    axis = (np.arange(POLAR_PX) + 0.5) / POLAR_PX * 2 - 1
    x, y = np.meshgrid(axis, -axis)  # the first row of the image is the top one, y = +1
    rho = np.hypot(x, y)
    inside = rho <= 1
    lat = hemisphere * np.degrees(np.arccos(np.clip(rho, 0, 1)))
    lon = np.degrees(np.arctan2(x, y if hemisphere < 0 else -y))
    li, lj = _index(lat, lon)
    lj = np.floor(lon + N_LON / 2).astype(int) % N_LON
    total = total_grid[li, lj]
    rgba = np.zeros((POLAR_PX, POLAR_PX, 4), dtype=np.uint8)
    rgba[inside, :3] = _OCEAN_RGB  # the disk's sea, opaque: Plotly images sit below the other traces
    rgba[inside, 3] = 255
    has_total = inside & ~np.isnan(total)
    rgba[has_total, :3] = _LUT[np.clip(np.rint(total[has_total] * 255), 0, 255).astype(int)]
    gray = inside & painted[li, lj] & np.isnan(total)
    rgba[gray, :3] = _GRAY_RGB
    # Plotly puts the image's first row at y0 and goes up from there: it is flipped so south ends up at the bottom.
    return _png_uri(rgba[::-1].copy())


def _globe_outline(hemisphere: int) -> go.Scatter:
    """The globe's edge and a faint graticule every 30°, for context without a base map."""
    t = np.radians(np.linspace(0, 360, 181))
    xs, ys = [np.sin(t)], [np.cos(t)]
    for lat in (hemisphere * 30.0, hemisphere * 60.0):  # parallels
        r = np.cos(np.radians(lat))
        xs += [np.array([np.nan]), r * np.sin(t)]
        ys += [np.array([np.nan]), r * np.cos(t)]
    for lon in range(0, 360, 30):  # meridians
        x, y = _project(np.array([0.0, hemisphere * 89.9]), np.array([lon, lon]), hemisphere)
        xs += [np.array([np.nan]), x]
        ys += [np.array([np.nan]), y]
    return go.Scatter(
        x=np.concatenate(xs), y=np.concatenate(ys), mode="lines", line=dict(width=0.6, color="rgba(255,255,255,0.14)"),
        hoverinfo="skip", showlegend=False,
    )


# --- Common traces --------------------------------------------------------------


def _colorbar_trace() -> go.Scatter:
    """Color bar of the polar views: a one-point trace off the map that only contributes the scale."""
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
            colorbar=dict(title=dict(text="Total score"), thickness=12, len=0.7),
        ),
        hoverinfo="skip",
        showlegend=False,
        name="Total score",
    )


def _legend_gray_trace() -> go.Scatter:
    return go.Scatter(
        x=[None], y=[None], mode="markers", marker=dict(symbol="square", size=10, color=GRAY), name=INSUFFICIENT,
        hoverinfo="skip", showlegend=True,
    )


def _rings_trace(x, y) -> go.Scatter:
    return go.Scatter(
        x=x, y=y, mode="markers", name="Known analog",
        marker=dict(symbol="circle-open", size=RING_SIZE, color=ANALOG_BORDER, line=dict(width=2.5)),
        hoverinfo="skip", showlegend=True,
    )


def _cave_hover(cave: Cave) -> str:
    """Name, type, why it matters and source, in short lines (Plotly's hover does not wrap lines)."""
    def wrap(text: str) -> str:
        return "<br>".join(html.escape(line) for line in textwrap.wrap(text, HOVER_WRAP))

    return (f"<b>{html.escape(cave.name)}</b><br>{CAVE_KINDS[cave.kind]}<br>{wrap(cave.relevance)}"
            f"<br><i>Source: {wrap(cave.source)}</i>")


def _caves_trace(x, y, caves: Sequence[Cave]) -> go.Scatter:
    """Informational layer: one triangle per cave, with its own hover text. It is not a cell and has no score."""
    return go.Scatter(
        x=x, y=y, mode="markers", name=CAVES_NAME,
        marker=dict(symbol="triangle-up", size=CAVE_SIZE, color=CAVE_COLOR, line=dict(width=1, color="#000000")),
        hovertext=[_cave_hover(c) for c in caves], hoverinfo="text", showlegend=True,
    )


def _selected_traces(x_outline, y_outline, x, y) -> list[go.Scatter]:
    """The selected cell: its outline, which scales with zoom, and a marker larger than the ring."""
    return [
        go.Scatter(
            x=x_outline, y=y_outline, mode="lines", name="Selected cell outline",
            line=dict(width=2.5, color=SELECTED_COLOR), hoverinfo="skip", showlegend=False,
        ),
        go.Scatter(
            x=x, y=y, mode="markers", name="Selected cell",
            marker=dict(symbol="square-open", size=SELECTED_SIZE, color=SELECTED_COLOR, line=dict(width=3, color=SELECTED_COLOR)),
            hoverinfo="skip", showlegend=False,
        ),
    ]


# --- Figure ---------------------------------------------------------------------


def _world(fig: go.Figure, cells, selected_cell_id, caves: Sequence[Cave] = ()) -> None:
    lat = cells["lat"].to_numpy(dtype="float64")
    lon = cells["lon"].to_numpy(dtype="float64")
    total = cells["total"].to_numpy(dtype="float64")
    has_total = ~np.isnan(total)
    li, lj = _index(lat, lon)
    head = _place_text(cells)

    xs = np.arange(N_LON) * GRID_RES_DEG - 180 + GRID_RES_DEG / 2
    ys = np.arange(N_LAT) * GRID_RES_DEG - 90 + GRID_RES_DEG / 2

    # No data: a gray layer, underneath, only if there are such cells (with the real data there are none and a
    # megabyte is saved). There is hover only where there is a cell (hoverongaps=False).
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
            name="Eligible cells", x=xs, y=ys, z=_grid(li[has_total], lj[has_total], total[has_total]), zmin=0, zmax=1,
            colorscale=COLORSCALE, hoverongaps=False,
            text=_grid(li[has_total], lj[has_total], head[has_total], fill="", dtype=object),
            customdata=_grid(li[has_total], lj[has_total], _scores_text(cells)[has_total], fill="", dtype=object),
            hovertemplate=_HOVER_ROW + "<br>Total score: <b>%{z:.2f}</b>%{customdata}<extra></extra>",
            colorbar=dict(title=dict(text="Total score"), thickness=12, len=0.7),
        )
    )
    if gray.any():
        fig.add_trace(_legend_gray_trace())

    a_lat, a_lon = _analog_centers(cells)
    fig.add_trace(_rings_trace(a_lon, a_lat))
    if caves:
        fig.add_trace(_caves_trace([c.lon for c in caves], [c.lat for c in caves], caves))

    chosen = cells["cell_id"].to_numpy() == selected_cell_id if selected_cell_id is not None else np.zeros(len(cells), bool)
    if chosen.any():
        o_lat, o_lon = _cell_outline(float(lat[chosen][0]), float(lon[chosen][0]))
    else:
        o_lat = o_lon = np.array([])
    for t in _selected_traces(o_lon, o_lat, lon[chosen], lat[chosen]):
        fig.add_trace(t)

    ticks_x = list(range(-180, 181, 60))
    fig.update_xaxes(
        range=[-180, 180], minallowed=-180, maxallowed=180,  # zooming out stops at the whole world
        tickvals=ticks_x, constrain="domain", showgrid=True, gridcolor="rgba(255,255,255,0.07)",
        ticktext=[f"{abs(v)}°{'W' if v < 0 else 'E' if v > 0 else ''}" for v in ticks_x], zeroline=False, showline=False,
        tickfont=dict(size=10, color="#8b929c"),
    )
    ticks_y = [-60, -30, 0, 30, 60]
    fig.update_yaxes(
        range=[-90, 90], minallowed=-90, maxallowed=90, scaleanchor="x", scaleratio=1, tickvals=ticks_y, constrain="domain",
        showgrid=True,
        gridcolor="rgba(255,255,255,0.07)", zeroline=False, showline=False, tickfont=dict(size=10, color="#8b929c"),
        ticktext=[f"{abs(v)}°{'S' if v < 0 else 'N' if v > 0 else ''}" for v in ticks_y],
    )
    fig.update_layout(plot_bgcolor=OCEAN)


def _polar(fig: go.Figure, cells, projection: str, selected_cell_id, caves: Sequence[Cave] = ()) -> None:
    hemi = _HEMISPHERE[projection]
    lat = cells["lat"].to_numpy(dtype="float64")
    lon = cells["lon"].to_numpy(dtype="float64")
    total = cells["total"].to_numpy(dtype="float64")
    has_total = ~np.isnan(total)
    li, lj = _index(lat, lon)

    total_grid = _grid(li, lj, total)
    painted = _grid(li, lj, True, fill=False, dtype=bool)

    # Image of the globe with its cells, and the graticule on top.
    step = 2 / POLAR_PX
    fig.add_trace(
        go.Image(source=_png_uri_cached(total_grid, painted, hemi), x0=-1 + step / 2, dx=step, y0=-1 + step / 2, dy=step,
                 hoverinfo="skip", name="Cells")
    )
    fig.add_trace(_globe_outline(hemi))

    # Hover: transparent WebGL markers, only on the cells of the visible hemisphere.
    visible = lat * hemi > 0
    x, y = _project(lat, lon, hemi)
    head = _place_text(cells)
    tail = _scores_text(cells)
    lat_s, lon_s = np.char.mod("%.1f", lat), np.char.mod("%.1f", lon)
    place = "<b>" + head + "</b><br>Lat " + lat_s + "°, lon " + lon_s + "°"
    text = np.where(
        has_total,
        place + "<br>Total score: <b>" + np.char.mod("%.2f", np.where(has_total, total, 0.0)) + "</b>" + tail,
        place + f"<br>{INSUFFICIENT}",
    )
    fig.add_trace(
        go.Scattergl(
            x=x[visible], y=y[visible], mode="markers", name="Eligible cells", hovertext=text[visible], hoverinfo="text",
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
    shown = [c for c in caves if c.lat * hemi > 0]  # only those in the visible hemisphere
    if shown:
        cx, cy = _project(np.array([c.lat for c in shown]), np.array([c.lon for c in shown]), hemi)
        fig.add_trace(_caves_trace(cx, cy, shown))

    chosen = (cells["cell_id"].to_numpy() == selected_cell_id) & visible if selected_cell_id is not None else np.zeros(len(cells), bool)
    if chosen.any():
        o_lat, o_lon = _cell_outline(float(lat[chosen][0]), float(lon[chosen][0]), steps=6)
        o_x, o_y = _project(o_lat, o_lon, hemi)
    else:
        o_x = o_y = np.array([])
    for tr in _selected_traces(o_x, o_y, x[chosen], y[chosen]):
        fig.add_trace(tr)

    # minallowed and maxallowed: you can zoom in and pan, but zooming out stops at the whole globe (the map is never lost)
    fig.update_xaxes(range=[-1.03, 1.03], minallowed=-1.03, maxallowed=1.03, visible=False, constrain="domain")
    fig.update_yaxes(range=[-1.03, 1.03], minallowed=-1.03, maxallowed=1.03, scaleanchor="x", scaleratio=1, visible=False, constrain="domain")
    fig.update_layout(plot_bgcolor="rgba(0,0,0,0)")


_IMAGE_CACHE: dict = {}


def _png_uri_cached(total_grid, painted, hemisphere) -> str:
    """The polar image for the same totals is not recomputed (Streamlit reruns the page on every click)."""
    key = (hemisphere, hash(total_grid.tobytes()), hash(painted.tobytes()))
    if key not in _IMAGE_CACHE:
        if len(_IMAGE_CACHE) > 16:
            _IMAGE_CACHE.clear()
        _IMAGE_CACHE[key] = _polar_image(total_grid, painted, hemisphere)
    return _IMAGE_CACHE[key]


def build_figure(layer: MapLayer, projection: str = "world", selected_cell_id: int | None = None,
                 caves: Sequence[Cave] = ()) -> go.Figure:
    """World: a longitude/latitude Heatmap. Poles: an image with the orthographic projection.

    `caves`: the caves and lava tubes layer (TAI-53); if empty, the map does not draw it."""
    if projection not in PROJECTIONS:
        raise ValueError(f"projection must be one of {list(PROJECTIONS)}, not {projection!r}")
    fig = go.Figure()
    if projection == "world":
        _world(fig, layer.cells, selected_cell_id, caves)
    else:
        _polar(fig, layer.cells, projection, selected_cell_id, caves)
    fig.update_layout(
        height=520,
        margin=dict(l=0, r=0, t=28, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0.0),
        hoverlabel=dict(align="left"),
        dragmode="pan",
        uirevision=projection,  # keeps the zoom when moving weights; the view resets when changing projection
    )
    return fig


def render_map(layer: MapLayer, projection: str, selected_cell_id: int | None, caves: Sequence[Cave] = ()) -> None:
    import streamlit as st

    st.plotly_chart(
        build_figure(layer, projection, selected_cell_id, caves),
        width="stretch",
        config={"displaylogo": False, "scrollZoom": True, "modeBarButtonsToRemove": ["select2d", "lasso2d"]},
    )
