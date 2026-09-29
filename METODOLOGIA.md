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

### 2.4 Estandarización con ventana móvil robusta

`z_t = (x_t − mediana(x_{t−119}..x_t)) / (1,4826 · MAD(x_{t−119}..x_t))`, diez años
(120 meses), con arranque adaptativo mientras no hay historia suficiente (suelo de
48 meses). Se recorta a ±4σ para que un dato extremo aislado no domine la extracción
del componente principal.

Tres requisitos, y los dos últimos costó descubrirlos con datos reales del propio
panel, no en la pizarra.

**Causalidad.** Estandarizar con la muestra completa mete información del futuro en
cada punto del pasado: en 1975 nadie conocía la media 1959-2026. La ventana solo
mira hacia atrás.

**Posición cíclica, no nivel.** Una ventana *expansiva* (toda la historia desde el
arranque de la serie) no resuelve esto: el pico inflacionista de los setenta se
queda dentro de la referencia para siempre, y el resultado es que de 1990 a 2020 la
inflación aparece permanentemente por debajo de lo normal. Comprobado sobre el
histórico real de este panel: con ventana expansiva, los años noventa y toda la
década de 2010 no registraban **ni un solo mes** de Sobrecalentamiento ni de
Estanflación — dos de las cuatro fases, ausentes durante veinte años. Con la ventana
móvil de diez años las cuatro fases aparecen en todas las décadas desde 1970.

Un reloj mide dónde estás en el ciclo, no el nivel absoluto frente a medio siglo de
historia. La pregunta correcta es «¿alto o bajo respecto a lo que ha sido normal
últimamente?». Diez *años* de ventana cubren un ciclo económico completo sin
arrastrar un cambio de régimen de cuarenta años.

**Robustez frente a valores extremos.** Marzo y abril de 2020 son lecturas de hasta
±10 desviaciones. Con media y desviación típica, esos meses dominan la ventana de
diez años durante todo el tiempo que permanecen dentro de ella. La mediana y la
desviación absoluta mediana (MAD, escalada por 1,4826 para equivaler a la
desviación típica bajo normalidad) apenas se mueven por un puñado de valores
extremos.

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

1. Se toma el exceso mensual sobre el tipo libre de riesgo (letras del Tesoro a 3
   meses). **Esto no es un detalle solo de esta sección**: todo el panel trabaja
   sobre esta serie de excesos — la matriz, el backtest de 7.1, la cartera de
   rotación de 7.2. Cualquier "CAGR" o "rentabilidad anual" que aparece en la web,
   incluida la comparación de la cartera contra el S&P 500, es exceso sobre
   letras del Tesoro, no el retorno total del índice. Es la convención estándar
   para que el Sharpe (retorno entre riesgo) signifique lo que dice significar, y
   la comparación entre dos carteras es igual de válida en excesos que en bruto —
   pero el número absoluto del S&P 500 en bruto es más alto que el que se publica
   aquí, aproximadamente en el tipo de interés sin riesgo del periodo.
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

## 6b. Subsectores — análisis complementario

Sección «Un paso más», dentro de «El backtest». Responde a una pregunta distinta
de la de la cartera principal: dentro de un sector que la cartera **ya ha
elegido** para una fase, ¿hay un subsector que lo hizo notablemente mejor —o
peor— que el sector en conjunto?

**No participa en la selección ni en el backtest de ningún modo.** No entra en
`means()`, `_sleeve_pick()`, `rotation()` ni en ningún punto de la cartera de las
secciones 7.1/7.2: se calcula aparte, después de que la cartera ya está decidida,
y solo se muestra para los sectores que la cartera principal ya recomienda —
nunca decide cuáles son.

