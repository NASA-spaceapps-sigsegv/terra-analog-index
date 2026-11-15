"""Step 04 (dust and wind, TAI-52): annual dust optical depth and surface wind speed per cell.

Reads:  data/raw/04_dust_wind/m2tmnxaer/MERRA2_*.tavgM_2d_aer_Nx.<YYYYMM>.nc4  (12 months, DUEXTTAU)
        data/raw/04_dust_wind/m2tmnxflx/MERRA2_*.tavgM_2d_flx_Nx.<YYYYMM>.nc4  (12 months, SPEED)
        data/processed/grid.parquet  (step 01)
Writes: data/interim/dust_wind.parquet  (cell_id, dust_aod, wind_ms)

  dust_aod = mean of the 12 monthly means of the dust extinction optical depth at 550 nm
  wind_ms  = mean of the 12 monthly means of the surface wind speed (m/s)

MERRA-2 is a reanalysis on a 0.5° x 0.625° grid with no gaps (poles included), so every cell gets a
value: each 1° cell averages the 2 to 4 MERRA-2 points whose centers fall inside it. There is no land
mask: at this resolution a coastal cell's wind includes some sea, which the method declares.

It is a model, not an observation (the reason step 04 does not use MERRA-2 for precipitation). For dust
and wind there is no observed global product without gaps over ice, so the trade-off goes the other way.
"""

import re
import sys
import time
from pathlib import Path

# Steps run as `python pipeline/NN_step.py`; put the repo root on the path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import xarray as xr  # noqa: E402

from pipeline.common import (  # noqa: E402
    GRID_PATH,
    INTERIM,
    RAW,
    ROOT,
    MissingInputError,
    atomic_write_parquet,
    bbox_mask,
    bbox_note,
    column_stats,
    file_size_mb,
    is_up_to_date,
    last_run_partial,
    load_grid,
    make_parser,
    raster_to_cells,
    require_inputs,
    run,
    setup_logging,
    step_entry,
    validate_output,
    write_step_manifest,
)
from tai.constants import DATA_YEAR  # noqa: E402

STEP = "04_dust_wind"
RAW_DIR = RAW / STEP
OUTPUT = INTERIM / "dust_wind.parquet"
COLUMNS = ["dust_aod", "wind_ms"]

# column -> (subfolder, collection in the file name, MERRA-2 variable, manifest entry)
PRODUCTS = {
    "dust_aod": ("m2tmnxaer", "tavgM_2d_aer_Nx", "DUEXTTAU", {
        "name": f"MERRA-2, monthly dust optical depth, {DATA_YEAR}",
        "product": "M2TMNXAER v5.12.4 (DUEXTTAU)",
        "portal": "NASA Earthdata (GES DISC)",
        "url": "https://doi.org/10.5067/FH9A0MLJPC7N",
    }),
    "wind_ms": ("m2tmnxflx", "tavgM_2d_flx_Nx", "SPEED", {
        "name": f"MERRA-2, monthly surface wind speed, {DATA_YEAR}",
        "product": "M2TMNXFLX v5.12.4 (SPEED)",
        "portal": "NASA Earthdata (GES DISC)",
        "url": "https://doi.org/10.5067/0JRLVL8YV2Y4",
    }),
}


def find_months(column: str, year: int = DATA_YEAR, root: Path = RAW_DIR) -> list[Path]:
    """The 12 monthly files of one product, January first. Missing months: MissingInputError naming them."""
    folder, collection, _, _ = PRODUCTS[column]
    pattern = re.compile(rf"MERRA2_\d+\.{collection}\.{year}(\d\d)\.nc4$")
    found = {int(m.group(1)): p for p in (root / folder).glob("*.nc4") if (m := pattern.search(p.name))}
    missing = [m for m in range(1, 13) if m not in found]
    if missing:
        raise MissingInputError(
            f"missing months of {collection} {year} in {root / folder}: {missing}. "
            "Download them with: make data-dust-wind"
        )
    return [found[m] for m in range(1, 13)]


def annual_mean(paths: list[Path], variable: str) -> xr.DataArray:
    """Mean of the monthly fields of `variable` (lat x lon); a point missing in a month is skipped."""
    total = count = None
    for p in paths:
        with xr.open_dataset(p) as ds:
            field = ds[variable].squeeze("time", drop=True).astype("float64").load()
        ok = np.isfinite(field)
        total = field.where(ok, 0.0) if total is None else total + field.where(ok, 0.0)
        count = ok.astype(int) if count is None else count + ok.astype(int)
    return (total / count.where(count > 0)).rename(variable)


def dust_wind_cells(months: dict[str, list[Path]], grid: pd.DataFrame) -> pd.DataFrame:
    """dust_aod and wind_ms for every grid cell, in grid order."""
    out = pd.DataFrame({"cell_id": grid["cell_id"].to_numpy(dtype="int32")})
    for column, paths in months.items():
        field = annual_mean(paths, PRODUCTS[column][2])
        out[column] = raster_to_cells(field, grid, min_valid_frac=0.0).to_numpy(dtype="float32")
    return out


def main() -> None:
    args = make_parser(STEP, __doc__.splitlines()[0]).parse_args()
    log = setup_logging(STEP)
    started = time.monotonic()

    months = {c: find_months(c) for c in COLUMNS}
    files = [p for ps in months.values() for p in ps]
    require_inputs([GRID_PATH])
    code = [Path(__file__), ROOT / "pipeline" / "common.py", ROOT / "tai" / "constants.py"]
    if (
        not args.force
        and not args.bbox
        and is_up_to_date([OUTPUT], [*files, GRID_PATH, *code])
        and not last_run_partial(STEP)
    ):
        log.info("up to date")
        return

    grid = load_grid()
    inside = bbox_mask(grid["lat"], grid["lon"], args.bbox).to_numpy()
    log.info("%d MERRA-2 files of %d; %d cells", len(files), DATA_YEAR, int(inside.sum()))
    cells = dust_wind_cells(months, grid.loc[inside].reset_index(drop=True))
    if args.bbox:
        cells = grid[["cell_id"]].merge(cells, on="cell_id", how="left").astype(
            {"cell_id": "int32", "dust_aod": "float32", "wind_ms": "float32"}
        )

    nulls = {c: int(cells[c].isna().sum()) for c in COLUMNS}
    notes = [f"cells without data: dust_aod {nulls['dust_aod']}, wind_ms {nulls['wind_ms']}"]
    if args.bbox:
        notes.append(bbox_note(args.bbox))
        log.warning("--bbox: %d cells computed, the rest stay null", int(inside.sum()))

    validate_output(cells, grid_ids=grid["cell_id"])
    atomic_write_parquet(cells, OUTPUT)
    stats = column_stats(cells, COLUMNS)
    write_step_manifest(
        step_entry(
            STEP,
            started,
            inputs=[
                {**PRODUCTS[c][3], "files": len(months[c]),
                 "size_mb": round(sum(file_size_mb(p) for p in months[c]), 1),
                 "license_note": "NASA open data"}
                for c in COLUMNS
            ],
            outputs=[(OUTPUT, len(cells))],
            columns=stats,
            notes=notes,
        )
    )
    for col in COLUMNS:
        st = stats[col]
        log.info("%s: %d with data, %d null, min %s, max %s", col, st["non_null"], st["null"], st["min"], st["max"])
    log.info("wrote %s (%d cells)", OUTPUT.name, len(cells))


if __name__ == "__main__":
    run(main)
