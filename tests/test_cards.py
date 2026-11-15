"""Site cards (design 11 and 12.1, SiteCard contract, TAI-32)."""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tai import cards, services
from tai.constants import BIO_TYPES, CORE_VARS, DIFFERENT_MAX, SIMILAR_MIN
from tai.errors import CellNotFoundError, InvalidWeightsError, TargetNotFoundError
from tai.io import load_bundle
from tai.models import KnownAnalog, Manifest, SiteCard, Target, Weights

ROOT = Path(__file__).resolve().parents[1]
CARDS_DIR = ROOT / "content" / "cards"
WEIGHTS = Weights(terrain=1.0, temperature=1.0, water_ice=1.0, biology=0.5)

# --- The contract example (JSON contracts, section 5) ----------------------------------

EXAMPLE_VARS = {
    #              earth   mean    std   unit       rule               score  source_target                source_type
    "slope_deg": (3.5, 4.5, 2.0, "°", "overlap", 0.607, "MOLA, PDS Geosciences", "measured"),
    "roughness_m": (38.0, 52.0, 30.0, "m", "overlap", 0.627, "MOLA, PDS Geosciences", "measured"),
    "tmin_c": (-4.2, -83.0, 5.0, "°C", "directional_low", 0.880, "Citation for Santino to add", "literature"),
    "trange_c": (31.6, 60.0, 8.0, "°C", "directional_high", 0.940, "Citation for Santino to add", "literature"),
    "precip_mm": (3.0, 0.0, 0.0, "mm/yr", "directional_low", 0.990, "By definition: no rain", "definition"),
    "ice_frac": (0.05, 0.0, 0.0, "fraction", "absence", 0.950, "Derived from has_ice", "definition"),
}
EXAMPLE_PHRASES = {
    "slope_deg": "3.5 ° vs. the target's 4.5 ± 2.0",
    "roughness_m": "38.0 m vs. the target's 52.0 ± 30.0",
    "tmin_c": "Colder than 88% of dry land; the target (-83.0 °C) lies outside the Earth range",
    "trange_c": "Higher than 94% of dry land; the target (60.0 °C) lies outside the Earth range",
    "precip_mm": "Drier than 99% of dry land; the target (0 mm/yr) lies outside the Earth range",
    "ice_frac": "No snow or ice 95% of the year; the target has no surface ice",
}
EARTH_NAMES = {
    "02_terrain": [("Global elevation model, 1 km", "ETOPO")],
    "03_temperature": [("MODIS, monthly land surface temperature, 2024", "MOD11C3")],
    "04_water_ice": [("GPM IMERG monthly, 2024", "GPM_3IMERGM"), ("MODIS, monthly snow cover, 2024", "MOD10CM"),
                     ("MODIS, annual land cover, 2024", "MCD12C1")],
    "05_biology_ncbi": [("NCBI BioSample", "BioSample")],
}
MARS_LIMITS = [
    "Gravity of 3.71 m/s² (38% of Earth's)",
    "Carbon dioxide atmosphere with less than 1% of Earth's pressure",
    "Much higher ultraviolet and cosmic radiation",
    "Perchlorate-bearing soil",
    "Global dust storms",
]


def example_manifest() -> Manifest:
    ran = datetime(2026, 11, 14, 18, 0, tzinfo=timezone.utc)
    steps = [
        {"step": step, "ran_at": ran, "duration_s": 1.0, "git_commit": None, "outputs": [], "columns": {},
         "inputs": [{"name": n, "product": p, "portal": "x", "url": "x", "files": 1, "size_mb": 1.0,
                     "license_note": "x"} for n, p in inputs]}
        for step, inputs in EARTH_NAMES.items()
    ]
    return Manifest(schema_version=1, project="terra-analog-index", data_year=2024, steps=steps)


def example_target(**changes) -> Target:
    var = {v: {"mean": m, "std": s, "unit": u, "rule": r, "source": src, "source_type": st,
               "earth_p01": 0.0, "earth_p99": 1.0, "earth_std": 1.0}
           for v, (_, m, s, u, r, _, src, st) in EXAMPLE_VARS.items()}
    data = {"target_id": "mars_jezero", "label": "Mars, Jezero crater", "body": "mars",
            "bounds": {"lat_min": 17.9, "lat_max": 18.9, "lon_min": 77.0, "lon_max": 78.0},
            "has_ice": False, "has_ice_source": "Morgan et al. (2021)", "summary": "s",
            "unreplicable": MARS_LIMITS, "notes": [], "vars": var} | changes
    return Target(**data)


