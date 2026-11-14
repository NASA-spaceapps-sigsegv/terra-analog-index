"""tai/scoring.py: ejemplos de 5.6, elegibilidad y orden de 5.7 (design 12.1, TAI-19)."""

import time

import numpy as np
import pandas as pd
import pytest

from tai import scoring
from tai.constants import DEFAULT_WEIGHTS, N_CELLS_GLOBAL
from tai.errors import InvalidWeightsError, ZeroWeightsError
from tai.models import Weights

NAN = np.nan
COLS = ["s_terrain", "s_temperature", "s_water_ice", "bio_score"]


def make_sim(rows, known=None) -> pd.DataFrame:
    """rows: dict cell_id -> (terreno, temperatura, agua y hielo, biología)."""
    ids = list(rows)
    df = pd.DataFrame([rows[i] for i in ids], columns=COLS, dtype="float32")
    df.index = pd.Index(ids, name="cell_id", dtype="int32")
    df["known_analog"] = pd.array([(known or {}).get(i) for i in ids], dtype="string")
    return df


def order(sim, weights=DEFAULT_WEIGHTS, hide_known=False):
    return list(scoring.rank(sim, scoring.combine(sim, weights), hide_known=hide_known)["cell_id"])


# --- combine (5.6) -----------------------------------------------------------


def test_design_example_all_dimensions():
    sim = make_sim({1: (0.62, 0.91, 0.97, 0.40)})
    assert scoring.combine(sim, DEFAULT_WEIGHTS).iloc[0] == pytest.approx(0.771, abs=5e-4)


def test_design_example_null_temperature_leaves_the_denominator():
    sim = make_sim({1: (0.62, NAN, 0.97, 0.40)})
    assert scoring.combine(sim, DEFAULT_WEIGHTS).iloc[0] == pytest.approx(0.716, abs=5e-4)


def test_null_is_not_a_zero():
    full = make_sim({1: (0.5, 0.5, 0.5, 0.5)})
    holey = make_sim({1: (0.5, NAN, 0.5, 0.5)})
    assert scoring.combine(full, DEFAULT_WEIGHTS).iloc[0] == pytest.approx(0.5)
    assert scoring.combine(holey, DEFAULT_WEIGHTS).iloc[0] == pytest.approx(0.5)  # con 0 sería menor


def test_zero_weight_equals_dropping_the_dimension():
    sim = make_sim({1: (0.9, 0.1, 0.5, 0.2), 2: (0.1, 0.9, 0.5, 0.2), 3: (0.5, 0.5, 0.4, 0.9)})
    weights = dict(DEFAULT_WEIGHTS, terrain=0.0)
    by_hand = pd.Series({1: (0.1 + 0.5 + 0.5 * 0.2) / 2.5, 2: (0.9 + 0.5 + 0.5 * 0.2) / 2.5,
                         3: (0.5 + 0.4 + 0.5 * 0.9) / 2.5})
    got = scoring.combine(sim, weights)
    assert got.to_dict() == pytest.approx(by_hand.to_dict())
    assert order(sim, weights) == list(by_hand.sort_values(ascending=False).index)


def test_zero_weight_on_the_only_dimension_with_data_gives_null_total():
    sim = make_sim({1: (0.5, NAN, NAN, 0.8)})
    total = scoring.combine(sim, dict(DEFAULT_WEIGHTS, terrain=0.0, biology=0.0))
    assert total.isna().all()


def test_combine_keeps_the_index_and_does_not_modify_the_input():
    sim = make_sim({7: (0.2, 0.4, 0.6, 0.8), 3: (0.1, 0.1, 0.1, 0.1)})
    before = sim.copy()
    total = scoring.combine(sim, DEFAULT_WEIGHTS)
    assert list(total.index) == [7, 3]
    pd.testing.assert_frame_equal(sim, before)


def test_weights_can_be_a_weights_object():
    sim = make_sim({1: (0.2, 0.4, 0.6, 0.8)})
    w = Weights(**DEFAULT_WEIGHTS)
    assert scoring.combine(sim, w).iloc[0] == scoring.combine(sim, DEFAULT_WEIGHTS).iloc[0]


# --- validate_weights --------------------------------------------------------


def test_all_zero_weights_raise():
    with pytest.raises(ZeroWeightsError):
        scoring.validate_weights(dict.fromkeys(DEFAULT_WEIGHTS, 0.0))
    with pytest.raises(ZeroWeightsError):
        scoring.combine(make_sim({1: (0.5, 0.5, 0.5, 0.5)}), dict.fromkeys(DEFAULT_WEIGHTS, 0.0))


