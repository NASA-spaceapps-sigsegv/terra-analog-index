"""Shared helpers for the pipeline steps (design 6.2 to 6.4).

Every step script follows the same shape:

    args = make_parser("02_terrain", __doc__).parse_args()
    log = setup_logging("02_terrain")
    if not args.force and is_up_to_date(outputs, inputs + [Path(__file__)]):
        log.info("al día"); sys.exit(EXIT_OK)
    ...
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import time
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# --- Paths -------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"
CONTENT = ROOT / "content"
DATA = ROOT / "data"
RAW = DATA / "raw"
INTERIM = DATA / "interim"
PROCESSED = DATA / "processed"

GRID_PATH = PROCESSED / "grid.parquet"
LAND_MASK_PATH = INTERIM / "land_mask.nc"
MANIFEST_PATH = PROCESSED / "manifest.json"

# --- Exit codes (design 6.2) -------------------------------------------------
EXIT_OK = 0  # done, or already up to date
EXIT_INVALID_OUTPUT = 1  # output failed validation; nothing written
EXIT_MISSING_INPUT = 2  # a required input is missing


class MissingInputError(Exception):
    """A required input file does not exist."""


class OutputValidationError(Exception):
    """A step's output broke its contract (ranges, keys, schema)."""


# --- CLI ---------------------------------------------------------------------


def make_parser(step: str, description: str | None = None) -> argparse.ArgumentParser:
    """Parser with the arguments every step accepts: --force and --bbox."""
    parser = argparse.ArgumentParser(prog=f"{step}.py", description=description)
    parser.add_argument(
        "--force",
        action="store_true",
        help="run even if the output is newer than every input",
    )
    parser.add_argument(
        "--bbox",
        nargs=4,
        type=float,
        metavar=("LAT_MIN", "LAT_MAX", "LON_MIN", "LON_MAX"),
        help="limit computation to a region for quick tests; cells outside stay null",
    )
    return parser


def bbox_mask(lat: pd.Series, lon: pd.Series, bbox: Iterable[float] | None) -> pd.Series:
    """Boolean mask of points inside bbox (all True when bbox is None)."""
    if bbox is None:
        return pd.Series(True, index=lat.index)
    lat_min, lat_max, lon_min, lon_max = bbox
    if lat_min >= lat_max or lon_min >= lon_max:
        raise ValueError("bbox must satisfy LAT_MIN < LAT_MAX and LON_MIN < LON_MAX")
    return lat.between(lat_min, lat_max) & lon.between(lon_min, lon_max)


def setup_logging(step: str, level: int = logging.INFO) -> logging.Logger:
    """One line per stage, prefixed with time and step name."""
    logging.basicConfig(
        level=level,
        format=f"%(asctime)s {step} %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
        force=True,
    )
    return logging.getLogger(step)


# --- Inputs and freshness ----------------------------------------------------


def require_inputs(paths: Iterable[Path]) -> None:
    """Raise MissingInputError listing every input that does not exist."""
    missing = [str(p) for p in paths if not Path(p).exists()]
    if missing:
        raise MissingInputError("missing inputs: " + ", ".join(missing))


def _mtime(path: Path) -> float:
    path = Path(path)
    if path.is_dir():
        times = [p.stat().st_mtime for p in path.rglob("*") if p.is_file()]
        return max(times, default=path.stat().st_mtime)
    return path.stat().st_mtime


def is_up_to_date(outputs: Iterable[Path], inputs: Iterable[Path]) -> bool:
    """True if every output exists and is newer than every input.

    Pass the step script itself among the inputs so that editing the code
    invalidates the output. Directories count by their newest file.
    """
    outputs = [Path(p) for p in outputs]
    inputs = [Path(p) for p in inputs]
    if not outputs or not all(p.exists() for p in outputs):
        return False
    existing_inputs = [p for p in inputs if p.exists()]
    if not existing_inputs:
        return True
    oldest_output = min(_mtime(p) for p in outputs)
    newest_input = max(_mtime(p) for p in existing_inputs)
    return oldest_output > newest_input


PARTIAL_NOTE_PREFIX = "partial run:"


def bbox_note(bbox: Iterable[float]) -> str:
    """Manifest note that marks an output as computed for a region only."""
    return f"{PARTIAL_NOTE_PREFIX} --bbox {' '.join(f'{v:g}' for v in bbox)}"


