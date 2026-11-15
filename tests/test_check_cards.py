"""scripts/check_cards.py: el control de los textos manuales que corre `make cards`."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("check_cards", ROOT / "scripts" / "check_cards.py")
check_cards = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_cards)

GOOD = "# Salar de Atacama\n\n" + " ".join(["palabra"] * 180) + " [1].\n\n## Fuentes\n\n1. Autor (2020). Título.\n"


def test_empty_folder_is_ok(tmp_path, capsys):
    assert check_cards.main([str(tmp_path)]) == 0
    assert "no hay textos" in capsys.readouterr().out


def test_good_file_passes(tmp_path, capsys):
    (tmp_path / "23510__mars_jezero.md").write_text(GOOD, encoding="utf-8")
    assert check_cards.main([str(tmp_path)]) == 0
    assert "✓ 23510__mars_jezero.md" in capsys.readouterr().out


def test_bad_file_is_reported_with_every_problem(tmp_path, capsys):
    (tmp_path / "23510__mars_jezero.md").write_text(GOOD, encoding="utf-8")
    (tmp_path / "99999__mars_gale.md").write_text("Sin título.\n", encoding="utf-8")
    assert check_cards.main([str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "✗ 99999__mars_gale.md" in out
    assert "no es un cell_id válido" in out and "no es un objetivo" in out
    assert "título" in out and "Fuentes" in out
    assert "1 de 2 textos en orden" in out


def test_name_without_separator():
    assert check_cards.name_problems(Path("atacama.md"))
