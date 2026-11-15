"""Step 06: join the four intermediate files into features.parquet (design 6.1, TAI-18).

Reads:  data/interim/terrain.parquet      (step 02: slope_deg, roughness_m)
        data/interim/temperature.parquet  (step 03: tmin_c, trange_c)
        data/interim/water_ice.parquet    (step 04: precip_mm, ice_frac)
        data/interim/dust_wind.parquet    (step 04_dust_wind: dust_aod, wind_ms; TAI-52)
        data/interim/biology.parquet      (step 05: bio_records, bio_types, bio_type_list)
        data/processed/grid.parquet       (step 01)
Writes: data/processed/features.parquet   one row per grid cell (contract 3.2)
        manifest.json, entry 06_features  with earth_stats: p01, p99 and std of
                                          each physical variable, weighted by area

Outer join over the grid: a cell missing from an intermediate file keeps that
variable null (never 0). coverage counts the physical variables with data
(0 to 6) and n_physical the physical dimensions with at least one (0 to 3).
A cell without biology records gets 0 / 0 / "". bio_type_list is rewritten in
alphabetical order, as the contract asks.

earth_stats feeds step 07, which picks each target's rule with the 1st and
99th percentiles, and the overlap rule's sigma floor (design 5.1 and 5.2).
They are weighted by area_km2 because 1-degree cells shrink toward the poles.
If any input came from a --bbox run, this output is partial too and the
manifest says so.
"""

import sys
import time
from pathlib import Path

# Steps run as `python pipeline/NN_step.py`; put the repo root on the path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from pipeline.common import (  # noqa: E402
    GRID_PATH,
    INTERIM,
    PARTIAL_NOTE_PREFIX,
    PROCESSED,
    ROOT,
    OutputValidationError,
    atomic_write_parquet,
    column_stats,
    is_up_to_date,
    last_run_partial,
    load_grid,
    make_parser,
    require_inputs,
    run,
    setup_logging,
    step_entry,
    validate_output,
    write_step_manifest,
)
from tai import rules  # noqa: E402
from tai.constants import CORE_DIMENSIONS, DIMENSION_VARS, PHYSICAL_VARS  # noqa: E402

STEP = "06_features"
OUTPUT = PROCESSED / "features.parquet"

# intermediate file -> (step that writes it, columns taken from it)
SOURCES = {
    "terrain": ("02_terrain", INTERIM / "terrain.parquet", ["slope_deg", "roughness_m"]),
    "temperature": ("03_temperature", INTERIM / "temperature.parquet", ["tmin_c", "trange_c"]),
    "water_ice": ("04_water_ice", INTERIM / "water_ice.parquet", ["precip_mm", "ice_frac"]),
    "dust_wind": ("04_dust_wind", INTERIM / "dust_wind.parquet", ["dust_aod", "wind_ms"]),
    "biology": ("05_biology_ncbi", INTERIM / "biology.parquet", ["bio_records", "bio_types", "bio_type_list"]),
}
BIO_COLUMNS = SOURCES["biology"][2]


def _take(df: pd.DataFrame, columns: list[str], name: str) -> pd.DataFrame:
    missing = [c for c in ["cell_id", *columns] if c not in df.columns]
    if missing:
        raise OutputValidationError(f"{name}.parquet no trae las columnas {missing}")
    if df["cell_id"].duplicated().any():
        raise OutputValidationError(f"{name}.parquet tiene cell_id repetidos")
    return df[["cell_id", *columns]]


def _alphabetical(type_list: pd.Series) -> pd.Series:
    return type_list.map(lambda s: ",".join(sorted(t for t in s.split(",") if t)))


