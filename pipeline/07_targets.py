"""Step 07: target profiles of the Moon south pole and Jezero (design 6.1, RF-07, TAI-16).

Reads:  config/targets_base.json          (hand-edited by Santino: names, cuts, has_ice,
                                           limits, literature values and their citations)
        data/raw/07_targets/LDEM_80S_80MPP_ADJ.TIF   LOLA elevation, 80 m, south polar
        data/raw/07_targets/Mars_MGS_MOLA_DEM_mosaic_global_463m.tif   MOLA, 463 m (or its URL)
        data/processed/manifest.json      earth_stats of step 06 (p01, p99 and std of each
                                          Earth variable, weighted by area)
Writes: data/processed/targets.json       six variables per target: mean, std, source,
                                          source type, rule and the earth_* fields

Variables marked `measured` in targets_base.json are read from the elevation
products: the DEM of the cut is brought to 1 km, then slope_from_dem and
local_roughness (the same functions as step 02) give slope_deg and roughness_m,
averaged over the cut. `literature` and `definition` variables take their mean
and std from the file. The scoring rule of each variable comes from
tai.rules.choose_rule (design 5.1), which is TAI-18's.

There is no reader for measured temperature yet: whether the Diviner and MEDA
products are read or taken from the literature is the TAI-05 decision, and a
`measured` temperature stops the step with a message that says so.
"""

import math
import sys
import time
from pathlib import Path

# Steps run as `python pipeline/NN_step.py`; put the repo root on the path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from pipeline.common import (  # noqa: E402
    CONFIG,
    MANIFEST_PATH,
    PROCESSED,
    RAW,
    MissingInputError,
    atomic_write_json,
    file_size_mb,
    is_up_to_date,
    local_roughness,
    make_parser,
    require_inputs,
    run,
    setup_logging,
    slope_from_dem,
    step_entry,
    write_step_manifest,
)
from tai.constants import PHYSICAL_VARS, SCHEMA_VERSION  # noqa: E402
from tai.models import EarthStats, TargetsBaseFile, TargetsFile  # noqa: E402

STEP = "07_targets"
RAW_DIR = RAW / STEP
BASE_PATH = CONFIG / "targets_base.json"
OUTPUT = PROCESSED / "targets.json"
FEATURES_PATH = PROCESSED / "features.parquet"  # step 06; written with earth_stats

MOON_DEM = RAW_DIR / "LDEM_80S_80MPP_ADJ.TIF"
MARS_DEM_NAME = "Mars_MGS_MOLA_DEM_mosaic_global_463m.tif"
MARS_DEM = RAW_DIR / MARS_DEM_NAME
MARS_DEM_URL = "https://planetarymaps.usgs.gov/mosaic/" + MARS_DEM_NAME

MOON_RADIUS_M = 1_737_400.0  # sphere of the LOLA south polar stereographic grid
MARS_M_PER_DEG = 3_396_190.0 * math.pi / 180.0  # MOLA mosaic: equirectangular, radius 3 396 190 m
BASE_RES_M = 1000.0  # design 4.1: slope and roughness at 1 km on all three bodies
TERRAIN_VARS = ("slope_deg", "roughness_m")


# --- Terrain of the cut ------------------------------------------------------


def _stats(slope: np.ndarray, rough: np.ndarray, inside: np.ndarray) -> dict[str, tuple[float, float, int]]:
    """(mean, std, valid pixels) of each terrain variable over the pixels of the cut."""
    out = {}
    for name, grid in (("slope_deg", slope), ("roughness_m", rough)):
        v = grid[inside & np.isfinite(grid)]
        if v.size == 0:
            raise MissingInputError(f"the crop has no valid pixels of {name}")
        out[name] = (float(v.mean()), float(v.std()), int(v.size))
    return out


def polar_colatitude_deg(x: np.ndarray, y: np.ndarray, radius_m: float = MOON_RADIUS_M) -> np.ndarray:
    """Angle from the pole of a polar stereographic point (x, y in meters from the pole)."""
    return np.degrees(2.0 * np.arctan(np.hypot(x, y) / (2.0 * radius_m)))


