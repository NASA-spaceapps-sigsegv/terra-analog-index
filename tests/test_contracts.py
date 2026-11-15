"""Every fixture must satisfy its contract (design 12.1, TAI-10/TAI-19)."""

import copy
import json
from pathlib import Path

import pandas as pd
import pytest
from pydantic import ValidationError

from tai import models, schemas
from tai.constants import PHYSICAL_VARS, TARGET_IDS

FIX = Path(__file__).parent / "fixtures"


def _json(name: str) -> dict:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


# --- Parquet tables ----------------------------------------------------------


@pytest.mark.parametrize("name", list(schemas.BY_NAME))
def test_parquet_fixture_matches_schema(name):
    df = pd.read_parquet(FIX / f"{name}.parquet")
    assert schemas.check_schema(df, name) == []


def test_all_cells_exist_in_grid():
    grid_ids = set(pd.read_parquet(FIX / "grid.parquet")["cell_id"])
    for name in ("features", "bio_samples", "similarity"):
        ids = set(pd.read_parquet(FIX / f"{name}.parquet")["cell_id"])
        assert ids <= grid_ids, name


def test_similarity_one_row_per_cell_and_target():
    grid = pd.read_parquet(FIX / "grid.parquet")
    sim = pd.read_parquet(FIX / "similarity.parquet")
    assert len(sim) == len(grid) * len(TARGET_IDS)
    scores = sim[[c for c in sim.columns if c.startswith(("sv_", "s_"))] + ["bio_score"]]
    assert ((scores >= 0) & (scores <= 1) | scores.isna()).all().all()


def test_features_ranges():
    from tai.constants import VALID_RANGES

    df = pd.read_parquet(FIX / "features.parquet")
    for col in (*PHYSICAL_VARS, "bio_records", "bio_types"):
        lo, hi = VALID_RANGES[col]
        s = df[col].dropna()
        assert (s >= lo).all(), col
        if hi is not None:
            assert (s <= hi).all(), col


# --- JSON files --------------------------------------------------------------


@pytest.mark.parametrize(
    "fname,model",
    [
        ("targets.json", models.TargetsFile),
        ("targets_base.json", models.TargetsBaseFile),
        ("validation.json", models.ValidationReport),
        ("manifest.json", models.Manifest),
        ("bio_terms.json", models.BioTermsFile),
    ],
)
def test_json_fixture_validates(fname, model):
    model.model_validate(_json(fname))


def test_known_analogs_csv_validates():
    df = pd.read_csv(FIX / "known_analogs.csv")
    assert tuple(df.columns) == schemas.KNOWN_ANALOGS_COLUMNS
    for row in df.to_dict(orient="records"):
        models.KnownAnalog.model_validate(row)


def test_targets_fixture_has_both_targets():
    t = models.TargetsFile.model_validate(_json("targets.json"))
    assert tuple(x.target_id for x in t.targets) == TARGET_IDS


# --- Rejections --------------------------------------------------------------


def test_unknown_key_rejected():
    data = _json("targets.json")
    data["targets"][0]["colour"] = "red"
    with pytest.raises(ValidationError):
        models.TargetsFile.model_validate(data)


def test_missing_variable_rejected():
    data = _json("targets.json")
    del data["targets"][0]["vars"]["ice_frac"]
    with pytest.raises(ValidationError):
        models.TargetsFile.model_validate(data)


def test_failed_validation_requires_note():
    data = _json("validation.json")
    data["targets"][0]["result"] = "fail"
    data["targets"][0]["note"] = ""
    with pytest.raises(ValidationError):
        models.ValidationReport.model_validate(data)


def test_duplicate_manifest_step_rejected():
    data = _json("manifest.json")
    data["steps"].append(copy.deepcopy(data["steps"][0]))
    with pytest.raises(ValidationError):
        models.Manifest.model_validate(data)


def test_literature_var_needs_mean():
    data = _json("targets_base.json")
    del data["targets"][0]["vars"]["tmin_c"]["mean"]
    with pytest.raises(ValidationError):
        models.TargetsBaseFile.model_validate(data)


@pytest.mark.parametrize("bad", [-0.1, 1.1, float("nan"), float("inf")])
def test_weights_out_of_range_rejected(bad):
    with pytest.raises(ValidationError):
        models.Weights(terrain=bad, temperature=1, water_ice=1, biology=0.5)


def test_weights_missing_dimension_rejected():
    with pytest.raises(ValidationError):
        models.Weights(terrain=1, temperature=1, water_ice=1)


# --- Real files in data/processed/ (TAI-19) ----------------------------------
# Those the pipeline has not produced yet are skipped; the ones that exist must comply.

REAL = Path(__file__).parent.parent / "data" / "processed"


def _real(name: str) -> Path:
    path = REAL / name
    if not path.exists():
        pytest.skip(f"data/processed/{name} does not exist yet")
    return path


@pytest.mark.parametrize("name", list(schemas.BY_NAME))
def test_real_parquet_matches_schema(name):
    assert schemas.check_schema(pd.read_parquet(_real(f"{name}.parquet")), name) == []


@pytest.mark.parametrize(
    "fname,model",
    [
        ("targets.json", models.TargetsFile),
        ("validation.json", models.ValidationReport),
        ("manifest.json", models.Manifest),
    ],
)
def test_real_json_validates(fname, model):
    model.model_validate(json.loads(_real(fname).read_text(encoding="utf-8")))


def test_real_known_analogs_csv_validates():
    df = pd.read_csv(_real("known_analogs.csv"))
    assert tuple(df.columns) == schemas.KNOWN_ANALOGS_COLUMNS
    for row in df.to_dict(orient="records"):
        models.KnownAnalog.model_validate(row)


def test_real_caves_csv_validates():
    df = pd.read_csv(_real("caves.csv"))
    assert tuple(df.columns) == schemas.CAVES_COLUMNS
    for row in df.to_dict(orient="records"):
        models.Cave.model_validate(row)


def test_real_similarity_has_one_row_per_cell_and_target_with_scores_in_range():
    grid = pd.read_parquet(_real("grid.parquet"))
    sim = pd.read_parquet(_real("similarity.parquet"))
    assert len(sim) == len(grid) * len(TARGET_IDS)
    assert not sim.duplicated(["cell_id", "target_id"]).any()
    assert set(sim["cell_id"]) == set(grid["cell_id"])
    scores = sim[[c for c in sim.columns if c.startswith(("sv_", "s_"))] + ["bio_score"]]
    assert ((scores >= 0) & (scores <= 1) | scores.isna()).all().all()


def test_real_cells_exist_in_grid():
    grid_ids = set(pd.read_parquet(_real("grid.parquet"))["cell_id"])
    for name in ("features", "bio_samples", "similarity"):
        assert set(pd.read_parquet(_real(f"{name}.parquet"))["cell_id"]) <= grid_ids, name


def test_processed_folder_is_under_the_size_limit():
    from tai.constants import MAX_PROCESSED_MB

    if not REAL.exists():
        pytest.skip("data/processed does not exist")
    total = sum(p.stat().st_size for p in REAL.rglob("*") if p.is_file())
    assert total < MAX_PROCESSED_MB * 1024 * 1024, f"data/processed weighs {total / 1e6:.1f} MB"
