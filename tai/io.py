"""Carga y validación de data/processed/ (design 9.4).

Sin Streamlit, sin red, sin escritura. Todo lo que falla lanza
DataNotAvailableError con el nombre del archivo y el paso que lo genera.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

import pandas as pd

from tai import schemas
from tai.errors import DataNotAvailableError
from tai.models import KnownAnalog, Manifest, TargetsFile, ValidationReport
from tai.schemas import KNOWN_ANALOGS_COLUMNS

# archivo -> paso del pipeline que lo genera
REQUIRED_FILES = MappingProxyType(
    {
        "grid.parquet": "01_grid",
        "features.parquet": "06_features",
        "bio_samples.parquet": "05_biology_ncbi",
        "targets.json": "07_targets",
        "similarity.parquet": "08_similarity",
        "known_analogs.csv": "08_similarity",
        "validation.json": "09_validation",
        "manifest.json": "cualquier paso del pipeline",
    }
)


@dataclass(frozen=True)
class DataBundle:
    """Todo lo que lee la app. No se modifica después de cargarlo."""

    grid: pd.DataFrame  # indexada por cell_id
    features: pd.DataFrame  # indexada por cell_id
    bio_samples: pd.DataFrame
    similarity: Mapping[str, pd.DataFrame]  # target_id -> tabla indexada por cell_id
    targets: TargetsFile
    known_analogs: tuple[KnownAnalog, ...]
    validation: ValidationReport
    manifest: Manifest


def data_signature(path: Path) -> tuple:
    """(archivo, mtime) de cada archivo requerido; None si falta.

    Sirve de clave de caché: si alguien borra o cambia un archivo, la clave
    cambia y la app vuelve a cargar (y a avisar) en vez de usar datos viejos."""
    path = Path(path)
    sig = []
    for name in REQUIRED_FILES:
        f = path / name
        sig.append((name, f.stat().st_mtime_ns if f.exists() else None))
    return tuple(sig)


def _fail(name: str, why: str) -> DataNotAvailableError:
    return DataNotAvailableError(f"{name}: {why}. Lo genera el paso {REQUIRED_FILES[name]}.")


def _require(path: Path, name: str) -> Path:
    f = path / name
    if not f.is_file():
        raise _fail(name, f"no está en {path}")
    return f


def _read_table(path: Path, name: str, schema_name: str) -> pd.DataFrame:
    f = _require(path, name)
    try:
        df = pd.read_parquet(f)
    except Exception as exc:  # archivo corrupto, formato inesperado
        raise _fail(name, f"no se pudo leer ({exc})") from exc
    problems = schemas.check_schema(df, schema_name)
    if problems:
        raise _fail(name, "no cumple su contrato (" + "; ".join(problems) + ")")
    return df


def _read_json(path: Path, name: str, model):
    f = _require(path, name)
    try:
        return model.model_validate(json.loads(f.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:  # JSONDecodeError y ValidationError son ValueError
        raise _fail(name, f"no valida contra su modelo ({exc})") from exc


def _read_known_analogs(path: Path) -> tuple[KnownAnalog, ...]:
    name = "known_analogs.csv"
    f = _require(path, name)
    try:
        df = pd.read_csv(f)
        if tuple(df.columns) != KNOWN_ANALOGS_COLUMNS:
            raise ValueError(f"columnas {list(df.columns)}, se esperaban {list(KNOWN_ANALOGS_COLUMNS)}")
        return tuple(KnownAnalog.model_validate(r) for r in df.to_dict(orient="records"))
    except (OSError, ValueError) as exc:
        raise _fail(name, f"no es válido ({exc})") from exc


def load_bundle(path: Path | str) -> DataBundle:
    """Lee los 8 archivos de `path`, los valida y arma el DataBundle."""
    path = Path(path)
    grid = _read_table(path, "grid.parquet", "grid")
    features = _read_table(path, "features.parquet", "features")
    bio = _read_table(path, "bio_samples.parquet", "bio_samples")
    sim = _read_table(path, "similarity.parquet", "similarity")
    targets = _read_json(path, "targets.json", TargetsFile)
    analogs = _read_known_analogs(path)
    validation = _read_json(path, "validation.json", ValidationReport)
    manifest = _read_json(path, "manifest.json", Manifest)

    # Una fila por celda y objetivo (la unicidad de la clave ya la comprobó check_schema).
    target_ids = [t.target_id for t in targets.targets]
    if set(sim["target_id"]) != set(target_ids):
        raise _fail("similarity.parquet", f"los objetivos {sorted(set(sim['target_id']))} no coinciden con targets.json {sorted(target_ids)}")
    if not set(sim["cell_id"]) <= set(grid["cell_id"]):
        raise _fail("similarity.parquet", "hay cell_id que no están en grid.parquet")
    if len(sim) != len(grid) * len(target_ids):
        raise _fail("similarity.parquet", f"tiene {len(sim)} filas y debería tener {len(grid) * len(target_ids)} (una por celda y objetivo)")

    by_target = {t: sim[sim["target_id"] == t].set_index("cell_id") for t in target_ids}
    return DataBundle(
        grid=grid.set_index("cell_id"),
        features=features.set_index("cell_id"),
        bio_samples=bio,
        similarity=MappingProxyType(by_target),
        targets=targets,
        known_analogs=analogs,
        validation=validation,
        manifest=manifest,
    )
