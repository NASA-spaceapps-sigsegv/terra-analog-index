"""Single source of parameters for the pipeline, the app and the tests.

Values come from the design document, section 1.1. Values marked "assumption"
are provisional (design section 13) and may change after team review.
"""

from types import MappingProxyType

# --- Grid (design 2.1) -------------------------------------------------------
GRID_RES_DEG = 1.0
N_LAT = 180
N_LON = 360
N_CELLS_GLOBAL = N_LAT * N_LON  # cell_id range is 0 .. 64799
LAND_FRAC_MIN = 0.5
EARTH_RADIUS_KM = 6371.0088

# --- Data processing ---------------------------------------------------------
TERRAIN_BASE_RES_KM = 1.0  # resolution for slope/roughness on all three bodies
DATA_YEAR = 2025  # assumption: year of the monthly Earth data

# --- Scoring (design 5) ------------------------------------------------------
SIGMA_FLOOR_FRAC = 0.10  # overlap rule: sigma floor as a fraction of Earth std
SIMILAR_MIN = 0.70  # a dimension at or above this "looks alike"
DIFFERENT_MAX = 0.30  # a dimension below this "differs"
MIN_PHYSICAL_DIMS = 2  # physical dimensions with data needed to be eligible

# --- Dimensions and variables (design 4) -------------------------------------
PHYSICAL_DIMENSIONS = ("terrain", "temperature", "water_ice")
DIMENSIONS = PHYSICAL_DIMENSIONS + ("biology",)

DIMENSION_VARS = MappingProxyType(
    {
        "terrain": ("slope_deg", "roughness_m"),
        "temperature": ("tmin_c", "trange_c"),
        "water_ice": ("precip_mm", "ice_frac"),
    }
)
PHYSICAL_VARS = tuple(v for dim in PHYSICAL_DIMENSIONS for v in DIMENSION_VARS[dim])

# Valid ranges (design 3.3). None means unbounded on that side.
# Out-of-range values make the producing step fail without writing output.
VALID_RANGES = MappingProxyType(
    {
        "slope_deg": (0.0, 90.0),
        "roughness_m": (0.0, None),
        "tmin_c": (-95.0, 45.0),
        "trange_c": (0.0, None),
        "precip_mm": (0.0, None),
        "ice_frac": (0.0, 1.0),
        "bio_records": (0, None),
        "bio_types": (0, 6),
        "area_km2": (0.0, None),  # strictly > 0, checked separately
        "land_frac": (LAND_FRAC_MIN, 1.0),
    }
)

RULES = ("overlap", "directional_low", "directional_high", "presence", "absence")
SOURCE_TYPES = ("measured", "literature", "definition")

# --- Weights (design 5.6) ----------------------------------------------------
DEFAULT_WEIGHTS = MappingProxyType(
    {"terrain": 1.0, "temperature": 1.0, "water_ice": 1.0, "biology": 0.5}
)  # assumption
WEIGHT_STEP = 0.05

# --- Targets (design 2.2) ----------------------------------------------------
TARGET_IDS = ("moon_south_pole", "mars_jezero")
BODIES = ("moon", "mars")

# --- UI ----------------------------------------------------------------------
TOP_N = 20
RANKING_LIMIT_MAX = 200

# --- Known analogs and validation --------------------------------------------
KNOWN_ANALOG_RADIUS_KM = 150  # assumption: default radius
COVERED_VALUES = ("yes", "partial", "no")
VALIDATION_PERCENTILE = 90

# --- Biology layer (design 7) ------------------------------------------------
BIO_TYPES = (
    "halophile",
    "psychrophile",
    "xerophile",
    "acidophile",
    "thermophile",
    "radioresistant",
)
BIO_MAX_RECORDS_PER_TYPE = 5000
NCBI_BATCH = 200
NCBI_DELAY_NO_KEY_S = 0.4
NCBI_DELAY_WITH_KEY_S = 0.12
NCBI_MAX_RETRIES = 3

# --- Output formatting (design 3.2) ------------------------------------------
SCORE_DECIMALS_FILE = 3
SCORE_DECIMALS_UI = 2
MAX_PROCESSED_MB = 50

SCHEMA_VERSION = 1
