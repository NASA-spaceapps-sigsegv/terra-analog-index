"""Method tab (design 10.7, TAI-34). Draws what tai/method.py builds; it neither computes nor words anything.

Six parts, in this order: what it does, data used (with the variables table and the manifest sources),
how it is calculated, validation (with the validation.json table), limits and credits. The fixed texts come
from content/method.md, written by Santino; a section without text says it is pending instead of staying
empty. No figure is written by hand: they come from the files in data/processed/.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd
import streamlit as st

from tai import method
from tai.cards import DIMENSION_LABELS
from tai.constants import SCORE_DECIMALS_UI

if TYPE_CHECKING:
    from tai.models import Manifest, Target, TargetValidation, ValidationReport

PENDING = "Text pending: the \"{title}\" section is missing from content/method.md."
VARIABLES_HEADING = "Variables of each target site"
SOURCES_HEADING = "Sources of the Earth data"
UNREPLICABLE_HEADING = "What no place on Earth can replicate"

# Table height, in pixels: with height="auto" st.dataframe is cut at 400 px and you have to scroll
# inside. Header and rows of 35 px (2.1875rem) plus a 1 px border at the top and bottom.
ROW_HEIGHT = 35
HEADER_HEIGHT = 35
TABLE_BORDERS = 2

# Soft background per result: it reads the same in light and dark themes because the text color does not change.
RESULT_STYLE = {
    "pass": "background-color: rgba(33, 145, 140, 0.35)",
    "fail": "background-color: rgba(229, 57, 53, 0.35)",
    "info": "background-color: rgba(128, 128, 128, 0.25)",
    "no_data": "background-color: rgba(128, 128, 128, 0.25)",
}


def table_height(n_rows: int) -> int:
    return HEADER_HEIGHT + n_rows * ROW_HEIGHT + TABLE_BORDERS


def _text(sections: dict[str, str], title: str) -> None:
    body = sections.get(title, "").strip()
    if body:
        st.markdown(body)
    else:
        st.caption(PENDING.format(title=title))


def style_results(df: pd.DataFrame):
    """The validation DataFrame with the Result column colored; a pandas Styler, which st.dataframe accepts."""
    return df.style.map(lambda r: RESULT_STYLE.get(r, ""), subset=["Result"])


# --- Data used --------------------------------------------------------------------------------------


def render_variables(targets: list[Target], manifest: Manifest) -> None:
    st.markdown(f"##### {VARIABLES_HEADING}")
    earth = method.earth_source_names(manifest)
    for target in targets:
        st.markdown(f"**{target.label}**")
        # st.table and not st.dataframe: the sources are long phrases and the table wraps them instead of cutting them.
        st.table(method.variables_table(target, earth).set_index("Variable"))


def render_sources(manifest: Manifest) -> None:
    st.markdown(f"##### {SOURCES_HEADING}")
    st.markdown(method.sources_markdown(manifest))
    st.caption(method.grid_summary(manifest))


# --- Validation ------------------------------------------------------------------------------------


def render_target_validation(target: TargetValidation, label: str, report: ValidationReport) -> None:
    st.markdown(f"**{label}**")
    summary = method.validation_summary(target, report)
    if target.result == "pass":
        st.success(summary)
    elif target.result == "fail":
        st.error(summary)  # a fail is not hidden: it is shown with Santino's note
    else:
        st.warning(summary)
    if target.note.strip():
        st.markdown(f"> {target.note.strip()}")
    table = method.validation_table(target)
    st.dataframe(
        style_results(table),
        hide_index=True,
        height=table_height(len(table)),
        column_config={
            "Cells": st.column_config.NumberColumn(format="%d"),
            "Best score": st.column_config.NumberColumn(format=f"%.{SCORE_DECIMALS_UI}f"),
            "Rank": st.column_config.NumberColumn(format="%d"),
            "Percentile": st.column_config.NumberColumn(format="%.1f"),
        },
    )


def render_validation(report: ValidationReport, labels: dict[str, str]) -> None:
    st.caption(method.weights_summary(report, DIMENSION_LABELS))
    for target in report.targets:
        render_target_validation(target, labels.get(target.target_id, target.target_id), report)
    st.caption(method.result_legend(report))


# --- Limits ----------------------------------------------------------------------------------------


def render_unreplicable(targets: list[Target]) -> None:
    st.markdown(f"##### {UNREPLICABLE_HEADING}")
    for target in targets:
        st.markdown(f"**{target.label}**")
        st.markdown("\n".join(f"- {item}" for item in [*target.unreplicable, *target.notes]))


# --- Tab -------------------------------------------------------------------------------------------


def render_method(
    sections: dict[str, str], targets: list[Target], validation: ValidationReport, manifest: Manifest
) -> None:
    """Draw the tab. `sections` is what tai.method.read_method() returns."""
    labels = {t.target_id: t.label for t in targets}

    st.subheader("What it does")
    _text(sections, "What it does")

    st.subheader("Data used")
    _text(sections, "Data used")
    render_variables(targets, manifest)
    render_sources(manifest)

    st.subheader("How it is calculated")
    _text(sections, "How it is calculated")

    st.subheader("Validation")
    _text(sections, "Validation")
    render_validation(validation, labels)

    st.subheader("Limits")
    _text(sections, "Limits")
    render_unreplicable(targets)

    st.subheader("Credits")
    _text(sections, "Credits")
