"""Fachada que usa la interfaz (design 9.2). Funciones puras: no modifican el bundle.

TAI-21 trae list_targets y get_ranking; el resto de la tabla 9.2 llega con
TAI-30 a TAI-34.
"""

from collections.abc import Mapping

import pandas as pd

from tai import scoring
from tai.constants import RANKING_LIMIT_MAX, TOP_N
from tai.errors import TargetNotFoundError
from tai.io import DataBundle
from tai.models import Ranking, RankingRow, TargetSummary, Weights


def _num(x) -> float | None:
    return None if pd.isna(x) else float(x)


def _text(x) -> str | None:
    return None if pd.isna(x) else str(x)


def list_targets(bundle: DataBundle) -> list[TargetSummary]:
    return [
        TargetSummary(target_id=t.target_id, label=t.label, body=t.body, summary=t.summary)
        for t in bundle.targets.targets
    ]


def get_ranking(
    bundle: DataBundle,
    target_id: str,
    weights: Weights | Mapping[str, float],
    hide_known: bool = False,
    limit: int = TOP_N,
) -> Ranking:
    """Las `limit` mejores celdas elegibles del objetivo, con los pesos dados.

    Lanza TargetNotFoundError, InvalidWeightsError o ZeroWeightsError."""
    if target_id not in bundle.similarity:
        raise TargetNotFoundError(f"No existe el sitio objetivo {target_id!r}")
    if not 1 <= limit <= RANKING_LIMIT_MAX:
        raise ValueError(f"limit debe estar entre 1 y {RANKING_LIMIT_MAX}")

    w = scoring.validate_weights(weights)
    sim = bundle.similarity[target_id]
    ranked = scoring.rank(sim, scoring.combine(sim, w), hide_known=hide_known)
    top = ranked.head(limit)
    grid = bundle.grid.loc[top["cell_id"]]  # lat, lon, country de las filas elegidas

    rows = [
        RankingRow(
            rank=i,
            cell_id=int(r.cell_id),
            lat=float(g.lat),
            lon=float(g.lon),
            country=_text(g.country),
            total=float(r.total),
            terrain=_num(r.s_terrain),
            temperature=_num(r.s_temperature),
            water_ice=_num(r.s_water_ice),
            biology=float(r.bio_score),
            known_analog=_text(r.known_analog),
        )
        for i, (r, g) in enumerate(zip(top.itertuples(index=False), grid.itertuples(index=False)), start=1)
    ]
    return Ranking(target_id=target_id, weights=w, total_eligible=len(ranked), rows=rows)
