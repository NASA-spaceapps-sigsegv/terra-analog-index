"""Capa biológica (TAI-15): paso 05 sobre XML y búsquedas de mentira, sin red."""

import importlib.util
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pipeline.common import MissingInputError
from tai import models, schemas
from tai.constants import BIO_TYPES, NCBI_BATCH

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("step05", ROOT / "pipeline" / "05_biology_ncbi.py")
step05 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(step05)

LOG = logging.getLogger("test")
ATACAMA_CELL = 23510  # design 3.3: lat -24.08, lon -69.92


def sample_xml(*samples) -> bytes:
    """samples: (accession, organism, {atributo: valor})."""
    parts = []
    for acc, organism, attrs in samples:
        a = "".join(
            f'<Attribute attribute_name="{k}" harmonized_name="{k}">{v}</Attribute>' for k, v in attrs.items()
        )
        parts.append(
            f'<BioSample accession="{acc}"><Description><Organism taxonomy_id="1" taxonomy_name="{organism}"/>'
            f"</Description><Attributes>{a}</Attributes></BioSample>"
        )
    return f"<BioSampleSet>{''.join(parts)}</BioSampleSet>".encode()


# --- Búsquedas ---------------------------------------------------------------


def test_environment_query_quotes_phrases_and_joins_with_or():
    q = step05.build_query("Bacteria[Organism]", "environment", ["hypersaline", "salt lake"])
    assert q == '(Bacteria[Organism]) AND (hypersaline OR "salt lake")'


def test_organism_query_uses_the_organism_field():
    q = step05.build_query("S", "organism", ["Deinococcus", "Chroococcidiopsis"])
    assert q == "(S) AND (Deinococcus[Organism] OR Chroococcidiopsis[Organism])"


def test_query_without_shared_filter():
    assert step05.build_query("  ", "environment", ["glacier"]) == "(glacier)"


# --- XML ---------------------------------------------------------------------


def test_parse_biosample_xml_extracts_the_design_attributes():
    xml = sample_xml(
        ("SAMN1", "Halomonas sp.", {"lat_lon": "24.08 S 69.92 W", "env_broad_scale": "desert biome",
                                    "isolation_source": "hypersaline lagoon", "geo_loc_name": "Chile: Atacama"}),
        ("SAMN2", "Bacillus", {"isolation_source": "soil"}),
    )
    one, two = step05.parse_biosample_xml(xml)
    assert one == {"accession": "SAMN1", "organism": "Halomonas sp.", "lat_lon": "24.08 S 69.92 W",
                   "env_broad_scale": "desert biome", "isolation_source": "hypersaline lagoon",
                   "geo_loc_name": "Chile: Atacama"}
    assert two["lat_lon"] is None and two["isolation_source"] == "soil" and two["geo_loc_name"] is None


def test_parse_ignores_empty_attribute_text_and_unknown_attributes():
    xml = sample_xml(("SAMN1", "X", {"lat_lon": "  ", "strain": "abc"}))
    (row,) = step05.parse_biosample_xml(xml)
    assert row["lat_lon"] is None and "strain" not in row


# --- Coordenadas y celdas ----------------------------------------------------


def raw_frame(rows):
    return pd.DataFrame(rows, columns=["accession", "organism", "lat_lon", "env_broad_scale",
                                       "isolation_source", "geo_loc_name"])


def test_samples_without_valid_coordinates_are_dropped():
    raw = raw_frame([
        ("A", "o", "24.08 S 69.92 W", None, None, None),
        ("B", "o", "missing", None, None, None),
        ("C", "o", None, None, None, None),
        ("D", "o", "0 N 0 E", None, None, None),
        ("E", "o", "95 N 10 E", None, None, None),
    ])
    out = step05.with_coordinates(raw)
    assert list(out["accession"]) == ["A"]
    assert out.loc[0, "lat"] == pytest.approx(-24.08) and out.loc[0, "lon"] == pytest.approx(-69.92)


def test_cell_assignment_matches_the_design_example_and_drops_the_sea():
    coords = pd.DataFrame({"accession": ["A", "B"], "lat": [-24.08, -40.5], "lon": [-69.92, -120.5]})
    out = step05.assign_cells(coords, [ATACAMA_CELL, 100])
    assert list(out["accession"]) == ["A"] and out.loc[0, "cell_id"] == ATACAMA_CELL


def test_assign_cells_on_an_empty_frame():
    empty = pd.DataFrame({"accession": [], "lat": [], "lon": []})
    assert step05.assign_cells(empty, [1, 2]).empty


# --- Tablas de salida --------------------------------------------------------


def on_land(rows):
    return pd.DataFrame(rows, columns=["accession", "extremophile_type", "organism", "lat", "lon", "cell_id",
                                       "env_broad_scale", "isolation_source", "geo_loc_name"])


def test_samples_table_matches_the_contract_and_keeps_one_row_per_sample_and_type():
    df = on_land([
        ("A", "halophile", "o", -24.08, -69.92, ATACAMA_CELL, None, None, None),
        ("A", "halophile", "o", -24.08, -69.92, ATACAMA_CELL, None, None, None),  # duplicado
        ("A", "xerophile", "o", -24.08, -69.92, ATACAMA_CELL, None, None, None),
    ])
    out = step05.samples_table(df)
    assert len(out) == 2
    assert schemas.check_schema(out, "bio_samples") == []


