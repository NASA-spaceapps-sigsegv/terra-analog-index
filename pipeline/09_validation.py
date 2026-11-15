"""Step 09: validation against known analogs and finalist candidates (design 6.1 and 12.2, TAI-20).

Reads:  data/processed/similarity.parquet, data/processed/known_analogs.csv  (step 08)
        data/processed/grid.parquet                                          (step 01)
        config/validation_notes.json   optional, hand-edited by Santino: {"<target_id>": "note"}
Writes: data/processed/validation.json     the ValidationReport of contract 6.1
        data/interim/finalists.csv         candidate finalist cells per target (not versioned)

The index is credible only if it rediscovers the analogs the community already
uses, so with the initial weights and the same `combine` and `rank` as the app
(tai.scoring), each known analog is scored by its best eligible cell inside its
radius:

    percentile = 100 * (1 - (best_rank - 1) / n_eligible)

A covered analog (covered = yes) passes at the 90th percentile or above. A
target passes if it has at least 2 covered analogs and at least two thirds of
them pass; with fewer than 2 it is "insufficient". Analogs that are not covered
(partial or no) are reported but never count. No exceptions per cell: if a
target fails, the review order of design 12.2 applies and each change is noted.

The note of each target is Santino's. A failed target needs one, so while
config/validation_notes.json has none the step writes a note that starts with
"PENDIENTE" and warns.
"""

import json
import sys
import time
from pathlib import Path

# Steps run as `python pipeline/NN_step.py`; put the repo root on the path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402

from pipeline.common import (  # noqa: E402
    CONFIG,
    GRID_PATH,
    INTERIM,
    PROCESSED,
    OutputValidationError,
    atomic_write_json,
    file_size_mb,
    is_up_to_date,
    load_grid,
    make_parser,
    require_inputs,
    run,
    setup_logging,
    step_entry,
    utc_now_iso,
    write_step_manifest,
)
from tai import geo, models, scoring  # noqa: E402
from tai.constants import (  # noqa: E402
    DEFAULT_WEIGHTS,
    SCHEMA_VERSION,
    SCORE_DECIMALS_FILE,
    TARGET_IDS,
    VALIDATION_PERCENTILE,
)

STEP = "09_validation"
SIMILARITY_PATH = PROCESSED / "similarity.parquet"
ANALOGS_PATH = PROCESSED / "known_analogs.csv"
NOTES_PATH = CONFIG / "validation_notes.json"
OUTPUT = PROCESSED / "validation.json"
FINALISTS_OUT = INTERIM / "finalists.csv"

PASS_FRACTION = 2 / 3  # design 12.2: at least two thirds of the covered analogs
MIN_COVERED = 2  # design 12.2: fewer covered analogs than this is "insufficient"
PENDING_NOTE = "PENDIENTE: nota de Santino sobre por qué no pasó y qué se revisó (design 12.2)"
FINALISTS_DEFAULT = 8  # the ticket asks for 6 to 10 per target


def raw_percentile(best_rank: int, n_eligible: int) -> float:
    """Percentile of a rank among the eligible cells (contract 6.1), unrounded."""
    return 100.0 * (1.0 - (best_rank - 1) / n_eligible)


def percentile(best_rank: int, n_eligible: int) -> float:
    """Percentile as written to validation.json: one decimal."""
    return round(raw_percentile(best_rank, n_eligible), 1)


def cells_within(analog, grid: pd.DataFrame) -> pd.Series:
    """cell_id of the grid cells whose center is within the analog's radius (great circle, inclusive)."""
    d = geo.haversine_km(grid["lat"].to_numpy(), grid["lon"].to_numpy(), analog.lat, analog.lon)
    return grid.loc[d <= analog.radius_km, "cell_id"]


