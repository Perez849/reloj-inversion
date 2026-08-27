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

- **FRED** (Reserva Federal de St. Louis): series macro y tipos. Los retornos de
  deuda pública y crédito con historia larga se derivan de la TIR por duración y
  convexidad, no de un índice de retorno total.
- **Biblioteca de Kenneth French** (Dartmouth): carteras sectoriales y factores
  desde 1926, con retorno total y tipo libre de riesgo consistentes entre sí. Es la
  fuente que nunca ha fallado, y de ella sale casi toda la historia previa a 1990.
- **Yahoo Finance**: ETFs y activos reales modernos (oro, plata, materias primas,
  cobre, REITs, crédito IG y HY, TIPS, municipales, MBS, emergentes). Fuente
  primaria de mercado desde 2026.
- **Stooq**: respaldo de la anterior. Bloquea las IP de los servidores de GitHub,
  así que en la práctica casi nunca responde; se mantiene por si vuelve.

Los índices de retorno total de **ICE BofA** en FRED quedaron truncados a tres años
en abril de 2026, incluidos los subconjuntos por rating. El crédito se cubre desde
entonces con los rendimientos Baa y Aaa de Moody's (desde 1919) y con ETF reales
para el tramo moderno.

Si una fuente falla, el activo desaparece del panel y el motivo queda registrado en
el apartado de diagnóstico. Nunca se rellena con supuestos.

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

### 2.4 Estandarización con ventana móvil

`z_t = (x_t − media(x_{t−119}..x_t)) / desv(x_{t−119}..x_t)`, diez años, y ventana
expansiva mientras no hay historia suficiente. Se recorta a ±4σ para que un dato
como marzo de 2020 no domine la extracción del componente principal.

Dos requisitos, y el segundo costó descubrirlo.

**Causalidad.** Estandarizar con la muestra completa mete información del futuro en
cada punto del pasado: en 1975 nadie conocía la media 1959-2026. La ventana solo
mira hacia atrás.

**Posición cíclica, no nivel.** La versión anterior usaba ventana expansiva, es
decir la media desde 1959 en adelante. Con eso, el pico inflacionista de los setenta
se queda dentro de la referencia para siempre, y el resultado era que de 1990 a 2020
la inflación aparecía permanentemente por debajo de lo normal: en los años noventa y
en la década de 2010 no había **ni un solo mes** de Sobrecalentamiento ni de
Estanflación. El reloj se pasó veinte años usando dos de sus cuatro cuadrantes, y
cualquier cartera medida sobre ese tramo estaba alternando dos etiquetas del mismo
régimen macro.

Un reloj mide dónde estás en el ciclo, no el nivel absoluto frente a medio siglo de
historia. La pregunta correcta es «¿alto o bajo respecto a lo que ha sido normal
últimamente?». Diez meses de ventana cubren un ciclo económico completo sin arrastrar
un cambio de régimen de cuarenta años.

El precio de este cambio es real y conviene tenerlo presente: una ventana móvil
tiende a poblar los cuatro cuadrantes por construcción, así que parte de los cambios
de fase que aparecen son ruido y no ciclo. La tabla de cuadrantes por década del
panel existe para vigilar exactamente eso.

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

Hay dos backtests y miden cosas distintas. Confundirlos es el error más fácil de
cometer con este panel.

### 7.1 La cartera de señal (sección de matriz)

Top-5 del universo entero por media contraída de la fase vigente, sin estructura de
bloques ni bandas. No es una cartera que nadie mantendría: acaba concentrada en lo
menos volátil y hay que apalancarla para llegar al riesgo de un 60/40. Sirve para
una sola pregunta, la de si la fase contiene información. La respuesta la da la
versión **larga menos corta**, que compra los 5 mejores y vende los 5 peores: elimina
el beta de mercado y deja la señal desnuda. Si esa cartera no gana dinero, lo que
aportaba el reloj era exposición, no información.

### 7.2 La cartera implementable (sección de asignación)

Es la que el panel recomienda. En el mes *t*:

1. Se lee la fase vigente en *t−1*, ya publicada y con sus retrasos aplicados.
2. Con datos hasta *t−1* se calcula, para cada activo, su **ventaja de fase**: la
   media condicionada a esa fase menos su propia media incondicional, por unidad de
   volatilidad. Es lo único que el reloj dice saber. Ordenar por
   rentabilidad/volatilidad absoluta —lo que se hacía antes— selecciona el mismo
   puñado de activos defensivos en las cuatro fases y no es una rotación.
