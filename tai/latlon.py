"""Parser for the NCBI BioSample lat_lon attribute (design 7.4, TAI-15).

The usual format is "24.08 S 69.92 W". Two signed decimals separated by a
comma or a space ("-24.08 -69.92") are also accepted. S and W give negative
values. It reads no files and does not use the network.
"""

import math
import re

_HEMISPHERES = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([NS])[,\s]+(\d+(?:\.\d+)?)\s*([EW])\s*$")
_SIGNED = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?)\s*[,\s]\s*([+-]?\d+(?:\.\d+)?)\s*$")

# Values BioSample uses for "no data" (compared in lowercase).
MISSING = frozenset(
    {"", "missing", "not collected", "not applicable", "na", "n/a", "not provided", "unknown", "none"}
)


def parse_lat_lon(value) -> tuple[float, float] | None:
    """(lat, lon) in decimal degrees, or None if the value is unusable.

    Discarded: empty and missing, not collected, not applicable, NA; unknown
    formats; latitudes outside -90 to 90; longitudes outside -180 to 180;
    and the exact pair (0, 0), which is the default value of many forms.
    """
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    text = str(value).strip()
    if text.lower() in MISSING:
        return None

    m = _HEMISPHERES.match(text)
    if m:
        lat = float(m.group(1)) * (-1 if m.group(2) == "S" else 1)
        lon = float(m.group(3)) * (-1 if m.group(4) == "W" else 1)
    else:
        m = _SIGNED.match(text)
        if not m:
            return None
        lat, lon = float(m.group(1)), float(m.group(2))

    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    if lat == 0 and lon == 0:
        return None
    return lat, lon
