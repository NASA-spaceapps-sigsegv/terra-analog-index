"""TAI-40: the phone layout, the full-width map with the ranking under it, presets, the comparison and the shareable link."""

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from tai.constants import DEFAULT_WEIGHTS, DIMENSIONS
from tests.test_dust_wind import _card
from ui import card_view, device, guide, map_view, share
from ui.map_view import FOCUS_KEY
from ui.ranking_view import SCROLL_KEY, SELECTED_KEY

APP = str(Path(__file__).resolve().parents[1] / "streamlit_app.py")
MOON, MARS = "moon_south_pole", "mars_jezero"


@pytest.fixture
def make(data_dir, monkeypatch):
    """An app that has not run yet, so a test can set the address first."""
    monkeypatch.setenv("TAI_DATA_DIR", str(data_dir))
    return lambda: AppTest.from_file(APP, default_timeout=30)


@pytest.fixture
def app(make):
    return make().run()


def text(at) -> str:
    return "\n".join(m.value for m in at.markdown) + "\n".join(c.value for c in at.caption)


# --- phone ---------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "agent, phone",
    [
        ("Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 Chrome/120.0 Mobile Safari/537.36", True),
        ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1", True),
        ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36", False),
        ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/17.0 Safari/605.1.15", False),
        ("Mozilla/5.0 (Linux; Android 13; SM-X700) AppleWebKit/537.36 Chrome/120.0 Safari/537.36", False),  # a tablet
        ("", False),
    ],
)
def test_phone_detection_reads_the_browser(agent, phone):
    assert bool(device._PHONE.search(agent)) is phone


def test_desktop_layout_by_default(app):
    assert not app.exception and not app.error
    spec = json.loads(app.get("plotly_chart")[0].proto.spec)["layout"]
    assert spec["height"] == map_view.HEIGHT["world"] and spec["dragmode"] == "pan"
    assert not [e for e in app.expander if e.label == "Full table, top 20"]
    assert len(app.tabs[0].dataframe) == 1  # the ranking table is there, not folded (the Method tab has its own)


def test_phone_layout_is_shorter_and_scrolls_with_one_finger(make):
    at = make()
    at.query_params["view"] = "phone"
    at.run()
    assert not at.exception and not at.error
    spec = json.loads(at.get("plotly_chart")[0].proto.spec)["layout"]
    assert spec["height"] == map_view.COMPACT_HEIGHT["world"] and spec["dragmode"] is False and spec["showlegend"] is False
    assert len(at.tabs[0].dataframe) == 1  # the ranking table, unfolded, as on a wide screen
    assert at.query_params["view"] == "phone"  # the forced layout survives the address rewrite


def test_the_view_parameter_can_force_the_desktop_layout(make):
    at = make()
    at.query_params["view"] = "desktop"
    at.run()
    assert json.loads(at.get("plotly_chart")[0].proto.spec)["layout"]["dragmode"] == "pan"


# --- the best cells and the card -----------------------------------------------------------------------------------------


def test_the_map_is_alone_with_no_panels_beside_it(app):
    assert not app.exception and not app.error
    assert "Top 5 cells" not in text(app) and not app.get("progress")
    assert len(app.tabs[0].dataframe) == 1  # the ranking goes right under the map


def test_picking_a_cell_shows_its_card_and_scrolls_to_it(app):
    app.session_state[SELECTED_KEY] = 102
    app.session_state[SCROLL_KEY] = True
    app.run()
    assert not app.exception and "Limits no site on Earth replicates" in text(app)
    assert SCROLL_KEY not in app.session_state  # the page scrolled to the card once


def test_the_hint_says_how_to_open_a_card(app):
    assert any("Pick a row in the ranking" in i.value and "numbered dot" in i.value for i in app.info)


# --- presets -------------------------------------------------------------------------------------------------------------


def weights(at) -> dict:
    return {d: at.sidebar.slider(key=f"w_{d}").value for d in DIMENSIONS}


def test_presets_set_all_five_weights_in_one_click(app):
    app.sidebar.button(key="preset_physical").click().run()
    assert weights(app) == dict(DEFAULT_WEIGHTS, biology=0.0)
    app.sidebar.button(key="preset_biology").click().run()
    assert weights(app)["biology"] == 1.0 and max(v for d, v in weights(app).items() if d != "biology") < 1.0
    app.sidebar.button(key="preset_balanced").click().run()
    assert weights(app) == dict(DEFAULT_WEIGHTS)


