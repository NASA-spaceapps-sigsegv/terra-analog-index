"""Step 02: slope and roughness per cell from a ~1 km elevation model (design 4.1, RF-02).

Reads:  data/raw/02_terrain/<one DEM>.{nc,tif,tiff,vrt}  (lat/lon, e.g. ETOPO 2022 30")
        data/processed/grid.parquet, data/interim/land_mask.nc  (step 01)
Writes: data/interim/terrain.parquet  (cell_id, slope_deg, roughness_m)

The planet is processed in 1-degree latitude bands, each read with a halo of
rows so the moving windows are continuous across bands. Inside a band:

1. Ocean pixels (0.05 deg land mask) are set to missing.
2. The DEM is block-averaged to about TERRAIN_BASE_RES_KM in both directions.
   The east-west block widens with 1/cos(latitude) so a base pixel is ~1 km
   wide at every latitude, as on the Moon and Mars crops.
3. slope_from_dem uses the real spacing in meters for each row;
   local_roughness uses a ROUGHNESS_WINDOW_PX window. Columns wrap around
   the antimeridian.
4. raster_to_cells averages the base pixels that are mostly land.
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
    MissingInputError,
    atomic_write_parquet,
    bbox_mask,
    bbox_note,
    column_stats,
    file_size_mb,
    is_up_to_date,
    last_run_partial,
    load_grid,
    load_land_mask,
    local_roughness,
    make_parser,
    raster_to_cells,
    require_inputs,
    run,
    setup_logging,
    slope_from_dem,
    step_entry,
    validate_output,
    write_step_manifest,
)
from tai.constants import (  # noqa: E402
    EARTH_RADIUS_KM,
    MIN_VALID_FRAC,
    ROUGHNESS_WINDOW_PX,
    TERRAIN_BASE_RES_KM,
)

STEP = "02_terrain"
RAW_DIR = RAW / STEP
OUTPUT = INTERIM / "terrain.parquet"
DEM_SUFFIXES = (".nc", ".tif", ".tiff", ".vrt")
KM_PER_DEG = EARTH_RADIUS_KM * np.pi / 180.0
BASE_LAND_FRAC = 0.5  # a base pixel counts as land when most of it is land
MAX_NULL_FRAC = 0.05  # TAI-12 acceptance: under 5% of cells without data
BLOCK_DEGREES = 12  # rows read at once: ~250 MB for a 30" global DEM
COLUMNS = ["slope_deg", "roughness_m"]

# Manifest metadata by file-name prefix; anything else is reported generically.
KNOWN_DEMS = {
    "ETOPO_2022": {
        "name": "ETOPO 2022, surface elevation, 30 arc-seconds",
        "product": "ETOPO_2022_v1_30s_surface",
        "portal": "NOAA NCEI",
        "url": "https://www.ncei.noaa.gov/products/etopo-global-relief-model",
        "license_note": "Public domain (NOAA)",
    },
    "GMTED2010": {
        "name": "GMTED2010, mean elevation, 30 arc-seconds",
        "product": "GMTED2010 mn30",
        "portal": "USGS EROS",
        "url": "https://www.usgs.gov/coastal-changes-and-impacts/gmted2010",
        "license_note": "Public domain (USGS)",
    },
}


# --- Inputs ------------------------------------------------------------------


def find_dem(folder: Path = RAW_DIR) -> Path:
    """The single DEM file in folder (first by name if there are several)."""
    files = sorted(p for p in Path(folder).glob("*") if p.suffix.lower() in DEM_SUFFIXES)
    if not files:
        raise MissingInputError(
            f"missing elevation model in {folder} ({', '.join(DEM_SUFFIXES)}; see data/raw/README.md)"
        )
    return files[0]


def open_dem(path: Path):
    """Open the DEM with rasterio; for multi-variable netCDF pick the elevation."""
    import rasterio

    src = rasterio.open(path)
    if src.count == 0 and src.subdatasets:
        names = src.subdatasets
        src.close()
        pick = next((s for s in names if s.rsplit(":", 1)[-1] in ("z", "elevation", "Band1")), names[0])
        src = rasterio.open(pick)
    return src


def pixels_per_degree(src) -> int:
    """Native pixels per degree of a lat/lon raster (rounded)."""
    if src.crs is not None and not src.crs.is_geographic:
        raise ValueError(f"DEM must be in geographic lat/lon, got {src.crs}")
    res = abs(src.transform.e)
    if not 0 < res <= 1:
        raise ValueError(f"unexpected DEM pixel size {res} deg")
    return max(1, int(round(1.0 / res)))


def global_view(src, ppd: int):
    """Warp the DEM onto the canonical global grid: north-up, origin (-180, 90).

    Nearest neighbor on an equal-resolution grid, so values are copied, not
    interpolated; areas the file does not cover come back as NaN.
    """
    from affine import Affine
    from rasterio.crs import CRS
    from rasterio.enums import Resampling
    from rasterio.vrt import WarpedVRT

    res = 1.0 / ppd
    return WarpedVRT(
        src,
        src_crs=src.crs or CRS.from_epsg(4326),
        crs=CRS.from_epsg(4326),
        transform=Affine(res, 0.0, -180.0, 0.0, -res, 90.0),
        width=360 * ppd,
        height=180 * ppd,
        resampling=Resampling.nearest,
        nodata=np.nan,
        dtype="float32",
    )


class RowCache:
    """Serve row ranges from large blocks read once.

    Compressed DEMs (e.g. ETOPO netCDF, 1440-row chunks) decompress a whole
    chunk for every read; reading 1-degree bands one by one would decompress
    each chunk about a dozen times. Bands go south to north, so each block
    ends at the requested rows and extends `block_rows` to the north.
    """

    def __init__(self, read, height: int, block_rows: int):
        self.read, self.height, self.block_rows = read, height, block_rows
        self.start = self.stop = 0
        self.rows = None

    def __call__(self, r0: int, r1: int) -> np.ndarray:
        if self.rows is None or r0 < self.start or r1 > self.stop:
            self.stop = min(self.height, r1)
            self.start = max(0, min(r0, self.stop - self.block_rows))
            self.rows = None  # free the old block before reading the next
            self.rows = self.read(self.start, self.stop)
        return self.rows[r0 - self.start : r1 - self.start]


# --- Resampling plan ---------------------------------------------------------


def nearest_divisor(n: int, target: float) -> int:
    """Divisor of n closest to target (ties to the smaller); at least 1."""
    divisors = [d for d in range(1, n + 1) if n % d == 0]
    return min(divisors, key=lambda d: (abs(d - max(target, 1.0)), d))


def block_factors(ppd: int, lat_center: float, base_km: float = TERRAIN_BASE_RES_KM) -> tuple[int, int]:
    """Native pixels per base pixel: (rows f, columns k) for a band at lat_center.

    f divides ppd so bands at whole degrees hold whole base rows; k divides
    the 360 * ppd columns so the base grid wraps cleanly at the antimeridian.
    k is capped at one degree (ppd) so every cell keeps at least one base
    column; only the rows closest to the poles end up finer than base_km.
    """
    px_km = KM_PER_DEG / ppd
    f = nearest_divisor(ppd, base_km / px_km)
    cos = max(np.cos(np.radians(lat_center)), 1e-6)
    k = min(nearest_divisor(360 * ppd, base_km / (px_km * cos)), ppd)
    return f, k


def block_mean(dem: np.ndarray, land: np.ndarray, f: int, k: int):
    """Average land pixels in f x k blocks.

    Returns (elevation, is_land): elevation is NaN where the block is not
    mostly land or has no valid land pixel.
    """
    rows, cols = dem.shape
    shape = (rows // f, f, cols // k, k)
    vals = np.where(land, dem, np.nan).astype(np.float64).reshape(shape)
    ok = np.isfinite(vals)
    n = ok.sum(axis=(1, 3))
    s = np.where(ok, vals, 0.0).sum(axis=(1, 3))
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = s / n
    is_land = land.reshape(shape).mean(axis=(1, 3)) >= BASE_LAND_FRAC
    mean[~is_land] = np.nan
    return mean, is_land


def _land_for(land: np.ndarray, land_res: float, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """Sample the land mask at pixel centers (lat descending, lon ascending)."""
    rows = np.clip(np.floor((90.0 - lat) / land_res).astype(np.int64), 0, land.shape[0] - 1)
    cols = np.clip(np.floor((lon + 180.0) / land_res).astype(np.int64), 0, land.shape[1] - 1)
    return land[np.ix_(rows, cols)]


# --- Band processing ---------------------------------------------------------


def terrain_band(
    read_rows,
    ppd: int,
    lat_idx: int,
    land: np.ndarray,
    land_res: float,
    base_km: float = TERRAIN_BASE_RES_KM,
    window: int = ROUGHNESS_WINDOW_PX,
):
    """Slope and roughness on the base grid for the band [lat_idx - 90, lat_idx - 89).

    read_rows(r0, r1): native DEM rows r0..r1-1 of the canonical global grid
    (row 0 at 90 N), all 360 * ppd columns, NaN for no data.

    Returns (slope, roughness, is_land) as DataArrays on the band's base grid.
    """
    lat_s = lat_idx - 90.0
    f, k = block_factors(ppd, lat_s + 0.5, base_km)
    halo = (window // 2) * f  # native rows; also covers the slope stencil
    height = 180 * ppd
    r0 = int(round((90.0 - (lat_s + 1.0)) * ppd))
    r1 = r0 + ppd
    a, b = max(r0 - halo, 0), min(r1 + halo, height)

    dem = np.asarray(read_rows(a, b), dtype=np.float64)
    native_lat = 90.0 - (np.arange(a, b) + 0.5) / ppd
    native_lon = -180.0 + (np.arange(360 * ppd) + 0.5) / ppd
    z, is_land = block_mean(dem, _land_for(land, land_res, native_lat, native_lon), f, k)

    base_lat = 90.0 - (a + (np.arange(z.shape[0]) + 0.5) * f) / ppd
    base_lon = -180.0 + (np.arange(z.shape[1]) + 0.5) * k / ppd
    dy_m = f / ppd * KM_PER_DEG * 1000.0
    dx_m = k / ppd * KM_PER_DEG * 1000.0 * np.cos(np.radians(base_lat))
    dx_m = np.maximum(dx_m, 1e-3)

    h = window // 2  # wrap columns across the antimeridian
    zp = np.concatenate([z[:, -h:], z, z[:, :h]], axis=1)
    slope = slope_from_dem(zp, dx_m, dy_m)[:, h:-h]
    rough = local_roughness(zp, window)[:, h:-h]

    top, n_core = (r0 - a) // f, ppd // f
    core = slice(top, top + n_core)
    coords = {"lat": base_lat[core], "lon": base_lon}

    def da(values, name):
        return xr.DataArray(values[core], coords=coords, dims=("lat", "lon"), name=name)

    return da(slope, "slope_deg"), da(rough, "roughness_m"), da(is_land, "land")


def terrain_cells(
    read_rows,
    ppd: int,
    grid: pd.DataFrame,
    land: np.ndarray,
    land_res: float,
    base_km: float = TERRAIN_BASE_RES_KM,
    window: int = ROUGHNESS_WINDOW_PX,
    lat_indices=None,
    log=None,
) -> pd.DataFrame:
    """slope_deg and roughness_m for every grid cell (NaN where not computed).

    lat_indices limits the bands processed (default: every band with cells).
    """
    lat_idx_of_cell = grid["cell_id"].to_numpy() // 360
    bands = sorted(set(lat_idx_of_cell.tolist()) if lat_indices is None else set(lat_indices))
    out = pd.DataFrame(
        {
            "cell_id": grid["cell_id"].to_numpy(dtype="int32"),
            "slope_deg": np.full(len(grid), np.nan, dtype="float32"),
            "roughness_m": np.full(len(grid), np.nan, dtype="float32"),
        }
    )
    for i, lat_idx in enumerate(bands):
        rows = lat_idx_of_cell == lat_idx
        if not rows.any():
            continue
        cells = grid.loc[rows, ["cell_id"]]
        slope, rough, is_land = terrain_band(read_rows, ppd, lat_idx, land, land_res, base_km, window)
        out.loc[rows, "slope_deg"] = raster_to_cells(slope, cells, MIN_VALID_FRAC, is_land).to_numpy()
        out.loc[rows, "roughness_m"] = raster_to_cells(rough, cells, MIN_VALID_FRAC, is_land).to_numpy()
        if log is not None and (i + 1) % 20 == 0:
            log.info("band %d/%d (lat %d)", i + 1, len(bands), lat_idx - 90)
    return out


# --- Main --------------------------------------------------------------------


def _input_entry(path: Path) -> dict:
    meta = next((m for prefix, m in KNOWN_DEMS.items() if path.name.startswith(prefix)), None)
    meta = meta or {
        "name": f"Global elevation model ({path.name})",
        "product": path.stem,
        "portal": "unknown",
        "url": "",
        "license_note": "Ver data/raw/README.md",
    }
    return {**meta, "files": 1, "size_mb": file_size_mb(path)}


def main() -> None:
    args = make_parser(STEP, __doc__.splitlines()[0]).parse_args()
    log = setup_logging(STEP)
    started = time.monotonic()

    dem_path = find_dem()
    require_inputs([GRID_PATH, LAND_MASK_PATH])
    code = [Path(__file__), ROOT / "pipeline" / "common.py", ROOT / "tai" / "constants.py"]
    if (
        not args.force
        and not args.bbox
        and is_up_to_date([OUTPUT], [dem_path, GRID_PATH, LAND_MASK_PATH, *code])
        and not last_run_partial(STEP)
    ):
        log.info("up to date")
        return

    grid = load_grid()
    land, land_res = load_land_mask()
    inside = bbox_mask(grid["lat"], grid["lon"], args.bbox).to_numpy()
    lat_indices = sorted(set((grid.loc[inside, "cell_id"].to_numpy() // 360).tolist()))

    with open_dem(dem_path) as src:
        ppd = pixels_per_degree(src)
        f, k = block_factors(ppd, 0.0)
        log.info(
            "%s: %d px/deg; base %s km = %d x %d native px at the equator; %d bands",
            dem_path.name, ppd, TERRAIN_BASE_RES_KM, f, k, len(lat_indices),
        )
        with global_view(src, ppd) as vrt:
            from rasterio.windows import Window

            def read_rows(r0, r1):
                return vrt.read(1, window=Window(0, r0, vrt.width, r1 - r0))

            read_rows = RowCache(read_rows, vrt.height, BLOCK_DEGREES * ppd)
            terrain = terrain_cells(read_rows, ppd, grid, land, land_res, lat_indices=lat_indices, log=log)

    notes = [
        f"base resolution {TERRAIN_BASE_RES_KM} km; roughness window "
        f"{ROUGHNESS_WINDOW_PX} x {ROUGHNESS_WINDOW_PX} pixels; DEM at {ppd} px/degree",
    ]
    if args.bbox:
        terrain.loc[~inside, COLUMNS] = np.nan
        notes.append(bbox_note(args.bbox))
        log.warning("--bbox: %d cells computed, the rest stay null", int(inside.sum()))

    nulls = terrain[COLUMNS].isna().any(axis=1)
    null_frac = float(nulls.mean()) if len(terrain) else 0.0
    notes.append(f"{int(nulls.sum())} cells without terrain data ({100 * null_frac:.1f}%)")
    if not args.bbox and null_frac >= MAX_NULL_FRAC:
        log.warning("%.1f%% of cells without terrain data (target < %d%%)", 100 * null_frac, 100 * MAX_NULL_FRAC)

    validate_output(terrain, grid_ids=grid["cell_id"])
    atomic_write_parquet(terrain, OUTPUT)
    stats = column_stats(terrain, COLUMNS)
    write_step_manifest(
        step_entry(
            STEP,
            started,
            inputs=[_input_entry(dem_path)],
            outputs=[(OUTPUT, len(terrain))],
            columns=stats,
            notes=notes,
        )
    )
    for col in COLUMNS:
        s = stats[col]
        log.info("%s: %d with data, %d null, min %s, max %s", col, s["non_null"], s["null"], s["min"], s["max"])
    log.info("wrote %s (%d cells)", OUTPUT.name, len(terrain))


if __name__ == "__main__":
    run(main)