**El universo — verificado, no adivinado.** Ken French publica los mismos
retornos sectoriales agregados en 49 industrias, más finas que las 12 que ya usa
el sistema (sección 2.1). La pregunta de qué industria de las 49 cae dentro de
cuál de las 12 no se ha respondido mirando el nombre: se ha comprobado contra los
propios ficheros de definición por código SIC que publica French
(`Siccodes12.txt` y `Siccodes49.txt`, el mismo origen que los retornos), viendo
qué rango de códigos de cada una de las 49 cae **entero** dentro del rango de
código de una de las 12. De las 49, 29 caen limpias en un único sector; las
otras 13 se reparten por código SIC entre varios sectores a la vez —por ejemplo
«Chips» (semiconductores) queda fuera de Tecnología por un solo código, el 3622
(«controles industriales»), que French agrupa con los semiconductores pero que
por su código pertenece a Industria— y se excluyen en vez de asignarse a ojo.
Gold y RlEst (oro y inmobiliario) también caen limpios, pero ya son activos
propios del sistema (sección 2.1): mostrarlos otra vez como «subsector de…»
sería la misma exposición contada dos veces. El mapeo completo, con su
justificación línea a línea, está en `SUBSECTOR_MAP` y
`SUBSECTOR_EXCLUDED_MIXED` en `build_data.py`.

Con esto, ocho de los diez sectores tienen desglose (Consumo básico, Salud,
Industria, Energía, Tecnología, Consumo discrecional, Financiero y Otros
sectores); Materiales/Químicas, Utilities y Comunicaciones no lo tienen porque
su único subsector limpio es idéntico al propio sector —no hay nada más fino
que enseñar—.

**La estadística es la misma que la sección 6**, aplicada a este universo
aparte: t de Newey-West, contracción de James-Stein para la media contraída, y
su **propio** control de Benjamini-Hochberg —una familia de contrastes
distinta de la de la matriz principal, corregida por separado— porque mezclar
las dos familias en un único control habría sido estadísticamente incorrecto.

**Cómo leerlo**: para cada sector ya elegido en la fase que se está mirando, se
lista cada subsector con su rentabilidad real de esa fase y, cuando corresponde,
la nota de significancia. Se marca en verde el que igualó o batió al sector en
conjunto, en rojo el que perdió dinero. Además se calcula, con los datos ya
vistos, la diferencia que habría supuesto comprar solo el mejor subsector en vez
de todo el sector — **una constatación histórica, nunca una previsión**: no hay
ninguna garantía de que el mismo subsector repita.

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

Es la que el panel recomienda: **100 % renta variable de sectores**, con el oro y
las mineras de oro como único seguro no bursátil. Sin renta fija — decisión
explícita, no un hallazgo del backtest. En el mes *t*:

1. Se lee la fase vigente en *t−1*, ya publicada y con sus retrasos aplicados.
2. Con datos hasta *t−1* se calcula, para cada activo, su **ventaja esperada
   en esta fase frente a su propia media**: la misma fórmula de contracción
   empírica de Bayes de la sección 6 —los meses reales en que el activo
   estuvo en esa fase, contra su propia media—, activo por activo, no una
   construcción aparte. Es a propósito: si un activo no muestra diferencia
   real entre fases en la matriz de evidencia, tampoco debe mostrarla aquí.
   Una versión anterior devolvía el nivel absoluto (media general + la
   desviación contraída) en vez de la desviación sola, y ese nivel absoluto
   es casi siempre positivo tanto para el oro como para cualquier sector a
   largo plazo: "puntúa positivo" no discriminaba nada y el oro competía por
   presupuesto con el nivel de una racha alcista de 25 años que no depende
   de la fase, no con una ventaja de fase real. Otra versión anterior a esa
   usaba la pendiente de una regresión sobre los dos factores (crecimiento,
   inflación) evaluada en el centro de la fase, y esa regresión extrapolaba
   oro como atractivo en las cuatro fases —incluidas las tres en las que la
   propia matriz de evidencia dice que no aporta nada—, así que la cartera
   recomendaba una posición que los datos no respaldaban. La regresión se
   conserva solo como respaldo, para cuando la muestra directa de la fase es
   demasiado corta para casi todo el universo.

   **Una diferencia real con la sección 6, y a propósito**: ahí la media de
   cada fase pesa igual el dato de 1935 que el de 2025; aquí pesa con una
   vida media de cinco años (la misma que usa el backtest de asignación, ver
   más abajo), porque es la decisión que se ejecuta hoy y da igual lo que
   hiciera una tecnológica en 1935. Con esto, el signo de una casilla casi
   plana en la sección 6 —próxima a cero, sin marca de significancia— puede
   salir con el signo contrario aquí si el comportamiento de los últimos
   años pesa distinto que el conjunto de la serie: no es un error, es la
   misma contracción con otra ponderación temporal. Cuanto más fuerte sea la
   marca de significancia en la sección 6 (`++`, `+++` y sus negativos), más
   improbable es que los últimos años por sí solos la contradigan, pero no
   hay una garantía matemática de que no pueda ocurrir en una serie con muy
   poca historia reciente en esa fase.

   Antes la vida media era de diez años; se bajó a cinco tras comprobar con el
   propio backtest que reaccionar más rápido a un sector saliendo de una mala
   racha (p.ej. tecnología tras el batacazo de 2022) mejora el resultado: CAGR
   más alto en los cuatro esquemas de reparto, mejor drawdown máximo y más años
   batiendo al S&P 500. El coste es más sensibilidad a rachas cortas.
