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


def names(fig):
    return [t.name for t in fig.data]


def test_figure_has_the_four_traces_in_order(bundle):
    fig = map_view.build_figure(layer_of(bundle), "world", None)
    assert names(fig) == ["Datos insuficientes", "Celdas elegibles", "Análogo conocido", "Análogo conocido", "Celda elegida"]
    gray, eligible, analog, analog_gray, chosen = fig.data
    assert len(gray.lat) == 1 and len(eligible.lat) == 5  # la 103 en gris, las otras cinco con color
    assert len(analog.lat) == 1 and len(analog_gray.lat) == 0 and len(chosen.lat) == 0


def test_eligible_cells_use_viridis_from_0_to_1_with_a_color_bar(bundle):
    eligible = map_view.build_figure(layer_of(bundle)).data[1]
    marker = eligible.marker
    assert marker.symbol == "square" and marker.cmin == 0 and marker.cmax == 1
    assert marker.colorscale[0][0] == 0 and marker.colorscale[-1][0] == 1 and len(marker.colorscale) >= 8  # Viridis
    assert marker.colorbar.title.text == "Puntaje total" and marker.showscale is not False


def test_insufficient_data_cell_is_gray_and_says_so_on_hover(bundle):
    gray = map_view.build_figure(layer_of(bundle)).data[0]
    assert gray.marker.color == map_view.GRAY and "Datos insuficientes" in gray.hovertemplate
    assert "Datos insuficientes" not in map_view.build_figure(layer_of(bundle)).data[1].hovertemplate


def test_hover_shows_the_location_the_total_and_the_four_dimensions(bundle):
    eligible = map_view.build_figure(layer_of(bundle)).data[1]
    h = eligible.hovertemplate
    for piece in ("%{lat", "%{lon", "Puntaje total", "Terreno", "Temperatura", "Agua y hielo", "Astrobiología"):
        assert piece in h
    assert eligible.customdata.shape == (5, 5)
    assert eligible.hovertemplatefallback == "sin dato"  # una dimensión nula se ve como "sin dato"


def test_known_analogs_have_a_thick_white_border_and_the_name_on_hover(bundle):
    fig = map_view.build_figure(layer_of(bundle))
    analog = fig.data[2]
    assert analog.marker.line.color == "#ffffff" and analog.marker.line.width >= 2
    assert "Atacama" in analog.text[0]


def test_selected_cell_is_a_bigger_red_marker(bundle):
    layer = layer_of(bundle)
    chosen = map_view.build_figure(layer, "world", 104).data[4]
    row = by_cell(layer).loc[104]
    assert list(chosen.lat) == [pytest.approx(row["lat"])] and list(chosen.lon) == [pytest.approx(row["lon"])]
    assert chosen.marker.line.color == map_view.SELECTED_COLOR
    assert chosen.marker.size > map_view.build_figure(layer).data[1].marker.size


def test_a_selected_cell_that_is_not_in_the_layer_draws_nothing(bundle):
    assert len(map_view.build_figure(layer_of(bundle), "world", 999999).data[4].lat) == 0


def test_all_weights_zero_draws_every_cell_gray(bundle):
    fig = map_view.build_figure(layer_of(bundle, dict.fromkeys(DEFAULT_WEIGHTS, 0.0)))
    assert len(fig.data[0].lat) == 6 and len(fig.data[1].lat) == 0


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
    map_view.build_figure(layer, projection, 5)  # calienta
    best = min(_timed(map_view.build_figure, layer, projection, 5) for _ in range(3))
    assert best < 0.5, f"la figura tardó {best * 1000:.0f} ms"


def _timed(fn, *args) -> float:
    t0 = time.perf_counter()
    fn(*args)
    return time.perf_counter() - t0
