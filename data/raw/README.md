# Datos crudos

Las descargas viven en `data/raw/<paso>/` y no se versionan. Este archivo sí: dice qué bajar, de dónde y cuánto pesa.

Todo lo que tiene descarga directa se baja con `make data` desde la raíz (o por paso: `make data-grid`, `make data-terrain`, `make data-earthdata`; `make help` los lista). Los comandos `curl` de abajo son el equivalente a mano.

Los productos terrestres quedaron verificados en TAI-04 contra el catálogo CMR de NASA el 14 de noviembre de 2026 (nombre, versión, meses disponibles y tamaño). Todos los productos mensuales y anuales son del año calendario **2024** (`DATA_YEAR` en `tai/constants.py`): la corrida Final de IMERG termina en septiembre de 2025, así que 2025 no está completo para la precipitación. Los de la Luna y Marte siguen **sin verificar** hasta que TAI-05 complete su tabla.

## Tierra (TAI-04)

| Variable | Paso | Producto | Versión | Resolución | Formato | Cobertura polar | Tamaño (1 año) | Enlace | Decisión |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Polígonos de tierra | 01_grid | Natural Earth `ne_50m_land` | 5.2.0-pre (espejo de GitHub) | 1:50m (vectorial) | shp o geojson | sí (Antártida y Groenlandia) | 1,6 MB | [naturalearthdata.com](https://www.naturalearthdata.com/downloads/50m-physical-vectors/) | Confirmado (TAI-11) |
| Países (nombre en español) | 01_grid | Natural Earth `ne_50m_admin_0_countries`, campo `NAME_ES` | 5.2.0-pre (espejo de GitHub) | 1:50m (vectorial) | shp o geojson | sí | 3,1 MB | [naturalearthdata.com](https://www.naturalearthdata.com/downloads/50m-cultural-vectors/) | Confirmado (TAI-11) |
| Elevación | 02_terrain | ETOPO 2022 `ETOPO_2022_v1_30s_N90W180_surface` | v1 | 30" (~0,93 km) | netCDF | sí (Antártida incluida; fondo marino se descarta con la máscara de tierra) | 1,64 GB | [NOAA NCEI](https://www.ncei.noaa.gov/products/etopo-global-relief-model) | Elegido para TAI-12: global y de dominio público. Alternativa: GMTED2010 mn30 |
| Temperatura superficial (día y noche) | 03_temperature | MODIS/Terra `MOD11C3`, capas `LST_Day_CMG` y `LST_Night_CMG` (K, factor 0,02) | 061 | 0,05° (CMG, 7200 × 3600) | HDF4-EOS, 1 archivo por mes | sí (90° S a 90° N); sin dato diurno en la noche polar | 837 MB (12 archivos de ~70 MB) | [doi:10.5067/MODIS/MOD11C3.061](https://doi.org/10.5067/MODIS/MOD11C3.061) (LP DAAC) | Confirmado: los 12 meses de 2024 están en CMR. Leer HDF4 requiere `pyhdf` (ver abajo) |
| Precipitación | 04_water_ice | GPM IMERG Final mensual `GPM_3IMERGM`, variable `precipitation` (mm/h) | 07 (archivos V07B) | 0,1° (3600 × 1800) | HDF5, 1 archivo por mes | sí (90° S a 90° N); en los polos y sobre hielo la estimación es menos confiable | 214 MB (12 archivos de ~18 MB) | [GES DISC](https://disc.gsfc.nasa.gov/datasets/GPM_3IMERGM_07/summary) | Confirmado para 2024. La corrida Final termina en septiembre de 2025; por eso `DATA_YEAR` pasó de 2025 a 2024 para todos los productos. Se descartó MERRA-2 `M2TMNXFLX` (reanálisis, 2025 completo): cambia observación satelital por modelo justo donde importa, en las zonas más secas |
| Nieve | 04_water_ice | MODIS/Terra `MOD10CM`, capa `Snow_Cover_Monthly_CMG` (% de 0 a 100; valores mayores son banderas) | 61 | 0,05° (CMG, 7200 × 3600) | HDF4-EOS, 1 archivo por mes | sí (90° S a 90° N); sin observación en la noche polar, como prevé la sección 4.3 | 16 MB (12 archivos de ~1,4 MB) | [doi:10.5067/MODIS/MOD10CM.061](https://doi.org/10.5067/MODIS/MOD10CM.061) (NSIDC) | Confirmado: los 12 meses de 2024 están en CMR. Las banderas exactas se revisan al abrir el primer archivo (TAI-14) |
| Cobertura del suelo | 04_water_ice | MODIS/Terra+Aqua `MCD12C1`, capa `Majority_Land_Cover_Type_1` (IGBP; clase 15 = nieve y hielo permanentes) y `Land_Cover_Type_1_Percent` | 061 | 0,05° (CMG, 7200 × 3600) | HDF4-EOS, 1 archivo por año | sí (90° S a 90° N) | 1,2 GB (1 archivo) | [doi:10.5067/MODIS/MCD12C1.061](https://doi.org/10.5067/MODIS/MCD12C1.061) (LP DAAC) | Confirmado: el año 2024 está publicado. `Land_Cover_Type_1_Percent` da directamente la fracción de casquete permanente de la sección 4.1 |

### Paso 01: cómo bajar los archivos

Van en `data/raw/01_grid/` con su nombre original. El paso acepta `.shp` (con sus archivos acompañantes), `.geojson`, `.gpkg` o el `.zip` sin descomprimir.

Desde la página oficial: *Land* (físico) y *Admin 0 – Countries* (cultural), escala 1:50m. Si el sitio está caído, la misma versión en GeoJSON está en el repositorio de Natural Earth en GitHub:

```bash
mkdir -p data/raw/01_grid
```
```bash
curl -L -o data/raw/01_grid/ne_50m_land.geojson https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_land.geojson
```
```bash
curl -L -o data/raw/01_grid/ne_50m_admin_0_countries.geojson https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_countries.geojson
```

Después: `python pipeline/01_grid.py`. Escribe `data/processed/grid.parquet` y `data/interim/land_mask.nc` (la máscara a 0,05° que usan los pasos 02 a 04).

### Paso 02: modelo de elevación

Un solo archivo en `data/raw/02_terrain/`, en latitud y longitud (`.nc`, `.tif`, `.tiff` o `.vrt`). Si el producto viene en mosaicos, unirlos antes con `gdalbuildvrt data/raw/02_terrain/dem.vrt mosaicos/*.tif`.

```bash
mkdir -p data/raw/02_terrain
```
```bash
curl -L -o data/raw/02_terrain/ETOPO_2022_v1_30s_N90W180_surface.nc https://www.ngdc.noaa.gov/thredds/fileServer/global/ETOPO2022/30s/30s_surface_elev_netcdf/ETOPO_2022_v1_30s_N90W180_surface.nc
```

Después: `python pipeline/02_terrain.py` (requiere haber corrido el paso 01). Escribe `data/interim/terrain.parquet`. Para probar rápido una región: `--bbox -35 -15 -75 -60`.

### Pasos 03 y 04: productos de Earthdata

Necesitan una cuenta de [NASA Earthdata Login](https://urs.earthdata.nasa.gov/) (TAI-01). El script busca los archivos en CMR y los baja con usuario y contraseña, tomados de `EARTHDATA_USERNAME` y `EARTHDATA_PASSWORD` o de `~/.netrc`:

```
machine urs.earthdata.nasa.gov login <usuario> password <contraseña>
```

Para IMERG, además, hay que autorizar la aplicación *NASA GESDISC DATA ARCHIVE* en el perfil de Earthdata (*Applications → Authorized Apps*); sin eso la descarga devuelve una página web en vez del archivo.

```bash
python pipeline/fetch_earthdata.py --dry-run   # lista archivos y tamaños, sin login
```
```bash
make data-earthdata                            # baja todo 2024 (~2,3 GB); se puede cortar y volver a correr
```

Destinos: `data/raw/03_temperature/` (MOD11C3), `data/raw/04_water_ice/imerg/`, `.../mod10cm/` y `.../mcd12c1/`.

**Lectura de HDF4.** MOD11C3, MOD10CM y MCD12C1 vienen en HDF4. El rasterio instalado con pip trae GDAL sin el driver HDF4, así que no los abre. Por eso `requirements-pipeline.txt` incluye `pyhdf==0.11.7` (tiene rueda para Python 3.14 en Linux, así que `pip install -r requirements-pipeline.txt` alcanza). Con conda, `gdal` de conda-forge también trae HDF4. IMERG (HDF5) y ETOPO (netCDF) se leen con lo que ya está instalado. En el código, `read_hdf4_layer` de `pipeline/common.py` abre cualquier capa y marca como nulos el relleno y lo que cae fuera de `valid_range`.

Después de bajar MOD11C3: `python pipeline/03_temperature.py` (requiere el paso 01). Necesita los 12 meses de `DATA_YEAR`; si falta alguno, termina con código 2 y dice cuáles. Escribe `data/interim/temperature.parquet`.

## Luna y Marte (TAI-05)

| Objetivo | Variable | Producto | Enlace | measured / literature | Formato y proyección |
| --- | --- | --- | --- | --- | --- |
| moon_south_pole | slope_deg, roughness_m | LOLA polar (a confirmar) | | | |
| moon_south_pole | tmin_c, trange_c | Diviner polar (a confirmar) | | | |
| moon_south_pole | precip_mm, ice_frac | Por definición / has_ice | — | definition | — |
| mars_jezero | slope_deg, roughness_m | MOLA (a confirmar) | | | |
| mars_jezero | tmin_c, trange_c | | | | |
| mars_jezero | precip_mm, ice_frac | Por definición / has_ice | — | definition | — |

Recorte de Jezero a confirmar con Mars Trek (supuesto A2): latitud 17,9 a 18,9 N; longitud 77,0 a 78,0 E.

## NCBI BioSample (paso 05)

No se descarga a mano: el paso 05 guarda cada lote crudo en `data/raw/05_biology/<tipo>_<inicio>.xml`.
