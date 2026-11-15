"""TAI-21 acceptance criteria, with the Streamlit test harness."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "streamlit_app.py")


@pytest.fixture
def app(data_dir, monkeypatch):
    monkeypatch.setenv("TAI_DATA_DIR", str(data_dir))
    return AppTest.from_file(APP, default_timeout=30).run()


def test_shows_the_ranking(app):
    assert not app.exception and not app.error
    assert len(app.dataframe[0].value) == 5


def test_moving_a_slider_changes_the_order(app):
    before = app.dataframe[0].value["Lon"].tolist()  # the 6 test cells share a latitude
    app.sidebar.slider(key="w_terrain").set_value(0.0).run()
    assert app.dataframe[0].value["Lon"].tolist() != before


def test_all_weights_zero_shows_the_warning(app):
    for dim in ("terrain", "temperature", "water_ice", "dust_wind", "biology"):
        app.sidebar.slider(key=f"w_{dim}").set_value(0.0)
    app.run()
    assert any("Raise at least one weight" in w.value for w in app.warning)
    assert not app.exception


def test_reset_button_restores_weights(app):
    app.sidebar.slider(key="w_terrain").set_value(0.0).run()
    app.sidebar.button(key="preset_balanced").click().run()  # the default weights, which is also the reset
    assert app.sidebar.slider(key="w_terrain").value == 1.0


def test_deleted_file_shows_its_name(data_dir, monkeypatch):
    (data_dir / "targets.json").unlink()
    monkeypatch.setenv("TAI_DATA_DIR", str(data_dir))
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert any("targets.json" in e.value for e in at.error)
