"""TAI-34 acceptance criteria: Method tab (design 10.7).

Covers tai/method.py (texts from content/method.md and tables), the services functions and ui/method_view.py.
"""

import json
import re
from pathlib import Path
from typing import get_args

import pytest
from streamlit.testing.v1 import AppTest

from tai import io, method, services
from tai.cards import VAR_LABELS, fmt_num
from tai.constants import DIMENSIONS, PHYSICAL_VARS
from tai.errors import TargetNotFoundError
from tai.models import (
    AnalogValidation,
    ColumnStats,
    Covered,
    Manifest,
    ManifestGrid,
    ManifestInput,
    ManifestOutput,
    ManifestStep,
    Rule,
    SourceType,
    TargetValidation,
    ValidationReport,
    Weights,
)
from ui import method_view

APP = str(Path(__file__).resolve().parents[1] / "streamlit_app.py")

MOON = "moon_south_pole"
MARS = "mars_jezero"

FULL_TEXT = """Before the first heading.

## What it does

First sentence. Second sentence.

## Data used

Data text.

### A subsection

Still part of Data used.

## How it is calculated

Rules.

## Validation

Percentiles.

## Limits

What is not known.

## Credits

Thanks.
"""


@pytest.fixture
def bundle(data_dir):
    return io.load_bundle(data_dir)


def _input(name, product, url="https://example.org/a", size=1.5):
    return ManifestInput(name=name, product=product, portal="Portal", url=url, files=1, size_mb=size, license_note="Open license")


def _step(step, inputs):
    return ManifestStep(
        step=step,
        ran_at="2026-11-14T15:00:00Z",
        duration_s=1.0,
        git_commit=None,
        inputs=inputs,
        outputs=[ManifestOutput(path="data/processed/x.parquet", rows=3, size_mb=0.1)],
        columns={"lat": ColumnStats(non_null=3, null=0, min=0.0, max=1.0)},
    )


@pytest.fixture
def manifest():
    return Manifest(
        schema_version=1,
        project="terra-analog-index",
        data_year=2024,
        grid=ManifestGrid(res_deg=1.0, n_cells=21357, land_frac_min=0.1),
        steps=[
            _step("01_grid", [_input("Land 1:50m", "ne_50m_land"), _input("Countries 1:50m", "ne_50m_countries")]),
            _step("02_terrain", [_input("ETOPO 2022", "ETOPO_2022"), _input("Land 1:50m", "ne_50m_land")]),
        ],
    )


def _analog(analog_id, name, covered, result, percentile, rank=10, total=0.5):
    return AnalogValidation(
        analog_id=analog_id, name=name, covered=covered, n_cells=4, best_cell_id=1, best_total=total,
        best_rank=rank, percentile=percentile, result=result,
    )


@pytest.fixture
def report():
    ok = TargetValidation(
        target_id=MOON, result="pass", covered_total=2, covered_passed=2, n_eligible=100,
        analogs=[_analog("a", "Analog A", "yes", "pass", 95.2), _analog("b", "Analog B", "yes", "pass", 91.0)],
    )
    bad = TargetValidation(
        target_id=MARS, result="fail", covered_total=2, covered_passed=1, n_eligible=100,
        note="Fails because analog C falls below the cutoff.",
        analogs=[
            _analog("c", "Analog C", "yes", "fail", 39.1),
            _analog("d", "Analog D", "no", "info", 88.8),
            AnalogValidation(analog_id="e", name="Analog E", covered="partial", n_cells=0, best_cell_id=None, best_total=None,
                             best_rank=None, percentile=None, result="no_data"),
        ],
    )
    return ValidationReport(
        schema_version=1, generated_at="2026-11-14T15:30:00Z",
        weights=Weights(terrain=1, temperature=1, water_ice=1, biology=0.5), percentile_threshold=90, targets=[ok, bad],
    )


# --- Texts in content/method.md ---------------------------------------------------------------------------


def test_parse_splits_by_second_level_headings():
    sections = method.parse_method(FULL_TEXT)
    assert list(sections) == list(method.SECTIONS)
    assert sections["What it does"] == "First sentence. Second sentence."
    assert "Before the first heading" not in " ".join(sections.values())


def test_a_third_level_heading_stays_inside_its_section():
    data = method.parse_method(FULL_TEXT)["Data used"]
    assert data.startswith("Data text.") and "### A subsection" in data and data.endswith("part of Data used.")


def test_windows_line_endings_and_bom_are_handled():
    sections = method.parse_method("﻿## What it does\r\n\r\nText.\r\n\r\n## Limits\r\n\r\nOther.\r\n")
    assert sections == {"What it does": "Text.", "Limits": "Other."}


