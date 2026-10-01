/* Reloj de inversión — render del panel. Sin dependencias externas. */
(() => {
"use strict";

const NS = "http://www.w3.org/2000/svg";

/* Colores literales (duplican las variables CSS): los presentation-attributes
   SVG no resuelven var() de forma fiable en todos los motores. */
const PHASE_COLOR = {
  "Recuperación": "#3F6B52",
  "Sobrecalentamiento": "#B8863B",
  "Estanflación": "#9C4A3C",
  "Reflación": "#3E4E7A",
};
const INK = "#1B1810", INK_SOFT = "#5B5340", INK_FAINT = "#8C8268";
const LINE = "rgba(27,24,16,.14)", LINE_SOFT = "rgba(27,24,16,.08)", LINE_STRONG = "rgba(27,24,16,.30)";
const POS = "#3F6B52", NEG = "#9C4A3C";

/* Ventanas del gráfico de evolución (#rotChart). "n" = nº de meses finales a
   mostrar; null = todo el histórico; "ytd" = desde enero del año del último
   dato disponible. */
const CURVE_RANGES = [
  { k: "1m", label: "1M", n: 1 },
  { k: "6m", label: "6M", n: 6 },
  { k: "ytd", label: "YTD", n: "ytd" },
  { k: "1y", label: "1A", n: 12 },
  { k: "3y", label: "3A", n: 36 },
  { k: "5y", label: "5A", n: 60 },
  { k: "max", label: "Máx.", n: null },
];

function sliceCurveRange(c, key) {
  // El mes en curso puede llegar sin benchmark aún (algunas fuentes lo
  // publican con más retraso que los activos de la cartera) — mostrarlo
  // como un punto suelto con "b: null" congelaría el índice en una línea
  // plana que no es su retorno real. Se recorta antes de aplicar la
  // ventana, para que "1M" no sea justo ese mes a medias.
  let end = c.length;
  while (end > 0 && c[end - 1].b == null) end--;
  c = c.slice(0, end);
  if (!c.length) return c;
  const r = CURVE_RANGES.find(x => x.k === key);
  if (!r || r.n === null) return c;
  if (r.n === "ytd") {
    const yr = c[c.length - 1].d.slice(0, 4);
    return c.filter(p => p.d.slice(0, 4) === yr);
  }
  return c.slice(-r.n);
}

const PHASE_HINT = {
  "Recuperación": "crecimiento sobre tendencia, inflación bajo tendencia",
  "Sobrecalentamiento": "crecimiento e inflación por encima de tendencia",
  "Estanflación": "crecimiento bajo tendencia, inflación por encima",
  "Reflación": "crecimiento e inflación por debajo de tendencia",
};
const PHASE_DEF = {
  "Recuperación": "el crecimiento repunta por encima de su tendencia reciente mientras la inflación " +
    "todavía cede. Es la salida clásica de una desaceleración: la política monetaria sigue laxa y los " +
    "beneficios empresariales aceleran antes de que lo hagan los precios. En el <i>investment clock</i> " +
    "clásico (Merrill Lynch, 2004) es la fase que históricamente mejor ha tratado a la renta variable cíclica.",
  "Sobrecalentamiento": "el crecimiento sigue por encima de tendencia, pero la inflación ya se ha unido " +
    "a la subida. La economía va cerca de plena capacidad y las presiones de precios empiezan a exigir " +
    "una política monetaria más dura. Los activos reales y los sectores con poder de fijación de precios " +
    "suelen tratarse mejor aquí que la renta fija.",
  "Estanflación": "el crecimiento ha caído por debajo de tendencia mientras la inflación se mantiene por " +
    "encima. Es la fase más hostil para los activos financieros en conjunto: ni el crecimiento sostiene los " +
    "beneficios ni la inflación permite bajar tipos con rapidez. Los sectores defensivos con demanda " +
    "inelástica suelen sufrir menos que el mercado en su conjunto.",
  "Reflación": "el crecimiento y la inflación están los dos por debajo de tendencia. Suele coincidir con " +
    "el tramo final de una recesión o los meses posteriores, cuando el banco central ya baja tipos con " +
    "fuerza. Es, históricamente, la mejor fase para la duración en renta fija.",
};
const BLOCK_TITLE = {
  growth: "Crecimiento (coincidente)",
  inflation: "Inflación",
  leading: "Condiciones financieras",
  standalone: "Aparte del PCA",
};
const MONTHS = ["ene","feb","mar","abr","may","jun","jul","ago","sep","oct","nov","dic"];

/* ------------------------- ETFs reales por activo ------------------------ */
/* Instrumento más parecido para ejecutar cada exposición hoy. Preferencia por
   iShares (familia IY-- de sectores US, más el resto de su gama); se añade el
   SPDR sectorial (XL-) como alternativa más líquida y con historia algo más
   larga. Donde no existe un ETF exacto para la definición académica del
   activo, se marca "aprox." y se explica la diferencia. */
const ETF_MAP = {
  "Tecnología": [["IYW","iShares US Technology"], ["XLK","Technology Select Sector SPDR"]],
  "Semiconductores": [["SOXX","iShares Semiconductor ETF"], ["SMH","VanEck Semiconductor ETF"]],
  "Salud": [["IYH","iShares US Healthcare"], ["XLV","Health Care Select Sector SPDR"], ["IBB","iShares Biotechnology"]],
  "Energía": [["IYE","iShares US Energy"], ["XLE","Energy Select Sector SPDR"]],
  "Comunicaciones": [["IYZ","iShares US Telecommunications"], ["XLC","Communication Services SPDR"]],
  "Financiero": [["IYF","iShares US Financials"], ["XLF","Financial Select Sector SPDR"]],
  "Industria": [["IYJ","iShares US Industrials"], ["XLI","Industrial Select Sector SPDR"]],
  "Materiales / Químicas": [["IYM","iShares US Basic Materials"], ["XLB","Materials Select Sector SPDR"]],
  "Utilities": [["IDU","iShares US Utilities"], ["XLU","Utilities Select Sector SPDR"]],
  "Consumo discrecional": [["IYC","iShares US Consumer Discretionary"], ["XLY","Consumer Discretionary SPDR"]],
  "Consumo básico": [["IYK","iShares US Consumer Goods"], ["XLP","Consumer Staples Select Sector SPDR"]],
  "Inmobiliario": [["IYR","iShares US Real Estate"], ["XLRE","Real Estate Select Sector SPDR"]],
  "Metales preciosos (mineras)": [["RING","iShares MSCI Global Gold Miners"], ["GDX","VanEck Gold Miners"]],
  "Oro (lingote)": [["IAU","iShares Gold Trust"]],
  "Plata": [["SLV","iShares Silver Trust"]],
  "Cobre": [["CPER","US Copper Index Fund (aprox.)"]],
  "Materias primas (índice)": [["GSG","iShares S&P GSCI Commodity-Indexed Trust"]],
  "Treasury 2 años": [["SHY","iShares 1-3 Year Treasury Bond"]],
  "Treasury 10 años": [["IEF","iShares 7-10 Year Treasury Bond"]],
  "Treasury 30 años": [["TLT","iShares 20+ Year Treasury Bond"]],
  "Hipotecario 30 años (aprox.)": [["MBB","iShares MBS ETF"]],
  "Crédito Baa (aprox.)": [["LQD","iShares iBoxx $ IG Corporate Bond"]],
  "Crédito Aaa (aprox.)": [["LQD","iShares iBoxx $ IG Corporate Bond (aprox.)"]],
  "Crédito Investment Grade (LQD)": [["LQD","iShares iBoxx $ IG Corporate Bond"]],
  "Crédito High Yield (HYG)": [["HYG","iShares iBoxx $ High Yield Corporate Bond"]],
  "Deuda emergente (EMB)": [["EMB","iShares J.P. Morgan USD Emerging Markets Bond"]],
  "TIPS (TIP)": [["TIP","iShares TIPS Bond"]],
  "TIPS 10 años (aprox.)": [["TIP","iShares TIPS Bond (aprox.)"]],
  "Municipales (MUB)": [["MUB","iShares National Muni Bond"]],
  "Titulizaciones hipotecarias (MBB)": [["MBB","iShares MBS ETF"]],
  "Liquidez (letras 3m)": [["SHV","iShares Short Treasury Bond"]],
  "Renta variable EE.UU. (mercado)": [["ITOT","iShares Core S&P Total US Stock Market"]],
  "Desarrollados ex EE.UU. (French)": [["IEFA","iShares Core MSCI EAFE"]],
  "Renta variable internacional": [["EFA","iShares MSCI EAFE"]],
  "Emergentes (French)": [["IEMG","iShares Core MSCI Emerging Markets"]],
  "Renta variable emergente": [["EEM","iShares MSCI Emerging Markets"]],
  "Small caps": [["IWM","iShares Russell 2000"]],
};
function tickerChips(name) {
  const list = ETF_MAP[name];
  if (!list) return "";
  return list.map(([t, n]) => `<span class="tick" title="${n}">${t}</span>`).join("");
}

let D = null;              // payload
let trail = 36;
let activeClass = "Todo";
let onlySig = false;
let playTimer = null;
let clockMode = "eq";      // "eq" renta variable | "fi" renta fija — nunca combinados

/* ------------------------------ utilidades ------------------------------ */
const $ = (sel, root = document) => root.querySelector(sel);
const el = (tag, attrs = {}, parent = null) => {
  const n = document.createElementNS(NS, tag);
  for (const k in attrs) n.setAttribute(k, attrs[k]);
  if (parent) parent.appendChild(n);
  return n;
};
const txt = (tag, attrs, content, parent) => {
  const n = el(tag, attrs, parent);
  n.textContent = content;
  return n;
};
const fmtPct = (v, d = 0) => v === null || v === undefined || Number.isNaN(v)
  ? "—" : `${(v * 100).toFixed(d)}%`;
const fmtNum = (v, d = 2) => v === null || v === undefined || Number.isNaN(v)
  ? "—" : Number(v).toFixed(d);
const signed = (v, d = 1) => v === null || v === undefined || Number.isNaN(v)
  ? "—" : `${v > 0 ? "+" : ""}${Number(v).toFixed(d)}`;
const label = (ym) => {
  const [y, m] = ym.split("-").map(Number);
  return `${MONTHS[m - 1]} ${y}`;
};

function diverging(v, scale) {
  const t = Math.max(-1, Math.min(1, v / scale));
  const a = 0.10 + 0.55 * Math.abs(t);
  return t >= 0 ? `rgba(63,107,82,${a.toFixed(3)})` : `rgba(156,74,60,${a.toFixed(3)})`;
}

/* --------------------------------- carga -------------------------------- */
async function boot() {
  try {
    const res = await fetch(`data/data.json?v=${Date.now()}`, { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    D = await res.json();
  } catch (err) {
    showError(err);
    return;
  }
  render();
}

function showError(err) {
  $("#loading").remove();
  const app = $("#app");
  app.innerHTML = `
    <div class="wrap">
      <div class="errbox">
        <h2>Todavía no hay datos que mostrar</h2>
        <p>El panel lee <code>docs/data/data.json</code>, que genera la acción programada del repositorio.
        Lanza el flujo <b>Actualizar datos</b> en la pestaña Actions y recarga esta página.</p>
        <p><code>${String(err)}</code></p>
      </div>
    </div>`;
}

function render() {
  const tpl = $("#tpl-main").content.cloneNode(true);
  $("#loading").remove();
  $("#app").appendChild(tpl);

  renderTopBar();
  renderHero();
  renderOutlook();
  renderPlane();
  wireClockToggle();
  renderBuy();
  renderIndicators();
  renderTimeline();
  renderMatrix();
  renderRobustness();
  renderConsensus();
  renderRotation();
  renderLab();
  renderValidation();
  renderDiagnostics();
  renderMethod();
  renderFooter();
  wireControls();
}

/* -------------------------------- cabecera ------------------------------ */
function renderTopBar() {
  $("#topUpdated").textContent = `Actualizado ${D.meta.generated_utc}`;
}

/* --------------------------------- hero ---------------------------------- */
function monthsInPhase() {
  const h = D.history, p = D.current.phase;
  let n = 0;
  for (let i = h.length - 1; i >= 0 && h[i].p === p; i--) n++;
  return n;
}

function phaseWhyText(c) {
  const gDir = c.growth >= 0 ? "por encima" : "por debajo";
  const iDir = c.inflation >= 0 ? "por encima" : "por debajo";
  const mg = c.momentum?.growth_3m, mi = c.momentum?.inflation_3m;
  const mgTxt = mg == null ? "" : (mg >= 0.10 ? ", acelerando" : mg <= -0.10 ? ", perdiendo fuerza" : ", estable");
  const miTxt = mi == null ? "" : (mi >= 0.10 ? ", subiendo" : mi <= -0.10 ? ", cediendo" : ", estable");
  return `El crecimiento está <b>${fmtNum(Math.abs(c.growth), 2)}σ ${gDir}</b> de su tendencia de los
    últimos diez años${mgTxt}; la inflación, <b>${fmtNum(Math.abs(c.inflation), 2)}σ ${iDir}</b> de la
    suya${miTxt} — <span class="small-cap">σ</span> son desviaciones estándar: cuántas veces la variación
    típica de la última década se aleja el dato de hoy de lo normal reciente, la misma vara de medir para
    crecimiento e inflación aunque una se mida en % interanual y la otra en puntos de otra escala, así que
    +1σ en una es comparable a +1σ en la otra. Bajo esa combinación, ${PHASE_DEF[c.phase]}`;
}

function confidenceText(c) {
  const q = c.confidence;
  if (q >= 0.6) {
    return `Las dos dimensiones están lo bastante lejos de cero como para que el cuadrante aguante el
      ruido de medición: tiene sentido posicionarse por la fase principal.`;
  }
  if (q >= 0.3) {
    return `El margen sobre <b>${c.alt_phase}</b> es estrecho. Conviene inclinar la cartera hacia lo que
      funciona en las dos fases antes que apostar todo a una sola — ver «solapamiento» más abajo.`;
  }
  return `La economía está prácticamente encima de un eje: la clasificación es frágil. Prioriza los
    activos de consenso y evita apuestas que dependan del cuadrante exacto.`;
}

function renderHero() {
  const c = D.current;
  const color = PHASE_COLOR[c.phase];
  const probs = D.phases.map(p => [p, c.probs[p] ?? 0]).sort((a, b) => b[1] - a[1]);
  const n = monthsInPhase();
  const rec = c.recession || {};

  $("#phaseName").textContent = c.phase_long;
  $("#phaseName").style.color = color;
  // Con el margen por debajo de 30 puntos la fase "principal" es, en la
  // práctica, casi una moneda al aire frente a la segunda — un aviso de
  // 13px bajo un titular de hasta 64px pasaba desapercibido (ver
  // METODOLOGIA.md, la propia fase actual en el momento de escribir esto
  // tenía 4,4 puntos de margen). El aviso va pegado al titular, no perdido
  // más abajo entre las estadísticas.
  $("#phaseTie").innerHTML = c.confidence < 0.3
    ? `⚠ Margen de solo <b>${fmtPct(c.confidence)}</b> sobre ${probs[1][0]} (${fmtPct(probs[0][1], 1)} vs ${fmtPct(probs[1][1], 1)}) — casi un empate`
    : "";
  $("#phaseWindow").textContent =
    `${n} ${n === 1 ? "mes" : "meses"} seguidos en esta fase · ${PHASE_HINT[c.phase]} · dato de ${label(c.date)}`;
  $("#phaseWhy").innerHTML = phaseWhyText(c);

  $("#confBlock").innerHTML = probs.map(([p, v], i) => `
    <div class="conf-row ${i === 0 ? "lead" : ""}">
      <span class="nm">${p}</span>
      <span class="conf-bar"><i style="width:${(v * 100).toFixed(1)}%;background:${PHASE_COLOR[p]}"></i></span>
      <span class="conf-val">${fmtPct(v, 1)}</span>
    </div>`).join("");
  $("#confNote").innerHTML = `<b>${fmtPct(c.confidence)}</b> de margen sobre ${c.alt_phase}. ${confidenceText(c)}`;

  $("#heroStats").innerHTML = [
    ["Impulso crecimiento 3m", signed(c.momentum?.growth_3m, 2) + " σ"],
    ["Impulso inflación 3m", signed(c.momentum?.inflation_3m, 2) + " σ"],
    ["Recesión a 12 meses", rec.prob_12m != null ? fmtPct(rec.prob_12m, 0) : "—"],
    ["Series activas", `${D.meta.series_ok}/${D.meta.series_total}`],
  ].map(([k, v]) => `<div class="hero-stat"><dt>${k}</dt><dd>${v}</dd></div>`).join("");
}

function mostLikelyNext() {
  // row[a][b] es la probabilidad, mes a mes, de que el mes que viene sea b
  // estando ahora en a — INCLUYE quedarse en la misma fase, que casi
  // siempre domina (las fases duran años, no meses). Mostrar esa fracción
  // cruda como "la transición más probable" confunde: un 11% suena bajo
  // para ser "lo más probable" y además se parece, sin serlo, al 32% de
  // probabilidad de fase actual del bloque de arriba (dos cosas distintas:
  // esa es cuán segura está la clasificación de ESTE mes, no hacia dónde
  // va el que viene). Lo que se muestra aquí es la pregunta que de verdad
  // importa: SI la fase cambia, ¿adónde suele ir? — la distribución entre
  // las otras tres fases, normalizada a que sumen 100% entre ellas.
  const row = D.validation.transition?.[D.current.phase] || {};
  const stay = row[D.current.phase] || 0;
  const moves = Object.entries(row).filter(([p]) => p !== D.current.phase);
  const moveTotal = moves.reduce((s, [, v]) => s + v, 0);
  let best = { phase: "—", p: 0 };
  for (const [p, v] of moves) {
    const cond = moveTotal > 0 ? v / moveTotal : 0;
    if (cond > best.p) best = { phase: p, p: cond };
  }
  return { ...best, stay };
}

function renderOutlook() {
  const c = D.current, rec = c.recession || {};
  const lead = c.leading, lead6 = c.leading_6m;
  const dir = lead != null && lead6 != null ? lead - lead6 : null;
  const next = mostLikelyNext();
  $("#outlookBand").innerHTML = `
    <div class="item"><dt>Bloque adelantado</dt>
      <dd style="color:${lead >= 0 ? POS : NEG}">${signed(lead, 2)} σ</dd>
      <small>Curva, condiciones financieras, permisos, horas y diferenciales. ${
        dir == null ? "" : dir >= 0 ? "Mejorando frente a hace 6 meses." : "Deteriorándose frente a hace 6 meses."}</small></div>
    <div class="item"><dt>Si la fase cambia, va hacia</dt>
      <dd style="color:${PHASE_COLOR[next.phase]}">${next.phase}</dd>
      <small>Lo más probable, con diferencia, es que ${c.phase.toLowerCase()} simplemente siga
        (${fmtPct(next.stay, 0)} de los meses). Cuando sí ha cambiado en el histórico, ${fmtPct(next.p, 0)}
        de esas veces fue a parar aquí — no confundir con el ${fmtPct(c.probs?.[next.phase], 0)} de
        arriba, que es cuánto se parece <i>este mes</i> a ${next.phase}, no hacia dónde va el que viene.</small></div>
    <div class="item"><dt>Persistencia media</dt>
      <dd>${fmtNum(D.validation.duration_months?.[c.phase], 1)} meses</dd>
      <small>Duración media histórica de un tramo en ${c.phase}.</small></div>
    <div class="item"><dt>Modelo de recesión</dt>
      <dd>${rec.prob_12m != null ? fmtPct(rec.prob_12m, 0) : "—"}</dd>
      <small>${rec.auc ? `Probabilidad de que EE.UU. entre en recesión (según el NBER) en los próximos
        12 meses, de una regresión logística — un modelo estadístico estándar para estimar la
        probabilidad de un suceso de sí/no — entrenada con la curva de tipos y las condiciones
        financieras. Ajuste: AUC ${fmtNum(rec.auc, 2)} en ${rec.n_obs} meses — el "área bajo la curva ROC"
        mide qué tan bien distingue el modelo entre meses que acabaron en recesión y los que no; 0,50 es
        adivinar a cara o cruz, 1,00 es perfecto, y ${fmtNum(rec.auc, 2)} está ${rec.auc >= 0.8 ? "cerca del extremo bueno" : rec.auc >= 0.65 ? "claramente por encima del azar, sin ser perfecto" : "solo algo por encima del azar"}.` : "No disponible."}</small></div>`;
}

/* ------------------------- reloj: renta variable / renta fija ------------------------- */
// Dos relojes completamente independientes, nunca combinados (a petición explícita): cada
// uno con su propio universo, su propio benchmark y su propio backtest walk-forward, ya
// separados en build_data.py (rotation()/laboratory() con sleeves/bench_name distintos).
// clockMode decide solo qué mitad de los datos ya calculados se muestra — build_data.py
// nunca mezcla las dos carteras en un mismo número.
const CLOCK_TXT = {
  eq: {
    label: "Renta variable",
    lede: `100% renta variable de sectores, sin renta fija: el oro y las mineras de oro son
      el único seguro no bursátil, y nunca superan el 20%. Selección walk-forward, con datos solo
      hasta el mes anterior en cada fecha: en cada fase, qué sectores han pagado más de lo que pagan
      de media. El reparto dentro de cada bloque y el punto de partida exactos están más abajo —
      cambian con el dato, no están fijados aquí. Entre paréntesis, el ETF real
      más parecido para ejecutarlo hoy.`,
    note: "",
    buyFootIntro: `100% renta variable de sectores; el oro y las mineras de oro son el único seguro no
      bursátil, hasta un 20% y solo cuando la fase lo justifica.`,
    consensusEmptyWord: "sector u oro",
    benchLabel: "S&amp;P 500 / renta variable EE.UU. 100%",
    benchDt: "S&amp;P 500 / mercado",
    benchShort: "S&amp;P 500",
    title: "¿Bate al S&amp;P 500?",
    intro: `Cartera 100% renta variable de sectores (más oro y mineras de oro como único
      seguro no bursátil, hasta un 20%), solo de compras y sin apalancar. La fase decide qué
      sectores ocupan la cartera y cuánto peso lleva el oro dentro de su banda. Los índices
      agregados quedan fuera de la selección, así que esto es una apuesta por sectores, no el
      S&amp;P 500 disfrazado — y la pregunta que responde esta sección es si esa apuesta
      <b>compensó</b> frente a comprar el índice sin más.`,
    assetWord: "sector",
    assetWordPl: "sectores",
    selectionWord: "de sectores y de oro",
    insuranceClause: "el seguro de oro y ",
    pureBenchWord: "la renta variable pura",
    curveBenchLabel: "S&P 500 (mercado)",
    show6040: true,
  },
  fi: {
    label: "Renta fija",
    lede: `100% renta fija: gobierno (Treasury a 2, 10 y 30 años), crédito investment-grade y
      high-yield, TIPS, titulizaciones hipotecarias y deuda emergente — nunca renta variable ni
      oro en este reloj. Selección walk-forward, con datos solo hasta el mes anterior en cada
      fecha: en cada fase, qué instrumentos de renta fija han pagado más de lo que pagan de
      media. Entre paréntesis, el ETF real (o la nota "aprox." cuando la fuente es un
      rendimiento FRED convertido a retorno, ver metodología) más parecido para ejecutarlo hoy.`,
    note: `Reloj independiente del de renta variable: universo, benchmark y backtest walk-forward
      propios — nunca se combina con la cartera de acciones.`,
    buyFootIntro: `100% renta fija: gobierno, crédito, TIPS, titulizaciones hipotecarias y deuda
      emergente en un único bloque, sin renta variable ni oro en este reloj.`,
    consensusEmptyWord: "activo de renta fija",
    benchLabel: "Agregado de bonos EE.UU. (AGG) 100%",
    benchDt: "AGG / mercado",
    benchShort: "AGG",
    title: "¿Bate al agregado de bonos (AGG)?",
    intro: `Cartera 100% renta fija, solo de compras y sin apalancar, en un único bloque a banda
      fija (100%): no hay renta variable ni oro en este reloj. El agregado de bonos EE.UU. (AGG)
      queda fuera de la selección, como referencia — y la pregunta que responde esta sección es
      si la rotación por fase <b>compensó</b> frente a comprar el agregado sin más.`,
    assetWord: "activo de renta fija",
    assetWordPl: "activos de renta fija",
    selectionWord: "de activos de renta fija",
    insuranceClause: "",
    pureBenchWord: "el agregado de bonos puro",
    curveBenchLabel: "AGG (mercado)",
    show6040: false,
  },
};

function bandTxt(band) {
  const [lo, hi] = band || [];
  if (lo == null) return "—";
  return lo === hi ? `${lo}%` : `${lo}–${hi}%`;
}

function activeRotation() { return (clockMode === "fi" ? D.rotation_fi : D.rotation) || {}; }
function activeLab() { return (clockMode === "fi" ? D.lab_fi : D.lab) || {}; }
function activeConsensus() { return (clockMode === "fi" ? D.consensus_fi : D.consensus) || []; }

function wireClockToggle() {
  const seg = $("#clockModeSeg");
  if (!seg) return;
  seg.querySelectorAll("button").forEach(b => {
    b.setAttribute("aria-pressed", String(b.dataset.m === clockMode));
    b.onclick = () => {
      if (clockMode === b.dataset.m) return;
      clockMode = b.dataset.m;
      scheme = null; pbPhase = null; labPhase = null; labSleeve = null;
      seg.querySelectorAll("button").forEach(x => x.setAttribute("aria-pressed", String(x === b)));
      renderBuy();
      renderConsensus();
      renderRotation();
      renderLab();
    };
  });
}

/* ------------------------------ qué comprar ------------------------------ */
function renderBuy() {
  const host = $("#buyCols"), foot = $("#buyFoot"), lede = $("#buyLede"), note = $("#clockModeNote");
  const T = CLOCK_TXT[clockMode];
  lede.innerHTML = T.lede;
  note.innerHTML = T.note;
  note.style.display = T.note ? "" : "none";
  const r = activeRotation();
  if (!r.schemes) {
    host.innerHTML = `<div class="buy-col"><p class="buy-empty">
      Los datos publicados no traen la sección de asignación de ${T.label.toLowerCase()}. Ejecuta
      <code>scripts/build_data.py</code> de nuevo.</p></div>`;
    foot.innerHTML = "";
    return;
  }
  const scheme_ = r.schemes[r.default] || Object.values(r.schemes)[0];
  const c = D.current;
  const phase = c.phase;
  const rows = scheme_.playbook[phase] || [];
  const mix = scheme_.sleeve_mix?.[phase] || {};
  const sleeveOrder = Object.keys(r.bands || {});

  host.innerHTML = sleeveOrder.map(sl => {
    const items = rows.filter(x => x.sleeve === sl);
    const wt = mix[sl];
    return `<div class="buy-col">
      <h4><span>${sl}</span><span>${wt != null ? fmtNum(wt, 0) + "%" : ""}</span></h4>
      ${items.length ? items.map(x => `
        <div class="buy-item">
          <div><span class="nm">${x.name}</span><span class="tickers">${tickerChips(x.name) || `<span class="small-cap mono">${x.class}</span>`}</span></div>
          <span class="wt">${fmtNum(x.weight, 1)}%</span>
        </div>`).join("") : `<p class="buy-empty">Sin exposición en esta fase (banda ${bandTxt(r.bands?.[sl])}).</p>`}
    </div>`;
  }).join("");

  const consensus = activeConsensus();
  const lowConf = c.confidence < 0.6 && consensus.length;
  const bandsTxt = sleeveOrder.map(sl => `${bandTxt(r.bands[sl])} ${sl.toLowerCase()}`).join(", ");
  foot.innerHTML = `${T.buyFootIntro} Reparto <b>${scheme_.label.toLowerCase()}</b>
    dentro de cada bloque; el peso entre bloques se mueve según lo bien que puntúa cada uno en
    <b>${phase}</b>, dentro de bandas fijadas de antemano (${bandsTxt}).
    Fuente: rotación walk-forward desde ${(scheme_.portfolio?.from || "").slice(0, 4) || "—"},
    sección «El backtest» más abajo.
    ${lowConf ? ` Con solo <b>${fmtPct(c.confidence)}</b> de margen sobre ${c.alt_phase}, conviene mirar
      también el bloque de «solapamiento» — lo que ha pagado en las dos fases candidatas a la vez.` : ""}`;
}

/* ------------------------- plano de fase (firma) ------------------------ */
const PLANE = { w: 560, h: 500, padL: 46, padR: 24, padT: 20, padB: 46 };

function planeScales() {
  const pts = D.history;
  const gmax = Math.max(2.2, ...pts.map(p => Math.abs(p.g))) * 1.06;
  const imax = Math.max(2.2, ...pts.map(p => Math.abs(p.i))) * 1.06;
  const { w, h, padL, padR, padT, padB } = PLANE;
  return {
    x: g => padL + ((g + gmax) / (2 * gmax)) * (w - padL - padR),
    y: i => (h - padB) - ((i + imax) / (2 * imax)) * (h - padT - padB),
    gmax, imax,
  };
}

function renderPlane(cursor = null) {
  const svg = $("#plane");
  svg.innerHTML = "";
  const { w, h, padL, padR, padT, padB } = PLANE;
  const S = planeScales();
  const cx = S.x(0), cy = S.y(0);

  const quadDefs = [
    { name: "Sobrecalentamiento", x0: cx, x1: w - padR, y0: padT, y1: cy, ax: "end", ay: "top" },
    { name: "Recuperación", x0: cx, x1: w - padR, y0: cy, y1: h - padB, ax: "end", ay: "bottom" },
    { name: "Estanflación", x0: padL, x1: cx, y0: padT, y1: cy, ax: "start", ay: "top" },
    { name: "Reflación", x0: padL, x1: cx, y0: cy, y1: h - padB, ax: "start", ay: "bottom" },
  ];
  quadDefs.forEach(q => {
    el("rect", {
      x: q.x0, y: q.y0, width: q.x1 - q.x0, height: q.y1 - q.y0,
      fill: PHASE_COLOR[q.name], opacity: q.name === D.current.phase ? 0.11 : 0.04,
    }, svg);
  });

  for (let v = -3; v <= 3; v++) {
    if (v === 0) continue;
    if (Math.abs(v) < S.gmax) el("line", { x1: S.x(v), y1: padT, x2: S.x(v), y2: h - padB, stroke: LINE_SOFT, "stroke-width": 1 }, svg);
    if (Math.abs(v) < S.imax) el("line", { x1: padL, y1: S.y(v), x2: w - padR, y2: S.y(v), stroke: LINE_SOFT, "stroke-width": 1 }, svg);
  }
  el("line", { x1: padL, y1: cy, x2: w - padR, y2: cy, stroke: LINE_STRONG, "stroke-width": 1.2 }, svg);
  el("line", { x1: cx, y1: padT, x2: cx, y2: h - padB, stroke: LINE_STRONG, "stroke-width": 1.2 }, svg);

  /* Etiquetas de cuadrante: pegadas a su propia esquina exterior, nunca cerca
     del cruce de ejes donde vive el rastro — así no colisionan con nada. */
  quadDefs.forEach(q => {
    const tx = q.ax === "end" ? q.x1 - 10 : q.x0 + 10;
    const ty = q.ay === "top" ? q.y0 + 20 : q.y1 - 12;
    txt("text", {
      x: tx, y: ty, fill: PHASE_COLOR[q.name], "text-anchor": q.ax,
      "font-family": "IBM Plex Mono, monospace", "font-size": 11, "font-weight": 600,
      "letter-spacing": "0.02em", opacity: q.name === D.current.phase ? 0.95 : 0.55,
    }, q.name.toUpperCase(), svg);
  });

  /* Títulos de eje: exclusivamente en el margen, fuera del área de trazado. */
  txt("text", { x: w - padR, y: h - padB + 24, fill: INK_FAINT, "text-anchor": "end",
    "font-family": "IBM Plex Mono, monospace", "font-size": 10.5 }, "crecimiento →", svg);
  txt("text", { x: padL, y: h - padB + 24, fill: INK_FAINT, "text-anchor": "start",
    "font-family": "IBM Plex Mono, monospace", "font-size": 10.5 }, "← contracción", svg);
  const ayTop = padT + 4, ayBot = h - padB - 4;
  txt("text", { x: padL - 32, y: ayTop, fill: INK_FAINT, "text-anchor": "start",
    "font-family": "IBM Plex Mono, monospace", "font-size": 10.5,
    transform: `rotate(-90 ${padL - 32} ${ayTop})` }, "inflación →", svg);
  txt("text", { x: padL - 32, y: ayBot, fill: INK_FAINT, "text-anchor": "end",
    "font-family": "IBM Plex Mono, monospace", "font-size": 10.5,
    transform: `rotate(-90 ${padL - 32} ${ayBot})` }, "← desinflación", svg);

  const hist = D.history;
  const end = cursor == null ? hist.length : cursor + 1;
  const pts = hist.slice(Math.max(0, end - trail), end);
  if (pts.length > 1) {
    const dstr = pts.map((p, k) => `${k ? "L" : "M"}${S.x(p.g).toFixed(1)},${S.y(p.i).toFixed(1)}`).join("");
    el("path", { d: dstr, fill: "none", stroke: "#8C8268", "stroke-width": 1.4, opacity: 0.4, "stroke-linejoin": "round" }, svg);
  }
  pts.forEach((p, k) => {
    const rel = (k + 1) / pts.length;
    const c = el("circle", { cx: S.x(p.g), cy: S.y(p.i), r: 2.2 + 2.4 * rel,
      fill: PHASE_COLOR[p.p], opacity: (0.12 + 0.72 * rel).toFixed(3) }, svg);
    c.dataset.i = hist.indexOf(p);
  });

  const cur = pts[pts.length - 1] || hist[hist.length - 1];
  const rx = Math.abs(S.x(D.current.sigma_g) - S.x(0));
  const ry = Math.abs(S.y(D.current.sigma_i) - S.y(0));
  el("ellipse", { cx: S.x(cur.g), cy: S.y(cur.i), rx: rx * 1.96, ry: ry * 1.96,
    fill: PHASE_COLOR[cur.p], opacity: 0.10, stroke: PHASE_COLOR[cur.p], "stroke-width": 1,
    "stroke-dasharray": "3 3", "stroke-opacity": 0.55 }, svg);
  el("circle", { cx: S.x(cur.g), cy: S.y(cur.i), r: 8, fill: "none",
    stroke: PHASE_COLOR[cur.p], "stroke-width": 1.4, opacity: 0.6 }, svg);
  el("circle", { cx: S.x(cur.g), cy: S.y(cur.i), r: 4.2, fill: PHASE_COLOR[cur.p] }, svg);

  /* La etiqueta de fecha se ancla al lado que deje más margen dentro del lienzo. */
  const nearRight = S.x(cur.g) > w - 130;
  txt("text", { x: S.x(cur.g) + (nearRight ? -12 : 12), y: S.y(cur.i) - 11, fill: INK,
    "text-anchor": nearRight ? "end" : "start",
    "font-family": "IBM Plex Mono, monospace", "font-size": 11.5, "font-weight": 600 }, label(cur.d), svg);

  svg.onmousemove = (ev) => planeHover(ev, S);
  svg.onmouseleave = () => { $("#planeTip").hidden = true; };
}

function planeHover(ev, S) {
  const svg = $("#plane");
  const r = svg.getBoundingClientRect();
  const sx = (ev.clientX - r.left) * (PLANE.w / r.width);
  const sy = (ev.clientY - r.top) * (PLANE.h / r.height);
  const hist = D.history;
  let best = null, bd = 1e9;
  const from = Math.max(0, hist.length - trail);
  for (let k = from; k < hist.length; k++) {
    const dx = S.x(hist[k].g) - sx, dy = S.y(hist[k].i) - sy;
    const d = dx * dx + dy * dy;
    if (d < bd) { bd = d; best = hist[k]; }
  }
  const tip = $("#planeTip");
  if (!best || bd > 700) { tip.hidden = true; return; }
  tip.hidden = false;
  tip.innerHTML = `<b>${label(best.d)}</b><br>${best.p}<br>crecimiento ${signed(best.g, 2)}σ · inflación ${signed(best.i, 2)}σ`;
  const px = (S.x(best.g) / PLANE.w) * r.width;
  const py = (S.y(best.i) / PLANE.h) * r.height;
  tip.style.left = `${Math.min(r.width - 160, Math.max(0, px + 12))}px`;
  tip.style.top = `${Math.max(0, py - 56)}px`;
}

/* ------------------------------ indicadores ----------------------------- */
function renderIndicators() {
  const host = $("#indicators");
  host.innerHTML = "";
  for (const block of ["growth", "inflation", "leading", "standalone"]) {
    const rows = D.indicators.filter(i => i.block === block);
    if (!rows.length) continue;
    rows.sort((a, b) => Math.abs(b.z) - Math.abs(a.z));
    const pc = D.pca?.[block];
    const box = document.createElement("div");
    box.className = "ind-block";
    box.innerHTML = `
      <header>
        <h3>${BLOCK_TITLE[block]}</h3>
        <div class="pc">${rows.length} series${pc ? `<br>1er componente: ${fmtPct(pc.explained_var, 0)} de la varianza` : "<br>no entran en ningún factor"}</div>
      </header>
      ${rows.map(indRow).join("")}`;
    host.appendChild(box);
  }
}

function indRow(i) {
  const scale = 3;
  const pctW = Math.min(50, Math.abs(i.z) / scale * 50);
  const pos = i.z >= 0;
  const col = i.block === "inflation"
    ? (pos ? PHASE_COLOR["Sobrecalentamiento"] : PHASE_COLOR["Reflación"])
    : (pos ? POS : NEG);
  const style = pos ? `left:50%;width:${pctW}%;background:${col}` : `right:50%;width:${pctW}%;background:${col}`;
  const delta = i.z_prev != null ? i.z - i.z_prev : null;
  const arrow = delta == null ? "" : (delta > 0.15 ? "▲" : delta < -0.15 ? "▼" : "▬");
  const tip = [i.note, `retraso de publicación: ${i.lag_m} ${i.lag_m === 1 ? "mes" : "meses"} — el dato de un mes concreto no entra en la clasificación hasta que de verdad se publicó, no en tiempo real`,
    i.invert ? "signo invertido: sube el indicador cuando la serie original baja, para que todo el bloque lea en la misma dirección" : null,
    i.loading != null ? `peso ${fmtNum(i.loading, 2)}: su carga dentro del primer componente principal del bloque — cuánto arrastra al índice conjunto cuando esta serie se mueve, no una importancia fijada a mano` : null,
  ].filter(Boolean).join(" · ");
  return `
    <div class="ind-row" title="${tip}">
      <div class="nm">${i.name}
        <small>${i.id} · retraso ${i.lag_m}m${i.invert ? " · invertida" : ""}${
          i.loading != null ? ` · peso ${fmtNum(i.loading, 2)}` : ""}</small>
      </div>
      <div class="zbar"><span class="axis"></span><i style="${style}"></i></div>
      <div class="zval" style="color:${col}">${signed(i.z, 2)} <span style="color:${INK_FAINT};font-size:9.5px">${arrow}</span></div>
    </div>`;
}

/* -------------------------------- timeline ------------------------------ */
function renderTimeline() {
  const svg = $("#timeline");
  svg.innerHTML = "";
  const W = 1200, H = 300, padL = 42, padR = 12, padT = 10;
  const hist = D.history;
  const stripH = 24;
  const chartTop = padT + stripH + 16;
  const chartH = H - chartTop - 34;
  const x = k => padL + (k / (hist.length - 1)) * (W - padL - padR);
  const vmax = Math.max(2.5, ...hist.map(p => Math.max(Math.abs(p.g), Math.abs(p.i))));
  const y = v => chartTop + chartH / 2 - (v / vmax) * (chartH / 2);

  $("#histFrom").textContent = label(hist[0].d);

  const idxOf = {};
  hist.forEach((p, k) => { idxOf[p.d] = k; });
  (D.nber || []).forEach(([a, b]) => {
    const ia = idxOf[a], ib = idxOf[b];
    if (ia == null || ib == null) return;
    el("rect", { x: x(ia), y: padT, width: Math.max(1, x(ib) - x(ia)), height: H - padT - 30,
      fill: INK, opacity: 0.07 }, svg);
  });

  let runStart = 0;
  for (let k = 1; k <= hist.length; k++) {
    if (k === hist.length || hist[k].p !== hist[runStart].p) {
      el("rect", { x: x(runStart), y: padT, width: Math.max(1, x(k - 1) - x(runStart) + 1),
        height: stripH, fill: PHASE_COLOR[hist[runStart].p], opacity: 0.9 }, svg);
      runStart = k;
    }
  }

  [-2, -1, 0, 1, 2].forEach(v => {
    if (Math.abs(v) > vmax) return;
    el("line", { x1: padL, y1: y(v), x2: W - padR, y2: y(v),
      stroke: v === 0 ? LINE_STRONG : LINE_SOFT, "stroke-width": 1 }, svg);
    txt("text", { x: padL - 8, y: y(v) + 4, fill: INK_FAINT, "text-anchor": "end",
      "font-family": "IBM Plex Mono, monospace", "font-size": 10 }, `${v > 0 ? "+" : ""}${v}σ`, svg);
  });

  const line = (key, color) => {
    const d = hist.map((p, k) => `${k ? "L" : "M"}${x(k).toFixed(1)},${y(p[key]).toFixed(1)}`).join("");
    el("path", { d, fill: "none", stroke: color, "stroke-width": 1.4, opacity: 0.95 }, svg);
  };
  line("i", PHASE_COLOR["Sobrecalentamiento"]);
  line("g", PHASE_COLOR["Reflación"]);

  const years = {};
  hist.forEach((p, k) => { const yy = p.d.slice(0, 4); if (!(yy in years)) years[yy] = k; });
  const keys = Object.keys(years);
  const step = Math.ceil(keys.length / 14);
  keys.forEach((yy, n) => {
    if (n % step) return;
    txt("text", { x: x(years[yy]), y: H - 12, fill: INK_FAINT, "text-anchor": "middle",
      "font-family": "IBM Plex Mono, monospace", "font-size": 10 }, yy, svg);
  });

  const lg = [["Crecimiento", PHASE_COLOR["Reflación"]], ["Inflación", PHASE_COLOR["Sobrecalentamiento"]], ["Recesión NBER", INK]];
  lg.forEach(([t, col], n) => {
    el("rect", { x: padL + n * 150, y: H - 26, width: 10, height: 3, fill: col, opacity: .9 }, svg);
    txt("text", { x: padL + n * 150 + 16, y: H - 22, fill: INK_SOFT,
      "font-family": "IBM Plex Mono, monospace", "font-size": 10 }, t, svg);
  });

  svg.onmousemove = (ev) => {
    const r = svg.getBoundingClientRect();
    const sx = (ev.clientX - r.left) * (W / r.width);
    const k = Math.round(((sx - padL) / (W - padL - padR)) * (hist.length - 1));
    const p = hist[Math.max(0, Math.min(hist.length - 1, k))];
    const tip = $("#tlTip");
    tip.hidden = false;
    tip.innerHTML = `<b>${label(p.d)}</b><br>${p.p}<br>crecimiento ${signed(p.g, 2)}σ · inflación ${signed(p.i, 2)}σ`;
    tip.style.left = `${Math.min(r.width - 190, (ev.clientX - r.left) + 12)}px`;
    tip.style.top = `10px`;
  };
  svg.onmouseleave = () => { $("#tlTip").hidden = true; };
}

/* --------------------------- matriz de activos -------------------------- */
function classes() {
  return ["Todo", ...Array.from(new Set(D.assets.map(a => a.class)))];
}

function renderMatrix() {
  const seg = $("#classFilter");
  seg.innerHTML = classes().map(c =>
    `<button type="button" data-c="${c}" aria-pressed="${c === activeClass}">${c}</button>`).join("");
  seg.querySelectorAll("button").forEach(b => {
    b.onclick = () => { activeClass = b.dataset.c; renderMatrix(); };
  });
  $("#onlySig").checked = onlySig;
  $("#onlySig").onchange = (e) => { onlySig = e.target.checked; drawMatrix(); };
  drawMatrix();
}

function drawMatrix() {
  const cur = D.current.phase;
  let rows = D.assets.filter(a => activeClass === "Todo" || a.class === activeClass);
  rows = rows.filter(a => !onlySig || D.phases.some(p => {
    const g = a.phases[p]?.grade;
    return g && g !== "0" && g !== "s/d";
  }));
  rows.sort((a, b) => (b.phases[cur]?.rel ?? -99) - (a.phases[cur]?.rel ?? -99));

  const head = `<thead><tr>
      <th>Activo</th>
      ${D.phases.map(p => `<th class="ph ${p === cur ? "active" : ""}" style="color:${p === cur ? PHASE_COLOR[p] : ""}">
        ${p}<span>${p === cur ? "fase vigente" : " "}</span></th>`).join("")}
      <th style="text-align:right">Media</th>
    </tr></thead>`;

  const groups = {};
  rows.forEach(a => { (groups[a.class] ||= []).push(a); });

  let body = "";
  for (const [cls, items] of Object.entries(groups)) {
    body += `<tr class="grp"><td colspan="${D.phases.length + 2}">${cls}</td></tr>`;
    for (const a of items) {
      const chips = tickerChips(a.name);
      body += `<tr><td class="asset">${a.name}${chips ? `<span class="tickers">${chips}</span>` : ""}<small>${a.source} · desde ${a.from.slice(0, 7)} · ${a.n} meses</small></td>`;
      for (const p of D.phases) {
        const d = a.phases[p] || {};
        if (d.grade == null || d.grade === "s/d") {
          body += `<td class="cell dim">—</td>`;
          continue;
        }
        const sig = d.grade !== "0";
        const col = sig ? diverging(d.rel, 12) : "transparent";
        const txtCol = d.rel >= 0 ? POS : NEG;
        const tCell = [
          `rentabilidad anualizada en ${p}: ${fmtNum(d.ann, 1)}%`,
          `exceso sobre su propia media de siempre: ${signed(d.rel, 1)} puntos`,
          d.rel_shrunk != null ? `contraído hacia cero: ${signed(d.rel_shrunk, 1)} pp — versión más prudente del exceso, encogida en proporción a lo poco fiable que es la muestra (pocos meses o mucho vaivén encogen más), para no dejarse impresionar por una racha corta` : null,
          `t=${fmtNum(d.t, 2)}: el exceso dividido por su propio margen de error — por debajo de ±2 aproximadamente, no se puede descartar que sea puro azar`,
          d.q != null ? `q=${fmtNum(d.q, 3)}: la probabilidad de que esta casilla en concreto sea un falso positivo, YA corregida por examinar decenas de casillas a la vez (sin esa corrección, el p-valor sin ajustar sería menor y parecería más fiable de lo que es)` : null,
          `${d.n} meses de esta fase en la muestra · acertó signo (subió cuando "suele subir") el ${fmtPct(d.hit, 0)} de esos meses`,
        ].filter(Boolean).join(" · ");
        body += `<td class="cell ${p === cur ? "active" : ""} ${sig ? "" : "dim"}"
            style="background:${col}"
            title="${tCell}">
            <span class="g" style="color:${sig ? txtCol : INK_FAINT}">${d.grade}</span>
            <span class="r">${signed(d.rel, 1)}</span></td>`;
      }
      body += `<td style="text-align:right;font-family:var(--mono);color:${INK_SOFT}">${fmtNum(a.uncond_ann, 1)}%</td></tr>`;
    }
  }

  $("#matrix").innerHTML = head + `<tbody>${body}</tbody>`;
  $("#matrixFoot").innerHTML = `
    Cada celda: exceso anualizado en puntos porcentuales frente a la media histórica del propio activo,
    y la nota que resume su significatividad. Pasa el cursor por encima para ver el detalle completo
    (t, q, meses y tasa de acierto).<br>
    <b>+++ / ---</b> la probabilidad de que este resultado sea puro azar (el "p-valor") es menor al 1%,
    y sigue siéndolo incluso después de corregir por examinar decenas de casillas a la vez ("FDR ≤ 0,10":
    de las casillas marcadas así, como mucho un 10% de media serían falsos positivos, no cada una
    individualmente) &nbsp;·&nbsp; <b>++ / --</b> probabilidad de azar menor al 5%, sin esa corrección
    adicional &nbsp;·&nbsp; <b>+ / -</b> menor al 20% — indicativo, no concluyente &nbsp;·&nbsp;
    <b>0</b> no se puede distinguir de su propia media, con la muestra disponible hoy — no significa que
    "no haya efecto", significa que con estos datos no se puede afirmar que lo haya.`;
}

/* -------------------------------- consenso ------------------------------ */
function renderConsensus() {
  const host = $("#consensusBlock");
  const T = CLOCK_TXT[clockMode];
  const c = D.current;
  const list = activeConsensus();
  if (c.confidence >= 0.6 || !list.length) {
    host.innerHTML = `
      <div class="wrap">
        <div class="section-head">
          <div class="eyebrow">Solapamiento · ${T.label}</div>
          <h2>Cartera de consenso</h2>
          <p class="cap">${c.confidence >= 0.6
            ? `La clasificación tiene ${fmtPct(c.confidence)} de margen: no hace falta cubrirse contra la fase alternativa. La columna de ${c.phase} de la matriz es suficiente.`
            : `No hay ningún ${T.consensusEmptyWord} con nota positiva y contrastada a la vez en ${c.phase} y en ${c.alt_phase}. Eso no cambia la cartera de «Qué comprar ahora» — sigue siendo la mejor estimación con los datos de hoy — solo significa que, en este caso, no hay ningún activo que además sirva de colchón si la fase resultara ser la otra candidata.`}</p>
        </div>
      </div>`;
    return;
  }
  host.innerHTML = `
    <div class="wrap">
      <div class="section-head">
        <div class="eyebrow">Solapamiento · ${T.label}</div>
        <h2>Lo que funciona en las dos fases candidatas</h2>
        <p class="cap">Con ${fmtPct(c.confidence)} de margen entre <b>${c.phase}</b> y <b>${c.alt_phase}</b>,
        estos activos tienen exceso positivo y contrastado en ambas: sobreviven a equivocarse de cuadrante.</p>
      </div>
      <div class="cons-grid">
        ${list.map(r => `
          <div class="cons-card">
            <span class="cls">${r.class}</span>
            <h4>${r.name}${tickerChips(r.name) ? `<span class="tickers">${tickerChips(r.name)}</span>` : ""}</h4>
            <div class="pair">
              <div><span>${c.phase.slice(0, 12)}</span>${r.g1} · ${signed(r.r1, 1)} pp</div>
              <div><span>${c.alt_phase.slice(0, 12)}</span>${r.g2} · ${signed(r.r2, 1)} pp</div>
            </div>
          </div>`).join("")}
      </div>
    </div>`;
}

/* ------------------------ robustez de las notas ------------------------- */
function renderRobustness() {
  const st = D.asset_stats || {};
  const cur = D.current.phase;
  const strong = D.assets
    .map(a => ({ a, d: a.phases[cur] || {} }))
    .filter(x => x.d.q != null && x.d.q <= 0.10)
    .sort((x, y) => (y.d.rel ?? 0) - (x.d.rel ?? 0));
  const share = st.cells ? st.fdr_survivors / st.cells : 0;
  const ok = share >= 0.08 && strong.length > 0;

  $("#robustBlock").innerHTML = `
    <div class="wrap">
      <div class="section-head">
        <div class="eyebrow">Lo que aguanta</div>
        <h2>El filtro más estricto: control de falsos descubrimientos</h2>
        <p class="cap">De ${st.cells ?? "—"} casillas contrastadas, <b>${st.graded ?? "—"}</b> tienen nota
          y solo <b>${st.fdr_survivors ?? "—"}</b> sobreviven al control de falsos descubrimientos.
          Con cientos de pruebas simultáneas, unas cuantas "señales" salen por azar puro: solo estas
          últimas son defendibles con ese rigor.</p>
      </div>
      ${ok ? `
        <div class="cons-grid">
          ${strong.slice(0, 8).map(x => `
            <div class="cons-card" style="border-top:2px solid ${x.d.rel >= 0 ? POS : NEG}">
              <span class="cls">${x.a.class}</span>
              <h4>${x.a.name}${tickerChips(x.a.name) ? `<span class="tickers">${tickerChips(x.a.name)}</span>` : ""}</h4>
              <div class="pair">
                <div><span>exceso</span>${signed(x.d.rel, 1)} pp${
                  x.d.rel_shrunk != null ? ` <span style="color:${INK_FAINT}">(${signed(x.d.rel_shrunk, 1)} contraído)</span>` : ""}</div>
                <div><span>t · q</span>${fmtNum(x.d.t, 1)} · ${fmtNum(x.d.q, 3)}</div>
              </div>
            </div>`).join("")}
        </div>
        <p class="foot">Estas son las posiciones con base empírica más sólida en ${cur}. El resto de la
          matriz de arriba es informativo, no accionable con este nivel de exigencia.</p>`
        : `<div class="errbox" style="border-color:${PHASE_COLOR["Sobrecalentamiento"]};background:rgba(184,134,59,.07)">
            <h2>Ninguna posición aguanta este nivel de exigencia</h2>
            <p>En ${cur}, ningún activo del universo tiene un exceso sobre su propia media que sobreviva
            al control de falsos descubrimientos. Eso no es un fallo del panel: es el resultado honesto.</p>
            <p style="margin-top:10px">Lo prudente entonces es no rotar de forma agresiva por fase. La
            cartera estratégica, la diversificación y el coste pesan más que el cuadrante aquí. El reloj
            sigue sirviendo para saber dónde está el ciclo y para el modelo de recesión.</p>
          </div>`}
    </div>`;
}

/* ---------------------- subsectores (complementario) --------------------- */
// Análisis aparte, por debajo del principal: NUNCA cambia qué sector se compra ni
// en qué peso — eso lo decide solo `rotation()`/`_sleeve_pick` en build_data.py.
// Esto solo mira, para los sectores YA elegidos en la fase, qué subsector (de los
// que caen limpios en un único sector por código SIC, ver METODOLOGIA.md) pagó más.

// Ejemplos de empresas reales bajo cada subsector: NO es una lista escrita de
// memoria. Son las posiciones reales y actuales (nombre, ticker, peso) del propio
// SPDR/State Street sectorial que ya aparece en ETF_MAP — ver holdings.meta.source
// y fetch_holdings() en build_data.py. Nunca cambian ningún número de la cartera.
function holdingsExamples(list) {
  if (!list || !list.length) return "";
  return list.slice(0, 3)
    .map(h => `${h.name} <span class="small-cap">${h.ticker}</span> ${fmtNum(h.weight, 1)}%`)
    .join(" · ");
}

// Una fila con el mismo aspecto en los dos tipos de tarjeta: nombre a la izquierda
// (con una insignia opcional), un número a la derecha en mono. Evita que las dos
// variantes de subsectorHTML (con rentabilidad por fase, o solo con peso real en
// el fondo) se vean como cosas distintas.
function metricRow({ label, badge, caption, value, valueColor, title }) {
  return `<div style="display:flex;justify-content:space-between;align-items:baseline;gap:10px;padding:6px 0;border-bottom:1px solid var(--line-soft);font-size:12.5px"
      title="${title}">
    <span style="min-width:0">${label}${badge || ""}${caption ? `<small class="small-cap" style="display:block;margin-top:1px">${caption}</small>` : ""}</span>
    <b style="font-family:var(--mono);white-space:nowrap;color:${valueColor}">${value}</b>
  </div>`;
}

function subsectorHTML(S, phase) {
  const sub = D.subsectors;
  const hold = D.holdings;
  if (!sub || !sub.por_sector) return "";
  const asOf = hold?.meta?.as_of;
  const rows = (S.playbook[phase] || []).filter(x => x.sleeve === "Renta variable");
  const cards = rows.map(x => {
    const items = sub.por_sector[x.name]?.[phase];
    const secAnn = D.assets.find(a => a.name === x.name)?.phases?.[phase]?.ann;
    if (!items || !items.length) {
      // Sin historia propia que desglosar por fase: en vez de un texto explicando
      // por qué, se enseña lo que sí hay, con el mismo aspecto que las filas de
      // abajo. Primero se intentan los grupos deducidos de la composición real del
      // ETF (Comunicaciones/Utilities/Materiales); si no hay grupos para este
      // sector, se cae a la lista plana de posiciones reales.
      const grupos = hold?.grupos?.[x.name];
      if (grupos && grupos.length) {
        return `<div class="cons-card">
          <span class="cls">${x.name}${secAnn != null ? ` · en conjunto ${fmtNum(secAnn, 1)}%` : ""}</span>
          ${grupos.map(g => metricRow({
            label: g.grupo,
            caption: holdingsExamples(g.empresas),
            value: `${fmtNum(g.peso, 1)}%`,
            valueColor: "var(--ink-soft)",
            title: `peso agregado real de hoy en el fondo que replica ${x.name}${asOf ? `, a ${asOf}` : ""}`,
          })).join("")}
          <p class="foot" style="margin-top:8px;margin-bottom:0">Peso real de hoy por línea de
            negocio dentro del fondo que replica este sector — no hay historia propia para
            desglosarlo por fase como al resto, así que se enseña la composición actual en su
            lugar.</p>
        </div>`;
      }
      const secHold = hold?.por_sector?.[x.name] || [];
      if (!secHold.length) return null;
      // Semiconductores no tiene fondo propio fiable (ver METODOLOGIA.md): sus
      // posiciones vienen del propio ETF de Tecnología, que es donde estas
      // empresas pesan de verdad — el pie lo deja claro para no dar a entender
      // que existe un fondo de semiconductores detrás de este número.
      const esSemis = x.name === "Semiconductores";
      return `<div class="cons-card">
        <span class="cls">${x.name}${secAnn != null ? ` · en conjunto ${fmtNum(secAnn, 1)}%` : ""}</span>
        ${secHold.map(h => metricRow({
          label: `${h.name} <span class="small-cap">${h.ticker}</span>`,
          value: `${fmtNum(h.weight, 1)}%`,
          valueColor: "var(--ink-soft)",
          title: `peso real ${esSemis ? "en el ETF de Tecnología (XLK)" : `en el fondo que replica ${x.name}`}${asOf ? `, a ${asOf}` : ""}`,
        })).join("")}
        <p class="foot" style="margin-top:8px;margin-bottom:0">${esSemis
          ? "Peso real de hoy dentro del ETF de Tecnología (XLK): no hay un fondo de semiconductores fiable que refleje el peso real de mercado de estas empresas, así que se muestra su peso dentro de Tecnología, filtrado a las que por actividad son fabricantes de semiconductores."
          : "Peso real de hoy en el fondo que replica este sector — no hay suficiente historia propia para desglosarlo por fase como al resto, así que se enseña la composición actual en su lugar."}</p>
      </div>`;
    }
    const best = items[0];
    const delta = (secAnn != null && best.ann != null) ? best.ann - secAnn : null;
    return `<div class="cons-card">
      <span class="cls">${x.name}${secAnn != null ? ` · en conjunto ${fmtNum(secAnn, 1)}%` : ""}</span>
      ${items.map(it => {
        const col = it.ann < 0 ? NEG : (secAnn != null && it.ann >= secAnn ? POS : "var(--ink-soft)");
        const sig = it.grade && it.grade !== "0" && it.grade !== "s/d";
        const examples = holdingsExamples(hold?.por_subsector?.[it.name]);
        return metricRow({
          label: it.name,
          badge: sig ? ` <span class="small-cap" style="color:${it.ann >= 0 ? POS : NEG}">${it.grade}</span>` : "",
          caption: examples,
          value: `${fmtNum(it.ann, 1)}%`,
          valueColor: col,
          title: `anualizado ${fmtNum(it.ann, 1)}% · exceso ${signed(it.rel, 1)} pp${it.rel_shrunk != null ? ` (contraído ${signed(it.rel_shrunk, 1)})` : ""} · ${it.n} meses`,
        });
      }).join("")}
      ${delta != null ? `<p class="foot" style="margin-top:8px;margin-bottom:0">
        Si en <b>${phase}</b> solo se hubiera comprado <b>${best.name}</b> en vez de todo
        ${x.name}, la diferencia habría sido de
        <b style="color:${delta >= 0 ? POS : NEG}">${signed(delta, 1)} pp</b> —
        con los datos ya vistos, nunca una predicción de lo que hará el próximo.</p>` : ""}
    </div>`;
  }).filter(Boolean);
  if (!cards.length) return "";
  return `
    <h3 style="font-family:var(--serif);font-size:17px;margin:32px 0 4px">Un paso más: qué subsector lo hizo mejor</h3>
    <p class="cap" style="margin-bottom:14px">Análisis <b>complementario</b>: nunca cambia la cartera de
      arriba, que sigue decidida por sector completo. Dentro de cada sector YA elegido en <b>${phase}</b>,
      mira qué línea de negocio pagó más y cuál menos — con historia suficiente para medirlo por fase en
      la mayoría de sectores; donde no la hay, se enseñan en su lugar las mayores posiciones reales de hoy
      del fondo que replica ese sector. Bajo cada nombre, un par de empresas reales y actuales (nombre,
      ticker y peso) — nunca una lista elegida de memoria, ver METODOLOGIA.md.</p>
    <div class="cons-grid" style="margin-bottom:8px">${cards.join("")}</div>`;
}

/* ------------------------------ backtest --------------------------------- */
let pbPhase = null;
let scheme = null;
let curveRange = "max";

function renderRotation() {
  const T = CLOCK_TXT[clockMode];
  const r = activeRotation();
  if (!r.schemes) {
    $("#rotationBlock").innerHTML = `
      <div class="section-head">
        <div class="eyebrow">El backtest · ${T.label}</div>
        <h2>La cartera, fase a fase</h2>
      </div>
      <div class="errbox" style="border-color:${PHASE_COLOR["Sobrecalentamiento"]};background:rgba(184,134,59,.07)">
        <h2>Los datos son de una versión anterior</h2>
        <p>Este panel espera los cuatro esquemas de reparto y el <code>data.json</code> publicado
        ${r.portfolio ? "trae solo uno" : `no trae la sección de asignación de ${T.label.toLowerCase()}`}. Sube el
        <code>scripts/build_data.py</code> actual y vuelve a lanzar <b>Actualizar datos</b> en Actions.</p>
      </div>`;
    return;
  }
  scheme = scheme || r.default || Object.keys(r.schemes)[0];
  pbPhase = pbPhase || D.current.phase;
  const S = r.schemes[scheme];
  const mkt = r.bench_100eq || {};
  const b6040 = r.bench_6040 || {};
  const p = S.portfolio;
  const beatsMkt = p.cagr != null && mkt.cagr != null && p.cagr > mkt.cagr;
  const mainSleeve = Object.keys(r.bands || {})[0];
  const [cLo, cHi] = r.counts?.[mainSleeve] || [];

  const statRow = (name, s, extra, active) => `
    <tr style="${active ? "background:rgba(169,117,44,.07)" : ""}">
      <td class="asset" style="${active ? "color:var(--ink);font-weight:600" : ""}">${name}</td>
      <td style="text-align:right;font-family:var(--mono)">${fmtNum(s.cagr, 1)}%</td>
      <td style="text-align:right;font-family:var(--mono)">${fmtNum(s.vol, 1)}%</td>
      <td style="text-align:right;font-family:var(--mono);font-weight:600;color:${
        s.sharpe > (mkt.sharpe ?? 0) ? POS : "var(--ink-soft)"}">${fmtNum(s.sharpe, 2)}</td>
      <td style="text-align:right;font-family:var(--mono)">${fmtNum(s.maxdd, 1)}%</td>
      <td style="text-align:right;font-family:var(--mono)">${fmtNum(s.worst12, 1)}%</td>
      <td style="text-align:right;font-family:var(--mono);color:var(--ink-soft)">${extra}</td>
    </tr>`;

  $("#rotationBlock").innerHTML = `
    <div class="section-head">
      <div class="eyebrow">El backtest · ${T.label}</div>
      <h2>${T.title} Fase a fase, desde ${(p.from || "").slice(0, 4) || "—"}</h2>
      <p class="cap">${T.intro}</p>
      <p class="cap" style="margin-top:8px">Todos los números de esta sección son <b>exceso sobre
        letras del Tesoro a 3 meses</b>, no el retorno total del índice — es la convención estándar
        para que el Sharpe signifique lo que dice significar. ${T.benchShort} en términos brutos ha
        rentado más que la cifra de abajo, aproximadamente el tipo de interés sin riesgo del
        periodo; la comparación entre cartera y mercado es igual de válida porque a los dos se les
        resta lo mismo. "Anual" es siempre <b>CAGR</b> (tasa de crecimiento anual compuesto): la
        rentabilidad anual constante que, capitalizada mes a mes durante todo el periodo, habría dado
        el mismo resultado final — no la media aritmética de los años sueltos, que sobreestima el
        resultado real de una serie con altibajos.</p>
    </div>

    <div class="outlook" style="margin-bottom:24px;border-color:${beatsMkt ? POS : PHASE_COLOR["Sobrecalentamiento"]}">
      <div class="item"><dt>Cartera de rotación</dt><dd style="color:${beatsMkt ? POS : "var(--ink)"}">${fmtNum(p.cagr, 1)}% anual*</dd>
        <small>Sharpe ${fmtNum(p.sharpe, 2)} · caída máxima ${fmtNum(p.maxdd, 1)}%</small></div>
      <div class="item"><dt>${T.benchDt}</dt><dd>${fmtNum(mkt.cagr, 1)}% anual*</dd>
        <small>Sharpe ${fmtNum(mkt.sharpe, 2)} · caída máxima ${fmtNum(mkt.maxdd, 1)}%</small></div>
      <div class="item"><dt>Diferencia</dt><dd style="color:${beatsMkt ? POS : NEG}">${signed((p.cagr ?? 0) - (mkt.cagr ?? 0), 1)} pp/año</dd>
        <small>${beatsMkt ? "la rotación por fase bate al índice en rentabilidad, no solo en riesgo" : "el índice bate a la rotación en rentabilidad; mira el Sharpe y la caída máxima antes de descartarla"}</small></div>
      <div class="item" title="Fórmula: rentabilidad anualizada dividida entre la volatilidad anualizada. Compara dos series con distinto nivel de riesgo en términos justos: 8% de rentabilidad con la mitad de vaivén que otra que también da 8% es, en Sharpe, el doble de buena. Por encima de 1 se considera sólido para una cartera de solo renta variable; por debajo de 0,5, flojo."><dt>Sharpe</dt><dd style="color:${(p.sharpe ?? 0) > (mkt.sharpe ?? 0) ? POS : "var(--ink)"}">${fmtNum(p.sharpe, 2)} vs ${fmtNum(mkt.sharpe, 2)}</dd>
        <small>rentabilidad por unidad de riesgo asumido — más alto es mejor</small></div>
    </div>
    <p class="foot" style="margin-top:-14px;margin-bottom:20px">* Exceso anualizado sobre letras del Tesoro a 3 meses (ver nota arriba), no CAGR del índice en bruto. "Caída máxima" (maxDD): la mayor pérdida que habría sufrido quien entró justo en el peor pico y vendió justo en el peor valle posterior — el susto más grande que ha dado la estrategia en todo el periodo, no una pérdida típica.</p>

    <h3 style="font-family:var(--serif);font-size:17px;margin-bottom:4px">¿Y si el reparto interno cambia?</h3>
    <p class="cap" style="margin-bottom:14px">La selección ${T.selectionWord} es idéntica en los cuatro
      esquemas — cuáles entran y con qué banda de peso lo decide solo la fase, sección de arriba. Lo único
      que cambia es cómo se reparte el dinero <i>entre</i> los ya elegidos, y ahí hay más de una forma
      razonable de hacerlo:</p>
    <ul class="cap" style="margin:0 0 14px 18px;padding:0">
      <li><b>Equiponderado</b>: mismo peso para todos los ${T.assetWordPl} elegidos (${cHi
          ? `si son ${cHi}, ${fmtNum(100 / cHi, 0)}% cada uno`
          : "si son 4, 25% cada uno"}) — no
        apuesta por ninguno en particular dentro del grupo.</li>
      <li><b>Inverso de la volatilidad</b>: más peso al ${T.assetWord} que se mueve con menos vaivén, menos al más
        errático — para que ningún ${T.assetWord} por sí solo acapare el riesgo de la cartera.</li>
      <li><b>Por puesto</b>: más peso al que mejor puntuó en la fase, menos al último de los elegidos —
        apuesta explícita por el orden del ranking, no solo por estar dentro de él.</li>
      <li><b>Mitad y mitad</b>: promedio de equiponderado e inverso de la volatilidad.</li>
    </ul>
    <div class="seg" id="schemeSeg" style="margin-bottom:18px">
      ${Object.entries(r.schemes).map(([k, v]) => `<button type="button" data-s="${k}"
        aria-pressed="${k === scheme}">${v.label}</button>`).join("")}
    </div>

    <div class="matrix-holder" style="margin-bottom:14px">
      <table class="matrix">
        <thead><tr>
          <th>Esquema de reparto</th>
          <th style="text-align:right" title="CAGR: rentabilidad anual compuesta, exceso sobre letras del Tesoro a 3 meses">Anual*</th>
          <th style="text-align:right" title="Volatilidad anualizada: la desviación estándar de los retornos mensuales, llevada a escala de un año — cuanto mayor, más se mueve el valor de la cartera mes a mes">Vol</th>
          <th style="text-align:right" title="Rentabilidad anual dividida entre volatilidad anualizada: rentabilidad por unidad de riesgo asumido">Sharpe</th>
          <th style="text-align:right" title="Caída máxima (maxDD): la mayor pérdida de pico a valle en todo el periodo, no una pérdida típica">Caída máx.</th>
          <th style="text-align:right" title="El peor resultado de cualquier ventana de 12 meses consecutivos del periodo (no necesariamente un año natural: puede empezar en marzo y terminar en febrero) — más informativo que el peor año del calendario porque no depende de dónde caigan las fronteras de enero a diciembre">Peor 12 m.</th>
          <th style="text-align:right" title="En cuántos de los años naturales del periodo la cartera terminó por delante de ${T.benchShort}, sobre el total de años con datos completos">Años ganados</th>
        </tr></thead>
        <tbody>
          ${Object.entries(r.schemes).map(([k, v]) =>
            statRow(v.label, v.portfolio, `${v.wins_years}/${v.n_years}`, k === scheme)).join("")}
          <tr style="border-top:2px solid var(--line-strong)"><td class="asset" style="font-weight:600">${T.benchLabel}</td>
            <td style="text-align:right;font-family:var(--mono);font-weight:600">${fmtNum(mkt.cagr, 1)}%</td>
            <td style="text-align:right;font-family:var(--mono)">${fmtNum(mkt.vol, 1)}%</td>
            <td style="text-align:right;font-family:var(--mono);font-weight:600">${fmtNum(mkt.sharpe, 2)}</td>
            <td style="text-align:right;font-family:var(--mono)">${fmtNum(mkt.maxdd, 1)}%</td>
            <td style="text-align:right;font-family:var(--mono)">${fmtNum(mkt.worst12, 1)}%</td>
            <td style="text-align:right;font-family:var(--mono);color:var(--ink-soft)">—</td></tr>
          ${T.show6040 ? `<tr><td class="asset" style="color:var(--ink-faint);font-size:12px">60/40 (referencia, sin peso en esta cartera)</td>
            <td style="text-align:right;font-family:var(--mono);color:var(--ink-faint);font-size:12px">${fmtNum(b6040.cagr, 1)}%</td>
            <td style="text-align:right;font-family:var(--mono);color:var(--ink-faint);font-size:12px">${fmtNum(b6040.vol, 1)}%</td>
            <td style="text-align:right;font-family:var(--mono);color:var(--ink-faint);font-size:12px">${fmtNum(b6040.sharpe, 2)}</td>
            <td style="text-align:right;font-family:var(--mono);color:var(--ink-faint);font-size:12px">${fmtNum(b6040.maxdd, 1)}%</td>
            <td style="text-align:right;font-family:var(--mono);color:var(--ink-faint);font-size:12px">${fmtNum(b6040.worst12, 1)}%</td>
            <td style="text-align:right;font-family:var(--mono);color:var(--ink-faint)">—</td></tr>` : ""}
        </tbody>
      </table>
    </div>
    <p class="foot" style="margin-bottom:14px">${beatsMkt && (p.sharpe ?? 0) > (mkt.sharpe ?? 0)
      ? `Sin matices: en este histórico la rotación por ${T.assetWordPl} bate a ${T.benchShort} tanto en
         rentabilidad como en Sharpe y en caída máxima, con menos volatilidad. No es "gana
         porque asume más riesgo": gana llevando <b>menos</b>.`
      : beatsMkt
        ? `Gana en rentabilidad, pero compara siempre el Sharpe antes de concluir que la selección de
           ${T.assetWordPl} aporta: parte de la ventaja puede venir simplemente de llevar más riesgo.`
        : `${T.benchShort} gana en rentabilidad en este histórico. Compara el Sharpe y la caída máxima
           antes de descartar la rotación: llevar menos riesgo con rentabilidad parecida también
           es ganar, aunque no lo parezca mirando solo el número grande.`}</p>
    ${S.vol_check ? `<p class="foot" style="margin-bottom:10px">
      Control de riesgo: la cartera terminó con <b>${fmtNum(S.vol_check.cartera, 1)}%</b> de
      volatilidad frente al <b>${fmtNum(S.vol_check.objetivo_mercado, 1)}%</b> de ${T.pureBenchWord}
      (${signed(S.vol_check.desvio, 1)} puntos) — ${T.insuranceClause}la diversificación entre varios
      ${T.assetWordPl}${cLo != null
        ? (cLo === cHi ? ` (siempre los ${cLo} con mejor ventaja de fase, nunca uno solo)`
                       : ` (entre ${cLo} y ${cHi} según la fase, nunca un número fijo)`)
        : ""}, no un objetivo impuesto.</p>` : ""}
    <p class="foot" style="margin-bottom:24px" title="Rotación = qué fracción de la cartera cambia de manos de un mes al siguiente. 20% no significa vender un quinto de las posiciones enteras: puede ser recortar un poco varias a la vez. A más rotación, más peso tienen los costes reales que este backtest no descuenta.">Rotación media de cartera: <b>${fmtNum(S.turnover, 1)}%</b>
      al mes — qué proporción del dinero cambia de sitio de un mes a otro, sea por vender del todo una
      posición o por ajustar el peso de las que se mantienen. Los costes de transacción no están
      descontados; a 15 puntos básicos (0,15%) por unidad de rotación — una estimación conservadora de
      comisión más horquilla de compraventa — restarían del orden de
      ${fmtNum(S.turnover * 0.15 * 12 / 100, 2)} puntos al año.</p>

    <div class="seg" id="curveRangeSeg" style="margin-bottom:10px">
      ${CURVE_RANGES.map(x => `<button type="button" data-r="${x.k}" aria-pressed="${x.k === curveRange}">${x.label}</button>`).join("")}
    </div>
    <div class="bt-chart" style="margin-bottom:24px">
      <svg id="rotChart" viewBox="0 0 900 340" role="img" aria-label="Evolución frente a ${T.benchShort}"></svg>
    </div>

    <h3 style="font-family:var(--serif);font-size:17px;margin-bottom:10px">Año contra año</h3>
    <div class="bt-chart" style="margin-bottom:8px">
      <svg id="annChart" viewBox="0 0 900 230" role="img" aria-label="Diferencia anual frente a ${T.benchShort}"></svg>
    </div>
    <p class="foot" style="margin-bottom:28px">Barras verdes: años en que la cartera batió a ${T.benchShort}.
      Ganó <b>${S.wins_years} de ${S.n_years}</b> años.</p>

    <h3 style="font-family:var(--serif);font-size:17px;margin-bottom:4px">Dónde gana y dónde no</h3>
    <p class="cap" style="margin-bottom:12px">Las fases con menos de 60 meses salen atenuadas: con año y
      medio o dos de datos, la diferencia es ruido y no debe leerse como que el sistema funcione mejor o
      peor ahí.</p>
    <div class="scores-grid" style="margin-bottom:28px">
      ${D.phases.filter(x => S.by_phase[x]).map(x => {
        const e = S.by_phase[x];
        const thin = e.n < 60;
        return `<div class="score-card" style="background:${PHASE_COLOR[x]};opacity:${
          thin ? .38 : (x === D.current.phase ? 1 : .68)}">
          <div class="l1">${x}</div>
          <div class="l2">${signed(e.edge, 1)} pp</div>
          <div class="l3">${e.n} meses · ${thin ? "<b>muestra insuficiente</b>" : ((e.edge ?? 0) > 0 ? "por delante del mercado" : "por detrás del mercado")}</div>
        </div>`;
      }).join("")}
    </div>

    <h3 style="font-family:var(--serif);font-size:17px;margin-bottom:10px">Manual completo: qué comprar en cada fase</h3>
    <div class="seg" id="phaseSeg" style="margin-bottom:14px">
      ${D.phases.map(x => `<button type="button" data-p="${x}" aria-pressed="${x === pbPhase}"
        style="${x === pbPhase ? `border-color:${PHASE_COLOR[x]};color:${PHASE_COLOR[x]}` : ""}">${x}</button>`).join("")}
    </div>
    ${S.sleeve_mix?.[pbPhase] ? `<div class="outlook" style="margin:0 0 16px;padding:16px 20px">
      ${Object.entries(S.sleeve_mix[pbPhase]).map(([k, v]) => `
        <div class="item"><dt>${k}</dt><dd>${fmtNum(v, 0)}%</dd>
        <small>banda ${bandTxt(r.bands?.[k])}</small></div>`).join("")}
    </div>` : ""}
    <div class="cons-grid">
      ${(() => {
        const rows = S.playbook[pbPhase] || [];
        const sleeves = [...new Set(rows.map(x => x.sleeve))];
        return sleeves.map(sl => {
          const items = rows.filter(x => x.sleeve === sl);
          const tot = items.reduce((a, x) => a + x.weight, 0);
          return `<div class="cons-card">
            <span class="cls">${sl} · ${fmtNum(tot, 0)}%</span>
            ${items.map(x => `<div style="display:flex;justify-content:space-between;align-items:baseline;gap:10px;padding:7px 0;border-bottom:1px solid var(--line-soft);font-size:13px">
              <span>${x.name}${tickerChips(x.name) ? `<span class="tickers">${tickerChips(x.name)}</span>` : ""}</span>
              <b style="font-family:var(--mono);white-space:nowrap">${fmtNum(x.weight, 1)}%</b></div>`).join("")}
          </div>`;
        }).join("");
      })()}
    </div>
    <p class="foot">Reparto <b>${S.label.toLowerCase()}</b>. Las primas largo-corto (value, tamaño,
      momentum) quedan fuera: no se compran en una cartera solo larga.
      ${pbPhase === D.current.phase ? "Esta es la fase vigente." : `La fase vigente es ${D.current.phase}.`}</p>
    ${clockMode === "eq" ? subsectorHTML(S, pbPhase) : ""}`;

  drawCurve("#rotChart", sliceCurveRange(S.curve || [], curveRange), S.label, T.curveBenchLabel);
  drawAnnual("#annChart", S.annual || {}, r.bench_annual || {}, T.curveBenchLabel);
  $("#schemeSeg").querySelectorAll("button").forEach(btn => {
    btn.onclick = () => { scheme = btn.dataset.s; renderRotation(); };
  });
  $("#phaseSeg").querySelectorAll("button").forEach(btn => {
    btn.onclick = () => { pbPhase = btn.dataset.p; renderRotation(); };
  });
  $("#curveRangeSeg").querySelectorAll("button").forEach(btn => {
    btn.onclick = () => { curveRange = btn.dataset.r; renderRotation(); };
  });
}

function drawCurve(sel, c, labelA, labelB) {
  const svg = $(sel);
  if (!svg) return;
  svg.innerHTML = "";
  // En ventanas cortas cabe la fecha completa (año-mes) bajo cada punto; en
  // el histórico completo, solo el año, como siempre. La etiqueta del último
  // punto es más ancha ("2026-08" que "2026") y queda centrada justo en el
  // borde derecho, así que ese caso necesita más margen para no recortarse.
  const shortWin = c.length <= 14;
  const W = 900, H = 340, padL = 52, padR = shortWin ? 26 : 14, padT = 14, padB = 28;
  if (!c.length) return;
  // Arranca con un vértice base en 100 (el instante justo antes del primer
  // mes mostrado): sin él, una ventana de 1-2 meses no tiene con qué trazar
  // una línea — solo un punto suelto.
  let s = 100, b = 100;
  const S = [s], B = [b];
  c.forEach(p => {
    s *= 1 + p.s / 100; S.push(s);
    if (p.b != null) { b *= 1 + p.b / 100; }
    B.push(b);
  });
  const npts = S.length;
  const lo = Math.min(...S, ...B) * 0.95, hi = Math.max(...S, ...B) * 1.05;
  const x = k => padL + (k / (npts - 1)) * (W - padL - padR);
  const y = v => H - padB - ((Math.log(v) - Math.log(lo)) / (Math.log(hi) - Math.log(lo))) * (H - padT - padB);

  [1, 2, 5, 10, 20, 50].map(m => 100 * m).filter(v => v > lo && v < hi).forEach(v => {
    el("line", { x1: padL, y1: y(v), x2: W - padR, y2: y(v), stroke: LINE_SOFT }, svg);
    txt("text", { x: padL - 8, y: y(v) + 4, fill: INK_FAINT, "text-anchor": "end",
      "font-family": "IBM Plex Mono, monospace", "font-size": 10 }, `${v / 100}×`, svg);
  });

  const path = (arr, col, wdt, op) => {
    const d = arr.map((v, k) => `${k ? "L" : "M"}${x(k).toFixed(1)},${y(v).toFixed(1)}`).join("");
    el("path", { d, fill: "none", stroke: col, "stroke-width": wdt, opacity: op }, svg);
  };
  path(B, INK_FAINT, 1.3, 0.85);
  path(S, "#3F6B52", 1.9, 1);

  const step = Math.max(1, Math.ceil(c.length / 10));
  let lastLbl = null;
  c.forEach((p, k) => {
    if (k % step) return;
    const lbl = shortWin ? p.d : p.d.slice(0, 4);
    if (lbl === lastLbl) return; // ventanas de pocos años repetían el mismo año seguido
    lastLbl = lbl;
    txt("text", { x: x(k + 1), y: H - 8, fill: INK_FAINT, "text-anchor": "middle",
      "font-family": "IBM Plex Mono, monospace", "font-size": 10 }, lbl, svg);
  });
  [[labelA, "#3F6B52"], [labelB, INK_FAINT]].forEach(([t, col], i) => {
    el("rect", { x: padL + i * 200, y: padT, width: 10, height: 3, fill: col }, svg);
    txt("text", { x: padL + i * 200 + 16, y: padT + 4, fill: INK_SOFT,
      "font-family": "IBM Plex Mono, monospace", "font-size": 10.5 }, t, svg);
  });
}

function drawAnnual(sel, ann, bench, benchLabel = "S&P 500") {
  const svg = $(sel);
  if (!svg) return;
  svg.innerHTML = "";
  const years = Object.keys(ann).map(Number).filter(y => y in bench).sort();
  if (!years.length) return;
  const W = 900, H = 230, padL = 44, padR = 10, padT = 12, padB = 30;
  const diffs = years.map(y => ann[y] - bench[y]);
  const m = Math.max(...diffs.map(Math.abs), 5);
  const x = i => padL + (i + 0.5) * ((W - padL - padR) / years.length);
  const y0 = padT + (H - padT - padB) / 2;
  const y = v => y0 - (v / m) * ((H - padT - padB) / 2);
  const bw = Math.max(2, (W - padL - padR) / years.length - 2);

  [-m, -m / 2, 0, m / 2, m].forEach(v => {
    el("line", { x1: padL, y1: y(v), x2: W - padR, y2: y(v),
      stroke: v === 0 ? LINE_STRONG : LINE_SOFT }, svg);
    txt("text", { x: padL - 7, y: y(v) + 4, fill: INK_FAINT, "text-anchor": "end",
      "font-family": "IBM Plex Mono, monospace", "font-size": 9.5 }, `${v > 0 ? "+" : ""}${v.toFixed(0)}`, svg);
  });
  years.forEach((yr, i) => {
    const d = diffs[i];
    const r = el("rect", { x: x(i) - bw / 2, y: d >= 0 ? y(d) : y0,
      width: bw, height: Math.max(1, Math.abs(y(d) - y0)),
      fill: d >= 0 ? "#3F6B52" : "#9C4A3C", opacity: 0.9 }, svg);
    txt("title", {}, `${yr}: cartera ${ann[yr].toFixed(1)}% · ${benchLabel} ${bench[yr].toFixed(1)}% · ${d >= 0 ? "+" : ""}${d.toFixed(1)} pp`, r);
    if (years.length <= 40 || i % Math.ceil(years.length / 30) === 0) {
      txt("text", { x: x(i), y: H - 10, fill: INK_FAINT, "text-anchor": "middle",
        "font-family": "IBM Plex Mono, monospace", "font-size": 8.5,
        transform: `rotate(-60 ${x(i)} ${H - 10})` }, String(yr).slice(2), svg);
    }
  });
}


/* ------------------------------ laboratorio ----------------------------- */
let labPhase = null, labSleeve = null;

function icVerdict(ic) {
  if (ic == null || Number.isNaN(ic)) return ["—", "var(--ink-soft)", "sin datos"];
  if (ic >= 0.4) return [fmtNum(ic, 2), POS, "lo que funcionó antes siguió funcionando: seleccionar por historia tiene sentido aquí"];
  if (ic >= 0.15) return [fmtNum(ic, 2), PHASE_COLOR["Sobrecalentamiento"], "persistencia débil: algo hay, pero poco donde agarrarse"];
  if (ic > -0.15) return [fmtNum(ic, 2), "var(--ink-soft)", "sin persistencia: elegir por lo que funcionó antes equivale a elegir al azar"];
  return [fmtNum(ic, 2), NEG, "persistencia negativa: lo que mejor funcionó antes tendió a funcionar peor después"];
}

function renderLab() {
  const T = CLOCK_TXT[clockMode];
  const L = activeLab();
  const phases = D.phases.filter(p => L[p] && !L[p].skipped);
  if (!phases.length) { $("#labBlock").innerHTML = ""; return; }
  labPhase = phases.includes(labPhase) ? labPhase : (phases.includes(D.current.phase) ? D.current.phase : phases[0]);
  const P = L[labPhase];
  const sleeves = Object.keys(P.sleeves || {});
  labSleeve = sleeves.includes(labSleeve) ? labSleeve : sleeves[0];
  const S = P.sleeves[labSleeve] || {};
  const noCombos = !S.n_combos;
  const [icTxt, icCol, icMsg] = icVerdict(S.rank_ic);
  const [aTxt, aCol, aMsg] = icVerdict(S.asset_ic);
  const r = activeRotation();
  const [cLo, cHi] = r.counts?.[labSleeve] || [];
  const countsTxt = cLo == null ? "un tamaño fijo"
    : cLo === cHi ? `siempre ${cLo}, nunca un tamaño distinto`
    : `entre ${cLo} y ${cHi} según cuántos no muestren desventaja de fase, nunca un tamaño fijo`;

  $("#labBlock").innerHTML = `
    <div class="wrap">
      <div class="section-head">
        <div class="eyebrow">Laboratorio · ${T.label}</div>
        <h2>Qué combinaciones funcionaron, y si siguieron funcionando</h2>
        <p class="cap">Para cada fase se evalúan <b>todas</b> las combinaciones posibles de
          ${S.k ?? 5} activos dentro del bloque — con ${S.universe?.length ?? "los"} candidatos en
          ${labSleeve.toLowerCase()} y grupos de ${S.k ?? 5}, eso son las
          <b>${S.n_combos ?? "cientos de"}</b> formas distintas de elegir ${S.k ?? 5} de entre
          ${S.universe?.length ?? "ellos"} sin importar el orden — partiendo los meses de esa fase en dos
          mitades por la mediana de la fecha (no al azar,
          para no mezclar meses consecutivos entre las dos mitades). Las combinaciones se ordenan por
          rentabilidad con la primera mitad y se miran en la segunda, que no se usó para elegirlas. La
          mejor de esas combinaciones siempre parece brillante en su propia mitad; lo que importa
          es si aguanta fuera de ella — igual que un fondo que fue el mejor del año pasado no tiene por
          qué repetir este año.</p>
        <p class="cap" style="margin-top:8px">Tamaño fijo a propósito — evaluar "todas las
          combinaciones" solo es tratable con un número constante de piezas. La cartera real de «Qué
          comprar ahora» no usa este número: elige ${countsTxt}. Esta sección responde una pregunta
          distinta y más simple: si lo que ganaba antes seguía ganando después.</p>
      </div>

      <div class="seg" id="labPhaseSeg" style="margin-bottom:10px">
        ${phases.map(p => `<button type="button" data-p="${p}" aria-pressed="${p === labPhase}"
          style="${p === labPhase ? `border-color:${PHASE_COLOR[p]};color:${PHASE_COLOR[p]}` : ""}">${p}</button>`).join("")}
      </div>
      ${sleeves.length > 1 ? `<div class="seg" id="labSleeveSeg" style="margin-bottom:18px">
        ${sleeves.map(x => `<button type="button" data-s="${x}" aria-pressed="${x === labSleeve}">${x}</button>`).join("")}
      </div>` : ""}

      <div class="outlook" style="margin-bottom:20px">
        <div class="item"><dt>Persistencia de combinaciones</dt><dd style="color:${icCol}">${icTxt}</dd><small>${icMsg}</small></div>
        <div class="item"><dt>Persistencia por activo suelto</dt><dd style="color:${aCol}">${aTxt}</dd><small>${aMsg}</small></div>
        <div class="item"><dt>Muestra</dt><dd>${P.n} meses</dd><small>fase completa, partida por la mediana de cada activo</small></div>
        <div class="item"><dt>Media de todas las combinaciones</dt><dd>${fmtNum(S.all_h2_mean, 1)}%</dd><small>en la segunda mitad · dispersión ±${fmtNum(S.all_h2_sd, 1)} pp</small></div>
      </div>

      ${noCombos ? `<div class="errbox" style="border-color:${PHASE_COLOR["Sobrecalentamiento"]};background:rgba(184,134,59,.07);margin-bottom:20px">
        <h2>Sin combinaciones evaluables en este bloque</h2>
        <p>${S.note || "No hay muestra suficiente."} Los activos sueltos sí aparecen abajo con los meses de que dispone cada uno.</p>
      </div>` : `
      <div class="matrix-holder" style="margin-bottom:14px">
        <table class="matrix">
          <thead><tr>
            <th>Mejores combinaciones según la primera mitad</th>
            <th style="text-align:right">1ª mitad</th>
            <th style="text-align:right">2ª mitad</th>
            <th style="text-align:right">Percentil en la 2ª</th>
          </tr></thead>
          <tbody>${(S.top || []).map(t => `
            <tr><td class="asset">${t.assets.join(" · ")}<small>${t.n} meses · ${t.span}</small></td>
              <td style="text-align:right;font-family:var(--mono)">${fmtNum(t.h1, 1)}%</td>
              <td style="text-align:right;font-family:var(--mono);color:${t.h2 > (S.all_h2_mean ?? 0) ? POS : NEG}">${fmtNum(t.h2, 1)}%</td>
              <td style="text-align:right;font-family:var(--mono);color:${t.pct_h2 > 0.5 ? POS : NEG}">${fmtPct(t.pct_h2, 0)}</td></tr>`).join("")}
          </tbody>
        </table>
      </div>
      <p class="foot" style="margin-bottom:26px">Percentil 50 % significa que esa combinación quedó justo
        en la media de las ${S.n_combos} posibles en la segunda mitad, o sea que elegirla no aportó nada.
        La mejor de la primera mitad acabó en el percentil
        <b style="color:${(S.best_h1_pct_in_h2 ?? 0) > 0.5 ? POS : NEG}">${fmtPct(S.best_h1_pct_in_h2, 0)}</b>.</p>`}

      <h3 style="font-family:var(--serif);font-size:16px;margin-bottom:10px">Activo por activo</h3>
      <div class="matrix-holder">
        <table class="matrix">
          <thead><tr><th>Activo</th><th style="text-align:right">1ª mitad</th>
            <th style="text-align:right">2ª mitad</th><th style="text-align:right">Diferencia</th></tr></thead>
          <tbody>${(S.assets_h1_h2 || []).slice()
            .sort((a, b) => (b.h1 ?? -999) - (a.h1 ?? -999)).map(a => `
            <tr style="${a.thin ? "opacity:.6" : ""}"><td class="asset">${a.name}<small>${a.n} meses${a.span ? ` · ${a.span}` : ""}${a.thin ? " · muestra corta" : ""}</small></td>
              <td style="text-align:right;font-family:var(--mono)">${fmtNum(a.h1, 1)}%</td>
              <td style="text-align:right;font-family:var(--mono)">${fmtNum(a.h2, 1)}%</td>
              <td style="text-align:right;font-family:var(--mono);color:${a.h2 - a.h1 >= 0 ? POS : NEG}">${signed(a.h2 - a.h1, 1)}</td></tr>`).join("")}
          </tbody>
        </table>
      </div>
    </div>`;

  $("#labPhaseSeg").querySelectorAll("button").forEach(b => { b.onclick = () => { labPhase = b.dataset.p; renderLab(); }; });
  $("#labSleeveSeg")?.querySelectorAll("button").forEach(b => { b.onclick = () => { labSleeve = b.dataset.s; renderLab(); }; });
}

/* ------------------------------- validación ----------------------------- */
function renderValidation() {
  const v = D.validation || {};
  const nber = v.nber;
  const T = v.transition || {};
  const host = $("#validation");
  host.innerHTML = `
    <div class="val-card">
      <h3>Contraste con las recesiones del NBER</h3>
      ${nber ? `<table>
        <tr title="De todos los meses que el NBER, con acceso a datos que en su momento no existían, acabó fechando como recesión, en cuántos el eje de crecimiento de este panel ya marcaba negativo — a esto en estadística se le llama 'recall' o sensibilidad"><td>Meses de recesión con crecimiento negativo</td><td>${fmtPct(nber.recall, 0)}</td></tr>
        <tr title="De todos los meses que el NBER fechó como expansión (no recesión), en cuántos el eje de crecimiento marcaba positivo — el reverso de la fila de arriba, a esto se le llama 'especificidad': si fuera bajo, el modelo vería recesión por todas partes, incluso en expansión clara"><td>Meses de expansión con crecimiento positivo</td><td>${fmtPct(nber.specificity, 0)}</td></tr>
        <tr title="De los meses que el NBER fechó como recesión, qué fracción cayó en la fase Reflación — la más fría de las cuatro, y la que cabría esperar que coincidiera más con una recesión real"><td>Recesiones repartidas en Reflación</td><td>${fmtPct(nber.phase_mix_in_recession["Reflación"], 0)}</td></tr>
        <tr title="El resto de meses de recesión que no cayeron en Reflación: caen aquí, en la fase de crecimiento débil con inflación aún alta — coherente con una recesión con inflación pegajosa, no con un fallo del modelo"><td>Recesiones repartidas en Estanflación</td><td>${fmtPct(nber.phase_mix_in_recession["Estanflación"], 0)}</td></tr>
      </table>
      <p class="cap" style="margin-top:10px;font-size:12px">El fechado del NBER (la autoridad oficial en
      EE.UU. sobre cuándo empieza y termina una recesión, que decide con meses de retraso y usando datos
      que este panel no tiene) no entra en ningún cálculo del modelo: es una comprobación externa e
      independiente, a posteriori.</p>` : "<p class='cap'>No disponible.</p>"}
    </div>
    <div class="val-card">
      <h3>Reparto y duración</h3>
      <table>
        ${D.phases.map(p => `<tr><td><span style="color:${PHASE_COLOR[p]}">■</span> ${p}</td>
          <td>${fmtPct(v.share?.[p], 0)} · ${fmtNum(v.duration_months?.[p], 1)} m</td></tr>`).join("")}
        <tr title="Cuánto se parecen entre sí, en la práctica, el eje de crecimiento y el de inflación desde 1959. Si estuvieran muy correlacionados (cerca de ±1), no serían dos historias independientes sino la misma contada dos veces, y el reloj de cuatro fases perdería sentido — cerca de 0 confirma que aportan información distinta."><td>Correlación entre los dos ejes</td><td>${fmtNum(v.factor_corr, 2)}</td></tr>
        ${v.rotation ? `<tr title="De todas las veces que la fase ha cambiado en el histórico, en qué fracción el cambio siguió el orden del reloj clásico (Recuperación → Sobrecalentamiento → Estanflación → Reflación → Recuperación) en vez de saltar a una fase no contigua. Por encima del 50% es más orden que azar (hay 3 destinos posibles al cambiar, así que el azar puro daría ~33%)."><td>Transiciones en el sentido del reloj</td>
          <td style="color:${v.rotation.clockwise_share < 0.4 ? NEG : "var(--ink)"}">${fmtPct(v.rotation.clockwise_share, 0)} de ${v.rotation.n_transitions}</td></tr>` : ""}
      </table>
    </div>
    <div class="val-card">
      <h3>Adónde se va desde cada fase</h3>
      <table class="tmatrix">
        <tr><th></th>${D.phases.map(p => `<th>${p.slice(0, 4)}</th>`).join("")}</tr>
        ${D.phases.map(a => `<tr><th class="rowh" style="color:${PHASE_COLOR[a]}">${a.slice(0, 12)}</th>
          ${D.phases.map(b => {
            const val = T[a]?.[b] ?? 0;
            return `<td style="background:rgba(169,117,44,${(val * 0.5).toFixed(3)})">${fmtPct(val, 0)}</td>`;
          }).join("")}</tr>`).join("")}
      </table>
      <p class="cap" style="margin-top:10px;font-size:12px">Probabilidad de estar en cada fase el mes
        siguiente. La diagonal alta indica que las fases persisten y el clasificador no salta con el ruido.</p>
    </div>`;
}

/* ----------------------------- diagnóstico ------------------------------ */
function renderDiagnostics() {
  const m = D.meta;
  const log = m.asset_log || [];
  const bad = log.filter(a => a.status !== "ok");
  const w = m.warnings || [];
  $("#diagBlock").innerHTML = `
    <div class="wrap">
      <div class="section-head">
        <div class="eyebrow">Diagnóstico</div>
        <h2>Qué entró y qué se quedó fuera</h2>
        <p class="cap">Ninguna fuente puede fallar en silencio: cada intento de descarga deja rastro.
          Si un activo no aparece en la matriz, aquí está el motivo.</p>
      </div>
      <div class="val-grid">
        <div class="val-card">
          <h3>Cobertura</h3>
          <table>
            <tr><td>Series macro</td><td>${m.series_ok}/${m.series_total}</td></tr>
            <tr><td>Activos cargados</td><td>${m.assets_ok}/${m.assets_tried}</td></tr>
            <tr><td>Tiempo de construcción</td><td>${fmtNum(m.build_seconds, 0)} s</td></tr>
            <tr><td>Avisos</td><td style="color:${w.length ? PHASE_COLOR["Sobrecalentamiento"] : "var(--ink-soft)"}">${w.length}</td></tr>
          </table>
        </div>
        <div class="val-card" style="grid-column:span 2">
          <h3>Activos no incorporados (${bad.length})</h3>
          ${bad.length ? `<table>${bad.map(a => `
            <tr><td>${a.name}<div style="color:var(--ink-faint);font-family:var(--mono);font-size:10.5px">${a.source}</div></td>
            <td style="color:${a.status === "fallo" ? NEG : "var(--ink-soft)"}">${a.status}<div style="color:var(--ink-faint);font-size:10.5px">${a.detail}</div></td></tr>`).join("")}</table>`
            : `<p class="cap">Todos los activos del universo se han cargado.</p>`}
        </div>
      </div>
      ${w.length ? `<details class="details" style="margin-top:18px"><summary>Avisos de la última construcción (${w.length})</summary>
        <div class="body"><ul>${w.map(x => `<li>${x}</li>`).join("")}</ul></div></details>` : ""}
    </div>`;
}

/* ------------------------------ metodología ----------------------------- */
function renderMethod() {
  const rules = [
    ["Un eje, muchas series", `Crecimiento e inflación se miden con ${D.indicators.filter(i => i.block !== "leading").length}
      series de FRED, no con una: una sola serie puede tener un mes raro por ruido propio; que once
      series distintas se muevan juntas es una señal mucho más difícil de fabricar por azar. Cada una
      entra como <em>z-score robusto</em> — cuántas "medianas de desviación absoluta" (MAD: la versión de
      la desviación estándar que usa la mediana en vez de la media, y que un solo dato extremo no puede
      disparar) se aleja del valor típico de esa misma serie — calculado con una <em>ventana móvil de
      diez años</em>: en cada fecha solo se usa el pasado, y solo el pasado reciente, nunca toda la
      historia por igual ni el futuro.`],
    ["Los pesos los pone la matriz de correlaciones", `Cada bloque se resume en su primer componente
      principal (PCA): la combinación de esas series que mejor explica cómo se mueven a la vez. Ningún
      peso está escrito a mano — lo decide la propia estructura de correlaciones de los datos — y la
      varianza explicada (qué fracción del movimiento conjunto capta ese único número) aparece en el
      panel de indicadores, sección «Por dentro».`],
    ["Cada dato entra cuando de verdad se publicó", `Cada serie lleva su retraso de publicación real
      (columna "retraso" en «Por dentro»). El PCE subyacente del mes t no influye en la clasificación
      hasta t+2, igual que en la vida real: un inversor de ese momento tampoco habría tenido ese dato
      antes. Ignorar esto — muy fácil de hacer sin querer — es la forma más común de que un backtest
      parezca mejor de lo que sería en directo.`],
    ["El cuadrante es el signo de los dos ejes", `Cero significa "en tendencia" por construcción (la
      media móvil de los últimos diez años de cada eje), no un umbral elegido para que cuadren las
      fases. Recuperación y Sobrecalentamiento están a la derecha del cero de crecimiento; arriba es
      más inflación que la tendencia reciente, abajo menos.`],
    ["La confianza sale de la geometría", `Un punto pegado a un eje es ambiguo: un pequeño cambio en el
      dato del mes que viene podría moverlo al cuadrante de al lado. La probabilidad de cada cuadrante
      sale de integrar una campana de Gauss (distribución normal) centrada en la medición actual, con la
      dispersión que el propio factor ha tenido realmente a ${D.current.horizon_m || 3} meses vista
      (±${fmtNum(D.current.sigma_g, 2)}σ en crecimiento, ±${fmtNum(D.current.sigma_i, 2)}σ en
      inflación) — así que un punto cerca del cruce de ejes siempre sale con menos confianza que uno
      instalado en pleno cuadrante, sin necesidad de una regla aparte para decirlo.`],
    ["Las notas de activos son contrastes, no opiniones", `Para cada activo y fase se calcula el exceso
      sobre su propia media histórica, con un error estándar <em>Newey-West</em> — una forma de medir el
      margen de error que no asume, como la fórmula de libro de texto, que cada mes es independiente del
      anterior: los retornos financieros suelen estar autocorrelacionados (un mes bueno tiende a ir
      seguido de otro parecido más de lo que el azar puro explicaría), y usar la fórmula simple ahí
      infla la confianza de forma artificial. La nota (+++ a ---) es el nivel de significación resultante,
      y se aplica la corrección de <em>Benjamini-Hochberg</em> — un método que ajusta el umbral de "esto es
      real" hacia arriba en proporción a cuántas pruebas se hacen a la vez — porque se testan cientos de
      casillas de golpe, y con tantas, algunas "señales" saldrían significativas por puro azar si no se
      corrigiera nada.`],
    ["El histórico es largo a propósito", `Los sectores usan las carteras de Ken French, que llegan a
      1926 — casi un siglo, con varios ciclos completos de negocio dentro. Con solo ETFs cotizados desde
      1999 apenas hay dos ciclos completos y cualquier resultado sería, en el mejor de los casos,
      anecdótico: no se puede separar una ventaja real de haber tenido suerte con el periodo elegido. Los
      tickers junto a cada activo son la forma real de ejecutarlo hoy, aunque el histórico que respalda
      la decisión venga de más atrás de lo que ese ETF concreto lleva cotizando.`],
    ["El backtest no mira al futuro para decidir el pasado", `Walk-forward significa exactamente eso:
      cada mes selecciona activos usando solo datos hasta el mes anterior, nunca información que en ese
      momento no existía todavía — ni el propio resultado de ese mes, ni revisiones posteriores del
      dato. Es la construcción la que impide la trampa, no una comprobación añadida después: no hay
      forma de que ese resultado esté inflado por haber mirado el futuro al elegir, porque nunca tuvo
      acceso a él.`],
    ["La comprobación externa es el NBER", `El fechado oficial de recesiones de EE.UU. (National Bureau
      of Economic Research, el árbitro académico reconocido para esto, que decide con meses de retraso y
      con datos que en su momento no existían) no entra en ninguna estimación del modelo: sirve solo,
      después de los hechos, para verificar que el eje de crecimiento se hunde cuando de verdad hay una
      recesión — ver «Control de calidad» más abajo.`],
    ["Cuando nada aguanta, se dice", `Si ninguna casilla sobrevive al control de falsos descubrimientos
      en la fase vigente, el panel lo dice explícitamente («Lo que aguanta») en vez de mostrar una
      recomendación con aspecto de certeza que en realidad no está respaldada por los datos.`],
  ];
  $("#rules").innerHTML = rules.map(([t, d]) => `<li><b>${t}</b>${d}</li>`).join("");

  $("#limits").innerHTML = `<ul>
    <li><b>No incorpora valoración.</b> Un sector puede ser el correcto para la fase y estar carísimo
    (cotizando a un múltiplo de beneficios ya muy exigente). El reloj dice cuándo suele pagar más un
    sector dado el ciclo, no a qué precio conviene pagarlo — eso requeriría otro tipo de análisis por
    completo, de valoración, que este panel no hace.</li>
    <li><b>Revisiones de los datos.</b> Se respeta el retraso de publicación real de cada serie, pero
    las cifras macro (PIB, empleo, inflación) casi siempre se revisan meses después de su primera
    publicación, a veces de forma sustancial. Este panel usa el dato tal como está disponible hoy en
    FRED, no la serie de publicaciones sucesivas que un inversor habría visto en tiempo real. El
    backtest es, en ese margen concreto, algo más optimista que la operativa real.</li>
    <li><b>Los treasuries son una aproximación.</b> Su retorno mensual se deriva matemáticamente del
    tipo de interés (TIR, la rentabilidad implícita del bono a día de hoy) más su duración y convexidad
    (cuánto se mueve el precio de un bono cuando cambian los tipos), no de un índice de retorno total
    real con las compras y ventas efectivas de un fondo — buena aproximación, pero aproximación.</li>
    <li><b>Los ETFs de la lista son el instrumento más parecido, no idéntico.</b> Un ETF sectorial pesa
    sus posiciones por capitalización bursátil actual y cambia de composición con el tiempo; las
    carteras académicas de Ken French que sostienen el histórico son otra cosa, reconstruidas con su
    propia metodología. Composición, comisión anual y tracking error (cuánto se desvía en la práctica
    la rentabilidad del ETF de la del índice que dice replicar) difieren entre el dato histórico y el
    instrumento real con el que se ejecutaría hoy.</li>
    <li><b>Régimen cambiante.</b> Una curva de Phillips más plana (la relación entre desempleo e
    inflación se ha debilitado desde los años 90), objetivos de inflación creíbles por parte de los
    bancos centrales y años de expansión cuantitativa (QE: compras masivas de bonos por la Fed) alteran
    relaciones económicas que el histórico largo da por estables. Lo que fue cierto en 1975 no tiene por
    qué seguir siéndolo igual en 2026.</li>
    <li><b>Cuatro cuadrantes son una simplificación.</b> Shocks de oferta, guerras o pandemias no caben
    bien en dos ejes continuos, y son precisamente los momentos en que más cara sale una clasificación
    equivocada — el modelo no distingue "inflación por exceso de demanda" de "inflación porque se ha
    cortado una cadena de suministro", aunque las dos suban el mismo número.</li>
    <li><b>No hay costes de operar.</b> Ni comisiones de compraventa, ni horquilla (la diferencia entre
    el precio de compra y venta de un valor en un momento dado), ni impuestos, en ningún backtest de
    este panel — la sección del backtest sí estima aparte cuánto restaría la rotación mensual a precios
    de mercado razonables, pero ni esa estimación ni ninguna otra cifra del panel la descuenta del
    resultado mostrado.</li>
  </ul>`;
}

function renderFooter() {
  const m = D.meta;
  const w = m.warnings?.length
    ? ` · <span style="color:${PHASE_COLOR["Sobrecalentamiento"]}">${m.warnings.length} avisos en la última descarga</span>`
    : "";
  $("#footMeta").innerHTML = `Una acción programada regenera el panel en días laborables. Última vez:
    ${m.generated_utc} · ${m.series_ok}/${m.series_total} series · histórico desde ${label(m.history_from)}${w}.`;
}

/* -------------------------------- controles ----------------------------- */
function wireControls() {
  const range = $("#trailRange");
  range.value = trail;
  $("#trailLenLbl").textContent = `${trail} meses de rastro`;
  range.oninput = () => {
    trail = Number(range.value);
    $("#trailLenLbl").textContent = `${trail} meses de rastro`;
    renderPlane();
  };
  const btn = $("#playBtn");
  btn.onclick = () => {
    if (playTimer) { stopPlay(); return; }
    btn.setAttribute("aria-pressed", "true");
    btn.textContent = "Detener";
    let k = Math.max(trail, 240);
    playTimer = setInterval(() => {
      k += 2;
      if (k >= D.history.length) { stopPlay(); renderPlane(); return; }
      renderPlane(k);
    }, 45);
  };
  function stopPlay() {
    clearInterval(playTimer);
    playTimer = null;
    btn.setAttribute("aria-pressed", "false");
    btn.textContent = "Recorrer histórico";
  }
  window.addEventListener("resize", () => { renderPlane(); }, { passive: true });
}

boot();
})();
