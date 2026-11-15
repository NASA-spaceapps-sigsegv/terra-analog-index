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

The best cells are drawn as numbered dots (the rank): tapping one opens its card, like picking its row in the
ranking. The cells themselves are not selectable: at world scale one is a pixel.

`build_figure` only builds the figure (tested without Streamlit); `render_map` draws it.
"""

from __future__ import annotations

import base64
import html
import struct
import textwrap
import zlib
from collections.abc import Callable, Sequence
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
POLAR_PX = 720  # side of the polar views image, in pixels (one cell spans several). It is computed again for every set of weights: 900 took 5.7 s on the free server
RING_SIZE = 26
CAVE_COLOR = "#ff5ec4"  # caves and lava tubes (TAI-53): pink, which appears neither in Viridis nor in the gray
CAVE_SIZE = 13
CAVES_NAME = "Caves and lava tubes"
HOVER_WRAP = 60  # characters per line in a cave's hover
SELECTED_SIZE = 28
RANK_SIZE = 15  # numbered dots on the best cells; smaller than the ring (RING_SIZE) so a known analog keeps its ring around it
RANK_FILL = "rgba(16,18,22,0.88)"
HINT_PICKABLE = "Tap or click to open its card"
HINT_LIST = "Open its card from the list below"  # the phone: see render_map
NO_SCORE_NAME = "Cells without a score"
MAP_KEY = "map_chart"  # session key of the chart: its selection (a tap on a numbered dot) is read in a callback
TOP_KEY = "map_top_trace"  # (curve number, cell_ids) of the numbered dots drawn in the last run
# Figure height, in px. The map sits beside the best cells, so it is narrower than the page: the world view (2:1) needs
# less height than the poles (square). On a phone it is narrower still.
HEIGHT = {"world": 400, "south_pole": 500, "north_pole": 500}
COMPACT_HEIGHT = {"world": 330, "south_pole": 420, "north_pole": 420}

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


def _colorbar(horizontal: bool) -> dict:
    """Settings of the color bar: a column on the right, or a strip below the map (the world view and the phone: a column would eat the width)."""
    if horizontal:
        return dict(title=dict(text="Total score", side="top"), orientation="h", thickness=9, len=0.9, x=0.5, xanchor="center",
                    y=-0.1, yanchor="top", ypad=14, tickfont=dict(size=10))
    return dict(title=dict(text="Total score"), thickness=12, len=0.7)


def _colorbar_trace(horizontal: bool = False) -> go.Scatter:
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
            colorbar=_colorbar(horizontal),
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


# Numbered dots closer than this (degrees on the world map, units on the polar disk) are drawn as one: the best rank on
# the dot, the others in its hover. A dot is about 10 degrees wide when the whole world is on screen, so 20 cells inside
# Antarctica used to pile up on top of each other and of the rings of the known analogs.
CLUSTER = {"world": 0.0, "polar": 0.0}  # 0: each of the best cells gets its own dot, all 20 are marked
CLUSTER_PHONE = 1.6  # the same dots on a narrower map cover more of it


def _declutter(x, y, radius: float) -> tuple[list[int], list[int]]:
    """Greedy, in rank order: the indices that stay, and for every point the position (in that list) of the one it joins."""
    keep: list[int] = []
    owner: list[int] = []
    for i in range(len(x)):
        for j, k in enumerate(keep):
            if (x[i] - x[k]) ** 2 + (y[i] - y[k]) ** 2 < radius**2:
                owner.append(j)
                break
        else:
            keep.append(i)
            owner.append(len(keep) - 1)
    return keep, owner



def _top_trace(cells, top_cells: Sequence[int], hemisphere: int = 0, pickable: bool = True) -> go.Scatter | None:
    """Numbered dots on the best cells: the number is the rank. Each carries its cell_id so a tap can open the card.

    `hemisphere` 0 is the world view (x = lon, y = lat); -1 and 1 are the polar views, which only show their own hemisphere."""
    if not len(top_cells):
        return None
    by_id = cells.set_index("cell_id")
    picked = [(rank, int(c)) for rank, c in enumerate(top_cells, start=1) if c in by_id.index]
    if hemisphere:
        picked = [(r, c) for r, c in picked if by_id.at[c, "lat"] * hemisphere > 0]
    if not picked:
        return None
    ranks = [r for r, _ in picked]
    ids = np.array([c for _, c in picked], dtype="int32")
    rows = by_id.loc[ids].reset_index()
    lat = rows["lat"].to_numpy(dtype="float64")
    lon = rows["lon"].to_numpy(dtype="float64")
    x, y = (lon, lat) if hemisphere == 0 else _project(lat, lon, hemisphere)
    country = rows["country"].fillna("No country").astype(str)
    analog = rows["known_analog"].fillna("")
    total = rows["total"].to_numpy(dtype="float64")
    scores = _scores_text(rows)
    keep, owner = _declutter(x, y, (CLUSTER["world"] if hemisphere == 0 else CLUSTER["polar"]) * (1.0 if pickable else CLUSTER_PHONE))
    joined = {j: [ranks[i] for i, o in enumerate(owner) if o == j and i != keep[j]] for j in range(len(keep))}
    order = [(j, keep[j]) for j in reversed(range(len(keep)))]  # the best rank is drawn last, so it stays on top of the others
    shown = [i for _, i in order]
    hover = [
        f"<b>#{ranks[i]} · {country.iat[i]}</b>" + (f"<br>Known analog: {analog.iat[i]}" if analog.iat[i] else "")
        + f"<br>Lat {lat[i]:.1f}°, lon {lon[i]:.1f}°<br>Total score: <b>{NO_DATA if np.isnan(total[i]) else f'{total[i]:.2f}'}</b>"
        + scores[i] + (f"<br>Also here: {', '.join(f'#{r}' for r in joined[j])}" if joined[j] else "")
        + f"<br><i>{HINT_PICKABLE if pickable else HINT_LIST}</i>"
        for j, i in order
    ]
    return go.Scatter(
        x=x[shown], y=y[shown], mode="markers+text", name=f"Top {len(top_cells)}", text=[str(ranks[i]) for i in shown],
        textposition="middle center", textfont=dict(color="#ffffff", size=9), customdata=ids[shown], hovertext=hover, hoverinfo="text",
        marker=dict(symbol="circle", size=RANK_SIZE, color=RANK_FILL, line=dict(width=1.5, color="#ffffff")),
        unselected=dict(marker=dict(opacity=1), textfont=dict(color="#ffffff")), showlegend=True,
    )


# --- Figure ---------------------------------------------------------------------

# --- The view never leaves the map ------------------------------------------------------------------------------
# Plotly's minallowed/maxallowed do not move the view back inside: past the edge they cut the range, so dragging a
# full map "zooms" it into a corner and zooming out afterwards cannot recover the whole map. This script does what a
# viewer expects: the view can be as large as the whole map and no larger, and it is shifted (never cut) to stay inside.
# It listens to every relayout of every chart (drag, wheel, toolbar buttons) and reads the limits from layout.meta.
VIEW_LIMITS = {"world": ((-180.0, 180.0), (-90.0, 90.0)), "south_pole": ((-1.03, 1.03), (-1.03, 1.03)),
               "north_pole": ((-1.03, 1.03), (-1.03, 1.03))}
VIEW_GUARD_JS = """
(() => {
  if (window.__taiViewGuard) return;
  window.__taiViewGuard = true;
  const keep = (gd) => {
    const lim = gd.layout && gd.layout.meta && gd.layout.meta.tai_limits;
    const L = gd._fullLayout;
    if (!lim || !L || !L.xaxis || !L.yaxis || gd.__taiBusy) return;
    let [x0, x1] = L.xaxis.range, [y0, y1] = L.yaxis.range;
    const fx = lim.x[1] - lim.x[0], fy = lim.y[1] - lim.y[0];
    const k = Math.max((x1 - x0) / fx, (y1 - y0) / fy);
    if (k > 1) {  // zoomed out past the whole map: back to its size, around the same centre
      const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2, hx = (x1 - x0) / (2 * k), hy = (y1 - y0) / (2 * k);
      x0 = cx - hx; x1 = cx + hx; y0 = cy - hy; y1 = cy + hy;
    }
    if (x0 < lim.x[0]) { x1 += lim.x[0] - x0; x0 = lim.x[0]; }
    if (x1 > lim.x[1]) { x0 -= x1 - lim.x[1]; x1 = lim.x[1]; }
    if (y0 < lim.y[0]) { y1 += lim.y[0] - y0; y0 = lim.y[0]; }
    if (y1 > lim.y[1]) { y0 -= y1 - lim.y[1]; y1 = lim.y[1]; }
    const [a0, a1] = L.xaxis.range, [b0, b1] = L.yaxis.range, tol = 1e-6 * Math.max(fx, fy);
    if (Math.abs(x0 - a0) < tol && Math.abs(x1 - a1) < tol && Math.abs(y0 - b0) < tol && Math.abs(y1 - b1) < tol) return;
    gd.__taiBusy = true;
    Promise.resolve(Plotly.relayout(gd, {"xaxis.range": [x0, x1], "yaxis.range": [y0, y1]}))
      .finally(() => { gd.__taiBusy = false; });
  };
  const attach = () => document.querySelectorAll(".js-plotly-plot").forEach((gd) => {
    if (gd.__taiGuard || typeof gd.on !== "function") return;
    gd.__taiGuard = true;
    gd.on("plotly_relayout", () => keep(gd));
  });
  attach();
  new MutationObserver(attach).observe(document.body, {childList: true, subtree: true});
})();
"""


def render_view_guard() -> None:
    import streamlit as st

    st.html(f"<script>{VIEW_GUARD_JS}</script>", unsafe_allow_javascript=True)




def _world(fig: go.Figure, cells, selected_cell_id, caves: Sequence[Cave] = (), top_cells: Sequence[int] = (),
           compact: bool = False) -> None:
    lat = cells["lat"].to_numpy(dtype="float64")
    lon = cells["lon"].to_numpy(dtype="float64")
    total = cells["total"].to_numpy(dtype="float64")
    has_total = ~np.isnan(total)
    li, lj = _index(lat, lon)
    head = _place_text(cells).astype("U")  # a unicode array, not object: Plotly copies it in one go instead of string by string

    xs = np.arange(N_LON) * GRID_RES_DEG - 180 + GRID_RES_DEG / 2
    ys = np.arange(N_LAT) * GRID_RES_DEG - 90 + GRID_RES_DEG / 2

    # No data: a gray layer, underneath, only if there are such cells (with the real data there are none and a
    # megabyte is saved). There is hover only where there is a cell (hoverongaps=False).
    gray = ~has_total
    if gray.any():
        fig.add_trace(
            go.Heatmap(
                name=INSUFFICIENT, x=xs, y=ys, z=_grid(li[gray], lj[gray], 1.0, dtype="float32"), zmin=0, zmax=1,
                colorscale=[[0, GRAY], [1, GRAY]], showscale=False, hoverongaps=False,
                text=_grid(li[gray], lj[gray], head[gray], fill="", dtype=head.dtype),
                hovertemplate=_HOVER_ROW + f"<br>{INSUFFICIENT}<extra></extra>",
            )
        )
    # The hover is the place, the coordinates and the total: what moves with the weights. The five scores are in the
    # card, in the ranking and in the hover of the numbered markers, so each rerun sends about a quarter of the bytes.
    fig.add_trace(
        go.Heatmap(
            name="Eligible cells", x=xs, y=ys, z=_grid(li[has_total], lj[has_total], total[has_total], dtype="float32"),
            zmin=0, zmax=1, colorscale=COLORSCALE, hoverongaps=False,
            text=_grid(li[has_total], lj[has_total], head[has_total], fill="", dtype=head.dtype),
            hovertemplate=_HOVER_ROW + "<br>Total score: <b>%{z:.2f}</b><extra></extra>",
            colorbar=_colorbar(True),  # below the map: the width goes to the map
        )
    )
    if gray.any():
        fig.add_trace(_legend_gray_trace())

    a_lat, a_lon = _analog_centers(cells)
    fig.add_trace(_rings_trace(a_lon, a_lat))
    if caves:
        fig.add_trace(_caves_trace([c.lon for c in caves], [c.lat for c in caves], caves))
    top = _top_trace(cells, top_cells, pickable=not compact)
    if top is not None:
        fig.add_trace(top)

    chosen = cells["cell_id"].to_numpy() == selected_cell_id if selected_cell_id is not None else np.zeros(len(cells), bool)
    if chosen.any():
        o_lat, o_lon = _cell_outline(float(lat[chosen][0]), float(lon[chosen][0]))
    else:
        o_lat = o_lon = np.array([])
    for t in _selected_traces(o_lon, o_lat, lon[chosen], lat[chosen]):
        fig.add_trace(t)

    ticks_x = list(range(-180, 181, 60))
    fig.update_xaxes(
        range=[-180, 180],  # the view is kept inside the whole world by VIEW_GUARD_JS
        tickvals=ticks_x, constrain="domain", showgrid=True, gridcolor="rgba(255,255,255,0.07)",
        ticktext=[f"{abs(v)}°{'W' if v < 0 else 'E' if v > 0 else ''}" for v in ticks_x], zeroline=False, showline=False,
        tickfont=dict(size=10, color="#8b929c"),
    )
    ticks_y = [-60, -30, 0, 30, 60]
    fig.update_yaxes(
        range=[-90, 90], scaleanchor="x", scaleratio=1, tickvals=ticks_y, constrain="domain",
        showgrid=True,
        gridcolor="rgba(255,255,255,0.07)", zeroline=False, showline=False, tickfont=dict(size=10, color="#8b929c"),
        ticktext=[f"{abs(v)}°{'S' if v < 0 else 'N' if v > 0 else ''}" for v in ticks_y],
    )
    fig.update_layout(plot_bgcolor=OCEAN)


def _polar(fig: go.Figure, cells, projection: str, selected_cell_id, caves: Sequence[Cave] = (),
           top_cells: Sequence[int] = (), compact: bool = False) -> None:
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

    # Hover: transparent WebGL markers, only on the cells of the visible hemisphere. Numbers travel as float32
    # arrays and the template formats them in the browser; only the place travels as text.
    visible = lat * hemi > 0
    x, y = _project(lat, lon, hemi)
    head = _place_text(cells).astype("U")
    show = visible & has_total
    fig.add_trace(
        go.Scattergl(
            x=x[show].astype("float32"), y=y[show].astype("float32"), mode="markers", name="Eligible cells",
            text=head[show], customdata=np.column_stack([lat[show], lon[show], total[show]]).astype("float32"),
            hovertemplate="<b>%{text}</b><br>Lat %{customdata[0]:.1f}°, lon %{customdata[1]:.1f}°"
                          "<br>Total score: <b>%{customdata[2]:.2f}</b><extra></extra>",
            marker=dict(symbol="square", size=10, color=HOVER_FILL), showlegend=False,
        )
    )
    no_total = visible & ~has_total
    if no_total.any():
        place = "<b>" + head[no_total] + "</b><br>Lat " + np.char.mod("%.1f", lat[no_total]) + "°, lon " + \
            np.char.mod("%.1f", lon[no_total]) + f"°<br>{INSUFFICIENT}"
        fig.add_trace(
            go.Scattergl(
                x=x[no_total].astype("float32"), y=y[no_total].astype("float32"), mode="markers", name=NO_SCORE_NAME,
                hovertext=place, hoverinfo="text", marker=dict(symbol="square", size=10, color=HOVER_FILL), showlegend=False,
            )
        )
    if (~has_total).any():
        fig.add_trace(_legend_gray_trace())
    fig.add_trace(_colorbar_trace(compact))  # a column on the side, except on a phone

    a_lat, a_lon = _analog_centers(cells)
    keep = a_lat * hemi > 0
    ax, ay = _project(a_lat[keep], a_lon[keep], hemi)
    fig.add_trace(_rings_trace(ax, ay))
    shown = [c for c in caves if c.lat * hemi > 0]  # only those in the visible hemisphere
    if shown:
        cx, cy = _project(np.array([c.lat for c in shown]), np.array([c.lon for c in shown]), hemi)
        fig.add_trace(_caves_trace(cx, cy, shown))
    top = _top_trace(cells, top_cells, hemi, pickable=not compact)
    if top is not None:
        fig.add_trace(top)

    chosen = (cells["cell_id"].to_numpy() == selected_cell_id) & visible if selected_cell_id is not None else np.zeros(len(cells), bool)
    if chosen.any():
        o_lat, o_lon = _cell_outline(float(lat[chosen][0]), float(lon[chosen][0]), steps=6)
        o_x, o_y = _project(o_lat, o_lon, hemi)
    else:
        o_x = o_y = np.array([])
    for tr in _selected_traces(o_x, o_y, x[chosen], y[chosen]):
        fig.add_trace(tr)

    # You can zoom in and pan, but never out of the whole globe: VIEW_GUARD_JS keeps the view inside it.
    fig.update_xaxes(range=[-1.03, 1.03], visible=False, constrain="domain")
    fig.update_yaxes(range=[-1.03, 1.03], scaleanchor="x", scaleratio=1, visible=False, constrain="domain")
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
                 caves: Sequence[Cave] = (), top_cells: Sequence[int] = (), compact: bool = False,
                 view_rev: int = 0) -> go.Figure:
    """World: a longitude/latitude Heatmap. Poles: an image with the orthographic projection.

    `caves`: the caves and lava tubes layer (TAI-53); if empty, the map does not draw it.
    `top_cells`: cell_ids in ranking order; they are drawn as numbered dots you can tap to open the card.
    `compact`: the phone layout: a shorter figure, the color bar below the map and the legend below that.
    `view_rev`: changing it resets the zoom (the "Back to full view" button)."""
    if projection not in PROJECTIONS:
        raise ValueError(f"projection must be one of {list(PROJECTIONS)}, not {projection!r}")
    fig = go.Figure()
    if projection == "world":
        _world(fig, layer.cells, selected_cell_id, caves, top_cells, compact)
    else:
        _polar(fig, layer.cells, projection, selected_cell_id, caves, top_cells, compact)
    # With a selection (a tap on a numbered dot) Plotly fades every other marker; the rings and caves must stay as they are.
    fig.update_traces(
        unselected=dict(marker=dict(opacity=1)), selected=dict(marker=dict(opacity=1)),
        selector=lambda t: t.type in ("scatter", "scattergl"),
    )
    fig.update_layout(
        height=(COMPACT_HEIGHT if compact else HEIGHT)[projection],
        margin=dict(l=0, r=0, t=34 if compact else 28, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        showlegend=not compact,  # on a phone the key under the map says it all
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0.0),
        hoverlabel=dict(align="left"),
        # On a phone one finger scrolls the page; panning is a button in the toolbar (pan2d).
        dragmode=False if compact else "pan",
        meta=dict(tai_limits=dict(x=list(VIEW_LIMITS[projection][0]), y=list(VIEW_LIMITS[projection][1]))),
        uirevision=f"{projection}-{view_rev}",  # keeps the zoom when moving weights; the view resets when changing projection
    )
    return fig


def render_map(layer: MapLayer, projection: str, selected_cell_id: int | None, caves: Sequence[Cave] = (),
               top_cells: Sequence[int] = (), compact: bool = False, view_rev: int = 0,
               on_pick: Callable[[int], None] | None = None) -> None:
    """Draws the map. With `on_pick`, tapping a numbered dot calls it with that cell's id.

    Not on a phone: Streamlit forces drag-to-pan on a chart that can be selected, and a map that pans under one finger
    traps the scroll of the page. There the dots are only a key, and the cards below open the cell."""
    import streamlit as st

    render_view_guard()
    fig = build_figure(layer, projection, selected_cell_id, caves, top_cells, compact, view_rev)
    remove = ["select2d", "lasso2d"] + (["toImage", "zoom2d", "autoScale2d"] if compact else [])
    config = {"displaylogo": False, "scrollZoom": not compact, "modeBarButtonsToRemove": remove}
    if on_pick is None or compact:
        st.plotly_chart(fig, width="stretch", config=config)
        return
    # What the numbered dots are, as plotted (the polar views only draw their own hemisphere): the callback needs it.
    curve = next((i for i, t in enumerate(fig.data) if t.name == f"Top {len(top_cells)}"), None)
    st.session_state[TOP_KEY] = (curve, [int(c) for c in fig.data[curve].customdata] if curve is not None else [])

    def picked() -> None:
        cell_id = cell_from_selection(st.session_state.get(MAP_KEY), *st.session_state.get(TOP_KEY, (None, [])))
        if cell_id is not None:
            on_pick(cell_id)

    st.plotly_chart(fig, key=MAP_KEY, on_select=picked, selection_mode="points", width="stretch", config=config)


def cell_from_selection(state, top_curve: int | None, plotted_ids: Sequence[int]) -> int | None:
    """The cell of the tapped numbered dot, from the chart's selection state; None if nothing useful was picked.

    Only points of the numbered-dots trace count (`top_curve`); the cell is the one plotted at that position."""
    points = ((state or {}).get("selection") or {}).get("points") or []
    for p in points:
        idx = p.get("point_index", p.get("point_number"))
        if top_curve is not None and p.get("curve_number") == top_curve and isinstance(idx, int) and 0 <= idx < len(plotted_ids):
            return int(plotted_ids[idx])
    return None
