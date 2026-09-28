# Reloj de inversión

Panel que clasifica el ciclo económico de EE.UU. en uno de los cuatro cuadrantes del
*investment clock* (Recuperación, Sobrecalentamiento, Estanflación, Reflación) y
muestra qué sectores de renta variable comprar en cada fase —sin renta fija, con el
oro y las mineras de oro como único seguro no bursátil—, con el ETF real más
parecido para ejecutarlo, a partir de lo que ha pagado *históricamente* cada sector
en esa fase, contrastado estadísticamente y comparado contra el propio S&P 500.

Se actualiza solo: una acción programada regenera los datos cada día laborable y
GitHub Pages sirve la página.

**[Metodología completa →](METODOLOGIA.md)**

---

## Cómo se construye la fase y la cartera, en corto

- **La fase**: 28 series de FRED, cada una estandarizada con z-score robusto
  (mediana/MAD) en ventana móvil de 10 años. 26 se reparten en tres bloques
  (crecimiento, inflación, adelantado) y se resumen por componente principal —
  el peso de cada serie sale de ahí, no de un criterio a mano; las 2 restantes
  (la curva de tipos) se muestran aparte, fuera de cualquier PCA. El cuadrante
  es el signo de los dos ejes resultantes; la confianza, la probabilidad real
  de ese cuadrante frente al segundo más probable.
- **La cartera**: 100 % renta variable de sectores (entre 2 y 7 de los 10
  posibles, según cuántos no muestren desventaja *de verdad* en la fase — la
  misma media condicionada de la matriz de evidencia, no una extrapolación
  aparte), con oro y mineras de oro como único seguro no bursátil (0-20 %). Cada
  recomendación lleva el contraste estadístico (t de Newey-West, control de
  FDR) y el backtest walk-forward completo, comparado contra el S&P 500.

---

## Diagnóstico incorporado

El panel tiene una sección que registra **cada intento de descarga**, con su motivo
de fallo si lo hubo. Ninguna fuente puede caerse en silencio: Stooq, por ejemplo,
devuelve un 200 con un mensaje de error cuando se supera su límite diario, y la
primera versión lo descartaba sin decir nada.

También publica cuántas casillas de la tabla de activos sobreviven al control de
falsos descubrimientos. Si son pocas, el panel lo dice en lugar de mostrar
recomendaciones con aspecto de certeza.

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
- **Añadir un activo**: entrada en `FRED_YIELD` (aproximado por TIR), `MARKET`
  (Yahoo con respaldo en Stooq) o `FRENCH_IND`/`FRENCH_49` (Ken French). Si la serie
  tiene menos de 60 meses, se descarta sola. Para que aparezca con su ticker en
  «Qué comprar ahora», añade la entrada correspondiente a `ETF_MAP` en `app.js`.
- **Cambiar el horizonte**: `HORIZON_M` en `main()`. Afecta a la anchura de la elipse
  de incertidumbre y, por tanto, a cuándo se activa la cartera de consenso.
- **Cambiar el umbral de consenso**: la constante `0.6` en `app.js` y en el texto de
  metodología.

## Fuentes

FRED · ICE BofA · biblioteca de datos de Kenneth French · Stooq.

Herramienta de análisis. No es recomendación de inversión ni asesoramiento financiero.
