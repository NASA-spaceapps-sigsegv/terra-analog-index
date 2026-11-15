"""Criterios de aceptación de TAI-30: capa del mapa (get_map_layer) y su figura (ui/map_view)."""

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
    assert cells.loc[103, "s_water_ice"] == pytest.approx(0.9)  # el dato que sí tiene se conserva
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
    text = json.dumps(body, allow_nan=False)  # NaN lanzaría ValueError
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
    assert len(found) == 1, f"debería haber una traza llamada {name!r}, hay {len(found)}"
    return found[0]


def heat(fig, name):
    """El Heatmap de ese nombre (la capa gris tiene además una entrada en la leyenda con el mismo nombre)."""
    found = [t for t in fig.data if t.name == name and t.type == "heatmap"]
    assert len(found) == 1, f"debería haber un heatmap llamado {name!r}, hay {len(found)}"
    return found[0]


def cell_pos(lat, lon) -> tuple[int, int]:
    li, lj = map_view._index([lat], [lon])
    return int(li[0]), int(lj[0])


def decode_png(uri: str) -> np.ndarray:
    """Decodifica el PNG RGBA (filtro 0 por fila) que arma map_view, para mirar píxeles."""
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
            "s_terrain": [0.5], "s_temperature": [0.5], "s_water_ice": [0.5], "bio_score": [0.0], "eligible": [True],
            "known_analog": [None],
        }
    )
    return MapLayer(target_id=MOON, weights=Weights(**DEFAULT_WEIGHTS), n_cells=1, n_eligible=1, cells=cells)


def spread_layer(totals) -> MapLayer:
    """Una celda cada 30° de longitud a 60° de latitud: lejos del polo, donde una celda ocupa varios píxeles."""
    n = len(totals)
    total = np.array(totals, dtype="float64")
    cells = pd.DataFrame(
        {
            "cell_id": np.arange(n, dtype="int32"), "lat": np.full(n, -60.5), "lon": 10.5 + 30.0 * np.arange(n), "country": ["Chile"] * n,
            "total": total, "s_terrain": [0.5] * n, "s_temperature": [0.5] * n, "s_water_ice": [0.5] * n, "bio_score": [0.0] * n,
            "eligible": ~np.isnan(total), "known_analog": [None] * n,
        }
    )
    return MapLayer(target_id=MOON, weights=Weights(**DEFAULT_WEIGHTS), n_cells=n, n_eligible=int((~np.isnan(total)).sum()), cells=cells)


def pixels_of_cells(layer: MapLayer) -> list[tuple]:
    """El color RGB que tiene la imagen del polo sur en el centro de cada celda."""
    image = trace(map_view.build_figure(layer, "south_pole"), "Celdas")
    rgba = decode_png(image.source)
    x, y = map_view._project(layer.cells["lat"].to_numpy(), layer.cells["lon"].to_numpy(), -1)
    col = np.floor((x - image.x0) / image.dx).astype(int)
    row = np.floor((y - image.y0) / image.dy).astype(int)
    return [tuple(int(v) for v in rgba[r, c, :3]) for r, c in zip(row, col)]


def figure(bundle, projection="world", weights=DEFAULT_WEIGHTS, selected=None):
    return map_view.build_figure(layer_of(bundle, weights), projection, selected)


# Mundo -----------------------------------------------------------------------


def test_world_cells_are_a_one_degree_heatmap_not_points(bundle):
    cells = by_cell(layer_of(bundle))
    z = np.asarray(trace(figure(bundle), "Celdas elegibles").z, dtype=float)
    assert z.shape == (180, 360)  # un píxel por celda de 1°: al ampliar se ven cuadrados exactos
    assert np.isfinite(z).sum() == 5  # las cinco elegibles; la 103 no
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
    assert [t.name for t in fig.data if t.type == "heatmap"] == ["Celdas elegibles"]  # no se manda una capa vacía


def test_world_uses_viridis_from_0_to_1_with_a_color_bar(bundle):
    heat = trace(figure(bundle), "Celdas elegibles")
    assert heat.zmin == 0 and heat.zmax == 1 and heat.colorscale[0][0] == 0 and heat.colorscale[-1][0] == 1
    assert len(heat.colorscale) >= 8 and heat.colorbar.title.text == "Puntaje total"  # Viridis


