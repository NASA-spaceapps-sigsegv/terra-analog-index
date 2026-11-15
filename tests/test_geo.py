import math

import numpy as np
import pytest

from tai import geo
from tai.constants import EARTH_RADIUS_KM, N_CELLS_GLOBAL, N_LAT


def test_worked_example_from_design():
    # Design 2.1: (-24.1, -69.3) -> lat_idx 65, lon_idx 110, cell 23510, center (-24.5, -69.5)
    assert geo.lat_lon_idx(-24.1, -69.3) == (65, 110)
    assert geo.cell_id_of(-24.1, -69.3) == 23510
    assert geo.cell_center(23510) == (-24.5, -69.5)


def test_edges_go_to_last_index():
    assert geo.lat_lon_idx(90.0, 180.0) == (179, 359)
    assert geo.cell_id_of(90.0, 180.0) == N_CELLS_GLOBAL - 1
    assert geo.cell_id_of(-90.0, -180.0) == 0


def test_lon_minus_180_is_first_column():
    assert geo.lat_lon_idx(0.5, -180.0) == (90, 0)
    assert geo.cell_center(geo.cell_id_of(0.5, -180.0)) == (0.5, -179.5)


def test_integer_boundaries_belong_to_upper_cell():
    assert geo.lat_lon_idx(0.0, 0.0) == (90, 180)
    assert geo.lat_lon_idx(-0.0001, -0.0001) == (89, 179)


@pytest.mark.parametrize("lat,lon", [(91, 0), (-90.5, 0), (0, 180.1), (0, -181), (math.nan, 0)])
def test_out_of_range_rejected(lat, lon):
    with pytest.raises(ValueError):
        geo.cell_id_of(lat, lon)


def test_vectorized_roundtrip():
    rng = np.random.default_rng(0)
    lat = rng.uniform(-90, 90, 1000)
    lon = rng.uniform(-180, 180, 1000)
    cid = geo.cell_id_of(lat, lon)
    clat, clon = geo.cell_center(cid)
    assert np.all(np.abs(clat - lat) <= 0.5)
    assert np.all(np.abs(clon - lon) <= 0.5)
    assert np.array_equal(geo.cell_id_of(clat, clon), cid)


def test_cell_center_rejects_bad_id():
    with pytest.raises(ValueError):
        geo.cell_center(N_CELLS_GLOBAL)


def test_area_equator_and_pole():
    # Design 2.1 quotes ~12,300 km2 at the equator and ~1,100 km2 "at 85 deg".
    # Exact values: 12,364 (0-1 N), 1,185 (84-85 N), 970 (85-86 N).
    assert geo.cell_area_km2(90) == pytest.approx(12_364, rel=1e-3)
    assert geo.cell_area_km2(174) == pytest.approx(1_185, rel=1e-3)
    assert geo.cell_area_km2(175) == pytest.approx(970, rel=1e-3)
    assert geo.cell_area_km2(5) == pytest.approx(geo.cell_area_km2(174))  # N/S symmetry


def test_area_sums_to_sphere():
    rows = geo.cell_area_km2(np.arange(N_LAT))
    total = rows.sum() * 360
    assert total == pytest.approx(4 * math.pi * EARTH_RADIUS_KM**2, rel=1e-9)


def test_haversine():
    assert geo.haversine_km(0, 0, 0, 0) == 0.0
    # One degree of latitude ~ 111.2 km
    assert geo.haversine_km(0, 0, 1, 0) == pytest.approx(111.19, abs=0.05)
    # Antipodes: half circumference
    assert geo.haversine_km(0, 0, 0, 180) == pytest.approx(math.pi * EARTH_RADIUS_KM)
    d = geo.haversine_km(np.array([0, 0]), np.array([0, 0]), np.array([0, 1]), np.array([0, 0]))
    assert d.shape == (2,)
