"""Pydantic models for the JSON contracts ("Contratos JSON e interfaces").

Every model rejects unknown keys (extra="forbid") so a typo in a file fails
at load time, not during the demo. Missing values are null, never NaN.
"""

import math
import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from tai.constants import (
    BIO_TYPES,
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
    if set(v) != set(PHYSICAL_VARS):
        raise ValueError(f"vars must have exactly {list(PHYSICAL_VARS)}, got {sorted(v)}")
    return v


# --- Weights -----------------------------------------------------------------


class Weights(_Model):
    """One weight per dimension; each finite and within 0..1."""

    terrain: float = Field(ge=0.0, le=1.0)
    temperature: float = Field(ge=0.0, le=1.0)
    water_ice: float = Field(ge=0.0, le=1.0)
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
    schema_version: Literal[SCHEMA_VERSION]  # type: ignore[valid-type]
    types: list[BioTermType] = Field(min_length=1)
