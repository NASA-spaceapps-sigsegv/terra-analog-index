"""Grid geometry (design 2.1).

All functions accept Python scalars or numpy arrays and are vectorized.

    lat_idx = floor(lat + 90)   in [0, 179]
    lon_idx = floor(lon + 180)  in [0, 359]
    cell_id = 360 * lat_idx + lon_idx

Points with lat = 90 or lon = 180 go to the last index (179 / 359).
"""

import numpy as np

from tai.constants import EARTH_RADIUS_KM, GRID_RES_DEG, N_LAT, N_LON


def _check_coords(lat, lon) -> None:
    if np.any(~np.isfinite(lat)) or np.any(~np.isfinite(lon)):
        raise ValueError("lat/lon must be finite")
    if np.any((lat < -90) | (lat > 90)):
        raise ValueError("lat must be in [-90, 90]")
    if np.any((lon < -180) | (lon > 180)):
        raise ValueError("lon must be in [-180, 180]")


def lat_lon_idx(lat, lon):
    """Return (lat_idx, lon_idx) of the cell that contains (lat, lon)."""
    lat = np.asarray(lat, dtype=np.float64)
    lon = np.asarray(lon, dtype=np.float64)
    _check_coords(lat, lon)
    lat_idx = np.minimum(np.floor((lat + 90.0) / GRID_RES_DEG), N_LAT - 1).astype(np.int32)
    lon_idx = np.minimum(np.floor((lon + 180.0) / GRID_RES_DEG), N_LON - 1).astype(np.int32)
    if lat_idx.ndim == 0:
        return int(lat_idx), int(lon_idx)
    return lat_idx, lon_idx


def cell_id_of(lat, lon):
    """cell_id of the 1-degree cell containing (lat, lon)."""
    lat_idx, lon_idx = lat_lon_idx(lat, lon)
    return lat_idx * N_LON + lon_idx


def split_cell_id(cell_id):
    """Return (lat_idx, lon_idx) for a cell_id."""
    cid = np.asarray(cell_id)
    if np.any((cid < 0) | (cid >= N_LAT * N_LON)):
        raise ValueError(f"cell_id must be in [0, {N_LAT * N_LON - 1}]")
    lat_idx, lon_idx = np.divmod(cid, N_LON)
    if lat_idx.ndim == 0:
        return int(lat_idx), int(lon_idx)
    return lat_idx, lon_idx


def cell_center(cell_id):
    """Return (lat, lon) of the cell center."""
    lat_idx, lon_idx = split_cell_id(cell_id)
    half = GRID_RES_DEG / 2.0
    lat = lat_idx * GRID_RES_DEG - 90.0 + half
    lon = lon_idx * GRID_RES_DEG - 180.0 + half
    return lat, lon


def cell_area_km2(lat_idx):
    """Area of a cell in a given latitude row: A = R^2 * dlon * (sin phi2 - sin phi1)."""
    lat_idx = np.asarray(lat_idx)
    if np.any((lat_idx < 0) | (lat_idx >= N_LAT)):
        raise ValueError(f"lat_idx must be in [0, {N_LAT - 1}]")
    phi1 = np.radians(lat_idx * GRID_RES_DEG - 90.0)
    phi2 = np.radians((lat_idx + 1) * GRID_RES_DEG - 90.0)
    dlon = np.radians(GRID_RES_DEG)
    area = EARTH_RADIUS_KM**2 * dlon * (np.sin(phi2) - np.sin(phi1))
    return float(area) if area.ndim == 0 else area


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance in km between points given in degrees."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = p2 - p1
    dlmb = np.radians(np.asarray(lon2) - np.asarray(lon1))
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlmb / 2) ** 2
    d = 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))
    return float(d) if np.ndim(d) == 0 else d
