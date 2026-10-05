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
otras 12 se reparten por código SIC entre varios sectores a la vez y se
excluyen en vez de asignarse a ojo (`SUBSECTOR_EXCLUDED_MIXED`). Gold, RlEst y
Chips (oro, inmobiliario y semiconductores) también caen limpios por código
SIC, pero no aparecen aquí porque ya son activos propios del sistema (sección
2.1 y la tabla de reglas de selección): mostrarlos otra vez como «subsector
de…» sería la misma exposición contada dos veces. El mapeo completo, con su
justificación línea a línea, está en `SUBSECTOR_MAP` y
`SUBSECTOR_EXCLUDED_MIXED` en `build_data.py`.

Con esto, ocho de los once sectores tienen desglose **estadístico** por
subsector (Consumo básico, Salud, Industria, Energía, Tecnología, Consumo
discrecional, Financiero y Otros sectores); Materiales/Químicas, Utilities y
Comunicaciones no lo tienen porque su único subsector limpio es idéntico al
propio sector, y Semiconductores no lo tiene porque ya es, él mismo, la pieza
más fina que existe. La página muestra una tarjeta para cada sector elegido
en la fase, con el mismo aspecto visual en los once casos: una fila por cada
línea de negocio, nombre a la izquierda y un número en mono a la derecha. En
los ocho con desglose estadístico ese número es la rentabilidad anualizada de
la fase; en Materiales/Químicas, Utilities y Comunicaciones es el peso real
agregado de hoy de un grupo de negocio deducido de la propia composición del
ETF (ver `HOLDINGS_GROUPS` más abajo); en Semiconductores es el peso real de
cada empresa, también de hoy — mismo formato en los once casos, dato de otra
naturaleza donde no hay historia que medir, nunca un hueco vacío ni un texto
aparte explicando la ausencia.

