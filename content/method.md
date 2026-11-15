## Qué hace

_Terra Analog Index_ es un buscador global que compara la Tierra celda por celda contra sitios lunares o marcianos para devolver un perfil de similitud por dimensión, permitiendo identificar cuáles características son bien copiadas y dónde falla la analogía. Incorpora una capa de habitabilidad para priorizar regiones con presencia documentada de extremófilos.

## Datos usados

Todos los cálculos terrestres se basan _en registros normalizados del año calendario 2024, abarcando modelos de elevación global a 1 km, temperaturas superficiales mensuales de MODIS, precipitaciones de GPM IMERG_ --- (Necesito la lista de fuentes terrestres) --- y registros de biodiversidad extrema extraídos de NCBI BioSample. Los datos correspondientes a la Luna y a Marte se obtuvieron de misiones oficiales como LRO (LOLA y Diviner), MOLA y MEDA, complementados cuando fue necesario con valores de literatura científica citados en el lugar.

## Cómo se calcula

Cada celda de 1° de la Tierra se compara con el sitio objetivo en estas dimensiones: terreno (pendiente y rugosidad), temperatura (mínima y rango diario), agua y hielo (precipitación y nieve o hielo), polvo y viento (espesor óptico del polvo y viento en superficie) e interés astrobiológico. Polvo y viento solo existe para Marte: la Luna no tiene atmósfera, así que su puntaje total no la incluye.

Cada variable física recibe un puntaje de 0 a 1 con una de tres reglas. La regla se elige sola, según dónde cae el valor del objetivo respecto de la Tierra, y queda escrita en `targets.json` para poder auditarla: la tabla de arriba muestra la que se usó en cada variable.

- **Parecido.** La Tierra cubre el valor del objetivo, así que el puntaje baja a medida que la celda se aleja de ese valor.
- **Direccional.** El objetivo está más allá de lo que alcanza la Tierra, como la temperatura mínima lunar. Se premia estar entre los lugares más extremos del planeta en esa dirección. Un 0,95 significa «más frío que el 95 % de la tierra firme con dato», no «95 % igual a la Luna».
- **Presencia o ausencia.** Para la nieve y el hielo, según si el objetivo tiene hielo o no.

Cada dimensión es el promedio de las variables que tienen dato. El **interés astrobiológico** no mide parecido con el objetivo: cuenta los registros y los tipos de extremófilos documentados en NCBI BioSample (con logaritmo, para que una celda muy muestreada no domine) y es igual para ambos objetivos.

El **puntaje total** es el promedio de las dimensiones con dato, ponderado por los pesos que mueve el visitante, y el ranking se recalcula en vivo. Una celda entra al ranking si tiene dato en al menos dos de las tres dimensiones físicas centrales (terreno, temperatura, agua y hielo); polvo y viento no cuenta para eso.

## Validación

La prueba científica más importante es que el índice vuelva a encontrar los análogos que la comunidad ya usa. Cada análogo conocido declara por qué se lo usa y si las dimensiones del índice lo cubren: uno elegido por su geología volcánica o por su aislamiento no puede ser redescubierto por un índice que no mide eso, así que se informa pero no cuenta para aprobar.

Un análogo cubierto **pasa** si su mejor celda, con los pesos iniciales, queda en el percentil 90 o más de las celdas elegibles. Un objetivo pasa si tiene al menos dos análogos cubiertos y pasan al menos dos tercios. La tabla de abajo sale de `validation.json` y muestra cada análogo con su percentil y su resultado: `pass`, `fail` o `info`.

Si un objetivo no pasa, se revisan en este orden los datos y las unidades, el recorte del objetivo, el piso del desvío y los pesos iniciales, y se documenta lo hecho. No se agregan excepciones por celda ni se ajusta hasta que «dé bien»: un resultado negativo bien explicado vale más que uno forzado.

## Límites

Estos son los límites que el método declara y que conviene tener presentes al leer un puntaje.

- **Condiciones irreplicables en la Tierra**: Algunas condiciones marcianas y lunares, como la gravedad reducida, la atmósfera marciana de CO2, o los suelos ricos en percloratos no pueden ser reproducidas en la Tierra. Ningún análogo va a ser perfecto.
- **Los puntajes direccionales no miden distancia al objetivo.** Un 0,95 en temperatura dice «entre lo más frío de la Tierra», no «95 % igual a la Luna»: la Tierra nunca llega a esos valores. La ficha de cada sitio siempre muestra el valor real del objetivo.
- **El interés astrobiológico refleja dónde se investigó.** Los sitios famosos suben y los inexplorados quedan en 0. Un lago hipersalino cuenta como evidencia de halófilos sin verificar qué se secuenció, y si un tipo supera los 5 000 registros se toman los primeros que devuelve NCBI (el manifiesto guarda el total real). Por eso el peso inicial es 0,5 y cada ficha lo aclara.
- **Los análogos «nuevos» pueden no serlo.** Una celda que no está en la lista del equipo puede estar estudiada igual; por eso se presentan como candidatos poco documentados.
- **Las celdas miden 1°.** Un cráter, un salar o una cueva se diluyen en el promedio de la celda.
- **Faltan dimensiones que el enunciado menciona:** geología y mineralogía, subsuelo y operación de rovers. Los análogos elegidos por esos motivos se informan, pero no cuentan para aprobar.
- **Polvo y viento en la Tierra salen de un reanálisis** (MERRA-2, un modelo), no de una observación, y el viento terrestre está a unos 10 m de altura mientras que Perseverance lo mide a 1,5 m.
- **Un solo año de datos** (el que indica la grilla, arriba) puede no ser representativo del clima.
- **Se usa la temperatura de superficie, no la del aire,** y el rango térmico lunar, de un ciclo de unos 29,5 días, no equivale al diurno terrestre.
- **Nieve y precipitación en los polos.** Sin luz no hay dato óptico de nieve en la noche polar, y el producto de precipitación puede ser poco fiable sobre la Antártida.

---
TODO (es así?):
- escribir sesgo de los datos biológicos: muestras concentradas en China (14.726/19.769 muestras únicas (74,5 %). Por tipo, % de China: acidófilos 97,7, termófilos 93,7, xerófilos 92,1, psicrófilos 49,7, radiorresistentes 27,9, halófilos 12,4) y los sitios famosos (aplicamos un logaritmo para atenuar?). Podrían existir lugares con extremófilos no identificados.
---

## Créditos

**Equipo sigsegv.** Juanma: repositorio y grilla, terreno, temperatura, agua y hielo, análogos conocidos, similitud, ranking, ficha y despliegue. Alan: capa biológica de NCBI, perfiles de los objetivos, puntaje, validación, mapa y esta pestaña. Santino: criterios científicos, fuentes, valores de los objetivos, términos de búsqueda, textos y pitch. Santiago: esqueleto de la app, mapas de control, README y video.

**Datos.** Las fuentes y sus licencias están en la tabla de «Datos usados». Los datos conservan sus propios términos; el código tiene licencia GNU GPL v3.

**Uso de IA.** El equipo usó Claude Code (Anthropic) como asistente de programación. Los commits en los que ayudó llevan una línea `Co-Authored-By` en el historial del repositorio. También se utilizaron Claude y Gemini para redacción y filtración temprana de literatura.
