"""Method tab (design 10.7, TAI-34): the texts in content/method.md and the tables that come from the files.

The fixed texts are written by Santino in content/method.md; here they are split by headings. The figures are
not written by hand anywhere: they come from targets.json, manifest.json and validation.json. It is pure except
for reading content/method.md. The view (ui/method_view.py) only draws what these functions build.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from tai.cards import VAR_LABELS, earth_source_names, fmt_num
from tai.constants import PHYSICAL_VARS
from tai.models import Manifest, Target, TargetValidation, ValidationReport

METHOD_PATH = Path("content") / "method.md"

# Headings of method.md (`## ...`), in the order the tab shows them (design 10.7).
SECTIONS = ("What it does", "Data used", "How it is calculated", "Validation", "Limits", "Credits")

NO_DATA = "no data"

# What each scoring rule (design 5.1) and each source type is called on screen.
RULE_LABELS = {
    "overlap": "Similar if it falls within the range",
    "directional_low": "Rewards the lowest values on Earth",
    "directional_high": "Rewards the highest values on Earth",
    "presence": "Rewards presence",
    "absence": "Rewards absence",
}
SOURCE_TYPE_LABELS = {"measured": "Measured", "literature": "Literature", "definition": "Definition"}

COVERED_LABELS = {"yes": "Yes", "partial": "Partial", "no": "No"}
TARGET_RESULT_LABELS = {"pass": "Pass", "fail": "Fail", "insufficient": "Insufficient data"}

# What each value in the "Result" column means (shown as it is in validation.json).
RESULT_LEGEND = {
    "pass": "the analog's best place exceeds the cutoff percentile",
    "fail": "the analog's best place does not exceed it",
    "info": "the analog is not covered: it is shown but does not count toward the target's result",
    "no_data": "there are no cells with data within the analog's radius",
}

# What each column of the validation table means, shown under the tables.
COLUMN_LEGEND = {
    "Covered": "whether the index measures what the analog is known for (only \"Yes\" counts toward the result)",
    "Cells": "cells within the analog's radius",
    "Best score, Rank and Percentile": "those of the best of those cells among all eligible cells",
}

# Why a known analog fails, by analog_id. Shown only while its result is "fail", so a text that the data
# no longer backs disappears by itself.
FAIL_REASONS = {
    "haughton_crater": (
        "a near miss. Colder, icier Antarctic cells fill the top of the lunar ranking, and a 23 km crater "
        "is lost in a 110 km cell."
    ),
    "mcmurdo_dry_valleys": (
        "its ice-free valleys are too small for a 110 km cell, which is mostly glacier, so ice scores 0 "
        "against an ice-free Jezero. It also has almost no dust and much stronger wind."
    ),
}

VARIABLE_COLUMNS = ("Variable", "Unit", "Value (mean ± std)", "Rule", "Range on Earth", "Sources", "Source type")
SOURCE_COLUMNS = ("Data", "Product", "Portal", "License", "Size (MB)", "Link")
VALIDATION_COLUMNS = ("Analog", "Covered", "Cells", "Best score", "Rank", "Percentile", "Result")


# --- Texts in content/method.md -------------------------------------------------------------------------

_HEADING = re.compile(r"^##[ \t]+(.+?)[ \t]*$", re.MULTILINE)


def parse_method(text: str) -> dict[str, str]:
    """Split method.md by its `## Title` headings: {title: text}. Anything before the first one is ignored."""
    text = text.lstrip("﻿").replace("\r\n", "\n")
    found = list(_HEADING.finditer(text))
    sections = {}
    for i, m in enumerate(found):
        end = found[i + 1].start() if i + 1 < len(found) else len(text)
        sections[m.group(1)] = text[m.end() : end].strip()
    return sections


def read_method(path: Path | None = None) -> dict[str, str]:
    """The sections of method.md. No file: {} (the tab says what is missing instead of breaking)."""
    path = Path(path) if path is not None else METHOD_PATH
    if not path.is_file():
        return {}
    return parse_method(path.read_text(encoding="utf-8"))


def pending_sections(sections: dict[str, str]) -> list[str]:
    """Headings in SECTIONS that are missing from the file or have no text yet."""
    return [s for s in SECTIONS if not sections.get(s, "").strip()]


# --- Variables table (design 10.7, point 2) ---------------------------------------------------------


def _decimals(unit: str) -> int:
    # The same digits as the card phrases: fractions and precipitation with fewer decimals.
    return {"mm/yr": 0, "fraction": 2}.get(unit, 1)


def variables_table(target: Target, earth_sources: dict[str, str] | None = None) -> pd.DataFrame:
    """One row per physical variable of the target: value, rule, range on Earth and sources.

    `earth_sources` (variable -> name of the Earth source) goes at the end of the row's source; it comes from the manifest.
    """
    earth_sources = earth_sources or {}
    rows = []
    for var in PHYSICAL_VARS:
        spec = target.vars.get(var)
        if spec is None:  # optional variable the target does not have (dust and wind on the Moon, TAI-52)
            continue
        d = _decimals(spec.unit)
        source = spec.source
        if earth_sources.get(var):
            source = f"{source}. Earth: {earth_sources[var]}"
        rows.append(
            {
                "Variable": VAR_LABELS[var],
                "Unit": spec.unit,
                "Value (mean ± std)": f"{fmt_num(spec.mean, d)} ± {fmt_num(spec.std, d)}",
                "Rule": RULE_LABELS[spec.rule],
                "Range on Earth": f"{fmt_num(spec.earth_p01, d)} to {fmt_num(spec.earth_p99, d)}",
                "Sources": source,
                "Source type": SOURCE_TYPE_LABELS[spec.source_type],
            }
        )
    return pd.DataFrame(rows, columns=list(VARIABLE_COLUMNS))


# --- Manifest sources -------------------------------------------------------------------------------


def sources_table(manifest: Manifest) -> pd.DataFrame:
    """The input data of every step, without repeats (a product appears once), in step order."""
    rows, seen = [], set()
    for step in manifest.steps:
        for item in step.inputs:
            if item.product in seen:
                continue
            seen.add(item.product)
            rows.append(
                {
                    "Data": item.name,
                    "Product": item.product,
                    "Portal": item.portal,
                    "License": item.license_note,
                    "Size (MB)": item.size_mb,
                    "Link": item.url,
                }
            )
    return pd.DataFrame(rows, columns=list(SOURCE_COLUMNS))


def _cell(x) -> str:
    return str(x).replace("|", "\\|").replace("\n", " ").strip()


def sources_markdown(manifest: Manifest) -> str:
    """The sources table as Markdown: cells wrap instead of being cut off and the link can be opened."""
    cols = ["Data", "Product", "Portal", "License", "Link"]
    lines = ["| " + " | ".join(cols) + " |", "|" + " --- |" * len(cols)]
    for r in sources_table(manifest).itertuples(index=False):
        url = str(r.Link).strip().replace(" ", "%20").replace(")", "%29")
        link = f"[Open]({url})" if url else ""
        lines.append("| " + " | ".join([_cell(r.Data), _cell(r.Product), _cell(r.Portal), _cell(r.License), link]) + " |")
    return "\n".join(lines)


def grid_summary(manifest: Manifest) -> str:
    """"1° grid with 21,357 land cells. Data year: 2024." No grid (step 01 not run): just the year."""
    year = f"Data year: {manifest.data_year}."
    if manifest.grid is None:
        return year
    g = manifest.grid
    cells = f"{g.n_cells:,}"
    return f"{fmt_num(g.res_deg, 0 if float(g.res_deg).is_integer() else 2)}° grid with {cells} land cells. {year}"


# --- Validation (design 10.7, point 4) --------------------------------------------------------------------


def validation_table(target: TargetValidation) -> pd.DataFrame:
    """One row per known analog with its percentile and its result, as they are in validation.json."""
    rows = [
        {
            "Analog": a.name,
            "Covered": COVERED_LABELS[a.covered],
            "Cells": a.n_cells,
            "Best score": a.best_total,
            "Rank": a.best_rank,
            "Percentile": a.percentile,
            "Result": a.result,
        }
        for a in target.analogs
    ]
    return pd.DataFrame(rows, columns=list(VALIDATION_COLUMNS))


def validation_summary(target: TargetValidation, report: ValidationReport) -> str:
    """"Pass: 2 of 3 covered analogs exceed the 90th percentile". The numbers come from the report."""
    threshold = f"{report.percentile_threshold:g}"
    return (
        f"{TARGET_RESULT_LABELS[target.result]}: {target.covered_passed} of {target.covered_total} covered "
        f"analogs exceed percentile {threshold}"
    )


def weights_summary(report: ValidationReport, labels: dict[str, str]) -> str:
    """"Validation weights: Terrain 1, Temperature 1, Water and ice 1, Astrobiological interest 0.5"."""
    parts = [f"{labels[d]} {fmt_num(w, 0 if float(w).is_integer() else 1)}" for d, w in report.weights.as_dict().items()]
    return "Validation weights: " + ", ".join(parts)


def result_legend(report: ValidationReport) -> str:
    threshold = f"{report.percentile_threshold:g}"
    parts = [f"{k}: {v}" for k, v in RESULT_LEGEND.items()]
    return f"Cutoff percentile: {threshold}. " + "; ".join(parts) + "."


def column_legend() -> str:
    """"Columns. Covered: ...; Cells: ...": what each column of the validation table means."""
    return "Columns. " + "; ".join(f"{k}: {v}" for k, v in COLUMN_LEGEND.items()) + "."


def fail_notes(target: TargetValidation) -> list[str]:
    """"Why Haughton Crater (Devon Island) fails: ..." for each failed analog with a reason in FAIL_REASONS."""
    return [
        f"Why {a.name} fails: {FAIL_REASONS[a.analog_id]}"
        for a in target.analogs
        if a.result == "fail" and a.analog_id in FAIL_REASONS
    ]


__all__ = [
    "METHOD_PATH",
    "SECTIONS",
    "column_legend",
    "fail_notes",
    "earth_source_names",
    "grid_summary",
    "parse_method",
    "pending_sections",
    "read_method",
    "result_legend",
    "sources_markdown",
    "sources_table",
    "validation_summary",
    "validation_table",
    "variables_table",
    "weights_summary",
]