def test_an_empty_section_is_kept_and_listed_as_pending():
    sections = method.parse_method("## What it does\n\nText.\n\n## Data used\n\n## Validation\n\nSomething.\n")
    assert sections["Data used"] == ""
    assert method.pending_sections(sections) == ["Data used", "How it is calculated", "Limits", "Credits"]
    assert method.pending_sections(method.parse_method(FULL_TEXT)) == []


def test_without_the_file_there_are_no_sections(tmp_path):
    assert method.read_method(tmp_path / "does_not_exist.md") == {}
    assert method.pending_sections({}) == list(method.SECTIONS)


def test_read_method_reads_a_utf8_file(tmp_path):
    path = tmp_path / "method.md"
    path.write_text(FULL_TEXT, encoding="utf-8")
    assert method.read_method(path)["Credits"] == "Thanks."
    assert services.get_method_text(path)["Credits"] == "Thanks."


def test_the_method_file_lives_in_content():
    assert method.METHOD_PATH == Path("content") / "method.md"
    assert services.METHOD_PATH == Path(__file__).resolve().parents[1] / "content" / "method.md"


def test_the_real_method_file_has_the_six_sections_with_text():
    """content/method.md is what the tab reads: if someone leaves a section empty, this test flags it."""
    sections = method.read_method(services.METHOD_PATH)
    assert method.pending_sections(sections) == [], "missing or empty: " + ", ".join(method.pending_sections(sections))
    assert set(sections) == set(method.SECTIONS)  # no extra or misspelled heading


def test_the_real_method_file_has_no_wiki_style_quotes_or_placeholders():
    text = services.METHOD_PATH.read_text(encoding="utf-8")
    assert "''" not in text, "in Markdown italics are *like this*, not ''like this''"
    assert "TODO" not in text and "text pending" not in text.lower()


# --- Variables table ------------------------------------------------------------------------------------


def test_every_rule_source_type_and_result_has_a_label():
    assert set(method.RULE_LABELS) == set(get_args(Rule))
    assert set(method.SOURCE_TYPE_LABELS) == set(get_args(SourceType))
    assert set(method.COVERED_LABELS) == set(get_args(Covered))
    assert set(method.TARGET_RESULT_LABELS) == {"pass", "fail", "insufficient"}
    assert set(method.RESULT_LEGEND) == {"pass", "fail", "info", "no_data"}


def test_variables_table_has_one_row_per_physical_variable(bundle):
    target = services.get_target(bundle, MOON)
    table = method.variables_table(target)
    assert tuple(table.columns) == method.VARIABLE_COLUMNS
    assert list(table["Variable"]) == [VAR_LABELS[v] for v in PHYSICAL_VARS]


def test_variables_table_numbers_come_from_targets_json(bundle):
    target = services.get_target(bundle, MOON)
    table = method.variables_table(target).set_index("Variable")
    for var in PHYSICAL_VARS:
        spec = target.vars[var]
        d = {"mm/yr": 0, "fraction": 2}.get(spec.unit, 1)
        row = table.loc[VAR_LABELS[var]]
        assert row["Unit"] == spec.unit
        assert row["Value (mean ± std)"] == f"{fmt_num(spec.mean, d)} ± {fmt_num(spec.std, d)}"
        assert row["Range on Earth"] == f"{fmt_num(spec.earth_p01, d)} to {fmt_num(spec.earth_p99, d)}"
        assert row["Rule"] == method.RULE_LABELS[spec.rule]
        assert row["Source type"] == method.SOURCE_TYPE_LABELS[spec.source_type]
        assert spec.source in row["Sources"]


def test_variables_table_adds_the_earth_source_when_the_manifest_has_it(bundle):
    target = services.get_target(bundle, MOON)
    table = method.variables_table(target, {"slope_deg": "ETOPO 2022"}).set_index("Variable")
    assert table.loc[VAR_LABELS["slope_deg"], "Sources"].endswith("Earth: ETOPO 2022")
    assert "Earth:" not in table.loc[VAR_LABELS["tmin_c"], "Sources"]


# --- Sources ----------------------------------------------------------------------------------------------


def test_sources_are_listed_once_in_step_order(manifest):
    table = method.sources_table(manifest)
    assert tuple(table.columns) == method.SOURCE_COLUMNS
    assert list(table["Product"]) == ["ne_50m_land", "ne_50m_countries", "ETOPO_2022"]  # ne_50m_land is not repeated


