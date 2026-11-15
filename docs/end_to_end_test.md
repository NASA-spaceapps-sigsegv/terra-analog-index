# End-to-end test (TAI-38), local part

Design list 12.3, walked through on November 15, 2026 on `develop` at commit `7da9f8d`, with the real data in
`data/processed/`. Test machine: Windows 10, Python 3.13, Streamlit 1.67.0, Microsoft Edge in a private window
(headless, 1500 × 1000 except where noted).

**Result: all 11 items pass locally and no failure that blocks the demo showed up.** Three things can only be checked
with the deployed app or on the presentation laptop (last column), and there are four non-blocking observations.

The app's interface was in Spanish when this test was run; the quoted labels below are given with their current English
text.

| # | Item | Result | How it was checked | Pending |
|---|------|--------|--------------------|---------|
| 1 | The app opens in a private window in under 10 s | Pass | 2.5 s until the map appears with the server running; 3.3 s with a freshly started server, which also takes 1.7 s to respond | With the deployed link, and with the app "asleep" (design risk 12) |
| 2 | Switching target changes the map and ranking and clears the card | Pass | AppTest: the ranking's first cell changes and the "Pick a row…" hint comes back. In the browser: 325 to 330 ms from the click to the new map | |
| 3 | Each slider recomputes in under 1 s | Pass | AppTest: 219 to 231 ms per recompute on the server. In the browser, the heaviest case (switching target, which redraws the whole map) takes 0.33 s end to end | With the deployed link (network latency). Dragging a real slider in the browser was not automated |
| 4 | All weights at 0 show the warning, without an error | Pass | AppTest: "Raise at least one weight" appears, with no exceptions | See it once by hand in the browser |
| 5 | "Hide known analogs" removes them from the ranking | Pass | In the Mars ranking, 4 of the top 100 cells were known analogs; with the box checked, none | |
| 6 | The three map views work; "South pole" shows all of Antarctica | Pass | All three are drawn without exceptions. The "South pole" screenshot shows the whole of Antarctica | |
| 7 | The 3 finalists show their manual text and their sources | Pass | 61661 (Moon), 46351 and 25671 (Mars): title, text and "Sources" section in the card | |
| 8 | A cell without biological records shows the sampling note | Pass | Cell 6467: "A lack of records may mean nobody sampled here…" appears | |
| 9 | The Method tab shows the validation table | Pass | Two tables, 9 of 9 analogs, with `pass`, `fail` and `info` as in `validation.json` | |
| 10 | It looks right at 1366 × 768 and on a projector | Pass, with observations 1 and 2 | 1366 × 768, 1280 × 720 and 1024 × 768: no horizontal scroll, map drawn, no exceptions | A real projector |
| 11 | It works with wifi off in local mode | Pass in simulation | With every external domain name blocked (only `localhost`), the map appears in 2.2 s with no exceptions. All 113 page resources come from `localhost` | Test with wifi actually off on the presentation laptop |

## Failures and observations, by priority

**Blocking the demo:** none.

**Not blocking:**

1. **The ranking and the card sit below the first screen at 1366 × 768 and at 1024 × 768.** You have to scroll down to
   see them. For the rehearsal: lower the browser zoom to 80 or 90%. To reproduce: open the app and shrink the window to
   that size.

   *TAI-40, decision:* it was measured and **the map height was not changed** (520 px in `ui/map_view.py`). At
   1366 × 768 the map drawing measures 750 × 375 inside a 520-high container, so about 145 px are spare. Lowering the
   fixed height to 440 moves the ranking up 80 px without shrinking the map on that screen, but at 1920 × 1080 the map
   goes from about 984 × 490 to 764 × 382 (22% smaller), which is the projector and video screen. A height that follows
   the window (a container with a `vh` height and `height="stretch"`) did not apply reliably in Streamlit 1.67: the
   container stayed at 450 px even when the style was forced. With no risk-free solution before the freeze, the map is
   left as is and the browser zoom is used.
2. **At 1024 × 768 the map is 564 px wide.** It is readable, but small. That is what a 4:3 projector would show.
3. **`scripts/check_cards.py` breaks in Windows consoles with the default encoding,** because it prints "✓". It is
   solved with `PYTHONIOENCODING=utf-8` or by running it from Git Bash. It does not affect the app.
4. **4 pipeline tests fail on this PC** (`pyhdf`, `geopandas` and a PROJ conflict with PostgreSQL). These are missing
   libraries, not an app problem; `make test` has to be run on the presentation laptop to confirm.

## How to repeat it

```bash
python scripts/e2e_local.py     # items 2 to 9, with AppTest and the real data; exits with code 1 if something fails
```

The rest (load times, screens, wifi off) is measured by hand, as above. It is worth repeating everything after any
last-minute change, for example the dust and wind dimension (TAI-52), which touches the map, the weights and the method
texts.

## Deployed part (Render, free plan)

Measured on November 15, 2026 between 09:35 and 09:50 (Argentina time) on
<https://terra-analog-index.onrender.com>, which deploys the `develop` branch at commit `37bf193`. Server in Oregon on
Render's free plan (0.1 CPU, 512 MB), client in Argentina, the tool panel's Chromium browser.

| # | Item | Result | Measurement |
|---|------|--------|-------------|
| 1 | The app opens in under 10 s | **Fails cold, passes warm** | First visit after creating the service: about 28 s until the map shows. With the app awake, the page loads in 4.1 s. Waking up after 15 minutes without visits was not measured; Render warns it can take 50 s or more |
| 3 | Each slider recomputes in under 1 s | **Fails on the free plan** | Real slider (keyboard arrow on "Terrain", from 1.00 to 0.95 and to 0.90): 3.57 s and 3.58 s until the recompute finishes (locally, 0.22 s). Switching target, which redraws the map: 4.1 s, 2.7 s and 3.4 s (locally, 0.33 s) |
| 4 | All weights at 0 show the warning, without an error | Pass | With the five sliders at 0, "Raise at least one weight." appears, with no errors or exceptions; clicking "Reset weights" brings them back to 1, 1, 1, 0.5 and 0.5 and the warning disappears |
| 7 | A finalist's card shows its manual text | Pass | Cell 46351 (Dalangtan) opens its card with the text and the sources, and the text's 0.86 matches the ranking's |

Not checked yet, and only possible on the presentation laptop: wifi actually off (the deployed app needs internet; that
is what local mode with `make app` is for) and a real projector.

**What to do about it.** Each interaction takes about 3.6 s on the free plan (0.1 CPU), ten times more than locally. It
is enough for the judges to come in and look around, but it feels slow and it falls asleep. For the demo: open the link
5 minutes earlier to wake it up, or show the app locally (`make app`, 0.33 s when switching target), or move the service
to Render's Starter plan (about 7 USD per month, 0.5 CPU, does not sleep).
