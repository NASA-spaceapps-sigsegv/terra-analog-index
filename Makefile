# Terra Analog Index: comandos del día a día. `make help` los lista agrupados.
#
#   make install   entorno .venv con todo (pipeline, pruebas y app)
#   make app       la app con los datos de data/processed/
#   make data      bajar los datos crudos que falten (~4,1 GB)
#   make pipeline  correr los pasos 01 a 09 (los que están al día se saltean)
#   make check     todo lo que tiene que pasar antes de integrar a main
#
# Las descargas son el archivo mismo como objetivo: lo que ya está en disco se saltea. Se bajan a
# <archivo>.part y se renombran solo al terminar; una descarga cortada se retoma en la próxima corrida.
# ETOPO además se controla contra su tamaño exacto: su servidor no manda Content-Length, así que curl
# no distingue una conexión cortada del final del archivo.

RAW := data/raw

# Credenciales del .env local (no se versiona), una por línea como NOMBRE=valor, sin comillas.
# Las leen data-earthdata (EARTHDATA_USERNAME, EARTHDATA_PASSWORD) y el paso 05 (NCBI_EMAIL, NCBI_API_KEY).
-include .env
export EARTHDATA_USERNAME EARTHDATA_PASSWORD NCBI_EMAIL NCBI_API_KEY

# Python del entorno .venv si existe; si no, el python3 del PATH.
PYTHON ?= $(firstword $(wildcard .venv/bin/python .venv/Scripts/python.exe) python3)
# El del entorno, para crearlo e instalar en él.
VENV_PY := $(if $(filter Windows_NT,$(OS)),.venv/Scripts/python.exe,.venv/bin/python)

MAPS_DIR := data/interim/maps
MAPS_ARGS ?= --projection all

# Opciones de los pasos del pipeline: make pipeline FORCE=1 BBOX="-30 -20 -75 -65"
STEP_ARGS = $(if $(FORCE),--force) $(if $(BBOX),--bbox $(BBOX))
STEPS := $(sort $(wildcard pipeline/0[1-9]_*.py))

NE_BASE := https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson
ETOPO_URL := https://www.ngdc.noaa.gov/thredds/fileServer/global/ETOPO2022/30s/30s_surface_elev_netcdf/ETOPO_2022_v1_30s_N90W180_surface.nc
# Tamaño exacto según el catálogo THREDDS (dataSize del archivo).
ETOPO_BYTES := 1642335281

LOLA_URL := https://pgda.gsfc.nasa.gov/data/LOLA_20mpp/LDEM_80S_80MPP_ADJ.TIF

GRID_FILES := $(RAW)/01_grid/ne_50m_land.geojson $(RAW)/01_grid/ne_50m_admin_0_countries.geojson
TERRAIN_FILES := $(RAW)/02_terrain/ETOPO_2022_v1_30s_N90W180_surface.nc
MOON_FILES := $(RAW)/07_targets/LDEM_80S_80MPP_ADJ.TIF

# curl: sigue redirecciones, falla con errores HTTP, reintenta y retoma un .part.
define download
	@mkdir -p $(dir $@)
	@echo "downloading $(notdir $@)"
	curl -L --fail --retry 5 --retry-delay 10 -C - -o $@.part $(1)
	@mv $@.part $@
endef

# Igual, para un servidor sin Content-Length: retoma hasta que el .part tenga exactamente $(2)
# bytes (hasta 20 intentos) y después lo renombra.
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
	data data-grid data-terrain data-earthdata data-moon data-temperature data-water-ice \
	pipeline maps cards check-data check-secrets check clean clean-partial

help:
	@echo "Instalación"
	@echo "  make install          entorno .venv con pipeline, pruebas y app"
	@echo "  make install-app      entorno .venv solo con la app (liviano)"
	@echo ""
	@echo "App"
	@echo "  make app              la app con data/processed/"
	@echo "  make app-demo         la app con los datos de prueba (no hace falta bajar nada)"
	@echo ""
	@echo "Datos crudos"
	@echo "  make data             todos los datos crudos (~4,1 GB)"
	@echo "  make data-grid        paso 01: Natural Earth, tierra y países (~5 MB)"
	@echo "  make data-terrain     paso 02: elevación ETOPO 2022, 30 segundos de arco (~1,6 GB)"
	@echo "  make data-earthdata   pasos 03 y 04, necesita usuario de Earthdata (~2,3 GB)"
	@echo "  make data-temperature paso 03: MOD11C3, temperatura mensual (~0,8 GB)"
	@echo "  make data-water-ice   paso 04: IMERG, MOD10CM, MCD12C1 (~1,4 GB)"
	@echo "  make data-moon        paso 07: elevación del polo sur lunar, LOLA 80 m (~190 MB)"
	@echo "                        (Marte, MOLA, se lee por HTTP: no hace falta bajarlo)"
	@echo ""
	@echo "Pipeline"
	@echo "  make pipeline         pasos 01 a 09 en orden; se detiene en el primero que falla"
	@echo "  make step-08          un solo paso (cualquier número de 01 a 09)"
	@echo "                        FORCE=1 corre aunque esté al día; BBOX=\"LATMIN LATMAX LONMIN LONMAX\" limita la región"
	@echo "  make maps             mapas de control de los pasos 01 a 04 en $(MAPS_DIR)"
	@echo "                        (MAPS_ARGS=\"--only terrain\" para pasar otras opciones)"
	@echo ""
	@echo "Controles"
	@echo "  make test             todas las pruebas"
	@echo "  make cards            revisa los textos de content/cards/ y dice qué le falta a cada uno"
	@echo "  make check-data       data/processed/ completo, válido y por debajo de 50 MB"
	@echo "  make check-secrets    claves y correos en los archivos y en el historial"
	@echo "  make check            los cuatro anteriores, antes de integrar a main"
	@echo ""
	@echo "Limpieza"
	@echo "  make fixtures         regenera los datos de prueba de tests/fixtures/"
	@echo "  make clean            cachés de Python y pytest, y mapas de control"
	@echo "  make clean-partial    borra descargas a medias (*.part)"

