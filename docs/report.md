# Terra Analog Index: project report

NASA Space Apps Challenge 2026, "Earth analogs of the Moon and Mars". Team sigsegv.
Live app: <https://terra-analog-index.onrender.com>. Source code and data: this repository (code under GNU GPL v3; the data keep their own terms).

## 1. Summary

Terra Analog Index (TAI) answers a practical question: which places on Earth resemble the lunar south pole or Jezero crater on Mars, and
in what ways does each resemblance fail? It splits Earth's land into 21,357 cells of 1° (about 110 km), scores each cell from 0 to 1 against
each target, dimension by dimension, and shows the result as an interactive map, a ranking with adjustable weights and a site card that
explains where the analogy holds and where it breaks. A last dimension counts documented records of extremophile life.

With the initial weights, the index ranks Ross Island (Antarctica), a field site already used as a lunar analog, first for the Moon (0.77). For Mars
it ranks the Dalangtan salt playa in China first (0.84), a place that the literature already studies as a Mars analog but that was not on our
list of known analogs. The index recovers the known analogs we use as a test in both targets, and we report the ones it does not recover.
The results are hypotheses to check in the field, not discoveries.

## 2. The challenge

Before sending instruments, rovers or astronauts to the Moon or Mars, agencies test them on Earth in places that match the target in some way
(analogs). The challenge asks for tools that characterize those analogs with data, find less-studied candidates, connect each site with an
exploration use and state what Earth cannot replicate (gravity, vacuum or a thin atmosphere, radiation). We chose two targets: the lunar south pole
(south of 85° S) and Jezero crater, the Perseverance landing site on Mars.

## 3. Process

1. **Targets.** For each target we wrote a profile of the variables we can compare, with the measured or published value and its source
   (`config/targets_base.json`, processed into `data/processed/targets.json`). Values from maps (slope, roughness) are measured on LOLA and MOLA elevation
   data; temperature, ice, dust and wind come from the literature.
2. **Earth grid.** One-degree land cells from Natural Earth. Only cells with land coverage of at least 50 % are kept (21,357 cells).
3. **Earth variables per cell**, from public NASA, NOAA and NCBI data (table in section 4), reduced to one value per cell for the year 2024.
4. **Scoring.** Each variable gets a score from 0 to 1 with one of three rules chosen from where the target's value falls relative to Earth
   (section 5). A dimension is the mean of its variables.
5. **Total and ranking.** The total is the weighted mean of the dimensions with data. The visitor moves the weights and the ranking is recomputed live.
6. **Site card.** For a selected cell: a radar chart, Earth against target for every variable, what it matches and where it differs, a note on
   biological sampling, the limits no place on Earth can replicate, and the sources. Three finalist cells have a hand-written text.
7. **Validation.** We test whether the index finds again the analogs the community already uses (section 6).
8. **Delivery.** A nine-step offline pipeline produces `data/processed/` (about 2 MB); the app only reads those files and runs on a free Render instance.

## 4. Data used