def last_run_partial(step: str, path: Path = MANIFEST_PATH) -> bool:
    """True if the manifest says the last run of `step` used --bbox.

    Steps call this next to is_up_to_date so a quick regional run never
    passes for a complete output.
    """
    path = Path(path)
    if not path.exists():
        return False
    manifest = json.loads(path.read_text(encoding="utf-8"))
    for entry in manifest.get("steps", []):
        if entry.get("step") == step:
            return any(n.startswith(PARTIAL_NOTE_PREFIX) for n in entry.get("notes", []))
    return False


def load_grid(path: Path = GRID_PATH) -> pd.DataFrame:
    """Read grid.parquet (output of step 01)."""
    require_inputs([path])
    return pd.read_parquet(path)


# --- Atomic writes (design 6.2) ----------------------------------------------


def _atomic_replace(path: Path, write) -> None:
    """Write via `write(tmp_path)` then rename, so a crash never leaves half a file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        write(tmp)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def atomic_write_parquet(df: pd.DataFrame, path: Path) -> None:
    _atomic_replace(path, lambda tmp: df.to_parquet(tmp, index=False))


def atomic_write_json(obj, path: Path) -> None:
    """Strict JSON: NaN/Infinity raise instead of being written (contracts 1)."""
    text = json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    _atomic_replace(path, lambda tmp: tmp.write_text(text, encoding="utf-8"))


def atomic_write_netcdf(ds, path: Path, **kwargs) -> None:
    """kwargs go to Dataset.to_netcdf (e.g. encoding for compression)."""
    kwargs.setdefault("engine", "netcdf4")
    _atomic_replace(path, lambda tmp: ds.to_netcdf(tmp, **kwargs))


# --- Manifest (design 6.4, contracts 6.2) ------------------------------------


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def file_size_mb(path: Path) -> float:
    path = Path(path)
    if path.is_dir():
        size = sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    else:
        size = path.stat().st_size
    return round(size / 1e6, 1)


def git_commit() -> str | None:
    """Short hash of HEAD, or None outside a git checkout."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def _num(x) -> float | None:
    if x is None or pd.isna(x):
        return None
    return round(float(x), 3)


def column_stats(df: pd.DataFrame, columns: Iterable[str]) -> dict:
    """non_null / null / min / max per column, as in the manifest contract."""
    stats = {}
    for col in columns:
        s = df[col]
        numeric = pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s)
        stats[col] = {
            "non_null": int(s.notna().sum()),
            "null": int(s.isna().sum()),
            "min": _num(s.min()) if numeric else None,
            "max": _num(s.max()) if numeric else None,
        }
    return stats


def step_entry(
    step: str,
    started: float,
    inputs: list[dict],
    outputs: list[tuple[Path, int]],
    columns: dict | None = None,
    notes: list[str] | None = None,
    earth_stats: dict | None = None,
) -> dict:
    """Build one manifest step entry.

    `started` is a time.monotonic() value taken when the step began.
    `inputs` are dicts with name, product, portal, url, files, size_mb, license_note.
    `outputs` are (path, rows) pairs; size is read from disk.
    """
    return {
        "step": step,
        "ran_at": utc_now_iso(),
        "duration_s": round(time.monotonic() - started, 1),
        "git_commit": git_commit(),
        "inputs": inputs,
        "outputs": [
            {
                "path": Path(p).resolve().relative_to(ROOT).as_posix(),
                "rows": int(rows),
                "size_mb": file_size_mb(p),
            }
            for p, rows in outputs
        ],
        "columns": columns or {},
        "earth_stats": earth_stats,
        "notes": notes or [],
    }


def write_step_manifest(entry: dict, grid: dict | None = None, path: Path = MANIFEST_PATH) -> None:
    """Insert or replace this step's entry in manifest.json (one entry per step).

    `grid` ({res_deg, n_cells, land_frac_min}) is set by step 01 only.
    The result is validated against tai.models.Manifest before writing.
    """
    from tai.constants import DATA_YEAR, SCHEMA_VERSION
    from tai.models import Manifest

    path = Path(path)
    if path.exists():
        manifest = json.loads(path.read_text(encoding="utf-8"))
    else:
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "project": "terra-analog-index",
            "data_year": DATA_YEAR,
            "grid": None,
            "steps": [],
        }
    manifest["data_year"] = DATA_YEAR  # follows the constant if it changes after step 01
    if grid is not None:
        manifest["grid"] = grid
    steps = [s for s in manifest["steps"] if s["step"] != entry["step"]]
    steps.append(entry)
    manifest["steps"] = sorted(steps, key=lambda s: s["step"])
    Manifest.model_validate(manifest)
    atomic_write_json(manifest, path)


