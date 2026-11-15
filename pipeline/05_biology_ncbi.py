"""Step 05: NCBI BioSample extremophile records per cell (design 7, RF-05, TAI-15).

Reads:  config/bio_terms.json            (types, search terms and shared filter, TAI-06)
        data/processed/grid.parquet      (step 01: which cells are land)
        NCBI BioSample over the network  (needs NCBI_EMAIL; NCBI_API_KEY is optional)
        config/bio_manual.csv            (only with --manual: plan B, no network)
Writes: data/raw/05_biology/<type>_<start>.xml   raw batches, so an interrupted run resumes
        data/processed/bio_samples.parquet       one row per sample and type
        data/interim/biology.parquet             one row per grid cell: bio_records,
                                                 bio_types, bio_type_list (0 / 0 / "" if none)

A sample belongs to every type whose search returns it, so bio_records counts
unique accessions per cell and bio_types the distinct types. Samples without a
valid lat_lon (design 7.4) or outside the land grid are dropped and counted
per type in the manifest: total in NCBI, downloaded, with coordinates, on land.

Test first with one type and few records, then run everything:
    python pipeline/05_biology_ncbi.py --type halophile --max-records 200
    python pipeline/05_biology_ncbi.py
"""

import io
import os
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

# Steps run as `python pipeline/NN_step.py`; put the repo root on the path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from pipeline.common import (  # noqa: E402
    CONFIG,
    GRID_PATH,
    INTERIM,
    PARTIAL_NOTE_PREFIX,
    PROCESSED,
    RAW,
    ROOT,
    MissingInputError,
    atomic_write_parquet,
    bbox_mask,
    bbox_note,
    column_stats,
    file_size_mb,
    is_up_to_date,
    last_run_partial,
    load_grid,
    make_parser,
    require_inputs,
    run,
    setup_logging,
    step_entry,
    validate_output,
    write_step_manifest,
)
from tai import geo  # noqa: E402
from tai.constants import (  # noqa: E402
    BIO_MAX_RECORDS_PER_TYPE,
    BIO_TYPES,
    NCBI_BATCH,
    NCBI_DELAY_NO_KEY_S,
    NCBI_DELAY_WITH_KEY_S,
    NCBI_MAX_RETRIES,
)
from tai.latlon import parse_lat_lon  # noqa: E402
from tai.models import BioTermsFile  # noqa: E402

STEP = "05_biology_ncbi"
RAW_DIR = RAW / "05_biology"
TERMS_PATH = CONFIG / "bio_terms.json"
MANUAL_PATH = CONFIG / "bio_manual.csv"
SAMPLES_OUT = PROCESSED / "bio_samples.parquet"
CELLS_OUT = INTERIM / "biology.parquet"
CELL_COLUMNS = ["bio_records", "bio_types"]

# BioSample attributes kept for auditing (design 3.3), besides lat_lon.
AUDIT_ATTRS = ("env_broad_scale", "isolation_source", "geo_loc_name")
BIOSAMPLE_URL = "https://www.ncbi.nlm.nih.gov/biosample"
RETRY_WAIT_S = 2.0  # grows x2 on each retry (design 7.5)


# --- Search terms ------------------------------------------------------------


def _quote(term: str) -> str:
    """Phrases go between double quotes; single words stay as they are."""
    return f'"{term}"' if " " in term.strip() else term.strip()


def build_query(shared: str, search_by: str, terms: list[str]) -> str:
    """Entrez query of one type: the shared filter AND the terms joined with OR.

    `environment` terms are searched in all fields; `organism` terms in [Organism].
    """
    if search_by == "organism":
        body = " OR ".join(f"{_quote(t)}[Organism]" for t in terms)
    else:
        body = " OR ".join(_quote(t) for t in terms)
    return f"({shared}) AND ({body})" if shared.strip() else f"({body})"


# --- NCBI --------------------------------------------------------------------


