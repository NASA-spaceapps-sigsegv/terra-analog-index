# Terra Analog Index

Índice de lugares de la Tierra análogos al polo sur lunar y al cráter Jezero (NASA Space Apps 2026).

El proyecto tiene dos mitades que no se mezclan:

- **Pipeline** (`pipeline/`): corre en las laptops del equipo. Descarga, calcula y escribe `data/processed/`.
- **App** (`streamlit_app.py`, `ui/`): solo lee `data/processed/` y combina puntajes con los pesos que elige el visitante.

El código compartido vive en `tai/` (sin Streamlit, sin red, sin escribir archivos).

## Instalación

Python 3.11 o más nuevo.

```bash
python -m venv .venv
```

```bash
source .venv/bin/activate
```

Solo la app:

```bash
pip install -r requirements.txt
```

Pipeline y pruebas (incluye la app):

```bash
pip install -r requirements-pipeline.txt
```

En Windows, si `rasterio` o `geopandas` fallan con pip, instalarlos con conda.

## Uso

Datos crudos que faltan (Natural Earth y elevación, ~1,6 GB; los ya bajados se saltean y una descarga cortada se retoma). `make help` lista los objetivos:

```bash
make data
```

En Windows, `make` se corre desde Git Bash o WSL; si no, los mismos comandos `curl` están en `data/raw/README.md`.

Mapas de control de los pasos 01 a 04 (TAI-24): genera un mapa por variable, histogramas, `index.html` e `informe.md` en `data/interim/maps/`, y al final imprime la ruta para abrir el índice en el navegador. Otras opciones del script van en `MAPS_ARGS`, por ejemplo `make maps MAPS_ARGS="--only terrain"`:

```bash
make maps
```

Pruebas:

```bash
pytest
```

Un paso del pipeline (`--force` lo ejecuta aunque esté al día; `--bbox` limita a una región):

```bash
python pipeline/01_grid.py --help
```

App:

```bash
streamlit run streamlit_app.py
```

## Estructura

| Carpeta | Contenido |
| --- | --- |
| `tai/` | Núcleo: constantes, geometría de la grilla, modelos de los contratos, reglas, puntaje |
| `pipeline/` | Pasos `01_grid.py` a `09_validation.py` y utilidades en `common.py` |
| `ui/` | Vistas de Streamlit |
| `config/` | Archivos que se editan a mano: objetivos, análogos conocidos, términos de NCBI |
| `content/` | Texto manual de fichas y de la pestaña Método |
| `data/raw/` | Descargas originales (fuera del repositorio; ver `data/raw/README.md`) |
| `data/interim/` | Un archivo por dimensión (fuera del repositorio) |
| `data/processed/` | Los archivos que lee la app (en el repositorio) |
| `tests/` | Pruebas con pytest; `tests/fixtures/` tiene un archivo de ejemplo por contrato |

Los fixtures de Parquet se regeneran con:

```bash
python tests/fixtures/make_fixtures.py
```

## Variables de entorno

El paso 05 lee `NCBI_EMAIL` (obligatoria) y `NCBI_API_KEY` (opcional). Ninguna va al repositorio: usar un `.env` local, que ya está ignorado.

## Flujo de trabajo

Una rama por ticket (`tai-12-terrain`), creada desde `develop`. Al terminar, con `pytest` en verde, se integra directo a `develop` (sin pull request):

```bash
git checkout develop && git pull && git merge tai-12-terrain && git push
```

Commits con [Conventional Commits](https://www.conventionalcommits.org/).
