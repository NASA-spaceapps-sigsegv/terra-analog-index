"""TAI-30 acceptance criteria: map layer (get_map_layer) and its figure (ui/map_view)."""

import json
import time

import numpy as np
import pandas as pd
import pytest

from tai import io, services
from tai.constants import DEFAULT_WEIGHTS
from tai.errors import InvalidWeightsError, TargetNotFoundError
from tai.models import MAP_CELL_COLUMNS, MapLayer, Weights
from ui import map_view

MOON = "moon_south_pole"


@pytest.fixture
def bundle(data_dir):
    return io.load_bundle(data_dir)


def layer_of(bundle, weights=DEFAULT_WEIGHTS, target=MOON) -> MapLayer:
    return services.get_map_layer(bundle, target, weights)


def by_cell(layer: MapLayer) -> pd.DataFrame:
    return layer.cells.set_index("cell_id")


# --- get_map_layer -----------------------------------------------------------


def test_layer_has_every_cell_and_the_contract_columns(bundle):
    layer = layer_of(bundle)
    assert tuple(layer.cells.columns) == MAP_CELL_COLUMNS
    assert layer.n_cells == 6 and layer.n_eligible == 5 and len(layer.cells) == 6
    assert layer.target_id == MOON and layer.weights.as_dict() == dict(DEFAULT_WEIGHTS)


def test_ineligible_cell_has_no_total_but_keeps_its_scores(bundle):
    cells = by_cell(layer_of(bundle))
    assert pd.isna(cells.loc[103, "total"]) and not cells.loc[103, "eligible"]
    assert cells.loc[103, "s_water_ice"] == pytest.approx(0.9)  # the value it does have is kept
    assert cells.drop(index=103)["total"].notna().all() and cells.drop(index=103)["eligible"].all()


def test_totals_are_the_same_as_the_ranking(bundle):
    cells = by_cell(layer_of(bundle))
    for item in services.get_ranking(bundle, MOON, DEFAULT_WEIGHTS).items:
        assert cells.loc[item.cell_id, "total"] == pytest.approx(item.total)


def test_moving_a_weight_changes_the_totals(bundle):
    before = by_cell(layer_of(bundle))["total"]
    after = by_cell(layer_of(bundle, dict(DEFAULT_WEIGHTS, terrain=0.0)))["total"]
    assert not np.allclose(before.dropna(), after.dropna())


def test_known_analog_comes_with_its_name(bundle):
    cells = by_cell(layer_of(bundle))
    assert cells.loc[105, "known_analog"] == "Atacama"
    assert cells.drop(index=105)["known_analog"].isna().all()


def test_all_weights_zero_still_gives_a_gray_layer(bundle):
    layer = layer_of(bundle, dict.fromkeys(DEFAULT_WEIGHTS, 0.0))
    assert layer.cells["total"].isna().all() and layer.n_eligible == 5 and layer.n_cells == 6


def test_json_shape_has_null_never_nan(bundle):
    body = layer_of(bundle).to_dict()
    text = json.dumps(body, allow_nan=False)  # NaN would raise ValueError
    cells = {c["cell_id"]: c for c in json.loads(text)["cells"]}
    assert cells[103]["total"] is None and cells[103]["s_temperature"] is None and cells[100]["known_analog"] is None
    assert set(cells[100]) == set(MAP_CELL_COLUMNS) and body["n_eligible"] == 5


def test_layer_does_not_modify_the_bundle(bundle):
    before = bundle.similarity[MOON].copy()
    layer_of(bundle)
    pd.testing.assert_frame_equal(bundle.similarity[MOON], before)


def test_errors(bundle):
    with pytest.raises(TargetNotFoundError):
        services.get_map_layer(bundle, "mars_gale", DEFAULT_WEIGHTS)
    with pytest.raises(InvalidWeightsError):
        services.get_map_layer(bundle, MOON, dict(DEFAULT_WEIGHTS, terrain=1.5))
    with pytest.raises(InvalidWeightsError):
        services.get_map_layer(bundle, MOON, {"terrain": 1.0})


