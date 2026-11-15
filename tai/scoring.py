"""Puntaje total con pesos, elegibilidad y orden del ranking (design 5.6 y 5.7, TAI-19).

Lo usan la app en vivo y el paso 09 de validación, con la misma fórmula.
Funciones puras sobre la tabla de similitud de un objetivo (indexada por
cell_id): no leen archivos ni modifican su entrada. Las pruebas están en
tests/test_scoring.py.
"""

from collections.abc import Mapping

import numpy as np
import pandas as pd
from pydantic import ValidationError

from tai.constants import CORE_DIMENSIONS, DIMENSIONS, MIN_PHYSICAL_DIMS, OPTIONAL_DIMENSIONS
from tai.errors import InvalidWeightsError, ZeroWeightsError
from tai.models import Weights

# Los puntajes vienen en float32 (0,1 o 0,3 no son exactos), así que dos totales
# iguales en papel pueden diferir en la octava cifra. Se ordena por el total
# redondeado a esta cantidad de decimales para que un empate real se decida
# por cell_id (design 5.7), sin mezclar totales que difieren de verdad.
TIE_DECIMALS = 6

# dimensión -> columna de similarity.parquet
SCORE_COLUMNS = {
    "terrain": "s_terrain",
    "temperature": "s_temperature",
    "water_ice": "s_water_ice",
    "dust_wind": "s_dust_wind",
    "biology": "bio_score",
}


def validate_weights(weights: Weights | Mapping[str, float]) -> Weights:
    """Devuelve Weights válidos. Falta una dimensión o hay un valor fuera de 0..1:
    InvalidWeightsError. Todos en 0: ZeroWeightsError."""
    if isinstance(weights, Weights):
        w = weights
    else:
        try:
            w = Weights(**dict(weights))
        except (ValidationError, TypeError) as exc:
            raise InvalidWeightsError(f"Pesos inválidos: {exc}") from exc
    if all(v == 0 for v in w.as_dict().values()):
        raise ZeroWeightsError("Subí al menos un peso")
    return w


def _scores(sim: pd.DataFrame, dim: str) -> np.ndarray:
    """Puntajes de una dimensión. Una dimensión opcional sin columna (tabla anterior a TAI-52) es nula."""
    col = SCORE_COLUMNS[dim]
    if col not in sim.columns and dim in OPTIONAL_DIMENSIONS:
        return np.full(len(sim), np.nan)
    return sim[col].astype("float64").to_numpy()


def combine(sim: pd.DataFrame, weights: Weights | Mapping[str, float]) -> pd.Series:
    """Puntaje total por celda (5.6). Las dimensiones nulas salen del denominador;
    si la suma de pesos con dato es 0, el total es nulo."""
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
    """Dato en al menos MIN_PHYSICAL_DIMS de las 3 dimensiones físicas centrales (5.7).

    Polvo y viento (TAI-52) no cuenta: es opcional por objetivo, y contarla cambiaría qué celdas entran."""
    n = sum(sim[SCORE_COLUMNS[d]].notna().astype(int) for d in CORE_DIMENSIONS)
    return n >= MIN_PHYSICAL_DIMS


def rank(sim: pd.DataFrame, total: pd.Series, hide_known: bool = False) -> pd.DataFrame:
    """Celdas elegibles ordenadas por total descendente; empates por cell_id (5.7).

    `sim` está indexada por cell_id. Devuelve un DataFrame con la columna cell_id,
    las columnas de sim y la columna total."""
    mask = is_eligible(sim).to_numpy() & total.notna().to_numpy()
    if hide_known:
        mask &= sim["known_analog"].isna().to_numpy()
    df = sim.assign(total=total, _key=total.round(TIE_DECIMALS))[mask].reset_index()
    df = df.sort_values(["_key", "cell_id"], ascending=[False, True], kind="stable")
    return df.drop(columns="_key").reset_index(drop=True)