def test_cells_table_counts_unique_samples_and_types():
    df = on_land([
        ("A", "halophile", "o", 0, 0, 10, None, None, None),
        ("A", "xerophile", "o", 0, 0, 10, None, None, None),  # la misma muestra en dos tipos
        ("B", "halophile", "o", 0, 0, 10, None, None, None),
        ("C", "thermophile", "o", 0, 0, 11, None, None, None),
    ])
    cells = step05.cells_table(step05.samples_table(df), [10, 11, 12])
    got = cells.set_index("cell_id")
    assert got.loc[10, "bio_records"] == 2  # A y B, no 3 filas
    assert got.loc[10, "bio_types"] == 2 and got.loc[10, "bio_type_list"] == "halophile,xerophile"
    assert got.loc[11, "bio_records"] == 1 and got.loc[11, "bio_type_list"] == "thermophile"
    assert got.loc[12, "bio_records"] == 0 and got.loc[12, "bio_types"] == 0 and got.loc[12, "bio_type_list"] == ""
    assert str(cells["bio_records"].dtype) == "int32" and str(cells["bio_types"].dtype) == "int8"


def test_cells_table_without_samples_is_all_zero():
    cells = step05.cells_table(step05.samples_table(on_land([])), [1, 2, 3])
    assert len(cells) == 3 and (cells["bio_records"] == 0).all() and (cells["bio_types"] == 0).all()


def test_type_list_follows_the_order_of_bio_types():
    rows = [(f"S{i}", t, "o", 0, 0, 5, None, None, None) for i, t in enumerate(reversed(BIO_TYPES))]
    cells = step05.cells_table(step05.samples_table(on_land(rows)), [5])
    assert cells.loc[0, "bio_type_list"] == ",".join(BIO_TYPES) and cells.loc[0, "bio_types"] == 6


# --- Descarga por lotes ------------------------------------------------------


class FakeNcbi:
    def __init__(self, total):
        self.total = total
        self.fetches = []

    def search(self, query):
        return self.total, "WEBENV", "1"

    def fetch(self, webenv, query_key, start, n):
        self.fetches.append((start, n))
        return sample_xml(*((f"SAMN{start + i}", "o", {"lat_lon": "24 N 10 E"}) for i in range(n)))


def test_download_is_capped_batched_and_resumable(tmp_path):
    total_in_ncbi, cap = 5000, NCBI_BATCH * 2 + 50
    ncbi = FakeNcbi(total_in_ncbi)
    total, files = step05.download_type(ncbi, "halophile", "q", tmp_path, cap, LOG)
    assert total == total_in_ncbi and len(files) == 3
    assert ncbi.fetches == [(0, NCBI_BATCH), (NCBI_BATCH, NCBI_BATCH), (2 * NCBI_BATCH, 50)]
    assert [f.name for f in files] == ["halophile_0.xml", f"halophile_{NCBI_BATCH}.xml", f"halophile_{2 * NCBI_BATCH}.xml"]
    assert len(step05.read_batches(files)) == cap

    (tmp_path / f"halophile_{2 * NCBI_BATCH}.xml").unlink()  # se cortó antes del último lote
    again = FakeNcbi(total_in_ncbi)
    step05.download_type(again, "halophile", "q", tmp_path, cap, LOG)
    assert again.fetches == [(2 * NCBI_BATCH, 50)]  # solo pide lo que falta
    assert not list(tmp_path.glob("*.part"))


def test_download_of_a_small_result_makes_a_single_batch(tmp_path):
    ncbi = FakeNcbi(7)
    _, files = step05.download_type(ncbi, "psychrophile", "q", tmp_path, 5000, LOG)
    assert ncbi.fetches == [(0, 7)] and len(files) == 1


def test_download_of_an_empty_search_requests_nothing(tmp_path):
    ncbi = FakeNcbi(0)
    total, files = step05.download_type(ncbi, "acidophile", "q", tmp_path, 5000, LOG)
    assert total == 0 and files == [] and ncbi.fetches == []


# --- Plan B manual -----------------------------------------------------------


def test_manual_csv_becomes_samples(tmp_path):
    csv = tmp_path / "bio_manual.csv"
    csv.write_text("lat,lon,extremophile_type,source\n-24.08,-69.92,halophile,Cita 1\n37.7,-6.6,acidophile,Cita 2\n",
                   encoding="utf-8")
    df = step05.read_manual(csv)
    assert list(df["accession"]) == ["MANUAL-0001", "MANUAL-0002"]
    coords = step05.with_coordinates(df)
    assert list(coords["isolation_source"]) == ["Cita 1", "Cita 2"]
    assert coords.loc[0, "lat"] == pytest.approx(-24.08)


def test_manual_csv_rejects_unknown_types_and_missing_columns(tmp_path):
    bad_type = tmp_path / "a.csv"
    bad_type.write_text("lat,lon,extremophile_type,source\n1,2,piezophile,x\n", encoding="utf-8")
    with pytest.raises(MissingInputError, match="piezophile"):
        step05.read_manual(bad_type)
    no_cols = tmp_path / "b.csv"
    no_cols.write_text("lat,lon\n1,2\n", encoding="utf-8")
    with pytest.raises(MissingInputError, match="faltan columnas"):
        step05.read_manual(no_cols)


# --- Archivo de términos real ------------------------------------------------


def test_config_terms_validate_and_cover_the_six_types():
    terms = models.BioTermsFile.model_validate(json.loads((ROOT / "config" / "bio_terms.json").read_text(encoding="utf-8")))
    assert {t.extremophile_type for t in terms.types} == set(BIO_TYPES)
    assert terms.shared.strip()