# --- ui/map_view -------------------------------------------------------------


def trace(fig, name):
    found = [t for t in fig.data if t.name == name]
    assert len(found) == 1, f"there should be one trace named {name!r}, there are {len(found)}"
    return found[0]


def heat(fig, name):
    """The Heatmap with that name (the gray layer also has a legend entry with the same name)."""
    found = [t for t in fig.data if t.name == name and t.type == "heatmap"]
    assert len(found) == 1, f"there should be one heatmap named {name!r}, there are {len(found)}"
    return found[0]


def cell_pos(lat, lon) -> tuple[int, int]:
    li, lj = map_view._index([lat], [lon])
    return int(li[0]), int(lj[0])


def decode_png(uri: str) -> np.ndarray:
    """Decode the RGBA PNG (filter 0 per row) that map_view builds, to look at pixels."""
    import base64
    import struct
    import zlib

    assert uri.startswith("data:image/png;base64,")
    raw = base64.b64decode(uri.split(",", 1)[1])
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat, w, h = 8, b"", 0, 0
    while pos < len(raw):
        n, tag = struct.unpack(">I4s", raw[pos : pos + 8])
        body = raw[pos + 8 : pos + 8 + n]
        if tag == b"IHDR":
            w, h = struct.unpack(">II", body[:8])
        elif tag == b"IDAT":
            idat += body
        pos += 12 + n
    rows = np.frombuffer(zlib.decompress(idat), dtype=np.uint8).reshape(h, w * 4 + 1)
    assert (rows[:, 0] == 0).all()
    return rows[:, 1:].reshape(h, w, 4)


def one_cell_layer(lat, lon, total=0.5) -> MapLayer:
    cells = pd.DataFrame(
        {
            "cell_id": np.array([1], dtype="int32"), "lat": [lat], "lon": [lon], "country": ["Chile"], "total": [total],
            "s_terrain": [0.5], "s_temperature": [0.5], "s_water_ice": [0.5], "s_dust_wind": [np.nan], "bio_score": [0.0], "eligible": [True],
            "known_analog": [None],
        }
    )
    return MapLayer(target_id=MOON, weights=Weights(**DEFAULT_WEIGHTS), n_cells=1, n_eligible=1, cells=cells)


def spread_layer(totals) -> MapLayer:
    """One cell every 30° of longitude at 60° latitude: far from the pole, where a cell spans several pixels."""
    n = len(totals)
    total = np.array(totals, dtype="float64")
    cells = pd.DataFrame(
        {
            "cell_id": np.arange(n, dtype="int32"), "lat": np.full(n, -60.5), "lon": 10.5 + 30.0 * np.arange(n), "country": ["Chile"] * n,
            "total": total, "s_terrain": [0.5] * n, "s_temperature": [0.5] * n, "s_water_ice": [0.5] * n, "s_dust_wind": [np.nan] * n, "bio_score": [0.0] * n,
            "eligible": ~np.isnan(total), "known_analog": [None] * n,
        }
    )
    return MapLayer(target_id=MOON, weights=Weights(**DEFAULT_WEIGHTS), n_cells=n, n_eligible=int((~np.isnan(total)).sum()), cells=cells)


def pixels_of_cells(layer: MapLayer) -> list[tuple]:
    """The RGB color of the south pole image at the center of each cell."""
    image = trace(map_view.build_figure(layer, "south_pole"), "Cells")
    rgba = decode_png(image.source)
    x, y = map_view._project(layer.cells["lat"].to_numpy(), layer.cells["lon"].to_numpy(), -1)
    col = np.floor((x - image.x0) / image.dx).astype(int)
    row = np.floor((y - image.y0) / image.dy).astype(int)
    return [tuple(int(v) for v in rgba[r, c, :3]) for r, c in zip(row, col)]


def figure(bundle, projection="world", weights=DEFAULT_WEIGHTS, selected=None, **kwargs):
    return map_view.build_figure(layer_of(bundle, weights), projection, selected, **kwargs)


# World -----------------------------------------------------------------------