def test_world_hover_shows_location_total_and_the_four_dimensions(bundle):
    heat = trace(figure(bundle), "Celdas elegibles")
    for piece in ("%{x", "%{y", "Puntaje total", "%{z", "%{text}", "%{customdata}"):
        assert piece in heat.hovertemplate
    assert heat.hoverongaps is False  # solo hay cursor donde hay celda
    cells = by_cell(layer_of(bundle))
    li, lj = cell_pos(cells.loc[104, "lat"], cells.loc[104, "lon"])  # la 104 no tiene temperatura
    tail = heat.customdata[li][lj]
    assert "Terreno: 0.60" in tail and "Temperatura: sin dato" in tail and "Agua y hielo: 0.60" in tail and "Astrobiología: 0.10" in tail


def test_world_hover_names_the_analog_and_the_country(bundle):
    heat = trace(figure(bundle), "Celdas elegibles")
    cells = by_cell(layer_of(bundle))
    li, lj = cell_pos(cells.loc[105, "lat"], cells.loc[105, "lon"])
    assert "Atacama" in heat.text[li][lj] and "Análogo conocido" in heat.text[li][lj]
    li, lj = cell_pos(cells.loc[100, "lat"], cells.loc[100, "lon"])
    assert heat.text[li][lj] == "Chile"


def test_world_insufficient_data_cell_is_gray_and_says_so_on_hover(bundle):
    fig = figure(bundle)
    cells = by_cell(layer_of(bundle))
    gray = heat(fig, "Datos insuficientes")
    li, lj = cell_pos(cells.loc[103, "lat"], cells.loc[103, "lon"])
    z = np.asarray(gray.z, dtype=float)
    assert np.isfinite(z).sum() == 1 and z[li, lj] == 1.0
    assert "Datos insuficientes" in gray.hovertemplate and "Datos insuficientes" not in trace(fig, "Celdas elegibles").hovertemplate
    assert gray.colorscale[0][1] == gray.colorscale[-1][1] == map_view.GRAY
    assert "Datos insuficientes" in [t.name for t in fig.data if t.showlegend]  # entrada en la leyenda


def test_world_all_weights_zero_draws_every_cell_gray(bundle):
    fig = figure(bundle, weights=dict.fromkeys(DEFAULT_WEIGHTS, 0.0))
    assert np.isfinite(np.asarray(heat(fig, "Datos insuficientes").z, dtype=float)).sum() == 6
    assert np.isfinite(np.asarray(trace(fig, "Celdas elegibles").z, dtype=float)).sum() == 0


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
    """Se decodifica el PNG: el centro de lo pintado coincide con el (x, y) de la celda en el eje de la figura."""
    image = trace(map_view.build_figure(one_cell_layer(lat, lon), projection), "Celdas")
    rgba = decode_png(image.source)
    inside_disc = rgba[..., 3] == 255
    painted = inside_disc & (rgba[..., :3] != map_view._OCEAN_RGB).any(axis=2)
    rows, cols = np.nonzero(painted)
    assert len(rows) > 5  # la celda ocupa varios píxeles
    x = image.x0 + cols.mean() * image.dx  # la fila 0 de la imagen es y0, y crece hacia arriba (dy > 0)
    y = image.y0 + rows.mean() * image.dy
    expected_x, expected_y = map_view._project(np.array([lat]), np.array([lon]), -1 if lat < 0 else 1)
    assert x == pytest.approx(expected_x[0], abs=0.012) and y == pytest.approx(expected_y[0], abs=0.012)


def test_polar_image_is_a_png_with_transparent_corners_and_an_ocean_disc(bundle):
    image = trace(figure(bundle, "south_pole"), "Celdas")
    rgba = decode_png(image.source)
    assert rgba.shape == (map_view.POLAR_PX, map_view.POLAR_PX, 4)
    assert rgba[0, 0, 3] == 0  # fuera del globo: transparente
    mid = map_view.POLAR_PX // 2
    assert rgba[mid + 200, mid + 200, 3] == 255 and (rgba[mid + 200, mid + 200, :3] == map_view._OCEAN_RGB).all()  # mar


def test_polar_image_scale_is_the_unit_disc(bundle):
    image = trace(figure(bundle, "south_pole"), "Celdas")
    assert image.dx == pytest.approx(2 / map_view.POLAR_PX) and image.dy == pytest.approx(2 / map_view.POLAR_PX)
    assert image.x0 == pytest.approx(-1 + image.dx / 2) and image.y0 == pytest.approx(-1 + image.dy / 2)
    assert image.dx > 0 and image.dy > 0  # un dy negativo daría vuelta la imagen


