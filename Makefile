# Terra Analog Index: everyday commands. `make help` lists them by group.
#
#   make install   .venv environment with everything (pipeline, tests and app)
#   make app       the app with the data in data/processed/
#   make data      download the missing raw data (~5.9 GB)
#   make pipeline  run steps 01 to 09 (those that are up to date are skipped)
#   make check     everything that must pass before merging into main
#
# Downloads use the file itself as the target: whatever is already on disk is skipped. They are downloaded
# to <file>.part and renamed only when finished; an interrupted download resumes on the next run.
# ETOPO is also checked against its exact size: its server sends no Content-Length, so curl cannot
# tell a dropped connection from the end of the file.

RAW := data/raw

# Credentials from the local .env (not tracked), one per line as NAME=value, without quotes.
# Read by data-earthdata (EARTHDATA_USERNAME, EARTHDATA_PASSWORD) and step 05 (NCBI_EMAIL, NCBI_API_KEY).
-include .env
export EARTHDATA_USERNAME EARTHDATA_PASSWORD NCBI_EMAIL NCBI_API_KEY

# The .venv environment's Python if it exists; otherwise python3 from PATH.
PYTHON ?= $(firstword $(wildcard .venv/bin/python .venv/Scripts/python.exe) python3)
# The environment's own, to create it and install into it.
VENV_PY := $(if $(filter Windows_NT,$(OS)),.venv/Scripts/python.exe,.venv/bin/python)

MAPS_DIR := data/interim/maps
MAPS_ARGS ?= --projection all

# Pipeline step options: make pipeline FORCE=1 BBOX="-30 -20 -75 -65"
STEP_ARGS = $(if $(FORCE),--force) $(if $(BBOX),--bbox $(BBOX))
STEPS := $(sort $(wildcard pipeline/0[1-9]_*.py))

NE_BASE := https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson
ETOPO_URL := https://www.ngdc.noaa.gov/thredds/fileServer/global/ETOPO2022/30s/30s_surface_elev_netcdf/ETOPO_2022_v1_30s_N90W180_surface.nc
# Exact size according to the THREDDS catalog (the file's dataSize).
ETOPO_BYTES := 1642335281

LOLA_URL := https://pgda.gsfc.nasa.gov/data/LOLA_20mpp/LDEM_80S_80MPP_ADJ.TIF

GRID_FILES := $(RAW)/01_grid/ne_50m_land.geojson $(RAW)/01_grid/ne_50m_admin_0_countries.geojson
TERRAIN_FILES := $(RAW)/02_terrain/ETOPO_2022_v1_30s_N90W180_surface.nc
MOON_FILES := $(RAW)/07_targets/LDEM_80S_80MPP_ADJ.TIF

# curl: follows redirects, fails on HTTP errors, retries and resumes a .part.
define download
	@mkdir -p $(dir $@)
	@echo "downloading $(notdir $@)"
	curl -L --fail --retry 5 --retry-delay 10 -C - -o $@.part $(1)
	@mv $@.part $@
endef

# Same, for a server without Content-Length: resumes until the .part has exactly $(2)
# bytes (up to 20 attempts) and then renames it.
define download_sized
	@mkdir -p $(dir $@)
	@echo "downloading $(notdir $@) ($(2) bytes)"
	@n=0; while [ $$(( $$(if [ -f $@.part ]; then wc -c < $@.part; else echo 0; fi) )) -lt $(2) ]; do \
	  n=$$((n + 1)); \
	  if [ $$n -gt 20 ]; then echo "$(notdir $@): still incomplete after 20 attempts; run make again to resume"; exit 1; fi; \
	  curl -L --fail --retry 5 --retry-delay 10 -C - -o $@.part $(1) || sleep 10; \
	done
	@size=$$(( $$(wc -c < $@.part) )); if [ $$size -ne $(2) ]; then \
	  echo "$(notdir $@): $$size bytes, expected $(2); delete $@.part and run make again"; exit 1; fi
	@mv $@.part $@
endef

.PHONY: help venv install install-app app app-demo test fixtures \
	data data-grid data-terrain data-earthdata data-moon data-temperature data-water-ice data-dust-wind \
	pipeline maps cards check-data check-secrets check clean clean-partial

help:
	@echo "Setup"
	@echo "  make install          .venv environment with pipeline, tests and app"
	@echo "  make install-app      .venv environment with the app only (lightweight)"
	@echo ""
	@echo "App"
	@echo "  make app              the app with data/processed/"
	@echo "  make app-demo         the app with the test data (nothing to download)"
	@echo ""
	@echo "Raw data"
	@echo "  make data             all the raw data (~5.9 GB)"
	@echo "  make data-grid        step 01: Natural Earth, land and countries (~5 MB)"
	@echo "  make data-terrain     step 02: ETOPO 2022 elevation, 30 arc-seconds (~1.6 GB)"
	@echo "  make data-earthdata   steps 03 and 04, needs an Earthdata account (~4.1 GB)"
	@echo "  make data-temperature step 03: MOD11C3, monthly temperature (~0.8 GB)"
	@echo "  make data-water-ice   step 04: IMERG, MOD10CM, MCD12C1 (~1.4 GB)"
	@echo "  make data-dust-wind   step 04: MERRA-2, dust and wind (~1.8 GB)"
	@echo "  make data-moon        step 07: lunar south pole elevation, LOLA 80 m (~190 MB)"
	@echo "                        (Mars, MOLA, is read over HTTP: no download needed)"
	@echo ""
	@echo "Pipeline"
	@echo "  make pipeline         steps 01 to 09 in order; stops at the first one that fails"
	@echo "  make step-08          a single step (01 to 09; step-04 runs both 04 steps)"
	@echo "                        FORCE=1 runs even if up to date; BBOX=\"LATMIN LATMAX LONMIN LONMAX\" limits the region"
	@echo "  make maps             control maps for steps 01 to 04 in $(MAPS_DIR)"
	@echo "                        (MAPS_ARGS=\"--only terrain\" to pass other options)"
	@echo ""
	@echo "Checks"
	@echo "  make test             all the tests"
	@echo "  make cards            checks the texts in content/cards/ and says what each one is missing"
	@echo "  make check-data       data/processed/ complete, valid and under 50 MB"
	@echo "  make check-secrets    keys and email addresses in the files and in the history"
	@echo "  make check            the four above, before merging into main"
	@echo ""
	@echo "Cleanup"
	@echo "  make fixtures         regenerates the test data in tests/fixtures/"
	@echo "  make clean            Python and pytest caches, and control maps"
	@echo "  make clean-partial    deletes half-finished downloads (*.part)"

