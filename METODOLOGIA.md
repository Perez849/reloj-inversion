# Metodología

El objetivo de este documento es que cualquier número del panel se pueda rastrear
hasta una regla explícita. Si algo no está aquí, no está en el código.

---

## 1. Por qué no hay umbrales a mano

La versión clásica del reloj (Merrill Lynch, *The Investment Clock*, 2004) clasifica
el ciclo comparando crecimiento e inflación con su tendencia, pero deja la medición
al criterio del analista. La implementación habitual acaba en tablas de puntos del
tipo «si el IPC supera el 4 %, suma 3 a estanflación». Ese tipo de regla tiene tres
problemas: el umbral es arbitrario, el peso relativo también, y ambos se eligen
mirando la historia que luego se usa para validar.

Aquí las dos coordenadas se estiman:

| Decisión | Cómo se resuelve |
|---|---|
| Qué es «alto» o «bajo» | z-score frente a la media y desviación históricas de la propia serie |
| Cuánto pesa cada serie | primer componente principal del bloque |
| Dónde está la frontera | el cero de cada eje, que por construcción es «en tendencia» |
| Cuánta confianza merece | probabilidad de cuadrante bajo la dispersión observada del factor |
| Qué activo comprar | contraste estadístico del exceso condicionado, con control de FDR |

---

## 2. Los datos

### 2.1 Fuentes

- **FRED** (Reserva Federal de St. Louis): series macro y tipos. Descarga por CSV
  público, sin clave de API.
- **ICE BofA** vía FRED: índices de retorno total de crédito IG, HY y emergentes.
- **Biblioteca de Kenneth French** (Dartmouth): 12 carteras sectoriales y factores
  desde 1926, con retorno total y tipo libre de riesgo consistentes entre sí.
- **Stooq**: ETFs y activos reales modernos (oro, materias primas, REITs, TIPS,
  municipales, MBS, estilos). Es la fuente más frágil de las cuatro; si falla, el
  activo desaparece del panel en lugar de rellenarse con supuestos.

### 2.2 Bloques

**Crecimiento (coincidente).** CFNAI-MA3, producción industrial, nóminas,
peticiones de desempleo, ventas reales de manufactura y comercio, renta personal
real sin transferencias, ventas minoristas reales, utilización de capacidad,
sentimiento del consumidor y viviendas iniciadas.

El ancla conceptual es el **CFNAI** del Chicago Fed: es a su vez el primer componente principal
de 85 indicadores mensuales y está construido para que cero sea el crecimiento
tendencial. Eso resuelve el problema del «output gap» sin tener que estimar el PIB
potencial. Las cuatro series del comité de fechado del NBER (empleo, renta,
producción, ventas) entran además por separado.

**Inflación.** PCE subyacente (la medida objetivo de la Fed), IPC general y
subyacente, IPC mediano de Cleveland, PCE de media truncada de Dallas, precios de
producción, salarios por hora, breakeven a 5 años, breakeven 5a5a y petróleo.

Se mezclan deliberadamente medidas realizadas y expectativas de mercado: las
primeras dicen dónde está la inflación, las segundas si el mercado cree que se queda.

**Condiciones financieras.** NFCI del Chicago Fed, diferencial high yield,
permisos de construcción, índice adelantado de la Fed de Filadelfia, VIX y horas
semanales en manufactura.

Este bloque **no entra en la clasificación de la fase actual**. Es una decisión
consciente: mezclar indicadores adelantados con coincidentes contamina el
diagnóstico del presente con una previsión.

**Aparte del PCA: la curva de tipos.** La curva 10a-3m y la 10a-2a se muestran
solas y alimentan el modelo de recesión, pero no entran en ningún componente
principal. El motivo es empírico: al incluirlas, su carga salía prácticamente
nula. Tiene sentido — la curva *anticipa* 12-18 meses, no co-mueve con lo que
está pasando ahora, y un componente principal solo captura lo que co-mueve.
Forzarla dentro daba un factor que parecía incluirla y en realidad la ignoraba.

### 2.3 Retrasos de publicación

Cada serie lleva anotado su retraso real. El z-score se desplaza esa cantidad de
meses antes de entrar en nada. En la práctica: el PCE subyacente de enero no afecta
a la clasificación hasta marzo, las ventas de manufactura llevan dos meses, los
tipos y diferenciales ninguno.

Esto no reconstruye las **revisiones** posteriores de cada dato —para eso haría
falta una base de datos de vintages tipo ALFRED—, así que el backtest sigue siendo
algo optimista. Está señalado en las limitaciones del panel.

