"""Pestaña Método (design 10.7, TAI-34). Dibuja lo que arma tai/method.py; no calcula ni redacta.

Seis partes, en este orden: qué hace, datos usados (con la tabla de variables y las fuentes del manifiesto),
cómo se calcula, validación (con la tabla de validation.json), límites y créditos. Los textos fijos salen de
content/method.md, que escribe Santino; una sección sin texto dice que está pendiente en vez de quedar vacía.
Ninguna cifra se escribe a mano: salen de los archivos de data/processed/.
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

PENDING = "Texto pendiente: falta la sección «{title}» en content/method.md."
VARIABLES_HEADING = "Variables de cada sitio objetivo"
SOURCES_HEADING = "Fuentes de los datos de la Tierra"
UNREPLICABLE_HEADING = "Lo que ningún lugar de la Tierra puede replicar"

# Altura de las tablas, en píxeles: con height="auto" st.dataframe se corta en 400 px y hay que desplazarse
# adentro. Encabezado y filas de 35 px (2.1875rem) más un borde de 1 px arriba y abajo.
ROW_HEIGHT = 35
HEADER_HEIGHT = 35
TABLE_BORDERS = 2

# Fondo suave por resultado: se lee igual en tema claro y oscuro porque el color de la letra no cambia.
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
    """El DataFrame de validación con la columna Resultado pintada; pandas Styler, que st.dataframe acepta."""
    return df.style.map(lambda r: RESULT_STYLE.get(r, ""), subset=["Resultado"])


# --- Datos usados ----------------------------------------------------------------------------------


def render_variables(targets: list[Target], manifest: Manifest) -> None:
    st.markdown(f"##### {VARIABLES_HEADING}")
    earth = method.earth_source_names(manifest)
    for target in targets:
        st.markdown(f"**{target.label}**")
        # st.table y no st.dataframe: las fuentes son frases largas y la tabla las parte en vez de cortarlas.
        st.table(method.variables_table(target, earth).set_index("Variable"))


def render_sources(manifest: Manifest) -> None:
    st.markdown(f"##### {SOURCES_HEADING}")
    st.markdown(method.sources_markdown(manifest))
    st.caption(method.grid_summary(manifest))


# --- Validación ------------------------------------------------------------------------------------


def render_target_validation(target: TargetValidation, label: str, report: ValidationReport) -> None:
    st.markdown(f"**{label}**")
    summary = method.validation_summary(target, report)
    if target.result == "pass":
        st.success(summary)
    elif target.result == "fail":
        st.error(summary)  # un fail no se esconde: se muestra con la nota de Santino
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
            "Celdas": st.column_config.NumberColumn(format="%d"),
            "Mejor puntaje": st.column_config.NumberColumn(format=f"%.{SCORE_DECIMALS_UI}f"),
            "Puesto": st.column_config.NumberColumn(format="%d"),
            "Percentil": st.column_config.NumberColumn(format="%.1f"),
        },
    )


def render_validation(report: ValidationReport, labels: dict[str, str]) -> None:
    st.caption(method.weights_summary(report, DIMENSION_LABELS))
    for target in report.targets:
        render_target_validation(target, labels.get(target.target_id, target.target_id), report)
    st.caption(method.result_legend(report))


# --- Límites ---------------------------------------------------------------------------------------


def render_unreplicable(targets: list[Target]) -> None:
    st.markdown(f"##### {UNREPLICABLE_HEADING}")
    for target in targets:
        st.markdown(f"**{target.label}**")
        st.markdown("\n".join(f"- {item}" for item in [*target.unreplicable, *target.notes]))


# --- Pestaña ---------------------------------------------------------------------------------------


def render_method(
    sections: dict[str, str], targets: list[Target], validation: ValidationReport, manifest: Manifest
) -> None:
    """Dibuja la pestaña. `sections` es lo que devuelve tai.method.read_method()."""
    labels = {t.target_id: t.label for t in targets}

    st.subheader("Qué hace")
    _text(sections, "Qué hace")

    st.subheader("Datos usados")
    _text(sections, "Datos usados")
    render_variables(targets, manifest)
    render_sources(manifest)

    st.subheader("Cómo se calcula")
    _text(sections, "Cómo se calcula")

    st.subheader("Validación")
    _text(sections, "Validación")
    render_validation(validation, labels)

    st.subheader("Límites")
    _text(sections, "Límites")
    render_unreplicable(targets)

    st.subheader("Créditos")
    _text(sections, "Créditos")
