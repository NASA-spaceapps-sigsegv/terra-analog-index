"""Pasos 06 (unión de variables) y 08 (similitud) de TAI-18, con mundos chicos armados a mano,
y una corrida de punta a punta 06 -> 07 -> 08 -> 09 con los archivos reales de config/."""

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pipeline.common import OutputValidationError
from tai import geo, models, schemas
from tai.constants import BIO_TYPES, CORE_VARS, PHYSICAL_VARS, TARGET_IDS

ROOT = Path(__file__).resolve().parents[1]


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / "pipeline" / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


step06 = _load("step06", "06_features.py")
step08 = _load("step08", "08_similarity.py")
NAN = np.nan


def make_grid(cells):
    """cells: lista de (lat, lon) de puntos; una celda por punto."""
    cid = np.array([geo.cell_id_of(la, lo) for la, lo in cells], dtype="int32")
    lat_idx, lon_idx = geo.split_cell_id(cid)
    lat, lon = geo.cell_center(cid)
    return pd.DataFrame({
        "cell_id": cid, "lat_idx": lat_idx.astype("int16"), "lon_idx": lon_idx.astype("int16"),
        "lat": lat.astype("float32"), "lon": lon.astype("float32"),
        "area_km2": geo.cell_area_km2(lat_idx).astype("float32"), "land_frac": np.float32(1.0),
        "country": pd.array([None] * len(cid), dtype="string"),
    })


def parts_for(grid, values, bio=None):
    """values: {variable: lista alineada con la grilla}. Los intermedios traen todas las celdas."""
    ids = grid["cell_id"]
    part = lambda cols: pd.DataFrame({"cell_id": ids, **{c: pd.array(values.get(c, [NAN] * len(ids)), dtype="float32")
                                                         for c in cols}})
    bio = bio or {}
    return {
        "terrain": part(["slope_deg", "roughness_m"]),
        "temperature": part(["tmin_c", "trange_c"]),
        "water_ice": part(["precip_mm", "ice_frac"]),
        "dust_wind": part(["dust_aod", "wind_ms"]),
        "biology": pd.DataFrame({
            "cell_id": ids,
            "bio_records": np.array(bio.get("bio_records", [0] * len(ids)), dtype="int32"),
            "bio_types": np.array(bio.get("bio_types", [0] * len(ids)), dtype="int8"),
            "bio_type_list": pd.array(bio.get("bio_type_list", [""] * len(ids)), dtype="string"),
        }),
    }


GRID3 = make_grid([(-24.1, -69.3), (10.5, 20.5), (-80.5, 0.5)])


def values3(**over):
    v = {"slope_deg": [3.5, 1.0, 0.5], "roughness_m": [38.0, 5.0, 2.0], "tmin_c": [-4.0, 20.0, -60.0],
         "trange_c": [30.0, 10.0, 5.0], "precip_mm": [3.0, 1200.0, NAN], "ice_frac": [0.05, 0.0, 1.0],
         "dust_aod": [0.05, 0.3, 0.003], "wind_ms": [5.5, 6.0, 12.0]}
    v.update(over)
    return v


# --- Paso 06 -----------------------------------------------------------------


def test_features_follow_the_contract():
    f = step06.build_features(GRID3, parts_for(GRID3, values3()))
    assert schemas.check_schema(f, "features") == []
    assert list(f["cell_id"]) == list(GRID3["cell_id"])


def test_coverage_and_n_physical_count_what_has_data():
    v = values3(slope_deg=[3.5, NAN, NAN], roughness_m=[38.0, NAN, NAN], tmin_c=[-4.0, NAN, -60.0],
                trange_c=[30.0, NAN, NAN], precip_mm=[3.0, NAN, NAN], ice_frac=[0.05, NAN, 1.0],
                dust_aod=[0.05, NAN, NAN], wind_ms=[NAN, 6.0, NAN])
    f = step06.build_features(GRID3, parts_for(GRID3, v))
    assert list(f["coverage"]) == [7, 1, 2]
    assert list(f["n_physical"]) == [3, 0, 2]  # polvo y viento no cuenta: no decide la elegibilidad (TAI-52)


