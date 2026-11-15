"""scripts/check_cards.py: the manual-text check that `make cards` runs."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("check_cards", ROOT / "scripts" / "check_cards.py")
check_cards = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_cards)

GOOD = "# Salar de Atacama\n\n" + " ".join(["word"] * 180) + " [1].\n\n## Sources\n\n1. Author (2020). Title.\n"


def test_empty_folder_is_ok(tmp_path, capsys):
    assert check_cards.main([str(tmp_path)]) == 0
    assert "there are no texts" in capsys.readouterr().out


def test_good_file_passes(tmp_path, capsys):
    (tmp_path / "23510__mars_jezero.md").write_text(GOOD, encoding="utf-8")
    assert check_cards.main([str(tmp_path)]) == 0
    assert "✓ 23510__mars_jezero.md" in capsys.readouterr().out


def test_bad_file_is_reported_with_every_problem(tmp_path, capsys):
    (tmp_path / "23510__mars_jezero.md").write_text(GOOD, encoding="utf-8")
    (tmp_path / "99999__mars_gale.md").write_text("No title.\n", encoding="utf-8")
    assert check_cards.main([str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "✗ 99999__mars_gale.md" in out
    assert "is not a valid cell_id" in out and "is not a target" in out
    assert "title" in out and "Sources" in out
    assert "1 of 2 texts in order" in out


def test_name_without_separator():
    assert check_cards.name_problems(Path("atacama.md"))