def test_polar_image_colors_use_viridis_and_gray_for_cells_without_total():
    low, high, none = pixels_of_cells(spread_layer([0.1, 0.9, np.nan]))
    assert low == tuple(int(v) for v in map_view._LUT[round(0.1 * 255)])
    assert high == tuple(int(v) for v in map_view._LUT[round(0.9 * 255)])
    assert none == tuple(int(v) for v in map_view._GRAY_RGB)  # sin total: gris
    assert len({low, high, none}) == 3


def test_polar_image_is_cached_for_the_same_totals(monkeypatch):
    calls = []
    real = map_view._polar_image
    monkeypatch.setattr(map_view, "_polar_image", lambda *a: calls.append(1) or real(*a))
    map_view._IMAGE_CACHE.clear()
    layer = big_layer(n=300, seed=7)
    first = trace(map_view.build_figure(layer, "south_pole"), "Celdas").source
    again = trace(map_view.build_figure(layer, "south_pole", 5), "Celdas").source
    assert first == again and len(calls) == 1  # no se vuelve a calcular al elegir una celda
    map_view.build_figure(big_layer(n=300, seed=8), "south_pole")
    assert len(calls) == 2  # otros totales: otra imagen


def test_polar_hover_has_one_transparent_webgl_marker_per_visible_cell(bundle):
    cursor = trace(figure(bundle, "south_pole"), "Celdas elegibles")
    assert cursor.type == "scattergl" and len(cursor.x) == 6  # las seis celdas de prueba están en el hemisferio sur
    assert cursor.marker.color == map_view.HOVER_FILL == "rgba(0,0,0,0)" and cursor.hoverinfo == "text"
    gray = next(t for t in cursor.hovertext if "Datos insuficientes" in t)  # la 103 no es elegible
    assert "Lat -89.5" in gray and "Puntaje total" not in gray
    ok = next(t for t in cursor.hovertext if "Terreno: 0.60" in t)  # la 104
    assert "Puntaje total" in ok and "Temperatura: sin dato" in ok and "Chile" in ok
    assert any("Atacama" in t for t in cursor.hovertext)


def test_north_view_hides_the_cells_of_the_southern_hemisphere(bundle):
    assert len(trace(figure(bundle, "north_pole"), "Celdas elegibles").x) == 0


def test_polar_all_weights_zero_paints_the_cells_gray():
    gray = tuple(int(v) for v in map_view._GRAY_RGB)
    assert pixels_of_cells(spread_layer([np.nan, np.nan, np.nan])) == [gray] * 3


def test_polar_axes_are_equal_aspect_and_hidden(bundle):
    fig = figure(bundle, "south_pole")
    assert fig.layout.yaxis.scaleanchor == "x" and fig.layout.xaxis.visible is False and fig.layout.yaxis.visible is False


def test_polar_views_keep_the_color_bar(bundle):
    for projection in ("south_pole", "north_pole"):
        bar = trace(figure(bundle, projection), "Puntaje total").marker
        assert bar.showscale is True and bar.cmin == 0 and bar.cmax == 1 and bar.colorbar.title.text == "Puntaje total"


# Anillos y celda elegida (las tres vistas) ------------------------------------


@pytest.mark.parametrize("view", ["world", "south_pole"])
def test_each_known_analog_is_one_white_ring(bundle, view):
    ring = trace(figure(bundle, view), "Análogo conocido")
    assert len(ring.x) == 1 and ring.marker.symbol == "circle-open" and ring.marker.color == "#ffffff"
    assert ring.marker.line.width >= 2 and ring.hoverinfo == "skip"  # el texto del cursor sale de las celdas


def test_a_ring_is_centered_on_all_the_cells_of_its_analog():
    layer = big_layer()  # 41 celdas con el mismo análogo
    ring = trace(map_view.build_figure(layer, "world"), "Análogo conocido")
    assert len(ring.y) == 1
    cells = layer.cells[layer.cells["known_analog"].notna()]
    assert ring.y[0] == pytest.approx(cells["lat"].mean(), abs=1e-3)


def test_the_ring_center_does_not_break_across_the_dateline():
    lon = np.array([179.5, -179.5, 178.5, -178.5])
    cells = pd.DataFrame({"lat": [-77.5] * 4, "lon": lon, "known_analog": ["A"] * 4})
    _, centers = map_view._analog_centers(cells)
    assert abs(abs(centers[0]) - 180) < 0.6  # cerca de ±180, no en 0


