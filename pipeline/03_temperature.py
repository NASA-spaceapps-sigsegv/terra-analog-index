"""Step 03: coldest-month night temperature and day-night range per cell (design 4.1, RF-03).

Reads:  data/raw/03_temperature/MOD11C3.A<YYYY><DOY>.061.*.hdf  (12 months of DATA_YEAR)
        data/processed/grid.parquet, data/interim/land_mask.nc  (step 01)
Writes: data/interim/temperature.parquet  (cell_id, tmin_c, trange_c)

For each month, the day and night land surface temperature layers are
converted to Celsius and averaged over the land pixels of each cell
(raster_to_cells, null below MIN_VALID_FRAC). Then, per cell:

  tmin_c   = lowest of the monthly night means (months without data skipped)
  trange_c = mean of (day - night) over the months with both values,
             clipped at 0: on the ice sheets the annual range can come out
             slightly negative (within MODIS error), meaning "no measurable
             diurnal range". The clipped count goes to the manifest.

Months without observations (polar night for the day pass) are skipped,
never filled.
"""

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
    LAND_MASK_PATH,
    RAW,
    ROOT,
    atomic_write_parquet,
    bbox_mask,
    bbox_note,
    column_stats,
    file_size_mb,
    find_modis_months,
    global_coords,
    is_up_to_date,
    land_mask_da,
    last_run_partial,
    load_grid,
    make_parser,
    modis_month,
    raster_to_cells,
    read_hdf4_layer,
    require_inputs,
    run,
    setup_logging,
    step_entry,
    validate_output,
    write_step_manifest,
)
from tai.constants import DATA_YEAR, MIN_VALID_FRAC  # noqa: E402

STEP = "03_temperature"
RAW_DIR = RAW / STEP
OUTPUT = INTERIM / "temperature.parquet"
PRODUCT = "MOD11C3"
DAY_LAYER, NIGHT_LAYER = "LST_Day_CMG", "LST_Night_CMG"
LST_SCALE = 0.02  # K per count (MOD11C3 user guide; also the file's scale_factor)
KELVIN = 273.15
CMG_RES = 0.05
COLUMNS = ["tmin_c", "trange_c"]


# --- Inputs ------------------------------------------------------------------


def find_months(folder: Path = RAW_DIR, year: int = DATA_YEAR) -> list[Path]:
    """The 12 monthly MOD11C3 files of `year`, January first."""
    return find_modis_months(folder, PRODUCT, year)


def lst_celsius(values: np.ndarray) -> np.ndarray:
    """MOD11C3 LST counts (NaN already masked) to degrees Celsius."""
    return values * LST_SCALE - KELVIN


def as_cmg(values: np.ndarray, name: str) -> xr.DataArray:
    """Wrap a north-up global array (any resolution) with lat/lon coordinates."""
    res = 180.0 / values.shape[0]
    lat, lon = global_coords(res)
    return xr.DataArray(values, coords={"lat": lat, "lon": lon}, dims=("lat", "lon"), name=name)


# --- Per month and per year --------------------------------------------------


def month_cells(day: np.ndarray, night: np.ndarray, grid: pd.DataFrame, land) -> tuple[np.ndarray, np.ndarray]:
    """Cell means of one month's day and night temperature (°C), in grid order."""
    d = raster_to_cells(as_cmg(day, "day"), grid, MIN_VALID_FRAC, mask=land)
    n = raster_to_cells(as_cmg(night, "night"), grid, MIN_VALID_FRAC, mask=land)
    return d.to_numpy(dtype=np.float64), n.to_numpy(dtype=np.float64)


