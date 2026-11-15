## Qué hace

_Terra Analog Index_ es un buscador global que compara la Tierra celda por celda contra sitios lunares o marcianos para devolver un perfil de similitud por dimensión, permitiendo identificar cuáles características son bien copiadas y dónde falla la analogía. Incorpora una capa de habitabilidad para priorizar regiones con presencia documentada de extremófilos.

## Datos usados

Todos los cálculos terrestres se basan ''en registros normalizados del año calendario 2024, abarcando modelos de elevación global a 1 km, temperaturas superficiales mensuales de MODIS, precipitaciones de GPM IMERG y registros de biodiversidad extrema extraídos de NCBI BioSample''. Los datos correspondientes a la Luna y a Marte se obtuvieron de misiones oficiales como LRO (LOLA y Diviner), MOLA y MEDA, complementados cuando fue necesario con valores de literatura científica citados en el lugar.

## Cómo se calcula

Se utilizan distintos métodos para cada variable, incluyendo overlap (cercanía de la celda al objetivo), directional high/low (entre las celdas de la Tierra, qué porcentaje es peor que la celda en la medida) y presence/absense, para el hielo.

El puntaje de cada dimensión física es el promedio simple de sus variables con dato. El puntaje total (que ordena el ranking en vivo) es el promedio ponderado según los pesos elegidos por el usuario, calculado únicamente para celdas con datos válidos en al menos dos de las tres dimensiones físicas.

## Validación

Para comprobar la solidez científica del índice, evaluamos si el modelo logra ubicar de forma automática en el percentil 90% o superior a sitios terrestres ya consagrados por la comunidad científica como análogos lunares o marcianos. Los análogos cuya relevancia depende de variables no incluidas en esta versión (como mineralogía específica o tubos de lava) se muestran a modo informativo:

## Límites

- Condiciones irreplicables en la Tierra: Algunas condiciones marcianas y lunares, como la gravedad reducida, la atmósfera marciana de CO2, o los suelos ricos en percloratos no pueden ser reproducidas en la Tierra. Ningún análogo va a ser perfecto.
- Alcance de variables en la v1: Esta primera versión no incluye composición mineralógica, química del suelo, polvo en suspensión, dinámica eólica ni estructuras subterráneas como cuevas o tubos de lava.
- Escala espacial y temporal: las celdas promedian los datos y rasgos locales como un pequeño cráter o cueva podrían diluirse.
- 

## Créditos

Desarrollado por Juan Martín Hernández, Alan Moreno, Santiago Walter y Santino Rimondotto para el NASA International Space Apps Challenge 2026 (sede Córdoba, Argentina).

Licencia y reproducibilidad: El código fuente y el pipeline de procesamiento se distribuyen bajo licencia GPLv3.

Declaración de uso de IA: Se utilizaron herramientas de inteligencia artificial generativa como asistencia para la estructuración de la documentación técnica, código y redacción editorial, bajo supervisión y validación científica del equipo.
