import numpy as np
import pandas as pd

from tai import schemas


def _grid_df(**overrides):
    df = pd.DataFrame(
        {
            "cell_id": np.array([23510], dtype="int32"),
            "lat_idx": np.array([65], dtype="int16"),
            "lon_idx": np.array([110], dtype="int16"),
            "lat": np.array([-24.5], dtype="float32"),
            "lon": np.array([-69.5], dtype="float32"),
            "area_km2": np.array([11250.4], dtype="float32"),
            "land_frac": np.array([1.0], dtype="float32"),
            "country": pd.array(["Chile"], dtype="string"),
        }
    )
    for k, v in overrides.items():
        df[k] = v
    return df


def test_valid_grid_passes():
    assert schemas.check_schema(_grid_df(), "grid") == []


def test_wrong_dtype_reported():
    problems = schemas.check_schema(_grid_df(cell_id=np.array([1], dtype="int64")), "grid")
    assert any("cell_id" in p and "dtype" in p for p in problems)


def test_missing_and_extra_columns_reported():
    df = _grid_df().drop(columns=["country"]).assign(foo=1)
    problems = schemas.check_schema(df, "grid")
    assert any("missing" in p for p in problems)
    assert any("unexpected" in p for p in problems)


def test_null_in_non_nullable_reported():
    df = _grid_df(lat=np.array([np.nan], dtype="float32"))
    assert any("lat" in p and "null" in p for p in schemas.check_schema(df, "grid"))


def test_duplicate_key_reported():
    df = pd.concat([_grid_df(), _grid_df()], ignore_index=True)
    assert any("duplicate" in p for p in schemas.check_schema(df, "grid"))