3. **El número de activos no es fijo.** Dentro de cada bloque se quedan los que
   **no muestran desventaja de fase** —esa rentabilidad esperada dividida
   entre volatilidad, ≥ 0, no hace falta ventaja, basta con que la fase no
   le siente peor que su propia media—, acotado entre un suelo y un techo:
   **Renta variable**, entre 2 y 7 de los 10 sectores posibles; **Oro**,
   entre 0 y 2 (oro físico y mineras de oro). Con menos aceptables que el
   suelo, se completa hasta el suelo con los siguientes mejores aunque
   puntúen negativo — el suelo evita la cartera vacía o concentrada en un
   único nombre, no es una opinión sobre esos activos. Con más aceptables
   que el techo, se recorta a los mejores. Un mes puede tener 2 sectores;
   otro, 7 — y el oro puede no aparecer en absoluto si la fase no lo
   sostiene, que es exactamente lo que ocurre fuera de Reflación.

   **Un empate en 0 solo es aceptable si, además, no es mediocre EN ESA
   FASE — y el desempate es lo que de verdad pasó esa fase, no el
   promedio general del activo.** Con contracción total (tau2 = 0: la fase
   no explica nada de la dispersión de un activo que el propio ruido de
   estimación no explique ya), un activo puntúa exacto 0 en la ventaja
   contraída — ninguna ventaja de fase distinguible, pero tampoco ninguna
   desventaja. Descartarlo sin más (como si 0 fuera negativo) tiene un
   coste real: Tecnología puntuaba 0 en las cuatro fases con datos reales
   de un dato concreto y quedaba fuera de la cartera por completo, pese a
   ser uno de los dos sectores con mayor rendimiento incondicional de los
   diez (8,75 % anual, solo por detrás de Energía).

   El primer intento de arreglar esto comparaba, para decidir si un empate
   en 0 es aceptable y para ordenar al completar el suelo con negativos, el
   rendimiento **incondicional** de cada activo (su media general, sin
   condicionar por fase). Parecía razonable —sin ventaja de fase que
   premiar, ¿qué otra cosa se puede mirar?— pero es la misma lógica que
   causó el problema original del oro, solo que un paso más allá: cuando la
   contracción es total, "el nivel de la fase contraído" es literalmente
   el nivel incondicional (no le suma nada la fase), así que comparar por
   incondicional es, en la práctica, ignorar la fase por completo.
   Comprobado con datos reales: en Estanflación, Tecnología rindió -0,85 %
   real (de los peores de los diez sectores) frente al +3,58 % real de
   Utilities, pero el desempate por incondicional seguía prefiriendo a
   Tecnología —8,75 % de media general, frente al 6,57 % de Utilities—,
   dándole el 53 % de la cartera de renta variable esa fase frente al 27 %
   de Utilities. Exactamente al revés de lo que de verdad pasó.

   El desempate correcto es el rendimiento **real de esa fase concreta,
   sin contraer** (la misma media por fase que se contrae para calcular la
   ventaja, pero tal cual, antes de contraerla): no sirve como criterio
   PRINCIPAL de selección porque con pocos meses de esa fase es ruidoso
   —para eso existe la contracción—, pero es estrictamente mejor que la
   única alternativa disponible cuando la ventaja contraída no diferencia
   nada, tanto para decidir si un empate en 0 es aceptable (¿rindió esta
   fase, sin contraer, al menos tanto como un candidato típico del bloque
   esa misma fase?) como para ordenar al completar el suelo con negativos
   (¿cuál rindió menos mal esta fase en concreto?). Con datos reales, este
   criterio deja entrar a Tecnología cuando de verdad conviene y prefiere a
   Utilities sobre Tecnología en Estanflación, que es lo que en efecto pasó
   esa fase.
