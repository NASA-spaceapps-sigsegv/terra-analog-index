# Review of 20 BioSample records (TAI-15)

TAI-15 acceptance criterion: review 20 random records from `data/processed/bio_samples.parquet` and confirm they come from the expected environment.

- **File:** `data/processed/bio_samples.parquet` on develop (19,778 rows, step 05 run of November 14, 2026).
- **Sample:** `df.sample(20, random_state=20261114)`; the same file gives the same sample.
- **Result:** all 20 come from the environment their type indicates. The criterion is met.

| # | accession | Type | Declared environment (isolation_source) | Place (geo_loc_name) | lat, lon | Expected environment? | Note |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | SAMN40885763 | thermophile | Hot spring sediment | China: Tengchong, Yunnan | 24.95, 98.44 | Yes | Same BioProject as 8, 9, 10, 14, 16 and 17 |
| 2 | SAMN49652498 | xerophile | Desert soil | China: Qaidam Basin | 38.34, 91.32 | Yes | |
| 3 | SAMN52932289 | halophile | Wulanhushao salt lake | China: Inner Mongolia | 41.53, 113.29 | Yes | |
| 4 | SAMD00689158 | acidophile | Acid mine drainage sediment | China: Longshenao mine, Guangxi | 24.83, 107.57 | Yes | |
| 5 | SAMN63291144 | xerophile | Hyper-arid desert rhizosphere soil | China: Northwest | 37.00, 85.00 | Yes | Coordinates rounded to whole degrees |
| 6 | SAMN51880182 | psychrophile | Permafrost soil | China: Tibetan Plateau | 37.55, 101.35 | Yes | |
| 7 | SAMD00665886 | halophile | Anoxic hypersaline lake sediment | USA: California | 33.42, -115.92 | Yes | Salton Sea |
| 8 | SAMN40885504 | thermophile | Hot spring sediment | China: Tengchong, Yunnan | 24.95, 98.44 | Yes | |
| 9 | SAMN40886060 | thermophile | Hot spring sediment | China: Tengchong, Yunnan | 24.95, 98.44 | Yes | |
| 10 | SAMN40885778 | thermophile | Hot spring sediment | China: Tengchong, Yunnan | 24.95, 98.44 | Yes | |
| 11 | SAMN48441082 | halophile | Hypersaline microbial mat, incubated 85 days | Mexico: Guerrero Negro, BCS | 27.69, -113.91 | Yes | Field sample incubated in the lab |
| 12 | SAMN62271544 | halophile | Porewater, hypersaline lake | Australia: Pink Lake, Western Australia | -33.84, 121.84 | Yes | |
| 13 | SAMN52864258 | xerophile | Desert soil | Saudi Arabia: Rub' al Khali | 21.98, 53.14 | Yes | |
| 14 | SAMN40886918 | thermophile | Hot spring sediment | China: Tengchong, Yunnan | 24.95, 98.44 | Yes | |
| 15 | SAMN51837064 | psychrophile | Permafrost soil | China: Sanjiang Plain | 37.55, 101.35 | Yes | **Inconsistent coordinates:** Sanjiang is near 47.5° N and 133.5° E; these are record 6's (Qinghai) |
| 16 | SAMN40883209 | thermophile | Hot spring sediment | China: Tengchong, Yunnan | 25.44, 98.46 | Yes | |
| 17 | SAMN40884149 | thermophile | Hot spring sediment | China: Tengchong, Yunnan | 25.44, 98.46 | Yes | |
| 18 | SAMN63298448 | xerophile | Hyper-arid desert bulk soil | China: Northwest | 38.00, 85.27 | Yes | |
| 19 | SAMD00689180 | acidophile | Acid mine drainage sediment | China: Longshenao mine, Guangxi | 24.83, 107.57 | Yes | |
| 20 | SAMN51834878 | psychrophile | Permafrost soil | China: Sanjiang Plain | 47.59, 133.64 | Yes | |

## Notes for the Method tab and the cards

1. **The environment is reliable.** The terms in `config/bio_terms.json` bring samples from the right environment: 20 of 20.
2. **The location is less reliable.** 1 of 20 has coordinates that do not match its `geo_loc_name` (possibly copied between samples of the same project) and 1 of 20 is rounded to whole degrees. With 1° cells the rounding does not change the cell; the inconsistency does send the sample to another cell.
3. **Concentration (sampling bias, design 14 #2).** 7 of 20 come from the same Tengchong hot-spring study and 14 of 20 are from China. `bio_records` counts samples, so a single large project inflates its cell. The logarithm in the formula (design 5.5) dampens it, and `bio_types` is not affected.
4. **A lab-incubated sample** (no. 11) still comes from a field hypersaline mat; it is accepted.
