"""Capa de cuevas y tubos de lava (TAI-53): config, paso 08, carga, mapa y casilla de la barra lateral."""

import importlib.util
from pathlib import Path

import pandas as pd
import pytest
from pydantic import ValidationError
from streamlit.testing.v1 import AppTest

from tai import caves as tai_caves
from tai import io, models, services
from tai.constants import DEFAULT_WEIGHTS
from tai.errors import DataNotAvailableError, TargetNotFoundError
from tai.schemas import CAVES_COLUMNS
from ui import card_view, caves_view, map_view

ROOT = Path(__file__).resolve().parents[1]
APP = str(ROOT / "streamlit_app.py")
CONFIG_CAVES = ROOT / "config" / "caves.csv"

spec = importlib.util.spec_from_file_location("step08caves", ROOT / "pipeline" / "08_similarity.py")
step08 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(step08)


@pytest.fixture
def bundle(data_dir):
    return io.load_bundle(data_dir)


def _cave(**kw) -> dict:
    return {"cave_id": "c", "name": "Cueva", "lat": 10.0, "lon": 20.0, "kind": "lava_tube",
            "relevance": "Marte", "source": "x"} | kw


# --- config/caves.csv ---------------------------------------------------------------


def test_the_config_file_is_valid_and_every_site_has_a_source():
    caves = step08.load_caves(CONFIG_CAVES)
    assert len(caves) >= 8
    assert len({c.cave_id for c in caves}) == len(caves)
    assert all(c.source.strip() and c.relevance.strip() for c in caves)
    assert {c.kind for c in caves} <= set(map_view.CAVE_KINDS)


@pytest.mark.parametrize("bad", [{"lat": 91.0}, {"lon": -181.0}, {"kind": "karst"}, {"cave_id": "Con Espacios"},
                                 {"source": ""}])
def test_the_model_rejects_bad_rows(bad):
    with pytest.raises(ValidationError):
        models.Cave.model_validate(_cave(**bad))


def test_load_caves_rejects_repeated_ids_and_wrong_columns(tmp_path):
    path = tmp_path / "caves.csv"
    pd.DataFrame([_cave(), _cave()], columns=list(CAVES_COLUMNS)).to_csv(path, index=False)
    with pytest.raises(step08.OutputValidationError, match="repetidos"):
        step08.load_caves(path)
    pd.DataFrame([_cave()]).drop(columns="source").to_csv(path, index=False)
    with pytest.raises(step08.OutputValidationError, match="columnas"):
        step08.load_caves(path)


# --- Carga -------------------------------------------------------------------------


def test_the_bundle_carries_the_caves(bundle):
    assert [c.cave_id for c in services.get_caves(bundle)] == ["cueva_norte", "cueva_sur"]


def test_a_missing_caves_file_names_step_08(data_dir):
    (data_dir / "caves.csv").unlink()
    with pytest.raises(DataNotAvailableError, match="caves.csv.*08_similarity"):
        io.load_bundle(data_dir)


# --- Mapa ------------------------------------------------------------------------------


def _caves_traces(fig):
    return [t for t in fig.data if t.name == map_view.CAVES_NAME]


def _figure(bundle, projection, caves):
    layer = services.get_map_layer(bundle, "mars_jezero", DEFAULT_WEIGHTS)
    return map_view.build_figure(layer, projection, None, caves)


def test_without_caves_the_map_has_no_cave_layer(bundle):
    assert _caves_traces(_figure(bundle, "world", ())) == []


def test_world_shows_every_cave_with_its_name_type_and_source(bundle):
    (trace,) = _caves_traces(_figure(bundle, "world", services.get_caves(bundle)))
    assert list(trace.x) == [-13.44, -77.5] and list(trace.y) == [29.16, -89.5]
    assert "Cueva del norte" in trace.hovertext[0] and "Tubo de lava" in trace.hovertext[0]
    assert "Cueva de hielo" in trace.hovertext[1] and "Fuente: prueba" in trace.hovertext[1]


@pytest.mark.parametrize("projection,expected", [("south_pole", "Cueva del sur"), ("north_pole", "Cueva del norte")])
def test_each_pole_shows_only_its_hemisphere(bundle, projection, expected):
    (trace,) = _caves_traces(_figure(bundle, projection, services.get_caves(bundle)))
    assert len(trace.x) == 1 and expected in trace.hovertext[0]


def test_long_hover_text_is_split_into_lines():
    cave = models.Cave.model_validate(_cave(relevance="palabra " * 30))
    lines = map_view._cave_hover(cave).split("<br>")
    assert all(len(line) <= map_view.HOVER_WRAP + 10 for line in lines[2:])


# --- En la app ----------------------------------------------------------------------


def test_the_checkbox_starts_off_and_turns_the_layer_on(data_dir, monkeypatch):
    monkeypatch.setenv("TAI_DATA_DIR", str(data_dir))
    at = AppTest.from_file(APP, default_timeout=30).run()
    box = at.sidebar.checkbox(key="show_caves")
    assert box.value is False and box.label == "Mostrar cuevas y tubos de lava"
    assert map_view.CAVES_NAME not in at.get("plotly_chart")[0].proto.spec
    box.check().run()
    assert not at.exception
    assert map_view.CAVES_NAME in at.get("plotly_chart")[0].proto.spec


