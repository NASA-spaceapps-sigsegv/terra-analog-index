"""App entry point (design 10). It only reads data/processed/.

To try it with the test data:
    TAI_DATA_DIR=tests/fixtures streamlit run streamlit_app.py
"""

import os
from contextlib import contextmanager
from pathlib import Path

import streamlit as st

from tai import services
from tai.constants import CSV_TOP_N
from tai.errors import (
    CellNotFoundError,
    DataNotAvailableError,
    TargetNotFoundError,
    TaiError,
    ZeroWeightsError,
)
from tai.io import DataBundle, data_signature, load_bundle
from ui import card_view, caves_view, map_view, method_view, ranking_view
from ui.ranking_view import SCROLL_KEY, SELECTED_KEY
from ui.sidebar import SidebarState, render_sidebar

ICON_PATH = Path(__file__).parent / "docs" / "img" / "logo" / "favicon.png"
st.set_page_config(
    page_title="Terra Analog Index", page_icon=str(ICON_PATH) if ICON_PATH.is_file() else "🛰️", layout="wide"
)

DATA_DIR = Path(os.environ.get("TAI_DATA_DIR") or Path(__file__).parent / "data" / "processed")


@st.cache_resource(show_spinner="Loading data…")
def get_bundle(path: str, signature: tuple) -> DataBundle:
    """Loaded once per process. `signature` changes if a file is deleted or touched."""
    return load_bundle(path)


@contextmanager
def handle_tai_errors(fatal: bool = False):
    """The only place where the app catches TaiError (design 9.3).

    fatal=True: what follows depends on what failed, so the page stops."""
    try:
        yield
    except DataNotAvailableError as err:
        st.error(f"**The data cannot be loaded.** {err.detail}")
        st.stop()
    except ZeroWeightsError:
        st.warning("Raise at least one weight.")
    except TargetNotFoundError as err:
        st.error(err.detail)
        st.session_state.pop("target_id", None)  # the next run goes back to the first target
        if fatal:
            st.stop()
    except CellNotFoundError as err:
        st.warning(err.detail)
        st.session_state[SELECTED_KEY] = None
    except TaiError as err:  # InvalidWeightsError and future ones: programming error
        st.error(f"{type(err).__name__}: {err.detail}")
        if fatal:
            st.stop()
    else:
        return
    if fatal:
        st.stop()


CARD_HINT = "Pick a row in the ranking to see its card."
CARD_ANCHOR = "card"


def explore_tab(bundle: DataBundle, state: SidebarState) -> None:
    """Map on top; with the layer on, the caves table; then the ranking and the card, all full width.

    Each part catches its own errors: with every weight at 0 the ranking warns and the selected
    card is still shown, with a null total."""
    with handle_tai_errors():
        layer = services.get_map_layer(bundle, state.target_id, state.weights)
        caves = services.get_caves(bundle) if state.show_caves else ()
        map_view.render_map(layer, state.projection, st.session_state.get(SELECTED_KEY), caves)
    if state.show_caves:
        with handle_tai_errors():
            table = services.get_caves_table(bundle, state.target_id, state.weights, hide_known=state.hide_known)
            caves_view.render_caves(table, state.target_id, st.session_state.get(SELECTED_KEY))
    st.subheader("Best cells")
    with handle_tai_errors():
        ranking = services.get_ranking(bundle, state.target_id, state.weights, hide_known=state.hide_known)
        csv_text = services.export_ranking_csv(bundle, state.target_id, state.weights, hide_known=state.hide_known)

        def csv_long() -> str:  # built only when its button is clicked
            return services.export_ranking_csv(bundle, state.target_id, state.weights, hide_known=state.hide_known,
                                               limit=CSV_TOP_N)

        ranking_view.render_ranking(ranking, st.session_state.get(SELECTED_KEY), csv_text, csv_long)
    st.subheader("Card", anchor=CARD_ANCHOR)
    with handle_tai_errors():
        selected = st.session_state.get(SELECTED_KEY)
        if selected is None:
            st.info(CARD_HINT)
        else:
            card_view.render_card(services.get_site_card(bundle, selected, state.target_id, state.weights))
    if st.session_state.pop(SCROLL_KEY, False):
        scroll_to(CARD_ANCHOR)


def scroll_to(anchor: str) -> None:
    """Scroll the page to the heading with that anchor. Waits a moment so the card is already drawn."""
    st.html(
        f"<script>setTimeout(() => document.getElementById({anchor!r})"
        "?.scrollIntoView({behavior: 'smooth', block: 'start'}), 150);</script>",
        unsafe_allow_javascript=True,
    )


def method_tab(bundle: DataBundle) -> None:
    """Method tab (design 10.7): texts from content/method.md and tables from the pipeline files."""
    with handle_tai_errors():
        targets = [services.get_target(bundle, t.target_id) for t in services.list_targets(bundle)]
        method_view.render_method(
            services.get_method_text(), targets, services.get_validation(bundle), services.get_manifest(bundle)
        )


def main() -> None:
    with handle_tai_errors(fatal=True):
        bundle = get_bundle(str(DATA_DIR), data_signature(DATA_DIR))
        state = render_sidebar(services.list_targets(bundle))

    tab_explore, tab_method = st.tabs(["Explore", "Method"])
    with tab_explore:
        explore_tab(bundle, state)
    with tab_method:
        method_tab(bundle)


main()
