"""The ranking table, shared by the view (ui/ranking_view.py) and the CSV download (TAI-50).

RF-34 requires the CSV to carry the same rows and columns as the table: both come from here.
"""

from __future__ import annotations

import pandas as pd

from tai.models import Ranking

# RankingItem field -> column name in the interface
COLUMNS = {
    "rank": "Rank",
    "lat": "Lat",
    "lon": "Lon",
    "country": "Country",
    "total": "Total",
    "s_terrain": "Terrain",
    "s_temperature": "Temperature",
    "s_water_ice": "Water and ice",
    "s_dust_wind": "Dust and wind",
    "bio_score": "Astrobiology",
    "known_analog": "Known analog",
}
SCORE_COLUMNS = ("Total", "Terrain", "Temperature", "Water and ice", "Dust and wind", "Astrobiology")
OPTIONAL_COLUMNS = ("Dust and wind",)  # hidden if the target lacks the dimension (the Moon)
_SCORE_FIELDS = ("total", "s_terrain", "s_temperature", "s_water_ice", "s_dust_wind", "bio_score")


def ranking_table(ranking: Ranking) -> pd.DataFrame:
    """One row per cell, in ranking order, with the interface's column names.

    Null scores stay NaN: the table shows them as "no data"."""
    rows = [item.model_dump() for item in ranking.items]
    df = pd.DataFrame(rows, columns=list(COLUMNS))
    df["known_analog"] = [a["name"] if a else None for a in df["known_analog"]]
    for col in _SCORE_FIELDS:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
    return df.rename(columns=COLUMNS).reset_index(drop=True)


def visible_columns(table: pd.DataFrame) -> list[str]:
    """The columns to show: an optional dimension that is empty across the whole table (dust and wind on the Moon) is hidden."""
    return [c for c in table.columns if not (c in OPTIONAL_COLUMNS and table[c].isna().all())]
