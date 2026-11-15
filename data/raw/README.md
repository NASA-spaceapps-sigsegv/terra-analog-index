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

Después de bajar IMERG, MOD10CM y MCD12C1: `python pipeline/04_water_ice.py`. Necesita los 12 meses de IMERG y de MOD10CM; para MCD12C1 usa el de `DATA_YEAR` o, si todavía no salió, el último anterior. Escribe `data/interim/water_ice.parquet`. La precipitación queda nula al sur de 60° S, porque IMERG no mide la nieve sobre la Antártida (diseño 4.3).

## NCBI BioSample (paso 05)

No se descarga a mano: el paso 05 guarda cada lote crudo en `data/raw/05_biology/<tipo>_<inicio>.xml`.

### Paso 05: NCBI BioSample (TAI-15)

No hay archivos que bajar a mano: el paso consulta NCBI con los términos de `config/bio_terms.json` y guarda cada lote crudo en `data/raw/05_biology/<tipo>_<inicio>.xml` (no se versiona). Si se corta, se vuelve a correr y solo pide los lotes que faltan.

Variables de entorno (en la terminal o en un `.env` local, que el `Makefile` carga; nunca en el repositorio): `NCBI_EMAIL` (obligatoria) y `NCBI_API_KEY` (opcional: 10 pedidos por segundo en vez de 3).

```bash
python pipeline/05_biology_ncbi.py --type halophile --max-records 200
```

Esa prueba baja un solo lote. Es una corrida parcial: queda marcada en el manifiesto y la siguiente corrida completa la reemplaza. Después, `python pipeline/05_biology_ncbi.py` baja los 6 tipos (hasta 5.000 registros cada uno; unos minutos). Plan B sin red: `--manual` lee `config/bio_manual.csv` (columnas `lat,lon,extremophile_type,source`). Escribe `data/processed/bio_samples.parquet` y `data/interim/biology.parquet`; el manifiesto dice, por tipo, cuántos hay en NCBI, cuántos se bajaron, cuántos traen coordenadas y cuántos caen en tierra.

## Luna y Marte (TAI-05)

Relevamiento del 14 de noviembre de 2026. Los enlaces de elevación se comprobaron con una petición de cabeceras (existen, tamaño real) y se leyeron sus metadatos. La columna "Decisión" dice qué variable se mide y cuál se toma de la literatura; los valores y las citas de literatura están en `config/targets_base.json`.

