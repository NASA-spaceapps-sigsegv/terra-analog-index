"""The finalists' manual texts state their cell's total score: it has to be the one the app shows.

When the dust and wind dimension was added (TAI-52) the Mars totals dropped and two texts kept the old
figure. This test catches that with the real data in data/processed/ and the default weights.
"""

from pathlib import Path

import pytest

from tai import io, services
from tai.constants import DEFAULT_WEIGHTS

ROOT = Path(__file__).resolve().parents[1]
CARDS = sorted((ROOT / "content" / "cards").glob("*.md"))


@pytest.fixture(scope="module")
def real_bundle():
    return io.load_bundle(ROOT / "data" / "processed")


@pytest.mark.parametrize("path", CARDS, ids=lambda p: p.name)
def test_the_total_in_each_finalist_text_is_the_one_in_the_app(real_bundle, path):
    cell, target = path.stem.split("__", 1)
    total = services.get_site_card(real_bundle, int(cell), target, DEFAULT_WEIGHTS).scores.total
    shown = f"{total:.2f}"
    text = path.read_text(encoding="utf-8")
    assert f"{shown}" in text, f"{path.name} does not mention the current total of the cell ({shown})"