def test_world_cells_are_a_one_degree_heatmap_not_points(bundle):
    cells = by_cell(layer_of(bundle))
    z = np.asarray(trace(figure(bundle), "Eligible cells").z, dtype=float)
    assert z.shape == (180, 360)  # one pixel per 1° cell: zooming in shows exact squares
    assert np.isfinite(z).sum() == 5  # the five eligible ones; not 103
    for cid in (100, 104):
        li, lj = cell_pos(cells.loc[cid, "lat"], cells.loc[cid, "lon"])
        assert z[li, lj] == pytest.approx(cells.loc[cid, "total"])
    li, lj = cell_pos(cells.loc[103, "lat"], cells.loc[103, "lon"])
    assert np.isnan(z[li, lj])


def test_world_without_ineligible_cells_has_no_gray_layer(bundle):
    full = layer_of(bundle)
    cells = full.cells.copy()
    cells.loc[cells["total"].isna(), "total"] = 0.4
    fig = map_view.build_figure(MapLayer(target_id=MOON, weights=full.weights, n_cells=6, n_eligible=6, cells=cells), "world")
    assert [t.name for t in fig.data if t.type == "heatmap"] == ["Eligible cells"]  # an empty layer is not sent


def test_world_uses_viridis_from_0_to_1_with_a_color_bar(bundle):
    heat = trace(figure(bundle), "Eligible cells")
    assert heat.zmin == 0 and heat.zmax == 1 and heat.colorscale[0][0] == 0 and heat.colorscale[-1][0] == 1
    assert len(heat.colorscale) >= 8 and heat.colorbar.title.text == "Total score"  # Viridis


def test_world_hover_shows_place_location_and_total(bundle):
    heat = trace(figure(bundle), "Eligible cells")
    for piece in ("%{x", "%{y", "Total score", "%{z", "%{text}"):
        assert piece in heat.hovertemplate
    assert heat.hoverongaps is False  # hover only where there is a cell
    # The five scores are not sent for every cell (it was most of the bytes of each rerun): they are in the card, in the
    # ranking and in the hover of the numbered dots.
    assert heat.customdata is None and "Terrain" not in heat.hovertemplate


def test_world_hover_names_the_analog_and_the_country(bundle):
    heat = trace(figure(bundle), "Eligible cells")
    cells = by_cell(layer_of(bundle))
    li, lj = cell_pos(cells.loc[105, "lat"], cells.loc[105, "lon"])
    assert "Atacama" in heat.text[li][lj] and "Known analog" in heat.text[li][lj]
    li, lj = cell_pos(cells.loc[100, "lat"], cells.loc[100, "lon"])
    assert heat.text[li][lj] == "Chile"


def test_world_insufficient_data_cell_is_gray_and_says_so_on_hover(bundle):
    fig = figure(bundle)
    cells = by_cell(layer_of(bundle))
    gray = heat(fig, "Insufficient data")
    li, lj = cell_pos(cells.loc[103, "lat"], cells.loc[103, "lon"])
    z = np.asarray(gray.z, dtype=float)
    assert np.isfinite(z).sum() == 1 and z[li, lj] == 1.0
    assert "Insufficient data" in gray.hovertemplate and "Insufficient data" not in trace(fig, "Eligible cells").hovertemplate
    assert gray.colorscale[0][1] == gray.colorscale[-1][1] == map_view.GRAY
    assert "Insufficient data" in [t.name for t in fig.data if t.showlegend]  # legend entry


def test_world_all_weights_zero_draws_every_cell_gray(bundle):
    fig = figure(bundle, weights=dict.fromkeys(DEFAULT_WEIGHTS, 0.0))
    assert np.isfinite(np.asarray(heat(fig, "Insufficient data").z, dtype=float)).sum() == 6
    assert np.isfinite(np.asarray(trace(fig, "Eligible cells").z, dtype=float)).sum() == 0


def test_world_axes_are_equal_aspect_and_cover_the_globe(bundle):
    fig = figure(bundle)
    assert tuple(fig.layout.xaxis.range) == (-180, 180) and tuple(fig.layout.yaxis.range) == (-90, 90)
    assert fig.layout.yaxis.scaleanchor == "x" and fig.layout.dragmode == "pan"


