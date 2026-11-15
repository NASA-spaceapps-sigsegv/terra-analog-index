"""TAI-32 en la app: la ficha de la celda elegida (design 11.1 y 10.6)."""

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
    assert labels[1] == "Temperatura (sin dato)" and values[1] == 0.0
    trace = card_view.radar_figure(card).data[0]
    assert list(trace.r) == values + values[:1]  # polígono cerrado


def test_variables_table_shows_earth_against_target():
    df = card_view.variables_table(example_card(feature_changes={"tmin_c": np.nan}, sim_changes={"sv_tmin_c": np.nan}))
    assert list(df.columns) == list(card_view.VARIABLE_COLUMNS) and len(df) == 6
    slope = df.iloc[0]
    assert (slope["Tierra"], slope["Objetivo"]) == ("3,5 °", "4,5 ± 2,0 °")
    assert df.iloc[4]["Objetivo"] == "0 mm/año"  # desvío 0: sin "± 0"
    assert df.iloc[2]["Tierra"] == "sin dato" and np.isnan(df.iloc[2]["Puntaje"])


def test_variables_html_wraps_long_readings_and_keeps_bars():
    card = example_card(feature_changes={"tmin_c": np.nan}, sim_changes={"sv_tmin_c": np.nan})
    out = card_view.variables_html(card, "#123456")
    assert out.count("<tr>") == 7  # encabezado y 6 variables
    assert 'class="reading"' in out and "overflow-wrap: anywhere" in out
    assert "white-space: nowrap" not in out.split(".tai-vars td.reading")[1].split("}")[0]
    assert out.count("background:#123456") == 5  # una barra por variable con puntaje
    assert "sin dato" in out
    assert "Más fría" not in out  # la temperatura mínima sin dato no tiene frase direccional


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
    assert "Celda 89,5°S" in text and "Chile" in text
    assert "Límites que ningún sitio terrestre replica" in text and "gravedad" in text
    assert "La falta de registros puede deberse" in text
    assert len(app.get("plotly_chart")) == 2  # mapa y radar
    assert len(app.dataframe) == 1  # el ranking; la tabla de variables va en HTML
    table = [h for h in app.get("html") if "tai-vars" in h.proto.body]
    assert len(table) == 1 and "Pendiente media" in table[0].proto.body


def test_card_updates_when_the_weights_change(app):
    app.session_state[SELECTED] = 100
    app.run()
    before = app.metric[0].value
    app.sidebar.slider(key="w_terrain").set_value(0.0).run()
    assert app.metric[0].value != before


def test_all_weights_zero_keeps_the_card_with_a_null_total(app):
    app.session_state[SELECTED] = 100
    for dim in ("terrain", "temperature", "water_ice", "biology"):
        app.sidebar.slider(key=f"w_{dim}").set_value(0.0)
    app.run()
    assert not app.exception
    assert any("Subí al menos un peso" in w.value for w in app.warning)
    assert app.metric[0].value == "sin dato"
    assert "Límites que ningún sitio terrestre replica" in _text(app)


def test_a_known_analog_cell_shows_its_label(app):
    app.session_state[SELECTED] = 105
    app.run()
    assert "Análogo conocido: Atacama" in _text(app)


def test_a_cell_that_is_not_eligible_still_has_a_card(app):
    app.session_state[SELECTED] = 103
    app.run()
    assert not app.exception and app.metric[0].value == "sin dato"
    assert "Datos insuficientes" in _text(app)


def test_no_selection_shows_the_hint(app):
    assert any("Elegí una fila del ranking" in i.value for i in app.info)
    assert not app.metric
