# Prueba de punta a punta (TAI-38), parte local

Lista 12.3 del diseño recorrida el 15 de noviembre de 2026 sobre `develop` en el commit `7da9f8d`, con los datos reales
de `data/processed/`. Equipo de prueba: Windows 10, Python 3.13, Streamlit 1.67.0, Microsoft Edge en ventana privada
(sin interfaz, 1500 × 1000 salvo donde se indica).

**Resultado: los 11 ítems pasan en local y no apareció ninguna falla que bloquee la demo.** Quedan tres cosas que solo se
pueden comprobar con la app desplegada o en la laptop de la presentación (última columna) y cuatro observaciones que no
bloquean.

| # | Ítem | Resultado | Cómo se comprobó | Falta |
|---|------|-----------|------------------|-------|
| 1 | La app abre en ventana privada en menos de 10 s | Pasa | 2,5 s hasta que aparece el mapa con el servidor encendido; 3,3 s con el servidor recién arrancado, que además tarda 1,7 s en responder | Con el link desplegado, y con la app «dormida» (riesgo 12 del diseño) |
| 2 | Cambiar de objetivo cambia mapa, ranking y limpia la ficha | Pasa | AppTest: cambia la primera celda del ranking y vuelve el aviso «Elegí una fila…». En el navegador: 325 a 330 ms del clic al mapa nuevo | |
| 3 | Cada slider recalcula en menos de 1 s | Pasa | AppTest: 219 a 231 ms por recálculo en el servidor. En el navegador, el caso más pesado (cambiar de objetivo, que rehace todo el mapa) tarda 0,33 s de punta a punta | Con el link desplegado (latencia de red). No se automatizó arrastrar un slider real en el navegador |
| 4 | Todos los pesos en 0 muestran el aviso, sin error | Pasa | AppTest: aparece «Subí al menos un peso», sin excepciones | Verlo una vez a mano en el navegador |
| 5 | «Ocultar análogos conocidos» los quita del ranking | Pasa | En el ranking de Marte, 4 de las 100 primeras celdas eran análogos conocidos; con la casilla, ninguna | |
| 6 | Las tres vistas del mapa funcionan; en «Polo sur» se ve la Antártida completa | Pasa | Las tres se dibujan sin excepciones. La captura de «Polo sur» muestra la Antártida entera | |
| 7 | Las 3 finalistas muestran su texto manual y sus fuentes | Pasa | 61661 (Luna), 46351 y 25671 (Marte): título, texto y sección «Fuentes» en la ficha | |
| 8 | Una celda sin registros biológicos muestra la aclaración de muestreo | Pasa | Celda 6467: aparece «La falta de registros puede deberse a que nadie tomó muestras acá…» | |
| 9 | La pestaña Método muestra la tabla de validación | Pasa | Dos tablas, 9 de 9 análogos, con `pass`, `fail` e `info` como en `validation.json` | |
| 10 | Se ve bien en 1366 × 768 y en un proyector | Pasa, con observaciones 1 y 2 | 1366 × 768, 1280 × 720 y 1024 × 768: sin scroll horizontal, mapa dibujado, sin excepciones | Un proyector real |
| 11 | Funciona con el wifi apagado en modo local | Pasa en simulación | Con todos los nombres de dominio externos bloqueados (solo `localhost`), el mapa aparece en 2,2 s y sin excepciones. Los 113 recursos de la página salen de `localhost` | Probar con el wifi realmente apagado en la laptop de la presentación |

## Fallas y observaciones, por prioridad

**Bloquean la demo:** ninguna.

**No bloquean:**

1. **El ranking y la ficha quedan debajo de la primera pantalla en 1366 × 768 y en 1024 × 768.** Hay que bajar con la
   rueda para verlos. Para el ensayo: bajar el zoom del navegador al 80 o 90 % o reducir la altura del mapa (520 px en
   `ui/map_view.py`). Para reproducirlo: abrir la app y achicar la ventana a ese tamaño.
2. **En 1024 × 768 el mapa mide 564 px de ancho.** Se lee, pero es chico. Es lo que se vería en un proyector de 4:3.
3. **`scripts/check_cards.py` se rompe en consolas de Windows con la codificación por defecto,** porque imprime «✓». Se
   resuelve con `PYTHONIOENCODING=utf-8` o corriéndolo desde Git Bash. No afecta a la app.
4. **En esta PC fallan 4 tests del pipeline** (`pyhdf`, `geopandas` y un conflicto de PROJ con PostgreSQL). Son
   librerías que faltan, no un problema de la app; hay que correr `make test` en la laptop de la presentación para
   confirmar.

## Cómo repetirla

```bash
python scripts/e2e_local.py     # los ítems 2 a 9, con AppTest y los datos reales; sale con código 1 si algo falla
```

El resto (tiempos de carga, pantallas, wifi apagado) se mide a mano, como arriba. Conviene repetir todo después de
cualquier cambio de último momento, por ejemplo la dimensión de polvo y viento (TAI-52), que toca el mapa, los pesos y
los textos del método.
