"""Pestaña Método (design 10.7, TAI-34): los textos de content/method.md y las tablas que salen de los archivos.

Los textos fijos los escribe Santino en content/method.md; acá se parten por encabezados. Las cifras no se
escriben a mano en ningún lado: salen de targets.json, manifest.json y validation.json. Es puro salvo por leer
content/method.md. La vista (ui/method_view.py) solo dibuja lo que arman estas funciones.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from tai.cards import VAR_LABELS, earth_source_names, fmt_num
from tai.constants import PHYSICAL_VARS
from tai.models import Manifest, Target, TargetValidation, ValidationReport

METHOD_PATH = Path("content") / "method.md"

# Encabezados de method.md (`## ...`), en el orden en que la pestaña los muestra (design 10.7).
SECTIONS = ("Qué hace", "Datos usados", "Cómo se calcula", "Validación", "Límites", "Créditos")

NO_DATA = "sin dato"

# Cómo se llama cada regla de puntaje (design 5.1) y cada tipo de fuente en pantalla.
RULE_LABELS = {
    "overlap": "Parecido si cae dentro del rango",
    "directional_low": "Premia los valores más bajos de la Tierra",
    "directional_high": "Premia los valores más altos de la Tierra",
    "presence": "Premia que haya",
    "absence": "Premia que no haya",
}
SOURCE_TYPE_LABELS = {"measured": "Medido", "literature": "Literatura", "definition": "Definición"}

COVERED_LABELS = {"yes": "Sí", "partial": "Parcial", "no": "No"}
TARGET_RESULT_LABELS = {"pass": "Pasa", "fail": "Falla", "insufficient": "Datos insuficientes"}

# Qué significa cada resultado de la columna "Resultado" (se muestra tal cual está en validation.json).
RESULT_LEGEND = {
    "pass": "el mejor lugar del análogo supera el percentil de corte",
    "fail": "el mejor lugar del análogo no lo supera",
    "info": "el análogo no está cubierto: se muestra pero no cuenta para el resultado del objetivo",
    "no_data": "no hay celdas con dato dentro del radio del análogo",
}

VARIABLE_COLUMNS = ("Variable", "Unidad", "Valor (media ± desvío)", "Regla", "Rango en la Tierra", "Fuentes", "Tipo de fuente")
SOURCE_COLUMNS = ("Dato", "Producto", "Portal", "Licencia", "Tamaño (MB)", "Enlace")
VALIDATION_COLUMNS = ("Análogo", "Cubierto", "Celdas", "Mejor puntaje", "Puesto", "Percentil", "Resultado")


# --- Textos de content/method.md -------------------------------------------------------------------------

_HEADING = re.compile(r"^##[ \t]+(.+?)[ \t]*$", re.MULTILINE)


def parse_method(text: str) -> dict[str, str]:
    """Partí method.md por los encabezados `## Título`: {título: texto}. Lo que va antes del primero se ignora."""
    text = text.lstrip("﻿").replace("\r\n", "\n")
    found = list(_HEADING.finditer(text))
    sections = {}
    for i, m in enumerate(found):
        end = found[i + 1].start() if i + 1 < len(found) else len(text)
        sections[m.group(1)] = text[m.end() : end].strip()
    return sections


def read_method(path: Path | None = None) -> dict[str, str]:
    """Las secciones de method.md. Sin archivo: {} (la pestaña dice qué falta en vez de romperse)."""
    path = Path(path) if path is not None else METHOD_PATH
    if not path.is_file():
        return {}
    return parse_method(path.read_text(encoding="utf-8"))


def pending_sections(sections: dict[str, str]) -> list[str]:
    """Encabezados de SECTIONS que faltan en el archivo o no tienen texto todavía."""
    return [s for s in SECTIONS if not sections.get(s, "").strip()]


# --- Tabla de variables (design 10.7, punto 2) ---------------------------------------------------------


def _decimals(unit: str) -> int:
    # Las mismas cifras que las frases de la ficha: fracciones y precipitación con menos decimales.
    return {"mm/año": 0, "fracción": 2}.get(unit, 1)


def variables_table(target: Target, earth_sources: dict[str, str] | None = None) -> pd.DataFrame:
    """Una fila por variable física del objetivo: valor, regla, rango en la Tierra y fuentes.

    `earth_sources` (variable -> nombre de la fuente terrestre) va en el pie de la fila de la fuente; sale del manifiesto.
    """
    earth_sources = earth_sources or {}
    rows = []
    for var in PHYSICAL_VARS:
        spec = target.vars[var]
        d = _decimals(spec.unit)
        source = spec.source
        if earth_sources.get(var):
            source = f"{source}. Tierra: {earth_sources[var]}"
        rows.append(
            {
                "Variable": VAR_LABELS[var],
                "Unidad": spec.unit,
                "Valor (media ± desvío)": f"{fmt_num(spec.mean, d)} ± {fmt_num(spec.std, d)}",
                "Regla": RULE_LABELS[spec.rule],
                "Rango en la Tierra": f"{fmt_num(spec.earth_p01, d)} a {fmt_num(spec.earth_p99, d)}",
                "Fuentes": source,
                "Tipo de fuente": SOURCE_TYPE_LABELS[spec.source_type],
            }
        )
    return pd.DataFrame(rows, columns=list(VARIABLE_COLUMNS))


# --- Fuentes del manifiesto -------------------------------------------------------------------------------


def sources_table(manifest: Manifest) -> pd.DataFrame:
    """Los datos de entrada de todos los pasos, sin repetir (un producto aparece una vez), en orden de paso."""
    rows, seen = [], set()
    for step in manifest.steps:
        for item in step.inputs:
            if item.product in seen:
                continue
            seen.add(item.product)
            rows.append(
                {
                    "Dato": item.name,
                    "Producto": item.product,
                    "Portal": item.portal,
                    "Licencia": item.license_note,
                    "Tamaño (MB)": item.size_mb,
                    "Enlace": item.url,
                }
            )
    return pd.DataFrame(rows, columns=list(SOURCE_COLUMNS))


def _cell(x) -> str:
    return str(x).replace("|", "\\|").replace("\n", " ").strip()


def sources_markdown(manifest: Manifest) -> str:
    """La tabla de fuentes como Markdown: las celdas se parten en vez de cortarse y el enlace se puede abrir."""
    cols = ["Dato", "Producto", "Portal", "Licencia", "Enlace"]
    lines = ["| " + " | ".join(cols) + " |", "|" + " --- |" * len(cols)]
    for r in sources_table(manifest).itertuples(index=False):
        url = str(r.Enlace).strip().replace(" ", "%20").replace(")", "%29")
        link = f"[Abrir]({url})" if url else ""
        lines.append("| " + " | ".join([_cell(r.Dato), _cell(r.Producto), _cell(r.Portal), _cell(r.Licencia), link]) + " |")
    return "\n".join(lines)


def grid_summary(manifest: Manifest) -> str:
    """"Grilla de 1° con 21.357 celdas de tierra. Año de los datos: 2024." Sin grilla (paso 01 sin correr): solo el año."""
    year = f"Año de los datos: {manifest.data_year}."
    if manifest.grid is None:
        return year
    g = manifest.grid
    cells = f"{g.n_cells:,}".replace(",", ".")
    return f"Grilla de {fmt_num(g.res_deg, 0 if float(g.res_deg).is_integer() else 2)}° con {cells} celdas de tierra. {year}"


# --- Validación (design 10.7, punto 4) --------------------------------------------------------------------


def validation_table(target: TargetValidation) -> pd.DataFrame:
    """Una fila por análogo conocido con su percentil y su resultado, tal cual están en validation.json."""
    rows = [
        {
            "Análogo": a.name,
            "Cubierto": COVERED_LABELS[a.covered],
            "Celdas": a.n_cells,
            "Mejor puntaje": a.best_total,
            "Puesto": a.best_rank,
            "Percentil": a.percentile,
            "Resultado": a.result,
        }
        for a in target.analogs
    ]
    return pd.DataFrame(rows, columns=list(VALIDATION_COLUMNS))


def validation_summary(target: TargetValidation, report: ValidationReport) -> str:
    """"Pasa: 2 de 3 análogos cubiertos superan el percentil 90". Los números salen del informe."""
    threshold = f"{report.percentile_threshold:g}".replace(".", ",")
    return (
        f"{TARGET_RESULT_LABELS[target.result]}: {target.covered_passed} de {target.covered_total} análogos "
        f"cubiertos superan el percentil {threshold}"
    )


def weights_summary(report: ValidationReport, labels: dict[str, str]) -> str:
    """"Pesos de la validación: Terreno 1, Temperatura 1, Agua y hielo 1, Interés astrobiológico 0,5"."""
    parts = [f"{labels[d]} {fmt_num(w, 0 if float(w).is_integer() else 1)}" for d, w in report.weights.as_dict().items()]
    return "Pesos de la validación: " + ", ".join(parts)


def result_legend(report: ValidationReport) -> str:
    threshold = f"{report.percentile_threshold:g}".replace(".", ",")
    parts = [f"{k}: {v}" for k, v in RESULT_LEGEND.items()]
    return f"Percentil de corte: {threshold}. " + "; ".join(parts) + "."


__all__ = [
    "METHOD_PATH",
    "SECTIONS",
    "earth_source_names",
    "grid_summary",
    "parse_method",
    "pending_sections",
    "read_method",
    "result_legend",
    "sources_markdown",
    "sources_table",
    "validation_summary",
    "validation_table",
    "variables_table",
    "weights_summary",
]
