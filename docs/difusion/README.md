# Póster A3 y tríptico A4

Material impreso para mostrar el proyecto al jurado. Todas las cifras salen de `data/processed/` con los pesos
iniciales; el generador falla en vez de imprimir un número viejo si, por ejemplo, cambia el puesto de una finalista.

| Archivo | Qué es |
|---------|--------|
| `poster_A3.pdf` | Póster vertical de 297 × 420 mm, una página. Es el archivo para imprimir. |
| `poster_A3.png` | La misma página como imagen, para compartir por chat. |
| `triptico_A4.pdf` | Tríptico en dos hojas A4 apaisadas: la hoja 1 es el afuera (solapa, contratapa y portada) y la hoja 2 es el adentro. |
| `triptico_afuera.png`, `triptico_adentro.png` | Cada hoja como imagen. |
| `fuente/` | El generador (`build.py`), los estilos (`estilos.css`) y los logos. |

## Cómo imprimir el tríptico

Doble faz, **volteando por el borde corto**, a tamaño real (sin «ajustar a la página»). Se dobla en tres: la solapa de la
hoja 1 (a la izquierda) entra primero y la portada queda arriba. Esa solapa mide 97 mm, tres menos que los otros
paneles, para que cierre sin arrugarse. Los textos están a más de 9 mm de cada pliegue. Conviene probar una hoja en papel
antes de imprimir todas, para ver colores y márgenes.

## Cómo regenerarlos

Hace falta Microsoft Edge (imprime el HTML a PDF) y las tipografías Bahnschrift y Segoe UI, que vienen con Windows.

```bash
.venv/Scripts/python.exe docs/difusion/fuente/build.py --url https://terra-analog-index.onrender.com
```

El QR necesita `pip install segno`; sin `--url`, el recuadro dice «Demo en vivo y código abierto». `--solo poster` o
`--solo triptico` genera una sola pieza y `--sin-png` omite las imágenes. Antes de imprimir, escaneá el QR con el celular.
