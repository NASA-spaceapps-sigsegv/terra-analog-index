"""Step 04: annual precipitation and snow/ice cover per cell (design 4.1 and 4.3, RF-04).

Reads:  data/raw/04_water_ice/imerg/3B-MO.MS.MRG.3IMERG.<YYYYMMDD>-*.HDF5   (12 months)
        data/raw/04_water_ice/mod10cm/MOD10CM.A<YYYY><DOY>.061.*.hdf    (12 months)
        data/raw/04_water_ice/mcd12c1/MCD12C1.A<YYYY>001.061.*.hdf      (1 year)
        data/processed/grid.parquet, data/interim/land_mask.nc  (step 01)
Writes: data/interim/water_ice.parquet  (cell_id, precip_mm, ice_frac)

precip_mm: each month's IMERG rate (mm/h) times the hours of that month,
    averaged over the land pixels of each cell, summed over the 12 months.
    Null if any month is missing, and null south of PRECIP_MIN_LAT: IMERG
    does not retrieve snowfall over the Antarctic ice sheet (no gauges, most
    pixels exactly 0), so per design 4.3 the dimension uses ice_frac alone
    there. Both counts go to the manifest.
ice_frac: mean of the monthly snow cover fraction (MOD10CM) over the months
    with a valid observation (polar night, cloud and the like are skipped).
    Cells with more than half of their land in permanent snow and ice
    (MCD12C1 IGBP class 15) are set to 1.
"""

import calendar
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
    LAND_MASK_PATH,
    RAW,
    ROOT,
    MissingInputError,
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

STEP = "04_water_ice"
RAW_DIR = RAW / STEP
IMERG_DIR, SNOW_DIR, COVER_DIR = RAW_DIR / "imerg", RAW_DIR / "mod10cm", RAW_DIR / "mcd12c1"
OUTPUT = INTERIM / "water_ice.parquet"
COLUMNS = ["precip_mm", "ice_frac"]

SNOW_LAYER = "Snow_Cover_Monthly_CMG"  # 0-100 %; 211 night, 250 cloud, 254 water... (masked)
COVER_LAYER = "Land_Cover_Type_1_Percent"  # one plane per IGBP class, % of the pixel
WATER_CLASS, ICE_CLASS = 0, 15
PERM_ICE_MIN = 0.5  # design 4.1: "more than half of its land" in permanent ice
PRECIP_MIN_LAT = -60.0  # cells centered south of this get null precip_mm (design 4.3)

_IMERG_DATE = re.compile(r"3IMERG\.(\d{4})(\d{2})01-")


# --- Inputs ------------------------------------------------------------------


def find_imerg_months(folder: Path = IMERG_DIR, year: int = DATA_YEAR) -> list[Path]:
    """The 12 monthly IMERG files of `year`, January first."""
    by_month: dict[int, Path] = {}
    for path in sorted(Path(folder).glob("3B-MO.MS.MRG.3IMERG.*.HDF5")):
        m = _IMERG_DATE.search(path.name)
        if m and int(m.group(1)) == year:
            by_month[int(m.group(2))] = path
    missing = [m for m in range(1, 13) if m not in by_month]
    if missing:
        raise MissingInputError(
            f"missing IMERG months {missing} of {year} in {folder} "
            "(run `make data-water-ice`; see data/raw/README.md)"
        )
    return [by_month[m] for m in range(1, 13)]


def find_land_cover(folder: Path = COVER_DIR, year: int = DATA_YEAR) -> Path:
    """The MCD12C1 file of `year`, or the latest earlier one (it is published late)."""
    files = [(modis_month(p)[0], p) for p in sorted(Path(folder).glob("MCD12C1.A*.hdf"))]
    usable = [(y, p) for y, p in files if y <= year]
    if not usable:
        raise MissingInputError(
            f"missing MCD12C1 for {year} or earlier in {folder} (run `make data-water-ice`)"
        )
    return max(usable)[1]


def read_imerg(path: Path) -> np.ndarray:
    """IMERG monthly precipitation rate (mm/h) as a north-up (lat, lon) array, NaN if missing."""
    with xr.open_dataset(path, group="Grid", decode_times=False) as ds:
        rate = ds["precipitation"].squeeze("time", drop=True).transpose("lat", "lon").load()
    rate = rate.sortby("lat", ascending=False).sortby("lon")
    values = rate.values.astype(np.float32)
    values[values < 0] = np.nan  # -9999.9 if it was not decoded as missing
    return values


def as_global(values: np.ndarray, name: str) -> xr.DataArray:
    """Wrap a north-up global array (any resolution) with lat/lon coordinates."""
    lat, lon = global_coords(180.0 / values.shape[0])
    return xr.DataArray(values, coords={"lat": lat, "lon": lon}, dims=("lat", "lon"), name=name)