def test_cells_missing_from_an_intermediate_stay_null_not_zero():
    parts = parts_for(GRID3, values3())
    parts["terrain"] = parts["terrain"].iloc[:1]  # el terreno trae solo la primera celda
    parts["biology"] = parts["biology"].iloc[:0]  # sin registros biológicos
    f = step06.build_features(GRID3, parts)
    assert f["slope_deg"].isna().tolist() == [False, True, True]
    assert list(f["bio_records"]) == [0, 0, 0] and list(f["bio_type_list"]) == ["", "", ""]


def test_bio_type_list_is_alphabetical():
    bio = {"bio_records": [3, 0, 0], "bio_types": [2, 0, 0], "bio_type_list": ["xerophile,halophile", "", ""]}
    f = step06.build_features(GRID3, parts_for(GRID3, values3(), bio))
    assert f.loc[0, "bio_type_list"] == "halophile,xerophile"


def test_intermediate_outside_the_grid_or_without_columns_fails():
    parts = parts_for(GRID3, values3())
    parts["temperature"] = pd.concat([parts["temperature"], parts["temperature"].iloc[:1].assign(cell_id=1)])
    with pytest.raises(OutputValidationError, match="fuera de la grilla"):
        step06.build_features(GRID3, parts)
    parts = parts_for(GRID3, values3())
    parts["water_ice"] = parts["water_ice"].drop(columns="ice_frac")
    with pytest.raises(OutputValidationError, match="ice_frac"):
        step06.build_features(GRID3, parts)


def test_earth_stats_are_weighted_by_area_and_validate():
    f = step06.build_features(GRID3, parts_for(GRID3, values3()))
    stats = step06.earth_stats(f, GRID3)
    assert set(stats) == set(PHYSICAL_VARS)
    for s in stats.values():
        models.EarthStats.model_validate(s)
        assert s["p01"] <= s["p99"]
    # con tres celdas, los percentiles 1 y 99 caen en los extremos
    assert stats["tmin_c"]["p01"] == -60.0 and stats["tmin_c"]["p99"] == 20.0
    assert stats["precip_mm"]["p99"] == 1200.0  # el nulo no cuenta


def test_earth_stats_fail_if_a_variable_has_no_data():
    f = step06.build_features(GRID3, parts_for(GRID3, values3(ice_frac=[NAN, NAN, NAN])))
    with pytest.raises(OutputValidationError, match="ice_frac"):
        step06.earth_stats(f, GRID3)


# --- Paso 08 -----------------------------------------------------------------


def target(target_id="mars_jezero", has_ice=False, rules_=None, earth_std=5.0):
    rules_ = rules_ or {"slope_deg": "overlap", "roughness_m": "overlap", "tmin_c": "directional_low",
                        "trange_c": "directional_high", "precip_mm": "directional_low",
                        "ice_frac": "presence" if has_ice else "absence"}
    means = {"slope_deg": 3.5, "roughness_m": 38.0, "tmin_c": -80.0, "trange_c": 70.0, "precip_mm": 0.0,
             "ice_frac": 1.0 if has_ice else 0.0}
    return models.Target(
        target_id=target_id, label="x", body="mars", bounds={"lat_min": 0, "lat_max": 1, "lon_min": 0, "lon_max": 1},
        has_ice=has_ice, has_ice_source="x", summary="", unreplicable=[], notes=[],
        vars={v: {"mean": means[v], "std": 2.0, "unit": "u", "rule": rules_[v], "source": "x",
                  "source_type": "literature", "earth_p01": 0.0, "earth_p99": 1.0, "earth_std": earth_std}
              for v in CORE_VARS})  # sin polvo y viento: es opcional (TAI-52)


def analog(analog_id, lat, lon, radius_km=150.0, target_id="mars_jezero"):
    return models.KnownAnalog(analog_id=analog_id, name=analog_id, lat=lat, lon=lon, radius_km=radius_km,
                              target_id=target_id, basis="x", covered="yes", source="x")


