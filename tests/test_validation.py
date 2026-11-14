"""Validación contra análogos conocidos (TAI-20, design 6.1, 12.2): paso 09 con mundos chicos armados a mano."""

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tai import geo, models
from tai.constants import DEFAULT_WEIGHTS

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("step09", ROOT / "pipeline" / "09_validation.py")
step09 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(step09)

FIX = Path(__file__).parent / "fixtures"
N = 100
LAT_IDX = 90  # latitud 0,5: celdas de 1° de longitud, a unos 111 km una de otra
NAN = np.nan


def make_world(ineligible=()):
    """100 celdas sobre el ecuador. La celda i tiene puesto i + 1: su terreno baja con i y lo demás es igual."""
    lon_idx = np.arange(N)
    cell_id = (LAT_IDX * 360 + lon_idx).astype("int32")
    lat, lon = geo.cell_center(cell_id)
    grid = pd.DataFrame({"cell_id": cell_id, "lat": lat, "lon": lon, "country": ["Chile"] * N})
    s = pd.DataFrame({
        "s_terrain": 1.0 - lon_idx / N, "s_temperature": 0.5, "s_water_ice": 0.5, "bio_score": 0.0,
    }, index=pd.Index(cell_id, name="cell_id")).astype("float32")
    for i in ineligible:  # una sola dimensión física: no elegible
        s.iloc[i, s.columns.get_loc("s_temperature")] = NAN
        s.iloc[i, s.columns.get_loc("s_water_ice")] = NAN
    s["known_analog"] = pd.array([None] * N, dtype="string")
    return grid, s


def cell(i):
    return int(LAT_IDX * 360 + i)


def analog(i, covered="yes", radius_km=50.0, analog_id=None, target_id="mars_jezero", dlat=0.0):
    lat, lon = geo.cell_center(cell(i))
    return models.KnownAnalog(analog_id=analog_id or f"analogo_{i}", name=f"Análogo {i}", lat=float(lat) + dlat,
                              lon=float(lon), radius_km=radius_km, target_id=target_id, basis="prueba",
                              covered=covered, source="prueba")


def validate(analogs, ineligible=(), note="", threshold=90):
    grid, sim = make_world(ineligible)
    return step09.validate_target("mars_jezero", sim, grid, analogs, DEFAULT_WEIGHTS, threshold, note)


# --- Percentil ---------------------------------------------------------------


def test_percentile_matches_the_design_example():
    assert step09.percentile(212, 19240) == 98.9  # 100 x (1 - 211 / 19240)
    assert step09.percentile(1, 19240) == 100.0
    assert step09.percentile(19240, 19240) == pytest.approx(0.0, abs=0.01)


# --- Un análogo --------------------------------------------------------------


def test_covered_analog_in_the_top_passes():
    t = validate([analog(3)])
    (a,) = t.analogs
    assert a.result == "pass" and a.best_cell_id == cell(3) and a.best_rank == 4
    assert a.percentile == 97.0 and a.n_cells == 1
    assert a.best_total == pytest.approx((0.97 + 0.5 + 0.5 + 0.5 * 0.0) / 3.5, abs=1e-3)  # pesos iniciales (design 5.6)


@pytest.mark.parametrize("i,expected", [(10, "pass"), (11, "fail")])  # percentil 90,0 y 89,0
def test_the_threshold_is_inclusive(i, expected):
    assert validate([analog(i)]).analogs[0].result == expected


def test_covered_analog_below_the_threshold_fails():
    a = validate([analog(50)]).analogs[0]
    assert a.result == "fail" and a.percentile == 50.0


def test_not_covered_analogs_are_only_informative():
    for covered in ("partial", "no"):
        a = validate([analog(50, covered=covered)]).analogs[0]
        assert a.result == "info" and a.percentile == 50.0


def test_analog_without_cells_has_no_data():
    a = validate([analog(3, dlat=60.0)]).analogs[0]  # a 60° al norte: ninguna celda
    assert a.result == "no_data" and a.n_cells == 0 and a.best_cell_id is None
    assert a.best_total is None and a.best_rank is None and a.percentile is None


def test_analog_whose_cells_are_not_eligible_has_no_data_but_counts_its_cells():
    a = validate([analog(7)], ineligible=[7]).analogs[0]
    assert a.result == "no_data" and a.n_cells == 1 and a.best_rank is None


