"""Loading and validation of data/processed/ (design 9.4).

No Streamlit, no network, no writing. Anything that fails raises
DataNotAvailableError with the file name and the step that produces it.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

import pandas as pd

from tai import schemas
from tai.errors import DataNotAvailableError
from tai.models import Cave, KnownAnalog, Manifest, TargetsFile, ValidationReport
from tai.schemas import CAVES_COLUMNS, KNOWN_ANALOGS_COLUMNS

# file -> pipeline step that produces it
REQUIRED_FILES = MappingProxyType(
    {
        "grid.parquet": "01_grid",
        "features.parquet": "06_features",
        "bio_samples.parquet": "05_biology_ncbi",
        "targets.json": "07_targets",
        "similarity.parquet": "08_similarity",
        "known_analogs.csv": "08_similarity",
        "caves.csv": "08_similarity",
        "validation.json": "09_validation",
        "manifest.json": "any pipeline step",
    }
)


@dataclass(frozen=True)
class DataBundle:
    """Everything the app reads. It is not modified after loading."""

    grid: pd.DataFrame  # indexed by cell_id
    features: pd.DataFrame  # indexed by cell_id
    bio_samples: pd.DataFrame
    similarity: Mapping[str, pd.DataFrame]  # target_id -> table indexed by cell_id
    targets: TargetsFile
    known_analogs: tuple[KnownAnalog, ...]
    caves: tuple[Cave, ...]  # informational map layer (TAI-53)
    validation: ValidationReport
    manifest: Manifest


def data_signature(path: Path) -> tuple:
    """(file, mtime) of each required file; None if missing.

    Used as a cache key: if someone deletes or changes a file, the key
    changes and the app reloads (and warns) instead of using stale data."""
    path = Path(path)
    sig = []
    for name in REQUIRED_FILES:
        f = path / name
        sig.append((name, f.stat().st_mtime_ns if f.exists() else None))
    return tuple(sig)


def _fail(name: str, why: str) -> DataNotAvailableError:
    return DataNotAvailableError(f"{name}: {why}. It is produced by step {REQUIRED_FILES[name]}.")


def _require(path: Path, name: str) -> Path:
    f = path / name
    if not f.is_file():
        raise _fail(name, f"not found in {path}")
    return f


def _read_table(path: Path, name: str, schema_name: str) -> pd.DataFrame:
    f = _require(path, name)
    try:
        df = pd.read_parquet(f)
    except Exception as exc:  # corrupt file, unexpected format
        raise _fail(name, f"could not be read ({exc})") from exc
    problems = schemas.check_schema(df, schema_name)
    if problems:
        raise _fail(name, "does not meet its contract (" + "; ".join(problems) + ")")
    return df


def _read_json(path: Path, name: str, model):
    f = _require(path, name)
    try:
        return model.model_validate(json.loads(f.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:  # JSONDecodeError and ValidationError are ValueError
        raise _fail(name, f"does not validate against its model ({exc})") from exc


def _read_csv_rows(path: Path, name: str, columns: tuple[str, ...], model) -> tuple:
    """Rows of a config CSV already validated by step 08, one per instance of `model`."""
    f = _require(path, name)
    try:
        df = pd.read_csv(f)
        if tuple(df.columns) != columns:
            raise ValueError(f"columns {list(df.columns)}, expected {list(columns)}")
        return tuple(model.model_validate(r) for r in df.to_dict(orient="records"))
    except (OSError, ValueError) as exc:
        raise _fail(name, f"is not valid ({exc})") from exc


def _read_known_analogs(path: Path) -> tuple[KnownAnalog, ...]:
    return _read_csv_rows(path, "known_analogs.csv", KNOWN_ANALOGS_COLUMNS, KnownAnalog)


def load_bundle(path: Path | str) -> DataBundle:
    """Read the 9 files in `path`, validate them and build the DataBundle."""
    path = Path(path)
    grid = _read_table(path, "grid.parquet", "grid")
    features = _read_table(path, "features.parquet", "features")
    bio = _read_table(path, "bio_samples.parquet", "bio_samples")
    sim = _read_table(path, "similarity.parquet", "similarity")
    targets = _read_json(path, "targets.json", TargetsFile)
    analogs = _read_known_analogs(path)
    caves = _read_csv_rows(path, "caves.csv", CAVES_COLUMNS, Cave)
    validation = _read_json(path, "validation.json", ValidationReport)
    manifest = _read_json(path, "manifest.json", Manifest)

    # One row per cell and target (check_schema already checked that the key is unique).
    target_ids = [t.target_id for t in targets.targets]
    if set(sim["target_id"]) != set(target_ids):
        raise _fail("similarity.parquet", f"the targets {sorted(set(sim['target_id']))} do not match targets.json {sorted(target_ids)}")
    if not set(sim["cell_id"]) <= set(grid["cell_id"]):
        raise _fail("similarity.parquet", "there are cell_ids that are not in grid.parquet")
    if len(sim) != len(grid) * len(target_ids):
        raise _fail("similarity.parquet", f"has {len(sim)} rows and should have {len(grid) * len(target_ids)} (one per cell and target)")

    by_target = {t: sim[sim["target_id"] == t].set_index("cell_id") for t in target_ids}
    return DataBundle(
        grid=grid.set_index("cell_id"),
        features=features.set_index("cell_id"),
        bio_samples=bio,
        similarity=MappingProxyType(by_target),
        targets=targets,
        known_analogs=analogs,
        caves=caves,
        validation=validation,
        manifest=manifest,
    )