| Variable | Objetivo | Producto | Formato y proyección | Tamaño | Enlace | Decisión |
| --- | --- | --- | --- | --- | --- | --- |
| slope_deg, roughness_m | Luna, polo sur | LOLA `LDEM_80S_80MPP_ADJ.TIF` (LRO), 80 m por píxel, de 80° S al polo | GeoTIFF float32 en metros, estereográfica polar sur (esfera de 1 737 400 m), 7600 × 7600 | 181 MiB (189 MB) | [LDEM_80S_80MPP_ADJ.TIF](https://pgda.gsfc.nasa.gov/data/LOLA_20mpp/LDEM_80S_80MPP_ADJ.TIF); página del producto: [PGDA 90](https://pgda.gsfc.nasa.gov/products/90) | measured (paso 07) |
| slope_deg (control) | Luna, polo sur | LOLA `LDSM_80S_80MPP_ADJ.TIF`, pendiente ya calculada | igual que el anterior | 231 MiB (242 MB) | [LDSM_80S_80MPP_ADJ.TIF](https://pgda.gsfc.nasa.gov/data/LOLA_20mpp/LDSM_80S_80MPP_ADJ.TIF) | opcional, solo para comparar con la pendiente propia |
| tmin_c, trange_c | Luna, polo sur | Diviner, producto de recursos polares `DLRE_PRP_SOUTH.TAB` (temperatura media y máxima anual por triángulo; 2 880 000 triángulos) o acumulado polar PCP (240 m, por hora local) | tabla ASCII (PRP) o binarios por bin horario (PCP) | por confirmar | [ayuda de ODE sobre PRP](https://ode.rsl.wustl.edu/moon/pagehelp/Content/Missions_Instruments/LRO/DIVINER/PRP.htm); la ruta exacta del archivo en PDS **no está confirmada** (la ruta que se probó dio 404) | literature: Williams et al. (2017), Icarus 283, 300-325 (Diviner, al sur de 85°: mínima media 50 K y máxima media 202 K). El PRP trae media y máxima anual, no el mínimo ni el rango: medirlo requeriría el PCP |
| precip_mm | Luna y Marte | sin lluvia | n/a | n/a | n/a | definition: 0 |
| ice_frac | Luna y Marte | `has_ice` (Luna: sí; Jezero: no), con la fuente que cargue Santino | n/a | n/a | n/a | definition |
| slope_deg, roughness_m | Marte, Jezero | MOLA, mosaico global de 463 m (USGS Astrogeology) | GeoTIFF int16 en metros, equirectangular, esfera de 3 396 190 m, longitud de -180 a 180 (media de 59 276 m por grado), nodata -32768 | 2,0 GiB (2 125 771 142 bytes); se lee solo la ventana por HTTP, no hace falta bajarlo | [Mars_MGS_MOLA_DEM_mosaic_global_463m.tif](https://planetarymaps.usgs.gov/mosaic/Mars_MGS_MOLA_DEM_mosaic_global_463m.tif) | measured (paso 07) |
| tmin_c, trange_c | Marte, Jezero | MEDA (Perseverance), archivo EDR y RDR en el nodo de Atmósferas de PDS | CSV por sol | por confirmar | [doi:10.17189/1522849](https://doi.org/10.17189/1522849) | literature: Savijärvi et al. (2023), JGR Planets, y Atri et al. (2022), MNRAS (temperatura del suelo medida por MEDA) |

### Recortes

- **Luna, polo sur:** al sur de 85° S, un círculo de unos 151,7 km de radio desde el polo (colatitud de 5°). El raster de 80 m cubre hasta 80° S (colatitud de 10°, 304 km), así que contiene el recorte entero.
- **Jezero:** centro en 18,38° N y 77,58° E según las fuentes consultadas ([JPL](https://www.jpl.nasa.gov/news/press_kits/mars_2020/landing/mission/landing_site) y [The Planetary Society](https://planetary.org/articles/jezero-landing-site-mars-2020-rover)); el diámetro del cráter es de unos 45 km (hay fuentes que dicen 49 km). El recorte del diseño (17,9 a 18,9° N y 77,0 a 78,0° E) lo contiene con margen: con 45 km de diámetro el cráter ocupa de 18,0 a 18,8° N y de 77,2 a 78,0° E. **Falta la comprobación visual en Mars Trek** (criterio del ticket), que queda para Santino o para los dos.
- **Control hecho con datos reales:** la ventana de MOLA de ese recorte tiene 128 × 128 píxeles con elevaciones de -2888 a -1465 m, o sea, se ve el relieve de un cráter (la longitud no está corrida 180°). A 1 km da una pendiente media de 2,3° y una rugosidad media de 53 m.
- **Temperatura de Marte:** se toma de la literatura sobre MEDA: mínima del suelo de 191 K a unos 200 K y amplitud diaria de unos 60 a 86 K. Valores y citas en `config/targets_base.json`.

### Paso 07: cómo se corre

`python pipeline/07_targets.py` lee `config/targets_base.json` (Santino), `earth_stats` del manifiesto (lo escribe el paso 06) y los dos DEM de elevación. Pone la regla de cada variable con `tai.rules.choose_rule` (TAI-18). Para la Luna hay que bajar el LDEM de 80 m a `data/raw/07_targets/` (189 MB) con `make data-moon` (también lo baja `make data`); el de Marte se lee por HTTP si no está en esa carpeta.