def coarsen_mask(land: xr.DataArray, factor: int) -> np.ndarray:
    """Land mask at `factor` times coarser resolution: land where most of the block is."""
    rows, cols = land.shape
    blocks = np.asarray(land.values, dtype=np.float32).reshape(rows // factor, factor, cols // factor, factor)
    return blocks.mean(axis=(1, 3)) >= 0.5


def mask_for(values: np.ndarray, land: xr.DataArray) -> np.ndarray:
    """Land mask matching the shape of `values` (same or coarser than the mask)."""
    if values.shape == land.shape:
        return np.asarray(land.values, dtype=bool)
    factor = land.shape[0] // values.shape[0]
    if factor * values.shape[0] != land.shape[0] or factor * values.shape[1] != land.shape[1]:
        raise ValueError(f"raster {values.shape} is not a coarsening of the land mask {land.shape}")
    return coarsen_mask(land, factor)


def cell_means(values: np.ndarray, grid: pd.DataFrame, land: xr.DataArray, name: str) -> np.ndarray:
    """Mean of `values` over the land pixels of each grid cell (NaN below MIN_VALID_FRAC)."""
    s = raster_to_cells(as_global(values, name), grid, MIN_VALID_FRAC, mask=mask_for(values, land))
    return s.to_numpy(dtype=np.float64)


# --- Variables ---------------------------------------------------------------


def month_hours(year: int, month: int) -> int:
    return 24 * calendar.monthrange(year, month)[1]


def annual_precip(monthly_mm: np.ndarray, lat: np.ndarray, min_lat: float = PRECIP_MIN_LAT) -> dict:
    """Sum (months x cells) of monthly precipitation in mm.

    Null when any month is missing (a partial sum would read as drier than
    it is) and for cells centered south of min_lat. Returns the values and
    the two null counts.
    """
    complete = np.isfinite(monthly_mm).all(axis=0)
    total = np.where(complete, np.nansum(monthly_mm, axis=0), np.nan)
    south = np.asarray(lat) < min_lat
    total[south] = np.nan
    return {
        "precip_mm": total,
        "null_south": int(south.sum()),
        "null_missing_month": int((~complete & ~south).sum()),
        "zero": int((total == 0).sum()),  # IMERG gives exactly 0 on parts of the ice sheets
    }


def ice_share(ice_pct: np.ndarray, water_pct: np.ndarray) -> np.ndarray:
    """Share of each pixel's land in permanent snow and ice, from IGBP class percents."""
    with np.errstate(invalid="ignore", divide="ignore"):
        share = ice_pct / (100.0 - water_pct)
    share[~np.isfinite(share) | (water_pct >= 100)] = np.nan
    return np.clip(share, 0.0, 1.0)


def ice_fraction(monthly_snow: np.ndarray, perm_share: np.ndarray, perm_min: float = PERM_ICE_MIN) -> dict:
    """ice_frac per cell from (months x cells) snow fractions and the permanent-ice share.

    Mean over the months with a value; 1 where more than perm_min of the
    land is permanent ice; null when neither applies.
    """
    valid = np.isfinite(monthly_snow)
    n = valid.sum(axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        snow = np.where(n > 0, np.where(valid, monthly_snow, 0.0).sum(axis=0) / n, np.nan)
    perm = np.nan_to_num(perm_share, nan=0.0) > perm_min
    frac = np.where(perm, 1.0, snow)
    return {"ice_frac": np.clip(frac, 0.0, 1.0), "n_months": n, "n_perm": int(perm.sum())}


# --- Main --------------------------------------------------------------------


def water_ice_cells(imerg, snow_files, cover_file, grid, land, year=DATA_YEAR, log=None):
    """precip_mm and ice_frac for every grid cell, plus the summaries."""
    precip = np.full((len(imerg), len(grid)), np.nan)
    for i, path in enumerate(imerg):
        precip[i] = cell_means(read_imerg(path) * month_hours(year, i + 1), grid, land, "precip")
    p = annual_precip(precip, grid["lat"].to_numpy())
    if log is not None:
        log.info("precipitation: %d months read", len(imerg))

    snow = np.full((len(snow_files), len(grid)), np.nan)
    for i, path in enumerate(snow_files):
        snow[i] = cell_means(read_hdf4_layer(path, SNOW_LAYER) / 100.0, grid, land, "snow")
    if log is not None:
        log.info("snow cover: %d months read", len(snow_files))

    share = ice_share(
        read_hdf4_layer(cover_file, COVER_LAYER, ICE_CLASS),
        read_hdf4_layer(cover_file, COVER_LAYER, WATER_CLASS),
    )
    ice = ice_fraction(snow, cell_means(share, grid, land, "perm_ice"))
    out = pd.DataFrame(
        {
            "cell_id": grid["cell_id"].to_numpy(dtype="int32"),
            "precip_mm": p["precip_mm"].astype("float32"),
            "ice_frac": ice["ice_frac"].astype("float32"),
        }
    )
    return out, p, ice


def _input(name, product, url, files, license_note="Datos abiertos de NASA"):
    return {
        "name": name,
        "product": product,
        "portal": "NASA Earthdata",
        "url": url,
        "files": len(files),
        "size_mb": round(sum(file_size_mb(f) for f in files), 1),
        "license_note": license_note,
    }


def main() -> None:
    args = make_parser(STEP, __doc__.splitlines()[0]).parse_args()
    log = setup_logging(STEP)
    started = time.monotonic()

    imerg = find_imerg_months()
    snow_files = find_modis_months(SNOW_DIR, "MOD10CM", DATA_YEAR)
    cover_file = find_land_cover()
    require_inputs([GRID_PATH, LAND_MASK_PATH])
    raw = [*imerg, *snow_files, cover_file]
    code = [Path(__file__), ROOT / "pipeline" / "common.py", ROOT / "tai" / "constants.py"]
    if (
        not args.force
        and not args.bbox
        and is_up_to_date([OUTPUT], [*raw, GRID_PATH, LAND_MASK_PATH, *code])
        and not last_run_partial(STEP)
    ):
        log.info("al día")
        return

    grid = load_grid()
    land = land_mask_da()
    inside = bbox_mask(grid["lat"], grid["lon"], args.bbox).to_numpy()
    cover_year = modis_month(cover_file)[0]
    log.info("IMERG and MOD10CM %d, MCD12C1 %d; %d cells", DATA_YEAR, cover_year, int(inside.sum()))

    sub = grid.loc[inside].reset_index(drop=True)
    out, p, ice = water_ice_cells(imerg, snow_files, cover_file, sub, land, log=log)
    if args.bbox:
        out = (
            grid[["cell_id"]].merge(out, on="cell_id", how="left")
            .astype({"cell_id": "int32", "precip_mm": "float32", "ice_frac": "float32"})
        )

    months = pd.Series(ice["n_months"]).value_counts().sort_index(ascending=False)
    notes = [
        f"precip_mm nula en {p['null_south']} celdas al sur de {PRECIP_MIN_LAT:g}°: IMERG no mide la nieve "
        "sobre la Antártida; ahí la dimensión agua y hielo usa solo ice_frac (diseño 4.3)",
        f"precip_mm nula en {p['null_missing_month']} celdas más por meses sin dato",
        f"precip_mm = 0 exacto en {p['zero']} celdas (centro del casquete de Groenlandia): IMERG no "
        "estima la nieve sobre el hielo; se conservan como dato, pero no son un mínimo real",
        f"ice_frac = 1 en {ice['n_perm']} celdas con más de la mitad de su tierra en hielo permanente "
        f"(MCD12C1 {cover_year}, clase IGBP 15)",
        f"ice_frac nula en {int(out['ice_frac'].isna().sum())} celdas sin mes válido de nieve ni hielo permanente",
        "meses con dato de nieve (meses: celdas): " + ", ".join(f"{int(k)}: {int(v)}" for k, v in months.items()),
    ]
    if cover_year != DATA_YEAR:
        notes.append(f"MCD12C1 de {cover_year}: el de {DATA_YEAR} no está publicado")
    if args.bbox:
        notes.append(bbox_note(args.bbox))
        log.warning("--bbox: %d cells computed, the rest stay null", int(inside.sum()))

    validate_output(out, grid_ids=grid["cell_id"])
    atomic_write_parquet(out, OUTPUT)
    stats = column_stats(out, COLUMNS)
    write_step_manifest(
        step_entry(
            STEP,
            started,
            inputs=[
                _input(f"GPM IMERG Final, precipitación mensual, {DATA_YEAR}", "GPM_3IMERGM v07",
                       "https://disc.gsfc.nasa.gov/datasets/GPM_3IMERGM_07/summary", imerg),
                _input(f"MODIS, cobertura de nieve mensual, {DATA_YEAR}", "MOD10CM v061",
                       "https://doi.org/10.5067/MODIS/MOD10CM.061", snow_files),
                _input(f"MODIS, cobertura del suelo anual, {cover_year}", "MCD12C1 v061",
                       "https://doi.org/10.5067/MODIS/MCD12C1.061", [cover_file]),
            ],
            outputs=[(OUTPUT, len(out))],
            columns=stats,
            notes=notes,
        )
    )
    for col in COLUMNS:
        st = stats[col]
        log.info("%s: %d with data, %d null, min %s, max %s", col, st["non_null"], st["null"], st["min"], st["max"])
    log.info("wrote %s (%d cells)", OUTPUT.name, len(out))


if __name__ == "__main__":
    run(main)
