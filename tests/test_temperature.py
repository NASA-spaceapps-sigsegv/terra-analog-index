"""Temperature (TAI-13): MODIS helpers and step 03 on synthetic data."""

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pipeline import common
from pipeline.common import MissingInputError
from tai import geo

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("step03", ROOT / "pipeline" / "03_temperature.py")
step03 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(step03)

NAN = np.nan


# --- MODIS helpers in common -------------------------------------------------


def test_modis_month():
    assert common.modis_month(Path("MOD11C3.A2024001.061.2024034041307.hdf")) == (2024, 1)
    assert common.modis_month(Path("MOD11C3.A2024032.061.2024066085830.hdf")) == (2024, 2)
    assert common.modis_month(Path("MOD11C3.A2024336.061.2025003202020.hdf")) == (2024, 12)  # leap year
    assert common.modis_month(Path("MOD11C3.A2023335.061.x.hdf")) == (2023, 12)
    with pytest.raises(ValueError):
        common.modis_month(Path("notes.hdf"))


def test_read_hdf4_layer_masks_fill_and_range(tmp_path):
    from pyhdf.SD import SD, SDC

    path = tmp_path / "MOD11C3.A2024001.061.test.hdf"
    sd = SD(str(path), SDC.WRITE | SDC.CREATE)
    sds = sd.create("LST_Day_CMG", SDC.UINT16, (2, 3))
    sds.setfillvalue(0)
    sds.valid_range = [7500, 65535]
    sds[:] = np.array([[0, 7499, 7500], [15000, 14000, 65535]], dtype=np.uint16)
    sds.endaccess()
    sd.end()

    values = common.read_hdf4_layer(path, "LST_Day_CMG")
    assert values.dtype == np.float32
    np.testing.assert_array_equal(values, [[NAN, NAN, 7500], [15000, 14000, 65535]])


def test_global_coords():
    lat, lon = common.global_coords(0.05)
    assert (lat.size, lon.size) == (3600, 7200)
    assert lat[0] == pytest.approx(89.975) and lat[-1] == pytest.approx(-89.975)
    assert lon[0] == pytest.approx(-179.975)


def test_land_mask_helpers(tmp_path):
    import xarray as xr

    lat = -89.5 + np.arange(180)  # south to north on disk: helpers flip it
    lon = -179.5 + np.arange(360)
    values = np.zeros((180, 360), dtype="uint8")
    values[-1, 0] = 1  # lat 89.5, lon -179.5
    xr.DataArray(values, coords={"lat": lat, "lon": lon}, dims=("lat", "lon"), name="land").to_netcdf(
        tmp_path / "mask.nc"
    )
    da = common.land_mask_da(tmp_path / "mask.nc")
    assert da.dtype == bool and da.lat.values[0] == 89.5 and bool(da.values[0, 0])
    land, res = common.load_land_mask(tmp_path / "mask.nc")
    assert res == 1.0 and land.sum() == 1 and land[0, 0]


# --- Inputs ------------------------------------------------------------------


def _touch_months(folder, months, year=2024):
    folder.mkdir(exist_ok=True)
    for m in months:
        doy = pd.Timestamp(year, m, 1).day_of_year
        (folder / f"MOD11C3.A{year}{doy:03d}.061.2025000000000.hdf").touch()


def test_find_months(tmp_path):
    _touch_months(tmp_path, range(1, 13))
    _touch_months(tmp_path, [1], year=2023)  # other years are ignored
    files = step03.find_months(tmp_path, 2024)
    assert [common.modis_month(p) for p in files] == [(2024, m) for m in range(1, 13)]


def test_find_months_names_the_missing_ones(tmp_path):
    _touch_months(tmp_path, [m for m in range(1, 13) if m not in (3, 7)])
    with pytest.raises(MissingInputError, match=r"\[3, 7\]"):
        step03.find_months(tmp_path, 2024)


def test_lst_celsius():
    counts = np.array([13657.5, NAN])  # 273.15 K
    np.testing.assert_allclose(step03.lst_celsius(counts), [0.0, NAN], atol=1e-9)


# --- Reduction over months ---------------------------------------------------


def test_summarize():
    #               cell: 0     1     2      3     4
    night = np.array(
        [
            [-10.0, -40.0, NAN, 5.0, NAN],
            [-12.0, -45.0, NAN, 4.0, NAN],
            [-11.0, -50.0, NAN, 6.0, NAN],
        ]
    )
    day = np.array(
        [
            [10.0, NAN, 20.0, 4.0, NAN],  # polar night: no day value in cell 1
            [8.0, -44.0, 25.0, 3.0, NAN],
            [9.0, -47.0, NAN, 5.0, NAN],
        ]
    )
    s = step03.summarize(day, night)
    np.testing.assert_allclose(s["tmin_c"], [-12.0, -50.0, NAN, 4.0, NAN])
    # cell 0: (20 + 20 + 20) / 3; cell 1 only months 2-3: (1 + 3) / 2
    np.testing.assert_allclose(s["trange_c"][:2], [20.0, 2.0])
    assert np.isnan(s["trange_c"][2])  # day without night never counts
    assert s["trange_c"][3] == 0.0  # mean -1 clipped
    assert np.isnan(s["tmin_c"][4]) and np.isnan(s["trange_c"][4])  # no data stays null, not 0
    assert s["clipped"] == 1
    assert s["n_night"].tolist() == [3, 3, 0, 3, 0]
    assert s["n_both"].tolist() == [3, 2, 0, 3, 0]


# --- End to end on a coarse synthetic globe ----------------------------------


def _grid(*points):
    return pd.DataFrame({"cell_id": np.array([geo.cell_id_of(*p) for p in points], dtype="int32")})


def test_temperature_cells_on_a_coarse_globe():
    import xarray as xr

    lat, lon = common.global_coords(0.5)  # 4 pixels per cell
    land = np.ones((lat.size, lon.size), dtype=bool)
    i, j = int((90 - 10.5) * 2) - 1, int((20.5 + 180) * 2)  # a pixel of cell (10.5, 20.5)
    land[i, j] = False
    land_da = xr.DataArray(land, coords={"lat": lat, "lon": lon}, dims=("lat", "lon"))

    def kelvin_counts(t_c):
        return np.full((lat.size, lon.size), (t_c + 273.15) / 0.02, dtype=np.float32)

    def read(path, layer):
        month = int(path)
        if layer == step03.NIGHT_LAYER:
            a = kelvin_counts(-month)  # coldest night in December: -12
            a[i, j] = (500 + 273.15) / 0.02  # ocean pixel: must be ignored
            return a
        a = kelvin_counts(30.0 - month)  # day - night = 30 every month
        if month in (6, 7):
            a[:] = NAN  # no daytime data in these months
        return a

    grid = _grid((10.5, 20.5), (-80.5, 0.5), (60.5, -100.5))
    out, s = step03.temperature_cells([str(m) for m in range(1, 13)], grid, land_da, read=read)
    assert out.columns.tolist() == ["cell_id", "tmin_c", "trange_c"]
    assert out["cell_id"].tolist() == grid["cell_id"].tolist()
    assert out["tmin_c"].dtype == np.float32 and out["trange_c"].dtype == np.float32
    np.testing.assert_allclose(out["tmin_c"], -12.0, atol=1e-3)
    np.testing.assert_allclose(out["trange_c"], 30.0, atol=1e-3)
    assert s["n_night"].tolist() == [12, 12, 12] and s["n_both"].tolist() == [10, 10, 10]
    assert s["clipped"] == 0
