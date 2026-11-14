# Datos crudos

Las descargas viven en `data/raw/<paso>/` y no se versionan. Este archivo sí: dice qué bajar, de dónde y cuánto pesa.

Los nombres de producto son los del Documento de diseño (sección 4.2) y **están sin verificar** hasta que TAI-04 (Tierra) y TAI-05 (Luna y Marte) completen las tablas.

## Tierra (TAI-04)

| Variable | Paso | Producto | Versión | Resolución | Formato | Cobertura polar | Tamaño (1 año) | Enlace | Decisión |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Polígonos de tierra | 01_grid | Natural Earth `ne_50m_land` | 5.2.0-pre (espejo de GitHub) | 1:50m (vectorial) | shp o geojson | sí (Antártida y Groenlandia) | 1,6 MB | [naturalearthdata.com](https://www.naturalearthdata.com/downloads/50m-physical-vectors/) | Confirmado (TAI-11) |
| Países (nombre en español) | 01_grid | Natural Earth `ne_50m_admin_0_countries`, campo `NAME_ES` | 5.2.0-pre (espejo de GitHub) | 1:50m (vectorial) | shp o geojson | sí | 3,1 MB | [naturalearthdata.com](https://www.naturalearthdata.com/downloads/50m-cultural-vectors/) | Confirmado (TAI-11) |
| Elevación | 02_terrain | | | ~1 km | | | | | |
| Temperatura superficial (día y noche) | 03_temperature | MOD11C3 (a confirmar) | | 0,05° | | | | | |
| Precipitación | 04_water_ice | IMERG mensual (a confirmar) | | | | | | | |
| Nieve | 04_water_ice | | | | | | | | |
| Cobertura del suelo | 04_water_ice | | | | | | | | |

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
