"""Mapas de control de los intermedios (TAI-24).

Dibuja un mapa de dispersión de Plotly por variable de grid, terrain,
temperature y water_ice, hace chequeos automáticos contra los criterios de
aceptación de TAI-11 a TAI-14 y comprueba que cada análogo de
config/known_analogs.csv cae en una celda de la grilla (criterio de TAI-17).

    python scripts/check_maps.py                      # todo lo que haya
    python scripts/check_maps.py --only terrain       # un solo archivo
    python scripts/check_maps.py --checks-only        # sin dibujar (no usa Plotly)
    python scripts/check_maps.py --projection south_pole

Escribe en data/interim/maps/ (fuera del repositorio): un .html por variable y
informe.md, para avisarle el resultado a cada responsable. Los chequeos
automáticos son orientativos: ayudan a mirar, no reemplazan mirar el mapa.
Códigos de salida: 0 bien; 2 falta una entrada pedida (o no hay grilla).
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tai import geo  # noqa: E402
from tai.constants import VALID_RANGES  # noqa: E402

PROCESSED = ROOT / "data" / "processed"
INTERIM = ROOT / "data" / "interim"
ANALOGS_CSV = ROOT / "config" / "known_analogs.csv"

# nombre -> (archivo, ticket, responsable, variables)
GROUPS = {
    "grid": (PROCESSED / "grid.parquet", "TAI-11", "Juanma", ["land_frac", "area_km2"]),
    "terrain": (INTERIM / "terrain.parquet", "TAI-12", "Juanma", ["slope_deg", "roughness_m"]),
    "temperature": (INTERIM / "temperature.parquet", "TAI-13", "Juanma", ["tmin_c", "trange_c"]),
    "water_ice": (INTERIM / "water_ice.parquet", "TAI-14", "Alan", ["precip_mm", "ice_frac"]),
}

# (lat_min, lat_max, lon_min, lon_max). Aproximadas: solo para los chequeos automáticos.
BOXES = {
    "Andes": (-35, -15, -72, -66),
    "Himalaya": (27, 35, 77, 95),
    "Sahara": (18, 28, -5, 25),
    "Pampa": (-38, -31, -66, -58),
    "Arabia": (18, 28, 40, 55),
    "Atacama": (-27, -18, -71, -68),
    "Amazonia": (-10, 0, -70, -55),
    "Groenlandia": (66, 80, -50, -25),
    "Antártida interior": (-90, -75, -180, 180),
}


# --- Chequeos ----------------------------------------------------------------


def in_box(df: pd.DataFrame, name: str) -> pd.DataFrame:
    la0, la1, lo0, lo1 = BOXES[name]
    return df[(df["lat"] >= la0) & (df["lat"] <= la1) & (df["lon"] >= lo0) & (df["lon"] <= lo1)]


def box_percentile(df: pd.DataFrame, var: str, name: str) -> tuple[float, int]:
    """Percentil (0 a 1) de la media de la región dentro de todas las celdas con dato."""
    sub = in_box(df, name)[var].dropna()
    if sub.empty:
        return float("nan"), 0
    return float((df[var].dropna() < sub.mean()).mean()), len(sub)


def check(name: str, ok: bool | None, detail: str) -> dict:
    return {"name": name, "status": "?" if ok is None else ("OK" if ok else "REVISAR"), "detail": detail}


def high_low(df, var, region, high: bool, thr: float) -> dict:
    p, n = box_percentile(df, var, region)
    if n == 0:
        return check(f"{var}: {region} {'alta' if high else 'baja'}", None, "sin celdas con dato en la región")
    ok = p >= thr if high else p <= thr
    return check(f"{var}: {region} {'alta' if high else 'baja'}", ok, f"percentil {p:.0%} ({n} celdas); se espera {'≥' if high else '≤'} {thr:.0%}")


def range_check(df: pd.DataFrame, var: str) -> dict:
    lo, hi = VALID_RANGES[var]
    s = df[var].dropna()
    bad = (s <= 0).sum() if var == "area_km2" else ((s < lo) | (s > hi if hi is not None else False)).sum()
    return check(f"{var}: dentro de rango", bad == 0, f"{bad} valores fuera de rango ({lo} a {hi})")


def null_check(df: pd.DataFrame, var: str, max_frac: float | None = None) -> dict:
    n_null, frac = int(df[var].isna().sum()), float(df[var].isna().mean())
    ok = None if max_frac is None else frac < max_frac
    extra = "" if max_frac is None else f"; se espera menos de {max_frac:.0%}"
    return check(f"{var}: nulos", ok, f"{n_null} de {len(df)} ({frac:.1%}){extra}")


def run_checks(name: str, df: pd.DataFrame) -> list[dict]:
    """Chequeos de la tabla `name`, con las columnas lat y lon ya unidas."""
    c: list[dict] = [range_check(df, v) for v in GROUPS[name][3]]
    if name == "grid":
        n = len(df)
        c += [
            check("celdas entre 15.000 y 25.000", 15_000 <= n <= 25_000, f"{n} celdas"),
            check("cell_id únicos", df["cell_id"].is_unique, f"{df['cell_id'].duplicated().sum()} repetidos"),
            check("hay celdas al sur de 85°S", bool((df["lat"] < -85).any()), f"{int((df['lat'] < -85).sum())} celdas"),
        ]
    elif name == "terrain":
        c += [null_check(df, v, 0.05) for v in ("slope_deg", "roughness_m")]
        c += [high_low(df, "slope_deg", r, True, 0.75) for r in ("Andes", "Himalaya")]
        c += [high_low(df, "slope_deg", r, False, 0.50) for r in ("Sahara", "Pampa")]
    elif name == "temperature":
        c += [null_check(df, v) for v in ("tmin_c", "trange_c")]
        cold = df.loc[df["tmin_c"].idxmin()] if df["tmin_c"].notna().any() else None
        if cold is not None:
            c.append(check("tmin_c: la celda más fría está en la Antártida", cold["lat"] <= -75, f"{cold['tmin_c']:.1f} °C en ({cold['lat']}, {cold['lon']})"))
        c += [high_low(df, "trange_c", r, True, 0.75) for r in ("Sahara", "Arabia")]
    elif name == "water_ice":
        c += [null_check(df, v) for v in ("precip_mm", "ice_frac")]
        polar = df[df["lat"].abs() >= 60]
        c.append(check("precip_mm: nulos polares (deben estar en el manifiesto)", None, f"{int(polar['precip_mm'].isna().sum())} de {len(polar)} celdas con |lat| ≥ 60°"))
        c += [high_low(df, "precip_mm", r, False, 0.15) for r in ("Atacama", "Sahara")]
        c.append(high_low(df, "precip_mm", "Amazonia", True, 0.85))
        for region, thr in (("Groenlandia", 0.5), ("Antártida interior", 0.9)):
            sub = in_box(df, region)["ice_frac"].dropna()
            share = float((sub >= 0.999).mean()) if len(sub) else float("nan")
            c.append(check(f"ice_frac = 1 en {region}", None if not len(sub) else share >= thr, f"{share:.0%} de {len(sub)} celdas; se espera ≥ {thr:.0%}"))
    return c


def check_analogs(analogs: pd.DataFrame, grid: pd.DataFrame) -> pd.DataFrame:
    """Para cada análogo: ¿su punto cae en una celda de la grilla?"""
    ids = set(grid["cell_id"])
    rows = []
    for a in analogs.itertuples(index=False):
        try:
            cid, err = int(geo.cell_id_of(a.lat, a.lon)), None
        except ValueError as exc:
            cid, err = None, str(exc)
        ok = cid in ids
        near = None
        if not ok and err is None:
            near = float(np.min(geo.haversine_km(a.lat, a.lon, grid["lat"].to_numpy(), grid["lon"].to_numpy())))
        rows.append({"analog_id": a.analog_id, "name": a.name, "target_id": a.target_id, "lat": a.lat, "lon": a.lon,
                     "cell_id": cid, "in_grid": ok, "nearest_cell_km": near, "error": err})
    return pd.DataFrame(rows)


# --- Mapas -------------------------------------------------------------------


def draw_map(df: pd.DataFrame, var: str, projection: str, analogs: pd.DataFrame | None = None):
    import plotly.graph_objects as go  # recién acá: --checks-only no necesita Plotly

    valid, nulls = df[df[var].notna()], df[df[var].isna()]
    hover = "lat %{lat}, lon %{lon}<br>" + var + " = %{marker.color:.3f}<extra></extra>"
    fig = go.Figure()
    if len(nulls):
        fig.add_trace(go.Scattergeo(lat=nulls["lat"], lon=nulls["lon"], mode="markers", name="sin dato",
                                    marker=dict(symbol="square", size=4, color="lightgray"),
                                    hovertemplate="lat %{lat}, lon %{lon}<br>sin dato<extra></extra>"))
    fig.add_trace(go.Scattergeo(lat=valid["lat"], lon=valid["lon"], mode="markers", name=var,
                                marker=dict(symbol="square", size=4, color=valid[var], colorscale="Viridis",
                                            colorbar=dict(title=var), showscale=True),
                                hovertemplate=hover))
    if analogs is not None and len(analogs):  # puntos de known_analogs.csv, para ver si caen en tierra
        for ok, color, label in ((True, "white", "análogo en grilla"), (False, "red", "análogo FUERA de la grilla")):
            sub = analogs[analogs["in_grid"] == ok]
            if len(sub):
                fig.add_trace(go.Scattergeo(lat=sub["lat"], lon=sub["lon"], text=sub["name"], mode="markers", name=label,
                                            marker=dict(symbol="diamond", size=9, color=color, line=dict(color="black", width=1))))
    geos = dict(showcoastlines=True, showland=True, landcolor="rgb(245,245,245)")
    if projection == "south_pole":
        geos.update(projection=dict(type="orthographic", rotation=dict(lon=0, lat=-90)))
    else:
        geos.update(projection_type="natural earth")
    n, lo, hi = len(valid), valid[var].min(), valid[var].max()
    fig.update_geos(**geos)
    fig.update_layout(title=f"{var}: {n} celdas con dato de {len(df)}; mín {lo:.3g}, máx {hi:.3g}", height=650, margin=dict(l=0, r=0, t=50, b=0))
    return fig


# --- Informe -----------------------------------------------------------------


def write_report(path: Path, results: dict, analog_result: pd.DataFrame | None) -> None:
    out = ["# Informe de mapas de control (TAI-24)", "",
           "Chequeos automáticos orientativos: confirmar mirando cada mapa. "
           "`REVISAR` no es un error confirmado, es algo para mirar.", ""]
    for name, (ticket, owner, checks) in results.items():
        out += [f"## {name} ({ticket}). Avisar a: {owner}", "", "- [ ] Mapa revisado a ojo y resultado avisado", ""]
        out += [f"- **{c['status']}** {c['name']}: {c['detail']}" for c in checks] + [""]
    out += ["## Análogos conocidos (TAI-17). Avisar a: Santino", ""]
    if analog_result is None:
        out += ["No se comprobó: falta config/known_analogs.csv o la grilla.", ""]
    else:
        bad = analog_result[~analog_result["in_grid"]]
        if bad.empty:
            out += [f"Los {len(analog_result)} análogos caen en una celda de la grilla.", ""]
        else:
            out += [f"{len(bad)} de {len(analog_result)} análogos NO caen en ninguna celda de la grilla:", ""]
            for r in bad.itertuples():
                dist = "coordenadas inválidas" if pd.isna(r.nearest_cell_km) else f"celda más cercana a {r.nearest_cell_km:.0f} km"
                out.append(f"- `{r.analog_id}` ({r.name}, {r.target_id}): ({r.lat}, {r.lon}); {dist}")
            out.append("")
    path.write_text("\n".join(out), encoding="utf-8")


# --- Programa ----------------------------------------------------------------


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Mapas de control de los intermedios (TAI-24)")
    p.add_argument("--only", nargs="+", choices=list(GROUPS), help="solo estos archivos")
    p.add_argument("--out", type=Path, default=INTERIM / "maps")
    p.add_argument("--projection", choices=["world", "south_pole"], default="world")
    p.add_argument("--checks-only", action="store_true", help="no dibuja mapas")
    args = p.parse_args(argv)

    if not GROUPS["grid"][0].exists():
        print(f"Falta {GROUPS['grid'][0]} (lo genera el paso 01_grid).", file=sys.stderr)
        return 2
    grid = pd.read_parquet(GROUPS["grid"][0])
    centers = grid[["cell_id", "lat", "lon"]]

    analog_result = None
    if ANALOGS_CSV.exists():
        analogs = pd.read_csv(ANALOGS_CSV)
        missing = {"analog_id", "name", "lat", "lon", "target_id"} - set(analogs.columns)
        if missing:
            print(f"{ANALOGS_CSV.name}: faltan columnas {sorted(missing)}", file=sys.stderr)
            return 2
        analog_result = check_analogs(analogs, grid)
    else:
        print(f"Aviso: no existe {ANALOGS_CSV.relative_to(ROOT)} (TAI-17); se omite la comprobación de análogos.")

    args.out.mkdir(parents=True, exist_ok=True)
    results, status = {}, 0
    for name in args.only or list(GROUPS):
        path, ticket, owner, variables = GROUPS[name]
        if not path.exists():
            print(f"Se omite {name}: falta {path.relative_to(ROOT)}")
            status = 2 if args.only else status
            continue
        df = pd.read_parquet(path)
        if "lat" not in df.columns:
            df = df.merge(centers, on="cell_id", how="left")
        checks = run_checks(name, df)
        results[name] = (ticket, owner, checks)
        print(f"\n== {name} ({ticket}, {owner}) ==")
        for c in checks:
            print(f"  [{c['status']:>7}] {c['name']}: {c['detail']}")
        if not args.checks_only:
            for var in variables:
                f = args.out / f"{name}__{var}.html"
                draw_map(df, var, args.projection, analog_result if name == "grid" else None).write_html(f, include_plotlyjs="directory")
                print(f"  mapa: {f.relative_to(ROOT)}")

    if analog_result is not None:
        bad = analog_result[~analog_result["in_grid"]]
        print("\n== análogos conocidos (TAI-17) ==")
        print("  Caen todos en la grilla." if bad.empty else f"  {len(bad)} NO caen en la grilla: {', '.join(bad['analog_id'])}")
    write_report(args.out / "informe.md", results, analog_result)
    print(f"\nInforme: {(args.out / 'informe.md').relative_to(ROOT)}")
    return status


if __name__ == "__main__":
    sys.exit(main())