def lola_cut_stats(path, lat_max: float = -85.0, res_m: float = BASE_RES_M) -> dict[str, tuple[float, float, int]]:
    """slope_deg and roughness_m of the LOLA south polar DEM, south of `lat_max`.

    The 80 m raster is averaged down to `res_m` while it is read (so the
    whole 7600 x 7600 grid is never held at full resolution), then slope and
    roughness are computed at that resolution.
    """
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.transform import Affine

    with rasterio.open(path) as src:
        # Exact output size, so the pixel is res_m (80 m does not divide 1 km evenly).
        h = max(5, round(src.height * abs(src.transform.e) / res_m))
        w = max(5, round(src.width * abs(src.transform.a) / res_m))
        z = src.read(1, out_shape=(h, w), resampling=Resampling.average, masked=True)
        z = np.ma.filled(z.astype("float64"), np.nan)
        tf = src.transform @ Affine.scale(src.width / w, src.height / h)
    dx, dy = abs(tf.a), abs(tf.e)
    cols, rows = np.meshgrid(np.arange(w) + 0.5, np.arange(h) + 0.5)
    x, y = tf.c + cols * tf.a, tf.f + rows * tf.e
    inside = polar_colatitude_deg(x, y) <= 90.0 - abs(lat_max)
    return _stats(slope_from_dem(z, dx, dy), local_roughness(z), inside)


def mola_cut_stats(path, lat_min: float, lat_max: float, lon_min: float, lon_max: float,
                   res_m: float = BASE_RES_M) -> dict[str, tuple[float, float, int]]:
    """slope_deg and roughness_m of the MOLA global DEM inside a lat/lon box (east longitudes).

    Reads only the window of the box, resampled to about `res_m`. The raster is
    equirectangular with x = lon * meters-per-degree and y = lat * meters-per-degree.
    A raster that starts at longitude 0 (0 to 360) wraps negative longitudes.
    """
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.windows import from_bounds

    mid = math.radians((lat_min + lat_max) / 2)
    out_h = max(5, round((lat_max - lat_min) * MARS_M_PER_DEG / res_m))
    out_w = max(5, round((lon_max - lon_min) * MARS_M_PER_DEG * math.cos(mid) / res_m))
    with rasterio.open(path) as src:
        if src.bounds.left >= 0:
            lon_min, lon_max = lon_min % 360, lon_max % 360 or 360
        win = from_bounds(lon_min * MARS_M_PER_DEG, lat_min * MARS_M_PER_DEG,
                          lon_max * MARS_M_PER_DEG, lat_max * MARS_M_PER_DEG, src.transform)
        z = src.read(1, window=win, out_shape=(out_h, out_w), resampling=Resampling.average, masked=True)
        z = np.ma.filled(z.astype("float64"), np.nan)
    lat_rows = lat_max - (np.arange(out_h) + 0.5) * (lat_max - lat_min) / out_h
    dx_rows = (lon_max - lon_min) / out_w * MARS_M_PER_DEG * np.cos(np.radians(lat_rows))
    dy = (lat_max - lat_min) / out_h * MARS_M_PER_DEG
    return _stats(slope_from_dem(z, dx_rows, dy), local_roughness(z), np.ones(z.shape, dtype=bool))


# --- Profiles ----------------------------------------------------------------


def load_earth_stats(path: Path = MANIFEST_PATH) -> dict[str, EarthStats]:
    """p01, p99 and std of each Earth variable, written by step 06 into the manifest."""
    import json

    require_inputs([path])
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    entry = next((s for s in manifest.get("steps", []) if s.get("step") == "06_features"), None)
    stats = (entry or {}).get("earth_stats")
    if not stats:
        raise MissingInputError(
            "earth_stats from step 06 is missing in manifest.json: step 06_features.py (TAI-18) has not run yet"
        )
    missing = [v for v in PHYSICAL_VARS if v not in stats]
    if missing:
        raise MissingInputError(f"earth_stats from step 06 lacks {missing}")
    return {v: EarthStats.model_validate(stats[v]) for v in PHYSICAL_VARS}


def build_targets(base: TargetsBaseFile, measured: dict, earth: dict, choose_rule) -> TargetsFile:
    """targets.json from the hand-edited base, the measured terrain and the Earth statistics.

    measured: target_id -> {variable: (mean, std, pixels)} for the `measured` variables.
    earth: variable -> EarthStats.
    choose_rule(variable, mean, earth_p01, earth_p99, has_ice) -> rule of design 5.1.
    """
    targets = []
    for t in base.targets:
        out_vars = {}
        for var in PHYSICAL_VARS:
            if var not in t.vars:  # optional variable the target does not have (dust and wind on the Moon)
                continue
            bv = t.vars[var]
            if bv.source_type == "measured":
                if var not in TERRAIN_VARS:
                    raise MissingInputError(
                        f"{t.target_id}.{var} is marked measured, but there is no temperature reader: "
                        "the decision belongs to TAI-05; meanwhile, mark it literature with its citation"
                    )
                got = measured.get(t.target_id, {}).get(var)
                if got is None:
                    raise MissingInputError(f"{t.target_id}.{var} is marked measured and the product was not read")
                mean, std = got[0], got[1]
            else:
                mean, std = bv.mean, bv.std
            e = earth[var]
            out_vars[var] = {
                "mean": mean, "std": std, "unit": bv.unit,
                "rule": choose_rule(var, mean, e.p01, e.p99, t.has_ice),
                "source": bv.source, "source_type": bv.source_type,
                "earth_p01": e.p01, "earth_p99": e.p99, "earth_std": e.std,
            }
        targets.append({**t.model_dump(exclude={"vars"}), "vars": out_vars})
    return TargetsFile.model_validate({"schema_version": SCHEMA_VERSION, "targets": targets})


