# Publicar la app en Google Cloud Run con dominio propio

La app (`streamlit_app.py`) corre en **Cloud Run** dentro de un contenedor. La imagen lleva el código y
`data/processed/` (unos 2 MB), así que no hace falta base de datos ni bucket. El pipeline, los tests y los
datos crudos no entran en la imagen (`.dockerignore` y `.gcloudignore`).

> No se necesita ninguna API key en producción: la app solo lee `data/processed/`. Las claves de NCBI y
> Earthdata son del pipeline y no van en el repo ni en la imagen.

## Lo que tiene que hacer una persona del equipo

Son cuentas, tarjeta y pagos. No se delegan a un agente.

1. **Reclamar los US$ 300 de crédito de Google Cloud** con una cuenta de Google del equipo. Suele pedir una
   tarjeta para verificar la identidad.
2. **Poner una alerta de presupuesto** (Facturación → Presupuestos y alertas), por ejemplo en US$ 20, para
   enterarse si algo se dispara.
3. **Reclamar el dominio gratis en GoDaddy** (por ejemplo `nasa-tai.earth`). Cuando se revisó, ese nombre no estaba registrado.
4. Instalar la CLI de Google Cloud: <https://cloud.google.com/sdk/docs/install>

## Primer despliegue

Se corre desde la raíz del repo, en la rama `develop` actualizada. Cambiar `PROJECT_ID` por el id del proyecto.

```bash
gcloud auth login
gcloud projects create PROJECT_ID --name "Terra Analog Index"
gcloud config set project PROJECT_ID
```

Vincular el proyecto a la cuenta de facturación que tiene el crédito (Consola → Facturación). Después:

```bash
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com
```

```bash
gcloud run deploy terra-analog-index \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --memory 1Gi --cpu 1 \
  --concurrency 10 \
  --min-instances 0 --max-instances 3 \
  --session-affinity \
  --timeout 3600
```

- `--source .` arma la imagen con el `Dockerfile` en Cloud Build y la guarda en Artifact Registry. La primera
  vez pide crear el repositorio `cloud-run-source-deploy`; hay que contestar que sí.
- `--allow-unauthenticated` hace pública la URL. Si la organización lo bloquea, ver el último apartado.
- `--session-affinity` y `--timeout 3600` ayudan a Streamlit, que usa una conexión websocket por visitante.
- Memoria: con una sesión la app llega a unos 270 MB; 1 GiB deja margen para varios visitantes a la vez.
- La región `us-central1` está entre las que admiten mapeo directo de dominios (ver abajo).

Al terminar, la CLI imprime la URL del servicio (`https://terra-analog-index-…run.app`). Abrirla y probar los
tres mapas y el cambio de objetivo.

Para volver a publicar después de un cambio, se corre el mismo comando. Cada despliegue crea una revisión
nueva y la anterior queda disponible para volver atrás desde la consola.

## Dominio propio

Hay tres caminos. Para una demo de hackatón alcanza el primero:

1. **Mapeo de dominio de Cloud Run** (`gcloud beta run domain-mappings`). Es el más corto, pero Google lo marca
   como vista previa: dice que no está listo para producción por problemas de latencia. Solo funciona en
   algunas regiones (`us-central1` sí) y el certificado HTTPS tarda entre 15 minutos y 24 horas.
2. **Balanceador de carga HTTP(S) global** delante del servicio. Es lo que Google recomienda para producción,
   pero tiene más pasos y costo propio.
3. **Firebase Hosting** con una regla de reescritura hacia el servicio.

### Camino 1, paso a paso

1. Verificar la propiedad del dominio en Google Search Console (agrega un registro TXT en el DNS de GoDaddy).
2. Crear el mapeo:

   ```bash
   gcloud beta run domain-mappings create --service terra-analog-index --domain nasa-tai.earth --region us-central1
   ```

3. Pedir los registros DNS que hay que cargar:

   ```bash
   gcloud beta run domain-mappings describe --domain nasa-tai.earth --region us-central1
   ```

   Se copian los registros de `resourceRecords` tal cual (tipo A, AAAA o CNAME) en el panel DNS de GoDaddy.
   `@` es el dominio raíz y `www` el subdominio.
4. Esperar a que el estado del mapeo pase a certificado emitido. Los cambios de DNS pueden tardar de minutos
   a unas horas.

Si el dominio usa registros CAA, tienen que autorizar `pki.goog` y `letsencrypt.org`.

## Costos y cuidados

- Con `--min-instances 0` no hay instancia encendida cuando nadie entra, y el primer visitante espera unos
  segundos de arranque. Para el día de la exposición conviene dejar una instancia siempre lista y volver a
  apagarla después:

  ```bash
  gcloud run services update terra-analog-index --region us-central1 --min-instances 1
  gcloud run services update terra-analog-index --region us-central1 --min-instances 0
  ```

- `--max-instances 3` pone un techo al gasto si llega mucho tráfico.
- Cada vez que se redibuja el mapa, la app manda unos 4 MB al navegador. Con buena conexión no se nota; con
  una conexión lenta el mapa puede tardar en aparecer.

## Probar la imagen en la propia máquina

Con Docker Desktop abierto:

```bash
docker build -t tai-app .
docker run --rm -p 8080:8080 tai-app
```

Abrir <http://localhost:8080>. Con `-e PORT=9000 -p 9000:9000` se prueba que la app respeta `$PORT`, que es como
Cloud Run indica el puerto.

## Si algo falla

- **El despliegue pide permisos:** la cuenta que despliega necesita los roles Cloud Run Source Developer,
  Service Usage Consumer y Service Account User; Cloud Build usa el rol Cloud Run Builder. Si es dueña del
  proyecto, ya los tiene. Los permisos nuevos pueden tardar unos minutos en aplicarse.
- **`--allow-unauthenticated` es rechazado:** una política de la organización (compartir solo con el dominio)
  puede bloquear los servicios públicos. En una cuenta personal no pasa.
- **La app muestra "No se pueden cargar los datos":** la imagen no incluyó `data/processed/`. Revisar que
  `.dockerignore` y `.gcloudignore` no la excluyan.
- **Los logs:** `gcloud run services logs read terra-analog-index --region us-central1`.