def test_figure_without_analogs_has_an_empty_ring_trace():
    layer = big_layer()
    empty = MapLayer(target_id=MOON, weights=layer.weights, n_cells=layer.n_cells, n_eligible=layer.n_eligible,
                     cells=layer.cells.assign(known_analog=None))
    assert len(trace(map_view.build_figure(empty, "world"), "Análogo conocido").x) == 0


@pytest.mark.parametrize("view", ["world", "south_pole"])
def test_selected_cell_is_an_outline_that_scales_with_zoom_plus_a_bigger_red_marker(bundle, view):
    fig = figure(bundle, view, selected=104)
    marker = trace(fig, "Celda elegida")
    assert len(marker.x) == 1 and marker.marker.line.color == map_view.SELECTED_COLOR
    assert marker.marker.size > trace(fig, "Análogo conocido").marker.size  # enmarca al anillo
    outline = trace(fig, "Contorno de la celda elegida")
    assert len(outline.x) >= 5 and outline.x[0] == outline.x[-1] and outline.y[0] == outline.y[-1]  # cerrado
    assert outline.line.color == map_view.SELECTED_COLOR


@pytest.mark.parametrize("view", ["world", "south_pole"])
def test_a_selected_cell_that_is_not_in_the_layer_draws_nothing(bundle, view):
    fig = figure(bundle, view, selected=999999)
    assert len(trace(fig, "Celda elegida").x) == 0 and len(trace(fig, "Contorno de la celda elegida").x) == 0


def test_cell_outline_is_a_closed_one_degree_square():
    for steps in (1, 6):
        lats, lons = map_view._cell_outline(10.5, 20.5, steps)
        assert len(lats) == len(lons) == 4 * steps + 1 and (lats[0], lons[0]) == (lats[-1], lons[-1])
        assert lats.max() - lats.min() == pytest.approx(1.0) and lons.max() - lons.min() == pytest.approx(1.0)


def test_unknown_projection_is_rejected(bundle):
    with pytest.raises(ValueError):
        map_view.build_figure(layer_of(bundle), "mercator")


# --- rendimiento (criterio: el mapa cambia en menos de 1 s al mover un slider) -


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
            "bio_score": rng.random(n).astype("float32"),
            "eligible": ~np.isnan(total),
            "known_analog": pd.array([None] * n, dtype=object),
        }
    )
    cells.loc[:40, "known_analog"] = "Análogo de prueba"
    return MapLayer(target_id=MOON, weights=Weights(**DEFAULT_WEIGHTS), n_cells=n, n_eligible=int((~np.isnan(total)).sum()), cells=cells)


@pytest.mark.parametrize("projection", ["world", "south_pole", "north_pole"])
def test_figure_of_the_whole_grid_is_built_in_well_under_a_second(projection):
    layer = big_layer()
    map_view.build_figure(layer, projection, 5)  # calienta
    best = min(_timed(map_view.build_figure, layer, projection, 5) for _ in range(3))
    assert best < 0.5, f"la figura tardó {best * 1000:.0f} ms"


@pytest.mark.parametrize("projection", ["south_pole", "north_pole"])
def test_polar_image_is_computed_in_under_a_second_when_the_totals_change(projection):
    layer = big_layer()
    map_view._IMAGE_CACHE.clear()
    elapsed = _timed(map_view.build_figure, layer, projection)  # sin caché: lo que cuesta mover un slider en los polos
    assert elapsed < 1.0, f"la imagen polar tardó {elapsed * 1000:.0f} ms"


@pytest.mark.parametrize("projection", ["world", "south_pole", "north_pole"])
def test_the_whole_grid_is_a_handful_of_traces_not_one_per_cell(projection):
    # Pocas trazas es lo que hace fluido mover y ampliar: el navegador dibuja un raster, no miles de polígonos.
    assert len(map_view.build_figure(big_layer(), projection, 5).data) <= 10


def _timed(fn, *args) -> float:
    t0 = time.perf_counter()
    fn(*args)
    return time.perf_counter() - t0


@pytest.mark.parametrize("view", ["world", "south_pole", "north_pole"])
def test_hiding_known_analogs_removes_the_rings(bundle, view):
    fig = map_view.build_figure(layer_of(bundle), view, show_analogs=False)
    assert not [t for t in fig.data if t.name == "Análogo conocido"]
