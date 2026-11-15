"""Facade used by the interface (design 9.2). Pure functions: they do not modify the bundle.

TAI-21 brings list_targets and get_ranking; the rest of table 9.2 arrives with
TAI-30 to TAI-34.
"""

from collections.abc import Mapping
from pathlib import Path

import numpy as np
import pandas as pd

from tai import cards, method, scoring, tables
from tai import caves as cave_cells
from tai.constants import RANKING_LIMIT_MAX, TOP_N
from tai.errors import CellNotFoundError, TargetNotFoundError, ZeroWeightsError
from tai.io import DataBundle
from tai.models import (
    MAP_CELL_COLUMNS,
    AnalogRef,
    Cave,
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


def get_caves(bundle: DataBundle) -> tuple[Cave, ...]:
    """Caves and lava tubes studied as analogs (TAI-53). They are the same for every target and have
    no score: the map draws them as an informational layer."""
    return bundle.caves


# Columns of the caves table; cell_id is hidden and is used to open the card.
CAVES_TABLE_COLUMNS = ("cell_id", "Cave", "Type", "Rank", "Total", "Why it matters", "Source")


def get_caves_table(
    bundle: DataBundle, target_id: str, weights: Weights | Mapping[str, float], hide_known: bool = False
) -> pd.DataFrame:
    """One row per cave with the rank and total of its cell in the current ranking (TAI-53).

    The rank counts every eligible cell, not only the ones the ranking table shows, and honors the
    known-analogs filter. Rank and total are empty if the cave has no cell (small island), if its
    cell is not eligible or if every weight is 0. Sorted by rank; those without a rank go last.
    Raises TargetNotFoundError or InvalidWeightsError."""
    if target_id not in bundle.similarity:
        raise TargetNotFoundError(f"Target site {target_id!r} does not exist")
    sim = bundle.similarity[target_id]
    try:
        ranked = scoring.rank(sim, scoring.combine(sim, scoring.validate_weights(weights)), hide_known=hide_known)
    except ZeroWeightsError:
        ranked = pd.DataFrame({"cell_id": [], "total": []})
    position = {int(c): i for i, c in enumerate(ranked["cell_id"], start=1)}
    totals = dict(zip(ranked["cell_id"].astype(int), ranked["total"]))

    rows = []
    for cave in bundle.caves:
        cell = cave_cells.cell_of(cave, bundle.grid.index)
        rows.append({
            "cell_id": cell,
            "Cave": cave.name,
            "Type": cave_cells.CAVE_KINDS[cave.kind],
            "Rank": position.get(cell),
            "Total": totals.get(cell),
            "Why it matters": cave.relevance if cell is not None else f"{cave.relevance}. ({cave_cells.NO_CELL})",
            "Source": cave.source,
        })
    df = pd.DataFrame(rows, columns=list(CAVES_TABLE_COLUMNS))
    df = df.astype({"cell_id": "Int64", "Rank": "Int64", "Total": "float64"})
    return df.sort_values("Rank", na_position="last", kind="stable").reset_index(drop=True)


def get_ranking(
    bundle: DataBundle,
    target_id: str,
    weights: Weights | Mapping[str, float],
    hide_known: bool = False,
    limit: int = TOP_N,
) -> Ranking:
    """The target's `limit` best eligible cells, with the given weights.

    Raises TargetNotFoundError, InvalidWeightsError or ZeroWeightsError."""
    if target_id not in bundle.similarity:
        raise TargetNotFoundError(f"Target site {target_id!r} does not exist")
    if not 1 <= limit <= RANKING_LIMIT_MAX:
        raise ValueError(f"limit must be between 1 and {RANKING_LIMIT_MAX}")

    w = scoring.validate_weights(weights)
    sim = bundle.similarity[target_id]
    ranked = scoring.rank(sim, scoring.combine(sim, w), hide_known=hide_known)
    top = ranked.head(limit)
    grid = bundle.grid.loc[top["cell_id"]]  # lat, lon, country of the chosen rows

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


CSV_DECIMALS = 3  # the file's scores, as in data/processed (the table shows 2)


def export_ranking_csv(
    bundle: DataBundle,
    target_id: str,
    weights: Weights | Mapping[str, float],
    hide_known: bool = False,
    limit: int = TOP_N,
) -> str:
    """The current ranking as CSV text with a header: the same rows and columns as the table (RF-34).

    Same arguments and errors as get_ranking. An empty optional column (dust and wind on the Moon) is left
    out, as in the table. Comma separator and decimal point; a missing value is left empty."""
    ranking = get_ranking(bundle, target_id, weights, hide_known=hide_known, limit=limit)
    table = tables.ranking_table(ranking)
    shown = table[tables.visible_columns(table)].round({"Lat": 1, "Lon": 1, **{c: CSV_DECIMALS for c in tables.SCORE_COLUMNS}})
    return shown.to_csv(index=False, lineterminator="\n")


def get_map_layer(bundle: DataBundle, target_id: str, weights: Weights | Mapping[str, float]) -> MapLayer:
    """Every grid cell with its total score for the target and the weights (design 4.4).

    It neither sorts nor filters: the map draws non-eligible cells in gray and known analogs with a border.
    `total` is null in non-eligible cells. With every weight at 0 no cell has a total: the layer is
    returned anyway, all gray (design 10.6), and the ranking shows the warning.

    Raises TargetNotFoundError or InvalidWeightsError.
    """
    if target_id not in bundle.similarity:
        raise TargetNotFoundError(f"Target site {target_id!r} does not exist")
    sim = bundle.similarity[target_id]  # indexed by cell_id
    eligible = scoring.is_eligible(sim)
    try:
        w = scoring.validate_weights(weights)
        total = scoring.combine(sim, w)
    except ZeroWeightsError:  # valid weights but all at 0: no total in any cell
        w = Weights(**_as_dict(weights))
        total = pd.Series(np.nan, index=sim.index)
    total = total.where(eligible)  # null if not eligible

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
    """Card for a cell against a target (design 11, SiteCard contract).

    With every weight at 0 it does not fail: scores.total is null. `cards_dir` is the folder of the manual
    texts; None skips them. Raises TargetNotFoundError, CellNotFoundError or InvalidWeightsError."""
    target = next((t for t in bundle.targets.targets if t.target_id == target_id), None)
    if target is None or target_id not in bundle.similarity:
        raise TargetNotFoundError(f"Target site {target_id!r} does not exist")
    sim = bundle.similarity[target_id]
    cell_id = int(cell_id)
    if cell_id not in sim.index or cell_id not in bundle.grid.index:
        raise CellNotFoundError(f"Cell {cell_id} is not in the grid")
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
        caves=cave_cells.caves_in_cell(bundle.caves, cell_id, bundle.grid.index),
    )


