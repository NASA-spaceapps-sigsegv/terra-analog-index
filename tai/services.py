"""Fachada que usa la interfaz (design 9.2). Funciones puras: no modifican el bundle.

TAI-21 trae list_targets y get_ranking; el resto de la tabla 9.2 llega con
TAI-30 a TAI-34.
"""

from collections.abc import Mapping
from pathlib import Path

import numpy as np
import pandas as pd

from tai import cards, method, scoring
from tai.constants import RANKING_LIMIT_MAX, TOP_N
from tai.errors import CellNotFoundError, TargetNotFoundError, ZeroWeightsError
from tai.io import DataBundle
from tai.models import (
    MAP_CELL_COLUMNS,
    AnalogRef,
    Manifest,
    MapLayer,
    Ranking,
    RankingItem,
    SiteCard,
    Target,
    TargetSummary,
    ValidationReport,
    Weights,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CARDS_DIR = REPO_ROOT / cards.CARDS_DIR
METHOD_PATH = REPO_ROOT / method.METHOD_PATH


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

    names = {a.analog_id: a.name for a in bundle.known_analogs}

    def analog(x) -> AnalogRef | None:
        aid = _text(x)
        return None if aid is None else AnalogRef(analog_id=aid, name=names.get(aid, aid))

    items = [
        RankingItem(
            rank=i,
            cell_id=int(r.cell_id),
            lat=float(g.lat),
            lon=float(g.lon),
            country=_text(g.country),
            total=float(r.total),
            s_terrain=_num(r.s_terrain),
            s_temperature=_num(r.s_temperature),
            s_water_ice=_num(r.s_water_ice),
            s_dust_wind=_num(r.s_dust_wind),
            bio_score=float(r.bio_score),
            known_analog=analog(r.known_analog),
        )
        for i, (r, g) in enumerate(zip(top.itertuples(index=False), grid.itertuples(index=False)), start=1)
    ]
    return Ranking(
        target_id=target_id,
        weights=w,
        hide_known=hide_known,
        limit=limit,
        total_eligible=len(ranked),
        items=items,
    )


def get_map_layer(bundle: DataBundle, target_id: str, weights: Weights | Mapping[str, float]) -> MapLayer:
    """Todas las celdas de la grilla con su puntaje total para el objetivo y los pesos (design 4.4).

    No ordena ni filtra: el mapa dibuja las no elegibles en gris y los análogos conocidos con borde.
    `total` es nulo en las celdas no elegibles. Con todos los pesos en 0 no hay total en ninguna
    celda: la capa sale igual, toda en gris (design 10.6), y el aviso lo muestra el ranking.

    Lanza TargetNotFoundError o InvalidWeightsError.
    """
    if target_id not in bundle.similarity:
        raise TargetNotFoundError(f"No existe el sitio objetivo {target_id!r}")
    sim = bundle.similarity[target_id]  # indexada por cell_id
    eligible = scoring.is_eligible(sim)
    try:
        w = scoring.validate_weights(weights)
        total = scoring.combine(sim, w)
    except ZeroWeightsError:  # pesos válidos pero todos en 0: sin total en ninguna celda
        w = Weights(**_as_dict(weights))
        total = pd.Series(np.nan, index=sim.index)
    total = total.where(eligible)  # nulo si no es elegible

    names = {a.analog_id: a.name for a in bundle.known_analogs}
    grid = bundle.grid.loc[sim.index, ["lat", "lon", "country"]]
    cells = pd.DataFrame(
        {
            "cell_id": sim.index.to_numpy(dtype="int32"),
            "lat": grid["lat"].to_numpy(),
            "lon": grid["lon"].to_numpy(),
            "country": grid["country"].astype(object).to_numpy(),
            "total": total.to_numpy(dtype="float64"),
            "s_terrain": sim["s_terrain"].to_numpy(),
            "s_temperature": sim["s_temperature"].to_numpy(),
            "s_water_ice": sim["s_water_ice"].to_numpy(),
            "s_dust_wind": sim["s_dust_wind"].to_numpy(),
            "bio_score": sim["bio_score"].to_numpy(),
            "eligible": eligible.to_numpy(dtype=bool),
            "known_analog": sim["known_analog"].map(names).astype(object).to_numpy(),
        }
    )[list(MAP_CELL_COLUMNS)]
    return MapLayer(
        target_id=target_id,
        weights=w,
        n_cells=len(cells),
        n_eligible=int(eligible.sum()),
        cells=cells,
    )


def get_site_card(
    bundle: DataBundle,
    cell_id: int,
    target_id: str,
    weights: Weights | Mapping[str, float],
    cards_dir: Path | None = CARDS_DIR,
) -> SiteCard:
    """Ficha de una celda frente a un objetivo (design 11, contrato SiteCard).

    Con todos los pesos en 0 no falla: scores.total es nulo. `cards_dir` es la carpeta de los textos
    manuales; None no los busca. Lanza TargetNotFoundError, CellNotFoundError o InvalidWeightsError."""
    target = next((t for t in bundle.targets.targets if t.target_id == target_id), None)
    if target is None or target_id not in bundle.similarity:
        raise TargetNotFoundError(f"No existe el sitio objetivo {target_id!r}")
    sim = bundle.similarity[target_id]
    cell_id = int(cell_id)
    if cell_id not in sim.index or cell_id not in bundle.grid.index:
        raise CellNotFoundError(f"La celda {cell_id} no está en la grilla")
    try:
        w = scoring.validate_weights(weights)
    except ZeroWeightsError:
        w = Weights(**_as_dict(weights))
    features = bundle.features.loc[cell_id] if cell_id in bundle.features.index else pd.Series(dtype=object)
    return cards.build_card(
        cell_id=cell_id,
        target=target,
        grid_row=bundle.grid.loc[cell_id],
        features_row=features,
        sim_row=sim.loc[cell_id],
        weights=w,
        analogs={a.analog_id: a for a in bundle.known_analogs},
        manifest=bundle.manifest,
        cards_dir=cards_dir,
        root=REPO_ROOT,
    )


def _target(bundle: DataBundle, target_id: str) -> Target:
    target = next((t for t in bundle.targets.targets if t.target_id == target_id), None)
    if target is None:
        raise TargetNotFoundError(f"No existe el sitio objetivo {target_id!r}")
    return target


def get_target(bundle: DataBundle, target_id: str) -> Target:
    """El sitio objetivo completo, con sus variables y fuentes (design 9.2). Lanza TargetNotFoundError."""
    return _target(bundle, target_id)


def get_validation(bundle: DataBundle, target_id: str | None = None) -> ValidationReport:
    """El informe de validation.json. Con `target_id`, solo ese objetivo. Lanza TargetNotFoundError."""
    report = bundle.validation
    if target_id is None:
        return report
    kept = [t for t in report.targets if t.target_id == target_id]
    if not kept:
        raise TargetNotFoundError(f"No hay validación del sitio objetivo {target_id!r}")
    return report.model_copy(update={"targets": kept})


def get_manifest(bundle: DataBundle) -> Manifest:
    """El manifiesto de la corrida del pipeline (manifest.json), fuente de la tabla "Datos usados"."""
    return bundle.manifest


def get_method_text(path: Path | None = None) -> dict[str, str]:
    """Los textos fijos de la pestaña Método, por encabezado ({} si content/method.md todavía no existe)."""
    return method.read_method(METHOD_PATH if path is None else path)


def _as_dict(weights) -> dict[str, float]:
    return weights.as_dict() if isinstance(weights, Weights) else dict(weights)
