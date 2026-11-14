"""Step 01: global 1-degree land grid and 0.05-degree land mask (design 2.1, RF-01).

Reads:  data/raw/01_grid/ne_50m_land.{shp,geojson,gpkg,zip}
        data/raw/01_grid/ne_50m_admin_0_countries.{shp,geojson,gpkg,zip}
Writes: data/processed/grid.parquet, data/interim/land_mask.nc
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
    LAND_MASK_PATH,
    RAW,
    ROOT,
    MissingInputError,
    atomic_write_netcdf,
    atomic_write_parquet,
    bbox_mask,
    bbox_note,
    column_stats,
    file_size_mb,
    is_up_to_date,
    last_run_partial,
    make_parser,
    raster_to_cells,
    run,
    setup_logging,
    step_entry,
    validate_output,
    write_step_manifest,
)
from tai import geo  # noqa: E402
from tai.constants import GRID_RES_DEG, LAND_FRAC_MIN, N_CELLS_GLOBAL  # noqa: E402

STEP = "01_grid"
RAW_DIR = RAW / STEP
LAND_BASENAME = "ne_50m_land"
COUNTRIES_BASENAME = "ne_50m_admin_0_countries"
VECTOR_SUFFIXES = (".shp", ".geojson", ".gpkg", ".zip")
MASK_RES_DEG = 0.05
COUNTRY_NAME_FIELDS = ("NAME_ES", "NAME")
OUTPUTS = [GRID_PATH, LAND_MASK_PATH]
EXPECTED_CELLS = (15_000, 25_000)  # TAI-11 acceptance range


def find_vector(basename: str, folder: Path = RAW_DIR) -> Path:
    """Return the first existing <basename><suffix> in folder."""
    for suffix in VECTOR_SUFFIXES:
        path = folder / f"{basename}{suffix}"
        if path.exists():
            return path
    raise MissingInputError(
        f"missing {folder / basename}.{{{','.join(s[1:] for s in VECTOR_SUFFIXES)}}} "
        "(see data/raw/README.md)"
    )


def read_vector(path: Path):
    """Read a vector file into a GeoDataFrame in WGS84 lat/lon."""
    import geopandas as gpd

    source = f"zip://{path}" if path.suffix == ".zip" else path
    gdf = gpd.read_file(source)
    if gdf.crs is not None and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)
    return gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty]


def raster_coords(res: float = MASK_RES_DEG) -> tuple[np.ndarray, np.ndarray]:
    """Pixel-center latitudes (north to south) and longitudes (west to east)."""
    n_lat = int(round(180 / res))
    n_lon = int(round(360 / res))
    lat = 90.0 - res * (np.arange(n_lat) + 0.5)
    lon = -180.0 + res * (np.arange(n_lon) + 0.5)
    return lat, lon


def rasterize_values(shapes, res: float = MASK_RES_DEG, dtype="uint8") -> np.ndarray:
    """Burn (geometry, value) pairs onto the global lat/lon raster.

    A pixel takes a value when its center falls inside the geometry; later
    shapes win where geometries overlap. Unburned pixels are 0.
    """
    from rasterio.features import rasterize
    from rasterio.transform import from_origin

    lat, lon = raster_coords(res)
    shapes = list(shapes)
    out_shape = (lat.size, lon.size)
    if not shapes:
        return np.zeros(out_shape, dtype=dtype)
    return rasterize(
        shapes,
        out_shape=out_shape,
        transform=from_origin(-180.0, 90.0, res, res),
        fill=0,
        dtype=dtype,
        all_touched=False,
    )


def rasterize_land(land_gdf, res: float = MASK_RES_DEG) -> xr.DataArray:
    """0/1 land mask on a global grid of `res` degrees (design 2.1)."""
    lat, lon = raster_coords(res)
    values = rasterize_values(((geom, 1) for geom in land_gdf.geometry), res)
    return xr.DataArray(
        values,
        coords={"lat": lat, "lon": lon},
        dims=("lat", "lon"),
        name="land",
        attrs={
            "long_name": "land mask (1 = land)",
            "source": "Natural Earth 1:50m land polygons",
            "res_deg": res,
        },
    )


def land_fraction(mask: xr.DataArray) -> pd.Series:
    """Fraction of land pixels in each of the 64,800 one-degree cells."""
    all_cells = pd.DataFrame({"cell_id": np.arange(N_CELLS_GLOBAL, dtype="int32")})
    frac = raster_to_cells(mask.astype("float32"), all_cells, min_valid_frac=0.0)
    return frac.fillna(0.0).rename("land_frac")


def build_grid(land_frac: pd.Series, min_frac: float = LAND_FRAC_MIN) -> pd.DataFrame:
    """Cells with land_frac >= min_frac, with indices, center and area (contracts 3.1).

    `country` is added later by assign_country; here it is all null.
    """
    kept = land_frac[land_frac >= min_frac].sort_index()
    ids = kept.index.to_numpy(dtype="int32")
    lat_idx, lon_idx = geo.split_cell_id(ids)
    lat, lon = geo.cell_center(ids)
    return pd.DataFrame(
        {
            "cell_id": ids,
            "lat_idx": np.asarray(lat_idx, dtype="int16"),
            "lon_idx": np.asarray(lon_idx, dtype="int16"),
            "lat": np.asarray(lat, dtype="float32"),
            "lon": np.asarray(lon, dtype="float32"),
            "area_km2": np.asarray(geo.cell_area_km2(lat_idx), dtype="float32"),
            "land_frac": kept.to_numpy(dtype="float32"),
            "country": pd.array([None] * len(ids), dtype="string"),
        }
    )


def country_names(countries_gdf) -> pd.Series:
    """Spanish name of each country (NAME_ES), falling back to NAME."""
    names = pd.Series([None] * len(countries_gdf), index=countries_gdf.index, dtype="object")
    for field in COUNTRY_NAME_FIELDS:
        if field in countries_gdf.columns:
            col = countries_gdf[field].astype("string").str.strip().replace("", pd.NA)
            names = names.where(names.notna(), col)
    return names.astype("string")


def pixel_cell_ids(res: float = MASK_RES_DEG) -> np.ndarray:
    """cell_id of every pixel of the global raster (by pixel center)."""
    lat, lon = raster_coords(res)
    lat_idx, lon_idx = geo.lat_lon_idx(lat, lon)
    return lat_idx.astype(np.int64)[:, None] * 360 + lon_idx.astype(np.int64)[None, :]


def majority_by_cell(values: np.ndarray, cells, res: float = MASK_RES_DEG) -> pd.Series:
    """Most frequent non-zero value per cell, among the requested cells.

    Ties go to the smallest value so the result is deterministic. Cells with
    no non-zero pixel are absent from the result.
    """
    cells = np.asarray(cells, dtype=np.int64)
    if cells.size == 0:
        return pd.Series(dtype="int64")
    cell = pixel_cell_ids(res)
    sel = (values > 0) & np.isin(cell, cells)
    if not sel.any():
        return pd.Series(dtype="int64")
    k = int(values.max()) + 1
    keys, counts = np.unique(cell[sel] * k + values[sel].astype(np.int64), return_counts=True)
    cell_of, value_of = np.divmod(keys, k)
    order = np.lexsort((value_of, -counts, cell_of))  # by cell, most pixels, smallest value
    first = np.unique(cell_of[order], return_index=True)[1]
    pick = order[first]
    return pd.Series(value_of[pick], index=pd.Index(cell_of[pick], name="cell_id"))


def assign_country(grid: pd.DataFrame, countries_gdf, res: float = MASK_RES_DEG):
    """Fill grid.country (design 2.1: country of the cell center).

    1. The country whose polygon contains the cell center.
    2. If the center is in the sea or a gap, the country with most land
       pixels inside the cell (coastal and island cells).
    3. Otherwise null (e.g. land with no country polygon).

    Returns (grid, counts) where counts has keys center, majority, none.
    """
    import geopandas as gpd

    countries = countries_gdf.reset_index(drop=True)
    names = country_names(countries)

    points = gpd.GeoDataFrame(
        {"cell_id": grid["cell_id"].to_numpy()},
        geometry=gpd.points_from_xy(grid["lon"], grid["lat"]),
        crs="EPSG:4326",
    )
    joined = gpd.sjoin(
        points, countries[["geometry"]].set_crs("EPSG:4326", allow_override=True),
        how="left", predicate="within",
    )
    joined = joined.sort_values(["cell_id", "index_right"]).drop_duplicates("cell_id")
    by_center = joined.set_index("cell_id")["index_right"]

    missing = by_center.index[by_center.isna()]
    ids = rasterize_values(((g, i + 1) for i, g in enumerate(countries.geometry)), res, "int32")
    by_majority = majority_by_cell(ids, missing, res) - 1

    country_idx = by_center.copy()
    country_idx.loc[by_majority.index] = by_majority
    idx = country_idx.reindex(grid["cell_id"]).to_numpy()
    name_values = names.to_numpy(dtype=object)
    country = [name_values[int(i)] if pd.notna(i) else None for i in idx]

    out = grid.copy()
    out["country"] = pd.array(country, dtype="string")
    counts = {
        "center": int(by_center.notna().sum()),
        "majority": int(len(by_majority)),
        "none": int(out["country"].isna().sum()),
    }
    return out, counts


def _input_entry(name: str, product: str, url: str, path: Path) -> dict:
    return {
        "name": name,
        "product": product,
        "portal": "Natural Earth",
        "url": url,
        "files": 1,
        "size_mb": file_size_mb(path),
        "license_note": "Dominio público",
    }


def main() -> None:
    args = make_parser(STEP, __doc__.splitlines()[0]).parse_args()
    log = setup_logging(STEP)
    started = time.monotonic()

    land_path = find_vector(LAND_BASENAME)
    countries_path = find_vector(COUNTRIES_BASENAME)
    code = [Path(__file__), ROOT / "pipeline" / "common.py", ROOT / "tai" / "geo.py", ROOT / "tai" / "constants.py"]
    if (
        not args.force
        and not args.bbox
        and is_up_to_date(OUTPUTS, [land_path, countries_path, *code])
        and not last_run_partial(STEP)
    ):
        log.info("al día")
        return

    log.info("reading %s", land_path.name)
    mask = rasterize_land(read_vector(land_path))
    log.info("land mask %s at %s deg: %d land pixels", mask.shape, MASK_RES_DEG, int(mask.sum()))

    grid = build_grid(land_fraction(mask))
    log.info("grid: %d cells with land_frac >= %s", len(grid), LAND_FRAC_MIN)

    log.info("reading %s", countries_path.name)
    grid, counts = assign_country(grid, read_vector(countries_path))
    log.info("country by center %d, by majority %d, none %d", counts["center"], counts["majority"], counts["none"])

    notes = [
        f"{len(grid)} celdas con land_frac >= {LAND_FRAC_MIN}",
        f"país por el centro: {counts['center']}; por mayoría de píxeles: {counts['majority']}; "
        f"sin país: {counts['none']}",
    ]
    if args.bbox:
        grid = grid[bbox_mask(grid["lat"], grid["lon"], args.bbox).to_numpy()].reset_index(drop=True)
        notes.append(bbox_note(args.bbox))
        log.warning("--bbox: keeping only %d cells; rerun without --bbox for the real grid", len(grid))
    elif not EXPECTED_CELLS[0] <= len(grid) <= EXPECTED_CELLS[1]:
        log.warning("cell count %d outside the expected %s", len(grid), EXPECTED_CELLS)

    validate_output(grid, schema="grid")

    atomic_write_netcdf(mask, LAND_MASK_PATH, encoding={"land": {"zlib": True, "complevel": 4}})
    atomic_write_parquet(grid, GRID_PATH)
    write_step_manifest(
        step_entry(
            STEP,
            started,
            inputs=[
                _input_entry(
                    "Natural Earth, tierra 1:50m",
                    LAND_BASENAME,
                    "https://www.naturalearthdata.com/downloads/50m-physical-vectors/",
                    land_path,
                ),
                _input_entry(
                    "Natural Earth, países 1:50m",
                    COUNTRIES_BASENAME,
                    "https://www.naturalearthdata.com/downloads/50m-cultural-vectors/",
                    countries_path,
                ),
            ],
            outputs=[(GRID_PATH, len(grid)), (LAND_MASK_PATH, int(mask.size))],
            columns=column_stats(grid, ["lat", "lon", "area_km2", "land_frac", "country"]),
            notes=notes,
        ),
        grid={"res_deg": GRID_RES_DEG, "n_cells": len(grid), "land_frac_min": LAND_FRAC_MIN},
    )
    log.info("wrote %s (%d cells) and %s", GRID_PATH.name, len(grid), LAND_MASK_PATH.name)


if __name__ == "__main__":
    run(main)