# Polos -----------------------------------------------------------------------


@pytest.mark.parametrize("hemisphere,lon,x_sign,y_sign", [(-1, 0.0, 0, 1), (-1, 90.0, 1, 0), (1, 0.0, 0, -1), (1, 90.0, 1, 0)])
def test_polar_projection_orientation(hemisphere, lon, x_sign, y_sign):
    x, y = map_view._project(np.array([hemisphere * 45.0]), np.array([lon]), hemisphere)
    rho = np.cos(np.radians(45.0))
    assert x[0] == pytest.approx(x_sign * rho, abs=1e-9) and y[0] == pytest.approx(y_sign * rho, abs=1e-9)


@pytest.mark.parametrize(
    "projection,lat,lon",
    [("south_pole", -45.5, 0.5), ("south_pole", -45.5, 90.5), ("south_pole", -70.5, -135.5), ("north_pole", 45.5, 0.5),
     ("north_pole", 45.5, 90.5), ("north_pole", 70.5, -135.5)],
)
def test_polar_image_puts_each_cell_where_the_projection_says(projection, lat, lon):
    """The PNG is decoded: the center of what is painted matches the cell's (x, y) on the figure axis."""
    image = trace(map_view.build_figure(one_cell_layer(lat, lon), projection), "Cells")
    rgba = decode_png(image.source)
    inside_disc = rgba[..., 3] == 255
    painted = inside_disc & (rgba[..., :3] != map_view._OCEAN_RGB).any(axis=2)
    rows, cols = np.nonzero(painted)
    assert len(rows) > 5  # the cell spans several pixels
    x = image.x0 + cols.mean() * image.dx  # row 0 of the image is y0, and it grows upward (dy > 0)
    y = image.y0 + rows.mean() * image.dy
    expected_x, expected_y = map_view._project(np.array([lat]), np.array([lon]), -1 if lat < 0 else 1)
    assert x == pytest.approx(expected_x[0], abs=0.012) and y == pytest.approx(expected_y[0], abs=0.012)


def test_polar_image_is_a_png_with_transparent_corners_and_an_ocean_disc(bundle):
    image = trace(figure(bundle, "south_pole"), "Cells")
    rgba = decode_png(image.source)
    assert rgba.shape == (map_view.POLAR_PX, map_view.POLAR_PX, 4)
    assert rgba[0, 0, 3] == 0  # outside the globe: transparent
    mid = map_view.POLAR_PX // 2
    assert rgba[mid + 200, mid + 200, 3] == 255 and (rgba[mid + 200, mid + 200, :3] == map_view._OCEAN_RGB).all()  # mar


def test_polar_image_scale_is_the_unit_disc(bundle):
    image = trace(figure(bundle, "south_pole"), "Cells")
    assert image.dx == pytest.approx(2 / map_view.POLAR_PX) and image.dy == pytest.approx(2 / map_view.POLAR_PX)
    assert image.x0 == pytest.approx(-1 + image.dx / 2) and image.y0 == pytest.approx(-1 + image.dy / 2)
    assert image.dx > 0 and image.dy > 0  # a negative dy would flip the image


def test_polar_image_colors_use_viridis_and_gray_for_cells_without_total():
    low, high, none = pixels_of_cells(spread_layer([0.1, 0.9, np.nan]))
    assert low == tuple(int(v) for v in map_view._LUT[round(0.1 * 255)])
    assert high == tuple(int(v) for v in map_view._LUT[round(0.9 * 255)])
    assert none == tuple(int(v) for v in map_view._GRAY_RGB)  # no total: gray
    assert len({low, high, none}) == 3


