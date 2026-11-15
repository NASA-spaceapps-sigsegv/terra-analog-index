"""La tabla del ranking, compartida por la vista (ui/ranking_view.py) y la descarga en CSV (TAI-50).

RF-34 pide que el CSV traiga las mismas filas y columnas que la tabla: las dos salen de acá.
"""

from __future__ import annotations

import pandas as pd

from tai.models import Ranking

# campo de RankingItem -> nombre de la columna en la interfaz
COLUMNS = {
    "rank": "Puesto",
    "lat": "Lat",
    "lon": "Lon",
    "country": "País",
    "total": "Total",
    "s_terrain": "Terreno",
    "s_temperature": "Temperatura",
    "s_water_ice": "Agua y hielo",
    "s_dust_wind": "Polvo y viento",
    "bio_score": "Astrobiología",
    "known_analog": "Análogo conocido",
}
SCORE_COLUMNS = ("Total", "Terreno", "Temperatura", "Agua y hielo", "Polvo y viento", "Astrobiología")
OPTIONAL_COLUMNS = ("Polvo y viento",)  # se ocultan si el objetivo no tiene la dimensión (la Luna)
_SCORE_FIELDS = ("total", "s_terrain", "s_temperature", "s_water_ice", "s_dust_wind", "bio_score")


def ranking_table(ranking: Ranking) -> pd.DataFrame:
    """Una fila por celda, en el orden del ranking, con los nombres de columna de la interfaz.

    Los puntajes nulos quedan como NaN: la tabla los muestra como "sin dato"."""
    rows = [item.model_dump() for item in ranking.items]
    df = pd.DataFrame(rows, columns=list(COLUMNS))
    df["known_analog"] = [a["name"] if a else None for a in df["known_analog"]]
    for col in _SCORE_FIELDS:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
    return df.rename(columns=COLUMNS).reset_index(drop=True)


def visible_columns(table: pd.DataFrame) -> list[str]:
    """Las columnas a mostrar: una dimensión opcional vacía en toda la tabla (polvo y viento en la Luna) se oculta."""
    return [c for c in table.columns if not (c in OPTIONAL_COLUMNS and table[c].isna().all())]
