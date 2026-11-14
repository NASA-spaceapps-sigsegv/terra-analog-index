"""Water and ice (TAI-14): step 04 helpers and variables on synthetic data."""

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from pipeline import common
from pipeline.common import MissingInputError
from tai import geo

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("step04", ROOT / "pipeline" / "04_water_ice.py")
step04 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(step04)

NAN = np.nan


# --- Inputs ------------------------------------------------------------------


def _imerg_name(year, month):
    return f"3B-MO.MS.MRG.3IMERG.{year}{month:02d}01-S000000-E235959.{month:02d}.V07B.HDF5"


def test_find_imerg_months(tmp_path):
    for m in range(1, 13):
        (tmp_path / _imerg_name(2024, m)).touch()
    (tmp_path / _imerg_name(2023, 5)).touch()
    files = step04.find_imerg_months(tmp_path, 2024)
    assert [f.name for f in files] == [_imerg_name(2024, m) for m in range(1, 13)]
    (tmp_path / _imerg_name(2024, 4)).unlink()
    with pytest.raises(MissingInputError, match=r"\[4\]"):
        step04.find_imerg_months(tmp_path, 2024)


def test_find_land_cover_falls_back_to_an_earlier_year(tmp_path):
    with pytest.raises(MissingInputError):
        step04.find_land_cover(tmp_path, 2024)
    (tmp_path / "MCD12C1.A2022001.061.x.hdf").touch()
    (tmp_path / "MCD12C1.A2023001.061.x.hdf").touch()
    (tmp_path / "MCD12C1.A2025001.061.x.hdf").touch()  # later than DATA_YEAR: never used
    assert step04.find_land_cover(tmp_path, 2024).name.startswith("MCD12C1.A2023")
    (tmp_path / "MCD12C1.A2024001.061.x.hdf").touch()
    assert step04.find_land_cover(tmp_path, 2024).name.startswith("MCD12C1.A2024")


def test_find_modis_months(tmp_path):
    for m in range(1, 13):
        doy = pd.Timestamp(2024, m, 1).day_of_year
        (tmp_path / f"MOD10CM.A2024{doy:03d}.061.x.hdf").touch()
    assert len(common.find_modis_months(tmp_path, "MOD10CM", 2024)) == 12
    with pytest.raises(MissingInputError, match="MOD11C3"):
        common.find_modis_months(tmp_path, "MOD11C3", 2024)


def test_read_hdf4_layer_band(tmp_path):
    from pyhdf.SD import SD, SDC

    path = tmp_path / "MCD12C1.A2024001.061.test.hdf"
    sd = SD(str(path), SDC.WRITE | SDC.CREATE)
    sds = sd.create("Land_Cover_Type_1_Percent", SDC.UINT8, (2, 2, 3))
    sds.setfillvalue(255)
    sds.valid_range = [0, 100]
    data = np.zeros((2, 2, 3), dtype=np.uint8)
    data[:, :, 2] = [[100, 40], [255, 0]]
    sds[:] = data
    sds.endaccess()
    sd.end()
    np.testing.assert_array_equal(
        common.read_hdf4_layer(path, "Land_Cover_Type_1_Percent", band=2), [[100, 40], [NAN, 0]]
    )


def test_read_imerg_orients_north_up(tmp_path):
    lat = np.array([-45.0, 45.0])  # south to north, as in IMERG
    lon = np.array([-90.0, 0.0, 90.0, 180.0])
    rate = np.array([[[1.0, 2.0], [3.0, -9999.9], [5.0, 6.0], [7.0, 8.0]]], dtype=np.float32)  # (time, lon, lat)
    ds = xr.Dataset({"precipitation": (("time", "lon", "lat"), rate)}, coords={"time": [0], "lon": lon, "lat": lat})
    path = tmp_path / _imerg_name(2024, 1)
    ds.to_netcdf(path, group="Grid")
    out = step04.read_imerg(path)
    np.testing.assert_array_equal(out, [[2, NAN, 6, 8], [1, 3, 5, 7]])  # row 0 is the north


