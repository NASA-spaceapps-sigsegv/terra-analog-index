"""Weighted total score, eligibility and ranking order (design 5.6 and 5.7, TAI-19).

Used by the live app and by validation step 09, with the same formula.
Pure functions over a target's similarity table (indexed by cell_id): they
do not read files or modify their input. The tests are in
tests/test_scoring.py.
"""

from collections.abc import Mapping

import numpy as np
import pandas as pd
from pydantic import ValidationError

from tai.constants import CORE_DIMENSIONS, DIMENSIONS, MIN_PHYSICAL_DIMS, OPTIONAL_DIMENSIONS
from tai.errors import InvalidWeightsError, ZeroWeightsError
from tai.models import Weights

# Scores come as float32 (0.1 or 0.3 are not exact), so two totals that are
# equal on paper can differ in the eighth digit. Sorting uses the total
# rounded to this many decimals so that a real tie is broken by cell_id
# (design 5.7), without mixing totals that truly differ.
TIE_DECIMALS = 6

# dimension -> similarity.parquet column
SCORE_COLUMNS = {
    "terrain": "s_terrain",
    "temperature": "s_temperature",
    "water_ice": "s_water_ice",
    "dust_wind": "s_dust_wind",
    "biology": "bio_score",
}


def validate_weights(weights: Weights | Mapping[str, float]) -> Weights:
    """Return valid Weights. A missing dimension or a value outside 0..1:
    InvalidWeightsError. All at 0: ZeroWeightsError."""
    if isinstance(weights, Weights):
        w = weights
    else:
        try:
            w = Weights(**dict(weights))
        except (ValidationError, TypeError) as exc:
            raise InvalidWeightsError(f"Invalid weights: {exc}") from exc
    if all(v == 0 for v in w.as_dict().values()):
        raise ZeroWeightsError("Raise at least one weight")
    return w


def _scores(sim: pd.DataFrame, dim: str) -> np.ndarray:
    """Scores of one dimension. An optional dimension without a column (table older than TAI-52) is null."""
    col = SCORE_COLUMNS[dim]
    if col not in sim.columns and dim in OPTIONAL_DIMENSIONS:
        return np.full(len(sim), np.nan)
    return sim[col].astype("float64").to_numpy()


def combine(sim: pd.DataFrame, weights: Weights | Mapping[str, float]) -> pd.Series:
    """Total score per cell (5.6). Null dimensions drop out of the denominator;
    if the sum of weights with data is 0, the total is null."""
    w = validate_weights(weights).as_dict()
    scores = np.column_stack([_scores(sim, d) for d in DIMENSIONS])
    wv = np.array([w[d] for d in DIMENSIONS], dtype="float64")
    has = ~np.isnan(scores)
    num = np.where(has, scores * wv, 0.0).sum(axis=1)
    den = (has * wv).sum(axis=1)
    total = np.full(len(sim), np.nan)
    np.divide(num, den, out=total, where=den > 0)
    return pd.Series(total, index=sim.index, name="total")


def is_eligible(sim: pd.DataFrame) -> pd.Series:
    """Data in at least MIN_PHYSICAL_DIMS of the 3 core physical dimensions (5.7).

    Dust and wind (TAI-52) does not count: it is optional per target, and counting it would change which cells get in."""
    n = sum(sim[SCORE_COLUMNS[d]].notna().astype(int) for d in CORE_DIMENSIONS)
    return n >= MIN_PHYSICAL_DIMS


def rank(sim: pd.DataFrame, total: pd.Series, hide_known: bool = False) -> pd.DataFrame:
    """Eligible cells sorted by descending total; ties by cell_id (5.7).

    `sim` is indexed by cell_id. Returns a DataFrame with the cell_id column,
    the columns of sim and the total column."""
    mask = is_eligible(sim).to_numpy() & total.notna().to_numpy()
    if hide_known:
        mask &= sim["known_analog"].isna().to_numpy()
    df = sim.assign(total=total, _key=total.round(TIE_DECIMALS))[mask].reset_index()
    df = df.sort_values(["_key", "cell_id"], ascending=[False, True], kind="stable")
    return df.drop(columns="_key").reset_index(drop=True)
