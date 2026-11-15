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


def fills(fig):
    """Las trazas que dibujan los cuadrados de las celdas (todas menos el contorno de la elegida)."""
    return [t for t in fig.data if t.fill == "toself"]


def n_squares(t) -> int:
    return int(np.isnan(np.asarray(t.lat, dtype=float)).sum())  # un NaN cierra cada cuadrado


def test_cells_are_one_degree_squares_not_points(bundle):
    fig = map_view.build_figure(layer_of(bundle), "world", None)
    painted = sum(n_squares(t) for t in fills(fig) if t.name != "Datos insuficientes")
    assert painted == 5 and n_squares(trace(fig, "Datos insuficientes")) == 1  # la 103 en gris, las otras cinco con color
    one = next(t for t in fills(fig) if t.name != "Datos insuficientes")
    lats, lons = np.asarray(one.lat, float)[:5], np.asarray(one.lon, float)[:5]
    # un grado más un pequeño solape con las vecinas (map_view.OVERLAP_DEG), para que no queden costuras
    assert 1.0 <= lats.max() - lats.min() <= 1.0 + 2 * map_view.OVERLAP_DEG
    assert 1.0 <= lons.max() - lons.min() <= 1.0 + 2 * map_view.MAX_LON_OVERLAP_DEG


def test_a_square_at_mid_latitude_is_one_degree_plus_the_overlap():
    lats, lons = map_view._squares(np.array([10.5]), np.array([20.5]))
    assert np.nanmax(lats) - np.nanmin(lats) == pytest.approx(1.0 + 2 * map_view.OVERLAP_DEG)
    expected = 1.0 + 2 * map_view.OVERLAP_DEG / np.cos(np.radians(10.5))
    assert np.nanmax(lons) - np.nanmin(lons) == pytest.approx(expected)


def test_no_vertex_is_exactly_on_a_pole():
    lats, _ = map_view._squares(np.array([89.5, -89.5, 0.5]), np.array([10.5, 10.5, 10.5]))
    finite = lats[~np.isnan(lats)]
    assert finite.max() <= map_view.POLE_LIMIT < 90 and finite.min() >= -map_view.POLE_LIMIT > -90


def test_squares_are_wound_clockwise_which_is_what_d3_geo_needs():
    lats, lons = map_view._squares(np.array([10.5]), np.array([20.5]))
    x, y = lons[:5], lats[:5]
    shoelace = 0.5 * np.sum(x[:-1] * y[1:] - x[1:] * y[:-1])
    assert shoelace < 0  # negativo = sentido horario; el contrario rellena las vistas polares enteras
    assert (x[0], y[0]) == (x[4], y[4])  # polígono cerrado


def test_cells_are_colored_with_viridis_by_total(bundle):
    fig = map_view.build_figure(layer_of(bundle))
    colored = [t for t in fills(fig) if t.name != "Datos insuficientes"]
    assert 1 <= len(colored) <= map_view.N_BINS and all(t.fillcolor.startswith("rgb") for t in colored)
    assert len({t.fillcolor for t in colored}) > 1  # no todas del mismo color: los puntajes de prueba difieren


def test_color_bar_is_viridis_from_0_to_1(bundle):
    bar = trace(map_view.build_figure(layer_of(bundle)), "Puntaje total").marker
    assert bar.showscale is True and bar.cmin == 0 and bar.cmax == 1
    assert bar.colorscale[0][0] == 0 and bar.colorscale[-1][0] == 1 and len(bar.colorscale) >= 8  # Viridis
    assert bar.colorbar.title.text == "Puntaje total"


def test_hover_shows_the_location_the_total_and_the_four_dimensions(bundle):
    cursor = trace(map_view.build_figure(layer_of(bundle)), "Celdas elegibles")
    for piece in ("%{lat", "%{lon", "Puntaje total", "Terreno", "Temperatura", "Agua y hielo", "Astrobiología"):
        assert piece in cursor.hovertemplate
    assert cursor.customdata.shape == (5, 5) and len(cursor.lat) == 5
    assert cursor.hovertemplatefallback == "sin dato"  # una dimensión nula se ve como "sin dato"
    # Transparente del todo: con un alfa pequeño pero no nulo, cerca de los polos se suman cientos de marcadores
    # superpuestos y oscurecen la vista polar (un agujero negro y anillos concéntricos).
    assert cursor.marker.color == "rgba(0,0,0,0)" and cursor.marker.size > 0


def test_insufficient_data_cell_says_so_on_hover(bundle):
    fig = map_view.build_figure(layer_of(bundle))
    cursor = trace(fig, "Datos insuficientes (cursor)")
    assert len(cursor.lat) == 1 and "Datos insuficientes" in cursor.hovertemplate
    assert "Datos insuficientes" not in trace(fig, "Celdas elegibles").hovertemplate
    assert trace(fig, "Datos insuficientes").fillcolor == map_view.GRAY