**¿Hay algo más fino que las 49 industrias, para los RETORNOS?** Se ha
comprobado, no asumido: Ken French no publica nada más granular —su catálogo
llega hasta 49 (`100_Industry_Portfolios` no existe, HTTP 404; el resto de
clasificaciones que ofrece, 5/10/12/17/30/38, son más *bastas*, no más
finas—. Una fuente moderna con más detalle (p. ej. ETFs sectoriales GICS de
subsector) tendría como mucho 15-20 años de historia, muy por debajo del
estándar de significancia que usa todo este documento (sección 2.1: con
menos de dos ciclos completos ninguna casilla llegaría a significativa). Se
prefiere no tener desglose de **retornos** antes que tener uno con una
fuente que no pasaría el propio control de calidad del panel. Esto sigue
siendo así: la tabla de rentabilidad por subsector y fase viene, sin
excepción, de Ken French.

**Los ejemplos de empresas — de posiciones reales, no de memoria.** Bajo
cada subsector (y bajo los cuatro sectores sin desglose estadístico) se
muestran empresas concretas. Hasta esta versión eran una lista fija escrita
a mano; ahora son las posiciones reales de hoy del propio ETF SPDR/State
Street sectorial —mismo ticker que ya aparece en la tabla de instrumentos—,
descargadas a diario junto con el resto de datos (`fetch_holdings()` en
`build_data.py`, fichero `.xlsx` de holdings que State Street publica en
abierto). Es un dato de otra naturaleza que la tabla de retornos: no es una
serie histórica sino una foto de la composición del fondo en el momento de
generar la página, así que el problema de historia corta de más arriba no
le afecta — no se usa para calcular nada, solo para ilustrar con nombres
reales y verificables (nombre, ticker y peso) qué tipo de empresa compone
cada subsector hoy.

De los tres proveedores que ya aparecen en `ETF_MAP` se probaron los tres
antes de elegir: el endpoint de iShares que se documentaba como CSV
descargable devuelve hoy el HTML del sitio en vez de datos; VanEck no se
pudo verificar como fuente programática fiable; SPDR/State Street sí expone
un `.xlsx` real y estable. Se queda como única fuente para este dato.

El propio fichero de SPDR **no** trae una columna de sub-industria utilizable
— la columna "Sector" viene vacía en los holdings de los cinco fondos
probados—, así que no hay forma de que el subsector de cada empresa salga
solo del dato descargado: la tabla `TICKER_SUBSECTOR` en `build_data.py`
clasifica cada ticker a mano, uno por uno, contra su código SIC real y
público (verificable en SEC EDGAR) — el mismo criterio que usa el propio
Ken French para construir sus 49 industrias, nunca "a qué suena" el negocio
de la empresa. Esto tiene consecuencias visibles: los mayores fabricantes de
chips que hoy pesan en el ETF de Tecnología (Nvidia, AMD, Broadcom, Micron,
Intel, Lam Research, Applied Materials...) no aparecen bajo "Hardware" ni
"Software" — por código SIC son semiconductores (ver `CHIP_TICKERS`), y
alimentan en su lugar, con su mismo peso real dentro de Tecnología, el propio
sector Semiconductores (más abajo). Visa, Mastercard, S&P Global y CME
Group, con todo su peso en el ETF Financiero, tampoco aparecen bajo Banca,
Seguros ni Bróker — su código SIC real es el de procesamiento de datos o
mercados/proveedores de datos, no el de una entidad financiera al uso. Un
holding que no encaja con confianza en ningún subsector de su propio sector
se deja fuera del ejemplo antes que forzarlo en el más parecido.

También se probó, y se descartó, un ETF de sub-industria (XHB) para dar
ejemplos reales de "Construcción": sus posiciones de hoy incluyen un
fabricante de pequeños electrodomésticos y una cadena de menaje del hogar
junto a las constructoras — el fondo ya no es un proxy limpio de esa
sub-industria, y mostrarlo tal cual habría sido precisamente el tipo de
ejemplo mal etiquetado que se quiere evitar. "Ocio y entretenimiento" se
queda igual, sin ejemplos: no existe un ETF de esa sub-industria exacta.
"Transporte" sí tiene fuente propia y fiable (XTN, mismo proveedor), así que
sus ejemplos no pasan por la tabla de clasificación: sus posiciones ya son,
todas, empresas de transporte por definición del propio fondo.

Un aviso de metodología para Semiconductores en concreto: se probó primero
XSD ("SPDR S&P Semiconductor Select Industry"), la fuente más directa por
nombre — pero es un índice de ponderación casi igualada entre sus
componentes, no de capitalización, y comprobado con datos reales su top-20
no incluye ni a Nvidia ni a Micron ni a Broadcom: pesan mucho en el mercado
real y casi nada en un índice que reparte el peso a partes iguales entre
fabricantes grandes y pequeños. Esas mismas empresas SÍ aparecen, y con su
peso real de mercado, dentro del propio XLK (Tecnología) que ya se descarga
— GICS las agrupa ahí, aunque por SIC sean semiconductores y no "Hardware"
ni "Software" (ver el párrafo anterior). Así que Semiconductores no tiene
fetch propio: se deriva filtrando, dentro de las posiciones ya descargadas
de Tecnología, las que por SIC real fabrican semiconductores (`CHIP_TICKERS`
en `build_data.py`) — mismo dato fiable de SPDR, sin sumar un cuarto
proveedor, y con los nombres que de verdad pesan hoy. El peso mostrado es su
peso dentro de XLK, no de un fondo de semiconductores propio: la página lo
deja explícito en el pie de la tarjeta para no confundir las dos cosas.

**Los grupos derivados (Comunicaciones, Utilities, Materiales/Químicas).**
Para estos tres sectores, además de no tener desglose de retornos por
subsector, tampoco tenía sentido enseñar solo una lista plana de empresas:
se pidió expresamente el mismo tipo de vista que ya tienen Salud o
Financiero, con líneas de negocio con nombre. Como no hay una fuente de
retornos por línea de negocio para deducirlas de ahí, se deducen de la
propia composición del ETF: `HOLDINGS_GROUPS` en `build_data.py` agrupa los
tickers reales observados en el top-20 de cada sector contra su sub-industria
GICS pública y verificable (p. ej. en Utilities: "Eléctricas reguladas"
frente a "Multiservicios electricidad y gas" frente a "Generación
independiente" — NextEra o Duke Energy no son lo mismo que Constellation,
que genera de forma competitiva en vez de operar una red regulada). El
número de cada grupo es la suma de los pesos reales de sus miembros en el
fondo, nunca un cálculo por fase — no hay historia de retornos que agrupar,
solo composición de hoy. Igual que en `TICKER_SUBSECTOR`, una empresa que no
encaja con confianza en ningún grupo se deja fuera en vez de forzarla: por
eso los grupos de un sector no siempre suman el 100% del top-20 (p. ej.
Omnicom, una agencia de publicidad tradicional, o News Corp, una editorial
por su SIC real, se quedan fuera de los grupos de Comunicaciones).

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
   **Renta variable**, entre 2 y 5 de los 11 sectores posibles; **Oro**,
   entre 0 y 2 (oro físico y mineras de oro). Con menos aceptables que el
   suelo, se completa hasta el suelo con los siguientes mejores aunque
   puntúen negativo — el suelo evita la cartera vacía o concentrada en un
   único nombre, no es una opinión sobre esos activos. Con más aceptables
   que el techo, se recorta a los mejores. Un mes puede tener 2 sectores;
   otro, 5 — y el oro puede no aparecer en absoluto si la fase no lo
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
| Entre 2 y 5 sectores, nunca fijo (2-3 en Estanflación, ver 7.4) | Un único sector sobre una cartera 100 % invertida es un riesgo idiosincrático que nadie pidió. El techo bajó de 7 a 5 tras comprobar con el propio backtest que concentrarse en los cinco con mejor ventaja de fase —dejando fuera a los más débiles aunque también puntúen positivo— rinde mejor que diversificar hasta 7: CAGR +0,25 a +0,29 puntos en los 4 esquemas de reparto, Sharpe igual o mejor, caída máxima casi idéntica; el único coste es 1-2 años menos, de 47, batiendo al S&P 500. Dentro de ese rango, manda la fase: cuantos puntúen positivo de verdad, ni uno más para rellenar cupo. Estanflación es la excepción: techo fijo en 3, no 5 — ver 7.4 |
| Índices agregados excluidos de la selección | S&P total, EAFE, emergentes y small caps copan la selección si se les deja, y desaparece la rotación sectorial. Siguen en la matriz como referencia |
| Series no invertibles excluidas | PPI y WTI spot no se pueden mantener en cartera |
| "Consumo duradero" (Durbl) excluido del todo | Ken French lo separa de "Consumo discrecional" (Shops) como industria propia, con su propia serie de retornos, pero no existe un ETF sectorial real que trackee bienes duraderos aparte del consumo discrecional — el mapeo real caía en el mismo IYC/XLY que "Consumo discrecional". Con los dos como sectores independientes, la cartera podía recomendar ambos a la vez en la misma fase: dos nombres, dos líneas en "qué comprar ahora", **la misma orden de compra**. Se descarta la industria entera de la fuente en vez de parchear la selección, porque el problema no es la selección — es que ese sector no tiene una forma real de comprarse aparte |
| 10 de los 11 sectores son mutuamente excluyentes por construcción | No hay un "Bancos" aparte de "Financiero" que pudiera duplicar la misma apuesta, y cada uno tiene un ETF sectorial real y distinto (ver el mapeo en `app.js`) |
| Semiconductores sí solapa con Tecnología, y se resuelve explícitamente | A diferencia del resto, Semiconductores (Ken French, 49 industrias, "Chips") comparte por código SIC casi toda su exposición con Tecnología (BusEq, la agregada de las 12): dejarlos competir libremente contaría en parte la misma exposición dos veces. `ASSET_OVERLAP` impide que los dos entren a la vez en el mismo bloque — de los dos, solo sigue en carrera el que muestre mejor ir esa fase, el mismo criterio de desempate que usa el resto de `_sleeve_pick`. Se añadió porque, hoy, los semiconductores son un eje de inversión propio (capex de IA, capacidad de fabricación) que hace treinta años era solo una pieza más de "equipo de negocio" — verificado con datos reales: gana el hueco a Tecnología en Sobrecalentamiento y Estanflación (antes sin exposición a tecnología en absoluto en esas fases), nunca coexisten, y el backtest mejora |
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
aparte de si el marco tiene memoria, no una fuente directa de la cartera de
7.2. Pero sí sirvió para diagnosticar un problema real que 7.2 tuvo que
resolver — el único caso, por ahora, en que esta comprobación encontró algo
y la cartera cambió a raíz de ello.

**Por qué Estanflación tiene un techo distinto (3, no 5).** Un usuario señaló
que la cartera de renta variable llevaba demasiados años perdiendo contra el
S&P 500 desde 2009 y pidió investigarlo, en vez de aceptar la explicación
fácil de "la diversificación cuesta rentabilidad en un mercado alcista
concentrado". El laboratorio de esta sección ya tenía la causa medida:
Estanflación es la única de las cuatro fases con persistencia claramente
**negativa** entre su primera y segunda mitad cronológica (rank_ic -0,27,
asset_ic -0,44) — lo que mejor rindió antes tiende a rendir peor después, no
simplemente "sin relación". Sobrecalentamiento (+0,51) y Reflación (+0,30)
muestran persistencia real; Recuperación (-0,18) está dentro de ruido.
Estanflación es el único caso franco.

Probado con el propio motor de selección (no con 7.4, que no decide nada),
en este orden:

1. **Diversificar más** en Estanflación (todo el universo de ~14 sectores, o
   una banda ancha de 7): empeora todo lo medible — Sharpe, CAGR, caída
   máxima, y el propio desfase frente al mercado en esa fase desde 2009 (de
   -0,16 a -0,25/-0,30 puntos porcentuales al mes). Diluir hacia sectores de
   peor ventaja por volatilidad no sustituye acertar, empeora las cosas.
2. **Momentum puro** (media de los últimos 6 o 12 meses, sin condicionar a la
   fase) en vez de la ventaja de fase: la peor variante probada — Sharpe
   0,64, caída máxima -44,6 %, el desfase se dispara a -0,47 puntos.
3. **Concentrar más** (lo contrario de 1): 2 o 3 sectores fijos, no la banda
   2-5 normal. Aislado con un control — 2 fijos en las *otras* tres fases,
   dejando Estanflación intacta: el Sharpe global empeora (0,62), así que el
   efecto no es general, es específico de concentrar Estanflación. El
   resultado, comparando esquema a esquema (no el que más CAGR da en cada
   variante, que cambia y puede confundir la comparación): 3 fijos mejora el
   Sharpe en los 4 esquemas de reparto a la vez, aunque modesto (+0,01 a
   +0,02), y reduce el desfase de Estanflación desde 2009 a menos de la
   mitad en los 4 esquemas (de -0,16/-0,18/-0,27/-0,17 a -0,04/-0,07/-0,13/
   -0,06 puntos al mes). El coste real es una caída máxima histórica algo
   peor en los 4 esquemas — pero ocurre en julio de 1982 (Volcker), no en el
   tramo reciente que motivó la pregunta. Una banda (2,3) que dejara decidir
   al propio mecanismo cada mes, en vez de fijarlo siempre a 3, quedó peor
   que cualquiera de los dos extremos puros — alternar entre 2 y 3 nombres
   mes a mes no capturaba lo bueno de ninguno.

Esto no convierte Estanflación en una fase ganadora — la cartera sigue sin
batir al mercado ahí, el desfase sigue siendo negativo — pero reduce
sustancialmente cuánto pierde, con el mismo nivel de riesgo aproximado.

### 7.5 El reloj de renta fija (paralelo, nunca combinado)

El panel tiene **dos relojes independientes**, seleccionables con un desplegable
encima de «Qué comprar ahora»: el de renta variable (7.1-7.4) y uno de renta fija
con la misma estructura — «Qué comprar ahora», «El backtest» y «Laboratorio» —
pero universo, benchmark y resultados propios. Nunca se combinan: activar uno no
mezcla ni un solo número con el otro, ni en la cartera ni en el backtest.

**Universo.** Los 14 activos de clase "Renta fija" que ya existen en el sistema
(sección 2.2): Treasury a 2, 10 y 30 años, crédito investment-grade (LQD),
high-yield (HYG) y ultracorto plazo (ICSH), TIPS (yield sintético a 10 años y
el ETF TIP), titulizaciones hipotecarias (el tipo hipotecario a 30 años como
yield sintético y el ETF MBB), deuda emergente (EMB), municipales (MUB) y
crédito Baa/Aaa (yields Moody's, sintéticos), más Liquidez (letras 3 meses) —
ver más abajo por qué esta sí entra aquí aunque quede fuera del reloj de
renta variable. Tres pares solapan
la misma exposición económica medida por dos fuentes distintas — un yield FRED
convertido a retorno sintético y el ETF real que mide, en esencia, lo mismo —
y se resuelven con el mismo mecanismo `ASSET_OVERLAP` que ya separaba
Semiconductores de Tecnología: hipotecario aprox./MBB, TIPS aprox./TIP, Baa
aprox./LQD. Solo sigue en carrera el que muestre mejor ventaja de fase; nunca
compiten los dos por el mismo hueco.

**Benchmark.** El agregado de bonos de EE.UU. (AGG), con clase "Índice
regional" — el mismo mecanismo que ya deja fuera de la selección al S&P 500 en
el reloj de renta variable: ningún bloque de `SLEEVES_FI` incluye esa clase,
así que el benchmark nunca puede ser, por construcción, una posición de la
cartera. La comparación primaria de «El backtest» es contra este agregado, no
contra el S&P 500 ni contra un 60/40 (que no se publica en este reloj: no
tiene sentido como referencia de una cartera ya 100 % renta fija).

**La cartera implementable.** Un único bloque, banda fija al 100 % — no hay
renta variable ni oro que compita por peso en este reloj. Dentro de él, el
suelo es 2 (la misma razón que en renta variable: nunca una única posición,
aunque puntúe mejor que cualquier otra) y el **techo también es 2**, así que
el bloque sostiene siempre los dos activos de renta fija con mejor ventaja de
fase, ni uno más. A diferencia del techo de renta variable (5 de 11, sección
7.2), este número **sí se determinó por completo con el backtest**, no por
una regla de diversificación mínima: probando cada techo entre 2 y 10 sobre
las hasta 10 exposiciones únicas del universo moderno (2003-2026), el techo de
2 gana con claridad en los cuatro esquemas de reparto a la vez y en las cinco
métricas a la vez. Con datos reales, esquema equiponderado, techo 2 frente a
techo 5: CAGR 4,01 % frente a 3,14 %, Sharpe 0,63 frente a 0,48, caída máxima
−27,7 % frente a −31,6 %, peor 12 meses −19,4 % frente a −23,1 % — el mismo
patrón, sin excepción, en inverso de la volatilidad, por puesto y mitad y
mitad. La explicación no es azar: los sectores de bolsa son exposiciones
económicas genuinamente distintas entre sí (Energía no se mueve como
Tecnología), así que diversificar entre varios reduce riesgo idiosincrático
real; casi todo el universo de renta fija, en cambio, comparte un único factor
de fondo — tipos de interés y duración —, así que un tercer o cuarto activo no
añade una exposición nueva de verdad: solo diluye la apuesta de fase hacia la
media del conjunto.

**Por qué Liquidez sí entra aquí y no en renta variable.** En renta variable,
"Liquidez (letras 3 meses)" queda fuera de la selección (`NOT_SELECTABLE`, ver
7.2): su exceso sobre el tipo sin riesgo es el spread real, pero diminuto (de
media 0,11 % anualizado, con 0,15 % de volatilidad) entre la letra a 3 meses de
FRED y la letra a 1 mes de Ken French que se usa como tipo sin riesgo global —
no una resta contra sí misma, pero sí casi. El problema no es que no tenga
señal: es que con una volatilidad así de baja, frente a sectores de bolsa que
mueven 15-20 % al año, el ratio rentabilidad/volatilidad se dispara y el
reparto por inverso de volatilidad le da un peso desproporcionado — comprobado
con datos reales, la cartera de renta variable acababa con una cuarta parte
del dinero parado sin que la rentabilidad lo justificara.

Frente a renta fija (4-7 % de volatilidad típica, no 15-20 %) el mismo
mecanismo pesa mucho menos, y **probado con datos reales en vez de asumido por
analogía**, no reproduce el problema: con el propio techo de 2, dejar que
Liquidez compita por un hueco mejora el Sharpe en los cuatro esquemas de
reparto a la vez (0,63→0,69, 0,60→0,68, 0,63→0,70, 0,62→0,71) y reduce la
caída máxima con fuerza (p. ej. inverso de la volatilidad, −29,6 %→−15,2 %),
con el CAGR prácticamente plano. Entra solo en Sobrecalentamiento — ocupando
uno de los dos huecos, nunca desplazando a los otros activos en las tres fases
restantes —, lo que además tiene sentido económico: es la fase en la que subir
tipos presiona a la baja a toda la curva de renta fija a la vez, y un ancla de
duración casi nula amortigua esa presión sin apenas coste de rentabilidad.
También se comprobó que subir el techo a 3 o 4 con Liquidez ya elegible no
ayuda — empeora en las mismas métricas que ya empeoraba sin ella —, así que el
techo se queda en 2 y Liquidez compite en igualdad de condiciones con el resto
del universo, sin trato especial.

**El tramo bajista de 2021-2024, y el candidato que sí ayudó.** Con este
diseño, el reloj de renta fija tuvo cuatro años seguidos en negativo
(2021-2024): coincide con el peor mercado bajista de bonos en décadas — en
2022, hasta el propio AGG cayó −14,24 %. La cartera ya amortiguaba bastante
frente a comprar el agregado sin más (−6,58 % ese mismo año), pero no evitaba
la caída del todo. Antes de dar el diseño por cerrado se probaron, con datos
reales y no por intuición, tres vías más:

- Préstamos bancarios a tipo flotante (BKLN), casi sin duración: **empeoró**
  el resultado. 2022 no fue solo un shock de tipos, también de diferencial de
  crédito, y los préstamos bancarios sí tienen riesgo de crédito — cayeron a
  la par que el resto en los meses peores en vez de proteger la cartera.
- Soberanos internacionales cubiertos en dólares (BNDX): **también empeoró**
  — la subida de tipos de 2022 fue una respuesta sincronizada de bancos
  centrales a nivel global, no solo de la Reserva Federal, así que cubrir el
  riesgo de divisa no evita el mismo shock de fondo.
- Bonos investment-grade de ultra corto plazo, ~6 meses de duración (ICSH):
  **sí ayudó**, de forma consistente en los cuatro esquemas de reparto.
  Esquema Inverso de la volatilidad: Sharpe 0,68→0,72, caída máxima
  −13,3 %→−9,7 %, peor 12 meses −9,2 %→−6,5 %, con el CAGR prácticamente
  plano o mejor. La diferencia con BKLN es el grado: al ser investment-grade
  (no high yield) y de duración muy corta, no carga ni el riesgo de tipos de
  un bono largo ni el riesgo de crédito que hundió a los préstamos bancarios
  — en los meses más duros de 2022 se mantuvo prácticamente plano. Entra al
  universo, no como excepción: compite por el mismo hueco que Liquidez en
  Sobrecalentamiento, sin preferencia fija por ninguno de los dos. Confirmado
  de nuevo que el techo de 2 sigue siendo el óptimo con ICSH ya en el
  universo — el Sharpe cae de forma monótona al subir el techo, el mismo
  patrón que sin él.

El resto del mecanismo es idéntico al de 7.2, reutilizando el mismo código con
otros parámetros: la misma ventaja de fase contraída con James-Stein, el mismo
desempate por rendimiento real sin contraer, los mismos cuatro esquemas de
reparto calculados en paralelo, la misma tolerancia de retraso de publicación
y el mismo guardián de plausibilidad. El laboratorio de 7.4 se repite también,
con `k=2` (el techo real de este reloj, igual que 7.4 usa `k=5` porque es el
techo real del otro) sobre el mismo universo de hasta 15 candidatos.

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

## 12. Auditoría de octubre de 2026: borde irregular, fiabilidad y familia extendida

**Borde irregular.** Las series macro se publican con retrasos distintos. El factor se calculaba
como media ponderada de las series *disponibles*, de modo que en un mes con una sola serie viva
(nóminas, 9% del peso) el factor era esa serie: el crecimiento saltó a −1,06. Ahora se arrastra
el último z de cada serie hasta 2 meses (`TAIL_FILL_M`), se exige ≥80% del peso de cobertura en
crecimiento e inflación (`MIN_TAIL_COVERAGE`) y se descartan los meses finales que no lleguen. Si
menos del 90% del peso tiene dato nuevo, `current.edge.nowcast = true` y la web lo marca como
estimación provisional. Series con última observación a más de 6 meses del final del panel (p. ej.
USSLIND, último dato 2020-02) se excluyen del PCA con aviso.

**Fiabilidad por casilla** (`reliability_label`): *Fuerte* = nota ++/+++, FDR q ≤ 0,10, mismo signo del
exceso en las dos mitades de la muestra, mismo signo usando la fase con un mes de retraso, y ≥ 60 meses
de esa fase. *Moderada* = nota ++/+++, estable en las dos mitades, ≥ 36 meses y (FDR o retraso).
*Débil* = tiene nota pero falla alguna comprobación. *Sin señal* = nota 0. No se puede "forzar" una señal
a Fuerte: solo más historia o más activos independientes la sostienen.

**Fuerza de la fase actual** (`current.call_strength`): margen ≥ 0,6 Fuerte; 0,3–0,6 Moderada; < 0,3 Débil.

**Familia extendida** (`extended`): Japón, Europa, Asia-Pacífico ex Japón y Norteamérica (Ken French),
small caps (cartera Lo 20), y ETF IBB, XBI, MCHI, FXI, EWJ. Familia de contrastes propia, fuera del
backtest, la rotación, el laboratorio y el consenso. Los nombres de archivo de French no se han podido
verificar desde el entorno de desarrollo; si fallan, se anotan en `extended.meta.log`.

**Contraste «ahora»** (`now_edge`): exceso mensual ~ constante + probabilidades de fase del mes anterior (una fase omitida), covarianza HAC. Se contrasta p_hoy − p̄ (un solo contraste por activo, BH entre activos). Validación fuera de muestra con ventana creciente desde 180 meses: R² OOS frente a la media creciente y Clark-West. Fuerte exige |t| ≥ 1,96, q ≤ 0,10, R² OOS > 0 y CW t ≥ 1,28.