def test_polar_image_is_cached_for_the_same_totals(monkeypatch):
    calls = []
    real = map_view._polar_image
    monkeypatch.setattr(map_view, "_polar_image", lambda *a: calls.append(1) or real(*a))
    map_view._IMAGE_CACHE.clear()
    layer = big_layer(n=300, seed=7)
    first = trace(map_view.build_figure(layer, "south_pole"), "Cells").source
    again = trace(map_view.build_figure(layer, "south_pole", 5), "Cells").source
    assert first == again and len(calls) == 1  # not recomputed when a cell is picked
    map_view.build_figure(big_layer(n=300, seed=8), "south_pole")
    assert len(calls) == 2  # other totals: another image


def test_polar_hover_has_one_transparent_webgl_marker_per_visible_cell(bundle):
    fig = figure(bundle, "south_pole")
    cursor = trace(fig, "Eligible cells")
    assert cursor.type == "scattergl" and len(cursor.x) == 5  # the five eligible cells of the southern hemisphere
    assert cursor.marker.color == map_view.HOVER_FILL == "rgba(0,0,0,0)"
    assert "%{text}" in cursor.hovertemplate and "Total score" in cursor.hovertemplate
    assert "Chile" in list(cursor.text) and any("Atacama" in t for t in cursor.text)
    assert cursor.customdata.shape == (5, 3) and str(cursor.customdata.dtype) == "float32"  # lat, lon and total: numbers, not text
    gray = trace(fig, map_view.NO_SCORE_NAME)  # 103 is not eligible: its own trace, with a text
    assert len(gray.x) == 1 and "Insufficient data" in gray.hovertext[0] and "Lat -89.5" in gray.hovertext[0]
    assert "Total score" not in gray.hovertext[0]


def test_north_view_hides_the_cells_of_the_southern_hemisphere(bundle):
    assert len(trace(figure(bundle, "north_pole"), "Eligible cells").x) == 0


def test_polar_all_weights_zero_paints_the_cells_gray():
    gray = tuple(int(v) for v in map_view._GRAY_RGB)
    assert pixels_of_cells(spread_layer([np.nan, np.nan, np.nan])) == [gray] * 3


def test_polar_axes_are_equal_aspect_and_hidden(bundle):
    fig = figure(bundle, "south_pole")
    assert fig.layout.yaxis.scaleanchor == "x" and fig.layout.xaxis.visible is False and fig.layout.yaxis.visible is False


def test_polar_views_keep_the_color_bar(bundle):
    for projection in ("south_pole", "north_pole"):
        bar = trace(figure(bundle, projection), "Total score").marker
        assert bar.showscale is True and bar.cmin == 0 and bar.cmax == 1 and bar.colorbar.title.text == "Total score"


# Rings and selected cell (the three views) ------------------------------------


@pytest.mark.parametrize("view", ["world", "south_pole"])
def test_each_known_analog_is_one_white_ring(bundle, view):
    ring = trace(figure(bundle, view), "Known analog")
    assert len(ring.x) == 1 and ring.marker.symbol == "circle-open" and ring.marker.color == "#ffffff"
    assert ring.marker.line.width >= 2 and ring.hoverinfo == "skip"  # the hover text comes from the cells


def test_a_ring_is_centered_on_all_the_cells_of_its_analog():
    layer = big_layer()  # 41 cells with the same analog
    ring = trace(map_view.build_figure(layer, "world"), "Known analog")
    assert len(ring.y) == 1
    cells = layer.cells[layer.cells["known_analog"].notna()]
    assert ring.y[0] == pytest.approx(cells["lat"].mean(), abs=1e-3)


def test_the_ring_center_does_not_break_across_the_dateline():
    lon = np.array([179.5, -179.5, 178.5, -178.5])
    cells = pd.DataFrame({"lat": [-77.5] * 4, "lon": lon, "known_analog": ["A"] * 4})
    _, centers = map_view._analog_centers(cells)
    assert abs(abs(centers[0]) - 180) < 0.6  # near ±180, not at 0


def test_figure_without_analogs_has_an_empty_ring_trace():
    layer = big_layer()
    empty = MapLayer(target_id=MOON, weights=layer.weights, n_cells=layer.n_cells, n_eligible=layer.n_eligible,
                     cells=layer.cells.assign(known_analog=None))
    assert len(trace(map_view.build_figure(empty, "world"), "Known analog").x) == 0


