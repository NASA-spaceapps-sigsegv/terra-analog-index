"""TAI-24: la lógica de scripts/check_maps.py (sin dibujar: no necesita Plotly)."""

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("check_maps", ROOT / "scripts" / "check_maps.py")
cm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cm)


def _grid(points):
    from tai import geo

    df = pd.DataFrame(points, columns=["lat", "lon"])
    df["cell_id"] = [int(geo.cell_id_of(a, b)) for a, b in points]
    return df


def _analogs(*rows):
    return pd.DataFrame(rows, columns=["analog_id", "name", "lat", "lon", "target_id"])


def test_analog_inside_and_outside_the_grid():
    grid = _grid([(-24.5, -69.5), (0.5, 0.5)])
    res = cm.check_analogs(
        _analogs(("atacama", "Atacama", -24.1, -69.3, "mars_jezero"), ("mar", "Mar abierto", 10.2, 10.2, "mars_jezero")),
        grid,
    ).set_index("analog_id")
    assert res.loc["atacama", "in_grid"] and pd.isna(res.loc["atacama", "nearest_cell_km"])
    assert not res.loc["mar", "in_grid"]
    assert res.loc["mar", "nearest_cell_km"] > 1000


def test_invalid_coordinates_do_not_crash():
    res = cm.check_analogs(_analogs(("raro", "Fuera de rango", 95.0, 0.0, "moon_south_pole")), _grid([(0.5, 0.5)]))
    assert not res.loc[0, "in_grid"] and res.loc[0, "error"]
    assert pd.isna(res.loc[0, "nearest_cell_km"])


def test_range_and_null_checks():
    df = pd.DataFrame({"lat": [0.5] * 4, "lon": [0.5] * 4, "slope_deg": [10.0, 95.0, np.nan, 5.0]})
    assert cm.range_check(df, "slope_deg")["status"] == "REVISAR"
    assert cm.null_check(df, "slope_deg", 0.05)["status"] == "REVISAR"  # 25% de nulos
    assert cm.null_check(df, "slope_deg")["status"] == "?"  # sin umbral: solo informa


def test_regional_percentile_flags_a_flat_andes():
    lat = np.repeat(np.arange(-89.5, 90, 5.0), 72)
    lon = np.tile(np.arange(-177.5, 180, 5.0), 36)
    df = pd.DataFrame({"lat": lat, "lon": lon, "slope_deg": 5.0})
    df.loc[cm.in_box(df, "Himalaya").index, "slope_deg"] = 30.0
    assert cm.high_low(df, "slope_deg", "Himalaya", True, 0.75)["status"] == "OK"
    assert cm.high_low(df, "slope_deg", "Andes", True, 0.75)["status"] == "REVISAR"
    assert cm.high_low(df, "slope_deg", "Andes", False, 0.75)["status"] == "OK"


def test_report_lists_analogs_outside_the_grid(tmp_path):
    res = cm.check_analogs(_analogs(("mar", "Mar abierto", 10.2, 10.2, "mars_jezero")), _grid([(0.5, 0.5)]))
    cm.write_report(tmp_path / "informe.md", {"terrain": ("TAI-12", "Juanma", [cm.check("x", True, "ok")])}, res)
    text = (tmp_path / "informe.md").read_text(encoding="utf-8")
    assert "Avisar a: Juanma" in text and "`mar`" in text and "NO caen" in text


def test_report_marks_invalid_coordinates(tmp_path):
    res = cm.check_analogs(_analogs(("raro", "Fuera de rango", 95.0, 0.0, "moon_south_pole")), _grid([(0.5, 0.5)]))
    cm.write_report(tmp_path / "informe.md", {}, res)
    assert "coordenadas inválidas" in (tmp_path / "informe.md").read_text(encoding="utf-8")
