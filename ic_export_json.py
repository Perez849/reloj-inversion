#!/usr/bin/env python3
"""
ic_export_json.py — Exporta el estado actual del Reloj de la Inversión a JSON
para ser consumido por la web estática en GitHub Pages.

Reutiliza TODA la lógica de investment_clock.py:
  - download_all()       descarga FRED
  - calculate_metrics()  calcula los 28 indicadores
  - compute_percentiles()
  - train_model()        entrena/carga el modelo logístico
  - select_engine()      decide motor logístico vs tradicional
  - score_dual()         scoring adelantados vs coincidentes
  - calculate_momentum()
  - generate_interpretation()

Genera: data.json  (en la carpeta docs/ para GitHub Pages)
"""
import os, sys, json, math
from datetime import datetime
import numpy as np

# Import del módulo principal (debe estar en la misma carpeta)
try:
    from investment_clock import (
        download_all, calculate_metrics, compute_percentiles,
        train_model, select_engine, score_dual, score_phase,
        calculate_momentum, generate_interpretation,
        FEATURES, INT_PHASE, PHASE_INT,
        FIXED_INCOME_RECS, EQUITY_RECS,
        INDICATORS,
    )
except ImportError as e:
    print(f"❌ No se pudo importar investment_clock.py: {e}")
    print("   Coloca este script en la misma carpeta que investment_clock.py")
    sys.exit(1)


# Mapa de etiqueta de rating numérico → string
def rating_str(v):
    return {3:"+++", 2:"++", 1:"+", 0:"0", -1:"–", -2:"– –", -3:"– – –"}.get(v, str(v))

def rating_class(v):
    if v >= 3:  return "r-pp3"
    if v == 2:  return "r-pp2"
    if v == 1:  return "r-pp1"
    if v == 0:  return "r-neu"
    if v == -1: return "r-mm1"
    if v == -2: return "r-mm2"
    return "r-mm3"


# ── Configuración de los 12 indicadores del panel diagnóstico ───────
# (nombre interno, etiqueta, formato, invertido, fase si alto, fase si bajo, explicación)
DIAG_INDICATORS = [
    ("yield_curve_10_3", "Curva 10Y-3M",  "{:+.2f}%",  False, "Recuperación",       "Reflación/Recesión", "La mejor predictora de recesión (Fed SF): invertida = recesión en 12-18m"),
    ("yield_curve",      "Curva 10Y-2Y",  "{:+.2f}%",  False, "Recuperación",       "Reflación/Recesión", "Positiva = mercado espera expansión; negativa = contracción futura"),
    ("proxy_pmi",        "Proxy PMI (z)", "{:+.2f}\u03c3", False, "Recuperación",    "Reflación/Recesión", "z-score combinando horas mfg + pedidos + claims; proxy del ISM sin suscripción"),
    ("awhman_yoy",       "Horas Mfg YoY", "{:+.1f}%",  False, "Recuperación",       "Reflación/Recesión", "Empresas recortan horas ANTES de despedir: adelanta 2-3m a las nóminas"),
    ("core_yoy",         "Core CPI YoY",  "{:.1f}%",   False, "Estanflación",       "Recuperación",       "Inflación estructural: alta + crecimiento débil = estanflación clásica"),
    ("inflation_trend",  "Aceler. CPI",   "{:+.2f}pp", False, "Estanflación",       "Recuperación",       "+ = inflación acelerando (últimos 6m vs anteriores): señal estanflacionaria"),
    ("inf_exp",          "Breakeven 5Y",  "{:.2f}%",   False, "Estanflación",       "Reflación/Recesión", "Expectativas de inflación del mercado: >2.5% = presión persistente"),
    ("hy_spread",        "HY Spread",     "{:.2f}%",   True,  "Reflación/Recesión", "Sobrecalentamiento", "Spreads altos = mercado descuenta defaults; bajos = apetito de riesgo pleno"),
    ("ig_spread",        "IG Spread",     "{:.2f}%",   True,  "Reflación/Recesión", "Sobrecalentamiento", "Estrés en grado inversión confirma que el problema es sistémico, no solo HY"),
    ("jobless_claims_yoy","Claims YoY",   "{:+.1f}%",  True,  "Reflación/Recesión", "Recuperación",       "Subiendo = deterioro laboral inminente; adelanta 3-6 semanas a la tasa de paro"),
    ("houst_yoy",        "Viviendas YoY", "{:+.1f}%",  False, "Recuperación",       "Reflación/Recesión", "Primer sector en reaccionar a tipos: cayendo ya antes de que el ciclo gire"),
    ("fed_chg",          "Fed Funds \u03941Y", "{:+.2f}%", True, "Recuperación",   "Estanflación",       "Bajando = Fed ve riesgo recesivo e inflación controlada; subiendo = freno al ciclo"),
]