@pytest.mark.parametrize("view", ["world", "south_pole"])
def test_selected_cell_is_an_outline_that_scales_with_zoom_plus_a_bigger_red_marker(bundle, view):
    fig = figure(bundle, view, selected=104)
    marker = trace(fig, "Selected cell")
    assert len(marker.x) == 1 and marker.marker.line.color == map_view.SELECTED_COLOR
    assert marker.marker.size > trace(fig, "Known analog").marker.size  # frames the ring
    outline = trace(fig, "Selected cell outline")
    assert len(outline.x) >= 5 and outline.x[0] == outline.x[-1] and outline.y[0] == outline.y[-1]  # closed
    assert outline.line.color == map_view.SELECTED_COLOR


@pytest.mark.parametrize("view", ["world", "south_pole"])
def test_a_selected_cell_that_is_not_in_the_layer_draws_nothing(bundle, view):
    fig = figure(bundle, view, selected=999999)
    assert len(trace(fig, "Selected cell").x) == 0 and len(trace(fig, "Selected cell outline").x) == 0


def test_cell_outline_is_a_closed_one_degree_square():
    for steps in (1, 6):
        lats, lons = map_view._cell_outline(10.5, 20.5, steps)
        assert len(lats) == len(lons) == 4 * steps + 1 and (lats[0], lons[0]) == (lats[-1], lons[-1])
        assert lats.max() - lats.min() == pytest.approx(1.0) and lons.max() - lons.min() == pytest.approx(1.0)


def test_unknown_projection_is_rejected(bundle):
    with pytest.raises(ValueError):
        map_view.build_figure(layer_of(bundle), "mercator")


# --- performance (criterion: the map changes in under 1 s when moving a slider) -


def big_layer(n=21_357, seed=0) -> MapLayer:
    rng = np.random.default_rng(seed)
    total = rng.random(n)
    total[rng.random(n) < 0.05] = np.nan
    cells = pd.DataFrame(
        {
            "cell_id": np.arange(n, dtype="int32"),
            "lat": rng.uniform(-89.5, 89.5, n).astype("float32"),
            "lon": rng.uniform(-179.5, 179.5, n).astype("float32"),
            "country": pd.array(rng.choice(["Chile", "China", None], n), dtype=object),
            "total": total,
            "s_terrain": rng.random(n).astype("float32"),
            "s_temperature": rng.random(n).astype("float32"),
            "s_water_ice": rng.random(n).astype("float32"),
            "s_dust_wind": np.full(n, np.nan, dtype="float32"),
            "bio_score": rng.random(n).astype("float32"),
            "eligible": ~np.isnan(total),
            "known_analog": pd.array([None] * n, dtype=object),
        }
    )
    cells.loc[:40, "known_analog"] = "Test analog"
    return MapLayer(target_id=MOON, weights=Weights(**DEFAULT_WEIGHTS), n_cells=n, n_eligible=int((~np.isnan(total)).sum()), cells=cells)


@pytest.mark.parametrize("projection", ["world", "south_pole", "north_pole"])
def test_figure_of_the_whole_grid_is_built_in_well_under_a_second(projection):
    layer = big_layer()
    map_view.build_figure(layer, projection, 5)  # warm-up
    best = min(_timed(map_view.build_figure, layer, projection, 5) for _ in range(3))
    assert best < 0.5, f"the figure took {best * 1000:.0f} ms"


@pytest.mark.parametrize("projection", ["south_pole", "north_pole"])
def test_polar_image_is_computed_in_under_a_second_when_the_totals_change(projection):
    layer = big_layer()
    map_view._IMAGE_CACHE.clear()
    elapsed = _timed(map_view.build_figure, layer, projection)  # no cache: what moving a slider costs in the polar views
    assert elapsed < 1.0, f"the polar image took {elapsed * 1000:.0f} ms"


@pytest.mark.parametrize("projection", ["world", "south_pole", "north_pole"])
def test_the_whole_grid_is_a_handful_of_traces_not_one_per_cell(projection):
    # Few traces is what makes panning and zooming smooth: the browser draws a raster, not thousands of polygons.
    assert len(map_view.build_figure(big_layer(), projection, 5).data) <= 12


