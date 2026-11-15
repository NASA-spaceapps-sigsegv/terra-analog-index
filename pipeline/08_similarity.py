"""Step 08: similarity of every cell to every target (design 5.2 to 5.7 and 6.1, TAI-18).

Reads:  data/processed/features.parquet  (step 06)
        data/processed/targets.json      (step 07: mean, std, rule and earth_std of each variable)
        data/processed/grid.parquet      (step 01: area and center of each cell)
        config/known_analogs.csv         (hand-edited by Santino, TAI-17)
Writes: data/processed/similarity.parquet  one row per cell and target (contract 3.4)
        data/processed/known_analogs.csv   the validated config file, as the app reads it

For each target, each physical variable gets a 0..1 score with the rule that
step 07 wrote (tai.rules): overlap against the target's mean and std,
area-weighted percentile for the directional rules, ice_frac itself for
presence and 1 - ice_frac for absence. A dimension is the plain mean of its
variables with data, null if none has. bio_score measures documented
astrobiological interest, the same for every target. A cell is eligible with
data in at least 2 of the 3 physical dimensions. known_analog is the nearest
analog of that target whose radius reaches the cell center.

Scores are stored with SCORE_DECIMALS_FILE decimals; dimensions are computed
from the unrounded variable scores.
"""

import sys
import time
from pathlib import Path

# Steps run as `python pipeline/NN_step.py`; put the repo root on the path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from pipeline.common import (  # noqa: E402
    CONFIG,
    GRID_PATH,
    PARTIAL_NOTE_PREFIX,
    PROCESSED,
    ROOT,
    OutputValidationError,
    atomic_write_csv,
    atomic_write_parquet,
    column_stats,
    file_size_mb,
    is_up_to_date,
    last_run_partial,
    load_grid,
    make_parser,
    require_inputs,
    run,
    setup_logging,
    step_entry,
    validate_output,
    write_step_manifest,
)
from tai import geo, models, rules, scoring  # noqa: E402
from tai.constants import (  # noqa: E402
    DIMENSION_VARS,
    PHYSICAL_DIMENSIONS,
    PHYSICAL_VARS,
    SCORE_DECIMALS_FILE,
    TARGET_IDS,
)
from tai.schemas import KNOWN_ANALOGS_COLUMNS, SIMILARITY  # noqa: E402

STEP = "08_similarity"
FEATURES_PATH = PROCESSED / "features.parquet"
TARGETS_PATH = PROCESSED / "targets.json"
ANALOGS_IN = CONFIG / "known_analogs.csv"
OUTPUT = PROCESSED / "similarity.parquet"
ANALOGS_OUT = PROCESSED / "known_analogs.csv"

DIM_COLUMN = {d: f"s_{d}" for d in PHYSICAL_DIMENSIONS}
SCORE_COLUMNS = [f"sv_{v}" for v in PHYSICAL_VARS] + list(DIM_COLUMN.values()) + ["bio_score"]


def load_analogs(path: Path = ANALOGS_IN, target_ids=TARGET_IDS) -> list[models.KnownAnalog]:
    """Rows of known_analogs.csv, validated; every target_id must be a known target."""
    require_inputs([path])
    df = pd.read_csv(path, dtype={"analog_id": str, "target_id": str})
    if list(df.columns) != list(KNOWN_ANALOGS_COLUMNS):
        raise OutputValidationError(f"known_analogs.csv: columnas {list(df.columns)}, se esperan {list(KNOWN_ANALOGS_COLUMNS)}")
    analogs = [models.KnownAnalog.model_validate(r) for r in df.to_dict(orient="records")]
    unknown = sorted({a.target_id for a in analogs} - set(target_ids))
    if unknown:
        raise OutputValidationError(f"known_analogs.csv: target_id desconocidos {unknown}")
    if df.duplicated(subset=["analog_id", "target_id"]).any():
        raise OutputValidationError("known_analogs.csv: filas repetidas (analog_id, target_id)")
    return analogs


def nearest_analog(lat, lon, analogs: list[models.KnownAnalog]) -> tuple[pd.Series, np.ndarray]:
    """For each cell center, the nearest analog whose radius reaches it, and the distance."""
    n = len(lat)
    best_id = np.full(n, None, dtype=object)
    best_km = np.full(n, np.nan)
    for a in analogs:
        d = np.asarray(geo.haversine_km(lat, lon, a.lat, a.lon), dtype=np.float64)
        closer = (d <= a.radius_km) & ~(d >= best_km)  # NaN best_km: no analog yet
        best_id[closer] = a.analog_id
        best_km[closer] = d[closer]
    return pd.Series(best_id, dtype="string"), best_km


