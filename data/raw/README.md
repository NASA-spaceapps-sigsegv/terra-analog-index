# Datos crudos

Las descargas viven en `data/raw/<paso>/` y no se versionan. Este archivo sí: dice qué bajar, de dónde y cuánto pesa.

Los nombres de producto son los del Documento de diseño (sección 4.2) y **están sin verificar** hasta que TAI-04 (Tierra) y TAI-05 (Luna y Marte) completen las tablas.

## Tierra (TAI-04)

| Variable | Paso | Producto | Versión | Resolución | Formato | Cobertura polar | Tamaño (1 año) | Enlace | Decisión |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Polígonos de tierra | 01_grid | Natural Earth land 1:50m | | vectorial | shp | sí | | | |
| Elevación | 02_terrain | | | ~1 km | | | | | |
| Temperatura superficial (día y noche) | 03_temperature | MOD11C3 (a confirmar) | | 0,05° | | | | | |
| Precipitación | 04_water_ice | IMERG mensual (a confirmar) | | | | | | | |
| Nieve | 04_water_ice | | | | | | | | |
| Cobertura del suelo | 04_water_ice | | | | | | | | |

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
