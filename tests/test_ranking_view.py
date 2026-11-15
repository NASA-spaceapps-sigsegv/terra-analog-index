"""TAI-31: ranking con selección de fila (design 10.4 y 10.5)."""

import json
from pathlib import Path

import numpy as np
import pytest
from streamlit.testing.v1 import AppTest

from tai import services
from tai.io import load_bundle
from ui import ranking_view as rv

APP = str(Path(__file__).resolve().parents[1] / "streamlit_app.py")
WEIGHTS = {"terrain": 1.0, "temperature": 1.0, "water_ice": 1.0, "biology": 0.5}


@pytest.fixture
def bundle(data_dir):
    return load_bundle(data_dir)


@pytest.fixture
def app(data_dir, monkeypatch):
    monkeypatch.setenv("TAI_DATA_DIR", str(data_dir))
    return AppTest.from_file(APP, default_timeout=30).run()


# --- Funciones puras ------------------------------------------------------------


def test_table_has_the_design_columns_in_order(bundle):
    df = rv.ranking_table(services.get_ranking(bundle, "mars_jezero", WEIGHTS))
    assert list(df.columns) == list(rv.COLUMNS.values())
    assert df["Puesto"].tolist() == list(range(1, len(df) + 1))
    assert df["Total"].is_monotonic_decreasing


def test_null_scores_stay_null_not_zero(bundle):
    ranking = services.get_ranking(bundle, "mars_jezero", WEIGHTS)
    df = rv.ranking_table(ranking)
    nulls = [i for i, item in enumerate(ranking.items) if item.s_temperature is None]
    assert nulls, "los datos de prueba tienen una celda sin temperatura (104)"
    assert all(np.isnan(df.loc[i, "Temperatura"]) for i in nulls)


def test_empty_ranking_gives_an_empty_table_with_the_columns(bundle):
    ranking = services.get_ranking(bundle, "mars_jezero", WEIGHTS).model_copy(update={"items": []})
    assert list(rv.ranking_table(ranking).columns) == list(rv.COLUMNS.values())


def test_key_changes_with_the_order_and_the_target_only():
    assert rv.table_key("a", [1, 2]) == rv.table_key("a", [1, 2])
    assert rv.table_key("a", [1, 2]) != rv.table_key("a", [2, 1])
    assert rv.table_key("a", [1, 2]) != rv.table_key("b", [1, 2])


def test_default_rows_marks_the_selected_cell_only_if_present():
    assert rv.default_rows([7, 8, 9], 9) == [2]
    assert rv.default_rows([7, 8, 9], 5) == []
    assert rv.default_rows([7, 8, 9], None) == []


def test_cell_from_rows():
    assert rv.cell_from_rows([1], (7, 8, 9)) == 8
    assert rv.cell_from_rows([], (7, 8, 9)) is None
    assert rv.cell_from_rows([5], (7, 8, 9)) is None


def test_callback_saves_and_clears_the_cell(monkeypatch):
    state = {"k": {"selection": {"rows": [2], "columns": [], "cells": []}}}
    monkeypatch.setattr(rv.st, "session_state", state)
    rv._on_select("k", (7, 8, 9))
    assert state[rv.SELECTED_KEY] == 9
    state["k"] = {"selection": {"rows": [], "columns": [], "cells": []}}
    rv._on_select("k", (7, 8, 9))
    assert state[rv.SELECTED_KEY] is None


# --- En la app ---------------------------------------------------------------------


def _selected(app):
    return app.session_state[rv.SELECTED_KEY]


def test_table_shows_scores_as_progress_bars_and_nulls_as_sin_dato(app):
    assert not app.exception and not app.error
    proto = app.dataframe[0].proto
    config = json.loads(proto.columns)
    assert all(config[c]["type_config"]["type"] == "progress" for c in rv.SCORE_COLUMNS)
    assert proto.placeholder == "sin dato"


def test_no_cell_selected_shows_the_hint(app):
    assert _selected(app) is None
    assert any("Elegí una fila del ranking" in i.value for i in app.info)


def test_selection_survives_moving_a_slider(app):
    app.session_state[rv.SELECTED_KEY] = 102
    app.run()
    assert any("Celda" in m.value for m in app.markdown)
    app.sidebar.slider(key="w_terrain").set_value(0.0).run()
    assert not app.exception
    assert _selected(app) == 102


def test_selection_survives_when_the_cell_leaves_the_ranking(app):
    app.session_state[rv.SELECTED_KEY] = 103  # no elegible: nunca está en el ranking
    app.sidebar.slider(key="w_biology").set_value(0.0).run()
    assert _selected(app) == 103
    assert not app.exception and not app.tabs[0].warning  # Método puede avisar de una validación insuficiente


def test_changing_the_target_clears_the_selection(app):
    app.session_state[rv.SELECTED_KEY] = 102
    app.run()
    app.sidebar.radio(key="target_id").set_value("mars_jezero").run()
    assert _selected(app) is None
    assert any("Elegí una fila del ranking" in i.value for i in app.info)


def test_hide_known_removes_every_known_analog(app):
    app.sidebar.slider(key="w_terrain").set_value(0.0).run()  # con terreno en 0 entra 105
    assert app.dataframe[0].value["Análogo conocido"].notna().any()
    app.sidebar.checkbox(key="hide_known").check().run()
    assert app.dataframe[0].value["Análogo conocido"].isna().all()


def test_the_widget_marks_the_row_of_the_selected_cell(app):
    app.session_state[rv.SELECTED_KEY] = 100
    app.run()
    df = app.dataframe[0]
    lon = float(df.value["Lon"].iloc[json.loads(df.proto.selection_default)["selection"]["rows"][0]])
    assert lon == pytest.approx(-79.5)  # centro de la celda 100

    app.sidebar.slider(key="w_terrain").set_value(0.0).run()  # orden nuevo: widget nuevo
    df = app.dataframe[0]
    rows = json.loads(df.proto.selection_default)["selection"]["rows"]
    assert df.value["Lon"].iloc[rows[0]] == pytest.approx(-79.5)
