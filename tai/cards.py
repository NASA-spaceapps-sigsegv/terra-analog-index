"""Site card (design 11, SiteCard contract, TAI-32).

`build_card` assembles the full card for a cell against a target from the already loaded tables:
scores, template phrases (11.2), limits, sources and the manual text (11.3), if there is one. It is
pure except for reading content/cards/<cell_id>__<target_id>.md. The view (ui/card_view.py) only
draws what the model carries.

The phrases live here as constants. The tests are in tests/test_cards.py.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from pathlib import Path

import pandas as pd

from tai import scoring
from tai.caves import CAVE_KINDS
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
    CardCave,
    CardDimension,
    CardHeader,
    CardScores,
    CardSource,
    CardVariable,
    Cave,
    KnownAnalog,
    Manifest,
    ManualText,
    SiteCard,
    Target,
    Weights,
)

# --- Fixed texts (11.2) ---------------------------------------------------------

PHRASE_OVERLAP = "{value} {unit} vs. the target's {mean} ± {std}"
PHRASE_DIRECTIONAL_LOW = (
    "{adjective} than {pct}% of dry land; the target ({mean} {unit}) lies outside the Earth range"
)
PHRASE_DIRECTIONAL_HIGH = (
    "Higher than {pct}% of dry land; the target ({mean} {unit}) lies outside the Earth range"
)
PHRASE_PRESENCE = "Snow or ice {pct}% of the year; the target has ice"
PHRASE_ABSENCE = "No snow or ice {pct}% of the year; the target has no surface ice"
PHRASE_NO_DATA = "No data for this cell"
PHRASE_BIO_RECORDS = "{n} extreme-environment records in NCBI BioSample: {types}"
PHRASE_BIO_ONE_RECORD = "1 extreme-environment record in NCBI BioSample: {types}"
PHRASE_BIO_NONE = "No records in NCBI BioSample"
SAMPLING_NOTE = "A lack of records may mean nobody sampled here, not that there is no life"
NONE_SIMILAR = "No physical dimension reaches a high similarity"
NONE_DIFFERENT = "No physical dimension departs markedly"
NOT_ELIGIBLE_NOTE = "Insufficient data: the cell has data in fewer than 2 of the 3 physical dimensions and is not ranked"

DIRECTIONAL_ADJECTIVE = {"tmin_c": "Colder", "precip_mm": "Drier"}

VAR_LABELS = {
    "slope_deg": "Mean slope",
    "roughness_m": "Local roughness",
    "tmin_c": "Minimum temperature",
    "trange_c": "Daily temperature range",
    "precip_mm": "Annual precipitation",
    "ice_frac": "Snow or ice",
    "dust_aod": "Airborne dust",
    "wind_ms": "Surface wind",
}
DIMENSION_LABELS = {
    "terrain": "Terrain",
    "temperature": "Temperature",
    "water_ice": "Water and ice",
    "dust_wind": "Dust and wind",
    "biology": "Astrobiological interest",
}
# Copy of the labels in config/bio_terms.json (the app does not read config/); a test keeps them equal.
BIO_TYPE_LABELS = {
    "halophile": "Halophiles (salt)",
    "psychrophile": "Psychrophiles (cold)",
    "xerophile": "Xerophiles (dryness)",
    "acidophile": "Acidophiles (acid)",
    "thermophile": "Thermophiles (heat)",
    "radioresistant": "Radioresistant",
}

# Decimals each unit is written with in the phrases.
UNIT_DECIMALS = {"mm/yr": 0, "fraction": 2, "": 2}  # "": optical depth, unitless
DEFAULT_DECIMALS = 1

# Which manifest input each Earth variable comes from: (step, product prefix).
EARTH_SOURCE = {
    "slope_deg": ("02_terrain", ""),
    "roughness_m": ("02_terrain", ""),
    "tmin_c": ("03_temperature", ""),
    "trange_c": ("03_temperature", ""),
    "precip_mm": ("04_water_ice", "GPM"),
    "ice_frac": ("04_water_ice", "MOD10"),
    "dust_aod": ("04_dust_wind", "M2TMNXAER"),
    "wind_ms": ("04_dust_wind", "M2TMNXFLX"),
}
BIO_STEP = "05_biology_ncbi"
BIO_SOURCE = "NCBI BioSample"
HAS_ICE_DERIVED = "Derived from has_ice"

MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)

CARDS_DIR = Path("content") / "cards"


# --- Formatting -------------------------------------------------------------------------


def _missing(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x)) or pd.isna(x)


def fmt_num(x: float, decimals: int = DEFAULT_DECIMALS) -> str:
    """Number with a decimal point: 3.5 -> "3.5". Never "-0"."""
    s = f"{x:.{decimals}f}"
    if float(s) == 0:
        s = s.lstrip("-")
    return s


def unit_value(x: float, unit: str) -> str:
    """The number with its unit's decimals: unit_value(3.0, "mm/yr") -> "3"."""
    return fmt_num(x, UNIT_DECIMALS.get(unit, DEFAULT_DECIMALS))


def coord_label(lat: float, lon: float) -> str:
    """"24.5°S 69.5°W"."""
    ns = "S" if lat < 0 else "N"
    ew = "W" if lon < 0 else "E"
    return f"{fmt_num(abs(lat))}°{ns} {fmt_num(abs(lon))}°{ew}"


def _round(x) -> float | None:
    return None if _missing(x) else round(float(x), SCORE_DECIMALS_FILE)


def _pct(x: float) -> int:
    return int(round(100 * x))


# --- Phrases ----------------------------------------------------------------------------


def _no_double_space(text: str) -> str:
    """A unitless variable (optical depth) leaves "0.12  vs." or "(0.45 )"; clean it up."""
    return text.replace("  ", " ").replace(" )", ")")


