"""End-to-end test, local part (TAI-38, design list 12.3), with the real data in data/processed/.

It walks through with AppTest what can be checked without opening a browser: switching target, the sliders, weights at 0,
"Hide known analogs", the three map views, the manual texts in content/cards/, the sampling note and the
validation table in the Method tab. What depends on the browser or the network (load time, screens, projector,
wifi off) is in docs/end_to_end_test.md.

    python scripts/e2e_local.py

Exits with code 1 if something fails. Worth running after every change that touches the app or the data.
"""

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.pop("TAI_DATA_DIR", None)  # always the real data

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
    print(("OK    " if ok else "FAIL  "), name, "|", detail, flush=True)


def fresh() -> AppTest:
    return AppTest.from_file(APP, default_timeout=60).run()


def page_text(app: AppTest) -> str:
    parts = [m.value for m in app.markdown] + [c.value for c in app.caption] + [i.value for i in app.info]
    parts += [w.value for w in app.warning] + [e.value for e in app.error] + [s.value for s in app.success]
    return "\n".join(parts)


def finalists() -> list[tuple[int, str]]:
    """The finalists are the <cell_id>__<target_id>.md files in content/cards/."""
    out = []
    for path in sorted((ROOT / "content" / "cards").glob("*.md")):
        cell, target = path.stem.split("__", 1)
        out.append((int(cell), target))
    return out


def main() -> int:
    bundle = io.load_bundle(ROOT / "data" / "processed")
    first, second = TARGET_IDS[0], TARGET_IDS[1]

    # 2. Switching target changes the ranking and clears the card
    top = {t: services.get_ranking(bundle, t, DEFAULT_WEIGHTS).items[0].cell_id for t in TARGET_IDS}
    app = fresh()
    app.session_state[SELECTED_KEY] = top[first]
    app.run()
    app.sidebar.radio(key="target_id").set_value(second).run()
    cleared = "Pick a row in the ranking to see its card." in page_text(app)
    check("2. Switching target clears the card", cleared and not app.exception, "")
    check("2. Switching target changes the ranking", top[first] != top[second], f"{first}: {top[first]}, {second}: {top[second]}")

    # 3. Each slider recomputes in under 1 s (the server; the browser is measured separately)
    app = fresh()
    times = []
    for dim, value in zip(DIMENSIONS, (0.4, 0.2, 0.7, 1.0)):
        t0 = time.perf_counter()
        app.sidebar.slider(key=f"w_{dim}").set_value(value).run()
        times.append(time.perf_counter() - t0)
    check("3. Each slider recomputes on the server in under 1 s", max(times) < SLIDER_LIMIT_S, ", ".join(f"{x * 1000:.0f} ms" for x in times))

    # 4. All weights at 0 show the warning, without an error
    app = fresh()
    for dim in DIMENSIONS:
        app.sidebar.slider(key=f"w_{dim}").set_value(0.0)
    app.run()
    warned = any("Raise at least one weight" in w.value for w in app.warning)
    check("4. Weights at 0: warning and no error", warned and not app.exception and not app.error, f"warning: {warned}")

    # 5. "Hide known analogs" removes them from the ranking
    cells = services.get_map_layer(bundle, second, DEFAULT_WEIGHTS).cells
    known = {int(c) for c, a in zip(cells["cell_id"], cells["known_analog"]) if pd.notna(a)}
    shown = {i.cell_id for i in services.get_ranking(bundle, second, DEFAULT_WEIGHTS, limit=100).items}
    hidden = {i.cell_id for i in services.get_ranking(bundle, second, DEFAULT_WEIGHTS, hide_known=True, limit=100).items}
    check("5. Hide known analogs removes them from the ranking", bool(known & shown) and not (known & hidden),
          f"in the top 100: {len(known & shown)} not hiding, {len(known & hidden)} hiding")
    app = fresh()
    app.sidebar.checkbox(key="hide_known").set_value(True).run()
    check("5. The app runs with the box checked", not app.exception, "")

    # 6. The three map views
    for view in ("world", "south_pole", "north_pole"):
        app = fresh()
        app.sidebar.radio(key="projection").set_value(view).run()
        check(f"6. View {view}", not app.exception and len(app.get("plotly_chart")) == 1, "")

    # 7. The finalists show their manual text and their sources
    pending = finalists()
    check("7. There are at least 3 finalists in content/cards/", len(pending) >= 3, f"{len(pending)} files")
    for cell, target in pending:
        card = services.get_site_card(bundle, cell, target, DEFAULT_WEIGHTS)
        app = fresh()
        app.sidebar.radio(key="target_id").set_value(target).run()  # target first: changing it clears the selection
        app.session_state[SELECTED_KEY] = cell
        app.run()
        text = page_text(app)
        ok = bool(card.manual) and card.manual.title in text and "Sources" in text and not app.exception
        check(f"7. Finalist {cell} ({target}): manual text and sources", ok, card.manual.title if card.manual else "no manual text")

    # 8. A cell without biological records shows the sampling note
    empty = next(
        (i.cell_id for i in services.get_ranking(bundle, first, DEFAULT_WEIGHTS).items
         if services.get_site_card(bundle, i.cell_id, first, DEFAULT_WEIGHTS).biology.records == 0),
        None,
    )
    app = fresh()
    app.session_state[SELECTED_KEY] = empty
    app.run()
    note = "A lack of records may mean nobody sampled here" in page_text(app)
    check("8. Cell without records: sampling note", empty is not None and note and not app.exception, f"cell {empty}")

    # 9. The Method tab shows the validation table
    app = fresh()
    tables = [d.value for d in app.dataframe if "Analog" in d.value.columns]
    expected = sum(len(t.analogs) for t in bundle.validation.targets)
    shown_rows = sum(len(t) for t in tables)
    check("9. Method: one validation table per target", len(tables) == len(bundle.validation.targets) and shown_rows == expected,
          f"{len(tables)} tables, {shown_rows} of {expected} analogs")
    results = {r for t in tables for r in t["Result"]}
    expected_results = {a.result for t in bundle.validation.targets for a in t.analogs}
    check("9. Method: shows pass, fail and info as in validation.json", results == expected_results, str(sorted(results)))

    failed = [n for n, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)} of {len(RESULTS)} checks in order.")
    if failed:
        print("Failing:", *failed, sep="\n  ")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
