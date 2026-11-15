#!/usr/bin/env python
"""Genera el póster A3 y el tríptico A4 de Terra Analog Index (PDF y PNG) con los datos de data/processed/.

    .venv/Scripts/python.exe docs/difusion/fuente/build.py                # sin QR
    .venv/Scripts/python.exe docs/difusion/fuente/build.py --url https://...   # con QR (pide `pip install segno`)

Salida, en docs/difusion/: poster_A3.pdf, poster_A3.png, triptico_A4.pdf (hoja 1 = afuera, hoja 2 = adentro),
triptico_afuera.png, triptico_adentro.png. Necesita Microsoft Edge (imprime el HTML a PDF) y las tipografías
Bahnschrift y Segoe UI (vienen con Windows); los PDF las llevan incrustadas.

Todas las cifras salen de los datos, con los pesos iniciales; si un dato cambia (por ejemplo el puesto de una
finalista), el script falla en vez de imprimir un número viejo.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE.parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO))

from tai import io, services  # noqa: E402
from tai.constants import DEFAULT_WEIGHTS, RANKING_LIMIT_MAX  # noqa: E402

EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]
BUILD = Path(tempfile.gettempdir()) / "tai_difusion"
MOON, MARS = "moon_south_pole", "mars_jezero"
FINALISTS = {"dalangtan": (46351, MARS), "sajama": (25671, MARS), "ellesmere": (61661, MOON)}


# ---------------------------------------------------------------- formato
def f2(x: float) -> str:
    return f"{x:.2f}".replace(".", ",")


def f1(x: float) -> str:
    return f"{x:.1f}".replace(".", ",")


def miles(n: int) -> str:
    return f"{n:,}".replace(",", ".")


# ---------------------------------------------------------------- datos
def load_facts() -> dict:
    b = io.load_bundle(REPO / "data" / "processed")
    val = json.loads((REPO / "data" / "processed" / "validation.json").read_text(encoding="utf-8"))
    facts: dict = {"val": {t["target_id"]: t for t in val["targets"]}}
    facts["analogs"] = pd.read_csv(REPO / "data" / "processed" / "known_analogs.csv")
    facts["maps"] = {t: services.get_map_layer(b, t, DEFAULT_WEIGHTS).cells for t in (MOON, MARS)}
    facts["n_cells"] = int(len(b.grid))
    facts["n_eligible"] = int(facts["maps"][MARS]["eligible"].sum())
    facts["bio_records"] = int(len(pd.read_parquet(REPO / "data" / "processed" / "bio_samples.parquet")))
    ranks = {}
    for t in (MOON, MARS):
        r = services.get_ranking(b, t, DEFAULT_WEIGHTS, hide_known=True, limit=RANKING_LIMIT_MAX)
        ranks[t] = r.items
        allr = services.get_ranking(b, t, DEFAULT_WEIGHTS, hide_known=False, limit=RANKING_LIMIT_MAX)
        facts[f"top_{t}"] = allr.items[0]
        facts[f"all_{t}"] = {i.cell_id: i for i in allr.items}
    fin = {}
    for key, (cid, tid) in FINALISTS.items():
        card = services.get_site_card(b, cid, tid, DEFAULT_WEIGHTS)
        pos = [i.rank for i in ranks[tid] if i.cell_id == cid]
        fin[key] = dict(total=card.scores.total, rank=pos[0] if pos else None, lat=card.header.lat, lon=card.header.lon)
    facts["fin"] = fin
    # lo que el texto afirma, comprobado contra los datos
    assert fin["dalangtan"]["rank"] == 1, "Dalangtan ya no es la 1.ª de Marte fuera de la lista del equipo"
    first_outside = next(i for i in ranks[MOON] if i.country != "Antártida")
    assert first_outside.cell_id == 61661, "Ellesmere ya no es la mejor del polo sur lunar fuera de la Antártida"
    assert facts[f"top_{MOON}"].known_analog and "Ross" in facts[f"top_{MOON}"].known_analog.name, "la 1.ª de la Luna ya no es Ross"
    for t in (MOON, MARS):
        assert facts["val"][t]["result"] == "pass", f"{t} ya no pasa la validación: revisar los textos del póster"
    facts["atacama_rank"] = facts[f"all_{MARS}"].get(23870).rank if 23870 in facts[f"all_{MARS}"] else None
    return facts


# ---------------------------------------------------------------- mapas
VIRIDIS = ["#440154", "#482878", "#3E4A89", "#31688E", "#26828E", "#1F9E89", "#35B779", "#6DCD59", "#B4DE2C", "#FDE725"]
STOPS = np.array([[int(h[i : i + 2], 16) for i in (1, 3, 5)] for h in VIRIDIS], dtype=float)
PX, LAT_TOP, LAT_BOT = 12, 84.0, -90.0


def viridis(v: float) -> np.ndarray:
    v = min(max(v, 0.0), 1.0) * (len(STOPS) - 1)
    i = min(int(v), len(STOPS) - 2)
    return (STOPS[i] * (1 - (v - i)) + STOPS[i + 1] * (v - i)).astype(np.uint8)


def render_map(tid: str, cells: pd.DataFrame, analogs: pd.DataFrame, out: Path) -> None:
    w, h = 360 * PX, int((LAT_TOP - LAT_BOT) * PX)
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:] = (16, 24, 39)
    for lat, lon, tot, ok in zip(cells.lat, cells.lon, cells.total, cells.eligible):
        x0, y0 = int((lon - 0.5 + 180) * PX), int((LAT_TOP - (lat + 0.5)) * PX)
        img[y0 : y0 + PX - 1, x0 : x0 + PX - 1] = viridis(tot) if (ok and not np.isnan(tot)) else (42, 51, 69)
    im = Image.fromarray(img)
    d = ImageDraw.Draw(im)

    def xy(lat, lon):
        return (lon + 180) * PX, (LAT_TOP - lat) * PX

    for _, a in analogs[analogs.target_id == tid].iterrows():
        x, y = xy(a.lat, a.lon)
        r = PX * 2.6
        d.ellipse([x - r, y - r, x + r, y + r], outline=(255, 255, 255), width=int(PX * 0.55))
    for key, (cid, t) in FINALISTS.items():
        if t != tid:
            continue
        row = cells[cells.cell_id == cid].iloc[0]
        x, y = xy(row.lat, row.lon)
        r = PX * 2.4
        d.rectangle([x - r, y - r, x + r, y + r], outline=(232, 136, 74), width=int(PX * 0.7))
    im.save(out, optimize=True)


def pin(lat: float, lon: float, text: str, side: str, size: float, orange: bool = False, dy: float = 0.0) -> str:
    left = (lon + 180) / 360 * 100
    top = (LAT_TOP - lat) / (LAT_TOP - LAT_BOT) * 100
    off = 2.3 if side == "r" else -2.3
    tf = "translate(0,-50%)" if side == "r" else "translate(-100%,-50%)"
    return (
        f'<div class="pin{" o" if orange else ""}" style="left:{left + off:.2f}%;top:{top + dy:.2f}%;font-size:{size}pt;'
        f'transform:{tf}">{text}</div>'
    )


def map_pins(tid: str, fin: dict, size: float, short: bool = False) -> str:
    if tid == MOON:
        e = fin["ellesmere"]
        return pin(e["lat"], e["lon"], "Ellesmere", "r", size, True, dy=2.5) + pin(-77.55, 167.5, "Isla de Ross", "l", size, dy=-9)
    d = fin["dalangtan"]
    alt = "Altiplano" if short else "Sajama · Atacama · Licancabur"
    return pin(d["lat"], d["lon"], "Dalangtan", "r", size, True) + pin(-18.5, -68.5, alt, "l", size, True, dy=4)


# ---------------------------------------------------------------- piezas HTML
SHORT = {
    "ross_island": "Isla de Ross",
    "concordia_dome_c": "Estación Concordia",
    "haughton_crater": "Cráter Haughton",
    "askja_iceland": "Caldera de Askja",
    "licancabur_altiplano": "Licancabur (Altiplano)",
    "atacama_yungay": "Atacama (Yungay)",
    "death_valley_ubehebe": "Valle de la Muerte",
    "rio_tinto": "Río Tinto",
    "mcmurdo_dry_valleys": "Valles Secos de McMurdo",
}
RES_LABEL = {"pass": "pasa", "fail": "no pasa", "info": "informativo"}
RES_SHORT = {"pass": "pasa", "fail": "falla", "info": "info"}


def val_block(facts: dict, tid: str, title: str, short: bool = False) -> str:
    labels = RES_SHORT if short else RES_LABEL
    t = facts["val"][tid]
    rows = sorted(t["analogs"], key=lambda a: (a["result"] == "info", -a["percentile"]))
    out = [
        f'<div class="vh"><b>{title}</b><span class="badge pass">PASA · {t["covered_passed"]} de {t["covered_total"]}</span></div>',
        '<div class="val">',
    ]
    for a in rows:
        r = a["result"]
        out.append(
            f'<div class="row"><div class="nm">{SHORT[a["analog_id"]]}</div>'
            f'<div class="track"><div class="bar {r}" style="width:{a["percentile"]:.1f}%"></div><div class="cut" style="left:90%"></div></div>'
            f'<div class="vals"><span class="num">{f1(a["percentile"])}</span><span class="rk">#{miles(a["best_rank"])}</span>'
            f'<span class="tag {r}">{labels[r]}</span></div></div>'
        )
    out.append("</div>")
    return "".join(out)


def legend_html() -> str:
    return (
        '<div class="legend">'
        '<div class="lab">Puntaje total <span style="margin-left:1mm">0</span><span class="ramp"></span>1</div>'
        '<div class="lab"><span class="sw ring"></span>análogo que el equipo ya conoce</div>'
        '<div class="lab"><span class="sw sq"></span>candidata finalista</div>'
        '<div class="lab"><span class="sw gray"></span>sin datos suficientes</div>'
        "</div>"
    )


def qr_html(url: str | None, css_class: str) -> str:
    if url:
        try:
            import segno
        except ImportError:
            print("aviso: falta segno (pip install segno); sigo sin QR", file=sys.stderr)
            url = None
        else:
            uri = segno.make(url, error="m").svg_data_uri(scale=6, border=1, dark="#0F1623", light="#F2F0E8")
            label = url.replace("https://", "").replace(".onrender", "<wbr>.onrender").replace(".streamlit", "<wbr>.streamlit")
            return f'<div class="{css_class}"><img src="{uri}" alt="QR"><span>{label}</span></div>'
    return f'<div class="{css_class} noqr"><span>Demo en vivo<br>y código abierto</span></div>'


# ---------------------------------------------------------------- póster
POSTER_CSS = """
@page { size: 297mm 420mm; margin: 0 }
.poster { width: 297mm; height: 420mm; display: flex; flex-direction: column; overflow: hidden; background: var(--paper); }
.top { padding: 10mm 14mm 0; }
.toprow { display: flex; justify-content: space-between; align-items: center; }
.toprow img { height: 16mm; display: block; }
.event { text-align: right; font: 700 10.5pt/1.55 'Bahnschrift'; letter-spacing: .16em; text-transform: uppercase; color: var(--soft); }
.event b { color: var(--paper); font-weight: 700; }
.poster h1 { font-size: 34pt; line-height: 1.06; letter-spacing: -.012em; margin-top: 6mm; max-width: 265mm; }
.lead { font-size: 14pt; line-height: 1.4; color: var(--soft); margin-top: 3.5mm; max-width: 269mm; }
.lead b { color: var(--paper); }
.maps { display: grid; grid-template-columns: 1fr 1fr; gap: 8mm; padding: 5mm 14mm 0; }
.mh { display: flex; align-items: baseline; gap: 3mm; margin-bottom: 2.4mm; }
.mh b { font: 700 15pt 'Bahnschrift'; }
.mh span { font-size: 10pt; color: var(--soft); }
.cap { margin-top: 2.2mm; font-size: 10pt; line-height: 1.36; color: var(--soft); }
.cap b { color: var(--paper); }
.legend { padding: 3.5mm 14mm 5.5mm; column-gap: 8mm; row-gap: 2mm; font-size: 9.6pt; }
.legend .lab { display: flex; align-items: center; gap: 2mm; }
.legend .ramp { width: 52mm; height: 3.4mm; margin: 0 1mm; }
.legend .sw.ring { width: 4.2mm; height: 4.2mm; } .legend .sw.sq, .legend .sw.gray { width: 4mm; height: 4mm; }
.body { flex: 1; padding: 7mm 14mm 0; display: flex; flex-direction: column; justify-content: space-between; gap: 4mm; min-height: 0; }
.poster h2 { font-size: 17pt; line-height: 1.1; margin-bottom: 2.6mm; }
.poster h2 small { display: block; font: 400 10.4pt/1.36 'Segoe UI'; color: var(--softd); margin-top: 1.3mm; }
.steps { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8mm; }
.step { display: flex; column-gap: 3.5mm; align-items: flex-start; }
.step .n { width: 11mm; height: 11mm; border-radius: 50%; background: var(--navy); color: var(--paper); font: 700 15pt 'Bahnschrift';
           display: flex; align-items: center; justify-content: center; flex: none; }