class Ncbi:
    """Thin Biopython wrapper: pauses between requests and retries network errors."""

    def __init__(self, email: str, api_key: str | None, sleep=time.sleep):
        from Bio import Entrez  # imported here so tests and --manual do not need Biopython

        Entrez.email = email
        Entrez.api_key = api_key or None
        self._entrez = Entrez
        self._sleep = sleep
        self.delay = NCBI_DELAY_WITH_KEY_S if api_key else NCBI_DELAY_NO_KEY_S

    def _call(self, fn, **kwargs):
        wait = RETRY_WAIT_S
        for attempt in range(NCBI_MAX_RETRIES + 1):
            try:
                handle = fn(**kwargs)
                data = handle.read()
                handle.close()
                self._sleep(self.delay)
                return data
            except Exception:  # urllib / HTTP / RuntimeError from Biopython
                if attempt == NCBI_MAX_RETRIES:
                    raise
                self._sleep(wait)
                wait *= 2

    def search(self, query: str) -> tuple[int, str, str]:
        """(total, WebEnv, QueryKey) of a BioSample search, keeping the result session."""
        data = self._call(self._entrez.esearch, db="biosample", term=query, usehistory="y", retmax=0)
        found = self._entrez.read(io.BytesIO(data))
        return int(found["Count"]), found["WebEnv"], found["QueryKey"]

    def fetch(self, webenv: str, query_key: str, start: int, n: int) -> bytes:
        """One batch of `n` records as BioSample XML."""
        return self._call(
            self._entrez.efetch,
            db="biosample",
            query_key=query_key,
            WebEnv=webenv,
            retstart=start,
            retmax=n,
            retmode="xml",
        )


def download_type(ncbi, extremophile_type: str, query: str, raw_dir: Path, max_records: int, log) -> tuple[int, list[Path]]:
    """Download up to `max_records` of one type in batches of NCBI_BATCH.

    Returns (total in NCBI, raw batch files). A batch already on disk is not
    requested again, so an interrupted run continues where it stopped.
    """
    raw_dir.mkdir(parents=True, exist_ok=True)
    total, webenv, query_key = ncbi.search(query)
    wanted = min(total, max_records)
    files: list[Path] = []
    for start in range(0, wanted, NCBI_BATCH):
        path = raw_dir / f"{extremophile_type}_{start}.xml"
        if not path.exists():
            data = ncbi.fetch(webenv, query_key, start, min(NCBI_BATCH, wanted - start))
            part = path.with_suffix(".xml.part")
            part.write_bytes(data)
            part.replace(path)
            log.info("%s: %d/%d", extremophile_type, min(start + NCBI_BATCH, wanted), wanted)
        files.append(path)
    return total, files


# --- Parsing -----------------------------------------------------------------


def parse_biosample_xml(data: bytes) -> list[dict]:
    """Samples of one efetch XML: accession, organism, lat_lon and the audit attributes."""
    root = ET.fromstring(data)
    out = []
    for bs in root.iter("BioSample"):
        accession = bs.get("accession")
        if not accession:
            continue
        org = bs.find(".//Organism")
        organism = None
        if org is not None:
            organism = org.get("taxonomy_name") or org.findtext("OrganismName")
        row = {"accession": accession, "organism": organism, "lat_lon": None}
        row.update(dict.fromkeys(AUDIT_ATTRS))
        for attr in bs.iter("Attribute"):
            for key in (attr.get("harmonized_name"), attr.get("attribute_name")):
                if key in row and key != "accession" and key != "organism" and row[key] is None:
                    text = (attr.text or "").strip()
                    row[key] = text or None
        out.append(row)
    return out


def read_batches(files: list[Path]) -> pd.DataFrame:
    rows = [r for f in files for r in parse_biosample_xml(Path(f).read_bytes())]
    cols = ["accession", "organism", "lat_lon", *AUDIT_ATTRS]
    return pd.DataFrame(rows, columns=cols)


# --- Coordinates and cells ---------------------------------------------------


def with_coordinates(raw: pd.DataFrame) -> pd.DataFrame:
    """Keeps the samples whose lat_lon is valid (design 7.4) and adds float lat and lon."""
    parsed = raw["lat_lon"].map(parse_lat_lon)
    ok = parsed.notna()
    out = raw.loc[ok].copy()
    out["lat"] = [p[0] for p in parsed[ok]]
    out["lon"] = [p[1] for p in parsed[ok]]
    return out.drop(columns="lat_lon").reset_index(drop=True)


def assign_cells(samples: pd.DataFrame, grid_ids) -> pd.DataFrame:
    """Adds cell_id and keeps the samples that fall on a land cell of the grid."""
    if samples.empty:
        return samples.assign(cell_id=pd.Series(dtype="int32"))
    cid = geo.cell_id_of(samples["lat"].to_numpy(), samples["lon"].to_numpy())
    out = samples.assign(cell_id=cid)
    return out[out["cell_id"].isin(pd.Index(grid_ids))].reset_index(drop=True)