# --- Output validation (design 6.2) ------------------------------------------


def validate_output(
    df: pd.DataFrame,
    grid_ids: Iterable[int] | None = None,
    schema: str | None = None,
) -> None:
    """Raise OutputValidationError listing every problem found.

    Checks the valid ranges of design 3.3 for any column present, cell_id
    uniqueness (when there is no other key), that every cell_id exists in
    the grid, and optionally the column contract in tai.schemas.
    """
    from tai.constants import VALID_RANGES
    from tai import schemas

    problems: list[str] = []
    for col, (lo, hi) in VALID_RANGES.items():
        if col not in df.columns:
            continue
        s = df[col].dropna()
        if lo is not None and (s < lo).any():
            problems.append(f"{col}: {int((s < lo).sum())} values below {lo} (min {s.min()})")
        if hi is not None and (s > hi).any():
            problems.append(f"{col}: {int((s > hi).sum())} values above {hi} (max {s.max()})")
    if "area_km2" in df.columns and (df["area_km2"] <= 0).any():
        problems.append("area_km2: values must be > 0")
    if "cell_id" in df.columns:
        multi_key = schema is not None and len(schemas.PRIMARY_KEYS[schema]) > 1
        if not multi_key and df["cell_id"].duplicated().any():
            problems.append(f"cell_id: {int(df['cell_id'].duplicated().sum())} duplicates")
        if grid_ids is not None:
            unknown = ~df["cell_id"].isin(pd.Index(grid_ids))
            if unknown.any():
                problems.append(f"cell_id: {int(unknown.sum())} not in the grid")
    if schema is not None:
        problems += schemas.check_schema(df, schema)
    if problems:
        raise OutputValidationError("; ".join(problems))


def run(main) -> None:
    """Call main() and exit with the codes of design 6.2."""
    log = logging.getLogger("pipeline")
    try:
        main()
    except MissingInputError as e:
        log.error(str(e))
        sys.exit(EXIT_MISSING_INPUT)
    except OutputValidationError as e:
        log.error("output failed validation, nothing written: %s", e)
        sys.exit(EXIT_INVALID_OUTPUT)
    sys.exit(EXIT_OK)


# --- Raster to cells (design 6.3) --------------------------------------------

_LAT_NAMES = ("lat", "latitude", "y")
_LON_NAMES = ("lon", "longitude", "x")


def _latlon_dims(data) -> tuple[str, str]:
    lat = next((d for d in _LAT_NAMES if d in data.dims), None)
    lon = next((d for d in _LON_NAMES if d in data.dims), None)
    if lat is None or lon is None or data.ndim != 2:
        raise ValueError(f"expected a 2-D raster with lat/lon dims, got {data.dims}")
    return lat, lon


def raster_to_cells(
    data,
    grid: pd.DataFrame,
    min_valid_frac: float = 0.25,
    mask=None,
) -> pd.Series:
    """Average the valid pixels of `data` inside each 1-degree cell.

    data: 2-D xarray.DataArray on a regular lat/lon grid (degrees). Longitudes
        in 0..360 are converted to -180..180. NaN marks invalid pixels.
    grid: DataFrame with a cell_id column (grid.parquet).
    min_valid_frac: a cell is null when valid pixels / considered pixels is
        below this fraction.
    mask: optional boolean array/DataArray, same shape; pixels where it is
        False (e.g. ocean in the 0.05 deg land mask) are ignored entirely,
        neither valid nor invalid.

    Returns a float32 Series indexed by cell_id, in grid order. Pixels are
    assigned by their center, so the raster may be a latitude band (TAI-12
    processes the planet in bands); cut bands at whole degrees.
    """
    from tai.constants import N_CELLS_GLOBAL, N_LAT, N_LON

    lat_name, lon_name = _latlon_dims(data)
    data = data.transpose(lat_name, lon_name)
    lat = np.asarray(data[lat_name].values, dtype=np.float64)
    lon = np.asarray(data[lon_name].values, dtype=np.float64)
    lon = np.where(lon > 180.0, lon - 360.0, lon)

    lat_idx = np.clip(np.floor(lat + 90.0), 0, N_LAT - 1).astype(np.int64)
    lon_idx = np.clip(np.floor(lon + 180.0), 0, N_LON - 1).astype(np.int64)
    cell = lat_idx[:, None] * N_LON + lon_idx[None, :]

    values = np.asarray(data.values, dtype=np.float64)
    considered = np.ones(values.shape, dtype=bool)
    if mask is not None:
        if hasattr(mask, "dims"):
            mask = mask.transpose(*[d for d in (lat_name, lon_name) if d in mask.dims]).values
        considered = np.asarray(mask, dtype=bool)
        if considered.shape != values.shape:
            raise ValueError(f"mask shape {considered.shape} != data shape {values.shape}")
    valid = considered & np.isfinite(values)

    n_total = np.bincount(cell[considered], minlength=N_CELLS_GLOBAL)
    n_valid = np.bincount(cell[valid], minlength=N_CELLS_GLOBAL)
    sums = np.bincount(cell[valid], weights=values[valid], minlength=N_CELLS_GLOBAL)

    with np.errstate(invalid="ignore", divide="ignore"):
        mean = sums / n_valid
        frac = n_valid / n_total
    ok = (n_valid > 0) & (frac >= min_valid_frac)
    result = np.where(ok, mean, np.nan)

    ids = grid["cell_id"].to_numpy()
    return pd.Series(
        result[ids].astype(np.float32),
        index=pd.Index(ids, name="cell_id"),
        name=data.name,
    )


