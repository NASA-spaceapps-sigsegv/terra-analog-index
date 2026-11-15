"""App entry point (design 10). It only reads data/processed/.

To try it with the test data:
    TAI_DATA_DIR=tests/fixtures streamlit run streamlit_app.py
"""

import os
from contextlib import contextmanager, nullcontext
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
from ui import card_view, caves_view, device, guide, map_view, method_view, ranking_view, share, top_cards
from ui.ranking_view import SCROLL_KEY, SELECTED_KEY, select_cell
from ui.sidebar import SidebarState, render_sidebar

ICON_PATH = Path(__file__).parent / "docs" / "img" / "logo" / "favicon.png"
st.set_page_config(
    page_title="Terra Analog Index", page_icon=str(ICON_PATH) if ICON_PATH.is_file() else "🛰️", layout="wide"
)

DATA_DIR = Path(os.environ.get("TAI_DATA_DIR") or Path(__file__).parent / "data" / "processed")


@st.cache_resource(show_spinner="Loading data… the first visit after a pause can take up to 30 s on the free server")
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


CARD_HINT = "Pick a row in the ranking to see its card. You can also tap a numbered dot on the map or a top card."
CARD_ANCHOR = "card"
VIEW_REV_KEY = "map_view_rev"  # changing it resets the map's zoom
COMPARE_KEY = "compare_other"
RANKING_HEADING = "Best cells"


def _back_to_full_view() -> None:
    st.session_state[VIEW_REV_KEY] = st.session_state.get(VIEW_REV_KEY, 0) + 1


def explore_tab(bundle: DataBundle, state: SidebarState, compact: bool) -> None:
    """Guide on top; the map beside the best cells (under it on a phone); then the table, the caves and the card.

    Each part catches its own errors: with every weight at 0 the ranking warns and the selected
    card is still shown, with a null total. The ranking and the card are computed once and shared by the parts that draw them."""
    guide.render_guide(compact)
    map_col, side_col = st.columns([3, 2], gap="medium")

    ranking = card = None
    with side_col:
        with handle_tai_errors():
            ranking = services.get_ranking(bundle, state.target_id, state.weights, hide_known=state.hide_known)
        selected = st.session_state.get(SELECTED_KEY)
        with handle_tai_errors():
            if selected is not None:
                card = services.get_site_card(bundle, selected, state.target_id, state.weights)
        selected = st.session_state.get(SELECTED_KEY)  # a cell that does not exist clears it
        if card is not None:
            card_view.render_summary(card, CARD_ANCHOR)
        if ranking is not None and ranking.items:
            top_cards.render_top_cards(ranking, selected, select_cell, compact)

    with map_col:
        with handle_tai_errors():
            layer = services.get_map_layer(bundle, state.target_id, state.weights)
            caves = services.get_caves(bundle) if state.show_caves else ()
            top_cells = [item.cell_id for item in ranking.items] if ranking is not None else []
            map_view.render_map(
                layer, state.projection, selected, caves, top_cells, compact,
                st.session_state.get(VIEW_REV_KEY, 0), on_pick=select_cell,
            )
        with st.container(horizontal=True):
            st.button("Back to full view", on_click=_back_to_full_view, icon=":material/zoom_out_map:",
                      help="Zoom out to the whole map")
            share.render_copy_button()
        guide.render_legend(state.show_caves)

    if state.show_caves:
        with handle_tai_errors():
            table = services.get_caves_table(bundle, state.target_id, state.weights, hide_known=state.hide_known)
            caves_view.render_caves(table, state.target_id, selected)
    st.subheader(RANKING_HEADING)
    if ranking is not None:
        def csv_short() -> str:  # built only when its button is clicked
            return services.export_ranking_csv(bundle, state.target_id, state.weights, hide_known=state.hide_known)

        def csv_long() -> str:
            return services.export_ranking_csv(bundle, state.target_id, state.weights, hide_known=state.hide_known,
                                               limit=CSV_TOP_N)

        # On a phone the wide table is folded away: the top cards above already give the best five.
        with st.expander("Full table, top 20", expanded=False) if compact else nullcontext():
            ranking_view.render_ranking(ranking, selected, csv_short, csv_long)
    else:
        st.caption("The ranking needs at least one weight above 0.")
    st.subheader("Card", anchor=CARD_ANCHOR)
    if card is None:
        st.info(CARD_HINT)
    else:
        render_card_with_comparison(bundle, state, selected, card)
    if st.session_state.pop(SCROLL_KEY, False):
        scroll_to(CARD_ANCHOR)


def render_card_with_comparison(bundle: DataBundle, state: SidebarState, selected: int, card) -> None:
    """The card, with a switch to lay the same cell's radar for the other target over it (Moon against Mars)."""
    other_card = None
    others = [t for t in services.list_targets(bundle) if t.target_id != state.target_id]
    if others and st.toggle(f"Compare with {others[0].label}", key=COMPARE_KEY,
                            help="Draws this cell's scores for the other target over the radar"):
        try:
            other_card = services.get_site_card(bundle, selected, others[0].target_id, state.weights)
        except CellNotFoundError:
            st.caption(f"This cell has no data for {others[0].label}.")
    with handle_tai_errors():
        card_view.render_card(card, other_card)


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
    guide.inject_styles()
    with handle_tai_errors(fatal=True):
        bundle = get_bundle(str(DATA_DIR), data_signature(DATA_DIR))
        state = render_sidebar(services.list_targets(bundle))
    compact = device.is_phone()

    tab_explore, tab_method = st.tabs(["Explore", "Method"])
    with tab_explore:
        explore_tab(bundle, state, compact)
    with tab_method:
        method_tab(bundle)
    # The address always describes this view, so the browser's own "copy" or the button gives a link that reopens it.
    share.sync_query_params(share.query_params_for(
        state.target_id, state.weights, state.projection, state.hide_known, state.show_caves,
        st.session_state.get(SELECTED_KEY), st.query_params.get("view"),
    ))


main()