.step h3 { font-size: 13.5pt; line-height: 1.15; margin: 0 0 1.4mm; padding-top: 1.2mm; }
.step p { font-size: 10pt; line-height: 1.36; }
.dims { display: grid; grid-template-columns: repeat(5, 1fr); gap: 3mm; margin-top: 3.5mm; }
.dim { background: #fff; border-radius: 1.6mm; padding: 2.2mm 3mm 2.4mm; border-top: 1.3mm solid var(--teal); }
.dim b { display: block; font: 700 11.8pt/1.15 'Bahnschrift'; }
.dim span { display: block; font-size: 9.2pt; line-height: 1.3; color: var(--softd); margin-top: .8mm; }
.dim .w { display: inline-block; margin-top: 1.6mm; font: 700 9pt 'Bahnschrift'; color: var(--ink); background: var(--paper2); border-radius: 5mm; padding: .4mm 2.4mm; }
.cols { display: grid; grid-template-columns: 1.1fr 1fr; gap: 10mm; }
.vh { display: flex; align-items: center; gap: 3mm; margin: 3mm 0 1.8mm; }
.vh:first-of-type { margin-top: 0; }
.vh b { font: 700 11.5pt 'Bahnschrift'; }
.badge { font-size: 8.5pt; padding: .5mm 2.6mm; }
.val .row { grid-template-columns: 41mm 1fr 34mm; column-gap: 3mm; }
.val { row-gap: .2mm; }
.val .nm { font-size: 9.8pt; }
.val .track { height: 3mm; }
.val .vals { font-size: 9.2pt; display: flex; align-items: baseline; gap: 1.6mm; }
.val .num { font-size: 10.6pt; } .val .rk { color: var(--softd); font-size: 8.4pt; }
.valnote { font-size: 9.2pt; line-height: 1.36; color: var(--softd); margin-top: 2.4mm; }
.valnote b { color: var(--ink); }
.fin { display: grid; grid-template-columns: 17mm 1fr; column-gap: 3.4mm; background: #fff; border-radius: 2mm; padding: 2.2mm 3.2mm; margin-bottom: 2.2mm; }
.fin .sc { font: 700 21pt 'Bahnschrift'; line-height: 1; }
.fin .sc small { display: block; font: 650 7.2pt 'Segoe UI'; letter-spacing: .05em; color: var(--softd); margin-top: 1.2mm; text-transform: uppercase; }
.fin h3 { font-size: 11.2pt; line-height: 1.15; }
.fin p { font-size: 9.2pt; line-height: 1.32; margin-top: .8mm; }
.tg { display: inline-block; font: 700 7.4pt 'Bahnschrift'; letter-spacing: .09em; border-radius: 5mm; padding: .3mm 2mm; margin-right: 1.6mm; color: #fff; vertical-align: 1px; }
.tg.mars { background: var(--orange); } .tg.moon { background: var(--navy3); }
.limrow { display: grid; grid-template-columns: 46mm 1fr; column-gap: 7mm; align-items: start; }
.limrow h2 { margin: 0; }
.lim { display: grid; grid-template-columns: repeat(4, 1fr); gap: 5mm; }
.lim div { border-left: 1.2mm solid var(--orange); padding-left: 3.2mm; }
.lim b { display: block; font: 700 11.2pt/1.18 'Bahnschrift'; margin-bottom: 1mm; }
.lim p { font-size: 9.4pt; line-height: 1.33; }
.foot { background: var(--navy); color: var(--paper); padding: 5mm 14mm 6mm; display: grid; grid-template-columns: 1fr 28mm; column-gap: 10mm; align-items: center; margin-top: 5mm; }
.team { display: grid; grid-template-columns: repeat(4, 1fr); gap: 5mm; }
.team b { display: block; font: 700 12pt 'Bahnschrift'; }
.team span { font-size: 8.7pt; line-height: 1.3; color: var(--soft); display: block; margin-top: .6mm; }
.small { font-size: 8.4pt; line-height: 1.4; color: var(--soft); margin-top: 3mm; }
.qr { width: 28mm; height: 28mm; border-radius: 2mm; background: var(--paper); color: var(--ink); display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 1.5mm; text-align: center; }
.qr img { width: 22mm; height: 22mm; display: block; } .qr span { font: 650 6.4pt 'Segoe UI'; margin-top: .6mm; word-break: normal; }
.qr.noqr span { font: 700 9.5pt/1.25 'Bahnschrift'; }
"""


def poster_html(f: dict, url: str | None) -> str:
    fin = f["fin"]
    ross = f[f"top_{MOON}"]
    dal = f["fin"]["dalangtan"]
    pins = {t: map_pins(t, fin, 8.2) for t in (MOON, MARS)}
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Terra Analog Index · póster A3</title>
<style>{(HERE / 'estilos.css').read_text(encoding='utf-8')}{POSTER_CSS}</style></head><body>
<div class="poster">
 <div class="dark">
  <div class="top">
   <div class="toprow"><img src="logo-dark.svg" alt="Terra Analog Index">
    <div class="event"><b>NASA Space Apps Challenge 2026</b><br>Equipo sigsegv</div></div>
   <h1>¿Qué lugares de la Tierra se parecen más a la <span class="accent">Luna</span> y a <span class="accent">Marte</span>?</h1>
   <p class="lead"><b>{miles(f['n_cells'])} celdas de 1°</b> puntuadas contra el polo sur lunar y el cráter Jezero: <b>en qué se parecen y en qué no</b>.</p>
  </div>
  <div class="maps">
   <div class="mapcard"><div class="mh"><b>Luna · polo sur</b><span>puntaje total, pesos iniciales</span></div>
    <div class="mapbox"><img src="map_{MOON}.png" alt="">{pins[MOON]}</div>
    <p class="cap"><b>La 1.ª es la isla de Ross ({f2(ross.total)})</b>, un análogo lunar que ya se usa. Fuera de la Antártida, Ellesmere (Canadá) con {f2(fin['ellesmere']['total'])}.</p></div>
   <div class="mapcard"><div class="mh"><b>Marte · cráter Jezero</b><span>puntaje total, pesos iniciales</span></div>
    <div class="mapbox"><img src="map_{MARS}.png" alt="">{pins[MARS]}</div>
    <p class="cap"><b>La 1.ª es Dalangtan, China ({f2(dal['total'])})</b>: no estaba en nuestra lista y la literatura ya la estudia como análogo. Atacama (Yungay) queda {f['atacama_rank']}.ª.</p></div>
  </div>
  {legend_html()}
 </div>
 <div class="body">
  <section>
   <h2>Cómo funciona</h2>
   <div class="steps">
    <div class="step"><div class="n">1</div><div><h3>Medimos la Tierra</h3><p>De cada celda medimos terreno, temperatura, agua y hielo, y polvo y viento con datos de MODIS, GPM IMERG, MERRA-2 y ETOPO. Los destinos salen de LRO, MOLA y MEDA.</p></div></div>
    <div class="step"><div class="n">2</div><div><h3>Puntuamos contra el destino</h3><p>Cada variable recibe de 0 a 1 con una de tres reglas auditables: parecido, direccional o presencia de hielo. Sumamos {miles(f['bio_records'])} registros de extremófilos de NCBI.</p></div></div>
    <div class="step"><div class="n">3</div><div><h3>Rankeamos y explicamos</h3><p>El ranking se recalcula en vivo con los pesos que elegís. Cada ficha dice en qué se parece la celda, en qué se aleja y qué no replica ningún lugar de la Tierra.</p></div></div>
   </div>
   <div class="dims">
    <div class="dim" style="border-color:#3E4A89"><b>Terreno</b><span>pendiente y rugosidad</span><i class="w">peso 1,0</i></div>
    <div class="dim" style="border-color:#31688E"><b>Temperatura</b><span>mínima y rango diario</span><i class="w">peso 1,0</i></div>
    <div class="dim" style="border-color:#1F9E89"><b>Agua y hielo</b><span>lluvia, nieve y hielo</span><i class="w">peso 1,0</i></div>
    <div class="dim" style="border-color:#6DCD59"><b>Polvo y viento</b><span>solo Marte</span><i class="w">peso 0,5</i></div>
    <div class="dim" style="border-color:#E8884A"><b>Interés astrobiológico</b><span>registros de extremófilos</span><i class="w">peso 0,5</i></div>
   </div>
  </section>
  <section class="cols">
   <div>
    <h2>¿Redescubre lo que la comunidad ya usa?<small>Un análogo pasa si su mejor celda queda en el percentil 90 o más (la línea). Un destino pasa si hay dos cubiertos y pasan dos tercios.</small></h2>
    {val_block(f, MARS, 'Marte · Jezero')}
    {val_block(f, MOON, 'Luna · polo sur')}
    <p class="valnote"><b>Lo que falla se muestra:</b> Haughton y McMurdo no pasan y no ajustamos hasta que «dé bien». Los análogos elegidos por su geología o su química no cuentan: el índice no mide eso.</p>
   </div>
   <div>
    <h2>Tres candidatas para verificar<small>Hipótesis, no hallazgos; cada una tiene ficha con fuentes en la app.</small></h2>
    <div class="fin"><div class="sc">{f2(dal['total'])}<small>puesto {dal['rank']}</small></div><div><h3><span class="tg mars">MARTE</span>Playa de Dalangtan, Qaidam (China)</h3><p>Sulfatos, cloruros y percloratos; se estudia como análogo desde 2008. Falla: mínima de −19 °C frente a −80 °C en Jezero.</p></div></div>
    <div class="fin"><div class="sc">{f2(fin['sajama']['total'])}<small>puesto {fin['sajama']['rank']}</small></div><div><h3><span class="tg mars">MARTE</span>Altiplano norte, Sajama (Bolivia)</h3><p>Puna de 4.200 a 6.542 m; no la encontramos descrita como análogo. Falla: llueve mucho más que en Jezero.</p></div></div>
    <div class="fin"><div class="sc">{f2(fin['ellesmere']['total'])}<small>puesto {fin['ellesmere']['rank']}</small></div><div><h3><span class="tg moon">LUNA</span>Norte de Ellesmere (Canadá)</h3><p>Desierto polar con permafrost y hielo en el suelo. Falla: −37 °C de mínima, no −223 °C.</p></div></div>
   </div>
  </section>
  <section class="limrow">
   <h2>Antes de creerle a un puntaje</h2>
   <div class="lim">
    <div><b>Un puntaje direccional no mide distancia</b><p>Un 0,95 en temperatura significa «más frío que el 95 % de la tierra firme», no «95 % igual a la Luna».</p></div>
    <div><b>Hay cosas que ningún lugar replica</b><p>Gravedad, vacío o atmósfera tenue de CO₂, radiación y regolito abrasivo. Cada ficha lo lista.</p></div>
    <div><b>La biología mide dónde se muestreó</b><p>Los sitios famosos suben y los inexplorados quedan en 0. Por eso su peso inicial es 0,5.</p></div>
    <div><b>Celdas de 110 km, un año de datos</b><p>Un cráter o un salar se diluye en su celda. Datos de 2024; faltan geología, mineralogía y subsuelo.</p></div>
   </div>
  </section>
 </div>
 <div class="foot">
  <div>
   <div class="team">
    <div><b>Juanma</b><span>repositorio y grilla, similitud, ranking, ficha y despliegue</span></div>
    <div><b>Alan</b><span>capa biológica, perfiles de los destinos, puntaje, validación y mapa</span></div>
    <div><b>Santino</b><span>criterios científicos, fuentes, textos y pitch</span></div>
    <div><b>Santiago</b><span>esqueleto de la app, mapas de control, README y video</span></div>
   </div>
   <p class="small">Código abierto (GNU GPL v3); los datos conservan sus licencias (NASA, NOAA, USGS y NCBI). Usamos Claude Code (Anthropic) como asistente de programación.</p>
  </div>
  {qr_html(url, 'qr')}
 </div>
</div></body></html>"""


# ---------------------------------------------------------------- tríptico
TRI_CSS = """
@page { size: 297mm 210mm; margin: 0 }
.sheet { width: 297mm; height: 210mm; display: grid; overflow: hidden; break-after: page; page-break-after: always; }
.sheet:last-child { break-after: auto; page-break-after: auto; }
.sheet.out { grid-template-columns: 97mm 100mm 100mm; } .sheet.in { grid-template-columns: 100mm 100mm 97mm; }
.panel { padding: 11mm 9.5mm 9mm; overflow: hidden; display: flex; flex-direction: column; background: var(--paper); }
.panel.dark { background: var(--navy); color: var(--paper); }
.panel.alt { background: #EAE6D8; }
.tri h2 { font-size: 15pt; line-height: 1.1; margin-bottom: 3mm; }
.tri h3 { font-size: 10.6pt; line-height: 1.15; margin-bottom: 1mm; }
.tri p, .tri li { font-size: 9.6pt; line-height: 1.38; }
.tri p + p { margin-top: 2mm; }
.tri .kick { font: 700 8pt 'Bahnschrift'; letter-spacing: .16em; text-transform: uppercase; color: var(--orange); margin-bottom: 2mm; }
.cover { justify-content: space-between; }
.cover .mark { width: 60mm; display: block; margin: 8mm auto 0; }
.cover h1 { font-size: 27pt; line-height: 1.02; letter-spacing: -.01em; }
.cover .tag { font-size: 12.5pt; line-height: 1.35; color: var(--soft); margin-top: 3.5mm; }
.cover .ev { font: 700 8.6pt/1.6 'Bahnschrift'; letter-spacing: .15em; text-transform: uppercase; color: var(--soft); border-top: .3mm solid #3a4660; padding-top: 3mm; }
.cover .ev b { color: var(--paper); font-weight: 700; }
.stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 2.5mm; margin: 4mm 0; }
.stat { background: #fff; border-radius: 1.6mm; padding: 2.6mm 2mm; text-align: center; }
.stat b { display: block; font: 700 17pt/1 'Bahnschrift'; } .stat span { display: block; font-size: 7.6pt; line-height: 1.25; color: var(--softd); margin-top: 1mm; }
.dest { background: #fff; border-radius: 1.6mm; padding: 2.6mm 3mm; margin-top: 2.4mm; border-left: 1.2mm solid var(--orange); }
.dest p { font-size: 9pt; line-height: 1.34; }
.tsteps { display: grid; row-gap: 3mm; margin-bottom: 4mm; }
.ts { display: grid; grid-template-columns: 8mm 1fr; column-gap: 2.6mm; }
.ts .n { width: 8mm; height: 8mm; border-radius: 50%; background: var(--navy); color: var(--paper); font: 700 11pt 'Bahnschrift'; display: flex; align-items: center; justify-content: center; }
.tdims { display: grid; grid-template-columns: 1fr auto; row-gap: 1.2mm; font-size: 9.2pt; line-height: 1.25; }
.tdims b { font-weight: 650; } .tdims i { font-style: normal; font: 700 8.4pt 'Bahnschrift'; background: var(--paper2); border-radius: 4mm; padding: .2mm 2mm; justify-self: end; }
.tdims span { color: var(--softd); }
.howto { margin-top: 4mm; background: var(--navy); color: var(--paper); border-radius: 1.8mm; padding: 3mm 3.4mm; }
.howto b { font: 700 9.6pt 'Bahnschrift'; display: block; margin-bottom: 1.2mm; color: var(--orange); letter-spacing: .06em; text-transform: uppercase; }
.howto p { font-size: 9pt; line-height: 1.36; }
.tleg { margin: -1mm 0 3mm; } .tleg .legend { font-size: 7.6pt; column-gap: 3mm; row-gap: 1mm; color: var(--softd); }
.tleg .legend .lab { display: flex; align-items: center; gap: 1.2mm; } .tleg .ramp { width: 16mm; height: 2.4mm; margin: 0 .6mm; }
.tleg .sw.ring { width: 3mm; height: 3mm; border-color: var(--ink); } .tleg .sw.sq, .tleg .sw.gray { width: 2.8mm; height: 2.8mm; }
.tmap { margin-bottom: 1mm; } .tmap .mapbox > img { border-radius: 1.2mm; }
.tmap p { font-size: 8.8pt; line-height: 1.32; margin: 1.4mm 0 3.2mm; }
.tmap .ttl { font: 700 10pt 'Bahnschrift'; margin-bottom: 1.2mm; }
.tfin { display: grid; grid-template-columns: 11mm 1fr; column-gap: 2.4mm; margin-top: 2.2mm; align-items: start; }
.tfin .sc { font: 700 14pt/1 'Bahnschrift'; } .tfin h3 { font-size: 9.8pt; margin-bottom: .3mm; } .tfin p { font-size: 8.8pt; line-height: 1.28; }
.tri .valw .val .row { grid-template-columns: 31mm 1fr 27mm; column-gap: 2mm; } .tri .val .vals { white-space: nowrap; }
.tri .val .nm { font-size: 8.6pt; } .tri .val .track { height: 2.8mm; }
.tri .val .vals { font-size: 7.8pt; display: flex; align-items: baseline; gap: 1.2mm; } .tri .val .num { font-size: 8.8pt; } .tri .val .rk { color: var(--softd); font-size: 7pt; }
.tri .vh { display: flex; align-items: center; gap: 2.4mm; margin: 2.4mm 0 1.4mm; } .tri .vh b { font: 700 9.6pt 'Bahnschrift'; } .tri .badge { font-size: 7.4pt; padding: .4mm 2.2mm; }
.tri .lims { margin-top: 3.4mm; display: grid; row-gap: 2.1mm; }
.tri .lims div { border-left: 1mm solid var(--orange); padding-left: 2.6mm; } .tri .lims b { font: 700 9.4pt/1.15 'Bahnschrift'; display: block; } .tri .lims p { font-size: 8.8pt; line-height: 1.28; }
.back h2 { font-size: 15pt; } .back .team { display: grid; row-gap: 2.4mm; margin-top: 2mm; }
.back .team b { font: 700 10pt 'Bahnschrift'; } .back .team span { display: block; font-size: 8pt; line-height: 1.28; color: var(--soft); }
.back p { font-size: 8.2pt; line-height: 1.38; color: var(--soft); } .back p b { color: var(--paper); }
.tqr { width: 38mm; height: 38mm; background: var(--paper); color: var(--ink); border-radius: 2mm; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 1.6mm; text-align: center; margin: 3mm 0 4mm; }
.tqr img { width: 31mm; height: 31mm; display: block; } .tqr span { font: 650 6.4pt 'Segoe UI'; margin-top: .6mm; word-break: normal; }
.tqr.noqr span { font: 700 11pt/1.25 'Bahnschrift'; }
.back .sp { flex: 1; }
"""


def tri_html(f: dict, url: str | None, sheets: tuple[str, ...]) -> str:
    fin = f["fin"]
    ross = f[f"top_{MOON}"]
    dal = fin["dalangtan"]
    pm, pr = map_pins(MOON, fin, 6.2, True), map_pins(MARS, fin, 6.2, True)
    flap = f"""<div class="panel alt tri">
  <div class="kick">¿Para qué sirve?</div>
  <h2>Probar en la Tierra lo que irá a la Luna y a Marte</h2>
  <p>Antes de mandar instrumentos, rovers o astronautas, los equipos de exploración ensayan en lugares de la Tierra que se parecen en algo al destino: Atacama, la Antártida, el Ártico canadiense. Son los <b>análogos</b>.</p>
  <p>Pero ¿cuánto se parece cada lugar, en qué y en qué no? <b>Terra Analog Index</b> lo mide con el mismo criterio para toda la tierra firme y lo explica.</p>
  <div class="stats"><div class="stat"><b>{miles(f['n_cells'])}</b><span>celdas de 1° (unos 110 km)</span></div><div class="stat"><b>5</b><span>dimensiones, con pesos que se mueven</span></div><div class="stat"><b>2</b><span>destinos</span></div></div>
  <div class="dest"><h3>Luna · polo sur</h3><p>Al sur de 85° S: cráteres en sombra permanente con hielo de agua y zonas casi siempre iluminadas. Destino de las misiones Artemis.</p></div>
  <div class="dest"><h3>Marte · cráter Jezero</h3><p>Cráter de unos 45 km con un antiguo lago y su delta: el sitio del rover Perseverance.</p></div>
 </div>"""
    back = f"""<div class="panel dark back tri">
  <div class="kick">Probalo</div>
  <h2>Elegí un destino, movés los pesos y mirá qué sale</h2>
  {qr_html(url, 'tqr')}
  <h2 style="font-size:12pt;margin-bottom:1.4mm">Equipo sigsegv</h2>
  <div class="team">
   <div><b>Juanma</b><span>repositorio y grilla, similitud, ranking, ficha y despliegue</span></div>
   <div><b>Alan</b><span>capa biológica, perfiles de los destinos, puntaje, validación y mapa</span></div>
   <div><b>Santino</b><span>criterios científicos, fuentes, textos y pitch</span></div>
   <div><b>Santiago</b><span>esqueleto de la app, mapas de control, README y video</span></div>
  </div>
  <div class="sp"></div>
  <p>Código abierto (GNU GPL v3); los datos conservan sus licencias: NASA, NOAA, USGS y NCBI. Usamos <b>Claude Code</b> (Anthropic) como asistente de programación.</p>
 </div>"""
    cover = """<div class="panel dark cover tri">
  <div><img class="mark" src="logo-mark.svg" alt=""></div>
  <div><h1>Terra Analog Index</h1><p class="tag">¿Qué lugares de la Tierra se parecen más a la <span class="accent">Luna</span> y a <span class="accent">Marte</span>?</p></div>
  <div class="ev"><b>NASA Space Apps Challenge 2026</b><br>Equipo sigsegv</div>
 </div>"""
    p1 = f"""<div class="panel tri">
  <div class="kick">Cómo funciona</div>
  <h2>Tres pasos</h2>
  <div class="tsteps">
   <div class="ts"><div class="n">1</div><div><h3>Medimos la Tierra</h3><p>Cada celda de 1° con datos de MODIS, GPM IMERG, MERRA-2, ETOPO y NCBI BioSample. Los destinos, de LRO, MOLA y MEDA.</p></div></div>
   <div class="ts"><div class="n">2</div><div><h3>Puntuamos contra el destino</h3><p>De 0 a 1 por variable, con tres reglas auditables: parecido, direccional o presencia de hielo.</p></div></div>
   <div class="ts"><div class="n">3</div><div><h3>Rankeamos y explicamos</h3><p>El ranking se recalcula con tus pesos. Cada ficha dice en qué se parece, en qué falla y con qué fuentes.</p></div></div>
  </div>
  <h3>Las dimensiones y su peso inicial</h3>
  <div class="tdims">
   <div><b>Terreno</b> <span>pendiente, rugosidad</span></div><i>1,0</i>
   <div><b>Temperatura</b> <span>mínima, rango diario</span></div><i>1,0</i>
   <div><b>Agua y hielo</b> <span>lluvia, nieve, hielo</span></div><i>1,0</i>
   <div><b>Polvo y viento</b> <span>solo Marte</span></div><i>0,5</i>
   <div><b>Interés astrobiológico</b> <span>extremófilos en NCBI</span></div><i>0,5</i>
  </div>
  <div class="howto"><b>En la app</b><p>1. Elegí el destino. 2. Movés los pesos. 3. Mirá el mapa y las 20 mejores celdas. 4. Tocá una fila para abrir la ficha: radar, valores de la Tierra frente al destino, fuentes y límites. Podés bajar el ranking en CSV.</p></div>
 </div>"""
    p2 = f"""<div class="panel alt tri">
  <div class="kick">Qué encontramos</div>
  <h2>Dos destinos, dos rankings</h2>
  <div class="tleg">{legend_html()}</div>
  <div class="tmap"><div class="ttl">Luna · polo sur</div><div class="mapbox"><img src="map_{MOON}.png" alt="">{pm}</div>
   <p><b>1.ª: isla de Ross ({f2(ross.total)})</b>, un análogo que ya se usa. Fuera de la Antártida, Ellesmere (Canadá) con {f2(fin['ellesmere']['total'])}.</p></div>
  <div class="tmap"><div class="ttl">Marte · cráter Jezero</div><div class="mapbox"><img src="map_{MARS}.png" alt="">{pr}</div>
   <p><b>1.ª: Dalangtan, China ({f2(dal['total'])})</b>. No estaba en nuestra lista y la literatura ya la estudia como análogo.</p></div>
  <h3 style="margin-top:2mm">Candidatas para verificar</h3>
  <div class="tfin"><div class="sc">{f2(dal['total'])}</div><div><h3>Playa de Dalangtan (China)</h3><p>Sales y percloratos; falla en el frío.</p></div></div>
  <div class="tfin"><div class="sc">{f2(fin['sajama']['total'])}</div><div><h3>Sajama (Bolivia)</h3><p>Puna a 4.200–6.542 m; llueve más que en Jezero.</p></div></div>
  <div class="tfin"><div class="sc">{f2(fin['ellesmere']['total'])}</div><div><h3>Ellesmere (Canadá)</h3><p>Permafrost; −37 °C de mínima, no −223 °C.</p></div></div>
 </div>"""
    p3 = f"""<div class="panel tri">
  <div class="kick">Cuánto confiar</div>
  <h2>¿Redescubre lo que ya se usa?</h2>
  <p>Un análogo pasa si su mejor celda queda en el percentil 90 o más (la línea). Un destino pasa si dos están cubiertos y pasan dos tercios.</p>
  <div class="valw">{val_block(f, MARS, 'Marte', True)}{val_block(f, MOON, 'Luna', True)}</div>
  <p style="margin-top:2.4mm"><b>Lo que falla se muestra</b> y no ajustamos hasta que «dé bien».</p>
  <h3 style="margin-top:4mm">Límites</h3>
  <div class="lims">
   <div><b>Un puntaje direccional no mide distancia</b><p>0,95 en temperatura es «más frío que el 95 % de la Tierra», no «95 % igual a la Luna».</p></div>
   <div><b>Ningún lugar replica todo</b><p>Gravedad, vacío o atmósfera tenue, radiación y regolito.</p></div>
   <div><b>La biología mide dónde se muestreó</b><p>Por eso pesa 0,5.</p></div>
   <div><b>Celdas de 110 km, datos de 2024</b><p>Faltan geología, mineralogía y subsuelo.</p></div>
  </div>
 </div>"""
    parts = []
    if "out" in sheets:
        parts.append(f'<div class="sheet out">{flap}{back}{cover}</div>')
    if "in" in sheets:
        parts.append(f'<div class="sheet in">{p1}{p2}{p3}</div>')
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Terra Analog Index · tríptico A4</title>
<style>{(HERE / 'estilos.css').read_text(encoding='utf-8')}{TRI_CSS}</style></head><body>{''.join(parts)}</body></html>"""


# ---------------------------------------------------------------- Edge
def find_edge() -> str:
    for c in EDGE_CANDIDATES:
        if Path(c).exists():
            return c
    sys.exit("No encuentro Microsoft Edge: hace falta para imprimir el HTML a PDF")


def edge(args: list[str]) -> None:
    prof = BUILD / "edge_profile"
    cmd = [find_edge(), "--headless=new", "--disable-extensions", "--no-first-run", f"--user-data-dir={prof}", "--hide-scrollbars", *args]
    subprocess.run(cmd, check=True, timeout=180, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def to_pdf(html: Path, pdf: Path) -> None:
    edge(["--no-pdf-header-footer", f"--print-to-pdf={pdf}", "--virtual-time-budget=20000", html.as_uri()])


def to_png(html: Path, png: Path, w_mm: float, h_mm: float, scale: float) -> None:
    w, h = round(w_mm / 25.4 * 96) + 2, round(h_mm / 25.4 * 96) + 2
    raw = BUILD / (png.stem + "_raw.png")
    edge([f"--screenshot={raw}", f"--window-size={w},{h}", f"--force-device-scale-factor={scale}", "--virtual-time-budget=20000", html.as_uri()])
    im = Image.open(raw)
    im.crop((0, 0, round(w_mm / 25.4 * 96 * scale), round(h_mm / 25.4 * 96 * scale))).save(png, optimize=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", help="enlace de la app desplegada: agrega el QR")
    ap.add_argument("--solo", choices=["poster", "triptico"], help="genera solo una de las dos piezas")
    ap.add_argument("--sin-png", action="store_true", help="no genera las vistas PNG")
    a = ap.parse_args()

    BUILD.mkdir(exist_ok=True)
    for svg in ("logo-dark.svg", "logo-mark.svg"):
        shutil.copy(HERE / svg, BUILD / svg)
    facts = load_facts()
    for t in (MOON, MARS):
        render_map(t, facts["maps"][t], facts["analogs"], BUILD / f"map_{t}.png")

    if a.solo != "triptico":
        h = BUILD / "poster.html"
        h.write_text(poster_html(facts, a.url), encoding="utf-8")
        to_pdf(h, OUT_DIR / "poster_A3.pdf")
        if not a.sin_png:
            to_png(h, OUT_DIR / "poster_A3.png", 297, 420, 2)
    if a.solo != "poster":
        h = BUILD / "triptico.html"
        h.write_text(tri_html(facts, a.url, ("out", "in")), encoding="utf-8")
        to_pdf(h, OUT_DIR / "triptico_A4.pdf")
        if not a.sin_png:
            for side, name in (("out", "afuera"), ("in", "adentro")):
                hs = BUILD / f"tri_{side}.html"
                hs.write_text(tri_html(facts, a.url, (side,)), encoding="utf-8")
                to_png(hs, OUT_DIR / f"triptico_{name}.png", 297, 210, 3)
    print("listo:", sorted(p.name for p in OUT_DIR.iterdir() if p.suffix in (".pdf", ".png")))


if __name__ == "__main__":
    main()
