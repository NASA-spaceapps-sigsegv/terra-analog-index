"""Step 01: global 1-degree land grid and 0.05-degree land mask (design 2.1, RF-01).

Reads:  data/raw/01_grid/ne_50m_land.{shp,geojson,gpkg,zip}
        data/raw/01_grid/ne_50m_admin_0_countries.{shp,geojson,gpkg,zip}
Writes: data/processed/grid.parquet, data/interim/land_mask.nc
"""

import sys
from pathlib import Path

# Steps run as `python pipeline/NN_step.py`; put the repo root on the path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
import xarray as xr  # noqa: E402

from pipeline.common import (  # noqa: E402
    GRID_PATH,
    LAND_MASK_PATH,
    RAW,
    MissingInputError,
    make_parser,
    run,
    setup_logging,
)

STEP = "01_grid"
RAW_DIR = RAW / STEP
LAND_BASENAME = "ne_50m_land"
COUNTRIES_BASENAME = "ne_50m_admin_0_countries"
VECTOR_SUFFIXES = (".shp", ".geojson", ".gpkg", ".zip")
MASK_RES_DEG = 0.05
OUTPUTS = [GRID_PATH, LAND_MASK_PATH]


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


def main() -> None:
    args = make_parser(STEP, __doc__.splitlines()[0]).parse_args()
    log = setup_logging(STEP)
    log.info("args: force=%s bbox=%s", args.force, args.bbox)
    raise NotImplementedError("TAI-11: build the grid and land mask")


if __name__ == "__main__":
    run(main)