def validate_analog(analog: models.KnownAnalog, ranked: pd.DataFrame, grid: pd.DataFrame,
                    n_eligible: int, threshold: float) -> models.AnalogValidation:
    """Score one analog by its best eligible cell inside the radius."""
    inside = cells_within(analog, grid)
    hit = ranked[ranked["cell_id"].isin(set(inside))]
    base = {"analog_id": analog.analog_id, "name": analog.name, "covered": analog.covered, "n_cells": int(len(inside))}
    if hit.empty:  # no cell inside the radius, or none of them eligible
        return models.AnalogValidation(**base, best_cell_id=None, best_total=None, best_rank=None,
                                       percentile=None, result="no_data")
    best = hit.iloc[0]  # `ranked` is already in rank order
    rank = int(hit.index[0]) + 1
    pct = percentile(rank, n_eligible)
    if analog.covered != "yes":
        result = "info"
    else:  # the unrounded value decides: 89.96 must not pass because it prints as 90.0
        result = "pass" if raw_percentile(rank, n_eligible) >= threshold - 1e-9 else "fail"
    return models.AnalogValidation(**base, best_cell_id=int(best["cell_id"]),
                                   best_total=round(float(best["total"]), SCORE_DECIMALS_FILE),
                                   best_rank=rank, percentile=pct, result=result)


def target_result(covered_total: int, covered_passed: int) -> str:
    if covered_total < MIN_COVERED:
        return "insufficient"
    return "pass" if covered_passed / covered_total >= PASS_FRACTION - 1e-9 else "fail"


def validate_target(target_id: str, sim: pd.DataFrame, grid: pd.DataFrame, analogs: list[models.KnownAnalog],
                    weights=DEFAULT_WEIGHTS, threshold: float = VALIDATION_PERCENTILE,
                    note: str = "") -> models.TargetValidation:
    """The validation of one target. `sim` is its similarity table indexed by cell_id."""
    ranked = scoring.rank(sim, scoring.combine(sim, weights))
    n_eligible = len(ranked)
    results = [validate_analog(a, ranked, grid, n_eligible, threshold) for a in analogs]
    covered = [r for r in results if r.covered == "yes"]
    passed = sum(r.result == "pass" for r in covered)
    result = target_result(len(covered), passed)
    if result == "fail" and not note.strip():
        note = PENDING_NOTE
    return models.TargetValidation(target_id=target_id, result=result, covered_total=len(covered),
                                   covered_passed=passed, n_eligible=n_eligible, note=note, analogs=results)


def finalist_candidates(sim: pd.DataFrame, grid: pd.DataFrame, weights=DEFAULT_WEIGHTS, n: int = FINALISTS_DEFAULT) -> pd.DataFrame:
    """The `n` best eligible cells that are not a known analog (design 12.2, TAI-20)."""
    ranked = scoring.rank(sim, scoring.combine(sim, weights), hide_known=True).head(n)
    g = grid.set_index("cell_id").loc[ranked["cell_id"], ["lat", "lon", "country"]].reset_index(drop=True)
    out = pd.concat([ranked[[c for c in ("cell_id", "total", "s_terrain", "s_temperature", "s_water_ice", "s_dust_wind", "bio_score")
                if c in ranked.columns]]
                     .reset_index(drop=True), g], axis=1)
    out.insert(0, "rank", range(1, len(out) + 1))
    return out


def build_report(sim_all: pd.DataFrame, grid: pd.DataFrame, analogs: list[models.KnownAnalog],
                 notes: dict[str, str] | None = None, weights=DEFAULT_WEIGHTS,
                 threshold: float = VALIDATION_PERCENTILE) -> models.ValidationReport:
    """The ValidationReport of every target that has a similarity table."""
    notes = notes or {}
    targets = []
    for tid in TARGET_IDS:
        sim = sim_all[sim_all["target_id"] == tid].set_index("cell_id")
        if sim.empty:
            continue
        targets.append(validate_target(tid, sim, grid, [a for a in analogs if a.target_id == tid],
                                       weights, threshold, notes.get(tid, "")))
    return models.ValidationReport(schema_version=SCHEMA_VERSION, generated_at=utc_now_iso(),
                                   weights=models.Weights(**dict(weights)), percentile_threshold=threshold,
                                   targets=targets)


