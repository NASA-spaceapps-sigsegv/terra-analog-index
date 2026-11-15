"""Regenerate the Parquet fixtures in this folder.

Values follow the examples in "Contratos JSON e interfaces". Numbers are
illustrative, not results. Usage: python tests/fixtures/make_fixtures.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parents[1]))  # repo root, so `tai` imports without installing

from tai import geo  # noqa: E402
from tai.constants import OPTIONAL_VARS, PHYSICAL_VARS, TARGET_IDS  # noqa: E402

# cell_id, land_frac, country
CELLS = [
    (1620, 1.0, None),  # Antarctica, 85.5 S
    (23510, 1.0, "Chile"),  # Atacama (design 2.1 example)
    (40870, 1.0, "Argelia"),  # Sahara
    (45893, 0.8, "España"),  # Rio Tinto (validation example)
]


def grid() -> pd.DataFrame:
    ids = np.array([c[0] for c in CELLS], dtype="int32")
    lat_idx, lon_idx = geo.split_cell_id(ids)
    lat, lon = geo.cell_center(ids)
    return pd.DataFrame(
        {
            "cell_id": ids,
            "lat_idx": lat_idx.astype("int16"),
            "lon_idx": lon_idx.astype("int16"),
            "lat": lat.astype("float32"),
            "lon": lon.astype("float32"),
            "area_km2": geo.cell_area_km2(lat_idx).astype("float32"),
            "land_frac": np.array([c[1] for c in CELLS], dtype="float32"),
            "country": pd.array([c[2] for c in CELLS], dtype="string"),
        }
    )


def features() -> pd.DataFrame:
    rows = {
        #        slope roughness  tmin  trange precip  ice   dust_aod wind_ms
        1620: (1.2, 15.0, -62.0, 12.0, None, 1.0, 0.003, 12.0),
        23510: (3.5, 38.0, -4.2, 31.6, 3.0, 0.05, 0.05, 5.5),
        40870: (2.1, 25.0, 4.5, 28.0, 20.0, 0.0, 0.35, 6.0),
        45893: (None, None, 6.0, 14.5, 650.0, 0.0, 0.08, 3.5),
    }
    df = pd.DataFrame.from_dict(rows, orient="index", columns=list(PHYSICAL_VARS))
    df.index.name = "cell_id"
    df = df.reset_index().astype({"cell_id": "int32", **{v: "float32" for v in PHYSICAL_VARS}})
    df["bio_records"] = np.array([4, 15, 0, 9], dtype="int32")
    df["bio_types"] = np.array([1, 2, 0, 1], dtype="int8")
    df["bio_type_list"] = pd.array(
        ["psychrophile", "halophile,xerophile", "", "acidophile"], dtype="string"
    )
    present = df[list(PHYSICAL_VARS)].notna()
    df["coverage"] = present.sum(axis=1).astype("int8")
    dims = [("slope_deg", "roughness_m"), ("tmin_c", "trange_c"), ("precip_mm", "ice_frac")]
    df["n_physical"] = sum(present[list(d)].any(axis=1) for d in dims).astype("int8")
    return df


def bio_samples() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "accession": pd.array(["SAMN00000001", "SAMN00000001", "SAMN00000002"], dtype="string"),
            "extremophile_type": pd.array(["halophile", "xerophile", "acidophile"], dtype="string"),
            "organism": pd.array(["salt lake metagenome", "salt lake metagenome", None], dtype="string"),
            "lat": np.array([-24.08, -24.08, 37.72], dtype="float32"),
            "lon": np.array([-69.92, -69.92, -6.55], dtype="float32"),
            "cell_id": np.array([23510, 23510, 45893], dtype="int32"),
            "env_broad_scale": pd.array(["desert biome", "desert biome", None], dtype="string"),
            "isolation_source": pd.array(
                ["hypersaline lagoon sediment", "hypersaline lagoon sediment", "acid mine drainage"],
                dtype="string",
            ),
            "geo_loc_name": pd.array(["Chile: Atacama", "Chile: Atacama", "Spain: Huelva"], dtype="string"),
        }
    )


def similarity() -> pd.DataFrame:
    feats = features().set_index("cell_id")
    rows = []
    for target_id in TARGET_IDS:
        for cell_id in feats.index:
            f = feats.loc[cell_id]
            # Deterministic illustrative scores; null where the variable is null.
            base = (cell_id % 97) / 97
            sv = {
                f"sv_{v}": (None if pd.isna(f[v]) else round(0.2 + 0.6 * ((base + i / 7) % 1), 3))
                for i, v in enumerate(PHYSICAL_VARS)
            }
            # targets.json de ejemplo no trae polvo y viento (TAI-52, opcional): sin puntaje en ningún objetivo.
            sv |= {f"sv_{v}": None for v in OPTIONAL_VARS}
            dims = {
                "s_terrain": ("sv_slope_deg", "sv_roughness_m"),
                "s_temperature": ("sv_tmin_c", "sv_trange_c"),
                "s_water_ice": ("sv_precip_mm", "sv_ice_frac"),
                "s_dust_wind": ("sv_dust_aod", "sv_wind_ms"),
            }
            sd = {}
            for name, cols in dims.items():
                vals = [sv[c] for c in cols if sv[c] is not None]
                sd[name] = round(float(np.mean(vals)), 3) if vals else None
            n_physical = int(f["n_physical"])
            near = cell_id == 23510 and target_id == "mars_jezero"
            rows.append(
                {
                    "cell_id": cell_id,
                    "target_id": target_id,
                    **sv,
                    **sd,
                    "bio_score": round(min(1.0, np.log1p(f["bio_records"]) / 7), 3),
                    "n_physical": n_physical,
                    "eligible": n_physical >= 2,
                    "known_analog": "atacama_yungay" if near else None,
                    "known_analog_km": 67.0 if near else None,
                }
            )
    df = pd.DataFrame(rows)
    float_cols = [c for c in df.columns if c.startswith(("sv_", "s_"))] + ["bio_score", "known_analog_km"]
    return df.astype(
        {
            "cell_id": "int32",
            "target_id": "string",
            **{c: "float32" for c in float_cols},
            "n_physical": "int8",
            "eligible": "bool",
            "known_analog": "string",
        }
    )


def main() -> None:
    for name, fn in [
        ("grid", grid),
        ("features", features),
        ("bio_samples", bio_samples),
        ("similarity", similarity),
    ]:
        fn().to_parquet(HERE / f"{name}.parquet", index=False)
        print(f"wrote {name}.parquet")


if __name__ == "__main__":
    main()
