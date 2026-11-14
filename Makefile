# Raw data downloads for the pipeline (see data/raw/README.md).
#
#   make data      download everything that is missing
#   make maps      control maps of the intermediate files (TAI-24)
#   make help      list the targets
#
# Each target is the downloaded file itself, so files already on disk are
# skipped. Downloads go to <file>.part and are renamed only when complete;
# an interrupted download resumes on the next run.

RAW := data/raw

# The project's virtualenv if there is one, else whatever python3 is on PATH.
PYTHON ?= $(firstword $(wildcard .venv/bin/python .venv/Scripts/python.exe) python3)
MAPS_DIR := data/interim/maps
MAPS_ARGS ?= --projection all

NE_BASE := https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson
ETOPO_URL := https://www.ngdc.noaa.gov/thredds/fileServer/global/ETOPO2022/30s/30s_surface_elev_netcdf/ETOPO_2022_v1_30s_N90W180_surface.nc

GRID_FILES := $(RAW)/01_grid/ne_50m_land.geojson $(RAW)/01_grid/ne_50m_admin_0_countries.geojson
TERRAIN_FILES := $(RAW)/02_terrain/ETOPO_2022_v1_30s_N90W180_surface.nc

# curl: follow redirects, fail on HTTP errors, retry, resume a .part file.
define download
	@mkdir -p $(dir $@)
	@echo "downloading $(notdir $@)"
	curl -L --fail --retry 5 --retry-delay 10 -C - -o $@.part $(1)
	@mv $@.part $@
endef

.PHONY: help data data-grid data-terrain data-earthdata data-temperature data-water-ice maps clean-partial

help:
	@echo "make data             all raw datasets (~3.9 GB)"
	@echo "make data-grid        step 01: Natural Earth land and countries (~5 MB)"
	@echo "make data-terrain     step 02: ETOPO 2022 elevation, 30 arc-seconds (~1.6 GB)"
	@echo "make data-earthdata   steps 03 and 04, needs an Earthdata login (~2.3 GB)"
	@echo "make data-temperature step 03: MOD11C3 monthly LST (~0.8 GB)"
	@echo "make data-water-ice   step 04: IMERG, MOD10CM, MCD12C1 (~1.4 GB)"
	@echo "make maps             control maps and report of steps 01-04 in $(MAPS_DIR)"
	@echo "                      (MAPS_ARGS=\"--only terrain\" to pass other options)"
	@echo "make clean-partial    delete unfinished *.part downloads"

data: data-grid data-terrain data-earthdata

data-grid: $(GRID_FILES)

data-terrain: $(TERRAIN_FILES)

# Earthdata products: the granule list comes from CMR, so these run the
# downloader, which skips files already on disk.
data-earthdata:
	python3 pipeline/fetch_earthdata.py

data-temperature:
	python3 pipeline/fetch_earthdata.py mod11c3

data-water-ice:
	python3 pipeline/fetch_earthdata.py imerg mod10cm mcd12c1

$(RAW)/01_grid/%.geojson:
	$(call download,$(NE_BASE)/$*.geojson)

$(RAW)/02_terrain/ETOPO_2022_v1_30s_N90W180_surface.nc:
	$(call download,$(ETOPO_URL))

# Control maps (scripts/check_maps.py): one map per variable in three
# projections, histograms, index.html and informe.md.
maps:
	$(PYTHON) scripts/check_maps.py $(MAPS_ARGS) --out $(MAPS_DIR)
	@echo ""
	@echo "Mapas listos. Abrí el índice en el navegador:"
	@echo "  file://$(abspath $(MAPS_DIR))/index.html"
	@echo "Informe para avisar a cada responsable: $(MAPS_DIR)/informe.md"

clean-partial:
	find $(RAW) -name '*.part' -delete
