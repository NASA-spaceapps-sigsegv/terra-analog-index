"""Revisa los textos manuales de las fichas (content/cards/, contracts 7.4).

Para cada archivo .md dice qué le falta, en castellano llano: nombre <cell_id>__<target_id>.md,
título "# ...", entre 150 y 250 palabras y una sección final "## Fuentes" con al menos un ítem.
Usa las mismas reglas que la app (tai.cards) y que tests/test_cards.py.

    python scripts/check_cards.py            # content/cards/
    python scripts/check_cards.py otra/carpeta

Sale con código 1 si algún archivo tiene problemas.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # para importar tai sin instalarlo

from tai.cards import CARDS_DIR, manual_problems  # noqa: E402
from tai.constants import N_CELLS_GLOBAL, TARGET_IDS  # noqa: E402


def name_problems(path: Path) -> list[str]:
    """Lo que está mal en el nombre del archivo; vacía si está bien."""
    if "__" not in path.stem:
        return ["el nombre debe ser <cell_id>__<target_id>.md, por ejemplo 23510__mars_jezero.md"]
    cell, target = path.stem.split("__", 1)
    problems = []
    if not cell.isdigit() or not 0 <= int(cell) < N_CELLS_GLOBAL:
        problems.append(f"{cell!r} no es un cell_id válido (0 a {N_CELLS_GLOBAL - 1})")
    if target not in TARGET_IDS:
        problems.append(f"{target!r} no es un objetivo; tiene que ser uno de {', '.join(TARGET_IDS)}")
    return problems


def check_folder(folder: Path) -> dict[str, list[str]]:
    """Archivo -> problemas, solo para los archivos con problemas."""
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
        print(f"{folder}: no hay textos todavía.")
        return 0
    report = check_folder(folder)
    for path in files:
        if path.name in report:
            print(f"✗ {path.name}")
            for p in report[path.name]:
                print(f"    - {p}")
        else:
            print(f"✓ {path.name}")
    print(f"\n{len(files) - len(report)} de {len(files)} textos en orden.")
    return 1 if report else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
