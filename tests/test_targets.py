"""Perfiles objetivo (TAI-16): paso 07 sobre rásteres sintéticos y la base de prueba."""

import importlib.util
import json
import math
from pathlib import Path

import numpy as np
import pytest

from pipeline.common import MissingInputError
from tai import models
from tai.constants import PHYSICAL_VARS

rasterio = pytest.importorskip("rasterio")
from rasterio.transform import from_origin  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("step07", ROOT / "pipeline" / "07_targets.py")
step07 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(step07)

FIX = Path(__file__).parent / "fixtures"
SLOPE_01 = math.degrees(math.atan(0.1))  # pendiente de un plano que sube 0,1 m por metro
STD_5PX = math.sqrt(2)  # desvío de 5 pasos iguales (-2..2), en unidades de paso


def write_tif(path, array, transform, dtype, nodata=None):
    with rasterio.open(path, "w", driver="GTiff", height=array.shape[0], width=array.shape[1], count=1,
                       dtype=dtype, transform=transform, nodata=nodata) as dst:
        dst.write(array.astype(dtype), 1)


# --- Luna (LOLA, estereográfica polar) ---------------------------------------


def moon_plane(tmp_path, res_m, half_m=200_000, nodata_hole=False):
    n = int(2 * half_m / res_m)
    x = -half_m + (np.arange(n) + 0.5) * res_m
    z = np.tile(0.1 * x, (n, 1))  # plano inclinado hacia +x
    if nodata_hole:
        z[:10, :10] = np.nan
    path = tmp_path / "ldem.tif"
    write_tif(path, z, from_origin(-half_m, half_m, res_m, res_m), "float32", nodata=float("nan"))
    return path


def test_colatitude_of_the_cut_edge():
    # 5° de colatitud = 85°S queda a unos 151,7 km del polo
    rho = 2 * step07.MOON_RADIUS_M * math.tan(math.radians(2.5))
    assert rho / 1000 == pytest.approx(151.7, abs=0.1)
    assert step07.polar_colatitude_deg(np.array([rho]), np.array([0.0]))[0] == pytest.approx(5.0)
    assert step07.polar_colatitude_deg(np.array([0.0]), np.array([0.0]))[0] == 0.0


def test_lola_plane_gives_known_slope_and_roughness(tmp_path):
    path = moon_plane(tmp_path, res_m=1000)
    got = step07.lola_cut_stats(path, lat_max=-85.0)
    mean_s, std_s, n = got["slope_deg"]
    assert mean_s == pytest.approx(SLOPE_01, abs=0.01) and std_s < 0.05
    assert got["roughness_m"][0] == pytest.approx(STD_5PX * 100, abs=0.5)  # 100 m por píxel de 1 km
    area_px = math.pi * 151.7**2  # km² = píxeles de 1 km
    assert n == pytest.approx(area_px, rel=0.02)


def test_lola_is_averaged_down_to_1_km(tmp_path):
    fine = step07.lola_cut_stats(moon_plane(tmp_path, res_m=500), lat_max=-85.0)
    assert fine["slope_deg"][0] == pytest.approx(SLOPE_01, abs=0.02)
    assert fine["roughness_m"][0] == pytest.approx(STD_5PX * 100, abs=1.0)  # mismo plano a 1 km


def test_lola_pixel_is_1_km_when_the_resolution_does_not_divide_it(tmp_path):
    # 400 m, como los 80 m de LOLA, no divide 1 km: los píxeles tienen que medir 1 km igual
    got = step07.lola_cut_stats(moon_plane(tmp_path, res_m=400), lat_max=-85.0)
    assert got["slope_deg"][2] == pytest.approx(math.pi * 151.7**2, rel=0.02)  # km² = píxeles de 1 km


def test_lola_ignores_missing_pixels(tmp_path):
    path = moon_plane(tmp_path, res_m=1000, nodata_hole=True)
    got = step07.lola_cut_stats(path, lat_max=-85.0)
    assert got["slope_deg"][0] == pytest.approx(SLOPE_01, abs=0.01)  # el hueco queda fuera del recorte


def test_lola_with_no_valid_pixels_in_the_cut_fails(tmp_path):
    z = np.full((400, 400), np.nan)
    path = tmp_path / "empty.tif"
    write_tif(path, z, from_origin(-200_000, 200_000, 1000, 1000), "float32", nodata=float("nan"))
    with pytest.raises(MissingInputError, match="sin píxeles|no tiene píxeles"):
        step07.lola_cut_stats(path, lat_max=-85.0)


# --- Marte (MOLA, equirectangular) -------------------------------------------


def mars_plane(tmp_path, left_deg=-180.0):
    """Zona de 70 a 85 E y 10 a 25 N a 463 m; z crece 0,05 m por metro hacia el norte."""
    mpd = step07.MARS_M_PER_DEG
    res = 463.0935415503709
    lon0, lon1, lat0, lat1 = 70.0, 85.0, 10.0, 25.0
    w, h = round((lon1 - lon0) * mpd / res), round((lat1 - lat0) * mpd / res)
    y = lat1 * mpd - (np.arange(h) + 0.5) * res
    z = np.tile(0.05 * y[:, None], (1, w))
    path = tmp_path / "mola.tif"
    write_tif(path, z, from_origin(lon0 * mpd, lat1 * mpd, res, res), "int16", nodata=-32768)
    return path


