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
ROUGHNESS_WINDOW_PX = 5  # assumption A8: moving window side, in base-resolution pixels
MIN_VALID_FRAC = 0.25  # assumption A9: valid land pixels a cell needs to get a value
DATA_YEAR = 2024  # assumption: year of the Earth data (IMERG Final ends at 2025-09)

# --- Scoring (design 5) ------------------------------------------------------
SIGMA_FLOOR_FRAC = 0.10  # overlap rule: sigma floor as a fraction of Earth std
SIMILAR_MIN = 0.70  # a dimension at or above this "looks alike"
DIFFERENT_MAX = 0.30  # a dimension below this "differs"
MIN_PHYSICAL_DIMS = 2  # core physical dimensions with data needed to be eligible

# --- Dimensions and variables (design 4) -------------------------------------
# Core dimensions apply to every target and decide eligibility (design 5.7). Optional ones apply only to
# the targets that define their variables: dust and wind (TAI-52) needs an atmosphere, so the Moon has none.
CORE_DIMENSIONS = ("terrain", "temperature", "water_ice")
OPTIONAL_DIMENSIONS = ("dust_wind",)
PHYSICAL_DIMENSIONS = CORE_DIMENSIONS + OPTIONAL_DIMENSIONS
DIMENSIONS = PHYSICAL_DIMENSIONS + ("biology",)

DIMENSION_VARS = MappingProxyType(
    {
        "terrain": ("slope_deg", "roughness_m"),
        "temperature": ("tmin_c", "trange_c"),
        "water_ice": ("precip_mm", "ice_frac"),
        "dust_wind": ("dust_aod", "wind_ms"),
    }
)
PHYSICAL_VARS = tuple(v for dim in PHYSICAL_DIMENSIONS for v in DIMENSION_VARS[dim])
CORE_VARS = tuple(v for dim in CORE_DIMENSIONS for v in DIMENSION_VARS[dim])  # every target has these six
OPTIONAL_VARS = tuple(v for dim in OPTIONAL_DIMENSIONS for v in DIMENSION_VARS[dim])

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
        "dust_aod": (0.0, None),  # dust optical depth at 550 nm (MERRA-2 DUEXTTAU)
        "wind_ms": (0.0, None),  # surface wind speed, m/s (MERRA-2 SPEED)
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
    {"terrain": 1.0, "temperature": 1.0, "water_ice": 1.0, "dust_wind": 0.5, "biology": 0.5}
)  # assumption; dust_wind (TAI-52) at 0.5 keeps the finalist texts of TAI-33 in the top 20
WEIGHT_STEP = 0.05

# --- Targets (design 2.2) ----------------------------------------------------
TARGET_IDS = ("moon_south_pole", "mars_jezero")
BODIES = ("moon", "mars")

# --- UI ----------------------------------------------------------------------
TOP_N = 20
CSV_TOP_N = 2000  # rows in the long CSV download, built only when its button is clicked
RANKING_LIMIT_MAX = CSV_TOP_N

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