# --- Setup --------------------------------------------------------------------

$(VENV_PY):
	python3 -m venv .venv

venv: $(VENV_PY)

install: $(VENV_PY)
	$(VENV_PY) -m pip install -r requirements-pipeline.txt

install-app: $(VENV_PY)
	$(VENV_PY) -m pip install -r requirements.txt

# --- App ----------------------------------------------------------------------

app:
	$(PYTHON) -m streamlit run streamlit_app.py

app-demo:
	TAI_DATA_DIR=tests/fixtures $(PYTHON) -m streamlit run streamlit_app.py

# --- Raw data ------------------------------------------------------------------

data: data-grid data-terrain data-earthdata data-moon

data-grid: $(GRID_FILES)

# Also checks a file that is already on disk: one renamed before the size check existed
# may be truncated.
data-terrain: $(TERRAIN_FILES)
	@size=$$(( $$(wc -c < $<) )); if [ $$size -ne $(ETOPO_BYTES) ]; then \
	  echo "$<: $$size bytes, expected $(ETOPO_BYTES) (incomplete download)."; \
	  echo "To resume it: mv $< $<.part && make data-terrain"; exit 1; fi

# Earthdata products: the file list comes from CMR, so this runs the downloader,
# which skips the files already on disk.
data-earthdata:
	$(PYTHON) pipeline/fetch_earthdata.py

data-temperature:
	$(PYTHON) pipeline/fetch_earthdata.py mod11c3

data-water-ice:
	$(PYTHON) pipeline/fetch_earthdata.py imerg mod10cm mcd12c1

data-dust-wind:
	$(PYTHON) pipeline/fetch_earthdata.py m2aer m2flx

data-moon: $(MOON_FILES)

$(RAW)/01_grid/%.geojson:
	$(call download,$(NE_BASE)/$*.geojson)

$(RAW)/02_terrain/ETOPO_2022_v1_30s_N90W180_surface.nc:
	$(call download_sized,$(ETOPO_URL),$(ETOPO_BYTES))

$(RAW)/07_targets/LDEM_80S_80MPP_ADJ.TIF:
	$(call download,$(LOLA_URL))

# --- Pipeline -------------------------------------------------------------------

# Each step decides by itself whether it is up to date (its outputs are newer than its inputs and its
# code) and then does nothing. Exit codes: 0 fine, 1 invalid output, 2 a missing input.
pipeline:
	@for s in $(STEPS); do \
	  echo "== $$s $(STEP_ARGS)"; \
	  $(PYTHON) $$s $(STEP_ARGS) || { code=$$?; echo "$$s finished with code $$code"; exit $$code; }; \
	done

# step-04 runs both 04 steps (04_dust_wind and 04_water_ice); step-04_water_ice, only that one.
step-%:
	@steps=$$(ls pipeline/$*.py pipeline/$*_*.py 2>/dev/null | sort -u); \
	if [ -z "$$steps" ]; then echo "There is no step $* (they go from 01 to 09)"; exit 1; fi; \
	for s in $$steps; do \
	  echo "== $$s $(STEP_ARGS)"; \
	  $(PYTHON) $$s $(STEP_ARGS) || exit $$?; \
	done

# Control maps (scripts/check_maps.py): one map per variable in three projections,
# histograms, index.html and report.md.
maps:
	$(PYTHON) scripts/check_maps.py $(MAPS_ARGS) --out $(MAPS_DIR)
	@echo ""
	@echo "Maps ready. Open the index in the browser:"
	@echo "  file://$(abspath $(MAPS_DIR))/index.html"
	@echo "Report to notify each owner: $(MAPS_DIR)/report.md"

# --- Checks ---------------------------------------------------------------------

test:
	$(PYTHON) -m pytest -q

cards:
	$(PYTHON) scripts/check_cards.py

# Loading the full bundle the way the app does fails with the name of any file that is missing
# or breaks its contract; then, the contract tests on the real data and the size.
check-data:
	$(PYTHON) -c "from tai.io import load_bundle; load_bundle('data/processed'); print('data/processed: fully loaded')"
	$(PYTHON) -m pytest -q tests/test_contracts.py

check-secrets:
	sh scripts/check_secrets.sh

check: test cards check-data check-secrets
	@echo ""
	@echo "All good."

# --- Cleanup --------------------------------------------------------------------

fixtures:
	$(PYTHON) tests/fixtures/make_fixtures.py

# Never touches data/raw/ or data/processed/.
clean:
	find . -path ./.venv -prune -o -type d -name __pycache__ -exec rm -rf {} +
	rm -rf .pytest_cache $(MAPS_DIR)

clean-partial:
	find $(RAW) -name '*.part' -delete