def target_similarity(target: models.Target, features: pd.DataFrame, area: np.ndarray, lat, lon,
                      bio: np.ndarray, analogs: list[models.KnownAnalog]) -> pd.DataFrame:
    """similarity rows of one target; `features`, `area`, `lat`, `lon` and `bio` are aligned by row."""
    sv = {}
    for v in PHYSICAL_VARS:
        tv = target.vars[v]
        x = features[v].to_numpy(dtype=np.float64)
        sv[v] = np.clip(rules.score_variable(tv.rule, x, area, tv.mean, tv.std, tv.earth_std), 0.0, 1.0)
    out = pd.DataFrame({"cell_id": features["cell_id"].to_numpy(dtype="int32")})
    out["target_id"] = pd.Series([target.target_id] * len(out), dtype="string")
    for v in PHYSICAL_VARS:
        out[f"sv_{v}"] = sv[v]
    for d in PHYSICAL_DIMENSIONS:
        out[DIM_COLUMN[d]] = rules.dimension_score(*(sv[v] for v in DIMENSION_VARS[d]))
    out["bio_score"] = bio
    for c in SCORE_COLUMNS:
        out[c] = out[c].round(SCORE_DECIMALS_FILE).astype("float32")
    out["n_physical"] = out[list(DIM_COLUMN.values())].notna().sum(axis=1).astype("int8")
    out["eligible"] = scoring.is_eligible(out).astype(bool)
    known, km = nearest_analog(lat, lon, [a for a in analogs if a.target_id == target.target_id])
    out["known_analog"] = known.to_numpy()  # already "string" dtype; positions match `out`
    out["known_analog_km"] = pd.Series(km).round(1).astype("float32").to_numpy()
    return out[list(SIMILARITY)]


def build_similarity(features: pd.DataFrame, grid: pd.DataFrame, targets: models.TargetsFile,
                     analogs: list[models.KnownAnalog]) -> tuple[pd.DataFrame, int]:
    """similarity.parquet for every target in targets.json, and n_max of bio_records."""
    cells = features.merge(grid[["cell_id", "lat", "lon", "area_km2"]], on="cell_id", how="left")
    if cells["area_km2"].isna().any():
        raise OutputValidationError("features.parquet tiene celdas que no están en la grilla")
    area = cells["area_km2"].to_numpy(dtype=np.float64)
    lat, lon = cells["lat"].to_numpy(dtype=np.float64), cells["lon"].to_numpy(dtype=np.float64)
    n_max = int(cells["bio_records"].max()) if len(cells) else 0
    bio = rules.bio_score(cells["bio_records"], cells["bio_types"], n_max=n_max)
    parts = [target_similarity(t, cells, area, lat, lon, bio, analogs) for t in targets.targets]
    return pd.concat(parts, ignore_index=True), n_max


def check_scores(sim: pd.DataFrame) -> None:
    bad = [c for c in SCORE_COLUMNS if ((sim[c] < 0) | (sim[c] > 1)).any()]
    if bad:
        raise OutputValidationError(f"puntajes fuera de 0..1 en {bad}")


def main() -> None:
    args = make_parser(STEP, __doc__.splitlines()[0]).parse_args()
    log = setup_logging(STEP)
    started = time.monotonic()

    inputs = [FEATURES_PATH, TARGETS_PATH, GRID_PATH, ANALOGS_IN]
    require_inputs(inputs)
    code = [Path(__file__), ROOT / "pipeline" / "common.py", ROOT / "tai" / "rules.py",
            ROOT / "tai" / "scoring.py", ROOT / "tai" / "constants.py"]
    if (not args.force and is_up_to_date([OUTPUT, ANALOGS_OUT], [*inputs, *code])
            and not last_run_partial(STEP)):
        log.info("al día")
        return

    grid = load_grid()
    features = pd.read_parquet(FEATURES_PATH)
    targets = models.TargetsFile.model_validate_json(TARGETS_PATH.read_text(encoding="utf-8"))
    analogs = load_analogs(target_ids=[t.target_id for t in targets.targets])
    sim, n_max = build_similarity(features, grid, targets, analogs)

    notes = []
    missing = [tid for tid in TARGET_IDS if tid not in {t.target_id for t in targets.targets}]
    if missing:
        notes.append(f"targets.json no trae {missing}: similarity.parquet queda sin esas filas")
        log.warning(notes[-1])
    if n_max == 0:
        notes.append("ninguna celda tiene registros biológicos: bio_score vale 0 en todas")
        log.warning(notes[-1])
    if last_run_partial("06_features"):
        notes.append(f"{PARTIAL_NOTE_PREFIX} features.parquet viene de una corrida parcial")
        log.warning(notes[-1])
    for tid, g in sim.groupby("target_id"):
        line = (f"{tid}: {int(g['eligible'].sum())} celdas elegibles de {len(g)}; "
                f"{int(g['known_analog'].notna().sum())} celdas de análogos conocidos")
        notes.append(line)
        log.info(line)

    validate_output(sim, grid_ids=grid["cell_id"], schema="similarity")
    check_scores(sim)
    analogs_df = pd.DataFrame([a.model_dump() for a in analogs], columns=list(KNOWN_ANALOGS_COLUMNS))
    atomic_write_parquet(sim, OUTPUT)
    atomic_write_csv(analogs_df, ANALOGS_OUT)
    write_step_manifest(
        step_entry(
            STEP,
            started,
            inputs=[{"name": "Variables por celda, perfiles objetivo y análogos conocidos",
                     "product": "features.parquet, targets.json, known_analogs.csv",
                     "portal": "Pipeline del proyecto (pasos 06 y 07; config de TAI-17)",
                     "url": "https://github.com/NASA-spaceapps-sigsegv/terra-analog-index",
                     "files": len(inputs), "size_mb": round(sum(file_size_mb(p) for p in inputs), 1),
                     "license_note": "Datos derivados del proyecto"}],
            outputs=[(OUTPUT, len(sim)), (ANALOGS_OUT, len(analogs_df))],
            columns=column_stats(sim, SCORE_COLUMNS),
            notes=notes,
        )
    )
    log.info("wrote %s (%d rows) and %s (%d analogs)", OUTPUT.name, len(sim), ANALOGS_OUT.name, len(analogs_df))


if __name__ == "__main__":
    run(main)