def similarity(values=None, targets=None, analogs=(), bio=None, grid=GRID3):
    f = step06.build_features(grid, parts_for(grid, values or values3(), bio))
    tf = models.TargetsFile(schema_version=1, targets=targets or [target()])
    return step08.build_similarity(f, grid, tf, list(analogs))[0]


def test_similarity_follows_the_contract_one_row_per_cell_and_target():
    sim = similarity(targets=[target("moon_south_pole", has_ice=True), target("mars_jezero")])
    assert schemas.check_schema(sim, "similarity") == []
    assert len(sim) == 2 * len(GRID3) and not sim.duplicated(["cell_id", "target_id"]).any()


def test_variable_scores_follow_their_rules():
    sim = similarity()
    assert sim.loc[0, "sv_slope_deg"] == 1.0  # en la media del objetivo
    assert sim.loc[2, "sv_tmin_c"] == 1.0  # la más fría
    assert sim.loc[0, "sv_trange_c"] == 1.0  # el mayor rango
    assert list(sim["sv_ice_frac"]) == pytest.approx([0.95, 1.0, 0.0])  # absence
    assert np.isnan(sim.loc[2, "sv_precip_mm"])  # nulo sigue nulo


def test_dimension_is_the_mean_of_its_variables_with_data():
    sim = similarity()
    assert sim.loc[2, "s_water_ice"] == pytest.approx(sim.loc[2, "sv_ice_frac"])  # precip nula: solo hielo
    assert sim.loc[0, "s_temperature"] == pytest.approx((sim.loc[0, "sv_tmin_c"] + 1.0) / 2, abs=1e-3)


def test_eligibility_needs_two_physical_dimensions():
    v = values3(slope_deg=[NAN, 1.0, NAN], roughness_m=[NAN, 5.0, NAN], tmin_c=[NAN, 20.0, NAN],
                trange_c=[NAN, 10.0, NAN])
    sim = similarity(v)
    assert list(sim["n_physical"]) == [1, 3, 1] and list(sim["eligible"]) == [False, True, False]


def test_bio_score_matches_the_design_and_is_the_same_for_every_target():
    bio = {"bio_records": [12, 400, 0], "bio_types": [2, 6, 0], "bio_type_list": ["halophile,xerophile",
                                                                                 ",".join(BIO_TYPES), ""]}
    sim = similarity(targets=[target("moon_south_pole", has_ice=True), target("mars_jezero")], bio=bio)
    moon, mars = (sim[sim["target_id"] == t].reset_index() for t in ("moon_south_pole", "mars_jezero"))
    assert moon.loc[0, "bio_score"] == pytest.approx(0.381, abs=1e-3)  # design 5.5
    assert moon.loc[2, "bio_score"] == 0.0 and moon.loc[1, "bio_score"] == 1.0
    assert list(moon["bio_score"]) == list(mars["bio_score"])


def test_known_analog_is_the_nearest_within_its_radius_and_per_target():
    center = GRID3.loc[0, ["lat", "lon"]].astype(float)
    near = analog("cerca", center["lat"] + 0.3, center["lon"])  # unos 33 km
    far = analog("lejos", center["lat"] + 1.0, center["lon"])  # unos 111 km
    other = analog("de_la_luna", center["lat"], center["lon"], target_id="moon_south_pole")
    tiny = analog("radio_chico", center["lat"] + 0.3, center["lon"], radius_km=10)
    sim = similarity(targets=[target("moon_south_pole", has_ice=True), target("mars_jezero")],
                     analogs=[far, near, other, tiny])
    mars = sim[sim["target_id"] == "mars_jezero"].reset_index(drop=True)
    moon = sim[sim["target_id"] == "moon_south_pole"].reset_index(drop=True)
    assert mars.loc[0, "known_analog"] == "cerca" and mars.loc[0, "known_analog_km"] == pytest.approx(33.4, abs=0.5)
    assert mars["known_analog"].isna().tolist() == [False, True, True]
    assert moon.loc[0, "known_analog"] == "de_la_luna" and moon.loc[0, "known_analog_km"] == 0.0