# --- Variables ---------------------------------------------------------------


def test_month_hours():
    assert step04.month_hours(2024, 2) == 29 * 24
    assert step04.month_hours(2023, 2) == 28 * 24
    assert step04.month_hours(2024, 12) == 31 * 24


def test_annual_precip():
    monthly = np.array([[10.0, 1.0, 2.0, NAN], [20.0, 1.0, 3.0, 0.0], [30.0, NAN, 4.0, 0.0]])
    lat = np.array([10.5, 10.5, -70.5, -85.5])
    p = step04.annual_precip(monthly, lat)
    assert p["precip_mm"][0] == 60.0
    assert np.isnan(p["precip_mm"][1])  # a missing month: never a partial sum
    assert np.isnan(p["precip_mm"][2]) and np.isnan(p["precip_mm"][3])  # Antarctica
    assert (p["null_south"], p["null_missing_month"]) == (2, 1)
    assert p["zero"] == 0  # the 0 in cell 3 is south of -60, so it is null, not zero
    assert step04.annual_precip(np.zeros((12, 1)), np.array([74.5]))["zero"] == 1


def test_ice_share():
    ice = np.array([50.0, 50.0, 10.0, NAN, 0.0])
    water = np.array([0.0, 50.0, 100.0, 0.0, 0.0])
    np.testing.assert_allclose(step04.ice_share(ice, water), [0.5, 1.0, NAN, NAN, 0.0])


def test_ice_fraction():
    #               cell: 0     1     2     3     4
    snow = np.array(
        [
            [0.2, NAN, NAN, 0.9, 0.0],
            [0.4, 0.5, NAN, NAN, 0.0],  # NaN = night, cloud...
            [NAN, 0.7, NAN, NAN, 0.0],
        ]
    )
    perm = np.array([0.0, 0.2, 0.9, 0.51, NAN])
    out = step04.ice_fraction(snow, perm)
    np.testing.assert_allclose(out["ice_frac"], [0.3, 0.6, 1.0, 1.0, 0.0])
    assert out["n_months"].tolist() == [2, 2, 0, 1, 3]
    assert out["n_perm"] == 2
    assert np.isnan(step04.ice_fraction(np.full((2, 1), NAN), np.array([0.5]))["ice_frac"][0])  # exactly half is not more


# --- Rasters to cells --------------------------------------------------------


def _grid(*points):
    pts = list(points)
    return pd.DataFrame(
        {
            "cell_id": np.array([geo.cell_id_of(*p) for p in pts], dtype="int32"),
            "lat": np.array([p[0] for p in pts], dtype="float32"),
        }
    )


def test_cell_means_on_coarser_rasters():
    lat, lon = common.global_coords(0.5)
    land = xr.DataArray(np.ones((lat.size, lon.size), dtype=bool), coords={"lat": lat, "lon": lon}, dims=("lat", "lon"))
    land[int((90 - 10.5) * 2) - 1, int((20.5 + 180) * 2)] = False  # one ocean pixel in cell (10.5, 20.5)
    grid = _grid((10.5, 20.5), (-30.5, 140.5))

    fine = np.full((360, 720), 2.0)  # same resolution as the mask
    fine[int((90 - 10.5) * 2) - 1, int((20.5 + 180) * 2)] = 1000.0  # on the ocean pixel: ignored
    np.testing.assert_allclose(step04.cell_means(fine, grid, land, "v"), [2.0, 2.0])

    coarse = np.full((180, 360), 5.0)  # 1 degree: twice as coarse as the mask
    np.testing.assert_allclose(step04.cell_means(coarse, grid, land, "v"), [5.0, 5.0])

    with pytest.raises(ValueError):
        step04.mask_for(np.zeros((100, 200)), land)


def test_coarsen_mask_majority():
    land = xr.DataArray(np.array([[1, 1, 0, 0], [1, 0, 0, 0]], dtype=bool), dims=("lat", "lon"))
    assert step04.coarsen_mask(land, 2).tolist() == [[True, False]]