def test_mola_window_gives_known_slope_and_roughness(tmp_path):
    got = step07.mola_cut_stats(mars_plane(tmp_path), 17.9, 18.9, 77.0, 78.0)
    assert got["slope_deg"][0] == pytest.approx(math.degrees(math.atan(0.05)), abs=0.1)
    assert got["roughness_m"][0] == pytest.approx(STD_5PX * 50, abs=2.0)  # 50 m por píxel de 1 km
    assert got["slope_deg"][2] > 2000  # unos 59 x 56 píxeles de 1 km


# --- Perfiles ----------------------------------------------------------------


def base_file():
    return models.TargetsBaseFile.model_validate(json.loads((FIX / "targets_base.json").read_text(encoding="utf-8")))


def earth():
    return {v: models.EarthStats(p01=0.0, p99=10.0, std=2.0) for v in PHYSICAL_VARS}


def recording_rule(calls):
    def choose(variable, mean, p01, p99, has_ice):
        calls.append((variable, mean, p01, p99, has_ice))
        return "overlap"

    return choose


MEASURED = {"mars_jezero": {"slope_deg": (4.5, 2.0, 3000), "roughness_m": (38.0, 9.0, 3000)}}


def test_build_targets_uses_measured_and_literature_values():
    calls = []
    out = step07.build_targets(base_file(), MEASURED, earth(), recording_rule(calls))
    (jezero,) = out.targets
    assert jezero.vars["slope_deg"].mean == 4.5 and jezero.vars["slope_deg"].std == 2.0  # leída
    assert jezero.vars["slope_deg"].source_type == "measured"
    assert jezero.vars["tmin_c"].mean == -83.0 and jezero.vars["tmin_c"].source_type == "literature"  # de la base
    assert jezero.vars["precip_mm"].mean == 0.0 and jezero.vars["precip_mm"].source_type == "definition"
    assert all(jezero.vars[v].earth_p99 == 10.0 and jezero.vars[v].earth_std == 2.0 for v in PHYSICAL_VARS)
    assert set(jezero.vars) == set(PHYSICAL_VARS)


def test_build_targets_asks_the_rule_with_the_target_mean_and_has_ice():
    calls = []
    step07.build_targets(base_file(), MEASURED, earth(), recording_rule(calls))
    assert [c[0] for c in calls] == list(PHYSICAL_VARS)
    by_var = {c[0]: c for c in calls}
    assert by_var["slope_deg"][1] == 4.5 and by_var["tmin_c"][1] == -83.0
    assert all(c[4] is False for c in calls)  # Jezero: has_ice = false


def test_build_targets_output_validates_and_keeps_the_common_fields():
    out = step07.build_targets(base_file(), MEASURED, earth(), recording_rule([]))
    again = models.TargetsFile.model_validate(json.loads(out.model_dump_json()))
    assert again.targets[0].target_id == "mars_jezero" and again.targets[0].unreplicable


def test_measured_variable_without_a_reading_fails():
    with pytest.raises(MissingInputError, match="no se leyó"):
        step07.build_targets(base_file(), {}, earth(), recording_rule([]))


def test_measured_temperature_stops_with_the_ticket_to_blame():
    raw = json.loads((FIX / "targets_base.json").read_text(encoding="utf-8"))
    raw["targets"][0]["vars"]["tmin_c"] = {"unit": "°C", "source": "MEDA", "source_type": "measured"}
    base = models.TargetsBaseFile.model_validate(raw)
    with pytest.raises(MissingInputError, match="TAI-05"):
        step07.build_targets(base, MEASURED, earth(), recording_rule([]))


# --- Estadísticas de la Tierra (paso 06) -------------------------------------


def test_load_earth_stats_reads_the_manifest_of_step_06(tmp_path):
    stats = {v: {"p01": 0.0, "p99": 9.0, "std": 3.0} for v in PHYSICAL_VARS}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"steps": [{"step": "06_features", "earth_stats": stats}]}), encoding="utf-8")
    got = step07.load_earth_stats(path)
    assert set(got) == set(PHYSICAL_VARS) and got["tmin_c"].p99 == 9.0


def test_load_earth_stats_says_step_06_has_not_run(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"steps": [{"step": "01_grid"}]}), encoding="utf-8")
    with pytest.raises(MissingInputError, match="06_features"):
        step07.load_earth_stats(path)


def test_load_earth_stats_rejects_missing_variables(tmp_path):
    stats = {"tmin_c": {"p01": 0.0, "p99": 9.0, "std": 3.0}}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"steps": [{"step": "06_features", "earth_stats": stats}]}), encoding="utf-8")
    with pytest.raises(MissingInputError, match="no trae"):
        step07.load_earth_stats(path)