def test_sources_without_steps_is_an_empty_table(bundle):
    assert method.sources_table(bundle.manifest).empty


def test_sources_markdown_has_a_header_and_a_link_per_row(manifest):
    lines = method.sources_markdown(manifest).split("\n")
    assert lines[0] == "| Data | Product | Portal | License | Link |"
    assert lines[1] == "| --- | --- | --- | --- | --- |"
    assert len(lines) == 2 + 3 and all("[Open](https://example.org/a)" in row for row in lines[2:])


def test_sources_markdown_keeps_the_table_valid_with_pipes_and_parentheses():
    step = _step("01_grid", [ManifestInput(name="Odd | data", product="p", portal="Portal", url="https://x.org/a_(b)", files=1,
                                          size_mb=1, license_note="Free\nuse")])
    manifest = Manifest(schema_version=1, project="terra-analog-index", data_year=2024, grid=None, steps=[step])
    row = method.sources_markdown(manifest).split("\n")[2]
    assert "Odd \\| data" in row and "Free use" in row and "https://x.org/a_(b%29" in row
    assert len(method.sources_markdown(manifest).split("\n")) == 3  # no cell split the row


def test_grid_summary_comes_from_the_manifest(manifest, bundle):
    assert method.grid_summary(manifest) == "1° grid with 21,357 land cells. Data year: 2024."
    assert method.grid_summary(bundle.manifest) == "Data year: 2024."  # no grid, only the year


# --- Validation -------------------------------------------------------------------------------------------


def test_validation_table_shows_pass_fail_or_info_with_percentile(report):
    table = method.validation_table(report.targets[1])
    assert tuple(table.columns) == method.VALIDATION_COLUMNS
    assert list(table["Analog"]) == ["Analog C", "Analog D", "Analog E"]
    assert list(table["Result"]) == ["fail", "info", "no_data"]
    assert list(table["Covered"]) == ["Yes", "No", "Partial"]
    assert table.loc[0, "Percentile"] == 39.1 and table.loc[1, "Percentile"] == 88.8
    assert table["Percentile"].isna().tolist() == [False, False, True]  # no data stays empty, not 0


def test_validation_table_values_are_the_ones_in_the_file(report):
    for target in report.targets:
        table = method.validation_table(target)
        assert list(table["Percentile"].fillna(-1)) == [a.percentile if a.percentile is not None else -1 for a in target.analogs]
        assert list(table["Rank"].fillna(-1)) == [a.best_rank if a.best_rank is not None else -1 for a in target.analogs]
        assert list(table["Best score"].fillna(-1)) == [a.best_total if a.best_total is not None else -1 for a in target.analogs]


def test_validation_summary_uses_the_numbers_of_the_report(report):
    assert method.validation_summary(report.targets[0], report) == "Pass: 2 of 2 covered analogs exceed percentile 90"
    assert method.validation_summary(report.targets[1], report) == "Fail: 1 of 2 covered analogs exceed percentile 90"
    odd = report.model_copy(update={"percentile_threshold": 87.5})
    assert method.validation_summary(odd.targets[0], odd).endswith("percentile 87.5")


def test_weights_summary_lists_the_four_dimensions(report):
    text = method.weights_summary(report, {d: d.upper() for d in DIMENSIONS})
    assert text == "Validation weights: TERRAIN 1, TEMPERATURE 1, WATER_ICE 1, DUST_WIND 0, BIOLOGY 0.5"


def test_result_legend_explains_every_result_and_the_cut(report):
    legend = method.result_legend(report)
    assert legend.startswith("Cutoff percentile: 90.")
    assert all(f"{code}:" in legend for code in method.RESULT_LEGEND)


# --- services ---------------------------------------------------------------------------------------------


def test_get_target_returns_the_full_target(bundle):
    assert services.get_target(bundle, MARS).target_id == MARS
    with pytest.raises(TargetNotFoundError):
        services.get_target(bundle, "venus")


def test_get_validation_returns_everything_or_one_target(bundle):
    full = services.get_validation(bundle)
    assert [t.target_id for t in full.targets] == [MOON, MARS]
    one = services.get_validation(bundle, MARS)
    assert [t.target_id for t in one.targets] == [MARS]
    assert one.percentile_threshold == full.percentile_threshold
    assert len(bundle.validation.targets) == 2  # does not modify the bundle
    with pytest.raises(TargetNotFoundError):
        services.get_validation(bundle, "venus")


def test_get_manifest_is_the_bundles_manifest(bundle):
    assert services.get_manifest(bundle) is bundle.manifest


# --- Vista ------------------------------------------------------------------------------------------------


