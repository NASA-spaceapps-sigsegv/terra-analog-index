"""Intérprete del atributo lat_lon de NCBI BioSample (design 7.4, TAI-15).

El formato habitual es "24.08 S 69.92 W". También se aceptan dos decimales
con signo separados por coma o espacio ("-24.08 -69.92"). S y W dan valores
negativos. No lee archivos ni usa la red.
"""

import math
import re

_HEMISPHERES = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([NS])[,\s]+(\d+(?:\.\d+)?)\s*([EW])\s*$")
_SIGNED = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?)\s*[,\s]\s*([+-]?\d+(?:\.\d+)?)\s*$")

# Valores que BioSample usa para "sin dato" (se comparan en minúsculas).
MISSING = frozenset(
    {"", "missing", "not collected", "not applicable", "na", "n/a", "not provided", "unknown", "none"}
)


def parse_lat_lon(value) -> tuple[float, float] | None:
    """(lat, lon) en grados decimales, o None si el valor no sirve.

    Se descartan: vacíos y missing, not collected, not applicable, NA; formatos
    desconocidos; latitudes fuera de -90 a 90; longitudes fuera de -180 a 180;
    y el par exacto (0, 0), que es el valor por defecto de muchos formularios.
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