def test_best_cell_is_the_best_ranked_one_inside_the_radius():
    a = validate([analog(40, radius_km=250.0)]).analogs[0]  # 250 km: las celdas 38 a 42
    assert a.n_cells == 5 and a.best_cell_id == cell(38) and a.best_rank == 39


def test_radius_is_inclusive():
    grid, _ = make_world()
    base = analog(5)
    d = float(geo.haversine_km(grid.loc[6, "lat"], grid.loc[6, "lon"], base.lat, base.lon))
    exact = analog(5, radius_km=d)
    assert len(step09.cells_within(exact, grid)) == 3  # las celdas 4, 5 y 6
    just_short = analog(5, radius_km=d - 0.01)
    assert len(step09.cells_within(just_short, grid)) == 1


# --- Un objetivo (design 12.2) -----------------------------------------------


def test_target_passes_with_at_least_two_covered_and_two_thirds_passed():
    t = validate([analog(2), analog(5), analog(60)])  # pasan 2 de 3
    assert (t.covered_total, t.covered_passed, t.result) == (3, 2, "pass")
    assert t.note == "" and t.n_eligible == N


def test_target_fails_below_two_thirds_and_gets_a_pending_note():
    t = validate([analog(2), analog(60), analog(70)])  # pasa 1 de 3
    assert (t.covered_passed, t.result) == (1, "fail")
    assert t.note.startswith("PENDIENTE")


def test_a_failed_target_keeps_santinos_note():
    t = validate([analog(2), analog(60), analog(70)], note="Se revisaron las unidades (paso 1)")
    assert t.result == "fail" and t.note == "Se revisaron las unidades (paso 1)"


def test_one_covered_analog_is_insufficient_even_if_it_passes():
    t = validate([analog(2), analog(50, covered="partial")])
    assert (t.covered_total, t.covered_passed, t.result) == (1, 1, "insufficient")
    assert t.note == ""  # insufficient no pide nota


def test_target_without_analogs_is_insufficient():
    t = validate([])
    assert (t.covered_total, t.result, t.analogs) == (0, "insufficient", [])


def test_a_covered_analog_without_data_counts_against_the_target():
    t = validate([analog(2), analog(4), analog(6, dlat=60.0)])  # 2 pasan, 1 sin dato
    assert (t.covered_total, t.covered_passed, t.result) == (3, 2, "pass")
    t = validate([analog(2), analog(6, dlat=60.0)])  # 1 de 2: menos de dos tercios
    assert t.result == "fail"


# --- Candidatas a finalista --------------------------------------------------


def test_finalists_skip_known_analog_cells_and_follow_the_ranking():
    grid, sim = make_world()
    sim.loc[[cell(0), cell(1)], "known_analog"] = "atacama_yungay"
    out = step09.finalist_candidates(sim, grid, n=6)
    assert list(out["cell_id"]) == [cell(i) for i in range(2, 8)]
    assert list(out["rank"]) == [1, 2, 3, 4, 5, 6]
    assert out["total"].is_monotonic_decreasing and {"lat", "lon", "country"} <= set(out.columns)


# --- Informe completo --------------------------------------------------------


def test_report_validates_against_the_contract_and_skips_targets_without_data():
    grid, s = make_world()
    sim = s.reset_index().assign(target_id="mars_jezero")
    report = step09.build_report(sim, grid, [analog(2), analog(5), analog(60), analog(3, target_id="moon_south_pole")])
    assert [t.target_id for t in report.targets] == ["mars_jezero"]  # la Luna no tiene tabla
    again = models.ValidationReport.model_validate_json(report.model_dump_json())
    assert again.weights.as_dict() == dict(DEFAULT_WEIGHTS) and again.percentile_threshold == 90


def test_report_with_the_contract_fixtures():
    grid = pd.read_parquet(FIX / "grid.parquet")
    sim = pd.read_parquet(FIX / "similarity.parquet")
    analogs = step09.load_analogs(FIX / "known_analogs.csv")
    report = step09.build_report(sim, grid, analogs)
    models.ValidationReport.model_validate_json(report.model_dump_json())
    assert {t.target_id for t in report.targets} == {"moon_south_pole", "mars_jezero"}


def test_notes_file_is_optional(tmp_path):
    assert step09.load_notes(tmp_path / "nada.json") == {}
    path = tmp_path / "notes.json"
    path.write_text('{"mars_jezero": "texto de Santino"}', encoding="utf-8")
    assert step09.load_notes(path) == {"mars_jezero": "texto de Santino"}
