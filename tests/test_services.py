import pytest

from tai import io, services
from tai.constants import DEFAULT_WEIGHTS
from tai.errors import DataNotAvailableError, InvalidWeightsError, TargetNotFoundError, ZeroWeightsError

MOON = "moon_south_pole"


@pytest.fixture
def bundle(data_dir):
    return io.load_bundle(data_dir)


def ids(ranking):
    return [r.cell_id for r in ranking.items]


def test_list_targets(bundle):
    assert [t.target_id for t in services.list_targets(bundle)] == [MOON, "mars_jezero"]


def test_ranking_order_and_ties(bundle):
    r = services.get_ranking(bundle, MOON, DEFAULT_WEIGHTS)
    assert ids(r) == [104, 102, 100, 101, 105]  # 103 no es elegible; 100 y 101 empatan -> cell_id
    assert [x.rank for x in r.items] == [1, 2, 3, 4, 5]
    assert r.total_eligible == 5
    assert r.items[0].s_temperature is None  # nulo se conserva, no pasa a 0


def test_moving_a_weight_changes_the_order(bundle):
    w = dict(DEFAULT_WEIGHTS, terrain=0.0)
    assert ids(services.get_ranking(bundle, MOON, w)) == [101, 102, 104, 100, 105]


def test_hide_known_and_limit(bundle):
    r = services.get_ranking(bundle, MOON, DEFAULT_WEIGHTS, hide_known=True)
    assert 105 not in ids(r) and all(x.known_analog is None for x in r.items)
    assert len(services.get_ranking(bundle, MOON, DEFAULT_WEIGHTS, limit=2).items) == 2


def test_errors(bundle):
    with pytest.raises(ZeroWeightsError):
        services.get_ranking(bundle, MOON, dict.fromkeys(DEFAULT_WEIGHTS, 0.0))
    with pytest.raises(InvalidWeightsError):
        services.get_ranking(bundle, MOON, {"terrain": 1.0})
    with pytest.raises(InvalidWeightsError):
        services.get_ranking(bundle, MOON, dict(DEFAULT_WEIGHTS, terrain=1.5))
    with pytest.raises(TargetNotFoundError):
        services.get_ranking(bundle, "mars_gale", DEFAULT_WEIGHTS)


def test_missing_file_names_the_file_and_step(data_dir):
    (data_dir / "similarity.parquet").unlink()
    with pytest.raises(DataNotAvailableError, match=r"similarity\.parquet.*08_similarity"):
        io.load_bundle(data_dir)


def test_signature_changes_when_a_file_is_deleted(data_dir):
    before = io.data_signature(data_dir)
    (data_dir / "grid.parquet").unlink()
    assert io.data_signature(data_dir) != before


def test_ranking_follows_the_contract(bundle):
    r = services.get_ranking(bundle, MOON, DEFAULT_WEIGHTS, limit=3)
    assert (r.hide_known, r.limit, r.total_eligible) == (False, 3, 5)
    assert set(r.model_dump()) == {"target_id", "weights", "hide_known", "limit", "total_eligible", "items"}
    known = services.get_ranking(bundle, MOON, DEFAULT_WEIGHTS).items[-1]
    assert known.cell_id == 105
    assert known.known_analog.model_dump() == {"analog_id": "atacama_yungay", "name": "Atacama"}


def test_float32_ties_break_by_cell_id():
    import numpy as np
    import pandas as pd

    from tai import scoring

    sim = pd.DataFrame(
        {
            "s_terrain": np.array([0.1, 0.3], dtype="float32"),
            "s_temperature": np.array([0.5, 0.3], dtype="float32"),
            "s_water_ice": np.array([np.nan, np.nan], dtype="float32"),
            "bio_score": np.array([0.0, 0.0], dtype="float32"),
            "known_analog": [None, None],
        },
        index=pd.Index([200, 100], name="cell_id"),
    )
    total = scoring.combine(sim, DEFAULT_WEIGHTS)
    assert total.iloc[0] != total.iloc[1]  # 0.1 + 0.5 and 0.3 + 0.3 differ in float32...
    assert scoring.rank(sim, total)["cell_id"].tolist() == [100, 200]  # ...but tie on paper