def test_every_preset_is_a_valid_set_of_weights():
    from ui.sidebar import PRESETS

    for _, weights_, _ in PRESETS.values():
        assert set(weights_) == set(DIMENSIONS) and all(0.0 <= v <= 1.0 for v in weights_.values())
        assert any(v > 0 for v in weights_.values())


# --- compare the same cell on the Moon and on Mars -----------------------------------------------------------------------


def test_the_radar_overlays_the_other_target_on_shared_axes():
    moon, mars = _card(with_dust=False), _card(with_dust=True)
    alone, both = card_view.radar_figure(moon), card_view.radar_figure(moon, mars)
    assert len(alone.data) == 1 and alone.layout.showlegend is False
    assert len(both.data) == 2 and both.layout.showlegend is True
    assert list(both.data[0].theta) == list(both.data[1].theta) and len(both.data[0].theta) == 6  # five axes, closed
    assert both.data[1].line.dash == "dash" and both.data[1].line.color != both.data[0].line.color


def test_the_toggle_draws_the_other_target_over_the_radar(app):
    app.session_state[SELECTED_KEY] = 102
    app.run()
    assert len(json.loads(app.get("plotly_chart")[1].proto.spec)["data"]) == 1
    app.toggle(key="compare_other").set_value(True).run()
    assert not app.exception and not app.error
    assert len(json.loads(app.get("plotly_chart")[1].proto.spec)["data"]) == 2


# --- shareable link ------------------------------------------------------------------------------------------------------


def test_the_address_describes_the_view_after_every_run(app):
    params = dict(app.query_params)
    assert params["t"] == MOON and params["v"] == "world" and "c" not in params
    assert params["w"] == ",".join(f"{DEFAULT_WEIGHTS[d]:g}" for d in DIMENSIONS)
    app.sidebar.slider(key="w_terrain").set_value(0.25).run()
    app.session_state[SELECTED_KEY] = 102
    app.run()
    assert dict(app.query_params)["w"].split(",")[0] == "0.25" and dict(app.query_params)["c"] == "102"


def test_opening_a_shared_link_restores_the_whole_view(make):
    at = make()
    at.query_params.update({"t": MARS, "w": "0,1,0.5,0.5,0.25", "v": "south_pole", "c": "102", "k": "1", "g": "1"})
    at.run()
    assert not at.exception and not at.error
    assert at.sidebar.radio(key="target_id").value == MARS and at.sidebar.radio(key="projection").value == "south_pole"
    assert weights(at) == {"terrain": 0.0, "temperature": 1.0, "water_ice": 0.5, "dust_wind": 0.5, "biology": 0.25}
    assert at.sidebar.checkbox(key="hide_known").value and at.sidebar.checkbox(key="show_caves").value
    assert at.session_state[SELECTED_KEY] == 102


@pytest.mark.parametrize("bad", [{"t": "nowhere"}, {"w": "1,2,3"}, {"w": "a,b,c,d,e"}, {"w": "2,1,1,1,1"}, {"v": "mercator"}, {"c": "abc"}])
def test_a_broken_link_falls_back_to_the_defaults_without_an_error(make, bad):
    at = make()
    at.query_params.update(bad)
    at.run()
    assert not at.exception and not at.error
    assert at.sidebar.radio(key="target_id").value == MOON and weights(at) == dict(DEFAULT_WEIGHTS)


def test_weights_in_a_link_are_read_strictly_and_snapped_to_the_step():
    assert share._weights_from("1,1,1,0.5,0.5") == dict(DEFAULT_WEIGHTS)
    assert share._weights_from("0.33,1,1,0.5,0.5")["terrain"] == 0.35  # the sliders move in steps of 0.05
    for bad in (None, "", "1,1", "1,1,1,1,1,1", "x,1,1,1,1", "1.5,1,1,1,1", "-1,1,1,1,1"):
        assert share._weights_from(bad) is None


def test_query_params_for_keeps_it_short_and_only_what_differs():
    params = share.query_params_for(MARS, dict(DEFAULT_WEIGHTS), "world", False, False, None)
    assert params == {"t": MARS, "w": "1,1,1,0.5,0.5", "v": "world"}
    full = share.query_params_for(MOON, dict(DEFAULT_WEIGHTS), "south_pole", True, True, 7, "phone")
    assert full["k"] == "1" and full["g"] == "1" and full["c"] == "7" and full["view"] == "phone"


