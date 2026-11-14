"""Step 01: global 1-degree land grid and 0.05-degree land mask (design 2.1, RF-01).

Reads:  data/raw/01_grid/ (Natural Earth 1:50m land polygons)
Writes: data/processed/grid.parquet, data/interim/land_mask.nc

Not implemented yet: TAI-11 fills in main().
"""

import sys
from pathlib import Path

# Steps run as `python pipeline/NN_step.py`; put the repo root on the path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.common import (  # noqa: E402
    GRID_PATH,
    LAND_MASK_PATH,
    RAW,
    make_parser,
    run,
    setup_logging,
)

STEP = "01_grid"
INPUTS = [RAW / STEP]
OUTPUTS = [GRID_PATH, LAND_MASK_PATH]


def main() -> None:
    args = make_parser(STEP, __doc__.splitlines()[0]).parse_args()
    log = setup_logging(STEP)
    log.info("args: force=%s bbox=%s", args.force, args.bbox)
    raise NotImplementedError("TAI-11: build the grid and land mask")


if __name__ == "__main__":
    run(main)