### 2.4 Estandarización expansiva

`z_t = (x_t − media(x_0..x_t)) / desv(x_0..x_t)`, con un mínimo de 120 meses.

Estandarizar con la muestra completa mete información del futuro en cada punto del
pasado: en 1975 nadie conocía la media 1959-2026. Con ventana expansiva, el z-score
de 1975 solo usa 1959-1975. Se recorta a ±4σ para que un dato como marzo de 2020 no
domine la extracción del componente principal.

---

## 3. Los factores

Para cada bloque se calcula la matriz de correlaciones de los z-scores y se toma el
autovector asociado al mayor autovalor. Ese vector es el peso de cada serie.

El signo se ancla **por correlación con la media simple del bloque**. Todas las
series entran ya orientadas en el mismo sentido (las que van al revés se invierten
explícitamente: paro, VIX, diferenciales), así que el factor tiene que co-moverse
con su propio promedio. Anclar a una serie concreta, como hacía la primera versión,
falla cuando esa serie sale con carga casi nula: el signo queda a merced del ruido.
El panel publica esa correlación como "coherencia" para que se vea.

La proyección tolera huecos: cada mes promedia las series disponibles con sus pesos
en lugar de exigir el panel completo. Así el histórico arranca en los años sesenta
aunque los breakevens no existan hasta 2003.

El factor resultante se normaliza a varianza uno. Las unidades del panel, por tanto,
son desviaciones típicas respecto a la tendencia histórica.

**Referencias**: Stock y Watson (1989), *New Indexes of Coincident and Leading
Economic Indicators*; Stock y Watson (2002), *Forecasting Using Principal
Components*; Chicago Fed, *CFNAI Background Release*.

---

## 4. La fase y su probabilidad

El cuadrante es el signo de las dos coordenadas:

| | Inflación bajo tendencia | Inflación sobre tendencia |
|---|---|---|
| **Crecimiento sobre tendencia** | Recuperación | Sobrecalentamiento |
| **Crecimiento bajo tendencia** | Reflación / Recesión | Estanflación |

Un punto en (+1,8σ, −1,2σ) está claramente en Recuperación. Uno en (+0,05σ, −0,1σ)
está técnicamente en el mismo cuadrante y no significa nada. Para distinguirlos:

Se trata la medición como el centro de una distribución normal cuya dispersión es la
que el propio factor ha mostrado **a tres meses vista** —el horizonte en el que se
mantiene una posición—. Como los componentes principales son ortogonales, la
probabilidad conjunta factoriza y sale en forma cerrada:

```
P(Sobrecalentamiento) = Φ(g/σ_g) · Φ(i/σ_i)
P(Recuperación)       = Φ(g/σ_g) · (1 − Φ(i/σ_i))
P(Estanflación)       = (1 − Φ(g/σ_g)) · Φ(i/σ_i)
P(Reflación)          = (1 − Φ(g/σ_g)) · (1 − Φ(i/σ_i))
```

La **confianza** es la diferencia entre la probabilidad de la fase principal y la de
la segunda. Por debajo de 0,60 el panel deja de recomendar por fase y pasa a la
cartera de consenso.

Esto sustituye a la fórmula `(máximo − segundo) / máximo` sobre puntos inventados de
la versión anterior, que daba números con aspecto de probabilidad sin serlo.

---

## 5. Probabilidad de recesión

Logit estimado sobre el propio histórico, con la pendiente de la curva 10a-3m y el
NFCI como variables, y como objetivo si el NBER declaró recesión en alguno de los
doce meses siguientes. Se ajusta por IRLS con una regularización mínima y se reporta
el AUC en muestra.

No se importan coeficientes publicados: se reestiman con los datos que hay. La
pendiente de la curva como predictor viene de Estrella y Hardouvelis (1991) y
Estrella y Mishkin (1998); el NFCI, de la propia construcción del Chicago Fed.

---

## 6. Retornos condicionados por fase

Para cada activo y cada fase:

1. Se toma el exceso mensual sobre el tipo libre de riesgo.
2. Se calcula la media dentro de la fase y se compara con **la media incondicional
   del propio activo**. La pregunta no es «¿sube la tecnología en recuperación?»
   —casi todo sube— sino «¿sube más de lo que sube normalmente?».
3. El error estándar es **Newey-West** con 3 rezagos, porque los retornos
   condicionados por régimen están autocorrelacionados y un error estándar simple
   infla los t.
