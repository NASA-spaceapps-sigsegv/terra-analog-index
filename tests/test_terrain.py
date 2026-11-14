"""Terrain (TAI-12): slope_from_dem, local_roughness and step 02 on synthetic DEMs."""

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from pipeline.common import local_roughness, slope_from_dem
from tai import geo

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("step02", ROOT / "pipeline" / "02_terrain.py")
step02 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(step02)

R_M = step02.KM_PER_DEG * 1000.0 * 180.0 / np.pi  # Earth radius in meters


# --- slope_from_dem ----------------------------------------------------------


def test_slope_flat_is_zero():
    assert np.all(slope_from_dem(np.full((4, 5), 812.0), 1000.0, 1000.0) == 0.0)


@pytest.mark.parametrize("axis", [0, 1])
def test_slope_of_a_plane(axis):
    rows, cols = np.mgrid[0:6, 0:7]
    z = 100.0 * (rows if axis == 0 else cols)  # 100 m per 1 km pixel
    slope = slope_from_dem(z, 1000.0, 1000.0)
    np.testing.assert_allclose(slope, np.degrees(np.arctan(0.1)))


def test_slope_uses_spacing_per_row():
    z = np.tile(100.0 * np.arange(5), (2, 1))  # 100 m per column
    slope = slope_from_dem(z, np.array([1000.0, 500.0]), 1000.0)
    np.testing.assert_allclose(slope[0], np.degrees(np.arctan(0.1)))
    np.testing.assert_allclose(slope[1], np.degrees(np.arctan(0.2)))


def test_slope_missing_neighbors_stay_missing():
    z = np.zeros((5, 5))
    z[2, 2] = np.nan
    slope = slope_from_dem(z, 1000.0, 1000.0)
    assert np.isnan(slope[2, 2]) and np.isnan(slope[1, 2]) and np.isnan(slope[2, 3])
    assert slope[0, 0] == 0.0


def test_slope_in_range_on_a_cliff():
    z = np.zeros((3, 3))
    z[:, 2] = 1e6
    slope = slope_from_dem(z, 1.0, 1.0)
    assert np.all((slope >= 0) & (slope <= 90))


def test_slope_rejects_bad_spacing():
    with pytest.raises(ValueError):
        slope_from_dem(np.zeros((3, 3)), 0.0, 1.0)
    with pytest.raises(ValueError):
        slope_from_dem(np.zeros((3, 3)), np.ones(2), 1.0)


# --- local_roughness ---------------------------------------------------------


def test_roughness_flat_is_zero():
    r = local_roughness(np.full((7, 7), 4500.0))
    assert np.all(r[2:-2, :] == 0.0) and np.all(r[:, 2:-2] == 0.0)
    assert np.isnan(r[0, 0])  # corner window has 9 of 25 pixels


def test_roughness_is_window_std():
    z = 8000.0 + np.arange(25, dtype=float).reshape(5, 5)  # large offset: precision
    r = local_roughness(z, 5)
    assert r[2, 2] == pytest.approx(np.std(np.arange(25)), rel=1e-9)
    assert np.isnan(r[0, 0])  # corner sees 9 of 25 pixels, needs 13


def test_roughness_window_size_and_min_valid():
    z = np.arange(9, dtype=float).reshape(3, 3)
    assert local_roughness(z, 3)[1, 1] == pytest.approx(np.std(np.arange(9)))
    assert local_roughness(z, 3, min_valid=4)[0, 0] == pytest.approx(np.std([0, 1, 3, 4]))
    with pytest.raises(ValueError):
        local_roughness(z, 4)


def test_roughness_ignores_missing_pixels():
    z = np.zeros((5, 5))
    z[0, 0] = np.nan
    z[4, 4] = 10.0
    r = local_roughness(z, 5)
    assert np.isnan(r[0, 0])
    assert r[2, 2] == pytest.approx(np.std([0.0] * 23 + [10.0]))


# --- resampling plan ---------------------------------------------------------


def test_nearest_divisor():
    assert step02.nearest_divisor(120, 1.08) == 1
    assert step02.nearest_divisor(120, 5.4) == 5
    assert step02.nearest_divisor(120, 0.2) == 1
    assert step02.nearest_divisor(43200, 124.0) == 120