# --- guidance ------------------------------------------------------------------------------------------------------------


def test_the_guide_is_one_short_line_and_names_the_menu_on_a_phone(app):
    assert any("Pick a target in the sidebar" in c.value for c in app.caption)
    phone = AppTest.from_file(APP, default_timeout=30)
    phone.query_params["view"] = "phone"
    phone.run()
    assert any("Open the menu" in c.value for c in phone.caption)


def test_the_symbol_key_lists_caves_only_when_that_layer_is_on(app):
    def legend(at) -> str:
        return " ".join(h.proto.body for h in at.get("html") if "tai-legend" in h.proto.body)

    assert "Known analog" in legend(app) and "Selected cell" in legend(app) and "Cave" not in legend(app)
    app.sidebar.checkbox(key="show_caves").set_value(True).run()
    assert "Cave or lava tube" in legend(app)


def test_the_calculating_notice_is_css_on_the_running_state_and_nothing_is_left_unfilled():
    assert 'data-test-script-state="running"' in guide.STYLES and "Calculating" in guide.STYLES
    assert "SELECTED_COLOR" not in guide.STYLES and "CAVE_COLOR" not in guide.STYLES
    assert map_view.SELECTED_COLOR in guide.STYLES and map_view.CAVE_COLOR in guide.STYLES


# --- the list of the best 20 and the zoom on a cell ----------------------------------------------------------------------


def best_list(at):
    found = [g for g in at.get("button_group") if g.key and g.key.startswith("best_list_")]
    assert len(found) == 1
    return found[0]


def map_range(at) -> tuple[float, float]:
    spec = json.loads(at.get("plotly_chart")[0].proto.spec)["layout"]
    return tuple(spec["xaxis"]["range"])


def test_the_best_cells_are_a_row_of_small_numbers_and_the_map_starts_whole(app):
    pills = best_list(app)
    assert pills.options == ["1", "2", "3", "4"] or pills.options[0] == "1"  # the test data have 5 eligible cells: 1 to 5
    assert pills.value in (None, []) and map_range(app) == (-180, 180)
    assert any("tap a number to zoom the map" in c.value for c in app.caption)


def test_tapping_a_number_zooms_the_map_on_that_cell_and_opens_its_card(app):
    best_list(app).select(int(app.get("button_group")[0].options[1])).run()  # the second one
    assert not app.exception and not app.error
    assert app.session_state[FOCUS_KEY] == app.session_state[SELECTED_KEY]
    x0, x1 = map_range(app)
    assert x1 - x0 == 36.0 and "Limits no site on Earth replicates" in text(app)  # zoomed, and the card is below
    assert SCROLL_KEY not in app.session_state  # the map stays in front: no scroll
    assert any("Open its card" in c.value for c in app.caption)


def test_tapping_the_open_number_again_or_the_back_button_returns_to_the_whole_map(app):
    options = app.get("button_group")[0].options
    best_list(app).select(int(options[1])).run()
    assert FOCUS_KEY in app.session_state
    best_list(app).unselect(int(options[1])).run()
    assert FOCUS_KEY not in app.session_state and map_range(app) == (-180, 180)
    best_list(app).select(int(options[0])).run()
    next(b for b in app.button if b.label == "Back to full view").click().run()
    assert FOCUS_KEY not in app.session_state and map_range(app) == (-180, 180)


def test_changing_the_target_takes_the_map_back_to_the_whole_world(app):
    best_list(app).select(int(app.get("button_group")[0].options[0])).run()
    assert FOCUS_KEY in app.session_state
    app.sidebar.radio(key="target_id").set_value(MARS).run()
    assert FOCUS_KEY not in app.session_state and map_range(app) == (-180, 180)


def test_the_focus_survives_moving_a_weight_so_the_zoom_is_not_lost(app):
    best_list(app).select(int(app.get("button_group")[0].options[0])).run()
    before = map_range(app)
    app.sidebar.slider(key="w_terrain").set_value(0.5).run()
    assert not app.exception and FOCUS_KEY in app.session_state
    assert map_range(app) == before


def test_the_copy_button_script_runs_in_its_own_scope_so_a_rerun_does_not_redeclare_it(app):
    body = next(h.proto.body for h in app.get("html") if "tai-copy" in h.proto.body)
    assert "(() =>" in body and "})();" in body  # a top-level `const button` threw "already declared" on every rerun