def example_card(*, sim_changes=None, feature_changes=None, weights=WEIGHTS, cards_dir=None, **target_changes) -> SiteCard:
    features = {v: e for v, (e, *_rest) in EXAMPLE_VARS.items()}
    features |= {"bio_records": 15, "bio_types": 2, "bio_type_list": "halophile,xerophile"}
    features |= feature_changes or {}
    sim = {f"sv_{v}": row[5] for v, row in EXAMPLE_VARS.items()}
    sim |= {"s_terrain": 0.617, "s_temperature": 0.910, "s_water_ice": 0.970, "bio_score": 0.398,
            "eligible": True, "known_analog": "atacama_yungay", "known_analog_km": 67.0}
    sim |= sim_changes or {}
    analog = KnownAnalog(analog_id="atacama_yungay", name="Atacama Desert (Yungay)", lat=-24.08, lon=-69.92,
                         radius_km=150, target_id="mars_jezero", basis="Hyperaridity and nearly lifeless soils",
                         covered="yes", source="Navarro-González 2003")
    return cards.build_card(
        cell_id=23510,
        target=example_target(**target_changes),
        grid_row=pd.Series({"lat": -24.5, "lon": -69.5, "country": "Chile", "area_km2": 11250.4}),
        features_row=pd.Series(features, dtype=object),
        sim_row=pd.Series(sim, dtype=object),
        weights=weights,
        analogs={"atacama_yungay": analog},
        manifest=example_manifest(),
        cards_dir=cards_dir,
    )


def test_the_contract_example():
    card = example_card()
    assert card.header.label == "24.5°S 69.5°W" and card.header.country == "Chile"
    assert card.header.known_analog.name == "Atacama Desert (Yungay)"
    assert card.header.known_analog.distance_km == 67.0
    assert card.scores.total == pytest.approx(0.770, abs=1e-3)  # (0.617 + 0.910 + 0.970 + 0.5·0.398) / 3.5
    assert [v.variable for v in card.variables] == list(CORE_VARS)  # the example has no dust and wind
    assert {v.variable: v.phrase for v in card.variables} == EXAMPLE_PHRASES
    assert [d.dimension for d in card.similar_in] == ["temperature", "water_ice"]
    assert card.different_in == [] and card.similar_empty_phrase is None
    assert card.different_empty_phrase == "No physical dimension departs markedly"
    assert card.biology.phrase == "15 extreme-environment records in NCBI BioSample: halophiles, xerophiles"
    assert card.biology.source == "NCBI BioSample, queried on November 14, 2026"
    assert card.unreplicable == MARS_LIMITS
    assert card.manual is None


def test_sources_come_from_the_manifest_and_the_target():
    card = example_card()
    by_var = {v.variable: (v.source_earth, v.source_target) for v in card.variables}
    assert by_var["slope_deg"] == ("Global elevation model, 1 km", "MOLA, PDS Geosciences")
    assert by_var["precip_mm"][0] == "GPM IMERG monthly, 2024"
    assert by_var["ice_frac"][0] == "MODIS, monthly snow cover, 2024"
    sources = {s.name: s.used_for for s in card.sources}
    assert sources["Global elevation model, 1 km"] == ["slope_deg", "roughness_m"]
    assert sources["NCBI BioSample"] == ["bio_records", "bio_types"]
    assert sources["Morgan et al. (2021)"] == ["ice_frac"]  # the citation behind "Derived from has_ice"
    shown = {v for s in card.sources for v in s.used_for}
    assert set(CORE_VARS) <= shown  # no figure without a source (RF-28)


# --- The 12.1 rules ------------------------------------------------------------------------

DIMENSION_SCORES = [0.0, 0.29, 0.3, 0.5, 0.69, 0.7, 1.0, np.nan]


@pytest.mark.parametrize("terrain", DIMENSION_SCORES)
@pytest.mark.parametrize("water", [0.1, 0.7, np.nan])
def test_each_dimension_is_in_at_most_one_list(terrain, water):
    card = example_card(sim_changes={"s_terrain": terrain, "s_water_ice": water})
    similar = {d.dimension for d in card.similar_in}
    different = {d.dimension for d in card.different_in}
    assert not similar & different
    for d in card.similar_in:
        assert d.score >= SIMILAR_MIN
    for d in card.different_in:
        assert d.score < DIFFERENT_MAX
    if np.isnan(terrain):
        assert "terrain" not in similar | different


def test_empty_lists_get_their_fixed_phrases():
    card = example_card(sim_changes={"s_terrain": 0.5, "s_temperature": 0.5, "s_water_ice": 0.5})
    assert card.similar_empty_phrase == "No physical dimension reaches a high similarity"
    assert card.different_empty_phrase == "No physical dimension departs markedly"


