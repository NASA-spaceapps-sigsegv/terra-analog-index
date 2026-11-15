"""Cuevas y tubos de lava (TAI-53): en qué celda cae cada una. Sin Streamlit.

Son una capa informativa: no entran en ningún puntaje. Una cueva se asocia a la celda de 1° que contiene
su punto. Las que están en islas chicas (Lanzarote, Jeju, la isla de Ross) no tienen celda: a esa
resolución la máscara de tierra no incluye la isla, y la celda de tierra más cercana queda a 90 km o más,
así que no se busca una "parecida".
"""

from __future__ import annotations

from collections.abc import Container, Sequence

from tai import geo
from tai.models import Cave

CAVE_KINDS = {"lava_tube": "Tubo de lava", "ice_cave": "Cueva de hielo"}
NO_CELL = "Sin celda: la grilla de 1° no incluye esta isla"


def cell_of(cave: Cave, grid_cells: Container[int]) -> int | None:
    """La celda que contiene la cueva, o None si esa celda no está en la grilla."""
    cell_id = int(geo.cell_id_of(cave.lat, cave.lon))
    return cell_id if cell_id in grid_cells else None


def caves_in_cell(caves: Sequence[Cave], cell_id: int, grid_cells: Container[int]) -> list[Cave]:
    """Las cuevas que caen en `cell_id`, en el orden del archivo."""
    return [c for c in caves if cell_of(c, grid_cells) == cell_id]
