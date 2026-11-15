# AGENTS.md: reglas para agentes de código en Terra Analog Index

Proyecto del hackathon NASA Space Apps 2026 (desafío de análogos terrestres de la Luna y Marte).
Equipo: Juanma, Alan, Santiago y Santino. Cada ticket (`TAI-NN`) tiene un responsable.
Quien te lanza es el responsable del ticket: trabajás para esa persona, no para el resto del equipo.

## Antes de empezar

1. Leé el ticket que te dieron completo, con sus criterios de aceptación.
2. Leé el código que vas a tocar y sus pruebas. No asumas nombres de columnas ni de funciones: están en `tai/schemas.py`, `tai/models.py` y `tai/constants.py`.
3. Si el ticket choca con algo del código o del diseño, parate y preguntá. No inventes un contrato.

## Entorno

- Python 3.11. En Windows, el intérprete del entorno es `.venv\Scripts\python.exe`.
- Pruebas: `python -m pytest -q`. En Windows fallan 2 pruebas conocidas por falta de `pyhdf` (`test_read_hdf4_layer_*`). No las borres ni las "arregles": avisá y seguí.
- Streamlit: `streamlit run streamlit_app.py`. Con datos de prueba, apuntá la variable de entorno de la carpeta de datos a `tests/fixtures`.

## Git

- Una rama por ticket, siempre desde `develop` actualizado: `tai-NN-slug` (por ejemplo `tai-31-ranking`).
- Nunca hagas commit directo en `main` ni en `develop`. Nunca `push --force`. Nunca hagas merge: lo hace una persona.
- Commits chicos, con mensaje `feat(tai-NN): ...`, `fix(tai-NN): ...` o `test(tai-NN): ...`.
- Agregá al final de cada mensaje de commit la línea `AI-assisted: <nombre del agente>`. El equipo tiene que poder declarar el uso de IA en la entrega (TAI-03).
- No abras el Pull Request salvo que te lo pidan. Si te lo piden: base `develop`, descripción corta con lo que cambió y cómo se probó.

## Arquitectura (documento de diseño, sección 8.4)

- `tai/` no importa `streamlit`, `ui/` ni `pipeline/`. No hace red ni escribe archivos. Se prueba con pytest solo.
- `ui/` solo dibuja. Importa `tai.services` y `tai.constants`. No lee archivos ni calcula puntajes por su cuenta.
- `pipeline/` importa `tai.constants`, `tai.geo`, `tai.rules` y `tai.scoring`. Las fórmulas existen una sola vez.
- La app solo lee `data/processed/`: nunca descarga, nunca escribe, nunca llama a NCBI.
- `requirements.txt` es solo lo que usa la app. Lo pesado va en `requirements-pipeline.txt`. No agregues dependencias sin preguntar.

## Datos y ciencia

- Un dato faltante es `null` (en pandas, NaN) de punta a punta: nunca lo conviertas en 0 ni en un promedio. En JSON, `null`, nunca `NaN`.
- No hay aleatoriedad en el pipeline: las mismas entradas dan las mismas salidas.
- Toda cifra que ve el visitante tiene fuente. Si escribís un texto científico sin fuente, marcalo como hipótesis.
- Nunca digas que un sitio "es igual" o "idéntico" a la Luna o a Marte.
- La interfaz va en español. Identificadores, columnas, funciones y claves JSON, en inglés.

## No toques

- `data/processed/*` ni `data/interim/*`: los generan los pasos del pipeline.
- `config/*` y `content/*`: los edita Santino a mano.
- Valores de `tai/constants.py`, salvo que el ticket lo pida.
- Archivos de tickets que no son el tuyo, aunque veas algo mejorable. Anotalo en la descripción y seguí.

## Secretos

- No leas ni escribas `.env`. `NCBI_API_KEY`, `NCBI_EMAIL` y las claves de modelos no van en ningún archivo, log ni commit.
- Antes de cada commit, revisá `git diff --staged` y buscá claves, tokens y correos personales.

## Terminado significa

Criterios de aceptación del ticket cumplidos, `python -m pytest -q` en verde (salvo las 2 conocidas) y el cambio limitado al ticket. Al terminar, resumí qué cambiaste, qué probaste y qué quedó sin hacer.
