"""Capa de cuevas y tubos de lava (TAI-53): config, paso 08, carga, mapa y casilla de la barra lateral."""

import importlib.util
from pathlib import Path

import pandas as pd
import pytest
from pydantic import ValidationError
from streamlit.testing.v1 import AppTest

from tai import io, models, services
from tai.constants import DEFAULT_WEIGHTS
from tai.errors import DataNotAvailableError
from tai.schemas import CAVES_COLUMNS
from ui import map_view

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
    assert list(trace.x) == [-13.44, 167.16] and list(trace.y) == [29.16, -77.52]
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