def read_manual(path: Path) -> pd.DataFrame:
    """Plan B: config/bio_manual.csv with lat, lon, extremophile_type, source."""
    require_inputs([path])
    df = pd.read_csv(path)
    missing = {"lat", "lon", "extremophile_type", "source"} - set(df.columns)
    if missing:
        raise MissingInputError(f"{path}: missing columns {sorted(missing)}")
    unknown = sorted(set(df["extremophile_type"]) - set(BIO_TYPES))
    if unknown:
        raise MissingInputError(f"{path}: unknown types {unknown}; valid: {list(BIO_TYPES)}")
    df = df.reset_index(drop=True)
    return pd.DataFrame(
        {
            "accession": [f"MANUAL-{i + 1:04d}" for i in range(len(df))],
            "extremophile_type": df["extremophile_type"],
            "organism": None,
            "lat_lon": [f"{a} {b}" for a, b in zip(df["lat"], df["lon"])],
            "env_broad_scale": None,
            "isolation_source": df["source"],
            "geo_loc_name": None,
        }
    )


# --- Outputs -----------------------------------------------------------------


def samples_table(df: pd.DataFrame) -> pd.DataFrame:
    """bio_samples.parquet (contract 3.3): one row per accession and type."""
    df = df.drop_duplicates(["accession", "extremophile_type"])
    out = pd.DataFrame(
        {
            "accession": df["accession"].astype("string"),
            "extremophile_type": df["extremophile_type"].astype("string"),
            "organism": df["organism"].astype("string"),
            "lat": df["lat"].astype("float32"),
            "lon": df["lon"].astype("float32"),
            "cell_id": df["cell_id"].astype("int32"),
            "env_broad_scale": df["env_broad_scale"].astype("string"),
            "isolation_source": df["isolation_source"].astype("string"),
            "geo_loc_name": df["geo_loc_name"].astype("string"),
        }
    )
    return out.sort_values(["extremophile_type", "accession"]).reset_index(drop=True)


def cells_table(samples: pd.DataFrame, grid_ids) -> pd.DataFrame:
    """interim/biology.parquet: every grid cell with bio_records (unique samples),
    bio_types (distinct types) and bio_type_list (types in BIO_TYPES order)."""
    cells = pd.DataFrame({"cell_id": np.asarray(grid_ids, dtype="int32")})
    if samples.empty:
        counts = pd.DataFrame(columns=["cell_id", "bio_records", "bio_types", "bio_type_list"])
    else:
        records = samples.groupby("cell_id")["accession"].nunique().rename("bio_records")
        types = samples.groupby("cell_id")["extremophile_type"].agg(lambda s: set(s))
        counts = pd.DataFrame(
            {
                "bio_records": records,
                "bio_types": types.map(len),
                "bio_type_list": types.map(lambda s: ",".join(t for t in BIO_TYPES if t in s)),
            }
        ).reset_index()
    out = cells.merge(counts, on="cell_id", how="left")
    return pd.DataFrame(
        {
            "cell_id": out["cell_id"].astype("int32"),
            "bio_records": out["bio_records"].fillna(0).astype("int32"),
            "bio_types": out["bio_types"].fillna(0).astype("int8"),
            "bio_type_list": out["bio_type_list"].fillna("").astype("string"),
        }
    )


# --- Step --------------------------------------------------------------------


def _env(name: str) -> str | None:
    return (os.environ.get(name) or "").strip() or None


