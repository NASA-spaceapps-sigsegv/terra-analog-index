"""Step 01 on a synthetic world: hand-made polygons, no download (TAI-11)."""

import importlib.util
from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import MultiPolygon, box

from pipeline.common import MissingInputError
from tai import geo, schemas

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("step01", ROOT / "pipeline" / "01_grid.py")
step01 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(step01)


def _gdf(geoms, **cols):
    return gpd.GeoDataFrame(cols, geometry=list(geoms), crs="EPSG:4326")


# box(min_lon, min_lat, max_lon, max_lat)
LAND = _gdf(
    [
        box(10, 10, 12, 12),  # four full cells
        box(20, 10, 20.5, 11),  # half a cell: kept (land_frac == 0.5)
        box(30, 10, 30.4, 11),  # 40% of a cell: dropped
        box(179, 0, 180, 1),  # antimeridian, east side
        box(-180, 0, -179, 1),  # antimeridian, west side
        box(40, 10, 41, 11),  # land with no country polygon
        box(50, 50, 51, 51),  # center rule vs majority
    ]
)
COUNTRIES = _gdf(
    [
        box(10, 10, 12, 12),
        box(20, 10, 20.5, 11),  # center (20.5, 10.5) lies on the edge -> majority
        box(50.4, 50.4, 50.6, 50.6),  # small polygon around the center
        MultiPolygon([box(50, 50, 50.4, 51), box(50.6, 50, 51, 51)]),  # most of the cell
    ],
    NAME_EN=["Alpha", "Beta", "Gamma", "Delta"],
    NAME=["Alpha (short)", "Beta (short)", "Gamma (short)", "Delta (short)"],
)


@pytest.fixture(scope="module")
def mask():
    return step01.rasterize_land(LAND)


@pytest.fixture(scope="module")
def grid(mask):
    return step01.build_grid(step01.land_fraction(mask))


@pytest.fixture(scope="module")
def with_country(grid):
    return step01.assign_country(grid, COUNTRIES)


def _cell(lat, lon):
    return int(geo.cell_id_of(lat, lon))


def test_mask_shape_and_coords(mask):
    assert mask.shape == (3600, 7200)
    assert mask.dtype == np.uint8
    assert mask.lat.values[0] == pytest.approx(89.975)
    assert mask.lon.values[0] == pytest.approx(-179.975)
    # 2x2 deg box = 40x40 pixels; plus the other boxes
    expected = 1600 + 200 + 160 + 400 + 400 + 400 + 400
    assert int(mask.sum()) == expected


def test_full_cells(grid):
    g = grid.set_index("cell_id")
    for lat, lon in [(10.5, 10.5), (10.5, 11.5), (11.5, 10.5), (11.5, 11.5)]:
        assert g.loc[_cell(lat, lon), "land_frac"] == 1.0


def test_threshold(grid):
    ids = set(grid["cell_id"])
    assert _cell(10.5, 20.5) in ids  # exactly 0.5 is kept
    assert grid.set_index("cell_id").loc[_cell(10.5, 20.5), "land_frac"] == 0.5
    assert _cell(10.5, 30.5) not in ids  # 0.4 is dropped


def test_antimeridian(grid):
    ids = set(grid["cell_id"])
    assert _cell(0.5, 179.5) in ids
    assert _cell(0.5, -179.5) in ids


def test_grid_contract(grid):
    assert schemas.check_schema(grid, "grid") == []
    assert len(grid) == 4 + 1 + 2 + 1 + 1
    assert grid["cell_id"].is_monotonic_increasing
    row = grid.set_index("cell_id").loc[_cell(10.5, 10.5)]
    assert (row["lat"], row["lon"]) == (10.5, 10.5)
    assert row["area_km2"] == pytest.approx(geo.cell_area_km2(100), rel=1e-6)


def test_country_rules(with_country):
    grid, counts = with_country
    country = grid.set_index("cell_id")["country"]
    assert country[_cell(10.5, 10.5)] == "Alpha"  # center inside
    assert country[_cell(10.5, 20.5)] == "Beta"  # center on edge -> majority
    assert country[_cell(50.5, 50.5)] == "Gamma"  # center wins over majority
    assert country.isna()[_cell(10.5, 40.5)]  # no polygon at all
    assert counts == {"center": 5, "majority": 1, "none": 3}
    assert schemas.check_schema(grid, "grid") == []


def test_country_name_falls_back_to_name():
    names = step01.country_names(_gdf([box(0, 0, 1, 1)] * 2, NAME_EN=[None, " "], NAME=["X", "Y"]))
    assert names.tolist() == ["X", "Y"]


def test_majority_ties_go_to_smallest_value():
    values = np.zeros((3600, 7200), dtype=np.int32)
    # cell (0.5, 0.5): rows for lat 0..1 are 1780..1799, cols for lon 0..1 are 3600..3619
    values[1780:1790, 3600:3620] = 2
    values[1790:1800, 3600:3620] = 1
    out = step01.majority_by_cell(values, [_cell(0.5, 0.5)])
    assert out.to_dict() == {_cell(0.5, 0.5): 1}


def test_find_vector(tmp_path):
    with pytest.raises(MissingInputError):
        step01.find_vector("ne_50m_land", tmp_path)
    (tmp_path / "ne_50m_land.geojson").write_text("{}")
    (tmp_path / "ne_50m_land.zip").write_text("")
    assert step01.find_vector("ne_50m_land", tmp_path).suffix == ".geojson"