def test_scores_are_rounded_to_file_decimals():
    sim = similarity()
    s = sim["sv_tmin_c"].dropna().astype("float64")
    assert np.allclose(s, s.round(3), atol=1e-6)


def test_load_analogs_rejects_unknown_targets_and_wrong_columns(tmp_path):
    good = ROOT / "config" / "known_analogs.csv"
    assert len(step08.load_analogs(good)) >= 8
    df = pd.read_csv(good)
    bad = tmp_path / "a.csv"
    df.assign(target_id="venus").to_csv(bad, index=False)
    with pytest.raises(OutputValidationError, match="desconocidos"):
        step08.load_analogs(bad)
    df.drop(columns="basis").to_csv(bad, index=False)
    with pytest.raises(OutputValidationError, match="columnas"):
        step08.load_analogs(bad)


# --- De punta a punta: 06 -> 07 -> 08 -> 09 con config/ real -----------------


def test_end_to_end_with_the_real_config_files():
    step07 = _load("step07", "07_targets.py")
    step09 = _load("step09", "09_validation.py")
    from tai import rules

    # Un mundo chico: los puntos de los análogos (fríos, secos) y celdas templadas y húmedas de relleno.
    analogs = step08.load_analogs(ROOT / "config" / "known_analogs.csv")
    pts = [(a.lat, a.lon) for a in analogs] + [(-3.5 + i, -60.5 + i) for i in range(30)]
    grid = make_grid(pts).drop_duplicates("cell_id").reset_index(drop=True)
    n_an = len({geo.cell_id_of(a.lat, a.lon) for a in analogs})
    n = len(grid)
    cold = np.r_[np.full(n_an, -45.0), np.linspace(5, 25, n - n_an)]
    values = {"slope_deg": np.full(n, 3.0), "roughness_m": np.full(n, 40.0), "tmin_c": cold,
              "trange_c": np.r_[np.full(n_an, 30.0), np.full(n - n_an, 8.0)],
              "precip_mm": np.r_[np.full(n_an, 20.0), np.full(n - n_an, 2000.0)],
              "ice_frac": np.r_[np.full(n_an, 0.3), np.zeros(n - n_an)],
              # TAI-52: análogos polvorientos y con viento moderado, como Jezero
              "dust_aod": np.r_[np.full(n_an, 0.3), np.full(n - n_an, 0.02)],
              "wind_ms": np.r_[np.full(n_an, 4.0), np.full(n - n_an, 8.0)]}
    f = step06.build_features(grid, parts_for(grid, values))
    earth = {v: models.EarthStats(**s) for v, s in step06.earth_stats(f, grid).items()}

    base = models.TargetsBaseFile.model_validate_json((ROOT / "config" / "targets_base.json").read_text("utf-8"))
    measured = {"moon_south_pole": {"slope_deg": (12.0, 6.0, 1), "roughness_m": (120.0, 60.0, 1)},
                "mars_jezero": {"slope_deg": (2.3, 1.5, 1), "roughness_m": (53.0, 20.0, 1)}}
    targets = step07.build_targets(base, measured, earth, rules.choose_rule)
    assert [t.target_id for t in targets.targets] == list(TARGET_IDS)
    assert targets.targets[0].vars["tmin_c"].rule == "directional_low"

    sim, _ = step08.build_similarity(f, grid, targets, analogs)
    assert schemas.check_schema(sim, "similarity") == []
    assert len(sim) == n * len(TARGET_IDS)

    report = step09.build_report(sim, grid, analogs)
    models.ValidationReport.model_validate_json(report.model_dump_json())
    assert {t.target_id for t in report.targets} == set(TARGET_IDS)
    assert all(t.covered_total >= 3 for t in report.targets)  # TAI-17: 3 cubiertos por objetivo
    json.dumps(report.model_dump(mode="json"), allow_nan=False)
