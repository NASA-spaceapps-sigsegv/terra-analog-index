"""Scoring rules of one variable and area-weighted Earth statistics (design 5.1 to 5.5, TAI-18).

Pure functions over numpy arrays: no files, no network. Step 06 uses the
weighted statistics, step 07 uses choose_rule and step 08 uses the rest, so
each formula exists once. A missing value (NaN) in gives a missing score out;
it is never turned into 0 (design 1.2). Tests in tests/test_rules.py.
"""

import math

import numpy as np

from tai.constants import BIO_TYPES, DIMENSION_VARS, PHYSICAL_VARS, RULES, SIGMA_FLOOR_FRAC

TERRAIN_VARS = DIMENSION_VARS["terrain"]
ICE_VAR = "ice_frac"


# --- Choice of the rule (design 5.1) -----------------------------------------


def choose_rule(variable: str, mean: float, earth_p01: float, earth_p99: float, has_ice: bool) -> str:
    """Rule of a target variable, written to targets.json by step 07.

    slope_deg, roughness_m: always overlap. ice_frac: presence if the target has
    ice, absence if not. The rest: overlap if the target mean lies within the
    Earth's 1st and 99th percentiles (inclusive), directional_low below,
    directional_high above.
    """
    if variable not in PHYSICAL_VARS:
        raise ValueError(f"unknown variable {variable!r}")
    if variable in TERRAIN_VARS:
        return "overlap"
    if variable == ICE_VAR:
        return "presence" if has_ice else "absence"
    if mean is None or not math.isfinite(mean):
        raise ValueError(f"{variable}: the target mean must be a finite number")
    if mean < earth_p01:
        return "directional_low"
    if mean > earth_p99:
        return "directional_high"
    return "overlap"


# --- Rules (design 5.2 to 5.4) -----------------------------------------------


def overlap(x, mean: float, std: float, earth_std: float) -> np.ndarray:
    """exp(-|x - mean| / sigma), sigma = max(std, SIGMA_FLOOR_FRAC * earth_std).

    The floor keeps a very homogeneous target from leaving every cell at 0.
    With sigma = 0 (target and Earth without spread) only x == mean scores 1.
    """
    x = np.asarray(x, dtype=np.float64)
    sigma = max(float(std), SIGMA_FLOOR_FRAC * float(earth_std))
    dist = np.abs(x - float(mean))
    if sigma == 0:
        return np.where(np.isnan(x), np.nan, (dist == 0).astype(np.float64))
    return np.exp(-dist / sigma)


def _share_of_area(x, area, at_most: bool) -> np.ndarray:
    """For each value, the share of the total area (cells with data) whose
    value is <= it (at_most) or >= it. Ties count on both sides."""
    x = np.asarray(x, dtype=np.float64)
    area = np.broadcast_to(np.asarray(area, dtype=np.float64), x.shape)
    out = np.full(x.shape, np.nan)
    ok = ~np.isnan(x)
    if not ok.any():
        return out
    v, a = x[ok], area[ok]
    if np.any(a <= 0) or np.any(~np.isfinite(a)):
        raise ValueError("areas must be finite and > 0")
    order = np.argsort(v, kind="stable")
    vs, cum = v[order], np.cumsum(a[order])
    total = cum[-1]
    if at_most:
        idx = np.searchsorted(vs, v, side="right") - 1  # last position with value <= v
        out[ok] = cum[idx] / total
    else:
        idx = np.searchsorted(vs, v, side="left")  # first position with value >= v
        below = np.where(idx > 0, cum[np.maximum(idx - 1, 0)], 0.0)
        out[ok] = (total - below) / total
    return np.clip(out, 0.0, 1.0)


def directional_high(x, area) -> np.ndarray:
    """Share of the land area (with data) at or below x: the highest cell scores 1."""
    return _share_of_area(x, area, at_most=True)


def directional_low(x, area) -> np.ndarray:
    """Share of the land area (with data) at or above x: the lowest cell scores 1."""
    return _share_of_area(x, area, at_most=False)


def presence(ice) -> np.ndarray:
    return np.asarray(ice, dtype=np.float64).copy()


def absence(ice) -> np.ndarray:
    return 1.0 - np.asarray(ice, dtype=np.float64)


def score_variable(rule: str, x, area, mean: float, std: float, earth_std: float) -> np.ndarray:
    """Score of one variable over all cells with the rule written in targets.json."""
    if rule == "overlap":
        return overlap(x, mean, std, earth_std)
    if rule == "directional_low":
        return directional_low(x, area)
    if rule == "directional_high":
        return directional_high(x, area)
    if rule == "presence":
        return presence(x)
    if rule == "absence":
        return absence(x)
    raise ValueError(f"unknown rule {rule!r}; expected one of {RULES}")


# --- Dimension and biology (design 5.5) --------------------------------------


def dimension_score(*scores) -> np.ndarray:
    """Plain mean of the variable scores with data; null if none has data."""
    s = np.column_stack([np.asarray(v, dtype=np.float64) for v in scores])
    n = (~np.isnan(s)).sum(axis=1)
    total = np.nansum(s, axis=1)
    out = np.full(len(s), np.nan)
    np.divide(total, n, out=out, where=n > 0)
    return out


def bio_score(records, types, n_max: int | None = None) -> np.ndarray:
    """B = 0.5 * ln(1 + n) / ln(1 + n_max) + 0.5 * t / 6. Never null: no records gives 0.

    n_max defaults to the largest record count given; if it is 0 every score is 0.
    """
    n = np.asarray(records, dtype=np.float64)
    t = np.asarray(types, dtype=np.float64)
    if np.isnan(n).any() or np.isnan(t).any():
        raise ValueError("bio_records and bio_types cannot be null")
    n_max = float(n.max()) if n_max is None and n.size else float(n_max or 0)
    amount = np.log1p(n) / np.log1p(n_max) if n_max > 0 else np.zeros_like(n)
    return 0.5 * amount + 0.5 * t / len(BIO_TYPES)


# --- Area-weighted Earth statistics (step 06, design 5.3 and 6.1) ------------


def weighted_quantile(x, weights, q: float) -> float:
    """Area-weighted quantile (q in 0..1) of the values with data; NaN if none.

    The value where the cumulative weight first reaches q of the total, so
    it is always one of the data values.
    """
    x = np.asarray(x, dtype=np.float64)
    w = np.broadcast_to(np.asarray(weights, dtype=np.float64), x.shape)
    ok = ~np.isnan(x)
    if not ok.any():
        return float("nan")
    order = np.argsort(x[ok], kind="stable")
    v, cw = x[ok][order], np.cumsum(w[ok][order])
    i = int(np.searchsorted(cw, q * cw[-1], side="left"))
    return float(v[min(i, len(v) - 1)])


def weighted_std(x, weights) -> float:
    """Area-weighted population standard deviation of the values with data."""
    x = np.asarray(x, dtype=np.float64)
    w = np.broadcast_to(np.asarray(weights, dtype=np.float64), x.shape)
    ok = ~np.isnan(x)
    if not ok.any():
        return float("nan")
    mean = np.average(x[ok], weights=w[ok])
    return float(np.sqrt(np.average((x[ok] - mean) ** 2, weights=w[ok])))
