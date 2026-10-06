#!/usr/bin/env python3
"""Informe mensual "Market Pulse" en PDF, generado a partir de docs/data/data.json.

Todo sale de los datos ya calculados por build_data.py: no recalcula nada ni inventa
nada. Los gráficos son SVG generados aquí; el PDF lo renderiza Chromium (Playwright).

Uso:  python scripts/build_report.py [--force] [--html-only]
Salida: docs/reports/market-pulse.pdf  y  docs/reports/market-pulse-AAAA-MM.pdf
Para no engordar el repositorio, solo se regenera si cambia el mes, la fase, o si el
último informe tiene más de 7 días (o con --force).
"""
from __future__ import annotations

import html
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "docs" / "data" / "data.json"
OUT = ROOT / "docs" / "reports"

PHASES = ["Recuperación", "Sobrecalentamiento", "Estanflación", "Reflación"]
PC = {"Recuperación": "#3F6B52", "Sobrecalentamiento": "#B8863B",
      "Estanflación": "#9C4A3C", "Reflación": "#3E4E7A"}
INK, INK2, SOFT, FAINT = "#1B1810", "#322C1F", "#5B5340", "#8C8268"
PAPER, RAISED, DEEP = "#F6F2E8", "#FBF9F3", "#EEE6D2"
ACCENT, POS, NEG = "#A9752C", "#3F6B52", "#9C4A3C"
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]
PHASE_HINT = {
    "Recuperación": "crecimiento sobre tendencia, inflación bajo tendencia",
    "Sobrecalentamiento": "crecimiento e inflación por encima de tendencia",
    "Estanflación": "crecimiento bajo tendencia, inflación por encima",
    "Reflación": "crecimiento e inflación por debajo de tendencia",
}
PHASE_ONE = {
    "Recuperación": "La economía sale del bache: la actividad repunta sin presión de precios.",
    "Sobrecalentamiento": "Actividad firme y precios al alza: el ciclo está maduro y el banco central aprieta.",
    "Estanflación": "La actividad se enfría mientras los precios siguen altos: la fase más incómoda.",
    "Reflación": "Actividad y precios por debajo de tendencia: terreno de recesión o de desaceleración fuerte.",
}


# ------------------------------------------------------------------ utilidades
def e(s) -> str:
    return html.escape(str(s if s is not None else ""))


def num(v, d=1, sign=False):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    s = f"{v:+.{d}f}" if sign else f"{v:.{d}f}"
    return s.replace(".", ",").replace("-", "−")


def pct(v, d=0):
    return "—" if v is None else num(v * 100, d) + "%"


def tc(o):
    return None if not o else (o.get("cagr_tot") if o.get("cagr_tot") is not None else o.get("cagr"))


def mes_label(ym: str) -> str:
    y, m = ym[:4], int(ym[5:7])
    return f"{MESES[m - 1][:3]} {y}"


def diverge(v, scale=12.0):
    """Color divergente (verde/terracota) con intensidad por magnitud, sobre papel."""
    if v is None:
        return "transparent"
    a = min(1.0, abs(v) / scale) * 0.62
    rgb = "63,107,82" if v >= 0 else "156,74,60"
    return f"rgba({rgb},{a:.2f})"


