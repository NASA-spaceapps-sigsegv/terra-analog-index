"""TAI-30 dentro de la app: el mapa aparece en Explorar y sigue a los controles."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "streamlit_app.py")


@pytest.fixture
def app(data_dir, monkeypatch):
    monkeypatch.setenv("TAI_DATA_DIR", str(data_dir))
    return AppTest.from_file(APP, default_timeout=30).run()


def test_explore_shows_the_map_and_no_placeholder(app):
    assert not app.exception and not app.error
    assert len(app.get("plotly_chart")) == 1
    assert not any("El mapa llega" in i.value for i in app.info)


def test_all_weights_zero_keeps_the_gray_map_and_shows_the_warning(app):
    for dim in ("terrain", "temperature", "water_ice", "dust_wind", "biology"):
        app.sidebar.slider(key=f"w_{dim}").set_value(0.0)
    app.run()
    assert not app.exception
    assert any("Subí al menos un peso" in w.value for w in app.warning)
    assert len(app.get("plotly_chart")) == 1


@pytest.mark.parametrize("view", ["south_pole", "north_pole", "world"])
def test_changing_the_projection_redraws_without_errors(app, view):
    app.sidebar.radio(key="projection").set_value(view).run()
    assert not app.exception and len(app.get("plotly_chart")) == 1


def test_changing_the_target_redraws_the_map(app):
    app.sidebar.radio(key="target_id").set_value("mars_jezero").run()
    assert not app.exception and len(app.get("plotly_chart")) == 1
