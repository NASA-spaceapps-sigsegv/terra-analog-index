# Imagen de la app para Cloud Run (guía: docs/deploy_gcp.md).
# Lleva solo lo que la app lee al correr: el código, la config de Streamlit, content/ y data/processed/.
# El pipeline, los tests y los datos crudos no entran (ver .dockerignore).
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Primero las dependencias: mientras requirements.txt no cambie, esta capa se reutiliza.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY .streamlit ./.streamlit
COPY streamlit_app.py ./
COPY tai ./tai
COPY ui ./ui
COPY content ./content
COPY data/processed ./data/processed

RUN useradd --create-home --uid 10001 app && chown -R app /app
USER app

# Cloud Run indica el puerto en $PORT (8080 por defecto). `exec` para que SIGTERM llegue a Streamlit.
ENV PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "exec streamlit run streamlit_app.py --server.port=${PORT} --server.address=0.0.0.0 --server.headless=true --browser.gatherUsageStats=false"]
