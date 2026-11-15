"""Scoring rules (TAI-18, design 5.1 to 5.5 and 12.1)."""

import math

import numpy as np
import pytest

from tai import rules

NAN = np.nan


# --- overlap (5.2) -----------------------------------------------------------


def test_overlap_is_1_at_the_target_mean():
    assert rules.overlap([4.5], 4.5, 2.0, 5.0)[0] == 1.0


def test_overlap_matches_the_design_example():
    # x = 6, mean 4.5, std 2, Earth std 5: sigma = 2, S = exp(-0.75)
    assert rules.overlap([6.0], 4.5, 2.0, 5.0)[0] == pytest.approx(0.472, abs=5e-4)


def test_overlap_sigma_floor_acts():
    # target std 0.1 and Earth std 5: the floor gives sigma = 0.5, not 0.1
    got = rules.overlap([5.0], 4.5, 0.1, 5.0)[0]
    assert got == pytest.approx(math.exp(-1.0))
    assert got > rules.overlap([5.0], 4.5, 0.1, 0.0)[0]


def test_overlap_is_symmetric_and_decreasing():
    s = rules.overlap([3.0, 4.0, 4.5, 5.0, 6.0], 4.5, 1.0, 5.0)
    assert s[0] == pytest.approx(s[4]) and s[1] == pytest.approx(s[3])
    assert s[0] < s[1] < s[2]


def test_overlap_with_no_spread_at_all():
    assert list(rules.overlap([0.0, 1.0, NAN], 0.0, 0.0, 0.0)[:2]) == [1.0, 0.0]


# --- directional (5.3) -------------------------------------------------------


def test_directional_most_extreme_cell_scores_1():
    x = np.array([-50.0, -10.0, 0.0, 20.0])
    assert rules.directional_low(x, 1.0)[0] == 1.0
    assert rules.directional_high(x, 1.0)[3] == 1.0


def test_directional_respects_the_order():
    x = np.array([3.0, -2.0, 7.0, 0.0])
    low, high = rules.directional_low(x, 1.0), rules.directional_high(x, 1.0)
    assert list(np.argsort(-low)) == list(np.argsort(x))
    assert list(np.argsort(-high)) == list(np.argsort(-x))


def test_directional_equal_areas_give_plain_shares():
    x = np.array([1.0, 2.0, 3.0, 4.0])
    assert list(rules.directional_high(x, 1.0)) == [0.25, 0.5, 0.75, 1.0]
    assert list(rules.directional_low(x, 1.0)) == [1.0, 0.75, 0.5, 0.25]


def test_directional_is_weighted_by_area():
    # the cold cell covers 3/4 of the area: the temperate one is "colder than or equal to" only its own 1/4
    x = np.array([-40.0, 10.0])
    area = np.array([3.0, 1.0])
    assert list(rules.directional_low(x, area)) == [1.0, 0.25]
    assert list(rules.directional_high(x, area)) == [0.75, 1.0]


def test_directional_ties_share_the_score():
    x = np.array([1.0, 1.0, 2.0])
    assert list(rules.directional_high(x, 1.0)) == pytest.approx([2 / 3, 2 / 3, 1.0])
    assert list(rules.directional_low(x, 1.0)) == pytest.approx([1.0, 1.0, 1 / 3])


def test_directional_nulls_stay_null_and_do_not_count():
    x = np.array([1.0, NAN, 2.0])
    area = np.array([1.0, 100.0, 1.0])
    high = rules.directional_high(x, area)
    assert np.isnan(high[1]) and list(high[[0, 2]]) == [0.5, 1.0]


def test_directional_all_null():
    assert np.isnan(rules.directional_low([NAN, NAN], 1.0)).all()


def test_directional_rejects_bad_areas():
    with pytest.raises(ValueError):
        rules.directional_low([1.0, 2.0], [1.0, 0.0])


# --- presence and absence (5.4) -----------------------------------------------