def main() -> None:
    parser = make_parser(STEP, __doc__.splitlines()[0])
    parser.add_argument("--type", dest="types", action="append", choices=BIO_TYPES,
                        help="only this extremophile type (repeat for several); partial output")
    parser.add_argument("--max-records", type=int, default=BIO_MAX_RECORDS_PER_TYPE,
                        help=f"records per type (default {BIO_MAX_RECORDS_PER_TYPE}); fewer gives a partial output")
    parser.add_argument("--manual", action="store_true",
                        help="plan B: read config/bio_manual.csv instead of NCBI (no network)")
    args = parser.parse_args()
    log = setup_logging(STEP)
    started = time.monotonic()

    require_inputs([GRID_PATH, TERMS_PATH])
    terms = BioTermsFile.model_validate_json(TERMS_PATH.read_text(encoding="utf-8"))
    selected = [t for t in terms.types if not args.types or t.extremophile_type in args.types]

    partial = []
    if args.bbox:
        partial.append(bbox_note(args.bbox))
    if args.types:
        partial.append(f"{PARTIAL_NOTE_PREFIX} --type {' '.join(args.types)}")
    if args.max_records < BIO_MAX_RECORDS_PER_TYPE and not args.manual:
        partial.append(f"{PARTIAL_NOTE_PREFIX} --max-records {args.max_records}")

    inputs_for_freshness = [TERMS_PATH, GRID_PATH, Path(__file__), ROOT / "tai" / "latlon.py"]
    if args.manual:
        inputs_for_freshness.append(MANUAL_PATH)
    if (
        not args.force
        and not partial
        and is_up_to_date([SAMPLES_OUT, CELLS_OUT], inputs_for_freshness)
        and not last_run_partial(STEP)
    ):
        log.info("up to date")
        return

    grid = load_grid()
    stats: dict[str, dict] = {}
    frames = []
    raw_files: list[Path] = []

    if args.manual:
        raw = read_manual(MANUAL_PATH)
        for t, g in raw.groupby("extremophile_type"):
            stats[t] = {"total": len(g), "downloaded": len(g)}
        frames_in = [(t, g) for t, g in raw.groupby("extremophile_type")]
    else:
        email = _env("NCBI_EMAIL")
        if not email:
            raise MissingInputError("the NCBI_EMAIL environment variable is missing (see README, 'Environment variables')")
        ncbi = Ncbi(email, _env("NCBI_API_KEY"))
        if not _env("NCBI_API_KEY"):
            log.warning("no NCBI_API_KEY: %.1f s between requests", ncbi.delay)
        frames_in = []
        for t in selected:
            query = build_query(terms.shared, t.search_by, t.terms)
            log.info("%s: %s", t.extremophile_type, query)
            total, files = download_type(ncbi, t.extremophile_type, query, RAW_DIR, args.max_records, log)
            raw_files += files
            got = read_batches(files)
            stats[t.extremophile_type] = {"total": total, "downloaded": len(got)}
            frames_in.append((t.extremophile_type, got))

    for t, got in frames_in:
        coords = with_coordinates(got)
        if args.bbox:
            coords = coords[bbox_mask(coords["lat"], coords["lon"], args.bbox).to_numpy()]
        on_land = assign_cells(coords, grid["cell_id"])
        stats[t]["with_coords"] = len(coords)
        stats[t]["on_land"] = len(on_land)
        frames.append(on_land.assign(extremophile_type=t))

    samples = samples_table(pd.concat(frames, ignore_index=True)) if frames else samples_table(
        pd.DataFrame(columns=["accession", "extremophile_type", "organism", "lat", "lon", "cell_id",
                              "env_broad_scale", "isolation_source", "geo_loc_name"]))
    cells = cells_table(samples, grid["cell_id"])

    validate_output(samples, grid_ids=grid["cell_id"], schema="bio_samples")
    validate_output(cells, grid_ids=grid["cell_id"])

    empty = [t for t in BIO_TYPES if t not in set(samples["extremophile_type"])]
    if cells["bio_records"].max() == 0:
        log.warning("bio_records is 0 across the whole grid: bio_score will be 0 (design 5.5)")
    elif empty and not partial:
        log.warning("no records on land for: %s (the ticket asks for all 6 types)", ", ".join(empty))

    notes = [
        f"{t}: total in NCBI {s['total']}, downloaded {s['downloaded']}, with coordinates {s['with_coords']}, "
        f"on land {s['on_land']}"
        for t, s in stats.items()
    ]
    notes.append(f"unique samples on land: {samples['accession'].nunique()} in {int((cells['bio_records'] > 0).sum())} cells")
    if args.manual:
        notes.append("plan B: data from config/bio_manual.csv (literature), not from NCBI")
    capped = [t for t, s in stats.items() if s["total"] > args.max_records]
    if capped and not args.manual:
        notes.append(f"cap of {args.max_records} records per type reached for: {', '.join(capped)} (design 7.6)")
    notes += partial
    for line in notes:
        log.info(line)

    atomic_write_parquet(samples, SAMPLES_OUT)
    atomic_write_parquet(cells, CELLS_OUT)
    write_step_manifest(
        step_entry(
            STEP,
            started,
            inputs=[
                {
                    "name": "Literature (config/bio_manual.csv)" if args.manual else "NCBI BioSample",
                    "product": "bio_manual.csv" if args.manual else "BioSample (Entrez esearch/efetch)",
                    "portal": "Santino" if args.manual else "NCBI",
                    "url": BIOSAMPLE_URL,
                    "files": 1 if args.manual else len(raw_files),
                    "size_mb": file_size_mb(MANUAL_PATH) if args.manual else round(sum(file_size_mb(f) for f in raw_files), 1),
                    "license_note": "Literature citations" if args.manual else "NCBI public data",
                }
            ],
            outputs=[(SAMPLES_OUT, len(samples)), (CELLS_OUT, len(cells))],
            columns=column_stats(cells, CELL_COLUMNS),
            notes=notes,
        )
    )
    log.info("wrote %s (%d rows) and %s (%d cells)", SAMPLES_OUT.name, len(samples), CELLS_OUT.name, len(cells))


if __name__ == "__main__":
    run(main)