4. La nota traduce el contraste, sin margen para la opinión:

   | Nota | Condición |
   |---|---|
   | `+++` / `---` | \|t\| ≥ 2,58 (p < 0,01) **y** q de Benjamini-Hochberg ≤ 0,10 |
   | `++` / `--` | \|t\| ≥ 1,96 (p < 0,05) |
   | `+` / `-` | \|t\| ≥ 1,28 (p < 0,20) |
   | `0` | indistinguible de su propia media |
   | `s/d` | menos de 12 meses en esa fase |

5. Además del contraste se publica la **media contraída** (James-Stein): las medias
   por fase se estiman con pocas observaciones y son ruidosas, así que se acercan a
   la media del propio activo en proporción al ruido de estimación. Si la dispersión
   entre fases no supera al ruido, la contracción es total y las cuatro fases se
   igualan — que es la respuesta correcta cuando no hay señal. El backtest usa las
   medias contraídas, no las crudas.

6. Como se contrastan del orden de 150 casillas a la vez, se aplica
   **Benjamini-Hochberg** sobre el conjunto: con 150 pruebas al 5 %, siete u ocho
   «hallazgos» son puro azar. El q-value aparece en el tooltip de cada celda.

Por eso los sectores usan Ken French y no ETFs: con datos desde 1999 hay dos ciclos
completos y ninguna casilla llegaría a significativa. Desde 1926 hay quince.

**Referencias**: Newey y West (1987); Benjamini y Hochberg (1995); Fama y French
(1997) para la construcción de las carteras sectoriales.

---

## 7. Backtest walk-forward

En el mes *t*:

1. Se lee la fase vigente en *t−1* (ya publicada, con sus retrasos aplicados).
2. Se estima la media de cada activo en esa fase **usando solo datos hasta t−1**.
3. Se compran los 5 mejores, equiponderados, y se mantienen durante el mes *t*.

Se necesitan 240 meses de entrenamiento antes de la primera operación, así que el
resultado fuera de muestra arranca dos décadas después del inicio del histórico.

Se publican tres versiones de la cartera, porque comparar rentabilidad bruta contra
un 60/40 es tramposo si la cartera del reloj lleva más riesgo:

- **Larga**: los 5 mejores de la fase, equiponderados.
- **Volatilidad igualada**: la misma cartera escalada para tener la volatilidad del
  60/40. Es la única comparación limpia de rentabilidad frente al índice.
- **Larga menos corta**: compra los 5 mejores y vende los 5 peores. Elimina el beta
  de mercado y deja solo la señal de fase. Si esta cartera no gana dinero, el reloj
  no aporta información: lo que aportaba era exposición.

En paralelo se calcula la cartera larga **con las medias de la muestra completa**,
que es lo que hace un backtest ingenuo. La diferencia entre ambas curvas es la
medida directa del sobreajuste, y se publica en el panel en lugar de esconderse.

---

## 8. Validación

- **NBER**: el fechado oficial de recesiones no interviene en ninguna estimación de
  la fase. Se usa solo para comprobar que el eje de crecimiento es negativo cuando
  el NBER dice que hay recesión, y cómo se reparten esos meses entre Reflación y
  Estanflación.
- **Persistencia**: duración media de cada tramo y matriz de transición mensual. Una
  diagonal alta indica que el clasificador no salta de cuadrante con el ruido.
- **¿Gira el reloj?** Se cuenta qué proporción de las transiciones sigue el sentido
  que el marco presupone (Recuperación → Sobrecalentamiento → Estanflación →
  Reflación). Si esa proporción es baja, la premisa de rotación ordenada no se
  sostiene con los datos, y conviene saberlo antes de usar el marco para anticipar
  la fase siguiente.
- **Correlación entre ejes**: al venir de bloques distintos no son ortogonales por
  construcción; si la correlación fuera alta, los cuatro cuadrantes no serían
  independientes y el marco perdería sentido.

---

## 9. Lo que no hace

- **No valora.** El reloj dice qué fase es, no si el activo ya está caro. Un sector
  puede ser el correcto y estar en el percentil 95 de PER.
- **No usa datos en tiempo real de verdad.** Respeta el retraso de publicación pero
  no las revisiones posteriores.
- **Los treasuries son sintéticos.** El retorno se aproxima desde la TIR con duración
  y convexidad, no es un índice real.
- **Los regímenes cambian.** Una curva de Phillips más plana, objetivos de inflación
  creíbles y quince años de QE alteran relaciones que el histórico largo trata como
  estables.
- **Cuatro cuadrantes son pocos.** Shocks de oferta, guerras y pandemias no caben en
  dos ejes, y son precisamente los momentos en que más cara sale una clasificación
  equivocada.