def _timed(fn, *args) -> float:
    t0 = time.perf_counter()
    fn(*args)
    return time.perf_counter() - t0


@pytest.mark.parametrize(
    "projection, x_limits, y_limits",
    [("world", (-180, 180), (-90, 90)), ("south_pole", (-1.03, 1.03), (-1.03, 1.03)), ("north_pole", (-1.03, 1.03), (-1.03, 1.03))],
)
def test_the_view_limits_are_the_whole_map_and_start_there(bundle, projection, x_limits, y_limits):
    fig = figure(bundle, projection)
    limits = fig.layout.meta["tai_limits"]
    assert tuple(limits["x"]) == x_limits and tuple(limits["y"]) == y_limits
    assert tuple(fig.layout.xaxis.range) == x_limits and tuple(fig.layout.yaxis.range) == y_limits  # it opens on the whole map
    # minallowed/maxallowed cut the range past the edge instead of shifting it (a drag "zoomed" the map into a corner
    # and zooming out could not bring it back): the guard script replaces them
    assert fig.layout.xaxis.minallowed is None and fig.layout.yaxis.maxallowed is None


def test_the_guard_script_shifts_the_view_and_caps_its_size_for_every_chart():
    js = map_view.VIEW_GUARD_JS
    assert "plotly_relayout" in js and "tai_limits" in js and "Plotly.relayout" in js and "MutationObserver" in js
    assert "window.__taiViewGuard" in js  # installed once
    assert "k > 1" in js and "x1 += lim.x[0] - x0" in js  # capped to the whole map, then shifted, never cut


# --- numbered dots, selection, phone layout, weight (TAI-40) ---------------------------------------------------------


@pytest.fixture
def apart(monkeypatch):
    """The six test cells sit within a few degrees of each other: without clustering they stay separate dots."""
    monkeypatch.setitem(map_view.CLUSTER, "world", 0.0)
    monkeypatch.setitem(map_view.CLUSTER, "polar", 0.0)


@pytest.mark.parametrize("view", ["world", "south_pole"])
def test_best_cells_are_numbered_dots_with_all_their_scores_on_hover(bundle, apart, view):
    dots = trace(figure(bundle, view, top_cells=[104, 100, 105]), "Top 3")
    assert sorted(dots.text) == ["1", "2", "3"] and sorted(dots.customdata) == [100, 104, 105]  # every one gets its dot
    assert dots.text[-1] == "1" and dots.customdata[-1] == 104  # the best rank is drawn last: on top of the others
    assert dots.mode == "markers+text" and dots.hoverinfo == "text"
    hover = dict(zip(dots.text, dots.hovertext))
    first = hover["1"]  # 104 has no temperature
    assert "#1" in first and "Total score" in first and "Terrain: 0.60" in first and "Temperature: no data" in first
    assert "Water and ice: 0.60" in first and "Astrobiology: 0.10" in first and "Tap or click" in first
    assert "Known analog: Atacama" in hover["3"]


def test_the_numbers_are_the_rank_even_if_a_cell_is_not_drawn(bundle, apart):
    dots = trace(figure(bundle, "world", top_cells=[999999, 104]), "Top 2")  # the first one is not in the layer
    assert list(dots.text) == ["2"] and list(dots.customdata) == [104]


def test_the_north_view_draws_no_numbered_dots_for_southern_cells(bundle):
    assert "Top 1" not in [t.name for t in figure(bundle, "north_pole", top_cells=[104]).data]


def test_without_top_cells_there_are_no_numbered_dots(bundle):
    assert not [t for t in figure(bundle).data if t.name.startswith("Top ")]


def test_a_selection_does_not_fade_the_rings_and_the_dots(bundle):
    fig = figure(bundle, top_cells=[104])
    assert trace(fig, "Known analog").unselected.marker.opacity == 1
    assert trace(fig, "Top 1").unselected.marker.opacity == 1


