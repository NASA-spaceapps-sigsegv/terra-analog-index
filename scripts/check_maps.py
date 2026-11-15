"""Control maps of the intermediate files (TAI-24).

For grid, terrain, temperature and water_ice it produces:
  * a Plotly scatter map per variable (colored by value, nulls in gray)
    and a histogram per variable, to spot badly converted units;
  * automatic checks against the acceptance criteria of TAI-11 to TAI-14:
    ranges, nulls, structure, consistency with the manifest and reference regions;
  * the check that every analog in config/known_analogs.csv falls in a grid
    cell, plus the count and source criteria of TAI-17;
  * index.html (everything on one page) and report.md (with a message ready to
    tell each owner the result).

    python scripts/check_maps.py                       # everything available
    python scripts/check_maps.py --only terrain        # a single file
    python scripts/check_maps.py --projection all      # world + south pole + north pole
    python scripts/check_maps.py --checks-only         # no drawing (does not use Plotly)
    python scripts/check_maps.py --parquet-engine fastparquet   # if pyarrow does not run
    python scripts/check_maps.py --open --strict

Output in data/interim/maps/ (outside the repository). The regional checks are
indicative: `REVIEW` is something to look at on the map, not a confirmed error.
Exit codes: 0 fine; 1 with --strict if there is any REVIEW; 2 a requested input
is missing (or there is no grid) or Plotly is missing.
"""

import argparse
import html
import json
import sys
import webbrowser
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tai import geo  # noqa: E402
from tai.constants import TARGET_IDS, VALID_RANGES  # noqa: E402

# Each file: where it lives (processed or interim), which step produces it, which ticket
# it belongs to, who gets notified and which variables are drawn.
GROUPS = {
    "grid": dict(where="processed", file="grid.parquet", step="01_grid", ticket="TAI-11", owner="Juanma", vars=["land_frac", "area_km2"]),
    "terrain": dict(where="interim", file="terrain.parquet", step="02_terrain", ticket="TAI-12", owner="Juanma", vars=["slope_deg", "roughness_m"]),
    "temperature": dict(where="interim", file="temperature.parquet", step="03_temperature", ticket="TAI-13", owner="Juanma", vars=["tmin_c", "trange_c"]),
    "water_ice": dict(where="interim", file="water_ice.parquet", step="04_water_ice", ticket="TAI-14", owner="Alan", vars=["precip_mm", "ice_frac"]),
}
UNITS = {"land_frac": "fraction", "area_km2": "km²", "slope_deg": "°", "roughness_m": "m", "tmin_c": "°C",
         "trange_c": "°C", "precip_mm": "mm/yr", "ice_frac": "fraction"}
FIXED_COLOR_RANGE = {"land_frac": (0.5, 1.0), "ice_frac": (0.0, 1.0)}  # the rest: percentiles 1 to 99

# (lat_min, lat_max, lon_min, lon_max). Approximate: only for the automatic checks.
BOXES = {
    "Andes": (-35, -15, -72, -66), "Himalaya": (27, 35, 77, 95), "Sahara": (18, 28, -5, 25),
    "Pampa": (-38, -31, -66, -58), "Arabia": (18, 28, 40, 55), "Atacama": (-27, -18, -71, -68),
    "Amazonia": (-10, 0, -70, -55), "Greenland": (66, 80, -50, -25), "Antarctic interior": (-90, -75, -180, 180),
}
CONTINENTS = {  # RF-01: there are cells on all seven continents
    "Africa": (-30, 30, -15, 45), "Antarctica": (-90, -65, -180, 180), "Asia": (25, 60, 60, 120),
    "Europe": (40, 60, 0, 30), "North America": (30, 60, -125, -70), "Oceania": (-35, -15, 120, 150),
    "South America": (-40, 0, -75, -40),
}
PROJECTIONS = {"world": "World", "south_pole": "South pole", "north_pole": "North pole"}


# --- Utilities ---------------------------------------------------------------