def build_features(grid: pd.DataFrame, parts: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """features.parquet from the grid and the four intermediate tables (keys of SOURCES)."""
    out = grid[["cell_id"]].astype({"cell_id": "int32"})
    for name, (_, _, columns) in SOURCES.items():
        part = _take(parts[name], columns, name)
        unknown = ~part["cell_id"].isin(out["cell_id"])
        if unknown.any():
            raise OutputValidationError(f"{name}.parquet tiene {int(unknown.sum())} celdas fuera de la grilla")
        out = out.merge(part, on="cell_id", how="left")

    out["bio_records"] = out["bio_records"].fillna(0).astype("int32")
    out["bio_types"] = out["bio_types"].fillna(0).astype("int8")
    out["bio_type_list"] = _alphabetical(out["bio_type_list"].fillna("").astype(str)).astype("string")
    for v in PHYSICAL_VARS:
        out[v] = out[v].astype("float32")

    has = out[list(PHYSICAL_VARS)].notna()
    out["coverage"] = has.sum(axis=1).astype("int8")
    # Core dimensions only: n_physical decides eligibility, and dust and wind (TAI-52) does not count.
    out["n_physical"] = sum(has[list(DIMENSION_VARS[d])].any(axis=1).astype(int)
                            for d in CORE_DIMENSIONS).astype("int8")
    return out[["cell_id", *PHYSICAL_VARS, *BIO_COLUMNS, "coverage", "n_physical"]]


def earth_stats(features: pd.DataFrame, grid: pd.DataFrame) -> dict[str, dict[str, float]]:
    """p01, p99 and std of each physical variable over the cells with data, weighted by area."""
    area = features[["cell_id"]].merge(grid[["cell_id", "area_km2"]], on="cell_id", how="left")["area_km2"]
    stats = {}
    for v in PHYSICAL_VARS:
        x = features[v].to_numpy(dtype=np.float64)
        if np.isnan(x).all():
            raise OutputValidationError(f"{v}: ninguna celda tiene dato; no hay estadística terrestre")
        a = area.to_numpy(dtype=np.float64)
        stats[v] = {
            "p01": round(rules.weighted_quantile(x, a, 0.01), 3),
            "p99": round(rules.weighted_quantile(x, a, 0.99), 3),
            "std": round(rules.weighted_std(x, a), 3),
        }
    return stats


def main() -> None:
    args = make_parser(STEP, __doc__.splitlines()[0]).parse_args()
    log = setup_logging(STEP)
    started = time.monotonic()

    paths = [p for _, p, _ in SOURCES.values()]
    require_inputs([GRID_PATH, *paths])
    code = [Path(__file__), ROOT / "pipeline" / "common.py", ROOT / "tai" / "rules.py", ROOT / "tai" / "constants.py"]
    if not args.force and is_up_to_date([OUTPUT], [GRID_PATH, *paths, *code]) and not last_run_partial(STEP):
        log.info("al día")
        return

    grid = load_grid()
    features = build_features(grid, {name: pd.read_parquet(p) for name, (_, p, _) in SOURCES.items()})
    stats = earth_stats(features, grid)

    partial = [step for step, _, _ in SOURCES.values() if last_run_partial(step)]
    by_dims = features["n_physical"].value_counts().sort_index()
    notes = ["celdas por dimensiones físicas con dato: " + ", ".join(f"{k}: {v}" for k, v in by_dims.items())]
    if partial:
        notes.append(f"{PARTIAL_NOTE_PREFIX} viene de pasos parciales ({', '.join(partial)})")
        log.warning("inputs from partial runs: %s; this output is partial too", ", ".join(partial))

    validate_output(features, grid_ids=grid["cell_id"], schema="features")
    atomic_write_parquet(features, OUTPUT)
    write_step_manifest(
        step_entry(
            STEP,
            started,
            inputs=[{"name": "Archivos intermedios de los pasos 02 a 05", "product": ", ".join(p.name for p in paths),
                     "portal": "Pipeline del proyecto", "url": "https://github.com/NASA-spaceapps-sigsegv/terra-analog-index",
                     "files": len(paths), "size_mb": round(sum(p.stat().st_size for p in paths) / 1e6, 1),
                     "license_note": "Datos derivados del proyecto"}],
            outputs=[(OUTPUT, len(features))],
            columns=column_stats(features, [*PHYSICAL_VARS, "bio_records", "bio_types", "coverage", "n_physical"]),
            notes=notes,
            earth_stats=stats,
        )
    )
    for v, s in stats.items():
        log.info("%s: p01 %s, p99 %s, std %s (ponderados por área)", v, s["p01"], s["p99"], s["std"])
    log.info("wrote %s (%d cells)", OUTPUT.name, len(features))


if __name__ == "__main__":
    run(main)