def test_each_known_analog_is_one_white_ring_and_its_name_is_on_the_cell_hover(bundle):
    fig = map_view.build_figure(layer_of(bundle))
    ring = trace(fig, "Análogo conocido")
    assert len(ring.lat) == 1  # un anillo por análogo, no un borde por celda
    assert ring.marker.symbol == "circle-open" and ring.marker.color == "#ffffff" and ring.marker.line.width >= 2
    assert ring.hoverinfo == "skip"  # el texto del cursor sale de las celdas, para no duplicarlo
    assert any("Atacama" in t for t in trace(fig, "Celdas elegibles").text)


def test_a_ring_is_centered_on_all_the_cells_of_its_analog():
    layer = big_layer()  # 41 celdas con el mismo análogo
    ring = trace(map_view.build_figure(layer), "Análogo conocido")
    assert len(ring.lat) == 1
    cells = layer.cells[layer.cells["known_analog"].notna()]
    assert ring.lat[0] == pytest.approx(cells["lat"].mean(), abs=1e-3)


def test_the_ring_center_does_not_break_across_the_dateline():
    lon = np.array([179.5, -179.5, 178.5, -178.5])
    cells = pd.DataFrame({"lat": [-77.5] * 4, "lon": lon, "known_analog": ["A"] * 4})
    _, centers = map_view._analog_centers(cells)
    assert abs(abs(centers[0]) - 180) < 0.6  # cerca de ±180, no en 0


def test_figure_without_analogs_has_an_empty_ring_trace():
    layer = big_layer()
    cells = layer.cells.assign(known_analog=None)
    empty = MapLayer(target_id=MOON, weights=layer.weights, n_cells=layer.n_cells, n_eligible=layer.n_eligible, cells=cells)
    assert len(trace(map_view.build_figure(empty), "Análogo conocido").lat) == 0


def test_selected_cell_is_an_outline_that_scales_with_zoom_plus_a_bigger_red_marker(bundle):
    layer = layer_of(bundle)
    fig = map_view.build_figure(layer, "world", 104)
    row = by_cell(layer).loc[104]
    marker = trace(fig, "Celda elegida")
    assert list(marker.lat) == [pytest.approx(row["lat"])] and list(marker.lon) == [pytest.approx(row["lon"])]
    assert marker.marker.line.color == map_view.SELECTED_COLOR
    assert marker.marker.size > trace(fig, "Análogo conocido").marker.size  # enmarca al anillo
    outline = trace(fig, "Contorno de la celda elegida")
    assert n_squares(outline) == 1 and outline.line.color == map_view.SELECTED_COLOR


def test_a_selected_cell_that_is_not_in_the_layer_draws_nothing(bundle):
    fig = map_view.build_figure(layer_of(bundle), "world", 999999)
    assert len(trace(fig, "Celda elegida").lat) == 0 and n_squares(trace(fig, "Contorno de la celda elegida")) == 0


def test_all_weights_zero_draws_every_cell_gray(bundle):
    fig = map_view.build_figure(layer_of(bundle, dict.fromkeys(DEFAULT_WEIGHTS, 0.0)))
    assert n_squares(trace(fig, "Datos insuficientes")) == 6 and len(trace(fig, "Celdas elegibles").lat) == 0
    assert all(n_squares(t) == 0 for t in fills(fig) if t.name != "Datos insuficientes")


@pytest.mark.parametrize(
    "projection,kind,lat",
    [("world", "natural earth", None), ("south_pole", "orthographic", -90), ("north_pole", "orthographic", 90)],
)
def test_the_three_projections(bundle, projection, kind, lat):
    geo = map_view.build_figure(layer_of(bundle), projection).layout.geo
    assert geo.projection.type == kind
    if lat is not None:
        assert geo.projection.rotation.lat == lat  # centrada en el polo: la Antártida entera en la vista polar sur


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


@pytest.mark.parametrize("projection", ["world", "south_pole"])
def test_figure_of_the_whole_grid_is_built_in_well_under_a_second(projection):
    layer = big_layer()
    assert len(map_view.build_figure(layer, projection, 5).data) <= map_view.N_BINS + 8  # no una traza por celda
    map_view.build_figure(layer, projection, 5)  # calienta
    best = min(_timed(map_view.build_figure, layer, projection, 5) for _ in range(3))
    assert best < 0.5, f"la figura tardó {best * 1000:.0f} ms"


def _timed(fn, *args) -> float:
    t0 = time.perf_counter()
    fn(*args)
    return time.perf_counter() - t0
