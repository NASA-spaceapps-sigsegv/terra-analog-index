"""Ficha de sitio (design 11, contrato SiteCard, TAI-32).

`build_card` arma la ficha completa de una celda frente a un objetivo a partir de las tablas ya
cargadas: puntajes, frases de la plantilla (11.2), límites, fuentes y el texto manual (11.3), si
existe. Es puro salvo por leer content/cards/<cell_id>__<target_id>.md. La vista (ui/card_view.py)
solo dibuja lo que trae el modelo.

Las frases viven acá como constantes. Las pruebas están en tests/test_cards.py.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from pathlib import Path

import pandas as pd

from tai import scoring
from tai.constants import (
    DIFFERENT_MAX,
    DIMENSION_VARS,
    PHYSICAL_DIMENSIONS,
    PHYSICAL_VARS,
    SCORE_DECIMALS_FILE,
    SIMILAR_MIN,
)
from tai.errors import ZeroWeightsError
from tai.models import (
    BioTypeRef,
    CardAnalog,
    CardBiology,
    CardDimension,
    CardHeader,
    CardScores,
    CardSource,
    CardVariable,
    KnownAnalog,
    Manifest,
    ManualText,
    SiteCard,
    Target,
    Weights,
)

# --- Textos fijos (11.2) ---------------------------------------------------------

PHRASE_OVERLAP = "{value} {unit} frente a {mean} ± {std} del objetivo"
PHRASE_DIRECTIONAL_LOW = (
    "Más {adjective} que el {pct}% de la tierra firme; el objetivo ({mean} {unit}) queda fuera del rango terrestre"
)
PHRASE_DIRECTIONAL_HIGH = (
    "Mayor que el {pct}% de la tierra firme; el objetivo ({mean} {unit}) queda fuera del rango terrestre"
)
PHRASE_PRESENCE = "Nieve o hielo el {pct}% del año; el objetivo tiene hielo"
PHRASE_ABSENCE = "Sin nieve ni hielo el {pct}% del año; el objetivo no tiene hielo en superficie"
PHRASE_NO_DATA = "Sin dato para esta celda"
PHRASE_BIO_RECORDS = "{n} registros de ambientes extremos en NCBI BioSample: {types}"
PHRASE_BIO_ONE_RECORD = "1 registro de ambientes extremos en NCBI BioSample: {types}"
PHRASE_BIO_NONE = "Sin registros en NCBI BioSample"
SAMPLING_NOTE = "La falta de registros puede deberse a que nadie tomó muestras acá, no a que no haya vida"
NONE_SIMILAR = "Ninguna dimensión física alcanza un parecido alto"
NONE_DIFFERENT = "Ninguna dimensión física se aleja de forma marcada"
NOT_ELIGIBLE_NOTE = "Datos insuficientes: la celda tiene dato en menos de 2 de las 3 dimensiones físicas y no entra en el ranking"

DIRECTIONAL_ADJECTIVE = {"tmin_c": "fría", "precip_mm": "seca"}

VAR_LABELS = {
    "slope_deg": "Pendiente media",
    "roughness_m": "Rugosidad local",
    "tmin_c": "Temperatura mínima",
    "trange_c": "Rango térmico diario",
    "precip_mm": "Precipitación anual",
    "ice_frac": "Nieve o hielo",
}
DIMENSION_LABELS = {
    "terrain": "Terreno",
    "temperature": "Temperatura",
    "water_ice": "Agua y hielo",
    "biology": "Interés astrobiológico",
}
# Copia de las etiquetas de config/bio_terms.json (la app no lee config/); una prueba las mantiene iguales.
BIO_TYPE_LABELS = {
    "halophile": "Halófilos (sal)",
    "psychrophile": "Psicrófilos (frío)",
    "xerophile": "Xerófilos (aridez)",
    "acidophile": "Acidófilos (ácido)",
    "thermophile": "Termófilos (calor)",
    "radioresistant": "Radiorresistentes",
}

# Decimales con que se escribe cada unidad en las frases.
UNIT_DECIMALS = {"mm/año": 0, "fracción": 2}
DEFAULT_DECIMALS = 1

# De qué entrada del manifiesto sale cada variable terrestre: (paso, prefijo del producto).
EARTH_SOURCE = {
    "slope_deg": ("02_terrain", ""),
    "roughness_m": ("02_terrain", ""),
    "tmin_c": ("03_temperature", ""),
    "trange_c": ("03_temperature", ""),
    "precip_mm": ("04_water_ice", "GPM"),
    "ice_frac": ("04_water_ice", "MOD10"),
}
BIO_STEP = "05_biology_ncbi"
BIO_SOURCE = "NCBI BioSample"
HAS_ICE_DERIVED = "Derivado de has_ice"

MONTHS = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)

CARDS_DIR = Path("content") / "cards"


# --- Formato -------------------------------------------------------------------------


def _missing(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x)) or pd.isna(x)


def fmt_num(x: float, decimals: int = DEFAULT_DECIMALS) -> str:
    """Número con coma decimal: 3.5 -> "3,5". Nunca "-0"."""
    s = f"{x:.{decimals}f}"
    if float(s) == 0:
        s = s.lstrip("-")
    return s.replace(".", ",")


def unit_value(x: float, unit: str) -> str:
    """El número con los decimales de su unidad: unit_value(3.0, "mm/año") -> "3"."""
    return fmt_num(x, UNIT_DECIMALS.get(unit, DEFAULT_DECIMALS))


def coord_label(lat: float, lon: float) -> str:
    """"24,5°S 69,5°O"."""
    ns = "S" if lat < 0 else "N"
    eo = "O" if lon < 0 else "E"
    return f"{fmt_num(abs(lat))}°{ns} {fmt_num(abs(lon))}°{eo}"


def _round(x) -> float | None:
    return None if _missing(x) else round(float(x), SCORE_DECIMALS_FILE)


def _pct(x: float) -> int:
    return int(round(100 * x))


# --- Frases ----------------------------------------------------------------------------


def variable_phrase(variable: str, rule: str, earth_value, score, mean: float, std: float, unit: str) -> str:
    """La frase de 11.2 que corresponde a la regla. Sin dato: PHRASE_NO_DATA."""
    if _missing(earth_value) or _missing(score):
        return PHRASE_NO_DATA
    if rule == "overlap":
        return PHRASE_OVERLAP.format(
            value=unit_value(earth_value, unit), unit=unit, mean=unit_value(mean, unit), std=unit_value(std, unit)
        )
    if rule == "directional_low":
        adjective = DIRECTIONAL_ADJECTIVE.get(variable, "baja")
        return PHRASE_DIRECTIONAL_LOW.format(adjective=adjective, pct=_pct(score), mean=unit_value(mean, unit), unit=unit)
    if rule == "directional_high":
        return PHRASE_DIRECTIONAL_HIGH.format(pct=_pct(score), mean=unit_value(mean, unit), unit=unit)
    if rule == "presence":
        return PHRASE_PRESENCE.format(pct=_pct(earth_value))
    if rule == "absence":
        return PHRASE_ABSENCE.format(pct=_pct(1 - earth_value))
    raise ValueError(f"regla desconocida: {rule!r}")


def _type_short(label: str) -> str:
    """"Halófilos (sal)" -> "halófilos"."""
    return label.split(" (")[0].lower()


def biology_phrase(records: int, types: list[BioTypeRef]) -> str:
    if records == 0:
        return PHRASE_BIO_NONE
    names = ", ".join(_type_short(t.label) for t in types)
    if records == 1:
        return PHRASE_BIO_ONE_RECORD.format(types=names)
    return PHRASE_BIO_RECORDS.format(n=records, types=names)


# --- Texto manual (11.3) -----------------------------------------------------------------


def manual_filename(cell_id: int, target_id: str) -> str:
    return f"{cell_id}__{target_id}.md"


_SOURCES_HEADING = re.compile(r"^##\s+Fuentes\s*$", re.MULTILINE)
_LIST_ITEM = re.compile(r"^\s*(?:\d+[.)]|[-*])\s+\S", re.MULTILINE)
MANUAL_WORDS = (150, 250)


def parse_manual(text: str) -> tuple[str | None, str]:
    """(título, cuerpo). El título es la primera línea si empieza con "# "; si no, None."""
    lines = text.strip().splitlines()
    if lines and lines[0].startswith("# "):
        return lines[0][2:].strip() or None, "\n".join(lines[1:]).strip()
    return None, text.strip()


def manual_problems(text: str) -> list[str]:
    """Lo que le falta a un texto manual para cumplir el formato de contracts 7.4. Vacía si está bien."""
    problems = []
    title, body = parse_manual(text)
    if title is None:
        problems.append('la primera línea debe ser el título: "# Nombre del lugar"')
    found = list(_SOURCES_HEADING.finditer(body))
    if not found:
        problems.append('falta la sección final "## Fuentes"')
        return problems
    sources = body[found[-1].end():]
    if re.search(r"^#{1,6}\s", sources, re.MULTILINE):
        problems.append('"## Fuentes" debe ser la última sección')
    if not _LIST_ITEM.search(sources):
        problems.append('"## Fuentes" debe tener al menos un ítem de lista')
    words = len(re.findall(r"\w+", body[: found[-1].start()]))
    lo, hi = MANUAL_WORDS
    if not lo <= words <= hi:
        problems.append(f"el texto tiene {words} palabras sin contar las fuentes; deben ser entre {lo} y {hi}")
    return problems


def read_manual(cards_dir: Path, cell_id: int, target_id: str, root: Path | None = None) -> ManualText | None:
    """El texto manual de la celda y el objetivo, o None si no hay archivo.

    Un archivo sin título se muestra igual (el título pasa a ser el nombre del archivo): mejor ver
    el texto que ocultarlo por un error de formato, que de todos modos hace fallar test_cards.py."""
    path = Path(cards_dir) / manual_filename(cell_id, target_id)
    if not path.is_file():
        return None
    title, body = parse_manual(path.read_text(encoding="utf-8"))
    shown = path.relative_to(root).as_posix() if root and path.is_relative_to(root) else path.as_posix()
    return ManualText(title=title or path.stem, body_md=body, path=shown)


# --- Fuentes -------------------------------------------------------------------------------


def earth_source_names(manifest: Manifest) -> dict[str, str]:
    """Variable física -> nombre de su fuente terrestre en el manifiesto ("" si el paso no está)."""
    steps = {s.step: s for s in manifest.steps}
    out = {}
    for var, (step, prefix) in EARTH_SOURCE.items():
        inputs = steps[step].inputs if step in steps else []
        match = [i.name for i in inputs if i.product.startswith(prefix)]
        out[var] = match[0] if match else ""
    return out


def biology_source(manifest: Manifest) -> str:
    step = next((s for s in manifest.steps if s.step == BIO_STEP), None)
    if step is None:
        return BIO_SOURCE
    d = step.ran_at
    return f"{BIO_SOURCE}, consulta del {d.day} de {MONTHS[d.month - 1]} de {d.year}"


def _sources(variables: list[CardVariable], target: Target) -> list[CardSource]:
    """Una entrada por nombre, en orden de aparición: Tierra, NCBI y después el objetivo."""
    used: dict[str, list[str]] = {}
    for v in variables:
        if v.source_earth:
            used.setdefault(v.source_earth, []).append(v.variable)
    used.setdefault(BIO_SOURCE, []).extend(["bio_records", "bio_types"])
    for v in variables:
        used.setdefault(v.source_target, []).append(v.variable)
        if v.source_target == HAS_ICE_DERIVED:
            used.setdefault(target.has_ice_source, []).append(v.variable)
    return [CardSource(name=name, used_for=list(dict.fromkeys(vs))) for name, vs in used.items()]


# --- Ficha ------------------------------------------------------------------------------------


def _total(sim_row: pd.DataFrame, weights: Weights, eligible: bool) -> float | None:
    if not eligible:
        return None
    try:
        total = scoring.combine(sim_row, weights).iloc[0]
    except ZeroWeightsError:  # contrato: con todos los pesos en 0 la ficha no falla, el total es nulo
        return None
    return _round(total)


def build_card(
    *,
    cell_id: int,
    target: Target,
    grid_row: pd.Series,
    features_row: pd.Series,
    sim_row: pd.Series,
    weights: Weights,
    analogs: Mapping[str, KnownAnalog],
    manifest: Manifest,
    cards_dir: Path | None = None,
    root: Path | None = None,
) -> SiteCard:
    """La ficha de una celda. `sim_row` es la fila de similarity.parquet de ese objetivo."""
    earth_sources = earth_source_names(manifest)

    variables = []
    for dim in PHYSICAL_DIMENSIONS:
        for var in DIMENSION_VARS[dim]:
            t = target.vars[var]
            earth = None if _missing(features_row.get(var)) else float(features_row[var])
            score = _round(sim_row.get(f"sv_{var}"))
            variables.append(
                CardVariable(
                    variable=var,
                    label=VAR_LABELS[var],
                    dimension=dim,
                    unit=t.unit,
                    earth_value=None if earth is None else round(earth, SCORE_DECIMALS_FILE),
                    target_mean=t.mean,
                    target_std=t.std,
                    score=score,
                    rule=t.rule,
                    phrase=variable_phrase(var, t.rule, earth, score, t.mean, t.std, t.unit),
                    source_earth=earth_sources[var],
                    source_target=t.source,
                    source_type=t.source_type,
                )
            )

    dims = {d: _round(sim_row.get(scoring.SCORE_COLUMNS[d])) for d in PHYSICAL_DIMENSIONS}
    eligible = bool(sim_row.get("eligible", False))
    scores = CardScores(
        total=_total(sim_row.to_frame().T, weights, eligible),
        biology=_round(sim_row.get("bio_score")) or 0.0,
        **dims,
    )

    similar = [CardDimension(dimension=d, label=DIMENSION_LABELS[d], score=s) for d, s in dims.items()
               if s is not None and s >= SIMILAR_MIN]
    different = [CardDimension(dimension=d, label=DIMENSION_LABELS[d], score=s) for d, s in dims.items()
                 if s is not None and s < DIFFERENT_MAX]

    types_raw = features_row.get("bio_type_list")
    type_ids = [] if _missing(types_raw) or not types_raw else sorted(str(types_raw).split(","))
    types = [BioTypeRef(extremophile_type=t, label=BIO_TYPE_LABELS[t]) for t in type_ids]
    records = 0 if _missing(features_row.get("bio_records")) else int(features_row["bio_records"])
    biology = CardBiology(
        records=records,
        types=types,
        phrase=biology_phrase(records, types),
        sampling_note=SAMPLING_NOTE,
        source=biology_source(manifest),
    )

    analog_id = sim_row.get("known_analog")
    known = None
    if not _missing(analog_id):
        a = analogs.get(analog_id)
        km = sim_row.get("known_analog_km")
        known = CardAnalog(
            analog_id=analog_id,
            name=a.name if a else analog_id,
            distance_km=None if _missing(km) else round(float(km), 1),
            basis=a.basis if a else "",
        )
    lat, lon = float(grid_row["lat"]), float(grid_row["lon"])
    country = grid_row.get("country")
    header = CardHeader(
        lat=lat,
        lon=lon,
        label=coord_label(lat, lon),
        country=None if _missing(country) else str(country),
        area_km2=round(float(grid_row["area_km2"]), 1),
        known_analog=known,
    )

    notes = list(target.notes)
    if not eligible:
        notes.insert(0, NOT_ELIGIBLE_NOTE)

    return SiteCard(
        cell_id=int(cell_id),
        target_id=target.target_id,
        target_label=target.label,
        header=header,
        weights=weights,
        eligible=eligible,
        scores=scores,
        variables=variables,
        similar_in=similar,
        different_in=different,
        similar_empty_phrase=None if similar else NONE_SIMILAR,
        different_empty_phrase=None if different else NONE_DIFFERENT,
        biology=biology,
        unreplicable=list(target.unreplicable),
        notes=notes,
        manual=read_manual(cards_dir, cell_id, target.target_id, root) if cards_dir is not None else None,
        sources=_sources(variables, target),
    )


assert tuple(VAR_LABELS) == PHYSICAL_VARS