4. Dentro de cada bloque, el reparto entre los elegidos sigue uno de cuatro
   esquemas —equiponderado, inverso de volatilidad, por puesto, o mitad y
   mitad— calculados en paralelo. El panel abre con el que de verdad ha dado
   más CAGR en el propio backtest walk-forward, no uno fijado de antemano —el
   que gane puede cambiar de un dato a otro—, y deja elegir cuál mirar.
5. El reparto **entre** los dos bloques parte de bandas fijas —80-100 % renta
   variable, 0-20 % oro— y se mueve dentro de ellas en proporción a la
   rentabilidad esperada de cada bloque en esa fase. Una puntuación negativa se
   trata como cero: el oro puede desaparecer del todo si no aporta.
6. Se mantiene durante el mes *t*, siempre invertida al 100 %, sin apalancar y
   sin cortos.

**Reglas de selección**, todas fijadas antes de mirar resultados:

| Regla | Motivo |
|---|---|
| Bandas 80-100 % renta variable, 0-20 % oro | Nunca sin renta variable; el oro es un seguro táctico, no puede superar a la renta variable en peso |
| Entre 2 y 7 sectores, nunca fijo | Un único sector sobre una cartera 100 % invertida es un riesgo idiosincrático que nadie pidió; 8 o más de 10 es casi comprar el índice entero y no queda rotación que evaluar. Dentro de ese rango, manda la fase: cuantos puntúen positivo de verdad, ni uno más para rellenar cupo |
| Índices agregados excluidos de la selección | S&P total, EAFE, emergentes y small caps copan la selección si se les deja, y desaparece la rotación sectorial. Siguen en la matriz como referencia |
| Series no invertibles excluidas | PPI y WTI spot no se pueden mantener en cartera |
| "Consumo duradero" (Durbl) excluido del todo | Ken French lo separa de "Consumo discrecional" (Shops) como industria propia, con su propia serie de retornos, pero no existe un ETF sectorial real que trackee bienes duraderos aparte del consumo discrecional — el mapeo real caía en el mismo IYC/XLY que "Consumo discrecional". Con los dos como sectores independientes, la cartera podía recomendar ambos a la vez en la misma fase: dos nombres, dos líneas en "qué comprar ahora", **la misma orden de compra**. Se descarta la industria entera de la fuente en vez de parchear la selección, porque el problema no es la selección — es que ese sector no tiene una forma real de comprarse aparte |
| Los 10 sectores restantes son mutuamente excluyentes por construcción | No hay un "Bancos" aparte de "Financiero" ni un "Semiconductores" aparte de "Tecnología" que pudieran duplicar la misma apuesta, y cada uno tiene un ETF sectorial real y distinto (ver el mapeo en `app.js`). No hace falta ninguna regla de deduplicación dentro del bloque de renta variable |
| Oro físico y mineras de oro pueden convivir | No son la misma apuesta: el lingote es exposición pura al precio del oro, las mineras añaden apalancamiento operativo y riesgo de renta variable encima. Correlacionados, pero no intercambiables — de ahí que el bloque de oro pueda sostener los dos a la vez, hasta su techo de 2 |
| Mínimo 60 meses de historia | Un ETF con dos años de datos no gana la selección por ruido |
| Tolerancia de 4 meses al retraso de publicación | Ken French publica con dos meses de desfase; exigir dato del último mes exacto dejaba fuera todos los sectores |
| Guardián de plausibilidad | Una serie que no puede ser un retorno mensual no entra: más del 90 % de meses en positivo **y** media por encima del 3 % mensual a la vez (las dos condiciones juntas — la liquidez y los bonos cortos son legítimamente positivos el 95 %+ de los meses con media baja, y solo un filtro conjunto no los descarta a ellos), menos del 15 % de meses en positivo (signo invertido), media por encima del 8 % mensual, o un mes por encima del 150 %. Nace de un caso real: una fuente devolvió un índice acumulado disfrazado de bono, con media del 25 % mensual y el 99,9 % de meses en verde |
| 120 meses de entrenamiento antes de la primera operación | Con 240 el backtest arrancaba en 1990 y se perdía Volcker, que es donde el reloj tiene las cuatro fases pobladas. El coste es que las estimaciones de los primeros años son más ruidosas |
| Muestra recortada al último mes con benchmark | La estrategia y el S&P 500 tienen que cubrir exactamente los mismos meses |

