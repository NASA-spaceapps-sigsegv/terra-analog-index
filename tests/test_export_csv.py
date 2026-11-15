"""Ranking download as CSV (TAI-50, RF-34): the same rows and columns as the table."""

import io
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from tai import services, tables
from tai.constants import DEFAULT_WEIGHTS
from tai.errors import TargetNotFoundError, ZeroWeightsError
from tai.io import load_bundle
from ui import ranking_view

APP = str(Path(__file__).resolve().parents[1] / "streamlit_app.py")
W = dict(DEFAULT_WEIGHTS)


@pytest.fixture
def bundle(data_dir):
    return load_bundle(data_dir)


def _read(text: str) -> pd.DataFrame:
    return pd.read_csv(io.StringIO(text))


@pytest.mark.parametrize("hide_known", [False, True])
def test_csv_has_the_same_rows_and_columns_as_the_table(bundle, hide_known):
    ranking = services.get_ranking(bundle, "mars_jezero", W, hide_known=hide_known)
    table = tables.ranking_table(ranking)
    shown = table[tables.visible_columns(table)]
    csv = _read(services.export_ranking_csv(bundle, "mars_jezero", W, hide_known=hide_known))
    assert list(csv.columns) == list(shown.columns)
    assert csv["Rank"].tolist() == shown["Rank"].tolist()
    assert csv["Lon"].tolist() == pytest.approx(shown["Lon"].tolist())
    assert csv["Total"].tolist() == pytest.approx(shown["Total"].tolist(), abs=1e-3)


def test_hide_known_leaves_no_known_analog_in_the_file(bundle):
    weights = W | {"terrain": 0.0}  # with terrain at 0, cell 105 (a known analog) gets in
    assert _read(services.export_ranking_csv(bundle, "mars_jezero", weights))["Known analog"].notna().any()
    assert _read(services.export_ranking_csv(bundle, "mars_jezero", weights, hide_known=True))["Known analog"].isna().all()


def test_missing_values_are_empty_and_an_empty_optional_column_is_left_out(bundle):
    text = services.export_ranking_csv(bundle, "mars_jezero", W)
    assert "nan" not in text.lower() and "None" not in text
    assert "Dust and wind" not in text.splitlines()[0]  # the test data has no dust and wind


def test_same_errors_as_get_ranking(bundle):
    with pytest.raises(TargetNotFoundError):
        services.export_ranking_csv(bundle, "mars_gale", W)
    with pytest.raises(ZeroWeightsError):
        services.export_ranking_csv(bundle, "mars_jezero", {k: 0 for k in W})


def test_file_name_says_target_and_filter(bundle):
    assert ranking_view.csv_filename(services.get_ranking(bundle, "mars_jezero", W)) == "ranking_mars_jezero.csv"
    hidden = services.get_ranking(bundle, "mars_jezero", W, hide_known=True)
    assert ranking_view.csv_filename(hidden) == "ranking_mars_jezero_no_known.csv"


def test_the_app_offers_the_download_under_the_ranking(data_dir, monkeypatch):
    monkeypatch.setenv("TAI_DATA_DIR", str(data_dir))
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    buttons = at.tabs[0].get("download_button")
    assert len(buttons) == 1
    assert buttons[0].proto.label == "Download CSV"