# --- Terrain (design 4.1, TAI-12; reused by TAI-16 for the Moon and Mars) ----


def slope_from_dem(dem, dx_m, dy_m) -> np.ndarray:
    """Slope in degrees by central finite differences on an elevation grid.

    dem: 2-D elevation in meters, rows along y and columns along x. NaN marks
        missing pixels; a missing neighbor makes the slope missing too.
    dx_m: spacing between columns in meters. A scalar for projected grids
        (Moon and Mars crops at 1 km) or one value per row for lat/lon grids,
        where the east-west step shrinks with cos(latitude).
    dy_m: spacing between rows in meters (scalar).

    Edge pixels use one-sided differences. Same body-agnostic definition on
    the three bodies, so the numbers are comparable.
    """
    z = np.asarray(dem, dtype=np.float64)
    if z.ndim != 2:
        raise ValueError(f"dem must be 2-D, got shape {z.shape}")
    dx = np.asarray(dx_m, dtype=np.float64)
    if dx.ndim == 1:
        if dx.size != z.shape[0]:
            raise ValueError(f"dx_m has {dx.size} values for {z.shape[0]} rows")
        dx = dx[:, None]
    elif dx.ndim != 0:
        raise ValueError("dx_m must be a scalar or one value per row")
    if np.any(dx <= 0) or dy_m <= 0:
        raise ValueError("pixel spacing must be > 0")
    if min(z.shape) < 2:
        return np.full(z.shape, np.nan)
    dz_dy, dz_dx = np.gradient(z)
    grad = np.hypot(dz_dx / dx, dz_dy / float(dy_m))
    grad[~np.isfinite(z)] = np.nan  # central differences skip the pixel itself
    return np.degrees(np.arctan(grad))


def _box_sum(a: np.ndarray, window: int) -> np.ndarray:
    """Sum over a centered window x window box; outside the array counts as 0."""
    h = window // 2
    rows, cols = a.shape
    p = np.pad(a, h)
    by_rows = sum(p[i : i + rows, :] for i in range(window))
    return sum(by_rows[:, j : j + cols] for j in range(window))


def local_roughness(dem, window: int | None = None, min_valid: int | None = None) -> np.ndarray:
    """Standard deviation of elevation in a moving window (design 4.1).

    dem: 2-D elevation in meters at the base resolution (1 km by default),
        NaN for missing pixels.
    window: odd side of the square window in pixels (ROUGHNESS_WINDOW_PX).
    min_valid: valid pixels the window needs; default more than half of it.
        Pixels beyond the array edge count as missing, so callers that need
        continuity (e.g. across the antimeridian) pad the array first.

    Population std (ddof=0). A pixel that is itself missing stays missing.
    """
    from tai.constants import ROUGHNESS_WINDOW_PX

    window = ROUGHNESS_WINDOW_PX if window is None else int(window)
    if window < 3 or window % 2 == 0:
        raise ValueError("window must be an odd integer >= 3")
    if min_valid is None:
        min_valid = window * window // 2 + 1
    z = np.asarray(dem, dtype=np.float64)
    if z.ndim != 2:
        raise ValueError(f"dem must be 2-D, got shape {z.shape}")
    valid = np.isfinite(z)
    # Center on the mean so sum(z^2) - sum(z)^2/n does not lose precision.
    ref = float(z[valid].mean()) if valid.any() else 0.0
    d = np.where(valid, z - ref, 0.0)
    n = _box_sum(valid.astype(np.float64), window)
    s1 = _box_sum(d, window)
    s2 = _box_sum(d * d, window)
    with np.errstate(invalid="ignore", divide="ignore"):
        var = (s2 - s1 * s1 / n) / n
    out = np.sqrt(np.clip(var, 0.0, None))
    out[(n < min_valid) | ~valid] = np.nan
    return out


