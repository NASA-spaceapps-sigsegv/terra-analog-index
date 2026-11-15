"""Check the manual texts of the cards (content/cards/, contracts 7.4).

For each .md file it says what is missing, in plain English: name <cell_id>__<target_id>.md,
title "# ...", between 150 and 250 words and a final "## Sources" section with at least one item.
It uses the same rules as the app (tai.cards) and tests/test_cards.py.

    python scripts/check_cards.py            # content/cards/
    python scripts/check_cards.py other/folder

Exits with code 1 if any file has problems.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # to import tai without installing it

from tai.cards import CARDS_DIR, manual_problems  # noqa: E402
from tai.constants import N_CELLS_GLOBAL, TARGET_IDS  # noqa: E402


def name_problems(path: Path) -> list[str]:
    """What is wrong with the file name; empty if it is fine."""
    if "__" not in path.stem:
        return ["the name must be <cell_id>__<target_id>.md, for example 23510__mars_jezero.md"]
    cell, target = path.stem.split("__", 1)
    problems = []
    if not cell.isdigit() or not 0 <= int(cell) < N_CELLS_GLOBAL:
        problems.append(f"{cell!r} is not a valid cell_id (0 to {N_CELLS_GLOBAL - 1})")
    if target not in TARGET_IDS:
        problems.append(f"{target!r} is not a target; it must be one of {', '.join(TARGET_IDS)}")
    return problems


def check_folder(folder: Path) -> dict[str, list[str]]:
    """File -> problems, only for the files with problems."""
    report = {}
    for path in sorted(folder.glob("*.md")):
        problems = name_problems(path) + manual_problems(path.read_text(encoding="utf-8"))
        if problems:
            report[path.name] = problems
    return report


def main(argv: list[str]) -> int:
    folder = Path(argv[0]) if argv else ROOT / CARDS_DIR
    files = sorted(folder.glob("*.md"))
    if not files:
        print(f"{folder}: there are no texts yet.")
        return 0
    report = check_folder(folder)
    for path in files:
        if path.name in report:
            print(f"✗ {path.name}")
            for p in report[path.name]:
                print(f"    - {p}")
        else:
            print(f"✓ {path.name}")
    print(f"\n{len(files) - len(report)} of {len(files)} texts in order.")
    return 1 if report else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
