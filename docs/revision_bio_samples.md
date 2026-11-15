# Revisión de 20 registros de BioSample (TAI-15)

Criterio de aceptación de TAI-15: revisar 20 registros al azar de `data/processed/bio_samples.parquet` y confirmar que son del ambiente esperado.

- **Archivo:** `data/processed/bio_samples.parquet` de develop (19 778 filas, corrida del paso 05 del 14 de noviembre de 2026).
- **Muestra:** `df.sample(20, random_state=20261114)`; con el mismo archivo sale la misma muestra.
- **Resultado:** los 20 son del ambiente que indica su tipo. Se cumple el criterio.

| # | accession | Tipo | Ambiente declarado (isolation_source) | Lugar (geo_loc_name) | lat, lon | ¿Ambiente esperado? | Observación |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | SAMN40885763 | thermophile | Hot spring sediment | China: Tengchong, Yunnan | 24.95, 98.44 | Sí | Mismo BioProject que 8, 9, 10, 14, 16 y 17 |
| 2 | SAMN49652498 | xerophile | Desert soil | China: cuenca de Qaidam | 38.34, 91.32 | Sí | |
| 3 | SAMN52932289 | halophile | Wulanhushao salt lake | China: Mongolia Interior | 41.53, 113.29 | Sí | |
| 4 | SAMD00689158 | acidophile | Acid mine drainage sediment | China: mina Longshenao, Guangxi | 24.83, 107.57 | Sí | |
| 5 | SAMN63291144 | xerophile | Hyper-arid desert rhizosphere soil | China: Noroeste | 37.00, 85.00 | Sí | Coordenadas redondeadas a grados enteros |
| 6 | SAMN51880182 | psychrophile | Permafrost soil | China: meseta tibetana | 37.55, 101.35 | Sí | |
| 7 | SAMD00665886 | halophile | Anoxic hypersaline lake sediment | EE. UU.: California | 33.42, -115.92 | Sí | Salton Sea |
| 8 | SAMN40885504 | thermophile | Hot spring sediment | China: Tengchong, Yunnan | 24.95, 98.44 | Sí | |
| 9 | SAMN40886060 | thermophile | Hot spring sediment | China: Tengchong, Yunnan | 24.95, 98.44 | Sí | |
| 10 | SAMN40885778 | thermophile | Hot spring sediment | China: Tengchong, Yunnan | 24.95, 98.44 | Sí | |
| 11 | SAMN48441082 | halophile | Hypersaline microbial mat, incubated 85 days | México: Guerrero Negro, BCS | 27.69, -113.91 | Sí | Muestra de campo incubada en laboratorio |
| 12 | SAMN62271544 | halophile | Porewater, hypersaline lake | Australia: Pink Lake, Australia Occidental | -33.84, 121.84 | Sí | |
| 13 | SAMN52864258 | xerophile | Desert soil | Arabia Saudita: Rub al-Jali | 21.98, 53.14 | Sí | |
| 14 | SAMN40886918 | thermophile | Hot spring sediment | China: Tengchong, Yunnan | 24.95, 98.44 | Sí | |
| 15 | SAMN51837064 | psychrophile | Permafrost soil | China: llanura de Sanjiang | 37.55, 101.35 | Sí | **Coordenadas incoherentes:** Sanjiang está cerca de 47,5° N y 133,5° E; estas son las del registro 6 (Qinghai) |
| 16 | SAMN40883209 | thermophile | Hot spring sediment | China: Tengchong, Yunnan | 25.44, 98.46 | Sí | |
| 17 | SAMN40884149 | thermophile | Hot spring sediment | China: Tengchong, Yunnan | 25.44, 98.46 | Sí | |
| 18 | SAMN63298448 | xerophile | Hyper-arid desert bulk soil | China: Noroeste | 38.00, 85.27 | Sí | |
| 19 | SAMD00689180 | acidophile | Acid mine drainage sediment | China: mina Longshenao, Guangxi | 24.83, 107.57 | Sí | |
| 20 | SAMN51834878 | psychrophile | Permafrost soil | China: llanura de Sanjiang | 47.59, 133.64 | Sí | |

## Observaciones para la pestaña Método y las fichas

1. **El ambiente es confiable.** Los términos de `config/bio_terms.json` traen muestras del ambiente correcto: 20 de 20.
2. **La ubicación es menos confiable.** 1 de 20 tiene coordenadas que no corresponden a su `geo_loc_name` (posiblemente copiadas entre muestras de un mismo proyecto) y 1 de 20 viene redondeada a grados enteros. Con celdas de 1° el redondeo no cambia la celda; la incoherencia sí manda la muestra a otra celda.
3. **Concentración (sesgo de muestreo, design 14 #2).** 7 de 20 son del mismo estudio de aguas termales de Tengchong y 14 de 20 son de China. `bio_records` cuenta muestras, así que un solo proyecto grande infla su celda. El logaritmo de la fórmula (design 5.5) lo amortigua, y `bio_types` no se ve afectado.
4. **Una muestra incubada en laboratorio** (n.º 11) sigue siendo de un tapete hipersalino de campo; se acepta.
