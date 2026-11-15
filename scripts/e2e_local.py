"""Prueba de punta a punta, parte local (TAI-38, lista 12.3 del diseño), con los datos reales de data/processed/.

Recorre con AppTest lo que se puede comprobar sin abrir un navegador: cambiar de objetivo, los sliders, los pesos en 0,
"Ocultar análogos conocidos", las tres vistas del mapa, los textos manuales de content/cards/, la aclaración de muestreo
y la tabla de validación de la pestaña Método. Lo que depende del navegador o de la red (tiempo de carga, pantallas,
proyector, wifi apagado) está en docs/prueba_punta_a_punta.md.

    python scripts/e2e_local.py

Sale con código 1 si algo falla. Conviene correrlo después de cada cambio que toque la app o los datos.
"""

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.pop("TAI_DATA_DIR", None)  # siempre los datos reales

import pandas as pd  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

from tai import io, services  # noqa: E402
from tai.constants import DEFAULT_WEIGHTS, DIMENSIONS, TARGET_IDS  # noqa: E402
from ui.ranking_view import SELECTED_KEY  # noqa: E402

APP = str(ROOT / "streamlit_app.py")
SLIDER_LIMIT_S = 1.0
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(("OK    " if ok else "FALLA "), name, "|", detail, flush=True)


def fresh() -> AppTest:
    return AppTest.from_file(APP, default_timeout=60).run()


def page_text(app: AppTest) -> str:
    parts = [m.value for m in app.markdown] + [c.value for c in app.caption] + [i.value for i in app.info]
    parts += [w.value for w in app.warning] + [e.value for e in app.error] + [s.value for s in app.success]
    return "\n".join(parts)


def finalists() -> list[tuple[int, str]]:
    """Las finalistas son los archivos <cell_id>__<target_id>.md de content/cards/."""
    out = []
    for path in sorted((ROOT / "content" / "cards").glob("*.md")):
        cell, target = path.stem.split("__", 1)
        out.append((int(cell), target))
    return out


def main() -> int:
    bundle = io.load_bundle(ROOT / "data" / "processed")
    first, second = TARGET_IDS[0], TARGET_IDS[1]

    # 2. Cambiar de objetivo cambia el ranking y limpia la ficha
    top = {t: services.get_ranking(bundle, t, DEFAULT_WEIGHTS).items[0].cell_id for t in TARGET_IDS}
    app = fresh()
    app.session_state[SELECTED_KEY] = top[first]
    app.run()
    app.sidebar.radio(key="target_id").set_value(second).run()
    cleared = "Elegí una fila del ranking para ver su ficha." in page_text(app)
    check("2. Cambiar de objetivo limpia la ficha", cleared and not app.exception, "")
    check("2. Cambiar de objetivo cambia el ranking", top[first] != top[second], f"{first}: {top[first]}, {second}: {top[second]}")

    # 3. Cada slider recalcula en menos de 1 s (el servidor; el navegador se mide aparte)
    app = fresh()
    times = []
    for dim, value in zip(DIMENSIONS, (0.4, 0.2, 0.7, 1.0)):
        t0 = time.perf_counter()
        app.sidebar.slider(key=f"w_{dim}").set_value(value).run()
        times.append(time.perf_counter() - t0)
    check("3. Cada slider recalcula en el servidor en menos de 1 s", max(times) < SLIDER_LIMIT_S, ", ".join(f"{x * 1000:.0f} ms" for x in times))

    # 4. Todos los pesos en 0 muestran el aviso, sin error
    app = fresh()
    for dim in DIMENSIONS:
        app.sidebar.slider(key=f"w_{dim}").set_value(0.0)
    app.run()
    warned = any("Subí al menos un peso" in w.value for w in app.warning)
    check("4. Pesos en 0: aviso y sin error", warned and not app.exception and not app.error, f"aviso: {warned}")

    # 5. "Ocultar análogos conocidos" los quita del ranking
    cells = services.get_map_layer(bundle, second, DEFAULT_WEIGHTS).cells
    known = {int(c) for c, a in zip(cells["cell_id"], cells["known_analog"]) if pd.notna(a)}
    shown = {i.cell_id for i in services.get_ranking(bundle, second, DEFAULT_WEIGHTS, limit=100).items}
    hidden = {i.cell_id for i in services.get_ranking(bundle, second, DEFAULT_WEIGHTS, hide_known=True, limit=100).items}
    check("5. Ocultar análogos conocidos los quita del ranking", bool(known & shown) and not (known & hidden),
          f"en el top 100: {len(known & shown)} sin ocultar, {len(known & hidden)} ocultando")
    app = fresh()
    app.sidebar.checkbox(key="hide_known").set_value(True).run()
    check("5. La app corre con la casilla marcada", not app.exception, "")

    # 6. Las tres vistas del mapa
    for view in ("world", "south_pole", "north_pole"):
        app = fresh()
        app.sidebar.radio(key="projection").set_value(view).run()
        check(f"6. Vista {view}", not app.exception and len(app.get("plotly_chart")) == 1, "")

    # 7. Las finalistas muestran su texto manual y sus fuentes
    pending = finalists()
    check("7. Hay al menos 3 finalistas en content/cards/", len(pending) >= 3, f"{len(pending)} archivos")
    for cell, target in pending:
        card = services.get_site_card(bundle, cell, target, DEFAULT_WEIGHTS)
        app = fresh()
        app.sidebar.radio(key="target_id").set_value(target).run()  # primero el objetivo: cambiarlo limpia la selección
        app.session_state[SELECTED_KEY] = cell
        app.run()
        text = page_text(app)
        ok = bool(card.manual) and card.manual.title in text and "Fuentes" in text and not app.exception
        check(f"7. Finalista {cell} ({target}): texto manual y fuentes", ok, card.manual.title if card.manual else "sin texto manual")

    # 8. Una celda sin registros biológicos muestra la aclaración de muestreo
    empty = next(
        (i.cell_id for i in services.get_ranking(bundle, first, DEFAULT_WEIGHTS).items
         if services.get_site_card(bundle, i.cell_id, first, DEFAULT_WEIGHTS).biology.records == 0),
        None,
    )
    app = fresh()
    app.session_state[SELECTED_KEY] = empty
    app.run()
    note = "La falta de registros puede deberse a que nadie tomó muestras acá" in page_text(app)
    check("8. Celda sin registros: aclaración de muestreo", empty is not None and note and not app.exception, f"celda {empty}")

    # 9. La pestaña Método muestra la tabla de validación
    app = fresh()
    tables = [d.value for d in app.dataframe if "Análogo" in d.value.columns]
    expected = sum(len(t.analogs) for t in bundle.validation.targets)
    shown_rows = sum(len(t) for t in tables)
    check("9. Método: una tabla de validación por objetivo", len(tables) == len(bundle.validation.targets) and shown_rows == expected,
          f"{len(tables)} tablas, {shown_rows} de {expected} análogos")
    results = {r for t in tables for r in t["Resultado"]}
    expected_results = {a.result for t in bundle.validation.targets for a in t.analogs}
    check("9. Método: muestra pass, fail e info como en validation.json", results == expected_results, str(sorted(results)))

    failed = [n for n, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)} de {len(RESULTS)} comprobaciones en orden.")
    if failed:
        print("Fallan:", *failed, sep="\n  ")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
