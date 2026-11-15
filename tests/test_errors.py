import pytest

from tai import errors


@pytest.mark.parametrize(
    "cls,status",
    [
        (errors.DataNotAvailableError, 503),
        (errors.TargetNotFoundError, 404),
        (errors.CellNotFoundError, 404),
        (errors.InvalidWeightsError, 422),
        (errors.ZeroWeightsError, 422),
    ],
)
def test_status_and_hierarchy(cls, status):
    err = cls("boom")
    assert isinstance(err, errors.TaiError)
    assert err.http_status == status


def test_to_dict_matches_contract():
    err = errors.TargetNotFoundError("Target site 'mars_gale' does not exist")
    assert err.to_dict() == {
        "error": "TargetNotFoundError",
        "detail": "Target site 'mars_gale' does not exist",
        "http_status": 404,
    }