@pytest.mark.parametrize("records,types,phrase", [
    (0, "", "No records in NCBI BioSample"),
    (1, "psychrophile", "1 extreme-environment record in NCBI BioSample: psychrophiles"),
    (15, "halophile,xerophile", "15 extreme-environment records in NCBI BioSample: halophiles, xerophiles"),
])
def test_limits_and_sampling_note_are_always_there(records, types, phrase):
    card = example_card(feature_changes={"bio_records": records, "bio_type_list": types})
    assert card.biology.phrase == phrase
    assert card.biology.sampling_note == cards.SAMPLING_NOTE
    assert card.unreplicable == MARS_LIMITS


def test_a_card_without_limits_is_rejected():
    with pytest.raises(ValueError):
        example_card(unreplicable=[])


@pytest.mark.parametrize("variable,rule,earth,score,mean,unit,expected", [
    ("slope_deg", "overlap", 3.5, 0.6, 4.5, "°", "3.5 ° vs. the target's 4.5 ± 2.0"),
    ("tmin_c", "directional_low", -60.0, 0.995, -223.0, "°C",
     "Colder than 100% of dry land; the target (-223.0 °C) lies outside the Earth range"),
    ("precip_mm", "directional_low", 30.0, 0.9, 0.0, "mm/yr",
     "Drier than 90% of dry land; the target (0 mm/yr) lies outside the Earth range"),
    ("trange_c", "directional_high", 20.0, 0.42, 152.0, "°C",
     "Higher than 42% of dry land; the target (152.0 °C) lies outside the Earth range"),
    ("ice_frac", "presence", 0.25, 0.25, 1.0, "fraction", "Snow or ice 25% of the year; the target has ice"),
    ("ice_frac", "absence", 0.25, 0.75, 0.0, "fraction",
     "No snow or ice 75% of the year; the target has no surface ice"),
    ("slope_deg", "overlap", None, None, 4.5, "°", "No data for this cell"),
    ("tmin_c", "directional_low", np.nan, np.nan, -80.0, "°C", "No data for this cell"),
])
def test_the_phrase_matches_the_rule(variable, rule, earth, score, mean, unit, expected):
    assert cards.variable_phrase(variable, rule, earth, score, mean, 2.0, unit) == expected


def test_a_variable_without_data_has_null_value_and_score():
    card = example_card(sim_changes={"sv_tmin_c": np.nan}, feature_changes={"tmin_c": np.nan})
    tmin = next(v for v in card.variables if v.variable == "tmin_c")
    assert tmin.earth_value is None and tmin.score is None and tmin.phrase == cards.PHRASE_NO_DATA


def test_all_weights_zero_gives_a_null_total_and_no_error():
    card = example_card(weights=Weights(terrain=0, temperature=0, water_ice=0, biology=0))
    assert card.scores.total is None and card.scores.terrain == 0.617


def test_a_card_that_is_not_eligible_has_no_total_and_says_why():
    card = example_card(sim_changes={"eligible": False, "s_terrain": np.nan, "s_temperature": np.nan})
    assert card.scores.total is None and not card.eligible
    assert card.notes[0] == cards.NOT_ELIGIBLE_NOTE


@pytest.mark.parametrize("lat,lon,label", [(-24.5, -69.5, "24.5°S 69.5°W"), (0.5, 0.5, "0.5°N 0.5°E"),
                                           (-89.5, 179.5, "89.5°S 179.5°E")])
def test_coordinate_label(lat, lon, label):
    assert cards.coord_label(lat, lon) == label


def test_bio_type_labels_match_the_config():
    config = json.loads((ROOT / "config" / "bio_terms.json").read_text(encoding="utf-8"))
    assert cards.BIO_TYPE_LABELS == {t["extremophile_type"]: t["label"] for t in config["types"]}
    assert set(cards.BIO_TYPE_LABELS) == set(BIO_TYPES)


# --- Manual text (11.3) ---------------------------------------------------------------------

GOOD_MANUAL = "# Eastern edge of the Salar de Atacama\n\n" + " ".join(["word"] * 180) + " [1].\n\n## Sources\n\n1. Author (2020). Title.\n"


def test_a_manual_file_appears_without_touching_code(tmp_path):
    assert example_card(cards_dir=tmp_path).manual is None
    (tmp_path / "23510__mars_jezero.md").write_text(GOOD_MANUAL, encoding="utf-8")
    manual = example_card(cards_dir=tmp_path).manual
    assert manual.title == "Eastern edge of the Salar de Atacama"
    assert manual.body_md.startswith("word") and "## Sources" in manual.body_md


