"""TAI-32 in the app: the card of the selected cell (design 11.1 and 10.6)."""

from pathlib import Path

import numpy as np
import pytest
from streamlit.testing.v1 import AppTest

from tests.test_cards import example_card
from ui import card_view

APP = str(Path(__file__).resolve().parents[1] / "streamlit_app.py")
SELECTED = "selected_cell_id"


def test_radar_has_four_axes_and_a_null_dimension_sits_at_zero_with_its_label():
    card = example_card(sim_changes={"s_temperature": np.nan, "sv_tmin_c": np.nan, "sv_trange_c": np.nan})
    labels, values = card_view.radar_axes(card)
    assert len(labels) == 4 and all(0 <= v <= 1 for v in values)
    assert labels[1] == "Temperature (no data)" and values[1] == 0.0
    trace = card_view.radar_figure(card).data[0]
    assert list(trace.r) == values + values[:1]  # closed polygon


def test_radar_labels_are_readable_on_the_theme_background():
    polar = card_view.radar_figure(example_card()).layout.polar
    assert polar.bgcolor == "rgba(0,0,0,0)"  # not a white disk under light text
    assert list(polar.radialaxis.ticktext) == ["0.30", "0.70", "1.00"]
    assert polar.radialaxis.angle % 90 != 0  # the numbers do not sit on an axis


def test_variables_table_shows_earth_against_target():
    df = card_view.variables_table(example_card(feature_changes={"tmin_c": np.nan}, sim_changes={"sv_tmin_c": np.nan}))
    assert list(df.columns) == list(card_view.VARIABLE_COLUMNS) and len(df) == 6
    slope = df.iloc[0]
    assert (slope["Earth"], slope["Target"]) == ("3.5 °", "4.5 ± 2.0 °")
    assert df.iloc[4]["Target"] == "0 mm/yr"  # std 0: no "± 0"
    assert df.iloc[2]["Earth"] == "no data" and np.isnan(df.iloc[2]["Score"])


@pytest.fixture
def app(data_dir, monkeypatch):
    monkeypatch.setenv("TAI_DATA_DIR", str(data_dir))
    return AppTest.from_file(APP, default_timeout=30).run()


def _text(app) -> str:
    return "\n".join(m.value for m in app.markdown) + "\n".join(c.value for c in app.caption)


def test_selected_cell_shows_its_card_with_limits_and_sampling_note(app):
    app.session_state[SELECTED] = 102
    app.run()
    assert not app.exception and not app.error
    text = _text(app)
    assert "Cell 89.5°S" in text and "Chile" in text
    assert "Limits no site on Earth replicates" in text and "gravity" in text
    assert "A lack of records may mean" in text
    assert len(app.get("plotly_chart")) == 2  # map and radar
    explore = app.tabs[0]  # the Method tab has its own tables
    assert len(explore.dataframe) == 2  # ranking y variables
    variables = explore.dataframe[1].proto
    assert variables.row_height > 64  # at 64 px or less st.dataframe does not wrap the text
    assert set(card_view.COLUMN_WIDTHS) == set(card_view.VARIABLE_COLUMNS)
    assert sum(card_view.COLUMN_WIDTHS.values()) <= 760  # fits in the card column without scrolling
    assert card_view.table_height(6) == 35 + 6 * variables.row_height + 2  # every row fits, without scrolling


def test_card_updates_when_the_weights_change(app):
    app.session_state[SELECTED] = 100
    app.run()
    before = app.metric[0].value
    app.sidebar.slider(key="w_terrain").set_value(0.0).run()
    assert app.metric[0].value != before


def test_all_weights_zero_keeps_the_card_with_a_null_total(app):
    app.session_state[SELECTED] = 100
    for dim in ("terrain", "temperature", "water_ice", "dust_wind", "biology"):
        app.sidebar.slider(key=f"w_{dim}").set_value(0.0)
    app.run()
    assert not app.exception
    assert any("Raise at least one weight" in w.value for w in app.warning)
    assert app.metric[0].value == "no data"
    assert "Limits no site on Earth replicates" in _text(app)


def test_a_known_analog_cell_shows_its_label(app):
    app.session_state[SELECTED] = 105
    app.run()
    assert "Known analog: Atacama" in _text(app)


def test_a_cell_that_is_not_eligible_still_has_a_card(app):
    app.session_state[SELECTED] = 103
    app.run()
    assert not app.exception and app.metric[0].value == "no data"
    assert "Insufficient data" in _text(app)


def test_no_selection_shows_the_hint(app):
    assert any("Pick a row in the ranking" in i.value for i in app.info)
    assert not app.metric