def test_block_factors_track_latitude():
    f, k = step02.block_factors(120, 0.5, base_km=1.0)  # 30" pixels, ~0.93 km
    assert (f, k) == (1, 1)
    f, k = step02.block_factors(120, 60.5, base_km=1.0)
    assert f == 1 and k == 2  # east-west pixels are half as wide at 60 deg
    f, k = step02.block_factors(120, -80.5, base_km=1.0)
    assert k == 6
    f, k = step02.block_factors(120, 0.5, base_km=5.0)  # TAI-12 fallback
    assert (f, k) == (5, 5)
    assert step02.block_factors(120, -89.5, base_km=5.0)[1] == 120  # capped at 1 degree


def test_block_mean_drops_mostly_ocean_blocks():
    dem = np.arange(8, dtype=float).reshape(2, 4)
    land = np.array([[True, True, True, False], [True, True, False, False]])
    mean, is_land = step02.block_mean(dem, land, 2, 2)
    assert is_land.tolist() == [[True, False]]
    assert mean[0, 0] == pytest.approx(np.mean([0, 1, 4, 5]))
    assert np.isnan(mean[0, 1])


# --- terrain_cells on an analytic world --------------------------------------

PPD = 12  # 5' pixels keep the synthetic globe small
BASE_KM = 30.0  # a few native pixels per base pixel, so resampling is exercised


def _reader(fn):
    lon = -180.0 + (np.arange(360 * PPD) + 0.5) / PPD

    def read_rows(r0, r1):
        lat = 90.0 - (np.arange(r0, r1) + 0.5) / PPD
        return fn(lat[:, None], lon[None, :])

    return read_rows


def _grid(*points):
    return pd.DataFrame({"cell_id": np.array([geo.cell_id_of(*p) for p in points], dtype="int32")})


ALL_LAND = (np.ones((180, 360), dtype=bool), 1.0)


def _run(fn, grid, land=ALL_LAND):
    out = step02.terrain_cells(_reader(fn), PPD, grid, *land, base_km=BASE_KM)
    return out.set_index("cell_id")


def test_east_west_plane_has_the_same_slope_at_every_latitude():
    g = 0.05  # 5% grade eastward, in meters on the ground
    plane = lambda lat, lon: g * R_M * np.cos(np.radians(lat)) * np.radians(lon)  # noqa: E731
    points = [(0.5, 0.5), (60.5, 0.5), (-80.5, 0.5)]
    out = _run(plane, _grid(*points))
    expected = np.degrees(np.arctan(g))
    for p in points:
        assert out.loc[geo.cell_id_of(*p), "slope_deg"] == pytest.approx(expected, rel=0.02)


def test_north_south_plane():
    g = 0.02
    plane = lambda lat, lon: g * R_M * np.radians(lat) + 0 * lon  # noqa: E731
    out = _run(plane, _grid((-30.5, 20.5), (45.5, 100.5)))
    np.testing.assert_allclose(out["slope_deg"], np.degrees(np.arctan(g)), rtol=1e-3)
    assert (out["roughness_m"] > 0).all()


def test_flat_world_and_output_shape():
    grid = _grid((0.5, 0.5), (-89.5, 10.5), (10.5, 10.5))
    out = step02.terrain_cells(_reader(lambda lat, lon: 0 * lat + 0 * lon + 300.0), PPD, grid, *ALL_LAND, base_km=BASE_KM)
    assert out.columns.tolist() == ["cell_id", "slope_deg", "roughness_m"]
    assert out["cell_id"].tolist() == grid["cell_id"].tolist()
    assert out["slope_deg"].dtype == np.float32 and out["roughness_m"].dtype == np.float32
    assert (out[["slope_deg", "roughness_m"]] == 0).all().all()  # includes the south pole cell


def test_antimeridian_wraps():
    wave = lambda lat, lon: 2000.0 * np.sin(np.radians(lon) * 40) + 0 * lat  # noqa: E731
    out = _run(wave, _grid((5.5, 179.5), (5.5, -179.5), (5.5, 0.5)))
    east, west, mid = (out.loc[geo.cell_id_of(5.5, x)] for x in (179.5, -179.5, 0.5))
    assert east["roughness_m"] == pytest.approx(west["roughness_m"], rel=1e-6)
    assert east["slope_deg"] == pytest.approx(west["slope_deg"], rel=1e-6)
    assert east["roughness_m"] == pytest.approx(mid["roughness_m"], rel=1e-3)