def _target(bundle: DataBundle, target_id: str) -> Target:
    target = next((t for t in bundle.targets.targets if t.target_id == target_id), None)
    if target is None:
        raise TargetNotFoundError(f"Target site {target_id!r} does not exist")
    return target


def get_target(bundle: DataBundle, target_id: str) -> Target:
    """The full target site, with its variables and sources (design 9.2). Raises TargetNotFoundError."""
    return _target(bundle, target_id)


def get_validation(bundle: DataBundle, target_id: str | None = None) -> ValidationReport:
    """The validation.json report. With `target_id`, only that target. Raises TargetNotFoundError."""
    report = bundle.validation
    if target_id is None:
        return report
    kept = [t for t in report.targets if t.target_id == target_id]
    if not kept:
        raise TargetNotFoundError(f"There is no validation for target site {target_id!r}")
    return report.model_copy(update={"targets": kept})


def get_manifest(bundle: DataBundle) -> Manifest:
    """The pipeline run manifest (manifest.json), source of the "Data used" table."""
    return bundle.manifest


def get_method_text(path: Path | None = None) -> dict[str, str]:
    """The fixed texts of the Method tab, by heading ({} if content/method.md does not exist yet)."""
    return method.read_method(METHOD_PATH if path is None else path)


def _as_dict(weights) -> dict[str, float]:
    return weights.as_dict() if isinstance(weights, Weights) else dict(weights)