def measure_terrain(base: TargetsBaseFile, moon_dem, mars_dem, log) -> tuple[dict, list[Path]]:
    """Reads the elevation product of each target that has a measured terrain variable."""
    measured: dict[str, dict] = {}
    used: list[Path] = []
    for t in base.targets:
        wanted = [v for v in TERRAIN_VARS if t.vars[v].source_type == "measured"]
        if not wanted:
            continue
        b = t.bounds
        if t.body == "moon":
            require_inputs([moon_dem])
            log.info("%s: LOLA %s", t.target_id, Path(moon_dem).name)
            measured[t.target_id] = lola_cut_stats(moon_dem, lat_max=b.lat_max)
            used.append(Path(moon_dem))
        else:
            if not str(mars_dem).startswith("http"):
                require_inputs([mars_dem])
                used.append(Path(mars_dem))
            log.info("%s: MOLA %s", t.target_id, mars_dem)
            measured[t.target_id] = mola_cut_stats(mars_dem, b.lat_min, b.lat_max, b.lon_min, b.lon_max)
        for v in wanted:
            m, s, n = measured[t.target_id][v]
            log.info("%s.%s: mean %.2f, std %.2f, %d pixels", t.target_id, v, m, s, n)
    return measured, used


# --- Step --------------------------------------------------------------------


def main() -> None:
    parser = make_parser(STEP, __doc__.splitlines()[0])
    parser.add_argument("--moon-dem", default=str(MOON_DEM), help="LOLA LDEM_80S_80MPP_ADJ.TIF")
    parser.add_argument("--mars-dem", default=str(MARS_DEM) if MARS_DEM.exists() else MARS_DEM_URL,
                        help="MOLA global DEM, local file or URL (default: the local file if present, else the USGS URL)")
    args = parser.parse_args()
    log = setup_logging(STEP)
    started = time.monotonic()

    require_inputs([BASE_PATH])
    # earth_stats lives in the manifest, which every step (this one included) rewrites,
    # so freshness follows features.parquet: step 06 writes it together with earth_stats.
    root = Path(__file__).resolve().parents[1]
    freshness = [BASE_PATH, FEATURES_PATH, Path(__file__), root / "tai" / "rules.py"]
    freshness += [Path(p) for p in (args.moon_dem, args.mars_dem) if not str(p).startswith("http")]
    if not args.force and is_up_to_date([OUTPUT], freshness):
        log.info("up to date")
        return

    try:
        from tai import rules
        choose_rule = rules.choose_rule
    except (ImportError, AttributeError) as exc:
        raise MissingInputError("tai.rules.choose_rule is missing (TAI-18, Juanma's)") from exc

    base = TargetsBaseFile.model_validate_json(BASE_PATH.read_text(encoding="utf-8"))
    earth = load_earth_stats()
    measured, used = measure_terrain(base, args.moon_dem, args.mars_dem, log)
    targets = build_targets(base, measured, earth, choose_rule)

    atomic_write_json(targets.model_dump(mode="json"), OUTPUT)
    notes = [
        f"{t.target_id}.{v}: {t.vars[v].source_type}, rule {t.vars[v].rule}"
        for t in targets.targets for v in PHYSICAL_VARS if v in t.vars
    ]
    for line in notes:
        log.info(line)
    write_step_manifest(
        step_entry(
            STEP,
            started,
            inputs=[
                {"name": "Elevation of the Moon and Mars (LOLA and MOLA)", "product": "LDEM_80S_80MPP_ADJ, MOLA 463 m",
                 "portal": "NASA PGDA and USGS Astrogeology", "url": "https://pgda.gsfc.nasa.gov/products/90",
                 "files": len(used), "size_mb": round(sum(file_size_mb(p) for p in used), 1),
                 "license_note": "NASA open data"},
            ],
            outputs=[(OUTPUT, len(targets.targets))],
            columns={},
            notes=notes,
        )
    )
    log.info("wrote %s (%d targets)", OUTPUT.name, len(targets.targets))


if __name__ == "__main__":
    run(main)
