/* Reloj de inversión — render del panel. Sin dependencias externas. */
(() => {
"use strict";

const NS = "http://www.w3.org/2000/svg";
const PHASE_COLOR = {
  "Recuperación": "#35D0A5",
  "Sobrecalentamiento": "#F2A33C",
  "Estanflación": "#EE5D6C",
  "Reflación": "#5B8CFF",
};
const PHASE_HINT = {
  "Recuperación": "crecimiento sobre tendencia, inflación bajo tendencia",
  "Sobrecalentamiento": "crecimiento e inflación por encima de tendencia",
  "Estanflación": "crecimiento bajo tendencia, inflación por encima",
  "Reflación": "crecimiento e inflación por debajo de tendencia",
};
const BLOCK_TITLE = {
  growth: "Crecimiento (coincidente)",
  inflation: "Inflación",
  leading: "Condiciones financieras",
  standalone: "Aparte del PCA",
};
const MONTHS = ["ene","feb","mar","abr","may","jun","jul","ago","sep","oct","nov","dic"];

let D = null;              // payload
let trail = 36;
let activeClass = "Todo";
let onlySig = false;
let playTimer = null;

/* ------------------------------ utilidades ------------------------------ */
const $ = (sel, root = document) => root.querySelector(sel);
const el = (tag, attrs = {}, parent = null) => {
  const n = document.createElementNS(NS, tag);
  for (const k in attrs) n.setAttribute(k, attrs[k]);
  if (parent) parent.appendChild(n);
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
  // rojo -> neutro -> verde, con opacidad proporcional a la magnitud
  const t = Math.max(-1, Math.min(1, v / scale));
  const a = 0.10 + 0.55 * Math.abs(t);
  return t >= 0 ? `rgba(53,208,165,${a.toFixed(3)})` : `rgba(238,93,108,${a.toFixed(3)})`;
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
    <div class="errbox">
      <h2>Todavía no hay datos que mostrar</h2>
      <p>El panel lee <code>docs/data/data.json</code>, que genera la acción programada del repositorio.
      Lanza el flujo <b>Actualizar datos</b> en la pestaña Actions y recarga esta página.</p>
      <p style="margin-top:10px"><code>${String(err)}</code></p>
    </div>`;
}

function render() {
  const tpl = $("#tpl-main").content.cloneNode(true);
  $("#loading").remove();
  $("#app").appendChild(tpl);

  renderVitals();
  renderVerdict();
  renderOutlook();
  renderPlane();
  renderIndicators();
  renderTimeline();
  renderMatrix();
  renderRobustness();
  renderConsensus();
  renderBacktest();
  renderValidation();
  renderDiagnostics();
  renderMethod();
  renderFooter();
  wireControls();
}

/* -------------------------------- cabecera ------------------------------ */
function renderVitals() {
  const c = D.current, m = D.meta;
  const items = [
    ["Dato más reciente", label(c.date)],
    ["Crecimiento", signed(c.growth, 2) + " σ"],
    ["Inflación", signed(c.inflation, 2) + " σ"],
    ["Series activas", `${m.series_ok}/${m.series_total}`],
  ];
  $("#vitals").innerHTML = items
    .map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join("");
}

/* ------------------------------- veredicto ------------------------------ */
function monthsInPhase() {
  const h = D.history, p = D.current.phase;
  let n = 0;
  for (let i = h.length - 1; i >= 0 && h[i].p === p; i--) n++;
  return n;
}

function renderVerdict() {
  const c = D.current;
  const color = PHASE_COLOR[c.phase];
  const probs = D.phases.map(p => [p, c.probs[p] ?? 0]).sort((a, b) => b[1] - a[1]);
  const n = monthsInPhase();
  const rec = c.recession || {};

  $("#verdict").innerHTML = `
    <div>
      <span class="eyebrow">Fase vigente</span>
      <div class="phase-name" style="color:${color}">${c.phase_long}</div>
      <p class="phase-since">${n} ${n === 1 ? "mes" : "meses"} seguidos · ${PHASE_HINT[c.phase]}</p>
      <div class="conf-row">
        <span class="conf-num" style="color:${color}">${fmtPct(c.confidence)}</span>
        <span class="conf-lbl">de margen sobre la alternativa (${c.alt_phase})</span>
      </div>
    </div>
    <div class="probs">
      ${probs.map(([p, v], i) => `
        <div class="prob ${i === 0 ? "lead" : ""}">
          <span style="color:${i === 0 ? PHASE_COLOR[p] : "var(--muted)"}">${p}</span>
          <span class="bar"><i style="width:${(v * 100).toFixed(1)}%;background:${PHASE_COLOR[p]}"></i></span>
          <span class="val">${fmtPct(v, 1)}</span>
        </div>`).join("")}
    </div>
    <dl class="mini">
      <div><dt>Impulso crecimiento 3m</dt><dd style="color:${c.momentum.growth_3m >= 0 ? "var(--pos)" : "var(--neg)"}">${signed(c.momentum.growth_3m, 2)} σ</dd></div>
      <div><dt>Impulso inflación 3m</dt><dd style="color:${c.momentum.inflation_3m >= 0 ? "var(--neg)" : "var(--pos)"}">${signed(c.momentum.inflation_3m, 2)} σ</dd></div>
      <div><dt>Recesión a 12 meses</dt><dd>${rec.prob_12m != null ? fmtPct(rec.prob_12m, 0) : "—"}</dd></div>
      <div><dt>Deriva típica a ${c.horizon_m || 3} meses</dt><dd>±${fmtNum(c.sigma_g, 2)} / ±${fmtNum(c.sigma_i, 2)} σ</dd></div>
    </dl>
    <p class="note">${confidenceText(c)}</p>`;
}

function confidenceText(c) {
  const q = c.confidence;
  if (q >= 0.6) {
    return `Las dos dimensiones están lo bastante lejos de cero como para que el cuadrante
      aguante el ruido de medición. Se puede posicionar por la fase principal.`;
  }
  if (q >= 0.3) {
    return `El margen sobre <b>${c.alt_phase}</b> es estrecho. Tiene sentido inclinar la cartera
      hacia lo que funciona en ambas fases antes que apostar por una sola.`;
  }
  return `La economía está prácticamente encima de un eje: la clasificación es frágil.
    Prioriza los activos de consenso y evita apuestas que dependan del cuadrante exacto.`;
}

function renderOutlook() {
  const c = D.current, rec = c.recession || {};
  const lead = c.leading, lead6 = c.leading_6m;
  const dir = lead != null && lead6 != null ? lead - lead6 : null;
  const next = mostLikelyNext();
  $("#outlookBand").innerHTML = `
    <div class="item"><dt>Bloque adelantado</dt>
      <dd style="color:${lead >= 0 ? "var(--pos)" : "var(--neg)"}">${signed(lead, 2)} σ</dd>
      <small>Curva, condiciones financieras, permisos, horas y diferenciales. ${
        dir == null ? "" : dir >= 0 ? "Mejorando frente a hace 6 meses." : "Deteriorándose frente a hace 6 meses."}</small></div>
    <div class="item"><dt>Transición más probable</dt>
      <dd style="color:${PHASE_COLOR[next.phase]}">${next.phase}</dd>
      <small>${fmtPct(next.p, 0)} de los meses que siguieron a esta fase en 60 años terminaron aquí.</small></div>
    <div class="item"><dt>Persistencia media</dt>
      <dd>${fmtNum(D.validation.duration_months?.[c.phase], 1)} meses</dd>
      <small>Duración media histórica de un tramo en ${c.phase}.</small></div>
    <div class="item"><dt>Modelo de recesión</dt>
      <dd>${rec.prob_12m != null ? fmtPct(rec.prob_12m, 0) : "—"}</dd>
      <small>${rec.auc ? `Logit sobre curva y condiciones financieras, AUC ${fmtNum(rec.auc, 2)} en ${rec.n_obs} meses.` : "No disponible."}</small></div>`;
}

function mostLikelyNext() {
  const row = D.validation.transition?.[D.current.phase] || {};
  let best = { phase: "—", p: 0 };
  for (const [p, v] of Object.entries(row)) {
    if (p === D.current.phase) continue;
    if (v > best.p) best = { phase: p, p: v };
  }
  return best;
}

/* ------------------------- plano de fase (firma) ------------------------ */
const PLANE = { w: 720, h: 620, pad: 58 };

function planeScales() {
  const pts = D.history;
  const gmax = Math.max(2.2, ...pts.map(p => Math.abs(p.g))) * 1.06;
  const imax = Math.max(2.2, ...pts.map(p => Math.abs(p.i))) * 1.06;
  const { w, h, pad } = PLANE;
  return {
    x: g => pad + ((g + gmax) / (2 * gmax)) * (w - 2 * pad),
    y: i => (h - pad) - ((i + imax) / (2 * imax)) * (h - 2 * pad),
    gmax, imax,
  };
}

function renderPlane(cursor = null) {
  const svg = $("#plane");
  svg.innerHTML = "";
  const { w, h, pad } = PLANE;
  const S = planeScales();
  const cx = S.x(0), cy = S.y(0);

  // ojo: eje X = crecimiento, eje Y = inflación (arriba = más inflación)
  const quadDefs = [
    { name: "Sobrecalentamiento", x0: cx, x1: w - pad, y0: pad, y1: cy },
    { name: "Recuperación", x0: cx, x1: w - pad, y0: cy, y1: h - pad },
    { name: "Estanflación", x0: pad, x1: cx, y0: pad, y1: cy },
    { name: "Reflación", x0: pad, x1: cx, y0: cy, y1: h - pad },
  ];
  quadDefs.forEach(q => {
    el("rect", {
      x: q.x0, y: q.y0, width: q.x1 - q.x0, height: q.y1 - q.y0,
      fill: PHASE_COLOR[q.name], opacity: q.name === D.current.phase ? 0.10 : 0.035,
    }, svg);
  });

  // rejilla
  for (let v = -3; v <= 3; v++) {
    if (v === 0) continue;
    if (Math.abs(v) < S.gmax) {
      el("line", { x1: S.x(v), y1: pad, x2: S.x(v), y2: h - pad, stroke: "#1D2740", "stroke-width": 1 }, svg);
    }
    if (Math.abs(v) < S.imax) {
      el("line", { x1: pad, y1: S.y(v), x2: w - pad, y2: S.y(v), stroke: "#1D2740", "stroke-width": 1 }, svg);
    }
  }
  // ejes
  el("line", { x1: pad, y1: cy, x2: w - pad, y2: cy, stroke: "#3A486E", "stroke-width": 1.4 }, svg);
  el("line", { x1: cx, y1: pad, x2: cx, y2: h - pad, stroke: "#3A486E", "stroke-width": 1.4 }, svg);

  // etiquetas de cuadrante
  quadDefs.forEach(q => {
    const t = el("text", {
      x: (q.x0 + q.x1) / 2, y: q.y0 + 26, fill: PHASE_COLOR[q.name],
      "text-anchor": "middle", "font-family": "Space Grotesk, sans-serif",
      "font-size": 15, "font-weight": 700, opacity: q.name === D.current.phase ? 0.95 : 0.5,
    }, svg);
    t.textContent = q.name;
  });

  // títulos de eje
  const ax = el("text", { x: w - pad, y: cy - 12, fill: "#66748F", "text-anchor": "end",
    "font-family": "IBM Plex Mono, monospace", "font-size": 11.5 }, svg);
  ax.textContent = "crecimiento sobre tendencia →";
  const ax2 = el("text", { x: pad, y: cy + 20, fill: "#66748F",
    "font-family": "IBM Plex Mono, monospace", "font-size": 11.5 }, svg);
  ax2.textContent = "← por debajo de tendencia";
  const ayY = PLANE.h - pad - 4;
  const ay = el("text", { x: cx + 9, y: ayY, fill: "#66748F",
    "font-family": "IBM Plex Mono, monospace", "font-size": 11.5,
    transform: `rotate(-90 ${cx + 9} ${ayY})` }, svg);
  ay.textContent = "inflación sobre tendencia →";

  // rastro
  const hist = D.history;
  const end = cursor == null ? hist.length : cursor + 1;
  const pts = hist.slice(Math.max(0, end - trail), end);
  if (pts.length > 1) {
    const dstr = pts.map((p, k) => `${k ? "L" : "M"}${S.x(p.g).toFixed(1)},${S.y(p.i).toFixed(1)}`).join("");
    el("path", { d: dstr, fill: "none", stroke: "#8FA6D8", "stroke-width": 1.6,
      opacity: 0.35, "stroke-linejoin": "round" }, svg);
  }
  pts.forEach((p, k) => {
    const rel = (k + 1) / pts.length;
    const c = el("circle", {
      cx: S.x(p.g), cy: S.y(p.i), r: 2.4 + 2.6 * rel,
      fill: PHASE_COLOR[p.p], opacity: (0.10 + 0.75 * rel).toFixed(3),
    }, svg);
    c.dataset.i = hist.indexOf(p);
  });

  // punto actual + elipse de incertidumbre
  const cur = pts[pts.length - 1] || hist[hist.length - 1];
  const rx = Math.abs(S.x(D.current.sigma_g) - S.x(0));
  const ry = Math.abs(S.y(D.current.sigma_i) - S.y(0));
  el("ellipse", {
    cx: S.x(cur.g), cy: S.y(cur.i), rx: rx * 1.96, ry: ry * 1.96,
    fill: PHASE_COLOR[cur.p], opacity: 0.12,
    stroke: PHASE_COLOR[cur.p], "stroke-width": 1, "stroke-dasharray": "3 3", "stroke-opacity": 0.5,
  }, svg);
  el("circle", { cx: S.x(cur.g), cy: S.y(cur.i), r: 9, fill: "none",
    stroke: PHASE_COLOR[cur.p], "stroke-width": 1.5, opacity: 0.55 }, svg);
  el("circle", { cx: S.x(cur.g), cy: S.y(cur.i), r: 4.6, fill: PHASE_COLOR[cur.p] }, svg);
  const lab = el("text", {
    x: S.x(cur.g) + 14, y: S.y(cur.i) - 10, fill: "#E9EDF8",
    "font-family": "IBM Plex Mono, monospace", "font-size": 12, "font-weight": 500,
  }, svg);
  lab.textContent = label(cur.d);

  // interacción
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
  if (!best || bd > 900) { tip.hidden = true; return; }
  tip.hidden = false;
  tip.innerHTML = `<b>${label(best.d)}</b><br>${best.p}<br>
    crecimiento ${signed(best.g, 2)}σ · inflación ${signed(best.i, 2)}σ`;
  const px = (S.x(best.g) / PLANE.w) * r.width;
  const py = (S.y(best.i) / PLANE.h) * r.height;
  tip.style.left = `${Math.min(r.width - 170, px + 14)}px`;
  tip.style.top = `${Math.max(0, py - 60)}px`;
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
    ? (pos ? "var(--sobrecalentamiento)" : "var(--reflacion)")
    : (pos ? "var(--pos)" : "var(--neg)");
  const style = pos
    ? `left:50%;width:${pctW}%;background:${col}`
    : `right:50%;width:${pctW}%;background:${col}`;
  const delta = i.z_prev != null ? i.z - i.z_prev : null;
  const arrow = delta == null ? "" :
    (delta > 0.15 ? "▲" : delta < -0.15 ? "▼" : "▬");
  return `
    <div class="ind-row" title="${i.note || ""}">
      <div class="nm">${i.name}
        <small>${i.id} · retraso ${i.lag_m}m${i.invert ? " · invertida" : ""}${
          i.loading != null ? ` · peso ${fmtNum(i.loading, 2)}` : ""}</small>
      </div>
      <div class="zbar"><span class="axis"></span><i style="${style}"></i></div>
      <div class="zval" style="color:${col}">${signed(i.z, 2)} <span style="color:var(--muted-2);font-size:10px">${arrow}</span></div>
    </div>`;
}

/* -------------------------------- timeline ------------------------------ */
function renderTimeline() {
  const svg = $("#timeline");
  svg.innerHTML = "";
  const W = 1200, H = 300, padL = 42, padR = 12, padT = 10;
  const hist = D.history;
  const stripH = 26;
  const chartTop = padT + stripH + 16;
  const chartH = H - chartTop - 34;
  const x = k => padL + (k / (hist.length - 1)) * (W - padL - padR);
  const vmax = Math.max(2.5, ...hist.map(p => Math.max(Math.abs(p.g), Math.abs(p.i))));
  const y = v => chartTop + chartH / 2 - (v / vmax) * (chartH / 2);

  $("#histFrom").textContent = label(hist[0].d);

  // recesiones NBER
  const idxOf = {};
  hist.forEach((p, k) => { idxOf[p.d] = k; });
  (D.nber || []).forEach(([a, b]) => {
    const ia = idxOf[a], ib = idxOf[b];
    if (ia == null || ib == null) return;
    el("rect", { x: x(ia), y: padT, width: Math.max(1, x(ib) - x(ia)), height: H - padT - 30,
      fill: "#9AA8C4", opacity: 0.10 }, svg);
  });

  // franja de fases
  let runStart = 0;
  for (let k = 1; k <= hist.length; k++) {
    if (k === hist.length || hist[k].p !== hist[runStart].p) {
      el("rect", { x: x(runStart), y: padT, width: Math.max(1, x(k - 1) - x(runStart) + 1),
        height: stripH, fill: PHASE_COLOR[hist[runStart].p], opacity: 0.85 }, svg);
      runStart = k;
    }
  }

  // rejilla y ejes
  [-2, -1, 0, 1, 2].forEach(v => {
    if (Math.abs(v) > vmax) return;
    el("line", { x1: padL, y1: y(v), x2: W - padR, y2: y(v),
      stroke: v === 0 ? "#3A486E" : "#1D2740", "stroke-width": 1 }, svg);
    const t = el("text", { x: padL - 8, y: y(v) + 4, fill: "#66748F", "text-anchor": "end",
      "font-family": "IBM Plex Mono, monospace", "font-size": 10 }, svg);
    t.textContent = `${v > 0 ? "+" : ""}${v}σ`;
  });

  const line = (key, color) => {
    const d = hist.map((p, k) => `${k ? "L" : "M"}${x(k).toFixed(1)},${y(p[key]).toFixed(1)}`).join("");
    el("path", { d, fill: "none", stroke: color, "stroke-width": 1.5, opacity: 0.9 }, svg);
  };
  line("i", "#F2A33C");
  line("g", "#5B8CFF");

  // años
  const years = {};
  hist.forEach((p, k) => { const yy = p.d.slice(0, 4); if (!(yy in years)) years[yy] = k; });
  const keys = Object.keys(years);
  const step = Math.ceil(keys.length / 14);
  keys.forEach((yy, n) => {
    if (n % step) return;
    const t = el("text", { x: x(years[yy]), y: H - 12, fill: "#66748F", "text-anchor": "middle",
      "font-family": "IBM Plex Mono, monospace", "font-size": 10 }, svg);
    t.textContent = yy;
  });

  // leyenda
  const lg = [["Crecimiento", "#5B8CFF"], ["Inflación", "#F2A33C"], ["Recesión NBER", "#9AA8C4"]];
  lg.forEach(([txt, col], n) => {
    el("rect", { x: padL + n * 150, y: H - 26, width: 10, height: 3, fill: col, opacity: .9 }, svg);
    const t = el("text", { x: padL + n * 150 + 16, y: H - 22, fill: "#8E9CBB",
      "font-family": "IBM Plex Mono, monospace", "font-size": 10 }, svg);
    t.textContent = txt;
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
        ${p}<span>${p === cur ? "fase vigente" : "&nbsp;"}</span></th>`).join("")}
      <th style="text-align:right">Media</th>
    </tr></thead>`;

  const groups = {};
  rows.forEach(a => { (groups[a.class] ||= []).push(a); });

  let body = "";
  for (const [cls, items] of Object.entries(groups)) {
    body += `<tr class="grp"><td colspan="${D.phases.length + 2}">${cls}</td></tr>`;
    for (const a of items) {
      body += `<tr><td class="asset">${a.name}<small>${a.source} · desde ${a.from.slice(0, 7)} · ${a.n} meses</small></td>`;
      for (const p of D.phases) {
        const d = a.phases[p] || {};
        if (d.grade == null || d.grade === "s/d") {
          body += `<td class="cell dim">—</td>`;
          continue;
        }
        const sig = d.grade !== "0";
        const col = sig ? diverging(d.rel, 12) : "transparent";
        const txtCol = d.rel >= 0 ? "var(--pos)" : "var(--neg)";
        body += `<td class="cell ${p === cur ? "active" : ""} ${sig ? "" : "dim"}"
            style="background:${col}"
            title="anualizado ${fmtNum(d.ann, 1)}% · exceso ${signed(d.rel, 1)} pp${d.rel_shrunk != null ? ` (contraído ${signed(d.rel_shrunk, 1)})` : ""} · t=${fmtNum(d.t, 2)}${d.q != null ? ` · q=${fmtNum(d.q, 3)}` : ""} · ${d.n} meses · aciertos ${fmtPct(d.hit, 0)}">
            <span class="g" style="color:${sig ? txtCol : "var(--muted-2)"}">${d.grade}</span>
            <span class="r">${signed(d.rel, 1)}</span></td>`;
      }
      body += `<td style="text-align:right;font-family:var(--mono);color:var(--muted)">${fmtNum(a.uncond_ann, 1)}%</td></tr>`;
    }
  }

  $("#matrix").innerHTML = head + `<tbody>${body}</tbody>`;
  $("#matrixFoot").innerHTML = `
    Cada celda: exceso anualizado en puntos porcentuales frente a la media histórica del propio activo,
    y la nota que resume su significatividad. Pasa el cursor por encima para ver t, q, número de meses y tasa de acierto.
    <b>+++ / ---</b> p&lt;0,01 con FDR ≤ 0,10 &nbsp;·&nbsp; <b>++ / --</b> p&lt;0,05 &nbsp;·&nbsp; <b>+ / -</b> p&lt;0,20 &nbsp;·&nbsp; <b>0</b> indistinguible de su media.`;
}

/* -------------------------------- consenso ------------------------------ */
function renderConsensus() {
  const host = $("#consensusBlock");
  const c = D.current;
  const list = D.consensus || [];
  if (c.confidence >= 0.6 || !list.length) {
    host.innerHTML = `
      <div class="block-head">
        <span class="eyebrow">Solapamiento</span>
        <h2>Cartera de consenso</h2>
        <p class="cap">${c.confidence >= 0.6
          ? `La clasificación tiene ${fmtPct(c.confidence)} de margen: no hace falta cubrirse contra la fase alternativa. La columna de ${c.phase} de la matriz es suficiente.`
          : "No hay activos con nota positiva simultánea en las dos fases candidatas. Liquidez y duración corta son la posición por defecto."}</p>
      </div>`;
    return;
  }
  host.innerHTML = `
    <div class="block-head">
      <span class="eyebrow">Solapamiento</span>
      <h2>Lo que funciona en las dos fases candidatas</h2>
      <p class="cap">Con ${fmtPct(c.confidence)} de margen entre <b>${c.phase}</b> y <b>${c.alt_phase}</b>,
      estos activos tienen exceso positivo y contrastado en ambas: sobreviven a equivocarse de cuadrante.</p>
    </div>
    <div class="cons-grid">
      ${list.map(r => `
        <div class="cons-card">
          <span class="cls">${r.class}</span>
          <h4>${r.name}</h4>
          <div class="pair">
            <div><span>${c.phase.slice(0, 12)}</span><br>${r.g1} · ${signed(r.r1, 1)} pp</div>
            <div><span>${c.alt_phase.slice(0, 12)}</span><br>${r.g2} · ${signed(r.r2, 1)} pp</div>
          </div>
        </div>`).join("")}
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
    <div class="block-head">
      <span class="eyebrow">Lo que aguanta</span>
      <h2>Qué comprar, según lo que resiste el contraste</h2>
      <p class="cap">De ${st.cells ?? "—"} casillas contrastadas, <b>${st.graded ?? "—"}</b> tienen nota
        y <b>${st.fdr_survivors ?? "—"}</b> sobreviven al control de falsos descubrimientos.
        Con cientos de pruebas simultáneas, unas cuantas "señales" salen por azar: solo estas últimas
        son defendibles.</p>
    </div>
    ${ok ? `
      <div class="cons-grid">
        ${strong.slice(0, 8).map(x => `
          <div class="cons-card" style="border-color:${x.d.rel >= 0 ? "var(--recuperacion)" : "var(--estanflacion)"}">
            <span class="cls">${x.a.class}</span>
            <h4>${x.a.name}</h4>
            <div class="pair">
              <div><span>exceso</span><br>${signed(x.d.rel, 1)} pp${
                x.d.rel_shrunk != null ? ` <span style="color:var(--muted-2)">(${signed(x.d.rel_shrunk, 1)} tras contraer)</span>` : ""}</div>
              <div><span>t · q</span><br>${fmtNum(x.d.t, 1)} · ${fmtNum(x.d.q, 3)}</div>
            </div>
          </div>`).join("")}
      </div>
      <p class="foot">Estas son las posiciones con base empírica en ${cur}. El resto de la matriz
        es informativo, no accionable.</p>`
      : `<div class="errbox" style="border-color:var(--sobrecalentamiento);background:rgba(242,163,60,.06)">
          <h2>Ninguna recomendación aguanta el contraste</h2>
          <p>En ${cur}, ningún activo del universo tiene un exceso sobre su propia media que sobreviva
          al control de falsos descubrimientos. Eso no es un fallo del panel: es el resultado.</p>
          <p style="margin-top:10px">Lo honesto entonces es no rotar por fase. La cartera estratégica,
          la diversificación y el coste mandan más que el cuadrante. El reloj sigue sirviendo para
          saber dónde estás y para el modelo de recesión, no para decidir la cartera.</p>
        </div>`}`;
}

/* ----------------------------- diagnóstico ------------------------------ */
function renderDiagnostics() {
  const m = D.meta;
  const log = m.asset_log || [];
  const bad = log.filter(a => a.status !== "ok");
  const w = m.warnings || [];
  $("#diagBlock").innerHTML = `
    <div class="block-head">
      <span class="eyebrow">Diagnóstico</span>
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
          <tr><td>Avisos</td><td style="color:${w.length ? "var(--sobrecalentamiento)" : "var(--muted)"}">${w.length}</td></tr>
        </table>
      </div>
      <div class="val-card" style="grid-column:span 2">
        <h3>Activos no incorporados (${bad.length})</h3>
        ${bad.length ? `<table>${bad.map(a => `
          <tr><td>${a.name}<div style="color:var(--muted-2);font-family:var(--mono);font-size:10.5px">${a.source}</div></td>
          <td style="color:${a.status === "fallo" ? "var(--estanflacion)" : "var(--muted)"}">${a.status}<div style="color:var(--muted-2);font-size:10.5px">${a.detail}</div></td></tr>`).join("")}</table>`
          : `<p class="cap">Todos los activos del universo se han cargado.</p>`}
      </div>
    </div>
    ${w.length ? `<details class="limits" style="margin-top:16px"><summary>Avisos de la última construcción (${w.length})</summary>
      <div><ul>${w.map(x => `<li>${x}</li>`).join("")}</ul></div></details>` : ""}`;
}

/* -------------------------------- backtest ------------------------------ */
function renderBacktest() {
  const bt = D.backtest || {};
  if (!bt.long) {
    $("#btStats").innerHTML = `<p class="cap">No hay histórico suficiente para el backtest.</p>`;
    return;
  }
  drawBtChart(bt);
  const rows = [
    ["Larga, fuera de muestra", bt.long],
    ["Inclinada (80% 60/40 + 20% fase)", bt.tilt],
    ["Larga, volatilidad igualada", bt.scaled],
    ["Larga menos corta (señal pura)", bt.spread],
    ["60/40 estático", bt.bench_6040],
    ["Equiponderada", bt.equal_weight],
    ["Larga, en muestra (trampa)", bt.in_sample],
  ].filter(r => r[1] && r[1].cagr != null);

  const gap = bt.in_sample && bt.long ? bt.in_sample.cagr - bt.long.cagr : null;
  const bench = bt.bench_6040 || {};
  const edge = bt.scaled && bench.sharpe != null
    ? bt.scaled.sharpe - bench.sharpe : null;
  $("#btStats").innerHTML = `
    <table>
      <thead><tr><th>Cartera</th><th>Anual</th><th>Vol</th><th>Sharpe</th><th>Caída máx.</th><th>t</th></tr></thead>
      <tbody>${rows.map(([n, s]) => `
        <tr><td>${n}</td><td>${fmtNum(s.cagr, 1)}%</td><td>${fmtNum(s.vol, 1)}%</td>
        <td>${fmtNum(s.sharpe, 2)}</td><td>${fmtNum(s.maxdd, 1)}%</td><td>${fmtNum(s.t, 1)}</td></tr>`).join("")}
      </tbody>
    </table>
    <p class="gap-note">${gap == null ? "" : `Optimizar con la muestra completa habría dado
      <b>${fmtNum(gap, 1)} puntos</b> más al año. Esa diferencia es sobreajuste: no existía
      en tiempo real. ${bt.long.months} meses fuera de muestra desde ${bt.long.from.slice(0, 7)},
      ${bt.top_k} activos equiponderados.`}</p>
    ${edge == null ? "" : `<p class="gap-note" style="border-left-color:${edge > 0.05 ? "var(--recuperacion)" : "var(--estanflacion)"}">
      Comparación limpia: con la volatilidad igualada al 60/40, el Sharpe es
      <b>${fmtNum(bt.scaled.sharpe, 2)}</b> frente a <b>${fmtNum(bench.sharpe, 2)}</b>.
      ${edge > 0.05
        ? "La fase aporta información más allá de asumir más riesgo."
        : "Sin ventaja ajustada por riesgo: la rentabilidad extra viene de cargar más riesgo, no de acertar la fase."}
      La inclinada es la versión implementable en una cartera real: un 60/40 de base con un
      20 % desviado hacia lo mejor de la fase.
      La cartera larga-corta aísla la señal sin beta de mercado: ${
        bt.spread && bt.spread.t != null
          ? `t = ${fmtNum(bt.spread.t, 1)} sobre ${bt.spread.months} meses.`
          : "sin datos."}</p>`}`;
}

function drawBtChart(bt) {
  const svg = $("#btChart");
  svg.innerHTML = "";
  const W = 900, H = 340, padL = 52, padR = 14, padT = 14, padB = 28;
  const c = bt.curve || [];
  if (c.length < 10) return;
  let s = 100, b = 100;
  const S = [], B = [];
  c.forEach(p => {
    s *= 1 + p.s / 100; S.push(s);
    if (p.b != null) { b *= 1 + p.b / 100; }
    B.push(b);
  });
  const lo = Math.min(...S, ...B) * 0.95, hi = Math.max(...S, ...B) * 1.05;
  const x = k => padL + (k / (c.length - 1)) * (W - padL - padR);
  const y = v => H - padB - ((Math.log(v) - Math.log(lo)) / (Math.log(hi) - Math.log(lo))) * (H - padT - padB);

  [1, 2, 5, 10, 20, 50].map(m => 100 * m).filter(v => v > lo && v < hi).forEach(v => {
    el("line", { x1: padL, y1: y(v), x2: W - padR, y2: y(v), stroke: "#1D2740" }, svg);
    const t = el("text", { x: padL - 8, y: y(v) + 4, fill: "#66748F", "text-anchor": "end",
      "font-family": "IBM Plex Mono, monospace", "font-size": 10 }, svg);
    t.textContent = `${v / 100}×`;
  });

  const path = (arr, col, wdt, op) => {
    const d = arr.map((v, k) => `${k ? "L" : "M"}${x(k).toFixed(1)},${y(v).toFixed(1)}`).join("");
    el("path", { d, fill: "none", stroke: col, "stroke-width": wdt, opacity: op }, svg);
  };
  path(B, "#66748F", 1.4, 0.8);
  path(S, "#35D0A5", 1.9, 1);

  const step = Math.ceil(c.length / 10);
  c.forEach((p, k) => {
    if (k % step) return;
    const t = el("text", { x: x(k), y: H - 8, fill: "#66748F", "text-anchor": "middle",
      "font-family": "IBM Plex Mono, monospace", "font-size": 10 }, svg);
    t.textContent = p.d.slice(0, 4);
  });
  [["Reloj, fuera de muestra", "#35D0A5"], ["60/40", "#66748F"]].forEach(([txt, col], n) => {
    el("rect", { x: padL + n * 200, y: padT, width: 10, height: 3, fill: col }, svg);
    const t = el("text", { x: padL + n * 200 + 16, y: padT + 4, fill: "#8E9CBB",
      "font-family": "IBM Plex Mono, monospace", "font-size": 10.5 }, svg);
    t.textContent = txt;
  });
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
        <tr><td>Meses de recesión con crecimiento negativo</td><td>${fmtPct(nber.recall, 0)}</td></tr>
        <tr><td>Meses de expansión con crecimiento positivo</td><td>${fmtPct(nber.specificity, 0)}</td></tr>
        <tr><td>Recesiones repartidas en Reflación</td><td>${fmtPct(nber.phase_mix_in_recession["Reflación"], 0)}</td></tr>
        <tr><td>Recesiones repartidas en Estanflación</td><td>${fmtPct(nber.phase_mix_in_recession["Estanflación"], 0)}</td></tr>
      </table>
      <p class="cap" style="margin-top:10px;font-size:12px">El fechado del NBER no entra en el modelo:
      es una comprobación externa e independiente.</p>` : "<p class='cap'>No disponible.</p>"}
    </div>
    <div class="val-card">
      <h3>Reparto y duración</h3>
      <table>
        ${D.phases.map(p => `<tr><td><span style="color:${PHASE_COLOR[p]}">■</span> ${p}</td>
          <td>${fmtPct(v.share?.[p], 0)} · ${fmtNum(v.duration_months?.[p], 1)} m</td></tr>`).join("")}
        <tr><td>Correlación entre los dos ejes</td><td>${fmtNum(v.factor_corr, 2)}</td></tr>
        ${v.rotation ? `<tr><td>Transiciones en el sentido del reloj</td>
          <td style="color:${v.rotation.clockwise_share < 0.4 ? "var(--estanflacion)" : "var(--text)"}">${fmtPct(v.rotation.clockwise_share, 0)} de ${v.rotation.n_transitions}</td></tr>` : ""}
      </table>
    </div>
    <div class="val-card">
      <h3>Adónde se va desde cada fase</h3>
      <table class="tmatrix">
        <tr><th></th>${D.phases.map(p => `<th>${p.slice(0, 4)}</th>`).join("")}</tr>
        ${D.phases.map(a => `<tr><th class="rowh" style="color:${PHASE_COLOR[a]}">${a.slice(0, 12)}</th>
          ${D.phases.map(b => {
            const val = T[a]?.[b] ?? 0;
            return `<td style="background:rgba(91,140,255,${(val * 0.5).toFixed(3)})">${fmtPct(val, 0)}</td>`;
          }).join("")}</tr>`).join("")}
      </table>
      <p class="cap" style="margin-top:10px;font-size:12px">Probabilidad de estar en cada fase el mes siguiente.
      La diagonal alta indica que las fases persisten y el clasificador no salta con el ruido.</p>
    </div>`;
}

/* ------------------------------ metodología ----------------------------- */
function renderMethod() {
  const rules = [
    ["Un eje, muchas series", `Crecimiento e inflación se miden con ${D.indicators.filter(i => i.block !== "leading").length}
      series de FRED, no con una. Cada una entra como z-score calculado con media y desviación
      <b>expansivas</b>: en cada fecha solo se usa el pasado.`],
    ["Los pesos los pone la matriz de correlaciones", `Cada bloque se resume en su primer componente principal.
      Ningún peso está escrito a mano, y la varianza explicada aparece en el panel de indicadores.`],
    ["Cada dato entra cuando de verdad se publicó", `Cada serie lleva su retraso de publicación.
      El PCE subyacente del mes t no influye en la clasificación hasta t+2, igual que en la vida real.`],
    ["El cuadrante es el signo de los dos ejes", `Cero significa "en tendencia" por construcción, no un umbral elegido.
      Recuperación y Sobrecalentamiento están a la derecha del cero de crecimiento; arriba es más inflación.`],
    ["La confianza sale de la geometría", `Un punto pegado a un eje es ambiguo. La probabilidad de cada cuadrante sale de integrar
      una normal centrada en la medición actual, con la dispersión que el propio factor ha tenido a
      ${D.current.horizon_m || 3} meses vista (±${fmtNum(D.current.sigma_g, 2)}σ en crecimiento,
      ±${fmtNum(D.current.sigma_i, 2)}σ en inflación). Traduce "¿aguanta este cuadrante lo que dura la posición?".`],
    ["Las notas de activos son contrastes, no opiniones", `Para cada activo y fase se calcula el exceso sobre su propia
      media con error estándar Newey-West. La nota es el nivel de significación, y se aplica Benjamini-Hochberg
      porque se testan cientos de casillas a la vez.`],
    ["El histórico es largo a propósito", `Los sectores usan las carteras de Ken French, que llegan a 1926.
      Con solo ETFs desde 1999 apenas hay dos ciclos completos y cualquier resultado sería anecdótico.`],
    ["El backtest no se mira a sí mismo", `Cada mes selecciona activos con datos hasta el mes anterior.
      La versión in-sample se publica al lado precisamente para que se vea cuánto se infla el resultado al hacer trampa.`],
    ["La comprobación externa es el NBER", `El fechado oficial de recesiones no entra en ninguna estimación:
      sirve solo para verificar que el eje de crecimiento se hunde cuando debe.`],
  ];
  $("#rules").innerHTML = rules.map(([t, d]) => `<li><b>${t}</b>${d}</li>`).join("");

  $("#limits").innerHTML = `<ul>
    <li><b>No incorpora valoración.</b> Un sector puede ser el correcto para la fase y estar carísimo.
    El reloj dice cuándo, no a qué precio.</li>
    <li><b>Revisiones.</b> Se respeta el retraso de publicación, pero no se reconstruyen las revisiones posteriores
    de cada dato. El backtest es optimista en ese margen.</li>
    <li><b>Los treasuries son una aproximación.</b> Su retorno se deriva de la TIR con duración y convexidad,
    no de un índice de retorno total real.</li>
    <li><b>Régimen cambiante.</b> Curva de Phillips más plana, objetivos de inflación creíbles y QE alteran
    relaciones que el histórico largo da por estables.</li>
    <li><b>Cuatro cuadrantes son una simplificación.</b> Shocks de oferta, guerras o pandemias no caben
    en dos ejes.</li>
  </ul>`;
}

function renderFooter() {
  const m = D.meta;
  const w = m.warnings?.length
    ? ` · <span style="color:var(--sobrecalentamiento)">${m.warnings.length} avisos en la última descarga</span>`
    : "";
  $("#footMeta").innerHTML = `Datos: FRED (Reserva Federal de St. Louis), ICE BofA, biblioteca de Kenneth French, Stooq.
    Actualizado ${m.generated_utc} · ${m.series_ok}/${m.series_total} series · histórico desde ${label(m.history_from)}${w}`;
}

/* -------------------------------- controles ----------------------------- */
function wireControls() {
  const range = $("#trailRange");
  range.value = trail;
  $("#trailLen").textContent = trail;
  range.oninput = () => {
    trail = Number(range.value);
    $("#trailLen").textContent = trail;
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
    btn.textContent = "Recorrer el histórico";
  }
  window.addEventListener("resize", () => { renderPlane(); }, { passive: true });
}

boot();
})();