@pytest.mark.parametrize("bad", [1.5, -0.1, float("nan"), float("inf")])
def test_weight_out_of_range_raises(bad):
    with pytest.raises(InvalidWeightsError):
        scoring.validate_weights(dict(DEFAULT_WEIGHTS, terrain=bad))


def test_missing_or_unknown_dimension_raises():
    with pytest.raises(InvalidWeightsError):
        scoring.validate_weights({"terrain": 1.0})
    with pytest.raises(InvalidWeightsError):
        scoring.validate_weights(dict(DEFAULT_WEIGHTS, polvo=1.0))


def test_valid_weights_come_back_as_weights():
    assert scoring.validate_weights(DEFAULT_WEIGHTS).as_dict() == dict(DEFAULT_WEIGHTS)


# --- is_eligible (5.7) -------------------------------------------------------


@pytest.mark.parametrize(
    "physical,expected",
    [((0.5, NAN, NAN), False), ((0.5, 0.5, NAN), True), ((NAN, 0.5, 0.5), True), ((0.5, 0.5, 0.5), True)],
)
def test_eligibility_needs_two_of_three_physical_dimensions(physical, expected):
    sim = make_sim({1: (*physical, 0.9)})
    assert bool(scoring.is_eligible(sim).iloc[0]) is expected


def test_biology_does_not_count_for_eligibility():
    assert not scoring.is_eligible(make_sim({1: (NAN, NAN, NAN, 1.0)})).iloc[0]
    assert not scoring.is_eligible(make_sim({1: (0.5, NAN, NAN, 1.0)})).iloc[0]


# --- rank (5.7) --------------------------------------------------------------


def test_rank_sorts_descending_and_drops_ineligible_cells():
    sim = make_sim({10: (0.2, 0.2, 0.2, 0.0), 11: (0.9, 0.9, 0.9, 0.0), 12: (0.99, NAN, NAN, 1.0)})
    assert order(sim) == [11, 10]  # 12 tiene una sola dimensión física


def test_rank_returns_cell_id_scores_and_total_columns():
    sim = make_sim({10: (0.2, 0.2, 0.2, 0.0)})
    ranked = scoring.rank(sim, scoring.combine(sim, DEFAULT_WEIGHTS))
    assert {"cell_id", "total", *COLS, "known_analog"} <= set(ranked.columns)
    assert list(ranked.index) == [0]


@pytest.mark.parametrize("input_order", [[5, 3, 9], [9, 5, 3], [3, 9, 5]])
def test_ties_are_broken_by_ascending_cell_id(input_order):
    sim = make_sim({i: (0.5, 0.5, 0.5, 0.5) for i in input_order})
    assert order(sim) == [3, 5, 9]


def test_float32_noise_does_not_break_a_real_tie():
    # 0.1 + 0.2 y 0.3 son iguales en papel pero no en float32
    sim = make_sim({2: (0.3, 0.3, 0.3, 0.3), 1: (0.1, 0.2, 0.6, 0.3)})
    w = dict(terrain=1.0, temperature=1.0, water_ice=1.0, biology=0.0)
    assert order(sim, w) == [1, 2]


def test_hide_known_removes_known_analogs_only_when_asked():
    sim = make_sim({1: (0.9, 0.9, 0.9, 0.0), 2: (0.5, 0.5, 0.5, 0.0)}, known={1: "atacama_yungay"})
    assert order(sim) == [1, 2]
    assert order(sim, hide_known=True) == [2]


def test_rank_of_an_empty_selection_is_empty():
    sim = make_sim({1: (0.5, NAN, NAN, 0.5)})
    assert scoring.rank(sim, scoring.combine(sim, DEFAULT_WEIGHTS)).empty


# --- rendimiento (criterio de aceptación: menos de 50 ms) ---------------------


def test_combine_on_the_whole_grid_takes_under_50_ms():
    rng = np.random.default_rng(0)
    n = N_CELLS_GLOBAL  # 64 800 celdas, más que las 21 357 de tierra firme
    data = rng.random((n, 4), dtype="float32")
    data[:, :3][rng.random((n, 3)) < 0.1] = NAN  # 10 % de huecos en las tres dimensiones físicas
    sim = pd.DataFrame(data, columns=COLS, index=pd.Index(np.arange(n, dtype="int32"), name="cell_id"))
    scoring.combine(sim, DEFAULT_WEIGHTS)  # calienta
    best = min(_timed(scoring.combine, sim, DEFAULT_WEIGHTS) for _ in range(5))
    assert best < 0.050, f"combine tardó {best * 1000:.1f} ms"


def _timed(fn, *args) -> float:
    t0 = time.perf_counter()
    fn(*args)
    return time.perf_counter() - t0