# --- Instalación --------------------------------------------------------------

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

# --- Datos crudos ---------------------------------------------------------------

data: data-grid data-terrain data-earthdata data-moon

data-grid: $(GRID_FILES)

# También controla un archivo que ya está en disco: uno renombrado antes de que existiera el
# control de tamaño puede estar cortado.
data-terrain: $(TERRAIN_FILES)
	@size=$$(( $$(wc -c < $<) )); if [ $$size -ne $(ETOPO_BYTES) ]; then \
	  echo "$<: $$size bytes, expected $(ETOPO_BYTES) (incomplete download)."; \
	  echo "To resume it: mv $< $<.part && make data-terrain"; exit 1; fi

# Productos de Earthdata: la lista de archivos sale de CMR, así que esto corre el descargador,
# que saltea los archivos que ya están en disco.
data-earthdata:
	$(PYTHON) pipeline/fetch_earthdata.py

data-temperature:
	$(PYTHON) pipeline/fetch_earthdata.py mod11c3

data-water-ice:
	$(PYTHON) pipeline/fetch_earthdata.py imerg mod10cm mcd12c1

data-moon: $(MOON_FILES)

$(RAW)/01_grid/%.geojson:
	$(call download,$(NE_BASE)/$*.geojson)

$(RAW)/02_terrain/ETOPO_2022_v1_30s_N90W180_surface.nc:
	$(call download_sized,$(ETOPO_URL),$(ETOPO_BYTES))

$(RAW)/07_targets/LDEM_80S_80MPP_ADJ.TIF:
	$(call download,$(LOLA_URL))

# --- Pipeline -------------------------------------------------------------------

# Cada paso decide solo si está al día (sus salidas son más nuevas que sus entradas y su código) y
# entonces no hace nada. Códigos de salida: 0 bien, 1 salida inválida, 2 falta una entrada.
pipeline:
	@for s in $(STEPS); do \
	  echo "== $$s $(STEP_ARGS)"; \
	  $(PYTHON) $$s $(STEP_ARGS) || { code=$$?; echo "$$s terminó con código $$code"; exit $$code; }; \
	done

step-%:
	@s=$$(ls pipeline/$*_*.py 2>/dev/null | head -n 1); \
	if [ -z "$$s" ]; then echo "No hay paso $* (van de 01 a 09)"; exit 1; fi; \
	echo "== $$s $(STEP_ARGS)"; \
	$(PYTHON) $$s $(STEP_ARGS)

# Mapas de control (scripts/check_maps.py): un mapa por variable en tres proyecciones,
# histogramas, index.html e informe.md.
maps:
	$(PYTHON) scripts/check_maps.py $(MAPS_ARGS) --out $(MAPS_DIR)
	@echo ""
	@echo "Mapas listos. Abrí el índice en el navegador:"
	@echo "  file://$(abspath $(MAPS_DIR))/index.html"
	@echo "Informe para avisar a cada responsable: $(MAPS_DIR)/informe.md"

# --- Controles ------------------------------------------------------------------

test:
	$(PYTHON) -m pytest -q

cards:
	$(PYTHON) scripts/check_cards.py

# Cargar el paquete completo como lo hace la app falla con el nombre de cualquier archivo que falte
# o no cumpla su contrato; después, las pruebas de contratos sobre los datos reales y el tamaño.
check-data:
	$(PYTHON) -c "from tai.io import load_bundle; load_bundle('data/processed'); print('data/processed: carga completa')"
	$(PYTHON) -m pytest -q tests/test_contracts.py

check-secrets:
	sh scripts/check_secrets.sh

check: test cards check-data check-secrets
	@echo ""
	@echo "Todo en orden."

# --- Limpieza -------------------------------------------------------------------

fixtures:
	$(PYTHON) tests/fixtures/make_fixtures.py

# Nunca toca data/raw/ ni data/processed/.
clean:
	find . -path ./.venv -prune -o -type d -name __pycache__ -exec rm -rf {} +
	rm -rf .pytest_cache $(MAPS_DIR)

clean-partial:
	find $(RAW) -name '*.part' -delete
