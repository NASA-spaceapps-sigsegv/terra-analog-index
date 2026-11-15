"""Datos de prueba mínimos de data/processed/ armados a mano (6 celdas, 2 objetivos).

Diseñados para que mover los pesos cambie el orden:
  pesos iniciales      -> 104, 102, 100, 101   (100 y 101 empatan: gana el cell_id menor)
  terreno en 0         -> 101, 102, 104, 100, 105
  103 tiene 1 sola dimensión física: no es elegible. 105 es análogo conocido.
"""

import json

import numpy as np
import pandas as pd
import pytest

from tai import geo
from tai.constants import PHYSICAL_VARS, TARGET_IDS

CELLS = [100, 101, 102, 103, 104, 105]
NAN = np.nan
#            terrain temperature water_ice bio
SCORES = [
    (0.9, 0.1, 0.5, 0.0),  # 100
    (0.1, 0.9, 0.5, 0.0),  # 101
    (0.5, 0.5, 0.5, 0.2),  # 102
    (NAN, NAN, 0.9, 0.0),  # 103: no elegible
    (0.6, NAN, 0.6, 0.1),  # 104
    (0.3, 0.3, 0.3, 0.0),  # 105: análogo conocido
]


def _grid() -> pd.DataFrame:
    lat_idx, lon_idx = geo.split_cell_id(np.array(CELLS))
    lat, lon = geo.cell_center(np.array(CELLS))
    return pd.DataFrame(
        {
            "cell_id": np.array(CELLS, dtype="int32"),
            "lat_idx": lat_idx.astype("int16"),
            "lon_idx": lon_idx.astype("int16"),
            "lat": lat.astype("float32"),
            "lon": lon.astype("float32"),
            "area_km2": np.asarray(geo.cell_area_km2(lat_idx), dtype="float32"),
            "land_frac": np.ones(len(CELLS), dtype="float32"),
            "country": pd.array(["Chile"] * 5 + [None], dtype="string"),
        }
    )


def _features() -> pd.DataFrame:
    n = len(CELLS)
    df = pd.DataFrame({"cell_id": np.array(CELLS, dtype="int32")})
    for v in PHYSICAL_VARS:
        df[v] = np.full(n, 1.0, dtype="float32")
    df["bio_records"] = np.zeros(n, dtype="int32")
    df["bio_types"] = np.zeros(n, dtype="int8")
    df["bio_type_list"] = pd.array([""] * n, dtype="string")
    df["coverage"] = np.full(n, 3, dtype="int8")
    df["n_physical"] = np.full(n, 3, dtype="int8")
    return df


def _bio_samples() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "accession": pd.array(["SAMN00000001"], dtype="string"),
            "extremophile_type": pd.array(["halophile"], dtype="string"),
            "organism": pd.array([None], dtype="string"),
            "lat": np.array([0.5], dtype="float32"),
            "lon": np.array([0.5], dtype="float32"),
            "cell_id": np.array([100], dtype="int32"),
            "env_broad_scale": pd.array([None], dtype="string"),
            "isolation_source": pd.array([None], dtype="string"),
            "geo_loc_name": pd.array([None], dtype="string"),
        }
    )


def _similarity() -> pd.DataFrame:
    s = np.array(SCORES, dtype="float32")
    frames = []
    for target_id in TARGET_IDS:
        df = pd.DataFrame({"cell_id": np.array(CELLS, dtype="int32"), "target_id": pd.array([target_id] * len(CELLS), dtype="string")})
        for v in PHYSICAL_VARS:
            df[f"sv_{v}"] = np.full(len(CELLS), NAN, dtype="float32")
        df["s_terrain"], df["s_temperature"], df["s_water_ice"], df["bio_score"] = (s[:, i] for i in range(4))
        df["s_dust_wind"] = np.full(len(CELLS), NAN, dtype="float32")  # TAI-52: sin dato, no altera el orden
        df["bio_score"] = df["bio_score"].astype("float32")
        phys = df[["s_terrain", "s_temperature", "s_water_ice"]].notna().sum(axis=1)
        df["n_physical"] = phys.astype("int8")
        df["eligible"] = phys >= 2
        df["known_analog"] = pd.array([None] * 5 + ["atacama_yungay"], dtype="string")
        df["known_analog_km"] = np.array([NAN] * 5 + [10.0], dtype="float32")
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def _target(target_id: str, body: str, bounds: dict) -> dict:
    var = {"mean": 1.0, "std": 1.0, "unit": "u", "rule": "overlap", "source": "prueba",
           "source_type": "literature", "earth_p01": 0.0, "earth_p99": 10.0, "earth_std": 2.0}
    return {"target_id": target_id, "label": f"Objetivo {target_id}", "body": body, "bounds": bounds,
            "has_ice": body == "moon", "has_ice_source": "prueba", "summary": "resumen de prueba",
            "unreplicable": ["gravedad"], "notes": [], "vars": {v: dict(var) for v in PHYSICAL_VARS}}


def write_bundle(path) -> None:
    _grid().to_parquet(path / "grid.parquet")
    _features().to_parquet(path / "features.parquet")
    _bio_samples().to_parquet(path / "bio_samples.parquet")
    _similarity().to_parquet(path / "similarity.parquet")
    targets = {"schema_version": 1, "targets": [
        _target("moon_south_pole", "moon", {"lat_min": -90, "lat_max": -85, "lon_min": -180, "lon_max": 180}),
        _target("mars_jezero", "mars", {"lat_min": 17.9, "lat_max": 18.9, "lon_min": 77.0, "lon_max": 78.0}),
    ]}
    (path / "targets.json").write_text(json.dumps(targets), encoding="utf-8")
    (path / "known_analogs.csv").write_text(
        "analog_id,name,lat,lon,radius_km,target_id,basis,covered,source\n"
        "atacama_yungay,Atacama,-24.1,-69.3,150,mars_jezero,hiperaridez,yes,prueba\n", encoding="utf-8")
    validation = {"schema_version": 1, "generated_at": "2026-11-14T15:30:00Z",
                  "weights": {"terrain": 1, "temperature": 1, "water_ice": 1, "biology": 0.5},
                  "percentile_threshold": 90,
                  "targets": [{"target_id": t, "result": "insufficient", "covered_total": 0, "covered_passed": 0,
                               "n_eligible": 5, "analogs": []} for t in TARGET_IDS]}
    (path / "validation.json").write_text(json.dumps(validation), encoding="utf-8")
    manifest = {"schema_version": 1, "project": "terra-analog-index", "data_year": 2024, "grid": None, "steps": []}
    (path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


@pytest.fixture
def data_dir(tmp_path):
    write_bundle(tmp_path)
    return tmp_path
