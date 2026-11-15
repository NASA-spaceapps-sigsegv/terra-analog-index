"""Dimensión polvo y viento (TAI-52): paso 04_dust_wind, objetivo sin la dimensión (la Luna), puntaje y vista."""

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr
from pydantic import ValidationError

from tai import cards, geo, models, scoring
from tai.constants import CORE_VARS, OPTIONAL_VARS, PHYSICAL_VARS
from ui import card_view, map_view, ranking_view

ROOT = Path(__file__).resolve().parents[1]


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / "pipeline" / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


step = _load("step04dw", "04_dust_wind.py")
step08 = _load("step08dw", "08_similarity.py")


# --- Paso 04_dust_wind --------------------------------------------------------------


def _merra_month(folder: Path, collection: str, variable: str, month: int, value) -> Path:
    """Un archivo mensual con la grilla de MERRA-2 (0,5° x 0,625°) y un valor por punto."""
    lat = np.arange(-90, 90.01, 0.5)
    lon = np.arange(-180, 180, 0.625)
    data = np.broadcast_to(np.asarray(value, dtype="float32"), (1, lat.size, lon.size)).copy()
    ds = xr.Dataset({variable: (("time", "lat", "lon"), data)}, coords={"time": [month], "lat": lat, "lon": lon})
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"MERRA2_400.{collection}.2024{month:02d}.nc4"
    ds.to_netcdf(path)
    return path


@pytest.fixture
def raw(tmp_path):
    for m in range(1, 13):
        _merra_month(tmp_path / "m2tmnxaer", "tavgM_2d_aer_Nx", "DUEXTTAU", m, 0.01 * m)  # media anual 0,065
        _merra_month(tmp_path / "m2tmnxflx", "tavgM_2d_flx_Nx", "SPEED", m, 5.0)
    return tmp_path


def test_find_months_returns_the_twelve_in_order(raw):
    months = step.find_months("dust_aod", year=2024, root=raw)
    assert [p.name[-10:-4] for p in months] == [f"2024{m:02d}" for m in range(1, 13)]


def test_find_months_names_the_missing_ones(raw):
    (raw / "m2tmnxflx" / "MERRA2_400.tavgM_2d_flx_Nx.202403.nc4").unlink()
    with pytest.raises(step.MissingInputError, match=r"\[3\]"):
        step.find_months("wind_ms", year=2024, root=raw)


def test_cells_get_the_annual_mean_of_the_monthly_means(raw):
    ids = np.array([geo.cell_id_of(-24.1, -69.3), geo.cell_id_of(-89.9, 0.1), geo.cell_id_of(89.9, 179.9)])
    grid = pd.DataFrame({"cell_id": ids.astype("int32")})
    months = {c: step.find_months(c, year=2024, root=raw) for c in step.COLUMNS}
    out = step.dust_wind_cells(months, grid)
    assert list(out.columns) == ["cell_id", "dust_aod", "wind_ms"]
    assert np.allclose(out["dust_aod"], 0.065) and np.allclose(out["wind_ms"], 5.0)  # también en los polos


# --- Objetivos sin la dimensión ---------------------------------------------------------


def _var(**kw):
    return {"mean": 1.0, "std": 1.0, "unit": "u", "rule": "overlap", "source": "x", "source_type": "literature",
            "earth_p01": 0.0, "earth_p99": 2.0, "earth_std": 1.0} | kw


def _target(vars_):
    return models.Target(target_id="mars_jezero", label="x", body="mars",
                         bounds={"lat_min": 0, "lat_max": 1, "lon_min": 0, "lon_max": 1}, has_ice=False,
                         has_ice_source="x", summary="", unreplicable=["x"], notes=[], vars={v: _var() for v in vars_})


def test_a_target_may_skip_the_optional_variables_but_not_the_core_ones():
    assert set(_target(CORE_VARS).vars) == set(CORE_VARS)
    assert set(_target(PHYSICAL_VARS).vars) == set(PHYSICAL_VARS)
    with pytest.raises(ValidationError):
        _target(CORE_VARS[1:])
    with pytest.raises(ValidationError):
        _target([*CORE_VARS, "dust_aod", "humedad"])


def _features(n=3):
    df = pd.DataFrame({"cell_id": np.arange(n, dtype="int32")})
    for v in PHYSICAL_VARS:
        df[v] = np.linspace(0.5, 1.5, n)
    return df


