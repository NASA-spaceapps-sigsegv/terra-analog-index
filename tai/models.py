"""Pydantic models for the JSON contracts ("Contratos JSON e interfaces").

Every model rejects unknown keys (extra="forbid") so a typo in a file fails
at load time, not during the demo. Missing values are null, never NaN.
"""

import math
import re
from datetime import datetime
from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from tai.constants import (
    BIO_TYPES,
    CORE_VARS,
    DIMENSIONS,
    PHYSICAL_VARS,
    SCHEMA_VERSION,
)

Body = Literal["moon", "mars"]
Rule = Literal["overlap", "directional_low", "directional_high", "presence", "absence"]
SourceType = Literal["measured", "literature", "definition"]
Covered = Literal["yes", "partial", "no"]
ExtremophileType = Literal[BIO_TYPES]  # type: ignore[valid-type]

_SNAKE_ID = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _check_snake_id(v: str) -> str:
    if not _SNAKE_ID.match(v):
        raise ValueError(f"must be lowercase snake_case, got {v!r}")
    return v


def _check_six_vars(v: dict) -> dict:
    """The six core variables are required; the optional ones (dust and wind, TAI-52) only where they apply."""
    missing = [x for x in CORE_VARS if x not in v]
    unknown = sorted(set(v) - set(PHYSICAL_VARS))
    if missing or unknown:
        raise ValueError(f"vars must have {list(CORE_VARS)} and may add {[x for x in PHYSICAL_VARS if x not in CORE_VARS]}; "
                         f"missing {missing}, unknown {unknown}")
    return v


# --- Weights -----------------------------------------------------------------


