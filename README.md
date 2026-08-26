# Reloj de inversión

Panel que clasifica el ciclo económico de EE.UU. en uno de los cuatro cuadrantes del
*investment clock* y muestra qué ha pagado históricamente cada activo en ese
cuadrante, con el contraste estadístico delante.

Se actualiza solo: una acción programada regenera los datos cada día laborable y
GitHub Pages sirve la página.

**[Metodología completa →](METODOLOGIA.md)**

---

## Qué lo diferencia de la versión anterior

| | Antes | Ahora |
|---|---|---|
| Umbrales | escritos a mano (`si IPC > 4 % …`) | z-scores con media y desviación expansivas |
| Pesos | puntos asignados por criterio | primer componente principal de cada bloque |
| Confianza | `(máx − 2.º) / máx` sobre puntos inventados | probabilidad de cuadrante bajo la dispersión real del factor |
| Fase | 10 series, reglas fijas | 28 series en tres bloques, con retraso de publicación aplicado |
| Recomendaciones | tabla de opiniones | exceso condicionado con t de Newey-West y control de FDR |
| Histórico | 5 años | desde los años sesenta (sectores desde 1926) |
| Validación | ninguna | contraste con el NBER, matriz de transición y backtest walk-forward |
| Sobreajuste | invisible | se publica la diferencia entre dentro y fuera de muestra |

---

## Puesta en marcha

1. **Crea el repositorio** y sube estos archivos tal cual.

2. **Activa Pages**: *Settings → Pages → Source: Deploy from a branch →
   `main` / carpeta `/docs`*.

3. **Permite que la acción escriba**: *Settings → Actions → General → Workflow
   permissions → Read and write permissions*.

4. **Lanza la primera ejecución**: pestaña *Actions → Actualizar datos → Run
   workflow*. Tarda unos 3-5 minutos, casi todo descargando FRED.

5. Abre `https://<tu-usuario>.github.io/<repo>/`.

Hasta que la acción termine por primera vez, la página avisa de que falta
`docs/data/data.json` en lugar de mostrar datos inventados.

## Ejecución local

```bash
pip install -r requirements.txt
python scripts/build_data.py          # genera docs/data/data.json
python -m http.server -d docs 8000    # abre http://localhost:8000
```

Para comprobar la lógica sin tocar la red:

```bash
python scripts/_selftest.py
```

Inyecta series sintéticas con un ciclo latente conocido y verifica que el pipeline
completo produce un `data.json` coherente. Se ejecuta también en cada acción, antes
de la descarga real, para que un fallo de lógica no publique un panel roto.

---

## Estructura

```
scripts/build_data.py   descarga, factores, clasificación, estadística, backtest
scripts/_selftest.py    prueba offline con datos sintéticos
docs/index.html         página
docs/assets/app.js      render del panel (sin dependencias)
docs/assets/style.css   estilos
docs/data/data.json     salida del pipeline (la genera la acción)
```

## Cómo tocarlo

- **Añadir un indicador**: una línea en la lista `SERIES` de `build_data.py` con su
  bloque, su transformación y su retraso de publicación. El PCA recalcula los pesos
  solo; no hay que ajustar nada más.
- **Añadir un activo**: entrada en `FRED_TR` (índices de retorno total de FRED) o en
  `STOOQ`. Si la serie tiene menos de 60 meses, se descarta sola.
- **Cambiar el horizonte**: `HORIZON_M` en `main()`. Afecta a la anchura de la elipse
  de incertidumbre y, por tanto, a cuándo se activa la cartera de consenso.
- **Cambiar el umbral de consenso**: la constante `0.6` en `app.js` y en el texto de
  metodología.

## Fuentes

FRED · ICE BofA · biblioteca de datos de Kenneth French · Stooq.

Herramienta de análisis. No es recomendación de inversión ni asesoramiento financiero.