def test_table_height_fits_the_header_and_every_row():
    assert method_view.table_height(0) == method_view.HEADER_HEIGHT + method_view.TABLE_BORDERS
    assert method_view.table_height(4) == 35 + 4 * 35 + 2


def test_results_are_colored_by_outcome(report):
    html = method_view.style_results(method.validation_table(report.targets[1])).to_html()
    # pandas merges cells with the same style into a single CSS rule: "#T_x_row1_col6, #T_x_row2_col6 { ... }"
    rule = lambda style: re.search(r"((?:#\w+(?:, )?)+) \{\s*" + re.escape(style), html)  # noqa: E731
    fail, info = rule(method_view.RESULT_STYLE["fail"]), rule(method_view.RESULT_STYLE["info"])
    assert fail.group(1).count("_row") == 1  # only the "fail" row
    assert info.group(1).count("_row") == 2  # info and no_data share the gray
    assert method_view.RESULT_STYLE["pass"] not in html


# --- The tab inside the app -----------------------------------------------------------------------------


@pytest.fixture
def app_with(data_dir, monkeypatch, tmp_path):
    """The app with the test data, its own method.md and, if requested, another validation.json."""

    def build(text: str | None = FULL_TEXT, validation: ValidationReport | None = None):
        monkeypatch.setenv("TAI_DATA_DIR", str(data_dir))
        path = tmp_path / "method.md"
        if text is not None:
            path.write_text(text, encoding="utf-8")
        monkeypatch.setattr(services, "METHOD_PATH", path)
        if validation is not None:
            (data_dir / "validation.json").write_text(validation.model_dump_json(), encoding="utf-8")
        return AppTest.from_file(APP, default_timeout=30).run()

    return build


def _method_markdown(app) -> str:
    return "\n".join(m.value for m in app.markdown)


def test_the_tab_shows_the_six_parts_in_order(app_with):
    app = app_with()
    assert not app.exception and not app.error
    headings = [s.value for s in app.subheader]
    assert [h for h in headings if h in method.SECTIONS] == list(method.SECTIONS)
    assert not any("arrives on Sunday" in i.value for i in app.info)


def test_the_fixed_texts_come_from_method_md(app_with):
    text = _method_markdown(app_with())
    for piece in ("First sentence. Second sentence.", "Data text.", "Rules.", "Percentiles.", "What is not known.", "Thanks."):
        assert piece in text
    assert "Before the first heading" not in text


def test_without_method_md_each_part_says_what_is_missing(app_with):
    app = app_with(text=None)
    assert not app.exception
    captions = [c.value for c in app.caption]
    for title in method.SECTIONS:
        assert method_view.PENDING.format(title=title) in captions


def test_a_half_written_method_md_marks_only_the_missing_parts(app_with):
    app = app_with(text="## What it does\n\nJust this.\n")
    captions = [c.value for c in app.caption]
    assert method_view.PENDING.format(title="What it does") not in captions
    assert method_view.PENDING.format(title="Credits") in captions


def test_there_is_a_variables_table_per_target(app_with, bundle):
    app = app_with()
    assert len(app.table) == len(bundle.targets.targets)
    assert [t.label for t in bundle.targets.targets][0] in _method_markdown(app)


def test_a_failing_validation_is_shown_with_the_note_and_not_hidden(app_with, report):
    app = app_with(validation=report)
    assert [e.value for e in app.error] == ["Fail: 1 of 2 covered analogs exceed percentile 90"]
    assert "Fails because analog C falls below the cutoff." in _method_markdown(app)
    assert [s.value for s in app.success] == ["Pass: 2 of 2 covered analogs exceed percentile 90"]
    shown = [df.value for df in app.dataframe if "Analog" in df.value.columns]  # the ranking is also a dataframe
    assert len(shown) == 2  # one validation table per target
    assert any("Analog C" in set(d["Analog"]) and "fail" in set(d["Result"]) for d in shown)


def test_insufficient_validation_is_a_warning(app_with):
    app = app_with()  # the test data has both targets as "insufficient"
    assert [w.value for w in app.warning if w.value.startswith("Insufficient data")]


def test_the_tab_numbers_are_the_ones_in_the_files(app_with, report):
    """No validation figure written by hand: what is shown is what the report says."""
    app = app_with(validation=report)
    text = _method_markdown(app) + "\n".join(c.value for c in app.caption)
    assert method.weights_summary(report, method_view.DIMENSION_LABELS) in text
    assert method.result_legend(report) in text
    json.loads(report.model_dump_json())  # the report is valid JSON