def test_a_manual_file_of_another_target_does_not_appear(tmp_path):
    (tmp_path / "23510__moon_south_pole.md").write_text(GOOD_MANUAL, encoding="utf-8")
    assert example_card(cards_dir=tmp_path).manual is None


@pytest.mark.parametrize("text,problem", [
    (GOOD_MANUAL, None),
    (GOOD_MANUAL.replace("# Eastern", "Eastern"), "title"),
    (GOOD_MANUAL.split("## Sources")[0], "Sources"),
    (GOOD_MANUAL.replace("1. Author (2020). Title.", "Pending."), "list item"),
    (GOOD_MANUAL + "\n## Another section\n", "last section"),
    ("# T\n\nShort.\n\n## Sources\n\n1. A.\n", "words"),
])
def test_manual_format_check(text, problem):
    problems = cards.manual_problems(text)
    if problem is None:
        assert problems == []
    else:
        assert any(problem in p for p in problems), problems


@pytest.mark.parametrize("path", sorted(CARDS_DIR.glob("*.md")), ids=lambda p: p.name)
def test_manual_texts_never_say_equal_or_identical_to_the_target(path):
    """TAI-33: a high score does not mean "equal to" the Moon or Mars (design 14, point 1)."""
    text = path.read_text(encoding="utf-8").lower()
    assert not re.search(r"\b(?:equal|identical)\s+to\b|\bthe\s+same\s+as\b", text), path.name


@pytest.mark.parametrize("path", sorted(CARDS_DIR.glob("*.md")), ids=lambda p: p.name)
def test_every_manual_file_has_title_and_sources(path):
    stem = path.stem
    assert "__" in stem, f"{path.name}: the name must be <cell_id>__<target_id>.md"
    cell, target = stem.split("__", 1)
    assert cell.isdigit() and 0 <= int(cell) < 64800, f"{path.name}: invalid cell_id"
    assert target in {"moon_south_pole", "mars_jezero"}, f"{path.name}: unknown target"
    assert cards.manual_problems(path.read_text(encoding="utf-8")) == []


# --- Service ---------------------------------------------------------------------------------


@pytest.fixture
def bundle(data_dir):
    return load_bundle(data_dir)


@pytest.mark.parametrize("target_id", ["moon_south_pole", "mars_jezero"])
def test_every_cell_of_the_test_data_gets_a_valid_card(bundle, target_id):
    for cell in bundle.similarity[target_id].index:
        card = services.get_site_card(bundle, cell, target_id, WEIGHTS, cards_dir=None)
        assert card.unreplicable and card.biology.sampling_note
        assert len(card.variables) == len(bundle.targets.targets[0].vars)  # the six and, if the target has them, dust and wind


def test_card_total_matches_the_ranking(bundle):
    ranking = services.get_ranking(bundle, "mars_jezero", WEIGHTS)
    for item in ranking.items:
        card = services.get_site_card(bundle, item.cell_id, "mars_jezero", WEIGHTS, cards_dir=None)
        assert card.scores.total == pytest.approx(item.total, abs=1e-3)


def test_the_card_follows_the_weights(bundle):
    a = services.get_site_card(bundle, 100, "mars_jezero", WEIGHTS, cards_dir=None)
    b = services.get_site_card(bundle, 100, "mars_jezero", WEIGHTS.model_copy(update={"terrain": 0.0}), cards_dir=None)
    assert a.scores.total != b.scores.total


def test_service_errors(bundle):
    with pytest.raises(TargetNotFoundError):
        services.get_site_card(bundle, 100, "mars_gale", WEIGHTS)
    with pytest.raises(CellNotFoundError):
        services.get_site_card(bundle, 999, "mars_jezero", WEIGHTS)
    with pytest.raises(InvalidWeightsError):
        services.get_site_card(bundle, 100, "mars_jezero", {"terrain": 2.0, "temperature": 1, "water_ice": 1, "biology": 0})


def test_service_with_zero_weights_does_not_fail(bundle):
    zero = {"terrain": 0, "temperature": 0, "water_ice": 0, "biology": 0}
    assert services.get_site_card(bundle, 100, "mars_jezero", zero, cards_dir=None).scores.total is None


def test_service_reads_the_manual_from_the_cards_dir(bundle, tmp_path):
    (tmp_path / "100__mars_jezero.md").write_text(GOOD_MANUAL, encoding="utf-8")
    card = services.get_site_card(bundle, 100, "mars_jezero", WEIGHTS, cards_dir=tmp_path)
    assert card.manual is not None and card.manual.path.endswith("100__mars_jezero.md")