def test_ocean_is_ignored_and_missing_dem_gives_null():
    land = np.zeros((180, 360), dtype=bool)
    land[89, 0:2] = True  # row 89 is lat 0..1  # cells (0.5, -179.5) and (0.5, -178.5)
    # Ocean holds a huge cliff; DEM has no data east of -179.
    fn = lambda lat, lon: np.where(lon < -179.0, 100.0, np.where(lon < 0, np.nan, 1e5)) + 0 * lat  # noqa: E731
    out = _run(fn, _grid((0.5, -179.5), (0.5, -178.5), (20.5, 20.5)), land=(land, 1.0))
    assert out.loc[geo.cell_id_of(0.5, -179.5), "slope_deg"] < 1.0  # edge of no-data, not the cliff
    assert out.loc[geo.cell_id_of(0.5, -178.5)].isna().all()  # land without DEM
    assert out.loc[geo.cell_id_of(20.5, 20.5)].isna().all()  # in the grid but all ocean


def test_lat_indices_limit_the_bands():
    grid = _grid((0.5, 0.5), (10.5, 10.5))
    out = step02.terrain_cells(
        _reader(lambda lat, lon: 0 * lat + 0 * lon), PPD, grid, *ALL_LAND, base_km=BASE_KM, lat_indices=[90]
    ).set_index("cell_id")
    assert out.loc[geo.cell_id_of(0.5, 0.5), "slope_deg"] == 0
    assert np.isnan(out.loc[geo.cell_id_of(10.5, 10.5), "slope_deg"])


# --- reading real files ------------------------------------------------------


def test_global_view_places_a_partial_geotiff(tmp_path):
    import rasterio
    from affine import Affine
    from rasterio.windows import Window

    res = 1 / 4
    data = np.arange(80 * 80, dtype="float32").reshape(80, 80)  # lat 10..-10, lon -10..10
    data[0, 0] = -32768
    path = tmp_path / "dem.tif"
    with rasterio.open(
        path, "w", driver="GTiff", width=80, height=80, count=1, dtype="float32",
        crs="EPSG:4326", transform=Affine(res, 0, -10, 0, -res, 10), nodata=-32768,
    ) as dst:
        dst.write(data, 1)

    with step02.open_dem(path) as src:
        ppd = step02.pixels_per_degree(src)
        assert ppd == 4
        with step02.global_view(src, ppd) as vrt:
            assert (vrt.width, vrt.height) == (1440, 720)
            r0 = (90 - 10) * ppd
            c0 = (180 - 10) * ppd
            got = vrt.read(1, window=Window(c0 - 1, r0 - 1, 82, 82))
    assert np.isnan(got[0]).all() and np.isnan(got[:, 0]).all()  # outside the file
    assert np.isnan(got[1, 1])  # nodata
    np.testing.assert_array_equal(got[1:-1, 1:-1].ravel()[1:], data.ravel()[1:])


def test_load_land_mask_and_find_dem(tmp_path):
    lat = 90 - 0.5 - np.arange(180)
    lon = -180 + 0.5 + np.arange(360)
    values = np.zeros((180, 360), dtype="uint8")
    values[0, 0] = 1
    xr.DataArray(values, coords={"lat": lat, "lon": lon}, dims=("lat", "lon"), name="land").to_netcdf(
        tmp_path / "mask.nc"
    )
    land, res = step02.load_land_mask(tmp_path / "mask.nc")
    assert res == 1.0 and land.dtype == bool and land[0, 0] and land.sum() == 1

    raw = tmp_path / "raw"
    raw.mkdir()
    with pytest.raises(step02.MissingInputError):
        step02.find_dem(raw)
    (raw / "notes.txt").touch()
    (raw / "b.tif").touch()
    (raw / "a.nc").touch()
    assert step02.find_dem(raw).name == "a.nc"


def test_row_cache_reads_blocks_once():
    calls = []

    def read(r0, r1):
        calls.append((r0, r1))
        return np.arange(r0, r1)[:, None] * np.ones((1, 3))

    cache = step02.RowCache(read, height=100, block_rows=30)
    np.testing.assert_array_equal(cache(80, 90)[:, 0], np.arange(80, 90))
    np.testing.assert_array_equal(cache(70, 85)[:, 0], np.arange(70, 85))  # same block
    np.testing.assert_array_equal(cache(40, 62)[:, 0], np.arange(40, 62))  # new block
    np.testing.assert_array_equal(cache(0, 5)[:, 0], np.arange(0, 5))
    assert calls == [(60, 90), (32, 62), (0, 5)]