def test_cell_from_selection_reads_the_tapped_numbered_dot():
    sel = {"selection": {"points": [{"curve_number": 3, "point_index": 1}], "point_indices": [1]}}
    assert map_view.cell_from_selection(sel, 3, [10, 20, 30]) == 20
    assert map_view.cell_from_selection(sel, 4, [10, 20, 30]) is None  # a point of another trace
    assert map_view.cell_from_selection(sel, 3, [10]) is None  # out of range
    assert map_view.cell_from_selection({"selection": {"points": []}}, 3, [10]) is None  # a click on the empty map
    assert map_view.cell_from_selection(None, None, []) is None


@pytest.mark.parametrize("view", ["world", "south_pole"])
def test_the_phone_layout_is_shorter_with_the_color_bar_below_and_one_finger_scrolling(bundle, view):
    full, phone = figure(bundle, view), figure(bundle, view, compact=True)
    assert phone.layout.height < full.layout.height and full.layout.dragmode == "pan" and phone.layout.dragmode is False
    bar = (lambda f: trace(f, "Eligible cells").colorbar) if view == "world" else (lambda f: trace(f, "Total score").marker.colorbar)
    assert bar(phone).orientation == "h"  # below the map, not a column that eats the width
    assert (bar(full).orientation == "h") == (view == "world")  # on a wide screen only the poles keep the column
    assert phone.layout.showlegend is False and full.layout.showlegend is not False  # the phone has the key under the map instead


def test_changing_view_rev_resets_the_zoom(bundle):
    assert figure(bundle).layout.uirevision == "world-0" and figure(bundle, view_rev=2).layout.uirevision == "world-2"
    assert figure(bundle, "south_pole", view_rev=2).layout.uirevision == "south_pole-2"


@pytest.mark.parametrize("projection, limit", [("world", 1_200_000), ("south_pole", 900_000), ("north_pole", 900_000)])
def test_the_figure_sent_on_every_rerun_stays_light(projection, limit):
    """Each rerun resends the figure. It was 4-5 MB (world) and about 3 MB (poles): the free server and a phone felt it."""
    import plotly.io as pio

    layer = big_layer()  # like the real data, every cell has a total: no gray layer
    cells = layer.cells.assign(total=layer.cells["total"].fillna(0.4))
    layer = MapLayer(target_id=MOON, weights=layer.weights, n_cells=layer.n_cells, n_eligible=layer.n_cells, cells=cells)
    fig = map_view.build_figure(layer, projection, 5, top_cells=range(20))
    assert len(pio.to_json(fig)) < limit


def test_all_the_best_cells_are_marked_by_default(bundle):
    assert len(trace(figure(bundle, "world", top_cells=[104, 100, 105]), "Top 3").x) == 3
    assert map_view.CLUSTER == {"world": 0.0, "polar": 0.0}


def test_dots_that_would_pile_up_can_become_one_with_the_others_in_its_hover(bundle, monkeypatch):
    monkeypatch.setitem(map_view.CLUSTER, "world", 10.0)  # optional: off by default, every cell is marked
    dots = trace(figure(bundle, "world", top_cells=[104, 100, 105]), "Top 3")
    assert list(dots.text) == ["1"] and list(dots.customdata) == [104]  # the best rank stays on the dot
    assert "Also here: #2, #3" in dots.hovertext[0] and "Terrain: 0.60" in dots.hovertext[0]


def test_declutter_keeps_the_best_of_each_neighbourhood_in_rank_order():
    keep, owner = map_view._declutter([0.0, 1.0, 50.0, 51.0, 3.0], [0.0, 0.0, 0.0, 0.0, 0.0], 6.0)
    assert keep == [0, 2] and owner == [0, 0, 1, 1, 0]
    assert map_view._declutter([0.0, 1.0], [0.0, 0.0], 0.0) == ([0, 1], [0, 1])  # radius 0: nothing joins


def test_a_known_analog_keeps_its_ring_around_the_numbered_dot():
    assert map_view.RING_SIZE > map_view.RANK_SIZE and map_view.SELECTED_SIZE > map_view.RING_SIZE
