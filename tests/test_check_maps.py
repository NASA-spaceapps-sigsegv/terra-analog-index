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
    results = {"terrain": dict(ticket="TAI-12", owner="Juanma", checks=[cm.check("x", True, "ok")])}
    cm.write_report(tmp_path / "informe.md", results, res, [], [])
    text = (tmp_path / "informe.md").read_text(encoding="utf-8")
    assert "Avisar a: Juanma" in text and "`mar`" in text and "NO caen" in text


def test_report_marks_invalid_coordinates(tmp_path):
    res = cm.check_analogs(_analogs(("raro", "Fuera de rango", 95.0, 0.0, "moon_south_pole")), _grid([(0.5, 0.5)]))
    cm.write_report(tmp_path / "informe.md", {}, res, [], [])
    assert "coordenadas inválidas" in (tmp_path / "informe.md").read_text(encoding="utf-8")


def test_regional_check_uses_the_median():
    # una caja llana con un macizo adentro (como el Tibesti en el Sahara)
    lat = np.repeat(np.arange(-89.5, 90, 1.0), 4)
    df = pd.DataFrame({"lat": lat, "lon": np.tile([10.5, 11.5, 12.5, 13.5], len(lat) // 4), "slope_deg": 1.0})
    df.loc[~df["lat"].between(18, 28), "slope_deg"] = np.linspace(0.5, 3.0, int((~df["lat"].between(18, 28)).sum()))
    box = cm.in_box(df, "Sahara").index
    df.loc[box, "slope_deg"] = 0.6
    df.loc[box[:4], "slope_deg"] = 20.0  # media de la caja ~ 2.5, mediana 0.6
    assert cm.high_low(df, "slope_deg", "Sahara", False, 0.5)["status"] == "OK"


def test_rel_never_fails_outside_the_root(tmp_path):
    root = tmp_path / "repo"
    assert cm.rel(root / "data" / "x.html", root) == str(Path("data") / "x.html")
    assert cm.rel(tmp_path / "otro" / "x.html", root) == str(tmp_path / "otro" / "x.html")


def test_manifest_checks():
    df = pd.DataFrame({"cell_id": [1, 2], "slope_deg": [1.0, np.nan], "roughness_m": [2.0, 3.0]})
    entry = {"step": "02_terrain", "notes": [], "columns": {"slope_deg": {"null": 1}, "roughness_m": {"null": 1}}}
    st = {c["name"]: c["status"] for c in cm.manifest_checks("terrain", df, {"steps": [entry]})}
    assert st == {"manifiesto: nulos de slope_deg": "OK", "manifiesto: nulos de roughness_m": "REVISAR"}
    assert cm.manifest_checks("terrain", df, {"steps": []})[0]["status"] == "REVISAR"
    assert cm.manifest_checks("terrain", df, None)[0]["status"] == "?"
    partial = {"steps": [{"step": "02_terrain", "notes": ["partial run: --bbox -30 -20 -75 -60"]}]}
    assert cm.partial_steps(partial) == {"02_terrain"}


def test_analog_rules_count_places_not_rows():
    rows = [(f"a{i}", f"A{i}", 0.0, 0.0, t, 150, "yes", "fuente") for i in range(4) for t in ("mars_jezero", "moon_south_pole")]
    a = pd.DataFrame(rows, columns=["analog_id", "name", "lat", "lon", "target_id", "radius_km", "covered", "source"])
    st = {c["name"]: c["status"] for c in cm.analog_rule_checks(a)}
    assert st["entre 8 y 12 análogos"] == "REVISAR"  # 8 filas pero 4 lugares
    assert st["al menos 3 cubiertos (covered = yes) en mars_jezero"] == "OK"
    a.loc[0, "source"] = " "
    a.loc[1, "target_id"] = "mars_gale"
    st = {c["name"]: c["status"] for c in cm.analog_rule_checks(a)}
    assert st["ninguna fila sin fuente"] == "REVISAR" and st["target_id conocidos"] == "REVISAR"


def test_main_on_a_synthetic_repo(tmp_path):
    from tai import geo

    root, out = tmp_path / "repo", tmp_path / "fuera"  # la salida queda fuera de la raíz
    pts = [(-23.5, -69.5), (0.5, 10.5), (-86.5, 0.5)]
    ids = np.array([geo.cell_id_of(*p) for p in pts], dtype="int32")
    (root / "data" / "processed").mkdir(parents=True)
    (root / "data" / "interim").mkdir()
    pd.DataFrame({"cell_id": ids, "lat": [p[0] for p in pts], "lon": [p[1] for p in pts], "country": ["Chile", "Gabón", None],
                  "area_km2": [11000.0, 12000.0, 700.0], "land_frac": [1.0, 0.8, 1.0]}).to_parquet(root / "data/processed/grid.parquet")
    pd.DataFrame({"cell_id": ids, "slope_deg": [2.6, 0.5, 0.1], "roughness_m": [54.0, 8.0, 3.0]}).to_parquet(root / "data/interim/terrain.parquet")
    assert cm.main(["--root", str(root), "--only", "grid", "terrain", "--checks-only", "--out", str(out)]) == 0
    assert (out / "informe.md").exists() and (out / "index.html").exists()
    assert "Avisar a: Juanma" in (out / "informe.md").read_text(encoding="utf-8")
    assert cm.main(["--root", str(root), "--only", "temperature", "--checks-only", "--out", str(out)]) == 2  # falta el archivo
    assert cm.main(["--root", str(root), "--checks-only", "--strict", "--out", str(out)]) == 1  # 3 celdas: REVISAR


def test_strict_flags_an_analog_outside_the_grid(tmp_path):
    from tai import geo

    root = tmp_path / "repo"
    (root / "data" / "processed").mkdir(parents=True)
    (root / "config").mkdir()
    cid = np.array([geo.cell_id_of(-24.5, -69.5)], dtype="int32")
    pd.DataFrame({"cell_id": cid, "lat": [-24.5], "lon": [-69.5], "area_km2": [11000.0],
                  "land_frac": [1.0]}).to_parquet(root / "data/processed/grid.parquet")
    rows = ["analog_id,name,lat,lon,radius_km,target_id,basis,covered,source",
            "atacama,Atacama,-24.1,-69.3,150,mars_jezero,aridez,yes,x",
            "lanzarote,Lanzarote,29.0,-13.6,150,moon_south_pole,basalto,no,x"]
    (root / "config" / "known_analogs.csv").write_text("\n".join(rows), encoding="utf-8")
    out = tmp_path / "out"
    assert cm.main(["--root", str(root), "--only", "grid", "--checks-only", "--strict", "--out", str(out)]) == 1
    assert "fuera: lanzarote" in (out / "informe.md").read_text(encoding="utf-8")