def rel(path: Path, root: Path) -> str:
    """Path relative to the repository root; if it falls outside, the path as is."""
    try:
        return str(Path(path).resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def read_parquet(path: Path, engine: str = "auto") -> pd.DataFrame:
    return pd.read_parquet(path) if engine == "auto" else pd.read_parquet(path, engine=engine)


def group_path(root: Path, spec: dict) -> Path:
    return root / "data" / spec["where"] / spec["file"]


# --- Checks ------------------------------------------------------------------


def check(name: str, ok: bool | None, detail: str) -> dict:
    return {"name": name, "status": "?" if ok is None else ("OK" if ok else "REVIEW"), "detail": detail}


def in_box(df: pd.DataFrame, box) -> pd.DataFrame:
    """Cells inside a region given by name (BOXES or CONTINENTS) or as a tuple."""
    if isinstance(box, str):
        box = BOXES[box] if box in BOXES else CONTINENTS[box]
    la0, la1, lo0, lo1 = box
    return df[(df["lat"] >= la0) & (df["lat"] <= la1) & (df["lon"] >= lo0) & (df["lon"] <= lo1)]


def box_percentile(df: pd.DataFrame, var: str, name: str) -> tuple[float, int]:
    """Percentile (0 to 1) of the region's median among all cells with data.

    Median and not mean: a massif inside a flat box (the Tibesti in the
    Sahara) drags the mean and would raise a false alarm."""
    sub = in_box(df, name)[var].dropna()
    if sub.empty:
        return float("nan"), 0
    return float((df[var].dropna() < sub.median()).mean()), len(sub)


def high_low(df: pd.DataFrame, var: str, region: str, high: bool, thr: float) -> dict:
    label = f"{var}: {region} {'high' if high else 'low'}"
    p, n = box_percentile(df, var, region)
    if n == 0:
        return check(label, None, "no cells with data in the region")
    ok = p >= thr if high else p <= thr
    return check(label, ok, f"percentile {p:.0%} ({n} cells); expected {'≥' if high else '≤'} {thr:.0%}")


def range_check(df: pd.DataFrame, var: str) -> dict:
    lo, hi = VALID_RANGES[var]
    s = df[var].dropna()
    if var == "area_km2":  # strictly greater than 0
        bad = int((s <= 0).sum())
    else:
        too_low = s < lo
        too_high = (s > hi) if hi is not None else pd.Series(False, index=s.index)
        bad = int((too_low | too_high).sum())
    return check(f"{var}: within range", bad == 0, f"{bad} values out of range ({lo} to {hi})")


def null_check(df: pd.DataFrame, var: str, max_frac: float | None = None) -> dict:
    n_null, frac = int(df[var].isna().sum()), float(df[var].isna().mean())
    extra = "" if max_frac is None else f"; expected less than {max_frac:.0%}"
    return check(f"{var}: nulls", None if max_frac is None else frac < max_frac, f"{n_null} of {len(df)} ({frac:.1%}){extra}")


def structure_checks(name: str, df: pd.DataFrame, grid_ids: set) -> list[dict]:
    dups = int(df["cell_id"].duplicated().sum())
    c = [check("unique cell_id", dups == 0, f"{dups} duplicated")]
    if name != "grid":
        extra = set(df["cell_id"]) - grid_ids
        missing = len(grid_ids - set(df["cell_id"]))
        c.append(check("every cell_id exists in the grid", not extra, f"{len(extra)} cell_id outside the grid"))
        c.append(check("one row per grid cell", missing == 0, f"{missing} grid cells without a row"))
    return c


def partial_steps(manifest: dict | None) -> set[str]:
    """Steps whose last run was partial (--bbox): nulls are expected there."""
    if not manifest:
        return set()
    return {s["step"] for s in manifest.get("steps", []) if any("partial run" in n for n in s.get("notes", []))}


def manifest_checks(name: str, df: pd.DataFrame, manifest: dict | None) -> list[dict]:
    """The manifest must report the same as what is seen in the file (RF-11)."""
    if manifest is None:
        return [check("manifest", None, "data/processed/manifest.json does not exist")]
    spec = GROUPS[name]
    entry = next((s for s in manifest.get("steps", []) if s["step"] == spec["step"]), None)
    if entry is None:
        return [check("manifest", False, f"it has no entry for step {spec['step']}")]
    c = []
    if name == "grid":
        n = (manifest.get("grid") or {}).get("n_cells")
        c.append(check("manifest: number of cells", None if n is None else n == len(df), f"manifest {n}, file {len(df)}"))
    for var in spec["vars"]:
        stats = entry.get("columns", {}).get(var)
        actual = int(df[var].isna().sum())
        if stats is None:
            c.append(check(f"manifest: nulls of {var}", None if name == "grid" else False, "the manifest does not report this column"))
        else:
            c.append(check(f"manifest: nulls of {var}", stats["null"] == actual, f"manifest {stats['null']}, file {actual}"))
    return c


def run_checks(name: str, df: pd.DataFrame, regional: bool = True) -> list[dict]:
    """Checks of table `name` (with lat and lon joined). regional=False on partial runs."""
    c = [range_check(df, v) for v in GROUPS[name]["vars"]]
    if name == "grid":
        n = len(df)
        c += [check("cells between 15,000 and 25,000", 15_000 <= n <= 25_000, f"{n} cells"),
              check("there are cells south of 85°S", bool((df["lat"] < -85).any()), f"{int((df['lat'] < -85).sum())} cells")]
        if regional:
            counts_ = {k: len(in_box(df, k)) for k in CONTINENTS}
            c.append(check("there are cells on all seven continents", all(counts_.values()), ", ".join(f"{k} {v}" for k, v in counts_.items())))
        c.append(check("the centers trace the continents", None, "confirm by eye in grid__land_frac"))
    elif name == "terrain":
        c += [null_check(df, v, 0.05) for v in ("slope_deg", "roughness_m")]
        if regional:
            c += [high_low(df, "slope_deg", r, True, 0.75) for r in ("Andes", "Himalaya")]
            c += [high_low(df, "slope_deg", r, False, 0.50) for r in ("Sahara", "Pampa")]
    elif name == "temperature":
        c += [null_check(df, v) for v in ("tmin_c", "trange_c")]
        if regional:
            if df["tmin_c"].notna().any():
                cold = df.loc[df["tmin_c"].idxmin()]
                c.append(check("tmin_c: the coldest cell is in Antarctica", cold["lat"] <= -75, f"{cold['tmin_c']:.1f} °C at ({cold['lat']}, {cold['lon']})"))
            c += [high_low(df, "trange_c", r, True, 0.75) for r in ("Sahara", "Arabia")]
    elif name == "water_ice":
        c += [null_check(df, v) for v in ("precip_mm", "ice_frac")]
        polar = df[df["lat"].abs() >= 60]
        c.append(check("precip_mm: polar nulls (report them in the manifest)", None, f"{int(polar['precip_mm'].isna().sum())} of {len(polar)} cells with |lat| ≥ 60°"))
        if regional:
            c += [high_low(df, "precip_mm", r, False, 0.15) for r in ("Atacama", "Sahara")]
            c.append(high_low(df, "precip_mm", "Amazonia", True, 0.85))
            for region, thr in (("Greenland", 0.5), ("Antarctic interior", 0.9)):
                sub = in_box(df, region)["ice_frac"].dropna()
                share = float((sub >= 0.999).mean()) if len(sub) else float("nan")
                c.append(check(f"ice_frac = 1 in {region}", None if not len(sub) else share >= thr, f"{share:.0%} of {len(sub)} cells; expected ≥ {thr:.0%}"))
    return c


def stats_table(df: pd.DataFrame, variables: list[str]) -> pd.DataFrame:
    """Summary per variable: the first thing that gives away a badly converted unit."""
    rows = []
    for v in variables:
        s = df[v].dropna()
        q = s.quantile([0.01, 0.5, 0.99]).tolist() if len(s) else [np.nan] * 3
        rows.append({"variable": v, "unit": UNITS.get(v, ""), "with data": len(s), "nulls": int(df[v].isna().sum()),
                     "min": s.min() if len(s) else np.nan, "p01": q[0], "median": q[1], "p99": q[2],
                     "max": s.max() if len(s) else np.nan, "mean": s.mean() if len(s) else np.nan})
    return pd.DataFrame(rows)


# --- Known analogs (TAI-17) -------------------------------------------------


def check_analogs(analogs: pd.DataFrame, grid: pd.DataFrame) -> pd.DataFrame:
    """For each analog: does its point fall in a grid cell?"""
    ids = set(grid["cell_id"])
    rows = []
    for a in analogs.itertuples(index=False):
        try:
            cid, err = int(geo.cell_id_of(a.lat, a.lon)), None
        except (ValueError, TypeError) as exc:
            cid, err = None, str(exc)
        ok = cid in ids
        near = None
        if not ok and err is None:
            near = float(np.min(geo.haversine_km(a.lat, a.lon, grid["lat"].to_numpy(), grid["lon"].to_numpy())))
        rows.append({"analog_id": a.analog_id, "name": a.name, "target_id": a.target_id, "lat": a.lat, "lon": a.lon,
                     "cell_id": cid, "in_grid": ok, "nearest_cell_km": near, "error": err})
    return pd.DataFrame(rows)


def analog_rule_checks(a: pd.DataFrame) -> list[dict]:
    """TAI-17 acceptance criteria that can be checked without scientific judgment."""
    # The same place can be listed for both targets in two rows: places are counted.
    n = a["analog_id"].nunique()
    c = [check("between 8 and 12 analogs", 8 <= n <= 12, f"{n} analogs in {len(a)} rows")]
    dup = int(a.duplicated(subset=["analog_id", "target_id"]).sum())
    c.append(check("no duplicated rows (analog_id, target_id)", dup == 0, f"{dup} duplicated"))
    unknown = sorted(set(a["target_id"].dropna()) - set(TARGET_IDS))
    c.append(check("known target_id", not unknown, f"unknown: {unknown}" if unknown else "all valid"))
    if "radius_km" in a:
        bad = int((~(a["radius_km"] > 0)).sum())  # includes nulls
        c.append(check("radius_km greater than 0", bad == 0, f"{bad} rows with an invalid radius"))
    if "source" in a:
        empty = int((a["source"].fillna("").astype(str).str.strip() == "").sum())
        c.append(check("no row without a source", empty == 0, f"{empty} without a source"))
    if "covered" in a:
        for t in TARGET_IDS:
            n = int(((a["target_id"] == t) & (a["covered"] == "yes")).sum())
            c.append(check(f"at least 3 covered (covered = yes) in {t}", n >= 3, f"{n} covered"))
    return c


# --- Maps --------------------------------------------------------------------


def color_range(s: pd.Series, var: str) -> tuple[float, float]:
    if var in FIXED_COLOR_RANGE:
        return FIXED_COLOR_RANGE[var]
    lo, hi = float(s.quantile(0.01)), float(s.quantile(0.99))
    if lo == hi:
        lo, hi = float(s.min()), float(s.max())
    return (lo, hi) if lo != hi else (lo - 0.5, hi + 0.5)


def draw_map(df: pd.DataFrame, var: str, projection: str, analogs: pd.DataFrame | None = None):
    import plotly.graph_objects as go  # only here: --checks-only does not need Plotly

    df = df[df["lat"].notna()]
    valid, nulls = df[df[var].notna()], df[df[var].isna()]
    unit = UNITS.get(var, "")
    country = valid["country"].fillna("—").astype(str) if "country" in valid else pd.Series("", index=valid.index)
    fig = go.Figure()
    if len(nulls):
        fig.add_trace(go.Scattergeo(lat=nulls["lat"], lon=nulls["lon"], mode="markers", name="no data",
                                    marker=dict(symbol="square", size=4, color="lightgray"),
                                    hovertemplate="lat %{lat}, lon %{lon}<br>no data<extra></extra>"))
    if len(valid):
        cmin, cmax = color_range(valid[var], var)
        fig.add_trace(go.Scattergeo(
            lat=valid["lat"], lon=valid["lon"], text=country, customdata=valid[var], mode="markers", name=var,
            marker=dict(symbol="square", size=4, color=valid[var], colorscale="Viridis", cmin=cmin, cmax=cmax,
                        colorbar=dict(title=dict(text=f"{var} ({unit})"))),
            hovertemplate="%{text}<br>lat %{lat}, lon %{lon}<br>" + var + " = %{customdata:.3f} " + unit + "<extra></extra>"))
    if analogs is not None and len(analogs):  # points from known_analogs.csv, to see whether they fall on land
        for ok, color, label in ((True, "white", "analog in grid"), (False, "red", "analog OUTSIDE the grid")):
            sub = analogs[(analogs["in_grid"] == ok) & analogs["lat"].notna()]
            if len(sub):
                fig.add_trace(go.Scattergeo(lat=sub["lat"], lon=sub["lon"], text=sub["name"] + " (" + sub["target_id"] + ")",
                                            mode="markers", name=label, hovertemplate="%{text}<extra></extra>",
                                            marker=dict(symbol="diamond", size=9, color=color, line=dict(color="black", width=1))))
    geos = dict(showcoastlines=True, showland=True, landcolor="rgb(245,245,245)")
    if projection == "world":
        geos["projection_type"] = "natural earth"
    else:
        geos["projection"] = dict(type="orthographic", rotation=dict(lon=0, lat=-90 if projection == "south_pole" else 90))
    rng = "" if var in FIXED_COLOR_RANGE else "; color between p1 and p99"
    lo, hi = (valid[var].min(), valid[var].max()) if len(valid) else (float("nan"),) * 2
    fig.update_geos(**geos)
    fig.update_layout(title=f"{var} · {PROJECTIONS[projection]}: {len(valid)} with data of {len(df)}; min {lo:.3g}, max {hi:.3g}{rng}",
                      height=650, margin=dict(l=0, r=0, t=50, b=40),
                      # Legend at the bottom and horizontal: top right (the default) overlaps
                      # the color bar title.
                      legend=dict(orientation="h", x=0.5, xanchor="center", y=0, yanchor="top"))
    return fig


def draw_hist(df: pd.DataFrame, var: str):
    import plotly.graph_objects as go

    s = df[var].dropna()
    fig = go.Figure(go.Histogram(x=s, nbinsx=60, name=var))
    lo, hi = VALID_RANGES[var]
    for x in (lo, hi):  # the contract's valid limits, if any
        if x is not None:
            fig.add_vline(x=x, line_dash="dash", line_color="red")
    fig.update_layout(title=f"{var}: distribution ({len(s)} cells with data; red line = valid limit)",
                      xaxis_title=f"{var} ({UNITS.get(var, '')})", yaxis_title="cells", height=420, margin=dict(t=50))
    return fig


# --- Report and index ---------------------------------------------------------


def counts(checks: list[dict]) -> dict:
    return {k: sum(c["status"] == k for c in checks) for k in ("OK", "REVIEW", "?")}


def message_for(res: dict) -> str:
    n, bad = counts(res["checks"]), [c for c in res["checks"] if c["status"] == "REVIEW"]
    head = f"{res['owner']}: I reviewed the {res['name']} maps ({res['ticket']}). {n['OK']} checks OK, {n['REVIEW']} to look at."
    if not bad:
        return head + " Nothing odd at first sight."
    return head + "".join(f"\n  - {c['name']}: {c['detail']}" for c in bad)


def write_report(path: Path, results: dict, analog_result, analog_checks, notes: list[str]) -> None:
    out = ["# Control maps report (TAI-24)", "",
           "Indicative automatic checks: confirm by looking at each map. `REVIEW` is not a confirmed error.", ""]
    out += [f"> {n}" for n in notes] + ([""] if notes else [])
    for name, res in results.items():
        n = counts(res["checks"])
        out += [f"## {name} ({res['ticket']}). Notify: {res['owner']}", "",
                f"{n['OK']} OK · {n['REVIEW']} REVIEW · {n['?']} to check by eye", "",
                "- [ ] Maps reviewed by eye and result reported", ""]
        out += [f"- **{c['status']}** {c['name']}: {c['detail']}" for c in res["checks"]] + [""]
        out += ["Message to paste:", "", "```", message_for({**res, "name": name}), "```", ""]
    out += ["## Known analogs (TAI-17). Notify: Santino", ""]
    if analog_result is None:
        out += ["Not checked: config/known_analogs.csv is missing.", ""]
    else:
        bad = analog_result[~analog_result["in_grid"]]
        if bad.empty:
            out += [f"All {len(analog_result)} analogs fall in a grid cell.", ""]
        else:
            out += [f"{len(bad)} of {len(analog_result)} analogs do NOT fall in any grid cell:", ""]
            for r in bad.itertuples():
                dist = "invalid coordinates" if pd.isna(r.nearest_cell_km) else f"nearest cell {r.nearest_cell_km:.0f} km away"
                out.append(f"- `{r.analog_id}` ({r.name}, {r.target_id}): ({r.lat}, {r.lon}); {dist}")
            out.append("")
        out += [f"- **{c['status']}** {c['name']}: {c['detail']}" for c in analog_checks] + [""]
    path.write_text("\n".join(out), encoding="utf-8")


_CSS = """body{font:15px/1.5 system-ui,sans-serif;max-width:1000px;margin:2rem auto;padding:0 1rem;color:#1a1a1a;background:#fff}
h1,h2{margin-top:2rem}table{border-collapse:collapse;width:100%;margin:.5rem 0}td,th{border:1px solid #ccc;padding:.25rem .5rem;text-align:left;font-size:13px}
.OK{color:#0a7a2f;font-weight:600}.REVIEW{color:#b42318;font-weight:600}.q{color:#667085;font-weight:600}.note{background:#fff4e5;padding:.5rem 1rem;border-radius:6px}
a{color:#175cd3}@media(prefers-color-scheme:dark){body{color:#eee;background:#111}td,th{border-color:#444}.note{background:#3a2a10}a{color:#7cb0ff}.OK{color:#4ade80}.REVIEW{color:#f87171}}"""


def _table(headers, rows) -> str:
    th = "".join(f"<th>{html.escape(str(h))}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in r) + "</tr>" for r in rows)
    return f"<table><tr>{th}</tr>{body}</table>"


def _status(c: dict) -> str:
    cls = {"OK": "OK", "REVIEW": "REVIEW", "?": "q"}[c["status"]]
    return f'<span class="{cls}">{html.escape(c["status"])}</span>'


def write_index(path: Path, results: dict, analog_result, analog_checks, notes: list[str]) -> None:
    h = ["<!doctype html><meta charset=utf-8><title>Control maps (TAI-24)</title>", f"<style>{_CSS}</style>",
         "<h1>Control maps of the intermediate files (TAI-24)</h1>",
         "<p>Indicative automatic checks: <b>REVIEW</b> is something to look at on the map, not a confirmed error.</p>"]
    h += [f'<p class="note">{html.escape(n)}</p>' for n in notes]
    for name, res in results.items():
        n = counts(res["checks"])
        h.append(f"<h2>{html.escape(name)} · {res['ticket']} · notify {html.escape(res['owner'])}</h2>")
        h.append(f"<p>{n['OK']} OK · {n['REVIEW']} REVIEW · {n['?']} to check by eye</p>")
        h.append(_table(["", "check", "detail"], [(_status(c), html.escape(c["name"]), html.escape(c["detail"])) for c in res["checks"]]))
        st = res["stats"]
        h.append(_table(list(st.columns), [[html.escape(f"{v:.4g}" if isinstance(v, float) else str(v)) for v in r] for r in st.itertuples(index=False)]))
        links = [f'<a href="{html.escape(f)}">{html.escape(f)}</a>' for f in res["maps"] + res["hists"]]
        h.append("<p>" + (" · ".join(links) if links else "No maps (--checks-only).") + "</p>")
    h.append("<h2>Known analogs · TAI-17 · notify Santino</h2>")
    if analog_result is None:
        h.append("<p>Not checked: config/known_analogs.csv is missing.</p>")
    else:
        bad = analog_result[~analog_result["in_grid"]]
        if bad.empty:
            summary = "They all fall in the grid."
        else:
            summary = f"{len(bad)} of {len(analog_result)} do NOT fall in the grid: " + ", ".join(bad["analog_id"])
        h.append(f"<p>{html.escape(summary)}</p>")
        h.append(_table(["", "check", "detail"], [(_status(c), html.escape(c["name"]), html.escape(c["detail"])) for c in analog_checks]))
    path.write_text("\n".join(h), encoding="utf-8")


# --- Program -----------------------------------------------------------------


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Control maps of the intermediate files (TAI-24)")
    p.add_argument("--only", nargs="+", choices=list(GROUPS), help="only these files")
    p.add_argument("--root", type=Path, default=ROOT, help="repository root (by default, this script's)")
    p.add_argument("--out", type=Path, default=None, help="output folder (default data/interim/maps)")
    p.add_argument("--projection", choices=[*PROJECTIONS, "all"], default="world")
    p.add_argument("--parquet-engine", choices=["auto", "pyarrow", "fastparquet"], default="auto",
                   help="engine to read Parquet; fastparquet helps if pyarrow does not run on the machine")
    p.add_argument("--checks-only", action="store_true", help="do not draw maps")
    p.add_argument("--strict", action="store_true", help="exit with code 1 if there is any REVIEW")
    p.add_argument("--open", action="store_true", help="open index.html in the browser")
    args = p.parse_args(argv)

    root = args.root.resolve()
    out_dir = args.out or root / "data" / "interim" / "maps"
    manifest_path = root / "data" / "processed" / "manifest.json"
    analogs_csv = root / "config" / "known_analogs.csv"
    projections = list(PROJECTIONS) if args.projection == "all" else [args.projection]

    grid_path = group_path(root, GROUPS["grid"])
    if not grid_path.exists():
        print(f"{rel(grid_path, root)} is missing (step 01_grid produces it).", file=sys.stderr)
        return 2
    if not args.checks_only:
        try:
            import plotly  # noqa: F401
        except ImportError:
            print("Plotly is missing: pip install plotly (or use --checks-only).", file=sys.stderr)
            return 2

    grid = read_parquet(grid_path, args.parquet_engine)
    cols = [c for c in ("cell_id", "lat", "lon", "country") if c in grid.columns]
    centers, grid_ids = grid[cols], set(grid["cell_id"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else None
    partial = partial_steps(manifest)
    notes = []
    if partial:
        notes.append(f"Partial run (--bbox) in {', '.join(sorted(partial))}: regional checks are skipped and nulls are expected.")

    analog_result, analog_checks = None, []
    if analogs_csv.exists():
        analogs = pd.read_csv(analogs_csv)
        missing = {"analog_id", "name", "lat", "lon", "target_id"} - set(analogs.columns)
        if missing:
            print(f"{analogs_csv.name}: missing columns {sorted(missing)}", file=sys.stderr)
            return 2
        analog_result = check_analogs(analogs, grid)
        outside = analog_result.loc[~analog_result["in_grid"], "analog_id"].tolist()
        analog_checks = [check("every analog falls in a grid cell", not outside,
                               f"outside: {', '.join(outside)}" if outside else f"all {len(analog_result)} fall in")]
        analog_checks += analog_rule_checks(analogs)
    else:
        print(f"Warning: {rel(analogs_csv, root)} does not exist (TAI-17); the analogs check is skipped.")

    out_dir.mkdir(parents=True, exist_ok=True)
    results, status = {}, 0
    for name in args.only or list(GROUPS):
        spec = GROUPS[name]
        path = group_path(root, spec)
        if not path.exists():
            print(f"Skipping {name}: {rel(path, root)} is missing")
            status = 2 if args.only else status
            continue
        df = read_parquet(path, args.parquet_engine)
        if "lat" not in df.columns:
            df = df.merge(centers, on="cell_id", how="left")
        checks = structure_checks(name, df, grid_ids) + run_checks(name, df, regional=spec["step"] not in partial) + manifest_checks(name, df, manifest)
        res = dict(ticket=spec["ticket"], owner=spec["owner"], checks=checks, stats=stats_table(df, spec["vars"]), maps=[], hists=[])
        print(f"\n== {name} ({spec['ticket']}, {spec['owner']}) ==")
        for c in checks:
            print(f"  [{c['status']:>7}] {c['name']}: {c['detail']}")
        if not args.checks_only:
            for var in spec["vars"]:
                for proj in projections:
                    f = f"{name}__{var}__{proj}.html"
                    draw_map(df, var, proj, analog_result if name == "grid" else None).write_html(out_dir / f, include_plotlyjs="directory")
                    res["maps"].append(f)
                f = f"{name}__{var}__hist.html"
                draw_hist(df, var).write_html(out_dir / f, include_plotlyjs="directory")
                res["hists"].append(f)
            print(f"  {len(res['maps'])} maps and {len(res['hists'])} histograms in {rel(out_dir, root)}")
        results[name] = res

    if analog_result is not None:
        bad = analog_result[~analog_result["in_grid"]]
        print("\n== known analogs (TAI-17) ==")
        print("  They all fall in the grid." if bad.empty else f"  {len(bad)} do NOT fall in the grid: {', '.join(bad['analog_id'])}")
        for c in analog_checks:
            print(f"  [{c['status']:>7}] {c['name']}: {c['detail']}")

    write_report(out_dir / "report.md", results, analog_result, analog_checks, notes)
    write_index(out_dir / "index.html", results, analog_result, analog_checks, notes)
    print(f"\nReport: {rel(out_dir / 'report.md', root)}\nIndex:  {rel(out_dir / 'index.html', root)}")
    if args.strict and any(c["status"] == "REVIEW" for r in results.values() for c in r["checks"] + analog_checks):
        status = 1
    if args.open:
        webbrowser.open((out_dir / "index.html").resolve().as_uri())
    return status


if __name__ == "__main__":
    sys.exit(main())
