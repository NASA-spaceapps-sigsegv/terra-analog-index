# Raw data

Downloads live in `data/raw/<step>/` and are not versioned. This file is: it says what to download, from where and how big it is.

Everything with a direct download is fetched with `make data` from the root (or per step: `make data-grid`, `make data-terrain`, `make data-earthdata`; `make help` lists them). The `curl` commands below are the manual equivalent.

The Earth products were verified in TAI-04 against NASA's CMR catalog on November 14, 2026 (name, version, available months and size). All monthly and annual products are for calendar year **2024** (`DATA_YEAR` in `tai/constants.py`): the IMERG Final run ends in September 2025, so 2025 is not complete for precipitation. The Moon and Mars ones remain **unverified** until TAI-05 completes its table.

## Earth (TAI-04)

| Variable | Step | Product | Version | Resolution | Format | Polar coverage | Size (1 year) | Link | Decision |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Land polygons | 01_grid | Natural Earth `ne_50m_land` | 5.2.0-pre (GitHub mirror) | 1:50m (vector) | shp or geojson | yes (Antarctica and Greenland) | 1.6 MB | [naturalearthdata.com](https://www.naturalearthdata.com/downloads/50m-physical-vectors/) | Confirmed (TAI-11) |
| Countries (English name) | 01_grid | Natural Earth `ne_50m_admin_0_countries`, field `NAME_EN` | 5.2.0-pre (GitHub mirror) | 1:50m (vector) | shp or geojson | yes | 3.1 MB | [naturalearthdata.com](https://www.naturalearthdata.com/downloads/50m-cultural-vectors/) | Confirmed (TAI-11) |
| Elevation | 02_terrain | ETOPO 2022 `ETOPO_2022_v1_30s_N90W180_surface` | v1 | 30" (~0.93 km) | netCDF | yes (Antarctica included; the sea floor is discarded with the land mask) | 1.64 GB | [NOAA NCEI](https://www.ncei.noaa.gov/products/etopo-global-relief-model) | Chosen for TAI-12: global and public domain. Alternative: GMTED2010 mn30 |
| Surface temperature (day and night) | 03_temperature | MODIS/Terra `MOD11C3`, layers `LST_Day_CMG` and `LST_Night_CMG` (K, scale factor 0.02) | 061 | 0.05° (CMG, 7200 × 3600) | HDF4-EOS, 1 file per month | yes (90° S to 90° N); no daytime data during the polar night | 837 MB (12 files of ~70 MB) | [doi:10.5067/MODIS/MOD11C3.061](https://doi.org/10.5067/MODIS/MOD11C3.061) (LP DAAC) | Confirmed: all 12 months of 2024 are in CMR. Reading HDF4 requires `pyhdf` (see below) |
| Precipitation | 04_water_ice | GPM IMERG Final monthly `GPM_3IMERGM`, variable `precipitation` (mm/h) | 07 (V07B files) | 0.1° (3600 × 1800) | HDF5, 1 file per month | yes (90° S to 90° N); at the poles and over ice the estimate is less reliable | 214 MB (12 files of ~18 MB) | [GES DISC](https://disc.gsfc.nasa.gov/datasets/GPM_3IMERGM_07/summary) | Confirmed for 2024. The Final run ends in September 2025; that is why `DATA_YEAR` went from 2025 to 2024 for every product. MERRA-2 `M2TMNXFLX` (reanalysis, 2025 complete) was discarded: it swaps satellite observation for a model exactly where it matters, in the driest areas |
| Snow | 04_water_ice | MODIS/Terra `MOD10CM`, layer `Snow_Cover_Monthly_CMG` (% from 0 to 100; higher values are flags) | 61 | 0.05° (CMG, 7200 × 3600) | HDF4-EOS, 1 file per month | yes (90° S to 90° N); no observation during the polar night, as design section 4.3 anticipates | 16 MB (12 files of ~1.4 MB) | [doi:10.5067/MODIS/MOD10CM.061](https://doi.org/10.5067/MODIS/MOD10CM.061) (NSIDC) | Confirmed: all 12 months of 2024 are in CMR. The exact flags are checked when opening the first file (TAI-14) |
| Land cover | 04_water_ice | MODIS/Terra+Aqua `MCD12C1`, layer `Majority_Land_Cover_Type_1` (IGBP; class 15 = permanent snow and ice) and `Land_Cover_Type_1_Percent` | 061 | 0.05° (CMG, 7200 × 3600) | HDF4-EOS, 1 file per year | yes (90° S to 90° N) | 1.2 GB (1 file) | [doi:10.5067/MODIS/MCD12C1.061](https://doi.org/10.5067/MODIS/MCD12C1.061) (LP DAAC) | Confirmed: year 2024 is published. `Land_Cover_Type_1_Percent` directly gives the permanent ice-cap fraction of design section 4.1 |

### Step 01: how to download the files

They go in `data/raw/01_grid/` under their original names. The step accepts `.shp` (with its companion files), `.geojson`, `.gpkg` or the `.zip` without unzipping.

From the official page: *Land* (physical) and *Admin 0 – Countries* (cultural), 1:50m scale. If the site is down, the same version in GeoJSON is in the Natural Earth repository on GitHub:

```bash
mkdir -p data/raw/01_grid
```
```bash
curl -L -o data/raw/01_grid/ne_50m_land.geojson https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_land.geojson
```
```bash
curl -L -o data/raw/01_grid/ne_50m_admin_0_countries.geojson https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_countries.geojson
```

Then: `python pipeline/01_grid.py`. It writes `data/processed/grid.parquet` and `data/interim/land_mask.nc` (the 0.05° mask used by steps 02 to 04).

### Step 02: elevation model

A single file in `data/raw/02_terrain/`, in latitude and longitude (`.nc`, `.tif`, `.tiff` or `.vrt`). If the product comes in tiles, merge them first with `gdalbuildvrt data/raw/02_terrain/dem.vrt tiles/*.tif`.

```bash
mkdir -p data/raw/02_terrain
```
```bash
curl -L -o data/raw/02_terrain/ETOPO_2022_v1_30s_N90W180_surface.nc https://www.ngdc.noaa.gov/thredds/fileServer/global/ETOPO2022/30s/30s_surface_elev_netcdf/ETOPO_2022_v1_30s_N90W180_surface.nc
```

Then: `python pipeline/02_terrain.py` (requires step 01 to have run). It writes `data/interim/terrain.parquet`. To quickly test a region: `--bbox -35 -15 -75 -60`.

### Steps 03 and 04: Earthdata products

They need a [NASA Earthdata Login](https://urs.earthdata.nasa.gov/) account (TAI-01). The script looks up the files in CMR and downloads them with a user and password, taken from `EARTHDATA_USERNAME` and `EARTHDATA_PASSWORD` or from `~/.netrc`:

```
machine urs.earthdata.nasa.gov login <user> password <password>
```

For IMERG you also have to authorize the *NASA GESDISC DATA ARCHIVE* application in the Earthdata profile (*Applications → Authorized Apps*); without it the download returns a web page instead of the file.

```bash
python pipeline/fetch_earthdata.py --dry-run   # lists files and sizes, no login
```
```bash
make data-earthdata                            # downloads all of 2024 (~2.3 GB); can be interrupted and rerun
```

Destinations: `data/raw/03_temperature/` (MOD11C3), `data/raw/04_water_ice/imerg/`, `.../mod10cm/` and `.../mcd12c1/`.

**Reading HDF4.** MOD11C3, MOD10CM and MCD12C1 come in HDF4. The rasterio installed with pip ships GDAL without the HDF4 driver, so it cannot open them. That is why `requirements-pipeline.txt` includes `pyhdf==0.11.7` (it has a wheel for Python 3.14 on Linux, so `pip install -r requirements-pipeline.txt` is enough). With conda, `gdal` from conda-forge also includes HDF4. IMERG (HDF5) and ETOPO (netCDF) are read with what is already installed. In the code, `read_hdf4_layer` in `pipeline/common.py` opens any layer and marks fill values and anything outside `valid_range` as null.

After downloading MOD11C3: `python pipeline/03_temperature.py` (requires step 01). It needs all 12 months of `DATA_YEAR`; if any is missing, it exits with code 2 and says which. It writes `data/interim/temperature.parquet`.

After downloading IMERG, MOD10CM and MCD12C1: `python pipeline/04_water_ice.py`. It needs all 12 months of IMERG and MOD10CM; for MCD12C1 it uses the `DATA_YEAR` one or, if it is not out yet, the latest earlier one. It writes `data/interim/water_ice.parquet`. Precipitation is left null south of 60° S, because IMERG does not measure snow over Antarctica (design 4.3).

## Dust and wind (step 04_dust_wind, TAI-52)

| Variable | Product | Version | Resolution | Format | Polar coverage | Size (1 year) | Link | Decision |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Dust optical depth at 550 nm (`dust_aod`) | MERRA-2 `M2TMNXAER`, variable `DUEXTTAU` (dimensionless) | 5.12.4 | 0.5° × 0.625° | netCDF4, 1 file per month | yes, no gaps | 960 MB (12 files of 80 MB) | [doi:10.5067/FH9A0MLJPC7N](https://doi.org/10.5067/FH9A0MLJPC7N) (GES DISC) | Chosen: global and without gaps over ice. It is a reanalysis (a model), not an observation; MODIS AOD (MOD08_M3) has no data over ice and no wind |
| Surface wind speed (`wind_ms`) | MERRA-2 `M2TMNXFLX`, variable `SPEED` (m/s) | 5.12.4 | 0.5° × 0.625° | netCDF4, 1 file per month | yes, no gaps | 880 MB (12 files of ~74 MB) | [doi:10.5067/0JRLVL8YV2Y4](https://doi.org/10.5067/0JRLVL8YV2Y4) (GES DISC) | Chosen together with the previous one; downloaded with the same Earthdata account |

```bash
make data-dust-wind   # or: python pipeline/fetch_earthdata.py m2aer m2flx
```

Destinations: `data/raw/04_dust_wind/m2tmnxaer/` and `.../m2tmnxflx/`. Then: `python pipeline/04_dust_wind.py` (requires step 01); it averages the 12 months and each 1° cell takes the mean of the MERRA-2 points whose center falls inside it. It writes `data/interim/dust_wind.parquet`.

The dimension only exists for Jezero: the Moon has no atmosphere. Jezero values (literature, in `config/targets_base.json`): dust optical depth of 0.4 to 0.5 outside storms (Mastcam-Z and MEDA; Rodriguez-Manfredi et al. 2023, Lemmon et al. 2022) and a mean daytime wind of about 4 m/s at 1.5 m (MEDA; Newman et al. 2022).

## NCBI BioSample (step 05)

Not downloaded by hand: step 05 saves each raw batch in `data/raw/05_biology/<type>_<start>.xml`.

### Step 05: NCBI BioSample (TAI-15)

There are no files to download by hand: the step queries NCBI with the terms in `config/bio_terms.json` and saves each raw batch in `data/raw/05_biology/<type>_<start>.xml` (not versioned). If it is interrupted, run it again and it only requests the missing batches.

Environment variables (in the terminal or in a local `.env`, which the `Makefile` loads; never in the repository): `NCBI_EMAIL` (required) and `NCBI_API_KEY` (optional: 10 requests per second instead of 3).

```bash
python pipeline/05_biology_ncbi.py --type halophile --max-records 200
```

That test downloads a single batch. It is a partial run: it is flagged in the manifest and the next full run replaces it. Then, `python pipeline/05_biology_ncbi.py` downloads all 6 types (up to 5,000 records each; a few minutes). Offline plan B: `--manual` reads `config/bio_manual.csv` (columns `lat,lon,extremophile_type,source`). It writes `data/processed/bio_samples.parquet` and `data/interim/biology.parquet`; the manifest says, per type, how many there are in NCBI, how many were downloaded, how many have coordinates and how many fall on land.

## Moon and Mars (TAI-05)

Survey of November 14, 2026. The elevation links were checked with a header request (they exist, real size) and their metadata were read. The "Decision" column says which variable is measured and which is taken from the literature; the literature values and citations are in `config/targets_base.json`.

| Variable | Target | Product | Format and projection | Size | Link | Decision |
| --- | --- | --- | --- | --- | --- | --- |
| slope_deg, roughness_m | Moon, south pole | LOLA `LDEM_80S_80MPP_ADJ.TIF` (LRO), 80 m per pixel, from 80° S to the pole | float32 GeoTIFF in meters, south polar stereographic (sphere of 1,737,400 m), 7600 × 7600 | 181 MiB (189 MB) | [LDEM_80S_80MPP_ADJ.TIF](https://pgda.gsfc.nasa.gov/data/LOLA_20mpp/LDEM_80S_80MPP_ADJ.TIF); product page: [PGDA 90](https://pgda.gsfc.nasa.gov/products/90) | measured (step 07) |
| slope_deg (check) | Moon, south pole | LOLA `LDSM_80S_80MPP_ADJ.TIF`, precomputed slope | same as above | 231 MiB (242 MB) | [LDSM_80S_80MPP_ADJ.TIF](https://pgda.gsfc.nasa.gov/data/LOLA_20mpp/LDSM_80S_80MPP_ADJ.TIF) | optional, only to compare with our own slope |
| tmin_c, trange_c | Moon, south pole | Diviner, polar resource product `DLRE_PRP_SOUTH.TAB` (annual mean and maximum temperature per triangle; 2,880,000 triangles) or polar cumulative PCP (240 m, per local hour) | ASCII table (PRP) or binaries per hourly bin (PCP) | to be confirmed | [ODE help on PRP](https://ode.rsl.wustl.edu/moon/pagehelp/Content/Missions_Instruments/LRO/DIVINER/PRP.htm); the exact file path in PDS is **not confirmed** (the path we tried returned 404) | literature: Williams et al. (2017), Icarus 283, 300-325 (Diviner, poleward of 85°: mean minimum 50 K and mean maximum 202 K). The PRP has the annual mean and maximum, not the minimum or the range: measuring it would require the PCP |
| precip_mm | Moon and Mars | no rain | n/a | n/a | n/a | definition: 0 |
| ice_frac | Moon and Mars | `has_ice` (Moon: yes; Jezero: no), with the source Santino provides | n/a | n/a | n/a | definition |
| slope_deg, roughness_m | Mars, Jezero | MOLA, 463 m global mosaic (USGS Astrogeology) | int16 GeoTIFF in meters, equirectangular, sphere of 3,396,190 m, longitude from -180 to 180 (59,276 m per degree on average), nodata -32768 | 2.0 GiB (2,125,771,142 bytes); only the window is read over HTTP, no download needed | [Mars_MGS_MOLA_DEM_mosaic_global_463m.tif](https://planetarymaps.usgs.gov/mosaic/Mars_MGS_MOLA_DEM_mosaic_global_463m.tif) | measured (step 07) |
| tmin_c, trange_c | Mars, Jezero | MEDA (Perseverance), EDR and RDR files in the PDS Atmospheres node | CSV per sol | to be confirmed | [doi:10.17189/1522849](https://doi.org/10.17189/1522849) | literature: Savijärvi et al. (2023), JGR Planets, and Atri et al. (2022), MNRAS (ground temperature measured by MEDA) |

### Crops

- **Moon, south pole:** south of 85° S, a circle of about 151.7 km radius from the pole (5° colatitude). The 80 m raster covers down to 80° S (10° colatitude, 304 km), so it contains the whole crop.
- **Jezero:** center at 18.38° N and 77.58° E according to the sources consulted ([JPL](https://www.jpl.nasa.gov/news/press_kits/mars_2020/landing/mission/landing_site) and [The Planetary Society](https://planetary.org/articles/jezero-landing-site-mars-2020-rover)); the crater diameter is about 45 km (some sources say 49 km). The design's crop (17.9 to 18.9° N and 77.0 to 78.0° E) contains it with margin: with a 45 km diameter the crater spans 18.0 to 18.8° N and 77.2 to 78.0° E. **The visual check in Mars Trek is still pending** (a ticket criterion), left for Santino or for both.
- **Check done with real data:** the MOLA window for that crop is 128 × 128 pixels with elevations from -2888 to -1465 m, i.e. the relief of a crater is visible (the longitude is not shifted by 180°). At 1 km it gives a mean slope of 2.3° and a mean roughness of 53 m.
- **Mars temperature:** taken from the MEDA literature: ground minimum of 191 K to about 200 K and a daily amplitude of about 60 to 86 K. Values and citations in `config/targets_base.json`.

### Step 07: how to run it

`python pipeline/07_targets.py` reads `config/targets_base.json` (Santino), `earth_stats` from the manifest (written by step 06) and the two elevation DEMs. It sets each variable's rule with `tai.rules.choose_rule` (TAI-18). For the Moon you have to download the 80 m LDEM to `data/raw/07_targets/` (189 MB) with `make data-moon` (`make data` downloads it too); the Mars one is read over HTTP if it is not in that folder.
