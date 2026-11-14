# Raw data downloads for the pipeline (see data/raw/README.md).
#
#   make data      download everything that is missing
#   make help      list the targets
#
# Each target is the downloaded file itself, so files already on disk are
# skipped. Downloads go to <file>.part and are renamed only when complete;
# an interrupted download resumes on the next run.

RAW := data/raw

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

.PHONY: help data data-grid data-terrain clean-partial

help:
	@echo "make data          all raw datasets (~1.6 GB)"
	@echo "make data-grid     step 01: Natural Earth land and countries (~5 MB)"
	@echo "make data-terrain  step 02: ETOPO 2022 elevation, 30 arc-seconds (~1.6 GB)"
	@echo "make clean-partial delete unfinished *.part downloads"

data: data-grid data-terrain

data-grid: $(GRID_FILES)

data-terrain: $(TERRAIN_FILES)

$(RAW)/01_grid/%.geojson:
	$(call download,$(NE_BASE)/$*.geojson)

$(RAW)/02_terrain/ETOPO_2022_v1_30s_N90W180_surface.nc:
	$(call download,$(ETOPO_URL))

clean-partial:
	find $(RAW) -name '*.part' -delete
