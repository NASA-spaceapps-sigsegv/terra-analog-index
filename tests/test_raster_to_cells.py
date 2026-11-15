import numpy as np
import pandas as pd
import pytest
import xarray as xr

from pipeline import common
from pipeline.common import OutputValidationError, raster_to_cells, validate_output
from tai import geo


def _raster(lat_min, lat_max, lon_min, lon_max, res, fill):
    lat = np.arange(lat_min + res / 2, lat_max, res)
    lon = np.arange(lon_min + res / 2, lon_max, res)
    values = np.full((lat.size, lon.size), fill, dtype=np.float64)
    return xr.DataArray(values, coords={"lat": lat, "lon": lon}, dims=("lat", "lon"), name="v")


def _grid(*cell_ids):
    return pd.DataFrame({"cell_id": np.array(cell_ids, dtype="int32")})


def test_mean_per_cell():
    da = _raster(-25, -23, -70, -69, 0.25, 0.0)
    da[:4, :] = 10.0  # cell (-25..-24) -> 10
    da[4:, :] = 20.0  # cell (-24..-23) -> 20
    a = geo.cell_id_of(-24.5, -69.5)
    b = geo.cell_id_of(-23.5, -69.5)
    out = raster_to_cells(da, _grid(a, b))
    assert out.dtype == np.float32
    assert out.loc[a] == 10.0 and out.loc[b] == 20.0


def test_min_valid_fraction():
    da = _raster(0, 1, 0, 1, 0.25, 5.0)  # 16 pixels
    da.values.flat[:13] = np.nan  # 3 valid = 0.1875
    cid = geo.cell_id_of(0.5, 0.5)
    assert np.isnan(raster_to_cells(da, _grid(cid)).loc[cid])
    da.values.flat[12] = 5.0  # 4 valid = 0.25
    assert raster_to_cells(da, _grid(cid)).loc[cid] == 5.0


def test_mask_excludes_pixels_from_both_counts():
    da = _raster(0, 1, 0, 1, 0.5, 1.0)  # 4 pixels
    da.values[0, 0] = 100.0
    mask = np.array([[False, True], [True, True]])
    cid = geo.cell_id_of(0.5, 0.5)
    assert raster_to_cells(da, _grid(cid), mask=mask).loc[cid] == 1.0


def test_longitudes_0_360_are_wrapped():
    da = _raster(10, 11, 0, 360, 1.0, 0.0)
    da.loc[dict(lon=359.5)] = 7.0
    cid = geo.cell_id_of(10.5, -0.5)
    assert raster_to_cells(da, _grid(cid)).loc[cid] == 7.0


def test_cells_outside_raster_are_null():
    da = _raster(0, 1, 0, 1, 0.5, 1.0)
    far = geo.cell_id_of(50.5, 50.5)
    assert np.isnan(raster_to_cells(da, _grid(far)).loc[far])


def test_validate_output_ranges_and_grid():
    df = pd.DataFrame({"cell_id": [1, 2], "slope_deg": [10.0, None]})
    validate_output(df, grid_ids=[1, 2])
    with pytest.raises(OutputValidationError, match="slope_deg"):
        validate_output(df.assign(slope_deg=[95.0, 1.0]), grid_ids=[1, 2])
    with pytest.raises(OutputValidationError, match="not in the grid"):
        validate_output(df, grid_ids=[1])
    with pytest.raises(OutputValidationError, match="duplicates"):
        validate_output(pd.DataFrame({"cell_id": [1, 1]}))


def test_run_maps_exceptions_to_exit_codes():
    def missing():
        raise common.MissingInputError("x")

    def invalid():
        raise OutputValidationError("x")

    for fn, code in [(missing, 2), (invalid, 1), (lambda: None, 0)]:
        with pytest.raises(SystemExit) as exc:
            common.run(fn)
        assert exc.value.code == code
