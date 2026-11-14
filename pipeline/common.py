"""Shared helpers for the pipeline steps (design 6.2 to 6.4).

Every step script follows the same shape:

    args = make_parser("02_terrain", __doc__).parse_args()
    log = setup_logging("02_terrain")
    if not args.force and is_up_to_date(outputs, inputs + [Path(__file__)]):
        log.info("al día"); sys.exit(EXIT_OK)
    ...
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

# --- Paths -------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"
CONTENT = ROOT / "content"
DATA = ROOT / "data"
RAW = DATA / "raw"
INTERIM = DATA / "interim"
PROCESSED = DATA / "processed"

GRID_PATH = PROCESSED / "grid.parquet"
LAND_MASK_PATH = INTERIM / "land_mask.nc"
MANIFEST_PATH = PROCESSED / "manifest.json"

# --- Exit codes (design 6.2) -------------------------------------------------
EXIT_OK = 0  # done, or already up to date
EXIT_INVALID_OUTPUT = 1  # output failed validation; nothing written
EXIT_MISSING_INPUT = 2  # a required input is missing


class MissingInputError(Exception):
    """A required input file does not exist."""


class OutputValidationError(Exception):
    """A step's output broke its contract (ranges, keys, schema)."""


# --- CLI ---------------------------------------------------------------------


def make_parser(step: str, description: str | None = None) -> argparse.ArgumentParser:
    """Parser with the arguments every step accepts: --force and --bbox."""
    parser = argparse.ArgumentParser(prog=f"{step}.py", description=description)
    parser.add_argument(
        "--force",
        action="store_true",
        help="run even if the output is newer than every input",
    )
    parser.add_argument(
        "--bbox",
        nargs=4,
        type=float,
        metavar=("LAT_MIN", "LAT_MAX", "LON_MIN", "LON_MAX"),
        help="limit computation to a region for quick tests; cells outside stay null",
    )
    return parser


def bbox_mask(lat: pd.Series, lon: pd.Series, bbox: Iterable[float] | None) -> pd.Series:
    """Boolean mask of points inside bbox (all True when bbox is None)."""
    if bbox is None:
        return pd.Series(True, index=lat.index)
    lat_min, lat_max, lon_min, lon_max = bbox
    if lat_min >= lat_max or lon_min >= lon_max:
        raise ValueError("bbox must satisfy LAT_MIN < LAT_MAX and LON_MIN < LON_MAX")
    return lat.between(lat_min, lat_max) & lon.between(lon_min, lon_max)


def setup_logging(step: str, level: int = logging.INFO) -> logging.Logger:
    """One line per stage, prefixed with time and step name."""
    logging.basicConfig(
        level=level,
        format=f"%(asctime)s {step} %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
        force=True,
    )
    return logging.getLogger(step)


# --- Inputs and freshness ----------------------------------------------------


def require_inputs(paths: Iterable[Path]) -> None:
    """Raise MissingInputError listing every input that does not exist."""
    missing = [str(p) for p in paths if not Path(p).exists()]
    if missing:
        raise MissingInputError("missing inputs: " + ", ".join(missing))


def _mtime(path: Path) -> float:
    path = Path(path)
    if path.is_dir():
        times = [p.stat().st_mtime for p in path.rglob("*") if p.is_file()]
        return max(times, default=path.stat().st_mtime)
    return path.stat().st_mtime


def is_up_to_date(outputs: Iterable[Path], inputs: Iterable[Path]) -> bool:
    """True if every output exists and is newer than every input.

    Pass the step script itself among the inputs so that editing the code
    invalidates the output. Directories count by their newest file.
    """
    outputs = [Path(p) for p in outputs]
    inputs = [Path(p) for p in inputs]
    if not outputs or not all(p.exists() for p in outputs):
        return False
    existing_inputs = [p for p in inputs if p.exists()]
    if not existing_inputs:
        return True
    oldest_output = min(_mtime(p) for p in outputs)
    newest_input = max(_mtime(p) for p in existing_inputs)
    return oldest_output > newest_input


