"""lat_lon parser (design 7.4 and 12.1, TAI-15)."""

import numpy as np
import pytest

from tai.latlon import parse_lat_lon


@pytest.mark.parametrize(
    "text,expected",
    [
        ("24.08 N 69.92 E", (24.08, 69.92)),
        ("24.08 S 69.92 W", (-24.08, -69.92)),  # S and W give negatives
        ("24.08 S, 69.92 W", (-24.08, -69.92)),  # comma between the two parts
        ("  18 N 77 E  ", (18.0, 77.0)),  # integers and spaces
        ("90 S 180 W", (-90.0, -180.0)),  # valid extremes
        ("-24.08 -69.92", (-24.08, -69.92)),  # signed decimals, space
        ("-24.08, -69.92", (-24.08, -69.92)),  # signed decimals, comma
        ("+37.7,-6.6", (37.7, -6.6)),
    ],
)
def test_valid_formats(text, expected):
    assert parse_lat_lon(text) == pytest.approx(expected)


@pytest.mark.parametrize(
    "text",
    ["missing", "Missing", "not collected", "Not Applicable", "NA", "na", "", "   ", None, float("nan"), np.nan],
)
def test_missing_values_are_rejected(text):
    assert parse_lat_lon(text) is None


@pytest.mark.parametrize("text", ["91 N 10 E", "91 S 10 E", "10 N 181 E", "10 N 181 W", "95, 10", "10, -190"])
def test_out_of_range_is_rejected(text):
    assert parse_lat_lon(text) is None


@pytest.mark.parametrize("text", ["0 N 0 E", "0 S 0 W", "0, 0", "0.0 0.0", "0.00 N 0.00 W"])
def test_exact_zero_zero_is_rejected(text):
    assert parse_lat_lon(text) is None


def test_zero_on_one_axis_is_valid():
    assert parse_lat_lon("0 N 25 E") == (0.0, 25.0)
    assert parse_lat_lon("40 N 0 E") == (40.0, 0.0)


@pytest.mark.parametrize("text", ["somewhere in Chile", "24.08 S", "24.08 X 69.92 W", "24.08 S 69.92 W extra", "1 2 3"])
def test_unknown_formats_are_rejected(text):
    assert parse_lat_lon(text) is None
