"""Caves and lava tubes (TAI-53): which cell each one falls in. No Streamlit.

They are an informational layer: they do not enter any score. A cave is tied to the 1° cell that contains
its point. Those on small islands (Lanzarote, Jeju, Ross Island) have no cell: at that resolution the
land mask does not include the island, and the nearest land cell is 90 km or more away, so no "similar"
one is looked for.
"""

from __future__ import annotations

from collections.abc import Container, Sequence

from tai import geo
from tai.models import Cave

CAVE_KINDS = {"lava_tube": "Lava tube", "ice_cave": "Ice cave"}
NO_CELL = "No cell: the 1° grid does not include this island"


def cell_of(cave: Cave, grid_cells: Container[int]) -> int | None:
    """The cell that contains the cave, or None if that cell is not in the grid."""
    cell_id = int(geo.cell_id_of(cave.lat, cave.lon))
    return cell_id if cell_id in grid_cells else None


def caves_in_cell(caves: Sequence[Cave], cell_id: int, grid_cells: Container[int]) -> list[Cave]:
    """The caves that fall in `cell_id`, in file order."""
    return [c for c in caves if cell_of(c, grid_cells) == cell_id]