La comparación primaria es contra la **renta variable estadounidense al 100 %**
(el propio S&P 500 / mercado), no contra un 60/40: esta cartera no lleva renta
fija, así que compararla contra una que sí la lleva mediría dos carteras
distintas, no si la rotación por sectores aporta. El 60/40 se publica aparte,
solo como referencia de contexto para quien lo pida.

### 7.3 La medida del sobreajuste

En paralelo se juega **la misma regla** estimando la ventaja de fase con el
histórico completo, incluido el futuro que en su momento no se conocía. La distancia
entre las dos curvas es la parte del resultado que depende de saber cosas por
adelantado. Se publica junto a la cartera real en lugar de esconderse: cuanto más
pequeña, más se parece el backtest a lo que habrías vivido.

### 7.4 El laboratorio de persistencia (sección «Laboratorio»)

Pregunta distinta a la de 7.1-7.3, y más simple: **lo que ganó en la primera mitad
de una fase, ¿seguía ganando en la segunda?** No es el algoritmo de selección de la
cartera real —ese usa regresión sobre los factores, contracción bayesiana y un
número variable de activos (7.2)—, sino un contraste directo sobre el propio
histórico crudo de cada bloque.

Para cada fase y cada bloque (renta variable, oro):

1. Se listan todos los activos del bloque con al menos 24 meses en esa fase.
2. Se evalúan **todas** las combinaciones posibles de `k=5` de esos activos —un
   tamaño fijo, a propósito: "todas las combinaciones posibles" solo es tratable
   con k constante, y 5 es el valor típico del rango 3-7 que usa la cartera real
   de 7.2. Con solo dos candidatos, como el bloque de oro, no hay combinaciones de
   5 que evaluar y el bloque se salta con una nota.
3. Cada combinación —y cada activo suelto— se parte por la **mediana de sus
   propios meses disponibles** en esa fase, no por una fecha común: un ETF que
   arrancó en 2007 se compara con su propia mitad temprana y tardía, no queda
   fuera por no tener historia antes de esa fecha.
4. Se ordenan las combinaciones por rentabilidad en la primera mitad y se mira
   dónde cae cada una, por percentil, dentro de **todas** las combinaciones en la
   segunda mitad. El coeficiente de correlación de rangos (Spearman) entre las dos
   mitades —para las combinaciones y, aparte, para los activos sueltos— es la cifra
   que resume si "lo que funcionó antes" es información o ruido: por encima de 0,4,
   hay persistencia real; por debajo de 0,15 en cualquier sentido, elegir por
   historia pasada equivale a tirar una moneda.

Esta sección no alimenta ninguna recomendación del panel: es una comprobación
aparte de si el marco tiene memoria, no una fuente de la cartera de 7.2.

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

- **Los "CAGR" del panel no son el retorno total del índice.** Son exceso sobre
  letras del Tesoro a 3 meses (sección 6.1) — la convención estándar para que el
  Sharpe tenga sentido, pero significa que el número del S&P 500 que se muestra
  es más bajo que su rentabilidad histórica real en bruto.
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
- **Sin renta fija, por decisión, no por resultado del backtest.** Una cartera
  100 % en renta variable —rote por sectores o no— lleva más volatilidad y
  caídas más profundas que cualquier mezcla con bonos; eso no lo cambia acertar
  la fase. El panel publica el Sharpe y la caída máxima frente al S&P 500 al
  lado del CAGR precisamente para que ese coste no quede escondido detrás de
  una rentabilidad más alta.