def load_grid(path: Path = GRID_PATH) -> pd.DataFrame:
    """Read grid.parquet (output of step 01)."""
    require_inputs([path])
    return pd.read_parquet(path)


# --- Atomic writes (design 6.2) ----------------------------------------------


def _atomic_replace(path: Path, write) -> None:
    """Write via `write(tmp_path)` then rename, so a crash never leaves half a file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        write(tmp)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def atomic_write_parquet(df: pd.DataFrame, path: Path) -> None:
    _atomic_replace(path, lambda tmp: df.to_parquet(tmp, index=False))


def atomic_write_json(obj, path: Path) -> None:
    """Strict JSON: NaN/Infinity raise instead of being written (contracts 1)."""
    text = json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    _atomic_replace(path, lambda tmp: tmp.write_text(text, encoding="utf-8"))


def atomic_write_netcdf(ds, path: Path) -> None:
    _atomic_replace(path, lambda tmp: ds.to_netcdf(tmp))


# --- Manifest (design 6.4, contracts 6.2) ------------------------------------


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def file_size_mb(path: Path) -> float:
    path = Path(path)
    if path.is_dir():
        size = sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    else:
        size = path.stat().st_size
    return round(size / 1e6, 1)


def git_commit() -> str | None:
    """Short hash of HEAD, or None outside a git checkout."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def _num(x) -> float | None:
    if x is None or pd.isna(x):
        return None
    return round(float(x), 3)


def column_stats(df: pd.DataFrame, columns: Iterable[str]) -> dict:
    """non_null / null / min / max per column, as in the manifest contract."""
    stats = {}
    for col in columns:
        s = df[col]
        numeric = pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s)
        stats[col] = {
            "non_null": int(s.notna().sum()),
            "null": int(s.isna().sum()),
            "min": _num(s.min()) if numeric else None,
            "max": _num(s.max()) if numeric else None,
        }
    return stats


def step_entry(
    step: str,
    started: float,
    inputs: list[dict],
    outputs: list[tuple[Path, int]],
    columns: dict | None = None,
    notes: list[str] | None = None,
    earth_stats: dict | None = None,
) -> dict:
    """Build one manifest step entry.

    `started` is a time.monotonic() value taken when the step began.
    `inputs` are dicts with name, product, portal, url, files, size_mb, license_note.
    `outputs` are (path, rows) pairs; size is read from disk.
    """
    return {
        "step": step,
        "ran_at": utc_now_iso(),
        "duration_s": round(time.monotonic() - started, 1),
        "git_commit": git_commit(),
        "inputs": inputs,
        "outputs": [
            {
                "path": Path(p).resolve().relative_to(ROOT).as_posix(),
                "rows": int(rows),
                "size_mb": file_size_mb(p),
            }
            for p, rows in outputs
        ],
        "columns": columns or {},
        "earth_stats": earth_stats,
        "notes": notes or [],
    }


def write_step_manifest(entry: dict, grid: dict | None = None, path: Path = MANIFEST_PATH) -> None:
    """Insert or replace this step's entry in manifest.json (one entry per step).

    `grid` ({res_deg, n_cells, land_frac_min}) is set by step 01 only.
    The result is validated against tai.models.Manifest before writing.
    """
    from tai.constants import DATA_YEAR, SCHEMA_VERSION
    from tai.models import Manifest

    path = Path(path)
    if path.exists():
        manifest = json.loads(path.read_text(encoding="utf-8"))
    else:
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "project": "terra-analog-index",
            "data_year": DATA_YEAR,
            "grid": None,
            "steps": [],
        }
    if grid is not None:
        manifest["grid"] = grid
    steps = [s for s in manifest["steps"] if s["step"] != entry["step"]]
    steps.append(entry)
    manifest["steps"] = sorted(steps, key=lambda s: s["step"])
    Manifest.model_validate(manifest)
    atomic_write_json(manifest, path)