def build_export():
    print("📊 Descargando datos FRED...")
    data = download_all()
    print(f"✅ {len(data)} series descargadas")

    print("🔢 Calculando métricas...")
    m = calculate_metrics(data)
    pcts = compute_percentiles(data)
    momentum = calculate_momentum(data, pcts)

    print("🧮 Scoring tradicional + dual...")
    trad = score_phase(m, pcts)
    dual = score_dual(m, pcts)

    print("🤖 Entrenando/cargando modelo logístico...")
    model = train_model(data)

    # Predicción logística
    logit_result = None
    if model and model.get("pipeline") is not None:
        feat_vals = [m.get(f, np.nan) for f in FEATURES]
        if not any(v is None or (isinstance(v,float) and np.isnan(v)) for v in feat_vals):
            proba = model["pipeline"].predict_proba([feat_vals])[0]
            probas = {INT_PHASE[c]: float(pp) for c, pp in zip(model["pipeline"].classes_, proba)}
            top = max(probas, key=probas.get)
            srt = sorted(probas.values(), reverse=True)
            logit_result = {
                "phase": top,
                "probas": probas,
                "confidence": probas[top],
                "margin": (srt[0]-srt[1]) if len(srt) > 1 else srt[0],
            }

    # Selección de motor
    result = select_engine(logit_result, trad, model)

    print("📝 Generando interpretación...")
    try:
        interp = generate_interpretation(m, dual, momentum, pcts)
    except Exception as e:
        interp = f"(Interpretación no disponible: {e})"

    phase = result["phase"]
    engine = result.get("engine", "tradicional")
    confidence = result.get("confidence", trad.get("confidence", 0))

    # ── Construir indicadores del panel diagnóstico ────────────────
    diag = []
    for key, label, fmt, invert, ph_hi, ph_lo, explain in DIAG_INDICATORS:
        val = m.get(key)
        if val is None or (isinstance(val,float) and np.isnan(val)):
            diag.append(dict(key=key, label=label, value="—", pct=None,
                             pct_eff=None, invert=invert, arrow="", phase="", explain=explain))
            continue
        # percentil
        pct_raw = pcts.get(key)
        if pct_raw is not None and not (isinstance(pct_raw,float) and np.isnan(pct_raw)):
            pct_raw = float(pct_raw)
            pct_eff = (100 - pct_raw) if invert else pct_raw
        else:
            pct_raw, pct_eff = None, None
        # dirección / flecha
        if pct_eff is not None:
            if pct_eff >= 60:
                arrow, ph = "↑", ph_hi
            elif pct_eff <= 40:
                arrow, ph = "↓", ph_lo
            else:
                arrow, ph = "→", "neutro"
        else:
            arrow, ph = "", ""
        diag.append(dict(
            key=key, label=label, value=fmt.format(val),
            pct=pct_raw, pct_eff=pct_eff, invert=invert,
            arrow=arrow, phase=ph, explain=explain,
        ))

    # ── Scoring por fase con momentum ──────────────────────────────
    scores = result.get("trad_scores") or trad.get("scores", {})
    total = sum(max(0,v) for v in scores.values()) or 1
    phase_scores = []
    for ph in ["Recuperación","Sobrecalentamiento","Estanflación","Reflación/Recesión"]:
        raw = scores.get(ph, 0)
        pct = max(0, raw) / total * 100
        mom = momentum.get("scores_3m_ago", {}).get(ph) if momentum else None
        delta = None
        if mom is not None and total:
            delta = pct - (max(0,mom)/ (sum(max(0,v) for v in momentum["scores_3m_ago"].values()) or 1) *100)
        phase_scores.append(dict(phase=ph, pct=round(pct,1), delta=round(delta,1) if delta is not None else None))

    # ── Recomendaciones de la fase actual ──────────────────────────
    fi = [dict(asset=a, rating=r, rating_str=rating_str(r), cls=rating_class(r), reason=txt)
          for a, r, txt in FIXED_INCOME_RECS.get(phase, [])]
    eq = [dict(asset=a, rating=r, rating_str=rating_str(r), cls=rating_class(r), reason=txt)
          for a, r, txt in EQUITY_RECS.get(phase, [])]

    # ── Probabilidades logísticas ──────────────────────────────────
    probas = logit_result["probas"] if logit_result else None

    export = dict(
        generated_at = datetime.now().strftime("%Y-%m-%d %H:%M"),
        data_date = max(s.index[-1] for s in data.values() if len(s)).strftime("%Y-%m-%d"),
        phase = phase,
        engine = engine,
        confidence = round(float(confidence)*100, 1) if confidence <= 1 else round(float(confidence),1),
        cv_accuracy = round(model.get("cv_accuracy",0)*100,1) if model else None,
        n_samples = model.get("n_samples") if model else None,
        secondary = result.get("secondary") or trad.get("secondary"),
        probas = probas,
        phase_scores = phase_scores,
        diagnostics = diag,
        fixed_income = fi,
        equity = eq,
        dual = dict(
            signal = dual.get("signal"),
            signal_detail = dual.get("signal_detail"),
            phase_lead = dual.get("phase_lead"),
            phase_coin = dual.get("phase_coin"),
            diverge = dual.get("diverge"),
        ),
        interpretation = interp,
        diag_legend = [a for a in DIAG_INDICATORS if a[3]],  # invertidos
    )

    # Limpieza de NaN para JSON válido
    def clean(o):
        if isinstance(o, dict):  return {k: clean(v) for k,v in o.items()}
        if isinstance(o, list):  return [clean(v) for v in o]
        if isinstance(o, float) and (math.isnan(o) or math.isinf(o)): return None
        if isinstance(o, (np.integer,)):  return int(o)
        if isinstance(o, (np.floating,)): return float(o)
        return o
    export = clean(export)

    return export


if __name__ == "__main__":
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "docs"
    os.makedirs(out_dir, exist_ok=True)
    export = build_export()
    out_path = os.path.join(out_dir, "data.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(export, f, ensure_ascii=False, indent=2)
    print(f"\n✅ Exportado a {out_path}")
    print(f"   Fase: {export['phase']} ({export['confidence']}%)  Motor: {export['engine']}")