def variable_phrase(variable: str, rule: str, earth_value, score, mean: float, std: float, unit: str) -> str:
    """The 11.2 phrase that matches the rule. No data: PHRASE_NO_DATA."""
    if _missing(earth_value) or _missing(score):
        return PHRASE_NO_DATA
    if rule == "overlap":
        return _no_double_space(PHRASE_OVERLAP.format(
            value=unit_value(earth_value, unit), unit=unit, mean=unit_value(mean, unit), std=unit_value(std, unit)
        ))
    if rule == "directional_low":
        adjective = DIRECTIONAL_ADJECTIVE.get(variable, "Lower")
        return _no_double_space(PHRASE_DIRECTIONAL_LOW.format(
            adjective=adjective, pct=_pct(score), mean=unit_value(mean, unit), unit=unit))
    if rule == "directional_high":
        return _no_double_space(PHRASE_DIRECTIONAL_HIGH.format(pct=_pct(score), mean=unit_value(mean, unit), unit=unit))
    if rule == "presence":
        return PHRASE_PRESENCE.format(pct=_pct(earth_value))
    if rule == "absence":
        return PHRASE_ABSENCE.format(pct=_pct(1 - earth_value))
    raise ValueError(f"unknown rule: {rule!r}")


def _type_short(label: str) -> str:
    """"Halophiles (salt)" -> "halophiles"."""
    return label.split(" (")[0].lower()


def biology_phrase(records: int, types: list[BioTypeRef]) -> str:
    if records == 0:
        return PHRASE_BIO_NONE
    names = ", ".join(_type_short(t.label) for t in types)
    if records == 1:
        return PHRASE_BIO_ONE_RECORD.format(types=names)
    return PHRASE_BIO_RECORDS.format(n=records, types=names)


# --- Manual text (11.3) -----------------------------------------------------------------


def manual_filename(cell_id: int, target_id: str) -> str:
    return f"{cell_id}__{target_id}.md"


_SOURCES_HEADING = re.compile(r"^##\s+Sources\s*$", re.MULTILINE)
_LIST_ITEM = re.compile(r"^\s*(?:\d+[.)]|[-*])\s+\S", re.MULTILINE)
MANUAL_WORDS = (150, 250)


def parse_manual(text: str) -> tuple[str | None, str]:
    """(title, body). The title is the first line if it starts with "# "; otherwise None."""
    lines = text.strip().splitlines()
    if lines and lines[0].startswith("# "):
        return lines[0][2:].strip() or None, "\n".join(lines[1:]).strip()
    return None, text.strip()


def manual_problems(text: str) -> list[str]:
    """What a manual text is missing to meet the contracts 7.4 format. Empty if it is fine."""
    problems = []
    title, body = parse_manual(text)
    if title is None:
        problems.append('the first line must be the title: "# Place name"')
    found = list(_SOURCES_HEADING.finditer(body))
    if not found:
        problems.append('the final "## Sources" section is missing')
        return problems
    sources = body[found[-1].end():]
    if re.search(r"^#{1,6}\s", sources, re.MULTILINE):
        problems.append('"## Sources" must be the last section')
    if not _LIST_ITEM.search(sources):
        problems.append('"## Sources" must have at least one list item')
    words = len(re.findall(r"\w+", body[: found[-1].start()]))
    lo, hi = MANUAL_WORDS
    if not lo <= words <= hi:
        problems.append(f"the text has {words} words not counting the sources; it must have between {lo} and {hi}")
    return problems


def read_manual(cards_dir: Path, cell_id: int, target_id: str, root: Path | None = None) -> ManualText | None:
    """The manual text for the cell and target, or None if there is no file.

    A file without a title is shown anyway (the title becomes the file name): better to see the
    text than to hide it over a format error, which makes test_cards.py fail anyway."""
    path = Path(cards_dir) / manual_filename(cell_id, target_id)
    if not path.is_file():
        return None
    title, body = parse_manual(path.read_text(encoding="utf-8"))
    shown = path.relative_to(root).as_posix() if root and path.is_relative_to(root) else path.as_posix()
    return ManualText(title=title or path.stem, body_md=body, path=shown)


# --- Sources -------------------------------------------------------------------------------


def earth_source_names(manifest: Manifest) -> dict[str, str]:
    """Physical variable -> name of its Earth source in the manifest ("" if the step is missing)."""
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
    return f"{BIO_SOURCE}, queried on {MONTHS[d.month - 1]} {d.day}, {d.year}"


def _sources(variables: list[CardVariable], target: Target) -> list[CardSource]:
    """One entry per name, in order of appearance: Earth, NCBI and then the target."""
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


# --- Card ------------------------------------------------------------------------------------


def _total(sim_row: pd.DataFrame, weights: Weights, eligible: bool) -> float | None:
    if not eligible:
        return None
    try:
        total = scoring.combine(sim_row, weights).iloc[0]
    except ZeroWeightsError:  # contract: with every weight at 0 the card does not fail, the total is null
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
    caves: Sequence[Cave] = (),
) -> SiteCard:
    """The card for a cell. `sim_row` is that target's row in similarity.parquet.

    `caves`: the caves and lava tubes that fall in the cell (TAI-53); they are shown, not scored."""
    earth_sources = earth_source_names(manifest)

    variables = []
    for dim in PHYSICAL_DIMENSIONS:
        for var in DIMENSION_VARS[dim]:
            t = target.vars.get(var)
            if t is None:  # optional variable the target does not have (dust and wind on the Moon)
                continue
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
        caves=[CardCave(name=c.name, kind_label=CAVE_KINDS[c.kind], relevance=c.relevance, source=c.source)
               for c in caves],
    )


assert tuple(VAR_LABELS) == PHYSICAL_VARS
