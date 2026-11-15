"""Los textos manuales de las finalistas dicen el puntaje total de su celda: tiene que ser el que muestra la app.

Cuando se agregó la dimensión de polvo y viento (TAI-52) los totales de Marte bajaron y dos textos quedaron con la cifra
vieja. Esta prueba lo detecta con los datos reales de data/processed/ y los pesos iniciales.
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
    shown = f"{total:.2f}".replace(".", ",")
    text = path.read_text(encoding="utf-8")
    assert f"{shown}" in text, f"{path.name} no menciona el total actual de la celda ({shown})"
