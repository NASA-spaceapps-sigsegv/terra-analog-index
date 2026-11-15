"""Column contracts of the Parquet/CSV files in data/processed/ (contracts 3.1 to 3.5).

Each schema maps column -> (dtype, nullable). The pipeline checks its output
against these before writing; tai.io checks them again when loading.
"""

from types import MappingProxyType

import pandas as pd

from tai.constants import PHYSICAL_VARS

Schema = MappingProxyType

GRID = Schema(
    {
        "cell_id": ("int32", False),
        "lat_idx": ("int16", False),
        "lon_idx": ("int16", False),
        "lat": ("float32", False),
        "lon": ("float32", False),
        "area_km2": ("float32", False),
        "land_frac": ("float32", False),
        "country": ("string", True),
    }
)

FEATURES = Schema(
    {
        "cell_id": ("int32", False),
        **{v: ("float32", True) for v in PHYSICAL_VARS},
        "bio_records": ("int32", False),
        "bio_types": ("int8", False),
        "bio_type_list": ("string", False),
        "coverage": ("int8", False),
        "n_physical": ("int8", False),
    }
)

BIO_SAMPLES = Schema(
    {
        "accession": ("string", False),
        "extremophile_type": ("string", False),
        "organism": ("string", True),
        "lat": ("float32", False),
        "lon": ("float32", False),
        "cell_id": ("int32", False),
        "env_broad_scale": ("string", True),
        "isolation_source": ("string", True),
        "geo_loc_name": ("string", True),
    }
)

SIMILARITY = Schema(
    {
        "cell_id": ("int32", False),
        "target_id": ("string", False),
        **{f"sv_{v}": ("float32", True) for v in PHYSICAL_VARS},
        "s_terrain": ("float32", True),
        "s_temperature": ("float32", True),
        "s_water_ice": ("float32", True),
        "s_dust_wind": ("float32", True),
        "bio_score": ("float32", False),
        "n_physical": ("int8", False),
        "eligible": ("bool", False),
        "known_analog": ("string", True),
        "known_analog_km": ("float32", True),
    }
)

KNOWN_ANALOGS_COLUMNS = (
    "analog_id",
    "name",
    "lat",
    "lon",
    "radius_km",
    "target_id",
    "basis",
    "covered",
    "source",
)

PRIMARY_KEYS = MappingProxyType(
    {
        "grid": ("cell_id",),
        "features": ("cell_id",),
        "bio_samples": ("accession", "extremophile_type"),
        "similarity": ("cell_id", "target_id"),
    }
)

BY_NAME = MappingProxyType(
    {
        "grid": GRID,
        "features": FEATURES,
        "bio_samples": BIO_SAMPLES,
        "similarity": SIMILARITY,
    }
)


def _dtype_matches(series: pd.Series, dtype: str) -> bool:
    if dtype == "string":
        return pd.api.types.is_string_dtype(series) or series.isna().all()
    return str(series.dtype) == dtype


def check_schema(df: pd.DataFrame, name: str) -> list[str]:
    """Return a list of contract violations (empty if df matches the named schema)."""
    schema = BY_NAME[name]
    problems: list[str] = []
    missing = [c for c in schema if c not in df.columns]
    extra = [c for c in df.columns if c not in schema]
    if missing:
        problems.append(f"{name}: missing columns {missing}")
    if extra:
        problems.append(f"{name}: unexpected columns {extra}")
    for col, (dtype, nullable) in schema.items():
        if col not in df.columns:
            continue
        if not _dtype_matches(df[col], dtype):
            problems.append(f"{name}.{col}: dtype {df[col].dtype}, expected {dtype}")
        if not nullable and df[col].isna().any():
            problems.append(f"{name}.{col}: has nulls but is not nullable")
    key = list(PRIMARY_KEYS[name])
    if all(k in df.columns for k in key) and df.duplicated(subset=key).any():
        problems.append(f"{name}: duplicate primary key {key}")
    return problems