def summarize(day: np.ndarray, night: np.ndarray) -> dict:
    """Reduce (months x cells) day and night means to tmin_c and trange_c.

    Returns arrays tmin_c, trange_c (NaN where no month qualifies), the
    number of months used per cell for each, and how many cells had their
    negative annual range clipped to 0.
    """
    night_ok = np.isfinite(night)
    both = night_ok & np.isfinite(day)
    n_night = night_ok.sum(axis=0)
    n_both = both.sum(axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        tmin = np.where(n_night > 0, np.min(np.where(night_ok, night, np.inf), axis=0), np.nan)
        diff = np.where(both, day - night, 0.0).sum(axis=0)
        trange = np.where(n_both > 0, diff / n_both, np.nan)
    negative = np.isfinite(trange) & (trange < 0)
    trange[negative] = 0.0
    return {
        "tmin_c": tmin,
        "trange_c": trange,
        "n_night": n_night,
        "n_both": n_both,
        "clipped": int(negative.sum()),
    }


def temperature_cells(months, grid: pd.DataFrame, land, read=read_hdf4_layer, log=None) -> tuple[pd.DataFrame, dict]:
    """tmin_c and trange_c for every grid cell, plus the summary of `summarize`.

    months: the 12 files (any order); read(path, layer) returns the masked
    raw layer. One layer is held in memory at a time.
    """
    day = np.full((len(months), len(grid)), np.nan)
    night = np.full_like(day, np.nan)
    for i, path in enumerate(months):
        d = lst_celsius(read(path, DAY_LAYER))
        n = lst_celsius(read(path, NIGHT_LAYER))
        day[i], night[i] = month_cells(d, n, grid, land)
        if log is not None:
            log.info("%s: day %d cells, night %d cells", Path(path).name[:16], np.isfinite(day[i]).sum(), np.isfinite(night[i]).sum())
    s = summarize(day, night)
    out = pd.DataFrame(
        {
            "cell_id": grid["cell_id"].to_numpy(dtype="int32"),
            "tmin_c": s["tmin_c"].astype("float32"),
            "trange_c": s["trange_c"].astype("float32"),
        }
    )
    return out, s


# --- Main --------------------------------------------------------------------


def _months_note(counts: np.ndarray, what: str) -> str:
    hist = pd.Series(counts).value_counts().sort_index(ascending=False)
    parts = ", ".join(f"{int(k)}: {int(v)}" for k, v in hist.items())
    return f"meses con dato {what} (meses: celdas): {parts}"


def main() -> None:
    args = make_parser(STEP, __doc__.splitlines()[0]).parse_args()
    log = setup_logging(STEP)
    started = time.monotonic()

    months = find_months()
    require_inputs([GRID_PATH, LAND_MASK_PATH])
    code = [Path(__file__), ROOT / "pipeline" / "common.py", ROOT / "tai" / "constants.py"]
    if (
        not args.force
        and not args.bbox
        and is_up_to_date([OUTPUT], [*months, GRID_PATH, LAND_MASK_PATH, *code])
        and not last_run_partial(STEP)
    ):
        log.info("al día")
        return

    grid = load_grid()
    land = land_mask_da()
    inside = bbox_mask(grid["lat"], grid["lon"], args.bbox).to_numpy()
    log.info("%d monthly files of %d; %d cells", len(months), DATA_YEAR, int(inside.sum()))

    temps, s = temperature_cells(months, grid.loc[inside].reset_index(drop=True), land, log=log)
    if args.bbox:
        temps = (
            grid[["cell_id"]].merge(temps, on="cell_id", how="left")
            .astype({"cell_id": "int32", "tmin_c": "float32", "trange_c": "float32"})
        )

    nulls = {c: int(temps[c].isna().sum()) for c in COLUMNS}
    notes = [
        f"celdas sin dato: tmin_c {nulls['tmin_c']}, trange_c {nulls['trange_c']}",
        f"{s['clipped']} celdas con rango anual negativo llevado a 0 (meseta de hielo, dentro del error de MODIS)",
        _months_note(s["n_night"], "nocturno"),
        _months_note(s["n_both"], "diurno y nocturno"),
    ]
    if args.bbox:
        notes.append(bbox_note(args.bbox))
        log.warning("--bbox: %d cells computed, the rest stay null", int(inside.sum()))

    validate_output(temps, grid_ids=grid["cell_id"])
    atomic_write_parquet(temps, OUTPUT)
    stats = column_stats(temps, COLUMNS)
    write_step_manifest(
        step_entry(
            STEP,
            started,
            inputs=[
                {
                    "name": f"MODIS, temperatura superficial mensual, {DATA_YEAR}",
                    "product": f"{PRODUCT} v061",
                    "portal": "NASA Earthdata (LP DAAC)",
                    "url": "https://doi.org/10.5067/MODIS/MOD11C3.061",
                    "files": len(months),
                    "size_mb": round(sum(file_size_mb(p) for p in months), 1),
                    "license_note": "Datos abiertos de NASA",
                }
            ],
            outputs=[(OUTPUT, len(temps))],
            columns=stats,
            notes=notes,
        )
    )
    for col in COLUMNS:
        st = stats[col]
        log.info("%s: %d with data, %d null, min %s, max %s", col, st["non_null"], st["null"], st["min"], st["max"])
    log.info("%d cells with negative annual range clipped to 0", s["clipped"])
    log.info("wrote %s (%d cells)", OUTPUT.name, len(temps))


if __name__ == "__main__":
    run(main)