def load_analogs(path: Path = ANALOGS_PATH) -> list[models.KnownAnalog]:
    require_inputs([path])
    return [models.KnownAnalog.model_validate(r) for r in pd.read_csv(path).to_dict(orient="records")]


def load_notes(path: Path = NOTES_PATH) -> dict[str, str]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def main() -> None:
    parser = make_parser(STEP, __doc__.splitlines()[0])
    parser.add_argument("--finalists", type=int, default=FINALISTS_DEFAULT,
                        help=f"finalist candidates per target (default {FINALISTS_DEFAULT}; the ticket asks for 6 to 10)")
    args = parser.parse_args()
    log = setup_logging(STEP)
    started = time.monotonic()

    inputs = [SIMILARITY_PATH, ANALOGS_PATH, GRID_PATH]
    require_inputs(inputs)
    tai_dir = Path(__file__).resolve().parents[1] / "tai"
    freshness = [*inputs, NOTES_PATH, Path(__file__), tai_dir / "scoring.py", tai_dir / "constants.py"]
    if not args.force and is_up_to_date([OUTPUT, FINALISTS_OUT], freshness):
        log.info("al día")
        return

    grid = load_grid()
    sim_all = pd.read_parquet(SIMILARITY_PATH)
    report = build_report(sim_all, grid, load_analogs(), load_notes())

    notes = []
    missing = [tid for tid in TARGET_IDS if tid not in {t.target_id for t in report.targets}]
    for tid in missing:
        line = f"{tid}: sin filas en similarity.parquet, queda fuera de la validación"
        notes.append(line)
        log.warning(line)
    if not report.targets:
        raise OutputValidationError("similarity.parquet no tiene filas de ningún objetivo")
    frames = []
    for t in report.targets:
        line = (f"{t.target_id}: {t.result} ({t.covered_passed} de {t.covered_total} análogos cubiertos "
                f"en el percentil {report.percentile_threshold:g} o más; {t.n_eligible} celdas elegibles)")
        notes.append(line)
        log.info(line)
        for a in t.analogs:
            log.info("  %s [%s]: %s, %s celdas, mejor puesto %s, percentil %s", a.analog_id, a.covered,
                     a.result, a.n_cells, a.best_rank, a.percentile)
        if t.note.startswith("PENDIENTE"):
            log.warning("%s no pasó y no tiene nota: Santino la carga en config/validation_notes.json", t.target_id)
        sim = sim_all[sim_all["target_id"] == t.target_id].set_index("cell_id")
        frames.append(finalist_candidates(sim, grid, n=args.finalists).assign(target_id=t.target_id))
    finalists = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    atomic_write_json(report.model_dump(mode="json"), OUTPUT)
    FINALISTS_OUT.parent.mkdir(parents=True, exist_ok=True)
    finalists.to_csv(FINALISTS_OUT, index=False)
    for tid, g in finalists.groupby("target_id"):
        log.info("candidatas a finalista de %s: %s", tid,
                 "; ".join(f"{r.rank}. celda {r.cell_id} ({r.lat:.1f}, {r.lon:.1f}) {r.country or ''} {r.total:.2f}"
                           for r in g.itertuples()))
    write_step_manifest(
        step_entry(
            STEP,
            started,
            inputs=[{"name": "Similitud por celda y análogos conocidos", "product": "similarity.parquet, known_analogs.csv",
                     "portal": "Pipeline del proyecto (pasos 08 y 01)", "url": "https://github.com/NASA-spaceapps-sigsegv/terra-analog-index",
                     "files": len(inputs), "size_mb": round(sum(file_size_mb(p) for p in inputs), 1),
                     "license_note": "Datos derivados del proyecto"}],
            outputs=[(OUTPUT, len(report.targets)), (FINALISTS_OUT, len(finalists))],
            columns={},
            notes=notes,
        )
    )
    log.info("wrote %s (%d targets) and %s (%d candidates)", OUTPUT.name, len(report.targets), FINALISTS_OUT.name, len(finalists))


if __name__ == "__main__":
    run(main)
