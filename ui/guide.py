"""Guidance in the Explore tab (TAI-40): a three-step strip, the key to the map's symbols and the "calculating" notice.

All of it is text and CSS: it computes nothing and reads no data.
"""

from __future__ import annotations

import streamlit as st

from ui.map_view import CAVE_COLOR, SELECTED_COLOR

GUIDE_TITLE = "How to use this page"

# The notice shows only if a run lasts more than half a second, so the quick ones (locally) do not flash it.
# It is a pseudo-element of the app container: Streamlit marks that container while the script is running.
STYLES = """
<style>
.stApp[data-test-script-state="running"]::after {
  content: "Calculating… the free server can take a few seconds";
  position: fixed; left: 50%; bottom: 1rem; transform: translateX(-50%);
  max-width: 92vw; text-align: center; font-size: 0.85rem; line-height: 1.3;
  background: rgba(20, 23, 28, 0.94); color: #fff; padding: 0.5rem 1rem; border-radius: 999px;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.4); z-index: 999999; pointer-events: none;
  opacity: 0; animation: tai-notice-in 0.25s ease 0.5s forwards;
}
@keyframes tai-notice-in { to { opacity: 1; } }
.tai-legend { display: flex; flex-wrap: wrap; gap: 0.35rem 1.1rem; font-size: 0.85rem; opacity: 0.85; margin: 0.25rem 0 0.5rem; }
.tai-legend span { display: inline-flex; align-items: center; gap: 0.4rem; }
.tai-key { display: inline-block; box-sizing: border-box; width: 1rem; height: 1rem; background: #14171c; }
.tai-ring { border: 2px solid #ffffff; border-radius: 50%; }
.tai-square { border: 2px solid SELECTED_COLOR; }
.tai-dot { border: 1.5px solid #ffffff; border-radius: 50%; background: rgba(16, 18, 22, 0.88); }
.tai-cave { width: 0; height: 0; background: none; border-left: 0.5rem solid transparent; border-right: 0.5rem solid transparent;
            border-bottom: 0.9rem solid CAVE_COLOR; }
</style>
""".replace("SELECTED_COLOR", SELECTED_COLOR).replace("CAVE_COLOR", CAVE_COLOR)


def inject_styles() -> None:
    st.html(STYLES)


def render_guide(compact: bool) -> None:
    """The three steps, in one line (two on a phone): what to do first."""
    first = "Open the menu (**»**, top left) and pick a target" if compact else "Pick a target in the sidebar"
    st.caption(
        f"**1** {first} · **2** Use a preset or move the weights · **3** Tap a numbered dot, a card or a row to open it"
    )


def render_legend(show_caves: bool) -> None:
    """What the symbols on the map mean, always visible (the map's own legend can be hidden by the toolbar on a phone)."""
    caves = '<span><i class="tai-key tai-cave"></i>Cave or lava tube</span>' if show_caves else ""
    st.html(
        '<div class="tai-legend">'
        '<span><i class="tai-key tai-ring"></i>Known analog</span>'
        '<span><i class="tai-key tai-dot"></i>Numbered dot: rank among the best 20</span>'
        '<span><i class="tai-key tai-square"></i>Selected cell</span>'
        f"{caves}</div>"
    )
