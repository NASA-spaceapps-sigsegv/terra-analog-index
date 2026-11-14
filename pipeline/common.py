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
import logging
import sys
from collections.abc import Iterable
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