# ------------------------------------------------------------------ gráficos SVG
def svg_plane(D, trail=36, w=520, h=560):
    hist = D["history"]
    cur = D["current"]
    pts = hist[-trail:]
    R = 3.0
    pl, pr, pt, pb = 38, 14, 14, 34
    X = lambda g: pl + (max(-R, min(R, g)) + R) / (2 * R) * (w - pl - pr)
    Y = lambda i: pt + (R - max(-R, min(R, i))) / (2 * R) * (h - pt - pb)
    x0, y0 = X(0), Y(0)
    q = {
        "Recuperación": (pl, y0, x0 - pl, 0), "Sobrecalentamiento": (x0, pt, 0, 0),
    }
    s = [f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" class="chart">']
    quads = [("Estanflación", pl, pt, x0 - pl, y0 - pt), ("Sobrecalentamiento", x0, pt, w - pr - x0, y0 - pt),
             ("Reflación", pl, y0, x0 - pl, h - pb - y0), ("Recuperación", x0, y0, w - pr - x0, h - pb - y0)]
    for ph, qx, qy, qw, qh in quads:
        on = ph == cur["phase"]
        s.append(f'<rect x="{qx:.1f}" y="{qy:.1f}" width="{qw:.1f}" height="{qh:.1f}" fill="{PC[ph]}" opacity="{0.20 if on else 0.08}"/>')
    for ph, qx, qy, qw, qh in quads:
        lx = qx + 10 if qx < x0 else qx + qw - 10
        anchor = "start" if qx < x0 else "end"
        ly = qy + 20 if qy < y0 else qy + qh - 12
        s.append(f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}" class="qlab" fill="{PC[ph]}">{e(ph.upper())}</text>')
    for v in range(-3, 4):
        s.append(f'<line x1="{X(v):.1f}" y1="{pt}" x2="{X(v):.1f}" y2="{h - pb}" stroke="{INK}" stroke-opacity="{0.55 if v == 0 else 0.07}" stroke-width="{1.2 if v == 0 else 0.8}"/>')
        s.append(f'<line x1="{pl}" y1="{Y(v):.1f}" x2="{w - pr}" y2="{Y(v):.1f}" stroke="{INK}" stroke-opacity="{0.55 if v == 0 else 0.07}" stroke-width="{1.2 if v == 0 else 0.8}"/>')
        if v:
            s.append(f'<text x="{X(v):.1f}" y="{h - pb + 14}" text-anchor="middle" class="tick">{v:+d}σ</text>')
            s.append(f'<text x="{pl - 6}" y="{Y(v) + 3:.1f}" text-anchor="end" class="tick">{v:+d}σ</text>')
    s.append(f'<text x="{(pl + w - pr) / 2:.1f}" y="{h - 4}" text-anchor="middle" class="axl">CRECIMIENTO →</text>')
    s.append(f'<text transform="translate(10 {(pt + h - pb) / 2:.1f}) rotate(-90)" text-anchor="middle" class="axl">INFLACIÓN →</text>')
    path = " ".join(("M" if k == 0 else "L") + f"{X(p['g']):.1f},{Y(p['i']):.1f}" for k, p in enumerate(pts))
    s.append(f'<path d="{path}" fill="none" stroke="{INK}" stroke-opacity="0.35" stroke-width="1.3"/>')
    for k, p in enumerate(pts):
        a = 0.15 + 0.7 * k / max(1, len(pts) - 1)
        s.append(f'<circle cx="{X(p["g"]):.1f}" cy="{Y(p["i"]):.1f}" r="2.8" fill="{PC[p["p"]]}" fill-opacity="{a:.2f}"/>')
    last = pts[-1]
    rx = max(6, cur["sigma_g"] / (2 * R) * (w - pl - pr))
    ry = max(6, cur["sigma_i"] / (2 * R) * (h - pt - pb))
    s.append(f'<ellipse cx="{X(last["g"]):.1f}" cy="{Y(last["i"]):.1f}" rx="{rx:.1f}" ry="{ry:.1f}" fill="{ACCENT}" fill-opacity="0.12" stroke="{ACCENT}" stroke-dasharray="3 3"/>')
    s.append(f'<circle cx="{X(last["g"]):.1f}" cy="{Y(last["i"]):.1f}" r="6.5" fill="{INK}" stroke="{RAISED}" stroke-width="2"/>')
    s.append("</svg>")
    return "".join(s)


def svg_strip(D, months=180, w=700, h=64):
    hist = D["history"][-months:]
    bw = w / len(hist)
    s = [f'<svg viewBox="0 0 {w} {h}" class="chart" xmlns="http://www.w3.org/2000/svg">']
    for k, p in enumerate(hist):
        s.append(f'<rect x="{k * bw:.2f}" y="6" width="{bw + 0.3:.2f}" height="30" fill="{PC[p["p"]]}"/>')
    for k, p in enumerate(hist):
        if p["d"].endswith("-01") and int(p["d"][:4]) % 3 == 0:
            s.append(f'<line x1="{k * bw:.1f}" y1="36" x2="{k * bw:.1f}" y2="42" stroke="{FAINT}"/>')
            s.append(f'<text x="{k * bw:.1f}" y="54" class="tick" text-anchor="middle">{p["d"][:4]}</text>')
    s.append("</svg>")
    return "".join(s)


def svg_gi(D, months=180, w=700, h=190):
    hist = D["history"][-months:]
    n = len(hist)
    R = 3.0
    pl, pr, pt, pb = 34, 8, 8, 22
    X = lambda k: pl + k / (n - 1) * (w - pl - pr)
    Y = lambda v: pt + (R - max(-R, min(R, v))) / (2 * R) * (h - pt - pb)
    s = [f'<svg viewBox="0 0 {w} {h}" class="chart" xmlns="http://www.w3.org/2000/svg">']
    for v in (-2, -1, 0, 1, 2):
        s.append(f'<line x1="{pl}" y1="{Y(v):.1f}" x2="{w - pr}" y2="{Y(v):.1f}" stroke="{INK}" stroke-opacity="{0.5 if v == 0 else 0.08}"/>')
        s.append(f'<text x="{pl - 5}" y="{Y(v) + 3:.1f}" text-anchor="end" class="tick">{v:+d}σ</text>')
    for k, p in enumerate(hist):
        if p["d"].endswith("-01") and int(p["d"][:4]) % 3 == 0:
            s.append(f'<text x="{X(k):.1f}" y="{h - 7}" text-anchor="middle" class="tick">{p["d"][:4]}</text>')
    for key, col in (("g", POS), ("i", NEG)):
        d = " ".join(("M" if k == 0 else "L") + f"{X(k):.1f},{Y(p[key]):.1f}" for k, p in enumerate(hist))
        s.append(f'<path d="{d}" fill="none" stroke="{col}" stroke-width="1.8"/>')
    s.append("</svg>")
    return "".join(s)


def svg_zrows(items, w=330):
    """Barras divergentes de z-score; items = [(nombre, z, z_prev)]"""
    rh = 31
    h = rh * len(items) + 6
    cx = 190 + (w - 190 - 40) / 2
    half = (w - 190 - 40) / 2
    s = [f'<svg viewBox="0 0 {w} {h}" class="chart" xmlns="http://www.w3.org/2000/svg">',
         f'<line x1="{cx}" y1="0" x2="{cx}" y2="{h}" stroke="{INK}" stroke-opacity="0.3"/>']
    for k, (name, z, zp) in enumerate(items):
        y = 3 + k * rh
        bw = min(half, abs(z) / 3.0 * half)
        col = POS if z >= 0 else NEG
        x = cx if z >= 0 else cx - bw
        s.append(f'<text x="0" y="{y + 15}" class="rowl">{e(name[:34])}</text>')
        s.append(f'<rect x="{x:.1f}" y="{y + 5}" width="{max(1.5, bw):.1f}" height="12" rx="2" fill="{col}" opacity="0.88"/>')
        if zp is not None:
            px = cx + max(-3, min(3, zp)) / 3.0 * half
            s.append(f'<line x1="{px:.1f}" y1="{y + 3}" x2="{px:.1f}" y2="{y + 19}" stroke="{INK}" stroke-width="1.4" stroke-dasharray="2 2"/>')
        s.append(f'<text x="{w - 2}" y="{y + 15}" text-anchor="end" class="rowv">{num(z, 2, True)}</text>')
    s.append("</svg>")
    return "".join(s)


def svg_lines(series, w=700, h=300, recs=None, labels=None):
    """series: lista de (nombre, color, [valores acumulados]) con eje log."""
    n = len(series[0][2])
    allv = [v for _, _, vs in series for v in vs if v and v > 0]
    lo, hi = min(allv), max(allv)
    lg0, lg1 = math.log10(lo) - 0.02, math.log10(hi) + 0.05
    pl, pr, pt, pb = 52, 12, 10, 26
    X = lambda k: pl + k / (n - 1) * (w - pl - pr)
    Y = lambda v: pt + (lg1 - math.log10(max(v, lo))) / (lg1 - lg0) * (h - pt - pb)
    s = [f'<svg viewBox="0 0 {w} {h}" class="chart" xmlns="http://www.w3.org/2000/svg">']
    for a, b in (recs or []):
        s.append(f'<rect x="{X(a):.1f}" y="{pt}" width="{max(1.5, X(b) - X(a)):.1f}" height="{h - pt - pb}" fill="{INK}" opacity="0.06"/>')
    ticks = [m * 10 ** k for k in range(int(math.floor(lg0)) - 1, int(math.ceil(lg1)) + 1) for m in (1, 1.5, 2, 3, 5, 7)]
    ticks = [v for v in ticks if lg0 <= math.log10(v) <= lg1]
    for v in ticks:
        s.append(f'<line x1="{pl}" y1="{Y(v):.1f}" x2="{w - pr}" y2="{Y(v):.1f}" stroke="{INK}" stroke-opacity="0.12"/>')
        s.append(f'<text x="{pl - 6}" y="{Y(v) + 3:.1f}" text-anchor="end" class="tick">{v:,.0f}</text>')
    for k, lab in (labels or []):
        s.append(f'<text x="{X(k):.1f}" y="{h - 8}" text-anchor="middle" class="tick">{lab}</text>')
    for name, col, vs in series:
        d = " ".join(("M" if i == 0 else "L") + f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(vs))
        s.append(f'<path d="{d}" fill="none" stroke="{col}" stroke-width="2" stroke-linejoin="round"/>')
    s.append("</svg>")
    return "".join(s)


def svg_bars(vals, w=700, h=150):
    """vals: [(etiqueta, valor)] barras divergentes (pp)"""
    n = len(vals)
    m = max(5.0, max(abs(v) for _, v in vals))
    pl, pr, pt, pb = 30, 6, 8, 22
    bw = (w - pl - pr) / n
    y0 = pt + (h - pt - pb) / 2
    sc = (h - pt - pb) / 2 / m
    s = [f'<svg viewBox="0 0 {w} {h}" class="chart" xmlns="http://www.w3.org/2000/svg">',
         f'<line x1="{pl}" y1="{y0}" x2="{w - pr}" y2="{y0}" stroke="{INK}" stroke-opacity="0.4"/>']
    for g in (-m, m):
        s.append(f'<text x="{pl - 5}" y="{y0 - g * sc + 3:.1f}" text-anchor="end" class="tick">{g:+.0f}</text>')
    for k, (lab, v) in enumerate(vals):
        x = pl + k * bw + 1.5
        hh = abs(v) * sc
        s.append(f'<rect x="{x:.1f}" y="{(y0 - hh) if v >= 0 else y0:.1f}" width="{max(2, bw - 3):.1f}" height="{max(1, hh):.1f}" fill="{POS if v >= 0 else NEG}" opacity="0.9"/>')
        if k % 2 == 0:
            s.append(f'<text x="{x + bw / 2 - 1.5:.1f}" y="{h - 7}" text-anchor="middle" class="tick">{str(lab)[2:]}</text>')
    s.append("</svg>")
    return "".join(s)


def svg_donut(rows, size=190):
    tot = sum(r[1] for r in rows) or 1
    cx = cy = size / 2
    r0, r1 = size * 0.30, size * 0.48
    s = [f'<svg viewBox="0 0 {size} {size}" class="chart" xmlns="http://www.w3.org/2000/svg">']
    a = -math.pi / 2
    pal = ["#3F6B52", "#B8863B", "#3E4E7A", "#9C4A3C", "#6E8B74", "#D2A760", "#7E8CB5", "#C58B80"]
    for k, (name, wgt) in enumerate(rows):
        da = wgt / tot * 2 * math.pi
        b = a + da
        large = 1 if da > math.pi else 0
        p = (f"M{cx + r1 * math.cos(a):.2f},{cy + r1 * math.sin(a):.2f} "
             f"A{r1},{r1} 0 {large} 1 {cx + r1 * math.cos(b):.2f},{cy + r1 * math.sin(b):.2f} "
             f"L{cx + r0 * math.cos(b):.2f},{cy + r0 * math.sin(b):.2f} "
             f"A{r0},{r0} 0 {large} 0 {cx + r0 * math.cos(a):.2f},{cy + r0 * math.sin(a):.2f} Z")
        s.append(f'<path d="{p}" fill="{pal[k % len(pal)]}" stroke="{RAISED}" stroke-width="2"/>')
        a = b
    s.append("</svg>")
    return "".join(s), pal


def svg_gauge(p, w=220, h=130):
    cx, cy, r = w / 2, h - 18, 84
    def pt(f):
        ang = math.pi * (1 - f)
        return cx + r * math.cos(ang), cy - r * math.sin(ang)
    s = [f'<svg viewBox="0 0 {w} {h}" class="chart" xmlns="http://www.w3.org/2000/svg">']
    zones = [(0, .15, POS), (.15, .35, ACCENT), (.35, 1, NEG)]
    for a, b, col in zones:
        x1, y1 = pt(a); x2, y2 = pt(b)
        s.append(f'<path d="M{x1:.1f},{y1:.1f} A{r},{r} 0 0 1 {x2:.1f},{y2:.1f}" fill="none" stroke="{col}" stroke-width="14" opacity="0.85"/>')
    nx, ny = pt(max(0.0, min(1.0, p)))
    s.append(f'<line x1="{cx}" y1="{cy}" x2="{cx + (nx - cx) * 0.86:.1f}" y2="{cy + (ny - cy) * 0.86:.1f}" stroke="{INK}" stroke-width="3" stroke-linecap="round"/>')
    s.append(f'<circle cx="{cx}" cy="{cy}" r="6" fill="{INK}"/>')
    s.append(f'<text x="{cx}" y="{cy - 28}" text-anchor="middle" class="gauge">{pct(p, 1)}</text>')
    s.append("</svg>")
    return "".join(s)


def cover_rings():
    s = ['<svg viewBox="0 0 600 600" class="rings" xmlns="http://www.w3.org/2000/svg">']
    for r in (80, 140, 200, 260, 320):
        s.append(f'<circle cx="300" cy="300" r="{r}" fill="none" stroke="{ACCENT}" stroke-opacity="{0.55 - r / 900:.2f}" stroke-width="1"/>')
    for k in range(48):
        a = k / 48 * 2 * math.pi
        r0, r1 = 320, 332 if k % 4 else 344
        s.append(f'<line x1="{300 + r0 * math.cos(a):.1f}" y1="{300 + r0 * math.sin(a):.1f}" x2="{300 + r1 * math.cos(a):.1f}" y2="{300 + r1 * math.sin(a):.1f}" stroke="{ACCENT}" stroke-opacity="0.5"/>')
    s.append(f'<line x1="300" y1="300" x2="300" y2="110" stroke="{ACCENT}" stroke-width="3" stroke-linecap="round"/>')
    s.append(f'<line x1="300" y1="300" x2="395" y2="345" stroke="{ACCENT}" stroke-opacity="0.8" stroke-width="2.4" stroke-linecap="round"/>')
    s.append(f'<circle cx="300" cy="300" r="9" fill="{ACCENT}"/></svg>')
    return "".join(s)


# ------------------------------------------------------------------ bloques HTML
def header(D, title, n, total_label):
    return (f'<div class="ph"><span>MARKET PULSE · RELOJ DE INVERSIÓN</span><span>{e(total_label)}</span></div>'
            f'<h2>{e(title)}</h2>')


def footer(n, note=""):
    return (f'<div class="pf"><span>{e(note)}</span><span>Página @@</span></div>')


def kpi(label, value, sub="", color=INK):
    return (f'<div class="kpi"><div class="kl">{e(label)}</div><div class="kv" style="color:{color}">{value}</div>'
            f'<div class="ks">{sub}</div></div>')


def sigma_text(v, label):
    if abs(v) < 0.05:
        return f"{label} está <b>en su tendencia</b> (≈0σ, justo en la frontera)"
    return f"{label} está <b>{num(abs(v), 2)}σ {'por encima' if v >= 0 else 'por debajo'}</b> de su tendencia"


def momentum_word(m, up, down):
    if m is None:
        return ""
    return up if m >= 0.10 else down if m <= -0.10 else "estable"


def next_phase(D):
    T = D["validation"]["transition"][D["current"]["phase"]]
    cand = sorted(((p, v) for p, v in T.items() if p != D["current"]["phase"]), key=lambda x: -x[1])
    return cand[0]


def scheme(D, key="rotation"):
    r = D[key]
    return r, r["schemes"][r["default"]]


def year_labels(sch, step):
    out = []
    for k, p in enumerate(sch["curve"]):
        if p["d"].endswith("-01") and int(p["d"][:4]) % step == 0:
            out.append((k, p["d"][:4]))
    return out


def rec_by_phase(D):
    v = D["validation"]
    n, sh = v["nber"], v["share"]
    out = {p: (n["phase_mix_in_recession"].get(p, 0) * n["share_recession_months"] / sh[p]) if sh[p] else 0 for p in PHASES}
    out["_now"] = sum(D["current"]["probs"][p] * out[p] for p in PHASES)
    return out


def curve_cum(sch):
    cs, cb = [100.0], [100.0]
    lab = []
    for k, p in enumerate(sch["curve"]):
        cs.append(cs[-1] * (1 + p["s"] / 100))
        cb.append(cb[-1] * (1 + (p["b"] or 0) / 100))
    return cs[1:], cb[1:]


def build_html(D, gen: datetime) -> str:
    cur = D["current"]
    ph = cur["phase"]
    alt = cur["alt_phase"]
    probs = cur["probs"]
    month_lbl = f"{MESES[gen.month - 1].capitalize()} {gen.year}"
    edge = cur.get("edge") or {}
    last_full = edge.get("last_full_month") or cur["date"]
    margin = cur["confidence"] * 100
    strength = cur.get("call_strength", "—")
    rec = cur.get("recession") or {}
    rot, sch = scheme(D)
    nxt, nxt_p = next_phase(D)
    mom = cur.get("momentum") or {}
    rows_probs = sorted(probs.items(), key=lambda x: -x[1])
    tag = f"{month_lbl} · último mes completo: {mes_label(last_full)}"

    pages = []

    # ---------------------------------------------------------------- 1 portada
    bars = "".join(
        f'<div class="cb"><span>{e(p)}</span><i><b style="width:{v * 100:.1f}%;background:{PC[p]}"></b></i><em>{pct(v, 1)}</em></div>'
        for p, v in rows_probs)
    pages.append(f'''
<section class="page cover">
  {cover_rings()}
  <div class="cv-top"><span>MARKET PULSE</span><span>{e(month_lbl.upper())}</span></div>
  <div class="cv-mid">
    <div class="cv-eyebrow">INFORME MENSUAL · RELOJ DE INVERSIÓN</div>
    <h1>Dónde está el ciclo<br>y qué ha pagado<br>en cada fase</h1>
    <div class="cv-phase" style="--c:{PC[ph]}"><i></i><div><small>FASE VIGENTE · EE.UU.</small><b>{e(ph)}</b></div></div>
    <p class="cv-sub">{e(PHASE_ONE[ph])}</p>
    <div class="cv-bars">{bars}</div>
    <div class="cv-sig">Señal de fase: <b>{e(strength)}</b> · margen sobre {e(alt)}: <b>{num(margin, 1)} puntos</b></div>
  </div>
  <div class="cv-foot"><span>Clasificador por componentes principales sobre series de la Fed · backtest desde {e(sch["portfolio"]["from"][:4])}</span>
  <span>Generado el {gen.strftime("%d/%m/%Y")}</span></div>
</section>''')

    # ---------------------------------------------------------------- 2 resumen
    bullets = []
    bullets.append(f'La clasificación sitúa la economía en <b>{e(ph)}</b> con un {pct(probs[ph], 1)} de probabilidad, '
                   f'frente al {pct(probs[alt], 1)} de <b>{e(alt)}</b>: margen de {num(margin, 1)} puntos, señal <b>{e(strength.lower())}</b>.'
                   + (' Es prácticamente un empate: la lectura puede cambiar con el próximo dato.' if margin < 5 else ''))
    bullets.append(f'{sigma_text(cur["growth"], "El crecimiento")} ({momentum_word(mom.get("growth_3m"), "acelerando", "perdiendo fuerza")}). '
                   f'{sigma_text(cur["inflation"], "La inflación")} '
                   f'({momentum_word(mom.get("inflation_3m"), "subiendo", "cediendo")}).')
    rbp = rec_by_phase(D)
    bullets.append(f'Recesión: el modelo a 12 meses (curva de tipos y condiciones financieras) da <b>{pct(rec.get("prob_12m"), 1)}</b>; '
                   f'el propio reloj, con las probabilidades de fase de hoy, implica un <b>≈{pct(rbp["_now"], 0)}</b> de que este mes ya sea de recesión. '
                   f'Miden cosas distintas: ver página @@RISK@@.')
    pb = [r for r in sch["playbook"].get(ph, [])]
    names = ", ".join(f'{r["name"]} ({num(r["weight"], 0)}%)' for r in pb)
    bullets.append(f'Cartera de la fase en el backtest: <b>{e(names)}</b>.')
    bullets.append(f'Si la fase cambia, el histórico apunta más a menudo a <b>{e(nxt)}</b> ({pct(nxt_p, 0)} de las transiciones desde {e(ph)}).')
    rfd = D.get("rotation_fi")
    if rfd:
        pbfi = rfd["schemes"][rfd["default"]]["playbook"].get(ph, [])
        bullets.append("Renta fija (cartera aparte): <b>" + e(", ".join(f'{r["name"]} ({num(r["weight"], 0)}%)' for r in pbfi)) + "</b>.")
    li = "".join(f"<li>{b}</li>" for b in bullets)
    pages.append(f'''
<section class="page">{header(D, "Resumen ejecutivo", 2, tag)}
  <div class="two">
    <div>
      <p class="lead">{e(PHASE_ONE[ph])} {e(PHASE_HINT[ph].capitalize())}.</p>
      <ul class="keys">{li}</ul>
    </div>
    <figure class="card"><figcaption>Crecimiento × inflación · últimos 36 meses</figcaption>{svg_plane(D)}
      <p class="cap">Cada punto, un mes (más oscuro = más reciente). El halo discontinuo es el margen de error de la medición actual.</p></figure>
  </div>
  <div class="kpis">
    {kpi("Crecimiento", num(cur["growth"], 2, True) + "σ", "vs tendencia 10 años", PC[ph] if cur["growth"] >= 0 else NEG)}
    {kpi("Inflación", num(cur["inflation"], 2, True) + "σ", "vs tendencia 10 años", NEG if cur["inflation"] >= 0 else POS)}
    {kpi("Bloque adelantado", num(cur["leading"], 2, True) + "σ", "condiciones financieras, crédito, permisos", INK)}
    {kpi("Recesión 12m", pct(rec.get("prob_12m"), 1), "modelo logístico", ACCENT)}
  </div>
  {footer(2, "σ = desviaciones estándar robustas respecto a la tendencia de los últimos diez años.")}
</section>''')

    # ---------------------------------------------------------------- 3 ciclo
    dur = D["validation"]["duration_months"]
    share = D["validation"]["share"]
    T = D["validation"]["transition"]
    trans = "".join(
        "<tr><th>" + e(a) + "</th>" + "".join(
            f'<td style="background:{PC[b]}{int(20 + 150 * T[a][b]):02x}">{pct(T[a][b], 0)}</td>' for b in PHASES) + "</tr>"
        for a in PHASES)
    probbars = "".join(
        f'<div class="pb"><span>{e(p)}</span><i><b style="width:{v * 100:.1f}%;background:{PC[p]}"></b></i><em>{pct(v, 1)}</em></div>'
        for p, v in sorted(probs.items(), key=lambda x: PHASES.index(x[0])))
    ds = "".join(f'<tr><th><i style="background:{PC[p]}"></i>{e(p)}</th><td>{num(dur[p], 1)} meses</td><td>{pct(share[p], 0)}</td></tr>' for p in PHASES)
    pages.append(f'''
<section class="page">{header(D, "El ciclo: dónde estamos y cuánto suele durar", 3, tag)}
  <p class="lead">Cada mes se mide qué tan por encima o por debajo de su tendencia están el crecimiento y la inflación; de los dos signos sale una de las cuatro fases. Debajo, los últimos 15 años.</p>
  <figure class="card"><figcaption>Fases mes a mes · últimos 15 años</figcaption>{svg_strip(D)}
    <div class="legend">{"".join(f'<span><i style="background:{PC[p]}"></i>{e(p)}</span>' for p in PHASES)}</div></figure>
  <figure class="card"><figcaption>Crecimiento e inflación frente a su tendencia <small>σ · últimos 15 años</small></figcaption>{svg_gi(D)}
    <div class="legend"><span><i style="background:{POS}"></i>Crecimiento</span><span><i style="background:{NEG}"></i>Inflación</span></div></figure>
  <div class="two">
    <figure class="card"><figcaption>Probabilidad de cada fase hoy</figcaption>{probbars}
      <p class="cap">Probabilidad normal sobre la posición de los dos ejes y su incertidumbre de medición. Margen entre las dos primeras: {num(margin, 1)} puntos.</p></figure>
    <figure class="card"><figcaption>Duración y peso histórico</figcaption>
      <table class="mini"><thead><tr><th>Fase</th><th>Duración media</th><th>% del tiempo</th></tr></thead><tbody>{ds}</tbody></table>
      <p class="cap">Desde {e(D["meta"]["history_from"][:4])}. Orden habitual del ciclo: Recuperación → Sobrecalentamiento → Estanflación → Reflación; solo el {pct(D["validation"]["rotation"]["clockwise_share"], 0)} de los cambios sigue ese orden, así que no conviene darlo por seguro.</p></figure>
  </div>
  <figure class="card"><figcaption>Si la fase cambia, ¿hacia dónde?</figcaption>
      <table class="mini trans"><thead><tr><th>desde ↓ hacia →</th>{"".join(f'<th>{e(p)}</th>' for p in PHASES)}</tr></thead><tbody>{trans}</tbody></table>
      <p class="cap">Frecuencia histórica de cada transición mensual (la diagonal es “seguir igual”).</p></figure>
  {footer(3)}
</section>''')

    # ---------------------------------------------------------------- 4 indicadores
    ind = D["indicators"]
    def block(bk, title):
        items = [i for i in ind if i["block"] == bk]
        tot = sum(abs(i["loading"]) for i in items if i.get("loading") is not None) or 1
        items.sort(key=lambda i: -abs(i.get("loading") or 0))
        rows = [(f'{i["name"]} · {num(abs(i["loading"]) / tot * 100, 0)}%', i["z"], i.get("z_prev")) for i in items]
        pc = D["pca"].get(bk, {})
        return (f'<figure class="card"><figcaption>{e(title)} <small>{len(items)} series · el 1.er componente explica el {pct(pc.get("explained_var"), 0)}</small></figcaption>'
                f'{svg_zrows(rows)}</figure>')
    movers = sorted((i for i in ind if i.get("z_prev") is not None), key=lambda i: -abs(i["z"] - i["z_prev"]))[:6]
    mv = "".join(f'<tr><td>{e(i["name"])}</td><td class="r">{num(i["z_prev"], 2, True)}</td><td class="r">{num(i["z"], 2, True)}</td>'
                 f'<td class="r" style="color:{POS if i["z"] - i["z_prev"] >= 0 else NEG}">{num(i["z"] - i["z_prev"], 2, True)}</td></tr>' for i in movers)
    pages.append(f'''
<section class="page">{header(D, "Qué está empujando cada eje", 4, tag)}
  <p class="lead">Cada serie entra como z-score robusto frente a su propia historia reciente. El número tras el nombre es su peso dentro del bloque (suman 100%); la raya discontinua marca dónde estaba esa misma serie el mes anterior.</p>
  <div class="two">{block("growth", "Crecimiento")}{block("inflation", "Inflación")}</div>
  <div class="two">{block("leading", "Bloque adelantado")}
    <figure class="card"><figcaption>Mayores cambios frente al mes anterior</figcaption>
      <table class="mini"><thead><tr><th>Serie</th><th class="r">Mes anterior</th><th class="r">Ahora</th><th class="r">Δ (σ)</th></tr></thead><tbody>{mv}</tbody></table>
      <p class="cap">z-score: cuántas desviaciones robustas (mediana y MAD de 10 años) está la variación interanual de la serie respecto a lo normal reciente. Cada serie se alinea a la fecha en que de verdad se publicó.</p></figure></div>
  {footer(4, "Fuente: FRED (Reserva Federal de St. Louis).")}
</section>''')

    # ---------------------------------------------------------------- 5 qué comprar
    def playbook_card(phase, title, sch=sch):
        rows = [r for r in sch["playbook"].get(phase, [])]
        donut, pal = svg_donut([(r["name"], r["weight"]) for r in rows])
        lg = "".join(f'<div class="dl"><i style="background:{pal[k % len(pal)]}"></i><span>{e(r["name"])}</span><b>{num(r["weight"], 1)}%</b></div>' for k, r in enumerate(rows))
        mix = sch["sleeve_mix"].get(phase, {})
        mixs = " · ".join(f"{e(k)} {num(v, 0)}%" for k, v in mix.items())
        bp = sch["by_phase"].get(phase, {})
        bps = (f'En el histórico de esta fase la cartera rindió {num(bp.get("ann"), 1)}% anual frente a {num(bp.get("bench_ann"), 1)}% del mercado '
               f'(exceso sobre letras; {bp.get("n")} meses).') if bp else ""
        return (f'<figure class="card pbk" style="border-top:3px solid {PC[phase]}"><figcaption>{e(title)}: <b>{e(phase)}</b></figcaption>'
                f'<div class="donut">{donut}<div class="dls">{lg}</div></div><p class="cap">{mixs}</p><p class="cap">{bps}</p></figure>')
    tie = margin < 10
    def phase_rows_for(sc):
        out = ""
        for pp in PHASES:
            comp = ", ".join(f'{r["name"]} {num(r["weight"], 0)}%' for r in sc["playbook"].get(pp, []))
            bpp = sc["by_phase"].get(pp, {})
            out += (f'<tr class="{"hl" if pp == ph else ""}"><th><i style="background:{PC[pp]}"></i>{e(pp)}</th><td>{e(comp)}</td>'
                    f'<td class="r">{num(bpp.get("ann"), 1, True)}%</td><td class="r">{num(bpp.get("bench_ann"), 1, True)}%</td></tr>')
        return out
    phase_rows = phase_rows_for(sch)
    pages.append(f'''
<section class="page">{header(D, "Renta variable: qué comprar ahora", 5, tag)}
  <p class="lead">Cartera solo larga de renta variable por sectores (y oro como único seguro), con el reparto «{e(sch["label"])}». Cada mes elige los activos con mayor ventaja <i>en esa fase frente a su propia media</i>, contraída estadísticamente para no dejarse engañar por rachas cortas.</p>
  <div class="{'two' if tie else 'one'}">
    {playbook_card(ph, "Fase vigente")}
    {playbook_card(alt, "Escenario alternativo (empate técnico)") if tie else ""}
  </div>
  <figure class="card"><figcaption>La cartera en cada fase <small>pesos de cada sector · resaltada la fase vigente</small></figcaption>
    <table class="mini phs"><thead><tr><th>Fase</th><th>Composición</th><th class="r">Exceso anual de la cartera en la fase</th><th class="r">Mercado</th></tr></thead><tbody>{phase_rows}</tbody></table></figure>
  <div class="note"><b>Cómo leerlo.</b> La señal de fase es <b>{e(strength.lower())}</b>: {"con un margen tan estrecho conviene mirar las dos carteras a la vez y no apostar todo a una sola." if tie else "el margen es suficiente para posicionarse por la fase principal."}
  El backtest es walk-forward: cada mes usa solo datos disponibles hasta el mes anterior.</div>
  {footer(5, "No es asesoramiento financiero. Rentabilidades pasadas no garantizan resultados futuros.")}
</section>''')

    # ---------------------------------------------------------------- 6 subsectores
    sub = D.get("subsectors", {}).get("por_sector", {})
    hold = D.get("holdings", {}).get("por_subsector", {})
    cards = []
    for r in [x for x in sch["playbook"].get(ph, []) if x["sleeve"] == "Renta variable"]:
        items = (sub.get(r["name"]) or {}).get(ph) or []
        if not items:
            continue
        a = next((x for x in D["assets"] if x["name"] == r["name"]), None)
        sec = (a["phases"].get(ph) or {}) if a else {}
        secv = sec.get("ann_tot") if sec.get("ann_tot") is not None else sec.get("ann")
        trs = []
        for it in items[:6]:
            v = it.get("ann_tot") if it.get("ann_tot") is not None else it.get("ann")
            d = (v - secv) if (v is not None and secv is not None) else None
            comp = hold.get(it["name"]) or []
            ctx = ", ".join(c["ticker"] for c in comp[:3])
            trs.append(f'<tr><td>{e(it["name"])}<small>{e(ctx)}</small></td><td class="r">{num(v, 1)}%</td>'
                       f'<td class="r" style="color:{POS if (d or 0) >= 0 else NEG}">{num(d, 1, True) if d is not None else "—"}</td></tr>')
        cards.append(f'<figure class="card"><figcaption>{e(r["name"])} <small>en conjunto {num(secv, 1)}% anual en {e(ph)}</small></figcaption>'
                     f'<table class="mini"><thead><tr><th>Subsector <small>(empresas del ETF, contexto)</small></th><th class="r">Anual</th><th class="r">vs sector</th></tr></thead><tbody>{"".join(trs)}</tbody></table></figure>')
    cards_html = "".join(cards) or '<p class="cap">Sin desglose por subsectores en esta ejecución.</p>'
    pages.append(f'''
<section class="page">{header(D, "Renta variable: qué subsector pagó mejor", 6, tag)}
  <p class="lead">Dentro de cada sector elegido en {e(ph)}, qué línea de negocio ha rendido más en esa fase. Análisis <b>complementario</b>: no cambia la cartera. Los tickers son las mayores posiciones del ETF sectorial como contexto, <b>no una recomendación</b>: que un subsector rinda más no implica que esas empresas concretas lo hagan.</p>
  <div class="stack">{cards_html}</div>
  {footer(6, "Subsectores: 49 industrias de Ken French (códigos SIC). Rentabilidad anual = media mensual de la fase × 12, retorno total.")}
</section>''')

    # ---------------------------------------------------------------- 7 mapa de calor
    base = [a for a in D["assets"] if (a["class"] in ("Renta variable", "Oro") or a["name"] in ("Small caps", "Renta variable EE.UU. (mercado)"))
            and a["name"] != "Otros sectores"]
    base.sort(key=lambda a: -((a["phases"].get(ph) or {}).get("rel") or -99))
    tact = [a for a in (D.get("extended", {}).get("assets") or []) if a["name"] not in ("Europa (French)", "Norteamérica (French)", "Japón (French)")]
    tact.sort(key=lambda a: -((a["phases"].get(ph) or {}).get("rel") or -99))

    def heat_row(a, hl=False):
        cells = []
        for p in PHASES:
            c = a["phases"].get(p) or {}
            if c.get("rel") is None:
                cells.append('<td class="hm dim">—</td>')
            else:
                cells.append(f'<td class="hm {"cur" if p == ph else ""}" style="background:{diverge(c["rel"])}">{num(c["rel"], 1, True)}</td>')
        avg = a.get("uncond_ann_tot") if a.get("uncond_ann_tot") is not None else a.get("uncond_ann")
        nm = a["name"].replace(" (French)", "")
        return f'<tr class="{"hl" if hl else ""}"><th>{e(nm)}</th>{"".join(cells)}<td class="hm avg">{num(avg, 1)}%</td></tr>'

    hrows = "".join(heat_row(a) for a in base)
    trows = "".join(heat_row(a) for a in tact)
    sep = (f'<tr class="sep"><th colspan="6">Candidatos tácticos <small>activos fuera del universo base: tamaño, biotecnología, Asia, China y Japón</small></th></tr>' if tact else "")
    pages.append(f'''
<section class="page">{header(D, "Renta variable: qué ha pagado cada activo", 7, tag)}
  <p class="lead">Exceso anualizado, en puntos porcentuales, de cada activo en cada fase <i>frente a su propia media histórica</i>. La última columna es esa media: la rentabilidad anual total del activo en todo el periodo, para saber contra qué se compara cada casilla (un +10 sobre una media del 5% no es lo mismo que sobre una del 15%).</p>
  <table class="heat"><thead><tr><th>Activo (ordenado por la fase vigente)</th>{"".join(f'<th class="{"cur" if p == ph else ""}" style="border-bottom:3px solid {PC[p]}">{e(p)}</th>' for p in PHASES)}<th class="avgh">Media anual</th></tr></thead><tbody>{hrows}{sep}{trows}</tbody></table>
  <div class="note"><b>Cómo leerlo.</b> Verde: el activo rindió por encima de su media cuando el reloj marcaba esa fase; terracota, por debajo. El recuadro marca la fase vigente. Los candidatos tácticos son activos que no forman parte del universo base; se muestran todos para que veas también los que no aportan ventaja en ninguna fase.</div>
  {footer(7, "Ken French (sectores), FRED y ETF. Contrastes con errores estándar Newey-West.")}
</section>''')

    # ---------------------------------------------------------------- 8 backtest
    cs, cb = curve_cum(sch)
    n = len(cs)
    labels = year_labels(sch, 10)
    dates = [p["d"] for p in sch["curve"]]
    recs = []
    for a, b in D.get("nber", []):
        ia = next((k for k, d in enumerate(dates) if d >= a), None)
        ib = next((k for k, d in enumerate(dates) if d >= b), n - 1)
        if ia is not None and ia < n:
            recs.append((ia, ib))
    pf = sch["portfolio"]
    b100 = rot.get("bench_100eq", {})
    b6040 = rot.get("bench_6040", {})

    def mrow(name, o, bold=False):
        t = "b" if bold else "span"
        return (f'<tr><th><{t}>{e(name)}</{t}></th><td class="r">{num(tc(o), 1)}%</td><td class="r">{num(o.get("vol"), 1)}%</td>'
                f'<td class="r">{num(o.get("sharpe"), 2)}</td><td class="r">{num(o.get("maxdd"), 1)}%</td><td class="r">{num(o.get("worst12"), 1)}%</td></tr>')

    def diffs_of(sc, bn, last=26):
        a_, b_ = sc["annual"], bn
        ys = sorted(int(y) for y in a_ if (str(y) in b_ or y in b_))
        return [(y, a_.get(y, a_.get(str(y))) - b_.get(y, b_.get(str(y)))) for y in ys][-last:]

    schrows = "".join(mrow(v["label"], v["portfolio"], k == rot["default"]) for k, v in rot["schemes"].items())
    diffs = diffs_of(sch, rot.get("bench_annual", {}))
    bp_rows = "".join(
        f'<tr class="{"hl" if pp == ph else ""}"><th><i style="background:{PC[pp]}"></i>{e(pp)}</th><td class="r">{sch["by_phase"][pp]["n"]}</td>'
        f'<td class="r">{num(sch["by_phase"][pp]["ann"], 1, True)}%</td><td class="r">{num(sch["by_phase"][pp]["bench_ann"], 1, True)}%</td>'
        f'<td class="r" style="color:{POS if sch["by_phase"][pp]["edge"] >= 0 else NEG}">{num(sch["by_phase"][pp]["edge"], 1, True)} pp</td></tr>' for pp in PHASES)
    pages.append(f'''
<section class="page">{header(D, "Renta variable: backtest frente al mercado", 8, tag)}
  <div class="kpis">
    {kpi("Cartera rotada", num(tc(pf), 1) + "%", f"anual compuesto desde {e(pf['from'][:4])}", POS)}
    {kpi("Mercado EE.UU.", num(tc(b100), 1) + "%", f"Sharpe {num(b100.get('sharpe'), 2)} · vol {num(b100.get('vol'), 1)}%", INK)}
    {kpi("Sharpe cartera", num(pf.get("sharpe"), 2), f"vs {num(b100.get('sharpe'), 2)} del mercado", ACCENT)}
    {kpi("Caída máxima", num(pf.get("maxdd"), 1) + "%", f"mercado {num(b100.get('maxdd'), 1)}%", NEG)}
  </div>
  <figure class="card"><figcaption>Valor de 100 invertidos · escala logarítmica <small>zonas grises: recesiones NBER</small></figcaption>
    {svg_lines([("Cartera", ACCENT, cs), ("Mercado", INK, cb)], h=330, recs=recs, labels=labels)}
    <div class="legend"><span><i style="background:{ACCENT}"></i>Cartera rotada ({e(sch["label"])})</span><span><i style="background:{INK}"></i>Mercado EE.UU.</span></div></figure>
  <div class="two">
    <figure class="card"><figcaption>Diferencia anual frente al mercado <small>pp, últimos 26 años</small></figcaption>{svg_bars(diffs, w=340, h=190)}
      <p class="cap">Años en que la cartera supera al mercado: {sch["wins_years"]} de {sch["n_years"]}.</p></figure>
    <figure class="card"><figcaption>Los cuatro repartos internos</figcaption>
      <table class="mini"><thead><tr><th>Esquema</th><th class="r">Anual</th><th class="r">Vol</th><th class="r">Sharpe</th><th class="r">Caída</th><th class="r">Peor 12m</th></tr></thead><tbody>{schrows}{mrow("Mercado EE.UU.", b100)}{mrow("60/40 (referencia)", b6040)}</tbody></table></figure>
  </div>
  <figure class="card"><figcaption>Cómo le fue a la cartera en cada fase <small>exceso anualizado sobre letras del Tesoro</small></figcaption>
    <table class="mini"><thead><tr><th>Fase</th><th class="r">Meses</th><th class="r">Cartera</th><th class="r">Mercado</th><th class="r">Ventaja</th></tr></thead><tbody>{bp_rows}</tbody></table>
    <p class="cap">Walk-forward: cada mes se decide con datos hasta el mes anterior. Cifras anuales: retorno total compuesto; Sharpe y volatilidad sobre el exceso respecto a letras del Tesoro.</p></figure>
  {footer(8, "Sin costes de transacción ni impuestos. Rentabilidades pasadas no garantizan resultados futuros.")}
</section>''')

    # ---------------------------------------------------------------- 9 renta fija (3 páginas)
    rf = D.get("rotation_fi")
    if rf:
        sf = rf["schemes"][rf["default"]]
        pff = sf["portfolio"]
        bf = rf.get("bench_100eq", {})
        bf6 = rf.get("bench_6040", {})
        csf, cbf = curve_cum(sf)
        schf = "".join(mrow(v["label"], v["portfolio"], k == rf["default"]) for k, v in rf["schemes"].items())
        difff = diffs_of(sf, rf.get("bench_annual", {}), 22)
        phase_rows_fi = phase_rows_for(sf)
        bp_rows_fi = "".join(
            f'<tr class="{"hl" if pp == ph else ""}"><th><i style="background:{PC[pp]}"></i>{e(pp)}</th><td class="r">{sf["by_phase"][pp]["n"]}</td>'
            f'<td class="r">{num(sf["by_phase"][pp]["ann"], 1, True)}%</td><td class="r">{num(sf["by_phase"][pp]["bench_ann"], 1, True)}%</td>'
            f'<td class="r" style="color:{POS if sf["by_phase"][pp]["edge"] >= 0 else NEG}">{num(sf["by_phase"][pp]["edge"], 1, True)} pp</td></tr>' for pp in PHASES)
        # --- 9a qué comprar
        pages.append(f'''
<section class="page">{header(D, "Renta fija: qué comprar ahora", 9, tag)}
  <p class="lead">El reloj también ordena la renta fija: gobierno (Treasuries), crédito, protegidos de la inflación y liquidez. Es una cartera <b>aparte</b>, con su propio universo, su propio mercado de referencia y su propio backtest; nunca se mezcla con la de renta variable. Reparto: «{e(sf["label"])}».</p>
  <div class="{'two' if tie else 'one'}">
    {playbook_card(ph, "Fase vigente", sf)}
    {playbook_card(alt, "Escenario alternativo (empate técnico)", sf) if tie else ""}
  </div>
  <figure class="card"><figcaption>La cartera de renta fija en cada fase <small>resaltada la fase vigente</small></figcaption>
    <table class="mini phs"><thead><tr><th>Fase</th><th>Composición</th><th class="r">Exceso anual de la cartera en la fase</th><th class="r">Agregado de bonos</th></tr></thead><tbody>{phase_rows_fi}</tbody></table></figure>
  <div class="note"><b>Cómo leerlo.</b> Igual que en renta variable, cada mes se eligen los activos con mayor ventaja <i>en esa fase frente a su propia media</i>, con datos solo hasta el mes anterior. Aquí no se impone ninguna regla teórica sobre duración o crédito: se muestra lo que ha pagado cada fase en los datos (página siguiente) y la cartera sale de ahí.</div>
  {footer(9, "No es asesoramiento financiero. Rentabilidades pasadas no garantizan resultados futuros.")}
</section>''')
        # --- 9b qué ha pagado
        fi_assets = [x for x in D["assets"] if x["class"] in ("Renta fija", "Liquidez")]
        fi_assets.sort(key=lambda x: -((x["phases"].get(ph) or {}).get("rel") or -99))
        picks = {r["name"] for r in sf["playbook"].get(ph, [])}
        fi_rows = "".join(heat_row(x, hl=x["name"] in picks) for x in fi_assets)
        pages.append(f'''
<section class="page">{header(D, "Renta fija: qué ha pagado cada activo", 10, tag)}
  <p class="lead">Exceso anualizado, en puntos porcentuales, de cada activo de renta fija en cada fase <i>frente a su propia media histórica</i>. La última columna es esa media: la rentabilidad anual total del activo en todo el periodo, para saber contra qué se compara cada casilla.</p>
  <table class="heat"><thead><tr><th>Activo (ordenado por la fase vigente)</th>{"".join(f'<th class="{"cur" if p == ph else ""}" style="border-bottom:3px solid {PC[p]}">{e(p)}</th>' for p in PHASES)}<th class="avgh">Media anual</th></tr></thead><tbody>{fi_rows}</tbody></table>
  <div class="note"><b>Cómo leerlo.</b> Verde: el activo rindió por encima de su media cuando el reloj marcaba esa fase; terracota, por debajo. El recuadro marca la fase vigente y las filas resaltadas son las que componen hoy la cartera de renta fija. Los activos marcados «aprox.» se reconstruyen a partir de rendimientos de FRED; el resto son ETF reales con menos historia.</div>
  {footer(10, "FRED, ETF y Ken French. Contrastes con errores estándar Newey-West.")}
</section>''')
        # --- 9c backtest
        pages.append(f'''
<section class="page">{header(D, "Renta fija: backtest frente al agregado", 11, tag)}
  <div class="kpis">
    {kpi("Cartera rotada", num(tc(pff), 1) + "%", f"anual compuesto desde {e(pff['from'][:4])}", POS)}
    {kpi("Agregado de bonos", num(tc(bf), 1) + "%", f"Sharpe {num(bf.get('sharpe'), 2)}", INK)}
    {kpi("Sharpe cartera", num(pff.get("sharpe"), 2), "rentabilidad / riesgo", ACCENT)}
    {kpi("Caída máxima", num(pff.get("maxdd"), 1) + "%", f"agregado {num(bf.get('maxdd'), 1)}%", NEG)}
  </div>
  <figure class="card"><figcaption>Valor de 100 invertidos · escala logarítmica</figcaption>{svg_lines([("Cartera", ACCENT, csf), ("Agregado", INK, cbf)], h=300, labels=year_labels(sf, 5))}
    <div class="legend"><span><i style="background:{ACCENT}"></i>Cartera rotada de renta fija</span><span><i style="background:{INK}"></i>Agregado de renta fija EE.UU.</span></div></figure>
  <div class="two">
    <figure class="card"><figcaption>Diferencia anual frente al agregado <small>pp</small></figcaption>{svg_bars(difff, w=340, h=190)}
      <p class="cap">Años en que la cartera supera al agregado: {sf["wins_years"]} de {sf["n_years"]}.</p></figure>
    <figure class="card"><figcaption>Cómo le fue a la cartera en cada fase <small>exceso anualizado</small></figcaption>
      <table class="mini"><thead><tr><th>Fase</th><th class="r">Meses</th><th class="r">Cartera</th><th class="r">Agregado</th><th class="r">Ventaja</th></tr></thead><tbody>{bp_rows_fi}</tbody></table></figure>
  </div>
  <figure class="card"><figcaption>Los cuatro repartos internos</figcaption>
    <table class="mini"><thead><tr><th>Esquema</th><th class="r">Anual</th><th class="r">Vol</th><th class="r">Sharpe</th><th class="r">Caída</th><th class="r">Peor 12m</th></tr></thead><tbody>{schf}{mrow("Agregado renta fija", bf)}{mrow("60/40 (referencia)", bf6) if bf6 else ""}</tbody></table></figure>
  <p class="cap">Renta fija desde 2003. Cifras anuales: retorno total compuesto; Sharpe y volatilidad sobre el exceso respecto a letras del Tesoro. Walk-forward, sin costes ni impuestos.</p>
  {footer(11, "Renta fija desde 2003 (ETF reales y rendimientos de FRED convertidos a retorno sintético).")}
</section>''')

    # ---------------------------------------------------------------- 10 riesgos y calidad
    nb = D["validation"]["nber"]
    warn = D["meta"].get("warnings") or []
    rbp = rec_by_phase(D)
    rec_rows = "".join(f'<tr><th><i style="background:{PC[pp]}"></i>{e(pp)}</th><td class="r">{pct(D["validation"]["share"][pp], 0)}</td><td class="r">{pct(nb["phase_mix_in_recession"][pp], 0)}</td><td class="r"><b>{pct(rbp[pp], 0)}</b></td></tr>' for pp in PHASES)
    pages.append(f'''
<section class="page">{header(D, "Riesgos, calidad del modelo y límites", 10, tag)}
  <div class="two">
    <figure class="card"><figcaption>Probabilidad de recesión a 12 meses</figcaption>{svg_gauge(rec.get("prob_12m") or 0)}
      <p class="cap">Modelo logístico con {e(", ".join(rec.get("features", [])))} (curva de tipos y condiciones financieras). AUC {num(rec.get("auc"), 2)} (0,5 = azar, 1 = perfecto), {rec.get("n_obs")} observaciones.</p></figure>
    <figure class="card"><figcaption>¿Y por qué no coincide con la fase?</figcaption>
      <table class="mini"><thead><tr><th>Fase</th><th class="r">% del tiempo</th><th class="r">% de las recesiones</th><th class="r">% de sus meses en recesión</th></tr></thead><tbody>{rec_rows}</tbody></table>
      <p class="cap">El 75% de recesiones en Estanflación responde a «si hay recesión, ¿en qué fase estaba?». Lo que importa hoy es la pregunta inversa: Estanflación ocupa el {pct(D["validation"]["share"]["Estanflación"], 0)} del tiempo y la recesión solo el {pct(nb["share_recession_months"], 1)}, así que solo el {pct(rbp["Estanflación"], 0)} de los meses en Estanflación fueron recesión.</p></figure>
  </div>
  <div class="note"><b>Lectura conjunta.</b> Con las probabilidades de fase de hoy, el reloj implica un ≈{pct(rbp["_now"], 0)} de que este mes sea de recesión (mezcla de Estanflación y Reflación); el modelo de recesión mira a 12 meses y solo usa curva de tipos y condiciones financieras, que ahora no dan alarma, y por eso marca {pct(rec.get("prob_12m"), 1)}. Son señales distintas y conviene leerlas juntas: actividad hoy frente a tensión financiera por delante.</div>
  <div class="three" style="margin-top:12px">
    <figure class="card"><figcaption>¿Ve el clasificador las recesiones?</figcaption>
      <table class="mini"><tbody><tr><th>Meses de recesión con crecimiento negativo</th><td class="r">{pct(nb["recall"], 0)}</td></tr>
      <tr><th>Meses de expansión con crecimiento positivo</th><td class="r">{pct(nb["specificity"], 0)}</td></tr>
      <tr><th>Meses de recesión NBER en la muestra</th><td class="r">{pct(nb["share_recession_months"], 1)}</td></tr></tbody></table>
      <p class="cap">Contraste con las fechas oficiales del NBER, que el modelo nunca ve.</p></figure>
    <figure class="card"><figcaption>Calidad de los datos</figcaption>
      <table class="mini"><tbody><tr><th>Series macro cargadas</th><td class="r">{D["meta"]["series_ok"]}/{D["meta"]["series_total"]}</td></tr>
      <tr><th>Activos cargados</th><td class="r">{D["meta"]["assets_ok"]}/{D["meta"]["assets_tried"]}</td></tr>
      <tr><th>Histórico desde</th><td class="r">{e(D["meta"]["history_from"])}</td></tr>
      <tr><th>Último mes completo</th><td class="r">{e(mes_label(last_full))}</td></tr>
      <tr><th>Avisos de la ejecución</th><td class="r">{len(warn)}</td></tr></tbody></table>
      <p class="cap">El último mes se estima con la información disponible (nowcast).</p></figure>
    <figure class="card"><figcaption>Estabilidad de la señal</figcaption>
      <table class="mini"><tbody><tr><th>Señal actual</th><td class="r">{e(strength)}</td></tr>
      <tr><th>Margen 1.ª vs 2.ª fase</th><td class="r">{num(margin, 1)} pp</td></tr>
      <tr><th>Cambios de fase en el histórico</th><td class="r">{D["validation"]["rotation"]["n_transitions"]}</td></tr></tbody></table>
      <p class="cap">Con margen pequeño, un solo dato puede cambiar la fase.</p></figure>
  </div>
  <div class="note"><b>Límites que conviene tener presentes</b>
    <ul>
      <li><b>Fase fronteriza.</b> Con crecimiento ≈ 0σ la fase puede cambiar de un mes a otro; la señal “{e(strength.lower())}” lo refleja.</li>
      <li><b>Mejora observada, no garantía.</b> Las variantes del modelo (más series, más activos, otras ventanas) se aceptaron o rechazaron sobre la misma muestra; las rechazadas empeoraban el Sharpe.</li>
      <li><b>Sectores no son empresas.</b> Que un sector o subsector rinda más en una fase no implica que una compañía concreta lo haga.</li>
      <li><b>Sin costes ni impuestos</b> en el backtest; rentabilidades pasadas no garantizan resultados futuros.</li>
    </ul></div>
  {footer(10)}
</section>''')

    # ---------------------------------------------------------------- 11 metodología
    pages.append(f'''
<section class="page">{header(D, "Metodología, fuentes y aviso legal", 11, tag)}
  <div class="two meth">
    <div>
      <h3>Cómo se construye</h3>
      <ol>
        <li><b>Dos ejes.</b> Crecimiento e inflación se miden con {sum(1 for i in ind if i["block"] in ("growth", "inflation"))} series de FRED, estandarizadas con z-score robusto sobre 10 años móviles y alineadas a su fecha real de publicación. El peso de cada serie sale del primer componente principal (PCA).</li>
        <li><b>Cuatro fases</b> según el signo de cada eje; la probabilidad de cada una usa la distribución normal con la incertidumbre de medición.</li>
        <li><b>Evidencia por activo y fase.</b> Exceso anualizado frente a la propia media, errores Newey-West, corrección de falsos descubrimientos y contracción James-Stein; cada casilla recibe una etiqueta de fiabilidad.</li>
        <li><b>Cartera.</b> Cada mes, con datos hasta el mes anterior, se eligen los activos de mayor ventaja esperada en la mezcla de fases ponderada por probabilidad, con bandas de peso por bloque. Se publican cuatro formas de repartir el peso.</li>
        <li><b>Tests de ampliación.</b> Series PCA adicionales, nuevos activos, criterio de nivel absoluto y semivida de los datos solo se adoptan si mejoran el Sharpe en al menos 3 de 4 esquemas sin bajar el CAGR más de 0,05 puntos.</li>
      </ol>
    </div>
    <div>
      <h3>Fuentes</h3>
      <p>FRED (Reserva Federal de St. Louis): macro, tipos, crédito y recesiones NBER. Kenneth R. French Data Library: sectores y 49 industrias de EE.UU. desde 1970. ETF de SPDR y otros emisores vía Yahoo Finance/Stooq para el tramo reciente y activos con poca historia. Composición de ETF sectoriales: State Street.</p>
      <h3>Glosario rápido</h3>
      <p><b>σ</b>: desviaciones estándar. <b>CAGR</b>: rentabilidad anual compuesta. <b>Sharpe</b>: rentabilidad por unidad de riesgo (sobre el exceso respecto a letras). <b>Caída máxima</b>: mayor pérdida de pico a valle. <b>pp</b>: puntos porcentuales. <b>AUC</b>: capacidad de un modelo para separar casos (0,5 = azar).</p>
      <h3>Aviso legal</h3>
      <p class="legal">Este informe es un análisis cuantitativo automático con fines informativos y educativos. No constituye asesoramiento de inversión, recomendación personalizada ni oferta de compra o venta de ningún instrumento. Los resultados históricos y los backtests no garantizan resultados futuros. Verifique siempre la información antes de tomar decisiones de inversión.</p>
      <p class="cap">Generado el {gen.strftime("%d/%m/%Y %H:%M")} UTC a partir de docs/data/data.json (ejecución de {e(D["meta"]["generated_utc"])}).</p>
    </div>
  </div>
  {footer(11)}
</section>''')

    risk_idx = next((k for k, pg in enumerate(pages, 1) if "Riesgos, calidad del modelo" in pg), 0)
    out_pages = []
    for k, pg in enumerate(pages, 1):
        pg = pg.replace("Página @@", f"Página {k}").replace("@@RISK@@", str(risk_idx))
        sec = ("RENTA VARIABLE" if "<h2>Renta variable" in pg else "RENTA FIJA" if "<h2>Renta fija" in pg else "")
        if sec:
            pg = pg.replace("MARKET PULSE · RELOJ DE INVERSIÓN", f"MARKET PULSE · {sec}", 1)
        out_pages.append(pg)
    pages = out_pages
    return TEMPLATE.replace("{{BODY}}", "".join(pages)).replace("{{TITLE}}", f"Market Pulse · {month_lbl}")


TEMPLATE = """<!DOCTYPE html><html lang="es"><head><meta charset="utf-8"><title>{{TITLE}}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,600;0,9..144,700;1,9..144,500&family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
@page{size:A4;margin:0}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{background:#F6F2E8;color:#1B1810;font-family:Inter,"Helvetica Neue",Arial,sans-serif;font-size:10.4pt;line-height:1.55;-webkit-print-color-adjust:exact;print-color-adjust:exact}
.page{width:210mm;height:297mm;padding:15mm 15mm 17mm;position:relative;page-break-after:always;overflow:hidden;background:#F6F2E8}
.page:last-child{page-break-after:auto}
.ph{display:flex;justify-content:space-between;font:600 6.6pt "IBM Plex Mono",monospace;letter-spacing:.14em;color:#8C8268;border-bottom:1.4px solid #A9752C;padding-bottom:5px;margin-bottom:12px}
h2{font:600 22pt Fraunces,Georgia,serif;letter-spacing:-.01em;margin:0 0 8px;color:#1B1810;line-height:1.1}
h3{font:600 11pt Fraunces,Georgia,serif;margin:12px 0 4px}
.lead{font-size:11pt;color:#322C1F;margin:0 0 12px;line-height:1.55}
.cap{font-size:8.2pt;color:#5B5340;margin:6px 0 0;line-height:1.4}
.pf{position:absolute;left:15mm;right:15mm;bottom:8mm;display:flex;justify-content:space-between;font:500 6.4pt "IBM Plex Mono",monospace;color:#8C8268;border-top:1px solid rgba(27,24,16,.14);padding-top:5px}
.two{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-bottom:12px}
.three{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-bottom:12px}
.one{display:block;margin-bottom:12px}
.stack{display:grid;gap:12px}
.card{margin:0 0 12px;background:#FBF9F3;border:1px solid rgba(27,24,16,.1);border-radius:6px;padding:11px 12px;box-shadow:0 1px 2px rgba(27,24,16,.04)}
.two .card,.three .card{margin-bottom:0}
.card figcaption{font:600 9.4pt Fraunces,Georgia,serif;margin:0 0 8px;color:#1B1810}
.card figcaption small{font:400 6.6pt Inter,sans-serif;color:#8C8268;margin-left:4px}
.chart{width:100%;height:auto;display:block}
.chart text{font-family:"IBM Plex Mono",monospace}
.qlab{font-size:8px;font-weight:600;letter-spacing:.1em}
.tick{font-size:8px;fill:#8C8268}.axl{font-size:8px;fill:#5B5340;letter-spacing:.14em}
.rowl{font:500 8.3px Inter,sans-serif!important;fill:#322C1F}.rowv{font-size:8.5px;fill:#5B5340}
.gauge{font:600 20px Fraunces,serif!important;fill:#1B1810}
.keys{margin:0;padding-left:16px}.keys li{margin:0 0 11px;line-height:1.5}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:2px 0 12px}
.kpi{background:#FBF9F3;border:1px solid rgba(27,24,16,.1);border-top:3px solid #A9752C;border-radius:6px;padding:9px 11px}
.kl{font:500 6.4pt "IBM Plex Mono",monospace;letter-spacing:.12em;text-transform:uppercase;color:#8C8268}
.kv{font:600 20pt Fraunces,Georgia,serif;line-height:1.15;margin:2px 0}
.ks{font-size:7pt;color:#5B5340}
.legend{display:flex;flex-wrap:wrap;gap:12px;font-size:7.4pt;color:#5B5340;margin-top:6px}
.legend i,.mini th i{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:5px;vertical-align:-1px}
.pb,.cb{display:grid;grid-template-columns:96px 1fr 44px;align-items:center;gap:8px;margin:10px 0;font-size:8.8pt}
.pb i,.cb i{display:block;height:9px;background:rgba(27,24,16,.08);border-radius:5px;overflow:hidden}
.pb b,.cb b{display:block;height:100%;border-radius:5px}
.pb em,.cb em{font:500 8pt "IBM Plex Mono",monospace;font-style:normal;text-align:right}
table.mini{width:100%;border-collapse:collapse;font-size:8.8pt}
table.mini th,table.mini td{padding:5px 5px;border-bottom:1px solid rgba(27,24,16,.08);text-align:left;font-weight:400;vertical-align:top}
table.mini thead th{font:500 6.2pt "IBM Plex Mono",monospace;letter-spacing:.06em;text-transform:uppercase;color:#8C8268;border-bottom:1.2px solid rgba(27,24,16,.25)}
table.mini th small,table.mini td small{display:block;font-size:6.4pt;color:#8C8268;font-weight:400}
table.mini th b{font-weight:600}
.r{text-align:right!important;font-family:"IBM Plex Mono",monospace}
table.trans{font-size:7.4pt!important}table.trans th{padding:4px 2px!important}table.trans td{text-align:center;font:500 7pt "IBM Plex Mono",monospace;color:#1B1810}
table.trans thead th{text-align:center}
.donut{display:flex;align-items:center;gap:14px}.donut svg{width:170px;flex:none}
.two .donut svg{width:118px}.two .donut{gap:10px}.dls{flex:1;min-width:0}.dl{display:grid;grid-template-columns:12px 1fr auto;gap:7px;align-items:center;padding:6px 0;border-bottom:1px solid rgba(27,24,16,.08);font-size:9.2pt}
.dl i{width:10px;height:10px;border-radius:2px}.dl b{font:600 8.4pt "IBM Plex Mono",monospace}
.note{background:#EEE6D2;border-left:3px solid #A9752C;border-radius:3px;padding:10px 13px;font-size:9.2pt;line-height:1.5}
.note ul{margin:5px 0 0;padding-left:16px}.note li{margin:3px 0}
table.heat{width:100%;border-collapse:collapse;font-size:9pt;margin-bottom:10px}
table.heat th,table.heat td{padding:6.5px 7px;border-bottom:1px solid rgba(27,24,16,.07)}
table.heat thead th{font:500 6.6pt "IBM Plex Mono",monospace;letter-spacing:.05em;text-transform:uppercase;text-align:center;color:#322C1F;padding-bottom:6px}
td.avg{background:#EEE6D2;font-weight:600}th.avgh{background:#EEE6D2}
table.heat tr.sep th{background:#1B1810;color:#F6F2E8;text-align:left;font:600 7.4pt "IBM Plex Mono",monospace;letter-spacing:.08em;text-transform:uppercase;padding:6px 8px}
table.heat tr.sep small{font:400 6.8pt Inter,sans-serif;text-transform:none;letter-spacing:0;color:#C9A56B;margin-left:6px}
tr.hl td,tr.hl th{background:rgba(169,117,44,.13)}
table.heat thead th:first-child{text-align:left}
table.heat tbody th{text-align:left;font-weight:500}
td.hm{text-align:center;font:500 8pt "IBM Plex Mono",monospace;position:relative}
td.hm.cur{box-shadow:inset 0 0 0 1.3px rgba(27,24,16,.55)}td.dim{color:#8C8268}
.rb{display:inline-block;font:700 5.8pt "IBM Plex Mono",monospace;margin-left:4px;padding:0 3px;border-radius:2px;vertical-align:1px;font-style:normal}
.rbF{background:#3F6B52;color:#fff}.rbM{background:#B8863B;color:#fff}.rbD{background:rgba(27,24,16,.14);color:#5B5340}
.meth h3{margin-top:0}.meth ol{padding-left:16px;margin:4px 0}.meth li{margin:0 0 9px;font-size:9.6pt}.meth p{font-size:9.6pt;margin:0 0 6px}
.legal{font-size:7.6pt!important;color:#5B5340}
/* portada */
.cover{background:#1B1810;color:#F6F2E8;padding:0}
.cover .rings{position:absolute;right:-170px;top:90px;width:640px;opacity:.9}
.cv-top{position:absolute;top:15mm;left:15mm;right:15mm;display:flex;justify-content:space-between;font:600 8pt "IBM Plex Mono",monospace;letter-spacing:.22em;color:#A9752C}
.cv-mid{position:absolute;left:15mm;right:15mm;top:78mm}
.cv-eyebrow{font:500 8pt "IBM Plex Mono",monospace;letter-spacing:.2em;color:#C9A56B;margin-bottom:12px}
.cover h1{font:500 38pt Fraunces,Georgia,serif;line-height:1.05;letter-spacing:-.02em;margin:0 0 26px;color:#FBF9F3;max-width:120mm}
.cv-phase{display:flex;align-items:center;gap:14px;margin:0 0 10px}
.cv-phase i{width:10px;height:52px;background:var(--c);border-radius:3px}
.cv-phase small{display:block;font:500 7pt "IBM Plex Mono",monospace;letter-spacing:.18em;color:#C9A56B}
.cv-phase b{font:600 28pt Fraunces,Georgia,serif;color:var(--c);filter:brightness(1.55) saturate(1.1)}
.cv-sub{font-size:10.4pt;max-width:105mm;color:#D9D0BA;margin:0 0 26px}
.cv-bars{max-width:118mm}.cv-bars .cb{grid-template-columns:104px 1fr 46px;font-size:8.6pt;color:#EEE6D2}
.cv-bars .cb i{background:rgba(246,242,232,.14)}
.cv-sig{margin-top:18px;font-size:9pt;color:#D9D0BA;border-top:1px solid rgba(201,165,107,.4);padding-top:10px;max-width:118mm}
.cv-foot{position:absolute;left:15mm;right:15mm;bottom:12mm;display:flex;justify-content:space-between;font:500 6.6pt "IBM Plex Mono",monospace;color:#8C8268;letter-spacing:.04em}
</style></head><body>{{BODY}}</body></html>"""


# ------------------------------------------------------------------ render
def render_pdf(html_text: str, out: Path) -> None:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.set_content(html_text, wait_until="load")
        try:
            pg.wait_for_load_state("networkidle", timeout=15000)
            pg.evaluate("document.fonts.ready")
        except Exception:
            pass
        pg.wait_for_timeout(500)
        # Ajuste de relleno: cada página interior se escala (zoom) para ocupar el alto útil,
        # sin pasarse (máx. x1,45) y encogiéndose si el contenido desborda.
        pg.evaluate("""() => {
          const avail = 297 * 3.7795 - (14.5 + 17) * 3.7795;
          document.querySelectorAll('.page:not(.cover)').forEach(pgEl => {
            const foot = pgEl.querySelector('.pf');
            const wrap = document.createElement('div'); wrap.className = 'pc';
            [...pgEl.children].forEach(c => { if (c !== foot) wrap.appendChild(c); });
            pgEl.insertBefore(wrap, foot);
            let z = 1;
            for (let i = 0; i < 4; i++) {
              wrap.style.zoom = z;
              const h = wrap.getBoundingClientRect().height;
              const nz = Math.max(0.8, Math.min(1.45, z * avail / h));
              if (Math.abs(nz - z) < 0.002) break;
              z = nz;
            }
            wrap.style.zoom = z * 0.985;
          });
        }""")
        pg.wait_for_timeout(300)
        pg.pdf(path=str(out), format="A4", print_background=True, prefer_css_page_size=True)
        b.close()


def main() -> int:
    force = "--force" in sys.argv
    D = json.loads(DATA.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    OUT.mkdir(parents=True, exist_ok=True)
    meta_f = OUT / "meta.json"
    ym = f"{now.year}-{now.month:02d}"
    if not force and meta_f.exists() and (OUT / "market-pulse.pdf").exists():
        m = json.loads(meta_f.read_text())
        age = (now - datetime.fromisoformat(m["generated"])).days
        if m.get("month") == ym and m.get("phase") == D["current"]["phase"] and m.get("scheme") == D["rotation"]["default"] and age < 7:
            print("Informe al día (mismo mes y fase, <7 días): no se regenera.")
            return 0
    page = build_html(D, now)
    if "--html-only" in sys.argv:
        (OUT / "preview.html").write_text(page, encoding="utf-8")
        print("HTML escrito en", OUT / "preview.html")
        return 0
    render_pdf(page, OUT / "market-pulse.pdf")
    (OUT / f"market-pulse-{ym}.pdf").write_bytes((OUT / "market-pulse.pdf").read_bytes())
    meta_f.write_text(json.dumps({"generated": now.isoformat(), "month": ym, "phase": D["current"]["phase"], "scheme": D["rotation"]["default"]}))
    print("Informe generado:", OUT / "market-pulse.pdf")
    return 0


if __name__ == "__main__":
    sys.exit(main())