class Weights(_Model):
    """One weight per dimension; each finite and within 0..1."""

    terrain: float = Field(ge=0.0, le=1.0)
    temperature: float = Field(ge=0.0, le=1.0)
    water_ice: float = Field(ge=0.0, le=1.0)
    # TAI-52. Optional so weights written before it (validation.json of an older run) still load: missing = 0.
    dust_wind: float = Field(default=0.0, ge=0.0, le=1.0)
    biology: float = Field(ge=0.0, le=1.0)

    @field_validator("*")
    @classmethod
    def _finite(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("weight must be finite")
        return v

    def as_dict(self) -> dict[str, float]:
        return {d: getattr(self, d) for d in DIMENSIONS}


# --- targets.json (contracts 3.6) --------------------------------------------


class Bounds(_Model):
    lat_min: float = Field(ge=-90, le=90)
    lat_max: float = Field(ge=-90, le=90)
    lon_min: float = Field(ge=-180, le=180)
    lon_max: float = Field(ge=-180, le=180)

    @model_validator(mode="after")
    def _ordered(self):
        if self.lat_min >= self.lat_max or self.lon_min >= self.lon_max:
            raise ValueError("bounds must satisfy min < max")
        return self


class TargetVar(_Model):
    mean: float
    std: float = Field(ge=0)
    unit: str
    rule: Rule
    source: str = Field(min_length=1)
    source_type: SourceType
    earth_p01: float
    earth_p99: float
    earth_std: float = Field(ge=0)


class _TargetCommon(_Model):
    target_id: str
    label: str = Field(min_length=1)
    body: Body
    bounds: Bounds
    has_ice: bool
    has_ice_source: str = Field(min_length=1)
    summary: str
    unreplicable: list[str]
    notes: list[str] = []

    @field_validator("target_id")
    @classmethod
    def _snake_id(cls, v: str) -> str:
        return _check_snake_id(v)


class Target(_TargetCommon):
    vars: dict[str, TargetVar]

    @field_validator("vars")
    @classmethod
    def _six_vars(cls, v: dict) -> dict:
        return _check_six_vars(v)


class TargetsFile(_Model):
    schema_version: Literal[SCHEMA_VERSION]  # type: ignore[valid-type]
    targets: list[Target] = Field(min_length=1)

    @field_validator("targets")
    @classmethod
    def _unique_ids(cls, v: list[Target]) -> list[Target]:
        ids = [t.target_id for t in v]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate target_id")
        return v


class TargetSummary(_Model):
    """Response of list_targets (contracts 4.1)."""

    target_id: str
    label: str
    body: Body
    summary: str


# --- config/targets_base.json (hand-edited input of step 07) -----------------


class TargetBaseVar(_Model):
    """Same as TargetVar without rule/earth_*; mean/std only for literature values."""

    mean: float | None = None
    std: float | None = Field(default=None, ge=0)
    unit: str
    source: str = Field(min_length=1)
    source_type: SourceType

    @model_validator(mode="after")
    def _literature_has_values(self):
        if self.source_type != "measured" and (self.mean is None or self.std is None):
            raise ValueError(f"{self.source_type} variables need mean and std")
        return self


class TargetBase(_TargetCommon):
    vars: dict[str, TargetBaseVar]

    @field_validator("vars")
    @classmethod
    def _six_vars(cls, v: dict) -> dict:
        return _check_six_vars(v)


class TargetsBaseFile(_Model):
    schema_version: Literal[SCHEMA_VERSION]  # type: ignore[valid-type]
    targets: list[TargetBase] = Field(min_length=1)


# --- known_analogs.csv row (contracts 3.5 / 4.3) -----------------------------


class KnownAnalog(_Model):
    analog_id: str
    name: str = Field(min_length=1)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    radius_km: float = Field(gt=0)
    target_id: str
    basis: str = Field(min_length=1)
    covered: Covered
    source: str = Field(min_length=1)

    @field_validator("analog_id", "target_id")
    @classmethod
    def _snake_id(cls, v: str) -> str:
        return _check_snake_id(v)


# --- caves.csv row (TAI-53) --------------------------------------------------

CaveKind = Literal["lava_tube", "ice_cave"]


class Cave(_Model):
    """Una cueva o tubo de lava estudiado como análogo. Capa informativa del mapa: no entra en ningún puntaje."""

    cave_id: str
    name: str = Field(min_length=1)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    kind: CaveKind
    relevance: str = Field(min_length=1)
    source: str = Field(min_length=1)

    @field_validator("cave_id")
    @classmethod
    def _snake_id(cls, v: str) -> str:
        return _check_snake_id(v)


# --- validation.json (contracts 6.1) -----------------------------------------


class AnalogValidation(_Model):
    analog_id: str
    name: str
    covered: Covered
    n_cells: int = Field(ge=0)
    best_cell_id: int | None
    best_total: float | None = Field(ge=0, le=1)
    best_rank: int | None = Field(ge=1)
    percentile: float | None = Field(ge=0, le=100)
    result: Literal["pass", "fail", "info", "no_data"]


class TargetValidation(_Model):
    target_id: str
    result: Literal["pass", "fail", "insufficient"]
    covered_total: int = Field(ge=0)
    covered_passed: int = Field(ge=0)
    n_eligible: int = Field(ge=0)
    note: str = ""
    analogs: list[AnalogValidation]

    @model_validator(mode="after")
    def _fail_needs_note(self):
        if self.result == "fail" and not self.note.strip():
            raise ValueError("note is required when result is 'fail'")
        if self.covered_passed > self.covered_total:
            raise ValueError("covered_passed cannot exceed covered_total")
        return self


class ValidationReport(_Model):
    schema_version: Literal[SCHEMA_VERSION]  # type: ignore[valid-type]
    generated_at: datetime
    weights: Weights
    percentile_threshold: float = Field(ge=0, le=100)
    targets: list[TargetValidation]


# --- manifest.json (contracts 6.2) -------------------------------------------


class ManifestGrid(_Model):
    res_deg: float = Field(gt=0)
    n_cells: int = Field(ge=0)
    land_frac_min: float = Field(ge=0, le=1)


class ManifestInput(_Model):
    name: str
    product: str
    portal: str
    url: str
    files: int = Field(ge=0)
    size_mb: float = Field(ge=0)
    license_note: str


class ManifestOutput(_Model):
    path: str
    rows: int = Field(ge=0)
    size_mb: float = Field(ge=0)


class ColumnStats(_Model):
    non_null: int = Field(ge=0)
    null: int = Field(ge=0)
    min: float | None
    max: float | None


class EarthStats(_Model):
    p01: float
    p99: float
    std: float = Field(ge=0)


class ManifestStep(_Model):
    step: str = Field(pattern=r"^\d{2}_[a-z0-9_]+$")
    ran_at: datetime
    duration_s: float = Field(ge=0)
    git_commit: str | None
    inputs: list[ManifestInput]
    outputs: list[ManifestOutput]
    columns: dict[str, ColumnStats]
    earth_stats: dict[str, EarthStats] | None = None
    notes: list[str] = []


class Manifest(_Model):
    schema_version: Literal[SCHEMA_VERSION]  # type: ignore[valid-type]
    project: Literal["terra-analog-index"]
    data_year: int
    grid: ManifestGrid | None = None  # null until step 01 has run
    steps: list[ManifestStep]

    @field_validator("steps")
    @classmethod
    def _one_entry_per_step(cls, v: list[ManifestStep]) -> list[ManifestStep]:
        names = [s.step for s in v]
        if len(names) != len(set(names)):
            raise ValueError("at most one entry per step")
        return v


# --- config/bio_terms.json (contracts 7.2) -----------------------------------


class BioTermType(_Model):
    extremophile_type: ExtremophileType
    label: str
    search_by: Literal["environment", "organism"]
    terms: list[str] = Field(min_length=1)


class BioTermsFile(_Model):
    # Versión 2 (TAI-06) agrega `shared`: filtro de BioSample común a todos los tipos
    # (bacterias, sin metagenomas, con lat_lon y los atributos de ambiente). Versión 1 no lo trae.
    schema_version: Literal[1, 2]
    shared: str = ""
    types: list[BioTermType] = Field(min_length=1)


# --- Respuesta de get_ranking (contracts 4.5) --------------------------------


class AnalogRef(_Model):
    """Análogo conocido que cubre una celda: id y nombre para mostrar."""

    analog_id: str
    name: str = Field(min_length=1)


class RankingItem(_Model):
    """Una fila del ranking. Un puntaje nulo es "sin dato", nunca 0."""

    rank: int = Field(ge=1)
    cell_id: int = Field(ge=0)
    lat: float
    lon: float
    country: str | None
    total: float = Field(ge=0, le=1)
    s_terrain: float | None = Field(ge=0, le=1)
    s_temperature: float | None = Field(ge=0, le=1)
    s_water_ice: float | None = Field(ge=0, le=1)
    s_dust_wind: float | None = Field(default=None, ge=0, le=1)  # nulo si el objetivo no tiene la dimensión
    bio_score: float = Field(ge=0, le=1)
    known_analog: AnalogRef | None


class Ranking(_Model):
    target_id: str
    weights: Weights
    hide_known: bool
    limit: int = Field(ge=1)
    total_eligible: int = Field(ge=0)  # elegibles antes de aplicar limit (y después de hide_known)
    items: list[RankingItem]


# --- Respuesta de get_map_layer (contracts 4.4) ------------------------------

MAP_CELL_COLUMNS = (
    "cell_id", "lat", "lon", "country", "total", "s_terrain", "s_temperature",
    "s_water_ice", "s_dust_wind", "bio_score", "eligible", "known_analog",
)


class MapLayer(BaseModel):
    """Todas las celdas de la grilla para un objetivo y unos pesos, sin ordenar.

    `cells` es una tabla (una fila por celda, columnas de MAP_CELL_COLUMNS) para que el mapa
    se arme sin recorrer objetos; `to_dict` da la forma JSON del contrato, con null en vez
    de NaN. `total` es nulo si la celda no es elegible (o si todos los pesos valen 0).
    """

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    target_id: str
    weights: Weights
    n_cells: int = Field(ge=0)
    n_eligible: int = Field(ge=0)
    cells: pd.DataFrame

    @model_validator(mode="after")
    def _columns(self):
        if tuple(self.cells.columns) != MAP_CELL_COLUMNS:
            raise ValueError(f"cells must have exactly the columns {MAP_CELL_COLUMNS}")
        if len(self.cells) != self.n_cells:
            raise ValueError("n_cells must equal the number of rows of cells")
        return self

    def to_dict(self) -> dict:
        rows = self.cells.astype(object).where(self.cells.notna(), None).to_dict(orient="records")
        return {
            "target_id": self.target_id,
            "weights": self.weights.as_dict(),
            "n_cells": self.n_cells,
            "n_eligible": self.n_eligible,
            "cells": rows,
        }



# --- Respuesta de get_site_card (contracts 5) ----------------------------------

PhysicalDimension = Literal["terrain", "temperature", "water_ice", "dust_wind"]


class CardAnalog(_Model):
    analog_id: str
    name: str = Field(min_length=1)
    distance_km: float | None = Field(ge=0)
    basis: str


class CardHeader(_Model):
    lat: float
    lon: float
    label: str  # "24,5°S 69,5°O"
    country: str | None
    area_km2: float = Field(gt=0)
    known_analog: CardAnalog | None


class CardScores(_Model):
    total: float | None = Field(ge=0, le=1)  # nulo si la celda no es elegible o los pesos suman 0
    terrain: float | None = Field(ge=0, le=1)
    temperature: float | None = Field(ge=0, le=1)
    water_ice: float | None = Field(ge=0, le=1)
    dust_wind: float | None = Field(default=None, ge=0, le=1)  # nulo si el objetivo no tiene la dimensión
    biology: float = Field(ge=0, le=1)


class CardVariable(_Model):
    variable: str
    label: str
    dimension: PhysicalDimension
    unit: str
    earth_value: float | None
    target_mean: float
    target_std: float = Field(ge=0)
    score: float | None = Field(ge=0, le=1)
    rule: Rule
    phrase: str = Field(min_length=1)
    source_earth: str
    source_target: str
    source_type: SourceType


class CardDimension(_Model):
    dimension: PhysicalDimension
    label: str
    score: float = Field(ge=0, le=1)


class BioTypeRef(_Model):
    extremophile_type: ExtremophileType
    label: str


class CardBiology(_Model):
    records: int = Field(ge=0)
    types: list[BioTypeRef]
    phrase: str = Field(min_length=1)
    sampling_note: str = Field(min_length=1)
    source: str


class ManualText(_Model):
    title: str = Field(min_length=1)
    body_md: str
    path: str


class CardSource(_Model):
    name: str = Field(min_length=1)
    used_for: list[str] = Field(min_length=1)


class SiteCard(_Model):
    """Todo lo que muestra la ficha, ya redactado: la vista no arma frases ni decide umbrales."""

    cell_id: int = Field(ge=0)
    target_id: str
    target_label: str
    header: CardHeader
    weights: Weights
    eligible: bool
    scores: CardScores
    variables: list[CardVariable]
    similar_in: list[CardDimension]
    different_in: list[CardDimension]
    similar_empty_phrase: str | None
    different_empty_phrase: str | None
    biology: CardBiology
    unreplicable: list[str] = Field(min_length=1)
    notes: list[str]
    manual: ManualText | None
    sources: list[CardSource]

    @model_validator(mode="after")
    def _rules(self):
        names = [v.variable for v in self.variables]
        if names != [x for x in PHYSICAL_VARS if x in names] or not set(CORE_VARS) <= set(names):
            raise ValueError(f"variables must be the six core variables plus the optional ones, in the order {PHYSICAL_VARS}")
        both = {d.dimension for d in self.similar_in} & {d.dimension for d in self.different_in}
        if both:
            raise ValueError(f"a dimension cannot be both similar and different: {sorted(both)}")
        if (self.similar_empty_phrase is None) != bool(self.similar_in):
            raise ValueError("similar_empty_phrase is set exactly when similar_in is empty")
        if (self.different_empty_phrase is None) != bool(self.different_in):
            raise ValueError("different_empty_phrase is set exactly when different_in is empty")
        return self