3. Cada bloque se queda con sus mejores por esa ventaja: 4 en renta variable, 3 en
   renta fija, 2 en activos reales, **equiponderados** entre sí.
4. El reparto entre bloques parte de una postura neutra 60/30/10 y se desvía según
   lo bien que puntúe cada bloque en esa fase respecto a su propio nivel habitual.
5. Se mantiene durante el mes *t*, siempre invertida al 100 %, sin apalancar y sin
   cortos.

**Reglas de selección**, todas fijadas antes de mirar resultados:

| Regla | Motivo |
|---|---|
| Bandas 30-70 % renta variable, 20-60 % renta fija, 0-15 % activos reales | Nunca sin renta variable ni sin renta fija; el oro puede irse a cero si no se lo gana |
| Neutro en 60/30/10 | Misma postura de riesgo que el índice contra el que se mide. Si el neutro fuera 40/45/15, la comparación mediría nivel de riesgo, no rotación |
| Desviación máxima de 1σ de la puntuación del bloque entre fases | Una fase excepcional lleva el bloque al borde de su banda, no más allá |
| Índices agregados excluidos de la selección | S&P total, EAFE, emergentes y small caps copan el bloque de renta variable si se les deja, y desaparece la rotación sectorial. Siguen en la matriz como referencia |
| Series no invertibles excluidas | PPI y WTI spot no se pueden mantener en cartera |
| Un solo activo por exposición económica | Oro lingote y oro ETF son la misma cosa. Sin esta regla el bloque de activos reales se llenaba con las dos y salía un 15 % de oro disfrazado de diversificación. El representante se elige por historia disponible, antes de mirar retornos |
| Mínimo 60 meses de historia | Un ETF con dos años de datos no gana la selección por ruido |
| Tolerancia de 4 meses al retraso de publicación | Ken French publica con dos meses de desfase; exigir dato del último mes exacto dejaba fuera todos los sectores |
| Equiponderación dentro del bloque | El inverso de volatilidad cancelaba la señal: si el reloj pide duración larga, eliges el Treasury a 30 años y acto seguido le pones cuatro veces menos peso por ser cuatro veces más volátil. El nivel de riesgo lo fijan las bandas entre bloques |
| 120 meses de entrenamiento antes de la primera operación | Con 240 el backtest arrancaba en 1990 y se perdía Volcker, que es donde el reloj tiene las cuatro fases pobladas. El coste es que las estimaciones de los primeros años son más ruidosas |
| Muestra recortada al último mes con benchmark | La estrategia y el 60/40 tienen que cubrir exactamente los mismos meses |

### 7.3 La medida del sobreajuste

En paralelo se juega **la misma regla** estimando la ventaja de fase con el
histórico completo, incluido el futuro que en su momento no se conocía. La distancia
entre las dos curvas es la parte del resultado que depende de saber cosas por
adelantado. Se publica junto a la cartera real en lugar de esconderse: cuanto más
pequeña, más se parece el backtest a lo que habrías vivido.

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
- **Cuadrantes usados por década**: cuántos meses cae cada fase en cada década. Es
  la comprobación más útil del panel. Si una década entera usa solo dos cuadrantes,
  la rotación no tiene nada que rotar en ese tramo, y cualquier resultado de cartera
  medido ahí dice mucho menos de lo que parece.

Sobre el sentido del reloj, una aclaración numérica: desde cada fase hay tres
destinos posibles, así que el azar puro daría un 33 %. Por debajo de esa cifra el
reloj gira al revés; solo muy por encima se puede hablar de un ciclo con dirección.

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
- **No hay costes.** Ni comisiones, ni horquilla, ni impuestos. La cartera se
  reequilibra entera cada mes, así que la rotación real rendiría menos que la del
  panel, y la diferencia crece con el tamaño de las desviaciones entre bloques.
- **Los sectores de Ken French no son invertibles tal cual.** Son carteras
  académicas ponderadas por capitalización, no ETF. El ETF sectorial equivalente
  tiene composición distinta, comisión y tracking error.
- **La ventana móvil tiene un coste.** Puebla los cuatro cuadrantes por
  construcción, así que parte de los cambios de fase son ruido. Se vigila con la
  tabla de cuadrantes por década y con la duración media de los tramos.