def test_a_target_without_the_dimension_gets_null_dust_wind_and_the_same_totals():
    f = _features()
    area = np.ones(len(f))
    lat = lon = np.zeros(len(f))
    bio = np.zeros(len(f))
    without = step08.target_similarity(_target(CORE_VARS), f, area, lat, lon, bio, [])
    assert without[[f"sv_{v}" for v in OPTIONAL_VARS] + ["s_dust_wind"]].isna().all().all()
    weights = {"terrain": 1, "temperature": 1, "water_ice": 1, "dust_wind": 1, "biology": 0.5}
    core_only = weights | {"dust_wind": 0}
    pd.testing.assert_series_equal(scoring.combine(without, weights), scoring.combine(without, core_only))

    with_dim = step08.target_similarity(_target(PHYSICAL_VARS), f, area, lat, lon, bio, [])
    assert with_dim["s_dust_wind"].notna().all()


def test_dust_wind_does_not_decide_eligibility():
    sim = pd.DataFrame({"s_terrain": [0.5, np.nan], "s_temperature": [np.nan, np.nan], "s_water_ice": [0.5, 0.5],
                        "s_dust_wind": [0.5, 0.5], "bio_score": [0.0, 0.0]})
    assert scoring.is_eligible(sim).tolist() == [True, False]  # la segunda tiene 2 dimensiones solo contando polvo


def test_weights_written_before_the_dimension_load_with_it_at_zero():
    assert models.Weights(terrain=1, temperature=1, water_ice=1, biology=0.5).dust_wind == 0.0


# --- Ficha y vistas ------------------------------------------------------------------------


@pytest.mark.parametrize("unit,expected", [
    ("", "0,12 frente a 0,45 ± 0,15 del objetivo"),
    ("m/s", "5,5 m/s frente a 4,0 ± 2,0 del objetivo"),
])
def test_overlap_phrase_without_unit_has_no_double_space(unit, expected):
    x, mean = (0.12, 0.45) if unit == "" else (5.5, 4.0)
    std = 0.15 if unit == "" else 2.0
    assert cards.variable_phrase("dust_aod", "overlap", x, 0.5, mean, std, unit) == expected


def test_directional_phrase_without_unit_closes_the_parenthesis():
    phrase = cards.variable_phrase("dust_aod", "directional_high", 0.3, 0.97, 0.45, 0.15, "")
    assert phrase == "Mayor que el 97% de la tierra firme; el objetivo (0,45) queda fuera del rango terrestre"


def _card(with_dust: bool):
    from tests.test_cards import example_card

    card = example_card()
    if not with_dust:
        return card
    extra = [cards.CardVariable(variable=v, label=cards.VAR_LABELS[v], dimension="dust_wind", unit="", earth_value=0.1,
                                target_mean=0.45, target_std=0.15, score=0.6, rule="overlap", phrase="x",
                                source_earth="MERRA-2", source_target="MEDA", source_type="literature")
             for v in OPTIONAL_VARS]
    return card.model_copy(update={"variables": [*card.variables, *extra],
                                   "scores": card.scores.model_copy(update={"dust_wind": 0.6})})


def test_radar_has_five_axes_with_the_dimension_and_four_without():
    labels, _ = card_view.radar_axes(_card(with_dust=True))
    assert len(labels) == 5 and "Polvo y viento" in labels
    labels, _ = card_view.radar_axes(_card(with_dust=False))
    assert len(labels) == 4 and not any("Polvo" in lbl for lbl in labels)


def test_ranking_hides_the_column_only_when_it_is_empty():
    table = pd.DataFrame({"Puesto": [1, 2], "Total": [0.5, 0.4], "Polvo y viento": [np.nan, np.nan]})
    assert "Polvo y viento" not in ranking_view.visible_columns(table)
    table.loc[0, "Polvo y viento"] = 0.3
    assert "Polvo y viento" in ranking_view.visible_columns(table)


def test_map_hover_shows_dust_wind_only_where_the_target_has_it():
    cells = pd.DataFrame({"s_terrain": [0.5], "s_temperature": [0.5], "s_water_ice": [0.5], "s_dust_wind": [np.nan],
                          "bio_score": [0.1]})
    assert "Polvo y viento" not in map_view._scores_text(cells)[0]
    cells["s_dust_wind"] = 0.25
    assert "Polvo y viento: 0.25" in map_view._scores_text(cells)[0]