# --- Global lat/lon rasters and inputs shared by steps 01 to 04 --------------


def global_coords(res: float) -> tuple[np.ndarray, np.ndarray]:
    """Pixel-center latitudes (north to south) and longitudes (west to east)
    of a global raster of `res` degrees with origin (-180, 90), such as the
    land mask and the MODIS 0.05 deg CMG products."""
    n_lat = int(round(180 / res))
    n_lon = int(round(360 / res))
    lat = 90.0 - res * (np.arange(n_lat) + 0.5)
    lon = -180.0 + res * (np.arange(n_lon) + 0.5)
    return lat, lon


def land_mask_da(path: Path = LAND_MASK_PATH):
    """Land mask of step 01 as a north-up boolean DataArray (lat, lon)."""
    import xarray as xr

    require_inputs([path])
    with xr.open_dataset(path) as ds:
        da = ds["land"].load()
    return da.sortby("lat", ascending=False).sortby("lon").astype(bool)


def load_land_mask(path: Path = LAND_MASK_PATH) -> tuple[np.ndarray, float]:
    """Land mask of step 01 as a north-up bool array, with its resolution in degrees."""
    da = land_mask_da(path)
    res = float(abs(da.lat.values[1] - da.lat.values[0]))
    return da.values, res


def read_hdf4_layer(path: Path, layer: str, band: int | None = None) -> np.ndarray:
    """Raw values of one HDF4 (MODIS) layer as float32, NaN where invalid.

    Pixels equal to _FillValue or outside valid_range become NaN. Scale and
    offset are NOT applied: MODIS layers differ in how they use add_offset,
    so each step applies the factor documented for its product.
    band: for 3-D layers (e.g. MCD12C1 Land_Cover_Type_1_Percent, one plane
    per class) read only that plane of the last axis.
    """
    from pyhdf.SD import SD, SDC

    sd = SD(str(path), SDC.READ)
    try:
        sds = sd.select(layer)
        attrs = sds.attributes()
        raw = sds[:] if band is None else sds[:, :, band]
        values = np.asarray(raw).astype(np.float32)
    finally:
        sd.end()
    fill = attrs.get("_FillValue")
    if isinstance(fill, (int, float)):
        values[values == fill] = np.nan
    valid = attrs.get("valid_range")
    if isinstance(valid, (list, tuple)) and len(valid) == 2:
        lo, hi = valid
        values[(values < lo) | (values > hi)] = np.nan
    return values


_MODIS_DATE = re.compile(r"\.A(\d{4})(\d{3})\.")


def modis_month(path: Path) -> tuple[int, int]:
    """(year, month) of a MODIS monthly file from its A<YYYY><DOY> tag."""
    m = _MODIS_DATE.search(Path(path).name)
    if not m:
        raise ValueError(f"no .A<YYYY><DOY>. date in {Path(path).name}")
    year, doy = int(m.group(1)), int(m.group(2))
    date = datetime(year, 1, 1) + timedelta(days=doy - 1)
    return year, date.month


def find_modis_months(folder: Path, product: str, year: int) -> list[Path]:
    """The 12 monthly files of a MODIS product for `year`, January first.

    Raises MissingInputError naming the missing months; with two files for
    the same month (a reprocessed granule) the last name in sort order wins.
    """
    by_month: dict[int, Path] = {}
    for path in sorted(Path(folder).glob(f"{product}.A*.hdf")):
        y, m = modis_month(path)
        if y == year:
            by_month[m] = path
    missing = [m for m in range(1, 13) if m not in by_month]
    if missing:
        raise MissingInputError(
            f"missing {product} months {missing} of {year} in {folder} "
            "(run `make data-earthdata`; see data/raw/README.md)"
        )
    return [by_month[m] for m in range(1, 13)]