| Data | Used for | Source | Terms |
| --- | --- | --- | --- |
| Natural Earth 1:50m land and countries | Grid, country names | [naturalearthdata.com](https://www.naturalearthdata.com/) | Public domain |
| ETOPO 2022, 30 arc-second | Earth slope and roughness | [NOAA NCEI](https://www.ncei.noaa.gov/products/etopo-global-relief-model) | Public domain |
| MODIS/Terra MOD11C3 v061, 2024 | Earth surface temperature | [doi:10.5067/MODIS/MOD11C3.061](https://doi.org/10.5067/MODIS/MOD11C3.061) | NASA open data |
| GPM IMERG Final monthly V07, 2024 | Earth precipitation | [GES DISC](https://disc.gsfc.nasa.gov/datasets/GPM_3IMERGM_07/summary) | NASA open data |
| MODIS/Terra MOD10CM v061 and MCD12C1 v061, 2024 | Earth snow cover; permanent snow and ice | [doi:10.5067/MODIS/MOD10CM.061](https://doi.org/10.5067/MODIS/MOD10CM.061), [doi:10.5067/MODIS/MCD12C1.061](https://doi.org/10.5067/MODIS/MCD12C1.061) | NASA open data |
| MERRA-2 M2TMNXAER and M2TMNXFLX v5.12.4, 2024 | Earth dust optical depth and surface wind speed (Mars only) | [doi:10.5067/FH9A0MLJPC7N](https://doi.org/10.5067/FH9A0MLJPC7N), [doi:10.5067/0JRLVL8YV2Y4](https://doi.org/10.5067/0JRLVL8YV2Y4) | NASA open data |
| NCBI BioSample | Extremophile records | [NCBI](https://www.ncbi.nlm.nih.gov/biosample) | Public NCBI data |
| LOLA LDEM_80S_80MPP_ADJ (LRO) | Lunar south pole terrain | [NASA PGDA](https://pgda.gsfc.nasa.gov/products/90) | NASA open data |
| MOLA global mosaic, 463 m (MGS) | Jezero terrain | [USGS Astrogeology](https://planetarymaps.usgs.gov/mosaic/Mars_MGS_MOLA_DEM_mosaic_global_463m.tif) | Public domain |

Target values that cannot be measured from a map come from the publications listed in section 9.

## 5. Method

Five dimensions are scored: terrain (slope and roughness), temperature (minimum and daily range), water and ice (precipitation, snow or ice),
dust and wind (dust optical depth and surface wind; **Mars only**, because the Moon has no atmosphere) and astrobiological interest. The initial weights
are 1.0, 1.0, 1.0, 0.5 and 0.5.

Each physical variable uses one of three rules, chosen automatically from where the target's value falls relative to Earth and written in `targets.json`
so it can be audited:

- **Overlap.** Earth covers the target's value, so the score drops as the cell moves away from it (for example slope and wind at Jezero).
- **Directional.** The target lies beyond what Earth reaches, such as the lunar minimum temperature of −223 °C. We reward being among the most extreme places on Earth in
  that direction: a score of 0.95 means "colder than 95 % of the land with data", not "95 % equal to the Moon".
- **Presence.** For snow and ice, according to whether the target has ice.

The astrobiological dimension does not measure similarity: it counts the extremophile records and their types in NCBI BioSample (with a logarithm so a heavily
sampled cell does not dominate), 19,778 records in 237 cells, and is the same for both targets. A cell enters the ranking if it has data in at least two of the
three core physical dimensions (terrain, temperature, water and ice).

## 6. Results

**Validation.** An analog we know passes if its best cell is at or above the 90th percentile of the eligible cells with the initial weights. A target passes if it has at
least two covered analogs and at least two thirds of them pass. Analogs chosen for geology or chemistry that the index does not measure are reported but do not count.

| Target | Analog | Covered | Percentile | Best cell rank | Result |
| --- | --- | --- | --- | --- | --- |
| Moon | Ross Island | yes | 100.0 | 1 | pass |
| Moon | Concordia (Dome C) | yes | 93.4 | 1,413 | pass |
| Moon | Haughton crater | yes | 86.4 | 2,914 | fail |
| Moon | Askja caldera | no | 95.0 | 1,064 | info |
| Mars | Atacama (Yungay) | yes | 99.8 | 52 | pass |
| Mars | Licancabur and Altiplano lakes | yes | 99.4 | 127 | pass |
| Mars | McMurdo Dry Valleys | yes | 31.8 | 14,565 | fail |
| Mars | Death Valley (Ubehebe) | partial | 99.5 | 115 | info |
| Mars | Río Tinto | no | 87.3 | 2,705 | info |

Both targets pass (2 of 3 covered analogs). We did not tune anything until it looked right: a well-explained negative result is worth more than a forced one.

**Top cells.** For the Moon the first cell is Ross Island, Antarctica (0.77); the ten best are in Antarctica, and outside it the best is northern Ellesmere Island, Canada (0.67,
rank 19). For Mars the first cell is the Dalangtan playa in the Qaidam Basin, China (0.84), then its neighbor (0.82). In the top 20 for Mars, 16 cells are in China, because
neighboring cells on the same plateau resemble each other: the ranking groups regions, not independent places. We apply no per-country cap and say so in the method.

**Candidates to verify.** Each has a site card with sources and a list of what to check in the field.

- **Dalangtan playa, Qaidam Basin, China** (Mars, 0.84): sulfates, chlorides and perchlorates; studied as a Mars analog since 2008. Where it fails: minimum temperature −19 °C against −80 °C at Jezero.
- **Northern Ellesmere Island, Canada** (Moon, 0.67): polar desert with permafrost. Where it fails: minimum of −37 °C, not −223 °C, and the satellite precipitation looks too high.
- **Sajama, Bolivia** (Mars, 0.72, rank 50): a 4,200 to 6,542 m puna, dry and cold. Where it fails: it rains much more than at Jezero.

## 7. Limits

- Directional scores do not measure distance to the target; the card always shows the real target value.
- Earth cannot replicate gravity (1.62 and 3.71 m/s²), vacuum or the thin carbon dioxide atmosphere, unshielded radiation, abrasive regolith, perchlorate soils or global dust storms.
- Astrobiological interest reflects where people have sampled; famous sites score higher and unexplored ones score 0. It has a logarithm and an initial weight of 0.5.
- Cells are about 110 km, so a crater, a salt flat or a cave is averaged out.
- Dust and wind on Earth come from a reanalysis (a model), and Earth's wind is at about 10 m while Perseverance measures at 1.5 m.
- One year of data (2024) and surface temperature, not air temperature.
- Missing dimensions: geology and mineralogy, subsurface and rover operations.

## 8. Reproducibility and delivery

- `make install-app` and `make app` run the app from the repository with no download; `make pipeline` regenerates `data/processed/` (a full run downloads about 5.9 GB).
- 560 automated tests (557 pass; the other 4 need geospatial libraries missing on one development machine), data contract tests, a script that walks 16 end-to-end
  checks with the real data, a card text checker and a secret scan of files and history.
- The app is deployed on Render's free plan from the `develop` branch. On that plan it sleeps after about 15 minutes without visits and each interaction takes 3 to 4 seconds
  (0.3 seconds locally).
- Team: Juanma (repository, grid, terrain, temperature, water and ice, similarity, ranking, site card, deployment), Alan (NCBI layer, target profiles, scoring,
  validation, map, method tab), Santino (scientific criteria, sources, target values, texts), Santiago (app skeleton, control maps, README, video).
- **Use of AI.** The team used Claude Code (Anthropic) as a programming assistant; commits it helped write carry a `Co-Authored-By` line.

## 9. References

Targets and analogs:

- Williams, J.-P. et al. (2017). The global surface temperatures of the Moon as measured by the Diviner Lunar Radiometer Experiment. *Icarus* 283, 300-325. doi:10.1016/j.icarus.2016.08.012
- Li, S. et al. (2018). Direct evidence of surface exposed water ice in the lunar polar regions. *PNAS* 115(36), 8907-8912. doi:10.1073/pnas.1802345115
- Savijärvi, H. et al. (2023). *Journal of Geophysical Research: Planets*. doi:10.1029/2022JE007438. Atri, D. et al. (2022). *MNRAS*, arXiv:2204.12850 (Jezero temperatures from MEDA).
- Rodriguez-Manfredi, J. A. et al. (2023). The diverse meteorology of Jezero crater over the first 250 sols of Perseverance on Mars. *Nature Geoscience* 16, 19-28. doi:10.1038/s41561-022-01084-0
- Lemmon, M. T. et al. (2022). *Geophysical Research Letters*. doi:10.1029/2022GL100126 (Jezero dust).
- Newman, C. E. et al. (2022). The dynamic atmospheric and aeolian environment of Jezero crater, Mars. *Science Advances* 8, eabn3783. doi:10.1126/sciadv.abn3783
- Morgan, G. A. et al. (2021). Availability of subsurface water-ice resources in the northern mid-latitudes of Mars. *Nature Astronomy* 5, 230-236.

Known analogs used for validation (each with its source in `config/known_analogs.csv`):

- Navarro-González, R. et al. (2003). Mars-like soils in the Atacama Desert, Chile, and the dry limit of microbial life. *Science* 302, 1018-1021.
- Marchant, D. R. and Head, J. W. (2007). Antarctic dry valleys: microclimate zonation and implications for Mars. *Icarus* 192, 187-222.
- Cabrol, N. A. et al. (2009). The High-Lakes Project. *Journal of Geophysical Research* 114, G00D06.
- Zacny, K. et al. (2013). LunarVader: development and testing of lunar drill in vacuum chamber and in lunar analog site of Antarctica. *Journal of Aerospace Engineering* 26, 74-86. doi:10.1061/(ASCE)AS.1943-5525.0000212
- Fernández-Remolar, D. C. et al. (2005). The Río Tinto Basin, Spain. *Earth and Planetary Science Letters* 240, 149-167.
- Lee, P. et al. (2007). Haughton-Mars Project. Lunar and Planetary Science Conference XXXVIII, abstract 2426.

Finalist cards:

- Kong, F. et al. (2018). Dalangtan Saline Playa in a Hyperarid Region on Tibet Plateau: I. Evolution and Environments. *Astrobiology* 18, 1243-1253. doi:10.1089/ast.2018.1830
- Huang, T. et al. (2018). Dalangtan Playa (Qaidam Basin, NW China): its microbial life and physicochemical characteristics and their astrobiological implications. *PLoS ONE*. doi:10.1371/journal.pone.0200949
- Liu, L. et al. (2023). Metabolic versatility of soil microbial communities below the rocks of the hyperarid Dalangtan Playa. *Applied and Environmental Microbiology*. doi:10.1128/aem.01072-23
- Parks Canada. Ecosystems and habitats, Quttinirpaaq National Park. <https://parks.canada.ca/pn-np/nu/quttinirpaaq/nature/environnement-environment/habitats>
- NASA. Haughton-Mars Project (HMP), Canadian Arctic. <https://www.nasa.gov/mission/haughton-mars-project-hmp-canadian-arctic>
- Key Biodiversity Areas. Sajama factsheet. <https://www.keybiodiversityareas.org/site/factsheet/14358>

Caves and lava tubes (informational layer): Sauro, F. et al. (2020). Lava tubes on Earth, Moon and Mars. *Earth-Science Reviews* 209, 103288.