def test_presence_and_absence_add_up_to_1():
    ice = np.array([0.0, 0.25, 1.0])
    assert list(rules.presence(ice) + rules.absence(ice)) == [1.0, 1.0, 1.0]
    assert list(rules.presence(ice)) == [0.0, 0.25, 1.0]


def test_presence_and_absence_keep_nulls():
    assert np.isnan(rules.presence([NAN])[0]) and np.isnan(rules.absence([NAN])[0])


def test_overlap_keeps_nulls():
    assert np.isnan(rules.overlap([NAN, 1.0], 1.0, 1.0, 1.0)[0])


def test_score_variable_dispatches_and_rejects_unknown_rules():
    x = np.array([0.0, 1.0])
    assert list(rules.score_variable("absence", x, 1.0, 0, 0, 0)) == [1.0, 0.0]
    assert list(rules.score_variable("directional_high", x, 1.0, 0, 0, 0)) == [0.5, 1.0]
    with pytest.raises(ValueError):
        rules.score_variable("nope", x, 1.0, 0, 0, 0)


# --- choice of rule (5.1) ---------------------------------------------------


@pytest.mark.parametrize("mean,expected", [(-83.0, "directional_low"), (10.0, "overlap"),
                                           (60.0, "directional_high"), (-62.0, "overlap"), (26.0, "overlap")])
def test_choose_rule_by_earth_percentiles(mean, expected):
    assert rules.choose_rule("tmin_c", mean, -62.0, 26.0, False) == expected


def test_choose_rule_terrain_is_always_overlap():
    assert rules.choose_rule("slope_deg", 500.0, 0.1, 21.0, True) == "overlap"
    assert rules.choose_rule("roughness_m", -1.0, 1.0, 310.0, False) == "overlap"


def test_choose_rule_ice_follows_has_ice():
    assert rules.choose_rule("ice_frac", 1.0, 0.0, 1.0, True) == "presence"
    assert rules.choose_rule("ice_frac", 0.0, 0.0, 1.0, False) == "absence"


def test_choose_rule_rejects_unknown_variables_and_null_means():
    with pytest.raises(ValueError):
        rules.choose_rule("bio_records", 1.0, 0.0, 1.0, False)
    with pytest.raises(ValueError):
        rules.choose_rule("tmin_c", float("nan"), 0.0, 1.0, False)


# --- dimension and biology (5.5) --------------------------------------------


def test_dimension_is_the_mean_of_the_variables_with_data():
    got = rules.dimension_score([0.2, NAN, NAN], [0.6, 0.4, NAN])
    assert got[0] == pytest.approx(0.4) and got[1] == pytest.approx(0.4) and np.isnan(got[2])


def test_bio_score_matches_the_design_example():
    # n = 12, n_max = 400, t = 2 -> 0,381
    assert rules.bio_score([12], [2], n_max=400)[0] == pytest.approx(0.381, abs=5e-4)


def test_bio_score_without_records_is_0_never_null():
    got = rules.bio_score([0, 400], [0, 6])
    assert got[0] == 0.0 and got[1] == 1.0


def test_bio_score_with_no_records_anywhere_is_all_0():
    assert list(rules.bio_score([0, 0], [0, 0])) == [0.0, 0.0]


# --- weighted Earth statistics (step 06) ------------------------------------


def test_weighted_quantile_follows_the_area():
    x = np.array([1.0, 2.0, 3.0, NAN])
    assert rules.weighted_quantile(x, [1, 1, 1, 50], 0.5) == 2.0  # the null does not count
    assert rules.weighted_quantile(x, [10, 1, 1, 1], 0.5) == 1.0
    assert rules.weighted_quantile(x, 1.0, 0.0) == 1.0 and rules.weighted_quantile(x, 1.0, 1.0) == 3.0


def test_weighted_std():
    assert rules.weighted_std([1.0, 3.0], [1.0, 1.0]) == pytest.approx(1.0)
    assert rules.weighted_std([1.0, 3.0, NAN], [3.0, 1.0, 1.0]) == pytest.approx(math.sqrt(0.75))
    assert math.isnan(rules.weighted_std([NAN], [1.0]))