# --- Tabla de cuevas y ficha (puesto de su celda, sin cambiar puntajes) -------------------------------


def test_a_cave_belongs_to_the_cell_that_contains_it_or_to_none(bundle):
    north, south = services.get_caves(bundle)
    assert tai_caves.cell_of(south, bundle.grid.index) == 102
    assert tai_caves.cell_of(north, bundle.grid.index) is None  # su celda no está en la grilla


def test_caves_table_gives_the_rank_and_total_of_each_cave_cell(bundle):
    table = services.get_caves_table(bundle, "mars_jezero", DEFAULT_WEIGHTS)
    assert tuple(table.columns) == services.CAVES_TABLE_COLUMNS
    ranking = {i.cell_id: i for i in services.get_ranking(bundle, "mars_jezero", DEFAULT_WEIGHTS).items}
    first, second = table.to_dict(orient="records")
    assert first["Cueva"] == "Cueva del sur" and first["cell_id"] == 102 and first["Tipo"] == "Cueva de hielo"
    assert first["Puesto"] == ranking[102].rank and first["Total"] == pytest.approx(ranking[102].total)
    assert second["Cueva"] == "Cueva del norte" and pd.isna(second["Puesto"]) and pd.isna(second["Total"])
    assert tai_caves.NO_CELL in second["Por qué interesa"]


def test_caves_table_follows_the_known_analog_filter_and_survives_zero_weights(bundle):
    weights = DEFAULT_WEIGHTS | {"terrain": 0.0}  # con terreno en 0 entra la celda 105, análogo conocido
    shown = services.get_caves_table(bundle, "mars_jezero", weights)["Puesto"].iloc[0]
    hidden = services.get_caves_table(bundle, "mars_jezero", weights, hide_known=True)["Puesto"].iloc[0]
    assert hidden <= shown
    zero = services.get_caves_table(bundle, "mars_jezero", {k: 0.0 for k in DEFAULT_WEIGHTS})
    assert zero["Puesto"].isna().all() and len(zero) == 2


def test_caves_table_unknown_target_raises(bundle):
    with pytest.raises(TargetNotFoundError):
        services.get_caves_table(bundle, "mars_gale", DEFAULT_WEIGHTS)


def test_the_card_lists_the_caves_of_its_cell_and_keeps_the_score(bundle):
    card = services.get_site_card(bundle, 102, "mars_jezero", DEFAULT_WEIGHTS, cards_dir=None)
    assert [(c.name, c.kind_label) for c in card.caves] == [("Cueva del sur", "Cueva de hielo")]
    ranking = {i.cell_id: i for i in services.get_ranking(bundle, "mars_jezero", DEFAULT_WEIGHTS).items}
    assert card.scores.total == pytest.approx(ranking[102].total, abs=1e-3)
    assert services.get_site_card(bundle, 104, "mars_jezero", DEFAULT_WEIGHTS, cards_dir=None).caves == []


def test_picking_a_cave_row_opens_its_cell_and_a_row_without_cell_does_nothing(monkeypatch):
    state = {"k": {"selection": {"rows": [0], "columns": [], "cells": []}}, caves_view.SELECTED_KEY: 7}
    monkeypatch.setattr(caves_view.st, "session_state", state)
    caves_view._on_select("k", (102, None))
    assert state[caves_view.SELECTED_KEY] == 102 and state[caves_view.SCROLL_KEY] is True
    state["k"]["selection"]["rows"] = [1]
    state[caves_view.SCROLL_KEY] = False
    caves_view._on_select("k", (102, None))
    assert state[caves_view.SELECTED_KEY] == 102 and state[caves_view.SCROLL_KEY] is False


def test_selected_rows_never_marks_a_cave_without_cell():
    assert caves_view.selected_rows((102, None), None) == []
    assert caves_view.selected_rows((102, None), 102) == [0]
    assert caves_view.selected_rows((102, None), 5) == []


def test_the_table_shows_only_with_the_layer_on_and_the_card_shows_the_cave(data_dir, monkeypatch):
    monkeypatch.setenv("TAI_DATA_DIR", str(data_dir))
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.sidebar.radio(key="target_id").set_value("mars_jezero").run()
    assert caves_view.HEADING not in [s.value for s in at.subheader]
    at.sidebar.checkbox(key="show_caves").check().run()
    assert not at.exception
    assert caves_view.HEADING in [s.value for s in at.subheader]
    keys = [d.key for d in at.dataframe if d.key]
    assert keys[0].startswith("ranking_caves_mars_jezero") and keys[1].startswith("ranking_mars_jezero")
    at.session_state[caves_view.SELECTED_KEY] = 102
    at.run()
    assert any(card_view.CAVES_HEADING in m.value for m in at.markdown)
    assert any("Cueva del sur" in m.value for m in at.markdown)
