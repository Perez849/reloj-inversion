# ═══════════════════════════════════════════════════════════════════════
#  INVESTMENT CLOCK  v3  —  Motor logístico primero
#
#  ARQUITECTURA DE DECISIÓN:
#
#   ┌─────────────────────────────────────────────────────────────┐
#   │  1. Descarga 20 años de FRED                                │
#   │  2. Construye features (métricas + percentiles)             │
#   │  3. Entrena regresión logística sobre cronología NBER real  │
#   │                                                             │
#   │  ¿Modelo válido? (CV ≥ 60%, ≥ 80 meses reales)             │
#   │       SÍ → usa logístico como resultado principal           │
#   │       NO → usa scoring tradicional (fallback)               │
#   │                                                             │
#   │  ¿Scoring tradicional supera al logístico en confianza?     │
#   │       (+15pp o más) → usa tradicional aunque haya logístico │
#   └─────────────────────────────────────────────────────────────┘
#
#  INSTALACIÓN:
#    pip install requests pandas matplotlib numpy scikit-learn
#
#  USO:
#    python ic_v3.py
#    → Genera: investment_clock_YYYYMMDD_HHMM.png
# ═══════════════════════════════════════════════════════════════════════

# ── BLOQUE BASE (descarga, métricas, scoring tradicional) ────────────
# (preservado íntegro de versión anterior — no tocar)
# ────────────────────────────────────────────────────────────────────

"""
╔══════════════════════════════════════════════════════════════════╗
║           INVESTMENT CLOCK ANALYZER  —  VS Code Edition          ║
║                                                                  ║
║  Descarga datos reales de FRED, determina la fase del ciclo      ║
║  económico con scoring ponderado, y genera una imagen            ║
║  de dashboard de alta calidad lista para usar.                   ║
║                                                                  ║
║  INSTALACIÓN (una sola vez):                                     ║
║    pip install requests pandas matplotlib numpy scipy            ║
║                                                                  ║
║  USO:                                                            ║
║    python investment_clock.py                                    ║
║    → Genera: investment_clock_YYYYMMDD.png                       ║
╚══════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import requests
import pandas as pd
import numpy as np
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.gridspec as gridspec
from matplotlib.patches import FancyBboxPatch, Arc, Wedge, FancyArrowPatch
from matplotlib.colors import LinearSegmentedColormap
import matplotlib.patheffects as pe
from datetime import datetime, timedelta
from io import StringIO
import warnings
import sys

warnings.filterwarnings("ignore")
matplotlib.rcParams['figure.dpi'] = 150


# ══════════════════════════════════════════════════════════════════
#  PALETA  &  TIPOGRAFÍA
# ══════════════════════════════════════════════════════════════════
BG       = "#0a0b0e"
SURFACE  = "#12141a"
SURFACE2 = "#1c1f28"
BORDER   = "#2a2d3a"
TEXT     = "#e8eaf2"
MUTED    = "#6b7080"
ACCENT   = "#c8f060"

PHASE_COLORS = {
    "Recuperación":    "#60f0a0",
    "Sobrecalentamiento": "#f06060",
    "Estanflación":    "#f0b060",
    "Reflación/Recesión": "#6090f0",
}

PHASE_BG = {
    "Recuperación":    "#0d1f16",
    "Sobrecalentamiento": "#1f0d0d",
    "Estanflación":    "#1f180d",
    "Reflación/Recesión": "#0d1220",
}

# Factor de escala de fuentes — sube este número para todo más grande
FS = 1.55   # multiplica todos los fontsize del dashboard


# ══════════════════════════════════════════════════════════════════
#  INDICADORES FRED  (id → configuración)
#
#  MEJORAS vs versión anterior:
#   + ISMMFG  : ISM Manufacturing PMI          (adelantado fuerte)
#   + ISMSERV : ISM Services PMI               (sector dominante EE.UU.)
#   + UNRATE  : Tasa de desempleo              (nivel + tendencia)
#   + T5YIE   : Breakeven inflación 5Y         (expectativas mercado)
#   + PERMIT  : Permisos de construcción       (sensible a tasas)
# ══════════════════════════════════════════════════════════════════
INDICATORS = {
    # ── ACTIVIDAD REAL ────────────────────────────────────────────
    "NEWORDER":     {"name": "Nuevos Pedidos Mfg",            "freq": "M", "weight": 1.8, "type": "leading"},
    "RETAILSMNSA":  {"name": "Ventas Minoristas ex Autos",    "freq": "M", "weight": 1.5, "type": "lagging"},
    "DGORDER":      {"name": "Pedidos Bienes Duraderos",      "freq": "M", "weight": 1.6, "type": "leading"},  # ★ NUEVO
    "IPMAN":        {"name": "Prod. Industrial Mfg",          "freq": "M", "weight": 1.4, "type": "lagging"},  # ★ NUEVO
    # ── EMPLEO ────────────────────────────────────────────────────
    "PAYEMS":       {"name": "Nóminas No Agrícolas",          "freq": "M", "weight": 1.5, "type": "lagging"},
    "UNRATE":       {"name": "Tasa de Desempleo",             "freq": "M", "weight": 1.5, "type": "lagging"},
    "AWHMAN":       {"name": "Horas Trabaj. Mfg",             "freq": "M", "weight": 1.7, "type": "leading"},  # ★ NUEVO — proxy PMI
    "IC4WSA":       {"name": "Peticiones Desempleo 4w",       "freq": "W", "weight": 1.6, "type": "leading"},
    # ── SENTIMIENTO ───────────────────────────────────────────────
    "UMCSENT":      {"name": "Sentimiento Consumidor",        "freq": "M", "weight": 0.8, "type": "lagging"},
    # ── INFLACIÓN ─────────────────────────────────────────────────
    "CPIAUCSL":     {"name": "CPI General",                   "freq": "M", "weight": 0.0, "type": "lagging"},  # solo display
    "CPILFESL":     {"name": "Core CPI",                      "freq": "M", "weight": 1.8, "type": "lagging"},
    "T5YIE":        {"name": "Breakeven Inflación 5Y",        "freq": "D", "weight": 1.2, "type": "leading"},
    # ── POLÍTICA MONETARIA & CURVAS ──────────────────────────────
    "FEDFUNDS":     {"name": "Fed Funds Rate",                "freq": "M", "weight": 1.5, "type": "lagging"},
    "T10Y2Y":       {"name": "Curva 10Y-2Y",                  "freq": "D", "weight": 2.0, "type": "leading"},
    "T10Y3M":       {"name": "Curva 10Y-3M",                  "freq": "D", "weight": 2.2, "type": "leading"},
    "BAMLH0A0HYM2": {"name": "HY Spread",                     "freq": "D", "weight": 1.5, "type": "leading"},
    "BAMLC0A0CM":   {"name": "IG Spread",                     "freq": "D", "weight": 1.2, "type": "leading"},
    # ── CONSTRUCCIÓN & RIESGO ────────────────────────────────────
    "VIXCLS":       {"name": "VIX",                           "freq": "D", "weight": 1.2, "type": "lagging"},
    "PERMIT":       {"name": "Permisos Construcción",         "freq": "M", "weight": 1.0, "type": "leading"},
    "HOUST":        {"name": "Viviendas Iniciadas",           "freq": "M", "weight": 1.1, "type": "leading"},  # ★ NUEVO
}

# Mapeo a IDs reales de FRED (todos verificados y activos)
# NEWORDER    → AMTMNO  (Nuevos pedidos manufactureros, Census Bureau)
# RETAILSMNSA → RSXFS   (Ventas minoristas ex autos, Census Bureau)
FRED_ID_MAP = {
    "NEWORDER":    "AMTMNO",
    "RETAILSMNSA": "RSXFS",
    # IC4WSA, T10Y3M, BAMLC0A0CM son IDs directos de FRED (sin mapeo)
}


# ══════════════════════════════════════════════════════════════════
#  DESCARGA FRED
# ══════════════════════════════════════════════════════════════════
def fetch_fred(series_id: str, start: str, end: str,
               max_retries: int = 4, retry_delay: float = 3.0) -> pd.Series:
    """
    Descarga una serie de FRED en formato CSV. Devuelve pd.Series con índice de fechas.
    Reintenta automáticamente hasta max_retries veces ante fallos del servidor.
    """
    import time
    fred_id = FRED_ID_MAP.get(series_id, series_id)
    url = (
        f"https://fred.stlouisfed.org/graph/fredgraph.csv"
        f"?id={fred_id}&cosd={start}&coed={end}"
    )
    for attempt in range(1, max_retries + 1):
        try:
            r = requests.get(url, timeout=20)
            r.raise_for_status()
            # Leer sin asumir nombre de columna — FRED a veces cambia "DATE" por otro nombre
            raw_text = r.text.strip()
            if not raw_text or raw_text.startswith("<") or raw_text.startswith("{"):
                raise ValueError(f"FRED devolvió respuesta no-CSV: {raw_text[:120]}")
            df = pd.read_csv(StringIO(raw_text))
            # La primera columna es siempre la fecha, la segunda el valor
            date_col  = df.columns[0]
            value_col = df.columns[1]
            df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
            df = df.dropna(subset=[date_col])
            df = df.set_index(date_col)
            s = pd.to_numeric(df[value_col], errors="coerce").dropna()
            if len(s) == 0:
                print(f"  ⚠  {series_id} ({fred_id}): sin datos")
                return pd.Series(dtype=float)
            return s
        except Exception as e:
            if attempt < max_retries:
                print(f"  ↻  {series_id}: intento {attempt}/{max_retries} fallido — reintentando en {retry_delay:.0f}s  ({e})")
                time.sleep(retry_delay)
            else:
                print(f"  ✗  {series_id}: todos los intentos fallaron — {e}")
                return pd.Series(dtype=float)


def monthly_avg(s: pd.Series) -> pd.Series:
    """Convierte serie diaria en promedio mensual."""
    return s.resample("MS").mean()


def val_at(s: pd.Series, months_ago: int = 0) -> float:
    """Devuelve el valor N meses antes del último dato disponible."""
    if s.empty:
        return np.nan
    latest_date = s.index[-1]
    target = latest_date - pd.DateOffset(months=months_ago)
    idx = s.index.get_indexer([target], method="nearest")[0]
    return float(s.iloc[idx])


# ══════════════════════════════════════════════════════════════════
#  DESCARGA TODOS LOS INDICADORES
# ══════════════════════════════════════════════════════════════════
def download_all() -> dict:
    end   = datetime.today().strftime("%Y-%m-%d")
    start = (datetime.today() - timedelta(days=365*20)).strftime("%Y-%m-%d")  # 20 años para percentiles históricos

    print("\n🌐  Descargando datos de FRED...")
    data = {}
    for sid, cfg in INDICATORS.items():
        print(f"    ↓  {sid:15s} — {cfg['name']}")
        raw = fetch_fred(sid, start, end)
        if raw.empty:
            data[sid] = pd.Series(dtype=float)
            continue
        # Series diarias → promedio mensual para uniformidad
        if cfg["freq"] in ("D", "W"):
            data[sid] = monthly_avg(raw)   # diarias y semanales → promedio mensual
        else:
            data[sid] = raw
    print("    ✓  Descarga completada\n")
    return data


# ══════════════════════════════════════════════════════════════════
#  CÁLCULO DE MÉTRICAS
# ══════════════════════════════════════════════════════════════════
def calculate_metrics(data: dict) -> dict:
    m = {}

    def safe(sid, months=0):
        s = data.get(sid, pd.Series(dtype=float))
        if s.empty:
            return np.nan
        return val_at(s, months)

    # — Nuevos Pedidos Manufactureros (AMTMNO) — adelantado ciclo industrial
    # CORRECCIÓN: AMTMNO es nominal. Lo deflactamos dividiendo por CPI para
    # evitar que la inflación infle artificialmente el YoY en periodos de precios altos.
    no_now_nom = safe("NEWORDER", 0)
    no_12m_nom = safe("NEWORDER", 12)
    no_3m_nom  = safe("NEWORDER", 3)
    cpi_now_d  = safe("CPIAUCSL", 0)
    cpi_12m_d  = safe("CPIAUCSL", 12)
    cpi_3m_d   = safe("CPIAUCSL", 3)
    # Pedidos reales = pedidos nominales / CPI (base relativa)
    no_now = (no_now_nom / cpi_now_d) if cpi_now_d else no_now_nom
    no_12m = (no_12m_nom / cpi_12m_d) if cpi_12m_d else no_12m_nom
    no_3m  = (no_3m_nom  / cpi_3m_d)  if cpi_3m_d  else no_3m_nom
    m["neworder_yoy"] = ((no_now / no_12m) - 1) * 100 if no_12m else np.nan
    m["neworder_mom"] = ((no_now / no_3m)  - 1) * 100 * 4 if no_3m else np.nan

    # — Ventas Minoristas ex Autos (RSXFS) — proxy actividad consumo/servicios
    rs_now = safe("RETAILSMNSA", 0)
    rs_12m = safe("RETAILSMNSA", 12)
    m["retail_yoy"] = ((rs_now / rs_12m) - 1) * 100 if rs_12m else np.nan

    # — Empleo —
    pay_now = safe("PAYEMS", 0)
    pay_3m  = safe("PAYEMS", 3)
    m["payroll_chg_3m"] = (pay_now - pay_3m) / 3 if pay_3m else np.nan

    # Tasa de desempleo: nivel + tendencia (sube = malo)
    m["unrate"]       = safe("UNRATE", 0)
    m["unrate_6m"]    = safe("UNRATE", 6)
    m["unrate_delta"] = m["unrate"] - m["unrate_6m"]  # >0 empeorando

    # — Sentimiento consumidor —
    m["sentiment_chg"] = safe("UMCSENT", 0) - safe("UMCSENT", 12)

    # — Inflación —
    cpi_now = safe("CPIAUCSL", 0)
    cpi_12m = safe("CPIAUCSL", 12)
    # CPI general: solo para mostrar en pantalla, NO entra en scoring
    m["cpi_yoy"] = ((cpi_now / cpi_12m) - 1) * 100 if cpi_12m else np.nan

    # Core CPI — sí entra en scoring
    core_now = safe("CPILFESL", 0)
    core_12m = safe("CPILFESL", 12)
    core_6m  = safe("CPILFESL", 6)
    m["core_yoy"] = ((core_now / core_12m) - 1) * 100 if core_12m else np.nan

    # CORRECCIÓN inflation_trend:
    # Antes comparaba cpi_6m (valor de hace 6 meses) con cpi_12m, calculando la
    # inflación del semestre anterior, no del reciente.
    # Ahora: inflación de los últimos 6 meses anualizada vs. los 6 meses previos.
    # Recent half: core_now / core_6m anualizado
    # Prior half:  core_6m  / core_12m anualizado
    if core_6m and core_12m and core_now:
        recent_ann = ((core_now / core_6m) - 1) * 100 * 2   # últimos 6m × 2
        prior_ann  = ((core_6m  / core_12m) - 1) * 100 * 2  # 6m anteriores × 2
        m["inflation_trend"] = recent_ann - prior_ann        # + = acelerando ahora
    else:
        m["inflation_trend"] = np.nan

    # — Expectativas inflación (breakeven 5Y) —
    m["inf_exp"]     = safe("T5YIE", 0)
    m["inf_exp_6m"]  = safe("T5YIE", 6)
    m["inf_exp_chg"] = m["inf_exp"] - m["inf_exp_6m"]

    # — Política monetaria —
    m["fed_funds"]   = safe("FEDFUNDS", 0)
    m["fed_chg"]     = safe("FEDFUNDS", 0) - safe("FEDFUNDS", 12)  # cambio anual

    # — Curva de tipos —
    m["yield_curve"] = safe("T10Y2Y", 0)

    # — Crédito & riesgo —
    hy_now = safe("BAMLH0A0HYM2", 0)
    hy_6m  = safe("BAMLH0A0HYM2", 6)
    m["hy_spread"]    = hy_now
    m["credit_stress"]= hy_now - hy_6m  # + = widening = estrés

    m["vix"]          = safe("VIXCLS", 0)

    # — Construcción —
    permit_now = safe("PERMIT", 0)
    permit_12m = safe("PERMIT", 12)
    m["permit_yoy"] = ((permit_now / permit_12m) - 1) * 100 if permit_12m else np.nan

    # ── NUEVOS INDICADORES ────────────────────────────────────────

    # Curva 10Y-3M (mejor predictor recesión según Fed de San Francisco)
    # Invertida con más frecuencia antes de recesiones que 10Y-2Y
    m["yield_curve_10_3"] = safe("T10Y3M", 0)

    # Peticiones desempleo iniciales (4w media) — adelantado semanal
    # Cambio YoY: sube = mercado laboral deteriorando
    ic_now = safe("IC4WSA", 0)
    ic_12m = safe("IC4WSA", 12)
    ic_3m  = safe("IC4WSA", 3)
    m["jobless_claims"]      = ic_now
    m["jobless_claims_yoy"]  = ((ic_now / ic_12m) - 1) * 100 if ic_12m else np.nan
    m["jobless_claims_trend"] = ic_now - ic_3m if not np.isnan(ic_now) and not np.isnan(ic_3m) else np.nan

    # IG Spread (investment grade) — confirma o diverge del HY spread
    ig_now = safe("BAMLC0A0CM", 0)
    ig_6m  = safe("BAMLC0A0CM", 6)
    m["ig_spread"]       = ig_now
    m["ig_stress"]       = ig_now - ig_6m if not np.isnan(ig_now) else np.nan

    # ══════════════════════════════════════════════════════════════
    # MEJORA 2: VELOCIDAD DE CAMBIO
    # Para cada indicador clave, calculamos si la tendencia
    # de los últimos 3 meses es mejor o peor que los 3 anteriores.
    # velocity > 0 = mejorando, < 0 = deteriorando
    # ══════════════════════════════════════════════════════════════

    # Velocidad nóminas: ¿los últimos 3 meses mejor que los 3 anteriores?
    pay_now   = safe("PAYEMS", 0);  pay_3m_v  = safe("PAYEMS", 3);  pay_6m_v = safe("PAYEMS", 6)
    pay_chg_recent = (pay_now - pay_3m_v) / 3 if pay_3m_v else np.nan
    pay_chg_prior  = (pay_3m_v - pay_6m_v) / 3 if pay_6m_v else np.nan
    m["payroll_velocity"] = pay_chg_recent - pay_chg_prior  # + = acelerando

    # Velocidad Core CPI: ¿inflación acelerando o frenando en los últimos 3m?
    core_3m = safe("CPILFESL", 3)
    if core_3m and core_now:
        recent_3m_ann = ((core_now / core_3m) - 1) * 400   # últimos 3m × 4
        prior_3m_ann  = ((core_3m / core_6m) - 1) * 400    # 3m anteriores × 4
        m["inflation_velocity"] = recent_3m_ann - prior_3m_ann
    else:
        m["inflation_velocity"] = np.nan

    # Velocidad peticiones desempleo (3m vs 3m anteriores)
    # Positivo = deteriorando (malo), Negativo = mejorando (bueno)
    m["claims_velocity"] = m["jobless_claims_trend"]

    # Velocidad curva de tipos (¿empinándose o aplanándose?)
    yc_3m = safe("T10Y2Y", 3)
    m["curve_velocity"] = m["yield_curve"] - yc_3m if not np.isnan(m["yield_curve"]) and not np.isnan(yc_3m) else np.nan

    # Velocidad HY spread (¿comprimiéndose o ampliándose en 3m?)
    hy_3m = safe("BAMLH0A0HYM2", 3)
    m["hy_velocity"] = hy_now - hy_3m if not np.isnan(hy_now) and not np.isnan(hy_3m) else np.nan

    # ── INDICADORES ADICIONALES para el panel de diagnóstico ─────────

    # Horas manufactureras (AWHMAN) — proxy PMI adelantado 2-3m vs nóminas
    awh_now = safe("AWHMAN", 0)
    awh_12m = safe("AWHMAN", 12)
    awh_3m  = safe("AWHMAN", 3)
    m["awhman"]      = awh_now
    m["awhman_yoy"]  = ((awh_now / awh_12m) - 1) * 100 if awh_12m and not np.isnan(awh_12m) else np.nan
    m["awhman_trend"] = awh_now - awh_3m if not np.isnan(awh_now) and not np.isnan(awh_3m) else np.nan

    # Bienes duraderos deflactados (DGORDER / CPI)
    dg_now_nom = safe("DGORDER", 0)
    dg_12m_nom = safe("DGORDER", 12)
    dg_3m_nom  = safe("DGORDER", 3)
    dg_now = (dg_now_nom / cpi_now_d) if cpi_now_d and not np.isnan(cpi_now_d) else dg_now_nom
    dg_12m = (dg_12m_nom / cpi_12m_d) if cpi_12m_d and not np.isnan(cpi_12m_d) else dg_12m_nom
    dg_3m  = (dg_3m_nom  / cpi_3m_d)  if cpi_3m_d  and not np.isnan(cpi_3m_d)  else dg_3m_nom
    m["durable_yoy"] = ((dg_now / dg_12m) - 1) * 100 if dg_12m and not np.isnan(dg_12m) else np.nan
    m["durable_mom"] = ((dg_now / dg_3m)  - 1) * 100 * 4 if dg_3m and not np.isnan(dg_3m) else np.nan

    # Producción industrial manufacturera (IPMAN)
    ip_now = safe("IPMAN", 0)
    ip_12m = safe("IPMAN", 12)
    ip_3m  = safe("IPMAN", 3)
    m["ipman_yoy"]   = ((ip_now / ip_12m) - 1) * 100 if ip_12m and not np.isnan(ip_12m) else np.nan
    m["ipman_trend"] = ip_now - ip_3m if not np.isnan(ip_now) and not np.isnan(ip_3m) else np.nan

    # Viviendas iniciadas (HOUST) — adelantado a permisos
    houst_now = safe("HOUST", 0)
    houst_12m = safe("HOUST", 12)
    m["houst_yoy"] = ((houst_now / houst_12m) - 1) * 100 if houst_12m and not np.isnan(houst_12m) else np.nan

    # Proxy PMI compuesto: z-score normalizado de AWHMAN + IC4WSA (invertido) + NEWORDER
    # Cada componente: (valor_actual - media_12m) / std_12m
    def rolling_z(sid, invert=False):
        s = data.get(sid, pd.Series(dtype=float))
        if s.empty or len(s) < 13:
            return np.nan
        recent = s.dropna().iloc[-13:]
        if len(recent) < 5:
            return np.nan
        mu, sigma = float(recent.iloc[:-1].mean()), float(recent.iloc[:-1].std())
        if sigma == 0:
            return 0.0
        z = (float(recent.iloc[-1]) - mu) / sigma
        return -z if invert else z

    valid_z = [v for v in [
        rolling_z("AWHMAN"),
        rolling_z("IC4WSA",   invert=True),   # claims: alto = malo → invertir
        rolling_z("NEWORDER"),
        rolling_z("DGORDER"),
    ] if not (isinstance(v, float) and np.isnan(v))]
    m["proxy_pmi"] = float(np.mean(valid_z)) if valid_z else np.nan

    return m



# ══════════════════════════════════════════════════════════════════
#  PERCENTILES HISTÓRICOS
#  Para cada métrica derivada, calcula en qué percentil está el
#  valor actual respecto a su distribución histórica (20 años).
#  Esto evita umbrales fijos: un CPI al 3% era "bajo" en 2022
#  pero "alto" en 2015. El percentil captura el contexto real.
# ══════════════════════════════════════════════════════════════════
def compute_percentiles(data: dict) -> dict:
    """
    Devuelve percentiles [0-100] para cada serie derivada clave.
    Se calculan sobre toda la historia disponible (hasta 20 años).
    """
    pcts = {}

    def pct_of(sid, transform=None):
        """Percentil del último valor de una serie tras aplicar transform."""
        s = data.get(sid, pd.Series(dtype=float))
        if s.empty or len(s) < 24:
            return np.nan
        vals = s.dropna()
        if transform:
            vals = transform(vals)
        current = float(vals.iloc[-1])
        pct = float((vals < current).mean() * 100)
        return round(pct, 1)

    def yoy_series(sid, deflate_by=None):
        """Serie YoY completa para calcular su percentil."""
        s = data.get(sid, pd.Series(dtype=float))
        if s.empty: return pd.Series(dtype=float)
        if deflate_by is not None:
            d = data.get(deflate_by, pd.Series(dtype=float))
            if not d.empty:
                d = d.reindex(s.index, method="nearest")
                s = s / d
        return s.pct_change(12) * 100

    # Actividad
    no_yoy = yoy_series("NEWORDER", deflate_by="CPIAUCSL")
    if not no_yoy.empty:
        no_yoy = no_yoy.dropna()
        if len(no_yoy) > 24:
            cur = float(no_yoy.iloc[-1])
            pcts["neworder_yoy"] = round(float((no_yoy < cur).mean() * 100), 1)

    rs_yoy = yoy_series("RETAILSMNSA")
    if not rs_yoy.empty:
        rs_yoy = rs_yoy.dropna()
        if len(rs_yoy) > 24:
            cur = float(rs_yoy.iloc[-1])
            pcts["retail_yoy"] = round(float((rs_yoy < cur).mean() * 100), 1)

    # Empleo — nóminas (cambio 3m)
    pay = data.get("PAYEMS", pd.Series(dtype=float))
    if not pay.empty and len(pay) > 24:
        pay_chg = (pay - pay.shift(3)) / 3
        pay_chg = pay_chg.dropna()
        cur = float(pay_chg.iloc[-1])
        pcts["payroll_chg_3m"] = round(float((pay_chg < cur).mean() * 100), 1)

    # Desempleo — nivel (invertido: percentil bajo = bueno)
    pcts["unrate"] = pct_of("UNRATE")

    # Core CPI YoY
    core_yoy = yoy_series("CPILFESL")
    if not core_yoy.empty:
        core_yoy = core_yoy.dropna()
        if len(core_yoy) > 24:
            cur = float(core_yoy.iloc[-1])
            pcts["core_yoy"] = round(float((core_yoy < cur).mean() * 100), 1)

    # Breakeven 5Y
    pcts["inf_exp"] = pct_of("T5YIE")

    # Fed Funds
    pcts["fed_funds"] = pct_of("FEDFUNDS")

    # Curva de tipos
    pcts["yield_curve"] = pct_of("T10Y2Y")

    # HY Spread
    pcts["hy_spread"] = pct_of("BAMLH0A0HYM2")

    # VIX
    pcts["vix"] = pct_of("VIXCLS")

    # Permisos construcción YoY
    permit_yoy = yoy_series("PERMIT")
    if not permit_yoy.empty:
        permit_yoy = permit_yoy.dropna()
        if len(permit_yoy) > 24:
            cur = float(permit_yoy.iloc[-1])
            pcts["permit_yoy"] = round(float((permit_yoy < cur).mean() * 100), 1)

    # ── NUEVOS PERCENTILES para diagnóstico logístico ─────────────

    # Curva 10Y-3M
    pcts["yield_curve_10_3"] = pct_of("T10Y3M")

    # IG Spread
    pcts["ig_spread"] = pct_of("BAMLC0A0CM")

    # Horas manufactureras YoY
    awh_yoy_s = yoy_series("AWHMAN")
    if not awh_yoy_s.empty:
        awh_yoy_s = awh_yoy_s.dropna()
        if len(awh_yoy_s) > 24:
            cur = float(awh_yoy_s.iloc[-1])
            pcts["awhman_yoy"] = round(float((awh_yoy_s < cur).mean() * 100), 1)

    # Viviendas iniciadas YoY
    houst_yoy_s = yoy_series("HOUST")
    if not houst_yoy_s.empty:
        houst_yoy_s = houst_yoy_s.dropna()
        if len(houst_yoy_s) > 24:
            cur = float(houst_yoy_s.iloc[-1])
            pcts["houst_yoy"] = round(float((houst_yoy_s < cur).mean() * 100), 1)

    # Bienes duraderos YoY (deflactado)
    dg_yoy_s = yoy_series("DGORDER", deflate_by="CPIAUCSL")
    if not dg_yoy_s.empty:
        dg_yoy_s = dg_yoy_s.dropna()
        if len(dg_yoy_s) > 24:
            cur = float(dg_yoy_s.iloc[-1])
            pcts["durable_yoy"] = round(float((dg_yoy_s < cur).mean() * 100), 1)

    # Peticiones desempleo YoY
    ic_yoy_s = yoy_series("IC4WSA")
    if not ic_yoy_s.empty:
        ic_yoy_s = ic_yoy_s.dropna()
        if len(ic_yoy_s) > 24:
            cur = float(ic_yoy_s.iloc[-1])
            pcts["jobless_claims_yoy"] = round(float((ic_yoy_s < cur).mean() * 100), 1)

    # Fed Funds cambio anual
    ff = data.get("FEDFUNDS", pd.Series(dtype=float))
    if not ff.empty and len(ff) > 24:
        ff_chg = (ff - ff.shift(12)).dropna()
        if len(ff_chg) > 24:
            cur = float(ff_chg.iloc[-1])
            pcts["fed_chg"] = round(float((ff_chg < cur).mean() * 100), 1)

    # Aceleración inflación (inflation_trend)
    core_s = data.get("CPILFESL", pd.Series(dtype=float))
    if not core_s.empty and len(core_s) > 24:
        r6 = (core_s / core_s.shift(6) - 1) * 200
        p6 = (core_s.shift(6) / core_s.shift(12) - 1) * 200
        trend_s = (r6 - p6).dropna()
        if len(trend_s) > 24:
            cur = float(trend_s.iloc[-1])
            pcts["inflation_trend"] = round(float((trend_s < cur).mean() * 100), 1)

    # Proxy PMI percentil (rolling z-score de AWHMAN)
    awh_s = data.get("AWHMAN", pd.Series(dtype=float))
    if not awh_s.empty and len(awh_s) > 24:
        rolling_z = awh_s.rolling(12).apply(
            lambda x: (x.iloc[-1] - x.mean()) / x.std() if x.std() > 0 else 0.0,
            raw=False
        ).dropna()
        if len(rolling_z) > 24:
            cur = float(rolling_z.iloc[-1])
            pcts["proxy_pmi"] = round(float((rolling_z < cur).mean() * 100), 1)

    return pcts


# ══════════════════════════════════════════════════════════════════
#  SCORING AJUSTADO POR PERCENTIL
#  En vez de umbrales fijos, los puntos se escalan según el
#  percentil histórico: más extremo el percentil → más puntos.
#  Función: pts = pts_base × scale(percentil)
#  Donde scale va de 0.3 (percentil 50, neutro) a 1.0 (extremos).
# ══════════════════════════════════════════════════════════════════
def percentile_scale(pct: float, invert: bool = False) -> float:
    """
    Devuelve un multiplicador [0.3, 1.0] según la distancia al percentil 50.
    invert=True para indicadores donde alto = malo (desempleo, spreads, VIX).
    Si pct es NaN, devuelve 0.7 (escala neutra, no ignora el indicador).
    """
    if np.isnan(pct):
        return 0.7
    if invert:
        pct = 100 - pct  # invertir: percentil 90 de desempleo = percentil 10 efectivo
    dist = abs(pct - 50) / 50  # 0 en el centro, 1 en los extremos
    return 0.3 + 0.7 * dist    # escala de 0.3 a 1.0


# ══════════════════════════════════════════════════════════════════
#  MOMENTUM DE FASE (opción 2)
#  Recalcula el scoring para los últimos 3 meses usando datos
#  históricos ya descargados. No necesita ficheros externos.
# ══════════════════════════════════════════════════════════════════
def calculate_momentum(data: dict, pcts: dict) -> dict:
    """
    Calcula scores para los últimos 4 meses y devuelve:
    - scores_history: lista de (mes, scores_dict)
    - trend: dict fase→ cambio en score últimos 3 meses
    - arrow: dict fase→ '↑' / '↓' / '→'
    """
    history = []
    for lag in [3, 2, 1, 0]:
        # Calcular métricas desplazadas en el tiempo
        m_lag = calculate_metrics_at(data, lag)
        r_lag = score_phase_core(m_lag, pcts)
        date_label = (datetime.today() - pd.DateOffset(months=lag)).strftime("%b %Y")
        history.append((date_label, r_lag["scores"]))

    # Tendencia: diferencia entre score actual y hace 3 meses
    trend  = {}
    arrows = {}
    scores_now  = history[-1][1]   # lag=0 (actual)
    scores_3m   = history[0][1]    # lag=3
    for ph in scores_now:
        delta = scores_now[ph] - scores_3m[ph]
        trend[ph]  = delta
        if   delta >  2.0: arrows[ph] = "↑"
        elif delta < -2.0: arrows[ph] = "↓"
        else:              arrows[ph] = "→"

    return {
        "history":  history,   # [(label, scores), ...]
        "trend":    trend,     # {fase: delta_pct}
        "arrows":   arrows,    # {fase: ↑/↓/→}
    }


def calculate_metrics_at(data: dict, months_ago: int) -> dict:
    """Igual que calculate_metrics pero usando datos de N meses atrás."""
    m = {}

    def safe(sid, offset=0):
        s = data.get(sid, pd.Series(dtype=float))
        if s.empty: return np.nan
        return val_at(s, months_ago + offset)

    # Nuevos pedidos reales
    no_now_nom = safe("NEWORDER", 0);  no_12m_nom = safe("NEWORDER", 12); no_3m_nom = safe("NEWORDER", 3)
    cpi_n = safe("CPIAUCSL", 0);       cpi_12 = safe("CPIAUCSL", 12);     cpi_3 = safe("CPIAUCSL", 3)
    no_now = (no_now_nom/cpi_n) if cpi_n else no_now_nom
    no_12m = (no_12m_nom/cpi_12) if cpi_12 else no_12m_nom
    no_3m  = (no_3m_nom/cpi_3)   if cpi_3  else no_3m_nom
    m["neworder_yoy"] = ((no_now/no_12m)-1)*100 if no_12m else np.nan
    m["neworder_mom"] = ((no_now/no_3m)-1)*100*4 if no_3m else np.nan

    rs_now = safe("RETAILSMNSA", 0); rs_12m = safe("RETAILSMNSA", 12)
    m["retail_yoy"] = ((rs_now/rs_12m)-1)*100 if rs_12m else np.nan

    pay_now = safe("PAYEMS", 0); pay_3m = safe("PAYEMS", 3)
    m["payroll_chg_3m"] = (pay_now - pay_3m)/3 if pay_3m else np.nan

    m["unrate"]       = safe("UNRATE", 0)
    m["unrate_6m"]    = safe("UNRATE", 6)
    m["unrate_delta"] = m["unrate"] - m["unrate_6m"] if not np.isnan(m["unrate"]) else np.nan

    m["sentiment_chg"] = safe("UMCSENT", 0) - safe("UMCSENT", 12)

    cpi_now = safe("CPIAUCSL", 0); cpi_12m = safe("CPIAUCSL", 12)
    m["cpi_yoy"] = ((cpi_now/cpi_12m)-1)*100 if cpi_12m else np.nan

    core_now = safe("CPILFESL", 0); core_12m = safe("CPILFESL", 12); core_6m = safe("CPILFESL", 6)
    m["core_yoy"] = ((core_now/core_12m)-1)*100 if core_12m else np.nan
    if core_6m and core_12m and core_now:
        m["inflation_trend"] = ((core_now/core_6m)-1)*100*2 - ((core_6m/core_12m)-1)*100*2
    else:
        m["inflation_trend"] = np.nan

    m["inf_exp"]     = safe("T5YIE", 0)
    m["inf_exp_6m"]  = safe("T5YIE", 6)
    m["inf_exp_chg"] = m["inf_exp"] - m["inf_exp_6m"] if not np.isnan(m["inf_exp"]) else np.nan

    m["fed_funds"]   = safe("FEDFUNDS", 0)
    m["fed_chg"]     = safe("FEDFUNDS", 0) - safe("FEDFUNDS", 12)

    m["yield_curve"] = safe("T10Y2Y", 0)

    hy_now = safe("BAMLH0A0HYM2", 0); hy_6m = safe("BAMLH0A0HYM2", 6)
    m["hy_spread"]     = hy_now
    m["credit_stress"] = hy_now - hy_6m if not np.isnan(hy_now) else np.nan

    m["vix"]        = safe("VIXCLS", 0)

    permit_now = safe("PERMIT", 0); permit_12m = safe("PERMIT", 12)
    m["permit_yoy"] = ((permit_now/permit_12m)-1)*100 if permit_12m else np.nan

    # Nuevos indicadores para momentum
    m["yield_curve_10_3"] = safe("T10Y3M", 0)

    ic_now_m = safe("IC4WSA", 0); ic_12m_m = safe("IC4WSA", 12); ic_3m_m = safe("IC4WSA", 3)
    m["jobless_claims_yoy"]   = ((ic_now_m/ic_12m_m)-1)*100 if ic_12m_m else np.nan
    m["jobless_claims_trend"] = ic_now_m - ic_3m_m if not np.isnan(ic_now_m) and not np.isnan(ic_3m_m) else np.nan

    ig_now_m = safe("BAMLC0A0CM", 0); ig_6m_m = safe("BAMLC0A0CM", 6)
    m["ig_spread"] = ig_now_m
    m["ig_stress"] = ig_now_m - ig_6m_m if not np.isnan(ig_now_m) else np.nan

    # Velocidades para momentum
    pay_n = safe("PAYEMS",0); pay_3 = safe("PAYEMS",3); pay_6 = safe("PAYEMS",6)
    m["payroll_velocity"] = ((pay_n-pay_3)/3 - (pay_3-pay_6)/3) if pay_3 and pay_6 else np.nan

    core_n = safe("CPILFESL",0); core_3 = safe("CPILFESL",3); core_6_m = safe("CPILFESL",6)
    if core_3 and core_n and core_6_m:
        m["inflation_velocity"] = ((core_n/core_3)-1)*400 - ((core_3/core_6_m)-1)*400
    else:
        m["inflation_velocity"] = np.nan

    yc_3m_v = safe("T10Y2Y", 3)
    m["curve_velocity"] = m.get("yield_curve",float("nan")) - yc_3m_v if not np.isnan(m.get("yield_curve",float("nan"))) else np.nan

    hy_n = safe("BAMLH0A0HYM2",0); hy_3 = safe("BAMLH0A0HYM2",3)
    m["hy_velocity"] = hy_n - hy_3 if not np.isnan(hy_n) else np.nan

    # ══════════════════════════════════════════════════════════════
    #  NUEVOS INDICADORES — PROXY PMI + PRODUCCIÓN
    # ══════════════════════════════════════════════════════════════

    # AWHMAN — Horas trabajadas en manufactura (proxy PMI de primer orden)
    # Cuando las empresas anticipan caída de demanda recortan horas ANTES de despedir
    # → indicador adelantado del ciclo manufacturero con lag ~2-3 meses vs nóminas
    awh_now = safe("AWHMAN", 0)
    awh_12m = safe("AWHMAN", 12)
    awh_3m  = safe("AWHMAN", 3)
    m["awhman"]         = awh_now
    m["awhman_yoy"]     = ((awh_now / awh_12m) - 1) * 100 if awh_12m else np.nan
    m["awhman_trend"]   = awh_now - awh_3m if not np.isnan(awh_now) and not np.isnan(awh_3m) else np.nan

    # DGORDER — Pedidos de bienes duraderos (proxy inversión empresarial)
    # Deflactamos por CPI para eliminar efecto precio
    dg_now_nom = safe("DGORDER", 0)
    dg_12m_nom = safe("DGORDER", 12)
    dg_3m_nom  = safe("DGORDER", 3)
    cpi_n_dg   = safe("CPIAUCSL", 0)
    cpi_12_dg  = safe("CPIAUCSL", 12)
    cpi_3_dg   = safe("CPIAUCSL", 3)
    dg_now = (dg_now_nom / cpi_n_dg)  if cpi_n_dg  else dg_now_nom
    dg_12m = (dg_12m_nom / cpi_12_dg) if cpi_12_dg else dg_12m_nom
    dg_3m  = (dg_3m_nom  / cpi_3_dg)  if cpi_3_dg  else dg_3m_nom
    m["durable_yoy"]   = ((dg_now / dg_12m) - 1) * 100 if dg_12m else np.nan
    m["durable_mom"]   = ((dg_now / dg_3m)  - 1) * 100 * 4 if dg_3m else np.nan  # anualizado

    # IPMAN — Producción industrial manufacturera
    # Coincidente pero captura amplitud del ciclo industrial
    ip_now = safe("IPMAN", 0)
    ip_12m = safe("IPMAN", 12)
    ip_3m  = safe("IPMAN", 3)
    m["ipman_yoy"]   = ((ip_now / ip_12m) - 1) * 100 if ip_12m else np.nan
    m["ipman_trend"] = ((ip_now / ip_3m)  - 1) * 100 * 4 if ip_3m else np.nan  # anualizado

    # HOUST — Viviendas iniciadas
    # Más adelantado que permisos (siguiente paso del proceso constructivo)
    houst_now = safe("HOUST", 0)
    houst_12m = safe("HOUST", 12)
    m["houst_yoy"] = ((houst_now / houst_12m) - 1) * 100 if houst_12m else np.nan

    # Curva 10Y-3M (Federal Reserve San Francisco: mejor predictor recesión)
    yc10_3m = safe("T10Y3M", 0)
    yc10_3m_6m = safe("T10Y3M", 6)
    m["yield_curve_10_3"]       = yc10_3m
    m["yield_curve_10_3_trend"] = yc10_3m - yc10_3m_6m if not np.isnan(yc10_3m) and not np.isnan(yc10_3m_6m) else np.nan

    # Composite proxy PMI:
    # Combina AWHMAN (horas), DGORDER (pedidos), NEWORDER (nuevos pedidos) y IC4WSA (claims)
    # Cada uno normalizado como z-score respecto a su media de 12m para que sean comparables
    def zscore_vs_12m(current, series_12m_vals):
        """Z-score del valor actual respecto a sus últimos 12 meses."""
        if np.isnan(current) or series_12m_vals is None:
            return np.nan
        mu  = np.nanmean(series_12m_vals)
        std = np.nanstd(series_12m_vals)
        return (current - mu) / std if std > 0 else 0.0

    # AWHMAN z-score (más alto = más horas = más actividad)
    awh_hist = [safe("AWHMAN", k) for k in range(1, 13)]
    awh_z    = zscore_vs_12m(awh_now, awh_hist)

    # IC4WSA z-score invertido (más claims = peor mercado laboral)
    ic_hist  = [safe("IC4WSA", k) for k in range(1, 13)]
    ic_z     = -zscore_vs_12m(m.get("jobless_claims", np.nan), ic_hist)

    # NEWORDER z-score
    no_hist  = [safe("NEWORDER", k) for k in range(1, 13)]
    no_z     = zscore_vs_12m(m.get("neworder_yoy", np.nan), no_hist)

    # DGORDER z-score
    dg_hist  = [safe("DGORDER", k) for k in range(1, 13)]
    dg_z     = zscore_vs_12m(dg_now, dg_hist)

    valid_z  = [z for z in [awh_z, ic_z, no_z, dg_z] if not np.isnan(z)]
    m["proxy_pmi"] = float(np.mean(valid_z)) if valid_z else np.nan
    # Escala aproximada: > 0.5 = expansión, < -0.5 = contracción, -1.5 = recesión

    return m


# ══════════════════════════════════════════════════════════════════
#  SCORING PONDERADO
#
#  MEJORAS vs versión anterior:
#   ✦ Pesos diferenciados por indicador (WEIGHTS en INDICATORS)
#   ✦ PMI ahora contribuye con más peso que sentimiento consumidor
#   ✦ Curva de tipos mantiene peso máximo (poder predictivo histórico)
#   ✦ Tasa de desempleo (nivel + tendencia) sustituye solo a nóminas
#   ✦ Permisos de construcción como indicador adelantado de tasas
#   ✦ Expectativas de inflación por separado del CPI realizado
# ══════════════════════════════════════════════════════════════════
def score_phase_core(m: dict, pcts: dict = None) -> dict:
    """
    Devuelve scores ponderados para cada fase + desglose de reglas.
    Cada regla devuelve (fase, puntos_brutos) y se multiplica por el peso.
    """
    phases = {
        "Recuperación":       0.0,
        "Sobrecalentamiento": 0.0,
        "Estanflación":       0.0,
        "Reflación/Recesión": 0.0,
    }
    R  = "Recuperación"
    S  = "Sobrecalentamiento"
    E  = "Estanflación"
    RF = "Reflación/Recesión"
    breakdown = []  # (descripción, fase, puntos_netos)

    def add(label, contributions: dict, weight=1.0, pct_key: str = None,
            invert_pct: bool = False):
        """
        contributions: {fase: puntos_brutos}
        pct_key: clave en pcts para escalar por percentil histórico.
        invert_pct: True si percentil alto es malo (desempleo, VIX, spreads).
        """
        if not contributions:
            return
        # Escala percentil: ajusta el peso según cuán extremo es el valor histórico
        if pcts and pct_key and pct_key in pcts:
            pct_val = pcts.get(pct_key, np.nan)
            pct_mult = percentile_scale(pct_val, invert=invert_pct)
        else:
            pct_mult = 0.7  # sin percentil → escala neutra
        eff_weight = weight * pct_mult
        for ph, pts in contributions.items():
            phases[ph] += pts * eff_weight
        breakdown.append((label, contributions, eff_weight))

    nan = np.nan

    # ── NUEVOS PEDIDOS MANUFACTUREROS REALES YoY (peso 1.8) ──────
    noy = m.get("neworder_yoy", nan)
    if not np.isnan(noy):
        if   noy > 8:   add(f"Pedidos Mfg {noy:+.1f}% muy fuerte",  {R:3, S:2},   1.8, "neworder_yoy")
        elif noy > 3:   add(f"Pedidos Mfg {noy:+.1f}% sólido",      {R:2, S:1},   1.8, "neworder_yoy")
        elif noy > 0:   add(f"Pedidos Mfg {noy:+.1f}% positivo",    {R:1},        1.8, "neworder_yoy")
        elif noy > -5:  add(f"Pedidos Mfg {noy:+.1f}% débil",       {RF:1, E:1},  1.8, "neworder_yoy")
        else:           add(f"Pedidos Mfg {noy:+.1f}% colapso",     {RF:3, E:2},  1.8, "neworder_yoy")

    nom = m.get("neworder_mom", nan)
    if not np.isnan(nom) and not np.isnan(noy):
        if   nom > noy + 2: add("Pedidos Mfg acelerando",  {R:2},       1.3)
        elif nom < noy - 3: add("Pedidos Mfg frenando",    {RF:1, E:1}, 1.3)

    # ── VENTAS MINORISTAS YoY (peso 1.5) — proxy consumo/servicios ───────
    ry = m.get("retail_yoy", nan)
    if not np.isnan(ry):
        if   ry > 6:   add(f"Retail {ry:+.1f}% boom consumo",       {R:2, S:2},   1.5, "retail_yoy")
        elif ry > 3:   add(f"Retail {ry:+.1f}% expansión",          {R:2, S:1},   1.5, "retail_yoy")
        elif ry > 0:   add(f"Retail {ry:+.1f}% positivo",           {R:1},        1.5, "retail_yoy")
        elif ry > -3:  add(f"Retail {ry:+.1f}% débil",              {RF:1, E:1},  1.5, "retail_yoy")
        else:          add(f"Retail {ry:+.1f}% contracción",         {RF:3, E:2},  1.5, "retail_yoy")

    # ── EMPLEO — NÓMINAS (peso 1.5) ──────────────────────────────
    pay = m.get("payroll_chg_3m", nan)
    if not np.isnan(pay):
        if   pay > 250: add(f"Nóminas {pay:.0f}k/mes fuerte",       {R:2, S:1},      1.5, "payroll_chg_3m")
        elif pay > 150: add(f"Nóminas {pay:.0f}k/mes sólido",       {R:2},           1.5, "payroll_chg_3m")
        elif pay > 75:  add(f"Nóminas {pay:.0f}k/mes moderado",     {R:1},           1.5, "payroll_chg_3m")
        elif pay > 0:   add(f"Nóminas {pay:.0f}k/mes débil",        {RF:1},          1.5, "payroll_chg_3m")
        else:           add(f"Nóminas {pay:.0f}k/mes negativo",     {RF:3, E:2},     1.5, "payroll_chg_3m")

    # ── DESEMPLEO — nivel + tendencia (peso 1.5) ─────────────────
    ur  = m.get("unrate", nan)
    dur = m.get("unrate_delta", nan)
    if not np.isnan(ur):
        if   ur < 4.0:  add(f"Desempleo {ur:.1f}% muy bajo",        {S:2, R:1},      1.5, "unrate", True)
        elif ur < 5.0:  add(f"Desempleo {ur:.1f}% bajo",            {R:1},           1.5, "unrate", True)
        elif ur > 6.0:  add(f"Desempleo {ur:.1f}% alto",            {RF:2, E:1},     1.5, "unrate", True)
    if not np.isnan(dur):
        if   dur > 0.5: add(f"Desempleo subiendo Δ+{dur:.1f}pp",    {RF:2, E:1},     1.5)
        elif dur < -0.3:add(f"Desempleo bajando Δ{dur:.1f}pp",      {R:1},           1.5)

    # ── SENTIMIENTO CONSUMIDOR (peso 0.8 — rezagado) ─────────────
    sc = m.get("sentiment_chg", nan)
    if not np.isnan(sc):
        if   sc > 8:    add(f"Sentiment +{sc:.1f} mejorando",       {R:1},           0.8)
        elif sc < -8:   add(f"Sentiment {sc:.1f} deteriorando",     {E:1, RF:1},     0.8)

    # ── CORE CPI (peso 1.8 — más limpio que CPI general) ────────────────
    # CPI general solo se muestra en pantalla, no entra en scoring
    core = m.get("core_yoy", nan)
    if not np.isnan(core):
        if   core < 2.0: add(f"Core CPI {core:.1f}% bajo objetivo",  {R:3, RF:1},  1.8, "core_yoy", True)
        elif core < 2.8: add(f"Core CPI {core:.1f}% moderado",       {R:1, S:1},   1.8, "core_yoy")
        elif core < 4.0: add(f"Core CPI {core:.1f}% elevado",        {S:2, E:1},   1.8, "core_yoy")
        else:            add(f"Core CPI {core:.1f}% muy alto",        {E:3, S:1},   1.8, "core_yoy")

    # Tendencia de inflación — ahora correctamente calculada:
    # reciente (últimos 6m anualizado) vs anterior (6m previos anualizado)
    it = m.get("inflation_trend", nan)
    if not np.isnan(it):
        if   it > 1.0:  add(f"Core CPI acelerando Δ{it:+.1f}pp",    {S:3, E:2},   1.5)
        elif it < -1.0: add(f"Core CPI frenando Δ{it:+.1f}pp",      {R:2, RF:2},  1.5)

    # ── EXPECTATIVAS INFLACIÓN 5Y BREAKEVEN (peso 1.2) ───────────
    ie  = m.get("inf_exp", nan)
    iec = m.get("inf_exp_chg", nan)
    if not np.isnan(ie):
        if   ie > 2.8:  add(f"Breakeven 5Y {ie:.2f}% alto",   {S:1, E:1}, 1.2, "inf_exp")
        elif ie < 1.5:  add(f"Breakeven 5Y {ie:.2f}% bajo",   {RF:1},     1.2, "inf_exp", True)
        # 1.5–2.8%: rango neutral, no añade señal
    if not np.isnan(iec) and abs(iec) > 0.2:
        if iec > 0:     add(f"Exp. inflación subiendo +{iec:.2f}pp",{E:1, S:1},     1.0)
        else:           add(f"Exp. inflación bajando {iec:.2f}pp",  {R:1, RF:1},    1.0)

    # ── FED FUNDS — cambio anual (peso 1.5) ──────────────────────
    fc = m.get("fed_chg", nan)
    if not np.isnan(fc):
        if   fc >  1.5: add(f"Fed hawkish {fc:+.2f}pp",            {S:2, E:1},      1.5)
        elif fc >  0.0: add(f"Fed endureciendo {fc:+.2f}pp",       {S:1},           1.5)
        elif fc < -1.5: add(f"Fed dovish {fc:+.2f}pp",             {RF:2},          1.5)
        elif fc <  0.0: add(f"Fed relajando {fc:+.2f}pp",          {RF:1},          1.5)

    # ── CURVA DE TIPOS 10Y-2Y (peso 2.0 — mejor predictor hist.) ─
    yc = m.get("yield_curve", nan)
    if not np.isnan(yc):
        if   yc < -0.75: add(f"Curva {yc:+.2f}% profundamente invertida", {RF:5},  2.0, "yield_curve", True)
        elif yc < -0.25: add(f"Curva {yc:+.2f}% invertida",               {RF:3, E:1}, 2.0, "yield_curve", True)
        elif yc <  0.25: add(f"Curva {yc:+.2f}% plana",                   {RF:1, E:1}, 2.0, "yield_curve")
        elif yc <  1.00: add(f"Curva {yc:+.2f}% positiva moderada",       {R:1, S:1},  2.0, "yield_curve")
        else:            add(f"Curva {yc:+.2f}% empinada",                 {R:3},       2.0, "yield_curve")

    # ── HY SPREAD — stress crédito (peso 1.5) ────────────────────
    hy  = m.get("hy_spread", nan)
    cs  = m.get("credit_stress", nan)
    if not np.isnan(hy):
        if   hy < 3.0:  add(f"HY spread {hy:.2f}% mínimos hist.",  {R:1, S:1},      1.5, "hy_spread", True)
        elif hy > 6.0:  add(f"HY spread {hy:.2f}% elevado",        {RF:2, E:1},     1.5, "hy_spread", True)
    if not np.isnan(cs):
        if   cs > 1.5:  add(f"Crédito ampliando +{cs:.2f}pp",      {RF:2},          1.5)
        elif cs < -1.0: add(f"Crédito comprimiendo {cs:.2f}pp",    {R:1},           1.5)

    # ── VIX (peso 1.2) ───────────────────────────────────────────
    vix = m.get("vix", nan)
    if not np.isnan(vix):
        if   vix > 35:  add(f"VIX {vix:.0f} — pánico",            {RF:2, E:1},     1.2, "vix", True)
        elif vix > 25:  add(f"VIX {vix:.0f} — elevado",           {E:1},           1.2, "vix", True)
        elif vix < 14:  add(f"VIX {vix:.0f} — complacencia",      {R:1, S:1},      1.2, "vix", True)

    # ── PERMISOS CONSTRUCCIÓN (peso 1.0) ─────────────────────────
    py = m.get("permit_yoy", nan)
    if not np.isnan(py):
        if   py > 10:   add(f"Permisos {py:+.1f}% boom",           {R:2, S:1},      1.0, "permit_yoy")
        elif py >  0:   add(f"Permisos {py:+.1f}% positivo",       {R:1},           1.0, "permit_yoy")
        elif py < -15:  add(f"Permisos {py:+.1f}% colapso",        {RF:2, E:1},     1.0, "permit_yoy", True)
        else:           add(f"Permisos {py:+.1f}% negativo",        {RF:1},          1.0, "permit_yoy", True)


    # ── CURVA 10Y-3M (peso 2.2 — mejor predictor recesión) ───────
    # La Fed de San Francisco demostró que predice recesiones
    # con mayor fiabilidad que la 10Y-2Y desde 1960
    yc2 = m.get("yield_curve_10_3", nan)
    if not np.isnan(yc2):
        if   yc2 < -1.00: add(f"Curva 10Y-3M {yc2:+.2f}% inversión severa",  {RF:6},       2.2, "yield_curve", True)
        elif yc2 < -0.50: add(f"Curva 10Y-3M {yc2:+.2f}% invertida",          {RF:4, E:1},  2.2, "yield_curve", True)
        elif yc2 <  0.00: add(f"Curva 10Y-3M {yc2:+.2f}% plana/leve inv.",    {RF:2, E:1},  2.2, "yield_curve")
        elif yc2 <  1.00: add(f"Curva 10Y-3M {yc2:+.2f}% positiva",           {R:1, S:1},   2.2, "yield_curve")
        else:             add(f"Curva 10Y-3M {yc2:+.2f}% empinada",            {R:3},        2.2, "yield_curve")

    # ── PETICIONES DESEMPLEO (peso 1.6 — adelantado semanal) ─────
    ic_yoy  = m.get("jobless_claims_yoy",  nan)
    ic_vel  = m.get("jobless_claims_trend", nan)
    if not np.isnan(ic_yoy):
        if   ic_yoy >  30: add(f"Claims +{ic_yoy:.0f}% YoY — deterioro severo",  {RF:3, E:2}, 1.6, "payroll_chg_3m", True)
        elif ic_yoy >  10: add(f"Claims +{ic_yoy:.0f}% YoY — subiendo",           {RF:2},      1.6, "payroll_chg_3m", True)
        elif ic_yoy <  -10: add(f"Claims {ic_yoy:.0f}% YoY — mercado laboral fuerte", {R:2},   1.6, "payroll_chg_3m")
        elif ic_yoy <   0: add(f"Claims {ic_yoy:.0f}% YoY — mejorando",           {R:1},       1.6, "payroll_chg_3m")
    # Velocidad claims: ¿subiendo o bajando en últimos 3 meses?
    if not np.isnan(ic_vel):
        if   ic_vel >  15: add(f"Claims acelerando +{ic_vel:.0f}k/3m",   {RF:2, E:1},  1.2)
        elif ic_vel <  -15: add(f"Claims cayendo {ic_vel:.0f}k/3m",       {R:2},         1.2)

    # ── IG SPREAD (peso 1.2 — confirma señal HY) ─────────────────
    ig  = m.get("ig_spread", nan)
    igs = m.get("ig_stress", nan)
    if not np.isnan(ig):
        if   ig > 1.80: add(f"IG Spread {ig:.2f}% — estrés crédito IG",  {RF:2, E:1},  1.2)
        elif ig < 0.90: add(f"IG Spread {ig:.2f}% — crédito excelente",   {R:1, S:1},   1.2)
    if not np.isnan(igs):
        if   igs >  0.40: add(f"IG ampliando +{igs:.2f}pp/6m",  {RF:2},   1.0)
        elif igs < -0.30: add(f"IG comprimiendo {igs:.2f}pp/6m", {R:1},    1.0)

    # ══════════════════════════════════════════════════════════════
    # MEJORA 2: VELOCIDAD DE CAMBIO
    # Los indicadores con tendencia favorable pesan más.
    # Los que están deteriorando pese a niveles ok, señalan precaución.
    # ══════════════════════════════════════════════════════════════

    # Velocidad nóminas
    pay_vel = m.get("payroll_velocity", nan)
    if not np.isnan(pay_vel):
        if   pay_vel >  50: add(f"Empleo acelerando +{pay_vel:.0f}k/m",  {R:2},       1.4)
        elif pay_vel < -50: add(f"Empleo frenando {pay_vel:.0f}k/m",     {RF:2, E:1}, 1.4)
        elif pay_vel < -25: add(f"Empleo desacelerando {pay_vel:.0f}k/m", {RF:1},      1.0)

    # Velocidad inflación (3m vs 3m anterior, anualizado)
    inf_vel = m.get("inflation_velocity", nan)
    if not np.isnan(inf_vel):
        if   inf_vel >  1.5: add(f"Inflación acelerando Δ{inf_vel:+.1f}pp",  {S:2, E:2}, 1.6)
        elif inf_vel >  0.5: add(f"Inflación repuntando Δ{inf_vel:+.1f}pp",  {S:1, E:1}, 1.2)
        elif inf_vel < -1.5: add(f"Inflación cayendo fuerte Δ{inf_vel:+.1f}pp", {R:2, RF:1}, 1.6)
        elif inf_vel < -0.5: add(f"Inflación moderándose Δ{inf_vel:+.1f}pp",  {R:1, RF:1}, 1.2)

    # Velocidad curva de tipos (¿empinándose o aplanándose?)
    crv_vel = m.get("curve_velocity", nan)
    if not np.isnan(crv_vel):
        if   crv_vel >  0.30: add(f"Curva empinándose +{crv_vel:.2f}pp/3m",   {R:2},       1.5)
        elif crv_vel < -0.30: add(f"Curva aplanándose {crv_vel:.2f}pp/3m",    {RF:2, E:1}, 1.5)

    # Velocidad HY spread
    hy_vel = m.get("hy_velocity", nan)
    if not np.isnan(hy_vel):
        if   hy_vel >  0.80: add(f"Crédito deteriorando rápido +{hy_vel:.2f}pp/3m", {RF:3},   1.5)
        elif hy_vel >  0.30: add(f"Crédito ampliando +{hy_vel:.2f}pp/3m",           {RF:1},   1.2)
        elif hy_vel < -0.50: add(f"Crédito comprimiendo {hy_vel:.2f}pp/3m",         {R:2},    1.5)

    # ══════════════════════════════════════════════════════════════
    # MEJORA 3: PATRONES COMBINADOS (no-lineales)
    # Ciertas combinaciones de indicadores tienen significado
    # histórico específico que va más allá de la suma de sus partes.
    # Peso alto (2.5-3.0) porque son señales de régimen confirmadas.
    # ══════════════════════════════════════════════════════════════

    # Patrón 1: TRAMPA DE COMPLACENCIA PRE-RECESIÓN
    # Curva invertida + spreads comprimidos + VIX bajo = mercado no
    # ha descontado aún lo que la curva está señalando (2006-07, 2019)
    yc_ok   = not np.isnan(yc)  and yc  < -0.25
    yc2_ok  = not np.isnan(yc2) and yc2 < -0.25
    hy_ok   = not np.isnan(hy)  and hy  < 4.0
    vix_ok  = not np.isnan(vix) and vix < 20
    if yc_ok and yc2_ok and hy_ok and vix_ok:
        add("⚠ PATRÓN: Curva inv. + spreads bajos + VIX bajo (complacencia pre-recesión)",
            {RF: 4}, 2.8)

    # Patrón 2: EXPANSIÓN LIMPIA CONFIRMADA
    # Curva positiva + crédito comprimido + empleo fuerte + inflación moderada
    yc_pos  = not np.isnan(yc)   and yc   > 0.50
    yc2_pos = not np.isnan(yc2)  and yc2  > 0.50
    hy_low  = not np.isnan(hy)   and hy   < 3.5
    pay_ok  = not np.isnan(pay)  and pay  > 100
    core_ok = not np.isnan(core) and core < 3.0
    if yc_pos and yc2_pos and hy_low and pay_ok and core_ok:
        add("✓ PATRÓN: Expansión limpia confirmada (curva+crédito+empleo+inflación)",
            {R: 4}, 2.8)

    # Patrón 3: ESTANFLACIÓN CLÁSICA
    # Inflación alta + crecimiento cayendo + Fed subiendo
    core_high = not np.isnan(core) and core > 4.0
    noy_weak  = not np.isnan(noy)  and noy  < 2.0
    fc_ok_s   = not np.isnan(fc)   and fc   > 1.0
    if core_high and noy_weak and fc_ok_s:
        add("⚠ PATRÓN: Estanflación (inflación alta + actividad débil + Fed hawkish)",
            {E: 5, S: 1}, 3.0)

    # Patrón 4: CRISIS DE CRÉDITO ACTIVA
    # HY spread muy alto + IG ampliando + VIX elevado + curva invertida
    hy_crisis  = not np.isnan(hy)  and hy  > 6.0
    ig_crisis  = not np.isnan(ig)  and ig  > 1.80
    vix_high   = not np.isnan(vix) and vix > 28
    yc_inv     = not np.isnan(yc)  and yc  < 0.0
    if hy_crisis and ig_crisis and vix_high and yc_inv:
        add("⚠ PATRÓN: Crisis de crédito activa (HY+IG+VIX+curva)",
            {RF: 6}, 3.0)

    # Patrón 5: PICO DE CICLO (SOBRECALENTAMIENTO TARDÍO)
    # Desempleo muy bajo + inflación subiendo + curva aplanándose + Fed hawkish
    ur_low   = not np.isnan(ur)     and ur     < 4.0
    inf_up   = not np.isnan(it)     and it     > 0.5
    crv_flat = not np.isnan(crv_vel) and crv_vel < -0.15
    fed_up   = not np.isnan(fc)     and fc     > 0.5
    if ur_low and inf_up and crv_flat and fed_up:
        add("⚠ PATRÓN: Pico de ciclo (empleo pleno + inflación subiendo + curva aplanándose)",
            {S: 3, E: 2}, 2.5)

    # Patrón 6: RECUPERACIÓN TEMPRANA CONFIRMADA
    # Claims cayendo + curva empinándose + crédito comprimiéndose + Fed dovish
    ic_falling = not np.isnan(ic_yoy) and ic_yoy  < -5
    crv_steep  = not np.isnan(crv_vel) and crv_vel > 0.15
    hy_comp    = not np.isnan(hy_vel)  and hy_vel  < -0.20
    fed_down   = not np.isnan(fc)     and fc       < 0.0
    if ic_falling and crv_steep and hy_comp and fed_down:
        add("✓ PATRÓN: Recuperación temprana confirmada (claims+curva+crédito+Fed)",
            {R: 5}, 2.8)

    # ══════════════════════════════════════════════════════════════
    #  NUEVOS INDICADORES — SCORING
    # ══════════════════════════════════════════════════════════════

    # ── PROXY PMI COMPUESTO (z-score, pesos como ISM manufacturero)
    # Es el indicador más parecido al ISM que podemos construir con FRED
    pmi_z = m.get("proxy_pmi", nan)
    if not np.isnan(pmi_z):
        if   pmi_z >  1.2: add(f"Proxy PMI z={pmi_z:+.2f} expansión fuerte", {R:3, S:2}, 1.9, "proxy_pmi")
        elif pmi_z >  0.4: add(f"Proxy PMI z={pmi_z:+.2f} expansión",        {R:2, S:1}, 1.9, "proxy_pmi")
        elif pmi_z > -0.4: add(f"Proxy PMI z={pmi_z:+.2f} neutro",           {RF:1},     1.0)
        elif pmi_z > -1.2: add(f"Proxy PMI z={pmi_z:+.2f} contracción",      {RF:2, E:1},1.9, "proxy_pmi")
        else:              add(f"Proxy PMI z={pmi_z:+.2f} recesión mfg",     {RF:4, E:2},1.9, "proxy_pmi")

    # ── HORAS MANUFACTURERAS (AWHMAN) — proxy PMI directo ─────────
    # La Fed de NY usa AWHMAN como componente de su índice líder
    awh_yoy = m.get("awhman_yoy", nan)
    awh_tr  = m.get("awhman_trend", nan)
    if not np.isnan(awh_yoy):
        if   awh_yoy >  1.5: add(f"Horas Mfg {awh_yoy:+.1f}% expansión",    {R:2, S:1}, 1.7, "awhman_yoy")
        elif awh_yoy >  0.0: add(f"Horas Mfg {awh_yoy:+.1f}% positivo",     {R:1},      1.7, "awhman_yoy")
        elif awh_yoy > -1.5: add(f"Horas Mfg {awh_yoy:+.1f}% débil",        {RF:1, E:1},1.7, "awhman_yoy")
        else:                add(f"Horas Mfg {awh_yoy:+.1f}% colapso",      {RF:3, E:2},1.7, "awhman_yoy")
    # Tendencia reciente (acelerando/frenando en últimos 3m)
    if not np.isnan(awh_tr):
        if   awh_tr >  0.3: add(f"Horas Mfg acelerando +{awh_tr:.2f}h",  {R:1},      1.2)
        elif awh_tr < -0.3: add(f"Horas Mfg frenando {awh_tr:.2f}h",     {RF:1, E:1},1.2)

    # ── PEDIDOS BIENES DURADEROS (DGORDER) — proxy inversión capex ─
    dg_yoy = m.get("durable_yoy", nan)
    dg_mom = m.get("durable_mom", nan)
    if not np.isnan(dg_yoy):
        if   dg_yoy >  8: add(f"Duraderos {dg_yoy:+.1f}% boom",          {R:3, S:1}, 1.6, "durable_yoy")
        elif dg_yoy >  2: add(f"Duraderos {dg_yoy:+.1f}% positivo",      {R:2},      1.6, "durable_yoy")
        elif dg_yoy > -3: add(f"Duraderos {dg_yoy:+.1f}% flojo",         {RF:1},     1.0)
        else:             add(f"Duraderos {dg_yoy:+.1f}% contracción",   {RF:2, E:1},1.6, "durable_yoy")

    # ── PRODUCCIÓN INDUSTRIAL MANUFACTURERA (IPMAN) ────────────────
    ip_yoy = m.get("ipman_yoy", nan)
    if not np.isnan(ip_yoy):
        if   ip_yoy >  4: add(f"Prod. Ind. {ip_yoy:+.1f}% fuerte",       {R:2, S:2}, 1.4, "ipman_yoy")
        elif ip_yoy >  0: add(f"Prod. Ind. {ip_yoy:+.1f}% positiva",     {R:1},      1.4, "ipman_yoy")
        elif ip_yoy > -3: add(f"Prod. Ind. {ip_yoy:+.1f}% débil",        {RF:1, E:1},1.4, "ipman_yoy")
        else:             add(f"Prod. Ind. {ip_yoy:+.1f}% recesión",     {RF:3, E:2},1.4, "ipman_yoy")

    # ── VIVIENDAS INICIADAS (HOUST) — más adelantado que permisos ──
    houst_yoy = m.get("houst_yoy", nan)
    if not np.isnan(houst_yoy):
        if   houst_yoy >  12: add(f"Viviendas {houst_yoy:+.1f}% boom",       {R:3, S:1}, 1.1, "houst_yoy")
        elif houst_yoy >   0: add(f"Viviendas {houst_yoy:+.1f}% positivo",   {R:1},      1.1, "houst_yoy")
        elif houst_yoy > -15: add(f"Viviendas {houst_yoy:+.1f}% bajando",    {RF:1, E:1},1.1, "houst_yoy")
        else:                 add(f"Viviendas {houst_yoy:+.1f}% desplome",   {RF:2, E:2},1.1, "houst_yoy")

    # ── CURVA 10Y-3M (Fed SF: mejor predictor recesión, umbral -0.5%) ──
    yc_10_3 = m.get("yield_curve_10_3", nan)
    if not np.isnan(yc_10_3):
        if   yc_10_3 < -1.0: add(f"Curva 10Y3M {yc_10_3:+.2f}% inversión profunda", {RF:5},      2.2, "yield_curve_10_3", True)
        elif yc_10_3 < -0.5: add(f"Curva 10Y3M {yc_10_3:+.2f}% invertida",          {RF:3, E:1}, 2.2, "yield_curve_10_3", True)
        elif yc_10_3 <  0.0: add(f"Curva 10Y3M {yc_10_3:+.2f}% plana-negativa",     {RF:1, E:1}, 2.2, "yield_curve_10_3")
        elif yc_10_3 <  1.0: add(f"Curva 10Y3M {yc_10_3:+.2f}% positiva",           {R:1, S:1},  2.2, "yield_curve_10_3")
        else:                add(f"Curva 10Y3M {yc_10_3:+.2f}% muy empinada",        {R:3},       2.2, "yield_curve_10_3")

    # ── IG SPREAD — confirma o diverge del HY (señal de calidad) ───
    ig_sp = m.get("ig_spread", nan)
    ig_st = m.get("ig_stress", nan)
    if not np.isnan(ig_sp):
        if   ig_sp < 0.9: add(f"IG spread {ig_sp:.2f}% mínimos",        {R:1, S:1},  1.2, "ig_spread", True)
        elif ig_sp > 2.0: add(f"IG spread {ig_sp:.2f}% stress",         {RF:2, E:1}, 1.2, "ig_spread", True)
    if not np.isnan(ig_st):
        if   ig_st > 0.5: add(f"IG ampliando +{ig_st:.2f}pp",           {RF:2},      1.2)
        elif ig_st < -0.3:add(f"IG comprimiendo {ig_st:.2f}pp",         {R:1},       1.2)

    # ── NORMALIZACIÓN & CONFIANZA ────────────────────────────────
    total = sum(phases.values())
    if total > 0:
        scores_norm = {k: v / total * 100 for k, v in phases.items()}
    else:
        scores_norm = {k: 25.0 for k in phases}

    max_phase = max(scores_norm, key=scores_norm.get)
    sorted_scores = sorted(scores_norm.values(), reverse=True)
    # Protección contra división por cero: si el score máximo es 0 o muy pequeño
    top = sorted_scores[0]
    second = sorted_scores[1] if len(sorted_scores) > 1 else 0.0
    confidence = (top - second) / top if top > 0.01 else 0.0

    # Fase secundaria: la de mayor score excluyendo la principal
    secondary_candidates = [k for k, v in scores_norm.items()
                            if k != max_phase and v == second]
    secondary = secondary_candidates[0] if secondary_candidates else [
        k for k in scores_norm if k != max_phase][0]

    return {
        "phase":     max_phase,
        "secondary": secondary,
        "scores":    scores_norm,
        "raw":       phases,
        "confidence": confidence,
        "breakdown": breakdown,
    }


# ══════════════════════════════════════════════════════════════════
#  TABLAS DE RECOMENDACIONES
# ══════════════════════════════════════════════════════════════════
# Formato: (activo, rating, razón)
# Rating: +3=+++  +2=++  +1=+  0=0  -1=-  -2=--  -3=---

FIXED_INCOME_RECS = {
    "Recuperación": [
        ("Gubernamental",    0,  "Neutral — tipos normalizando, sin catalizador"),
        ("Corporativo IG",   3,  "Compresión spreads + upgrades crediticios"),
        ("High Yield",       3,  "Mejora fundamentals + carry atractivo"),
        ("TIPS",             0,  "Inflación aún baja — sin ventaja vs. nominal"),
        ("Emergentes RF",    2,  "Apetito riesgo + crecimiento global"),
        ("Municipal",        0,  "Mejora fiscal pero sin ventaja clara"),
        ("MBS",              2,  "Estabilidad + spreads atractivos"),
        ("RF Corto Plazo",  -1,  "Tasas bajas limitan retorno total"),
        ("RF Largo Plazo",   2,  "Inflación controlada — duration funciona"),
    ],
    "Sobrecalentamiento": [
        ("Gubernamental",   -1,  "Tipos subiendo — duración penaliza"),
        ("Corporativo IG",   1,  "Calidad ok pero spreads ajustados"),
        ("High Yield",       0,  "Carry atractivo vs. riesgo tipos altos"),
        ("TIPS",             3,  "Inflación real protege — ideal en esta fase"),
        ("Emergentes RF",   -1,  "Fed hawkish drena liquidez global"),
        ("Municipal",        2,  "Tax-equivalent yield muy elevado"),
        ("MBS",             -1,  "Prepagos caen + tasas suben — penaliza"),
        ("RF Corto Plazo",   3,  "Tasas altas + máxima flexibilidad"),
        ("RF Largo Plazo",  -3,  "Duration muy negativa con tipos subiendo"),
    ],
    "Estanflación": [
        ("Gubernamental",    3,  "Safe haven + eventual pivot dovish"),
        ("Corporativo IG",  -1,  "Spreads ampliándose — recesión ahead"),
        ("High Yield",      -3,  "Worst case: inflación alta + defaults"),
        ("TIPS",             2,  "Inflación alta compensa algo"),
        ("Emergentes RF",   -3,  "Capital flight + commodity shock"),
        ("Municipal",        3,  "Tax-exempt + estabilidad relativa"),
        ("MBS",             -1,  "Tasas volátiles, prepagos inciertos"),
        ("RF Corto Plazo",   2,  "Preservación capital + liquidez"),
        ("RF Largo Plazo",   0,  "Inflación vs. eventual recesión"),
    ],
    "Reflación/Recesión": [
        ("Gubernamental",    3,  "Flight to quality — tasas caen con recesión"),
        ("Corporativo IG",   0,  "Spreads widening compensa la calidad"),
        ("High Yield",      -2,  "Riesgo default aumenta con desaceleración"),
        ("TIPS",             1,  "Tasas reales negativas — ligera protección"),
        ("Emergentes RF",   -1,  "Capital flight generalizado — selectivo"),
        ("Municipal",        3,  "Tax-exempt + calidad defensiva sólida"),
        ("MBS",              2,  "Tasas bajas favorecen prepagos"),
        ("RF Corto Plazo",  -1,  "Reinversión en tasas ya caídas"),
        ("RF Largo Plazo",   3,  "Duration positiva — máxima ganancia"),
    ],
}

EQUITY_RECS = {
    "Recuperación": [
        ("Tecnología",           3,  "Crecimiento + tasas bajas = múltiplos altos"),
        ("Salud",                2,  "Estable, no líder pero sólido"),
        ("Financiero",           2,  "NIM expansion + calidad crediticia mejora"),
        ("Consumo Discrecional", 3,  "Mejora empleo + confianza en alza"),
        ("Consumo Básico",       0,  "Defensivo — underperform en expansión"),
        ("Industria",            2,  "Capex cycle arrancando"),
        ("Energía",              1,  "Demand recovery gradual"),
        ("Materiales",           2,  "Demanda construcción + industrial"),
        ("Utilities",           -1,  "Underperform — tasas suben"),
        ("Inmobiliario (REITs)", 0,  "Neutral — tasas normalizando"),
        ("Comunicaciones",       2,  "Publicidad recupera + streaming"),
        ("Small Cap",            3,  "Máximo beneficio de ciclo expansivo"),
        ("Emergentes RV",        3,  "Crecimiento + commodities + flujos"),
        ("Commodities ex Oro",   2,  "Demanda industrial recuperando"),
        ("Oro",                  0,  "Tasas reales subiendo — sin atractivo"),
    ],
    "Sobrecalentamiento": [
        ("Tecnología",           2,  "Seculares fuertes pero valuación cara"),
        ("Salud",                0,  "Neutral — defensivo no lidera aquí"),
        ("Financiero",           1,  "NIM alto pero curva aplana"),
        ("Consumo Discrecional", 1,  "Fuerte pero inflación presiona márgenes"),
        ("Consumo Básico",      -1,  "Pricing power limitado vs. inflación"),
        ("Industria",            2,  "Capex en peak — óptimo"),
        ("Energía",              3,  "Inflación + supply constraints = winner"),
        ("Materiales",           3,  "Pricing power + demanda fuerte"),
        ("Utilities",           -3,  "Tasas altas destruyen valuación"),
        ("Inmobiliario (REITs)",-1,  "Cap rates suben con tasas"),
        ("Comunicaciones",       2,  "Pricing power + publicidad fuerte"),
        ("Small Cap",            1,  "Beneficia pero riesgo tasas alto"),
        ("Emergentes RV",       -1,  "Fed hawkish drena flujos EM"),
        ("Commodities ex Oro",   3,  "Inflación + demanda fuerte — máximo"),
        ("Oro",                  2,  "Hedge inflación funciona aquí"),
    ],
    "Estanflación": [
        ("Tecnología",          -1,  "Valuación alta + gasto IT recortado"),
        ("Salud",                3,  "No-cíclico + pricing power inelástico"),
        ("Financiero",          -3,  "NIM + credit losses + regulación"),
        ("Consumo Discrecional",-3,  "Peor entorno posible para el sector"),
        ("Consumo Básico",       2,  "Pricing power real + demanda inelástica"),
        ("Industria",           -1,  "Demanda débil + costos laborales altos"),
        ("Energía",              2,  "Commodities + inflación persistente"),
        ("Materiales",           2,  "Inflación favorece aunque demanda débil"),
        ("Utilities",            3,  "Defensivo + pricing regulado = refugio"),
        ("Inmobiliario (REITs)",-3,  "Tasas altas + demanda colapsa"),
        ("Comunicaciones",       0,  "Publicidad débil vs. pricing power"),
        ("Small Cap",           -2,  "Alta sensibilidad a ciclo — evitar"),
        ("Emergentes RV",       -3,  "Worst case para mercados emergentes"),
        ("Commodities ex Oro",   2,  "Inflación favorece aunque selectivo"),
        ("Oro",                  3,  "Única protección real efectiva"),
    ],
    "Reflación/Recesión": [
        ("Tecnología",          -1,  "Gasto IT recortado + múltiplos caros"),
        ("Salud",                2,  "Defensivo + demanda inelástica"),
        ("Financiero",           0,  "NIM comprimido pero eventual mejora"),
        ("Consumo Discrecional",-3,  "Caída demanda + desempleo sube"),
        ("Consumo Básico",       3,  "Resiliencia ingresos + pricing defensivo"),
        ("Industria",           -1,  "Capex recortado drásticamente"),
        ("Energía",              0,  "Depende de la severidad recesiva"),
        ("Materiales",          -1,  "Demanda industrial colapsa"),
        ("Utilities",            2,  "Dividendos + bond proxy — estable"),
        ("Inmobiliario (REITs)", 1,  "Yield atractivo si tasas bajan"),
        ("Comunicaciones",      -1,  "Publicidad colapsa con GDP"),
        ("Small Cap",           -2,  "Muy expuestos a contracción crédito"),
        ("Emergentes RV",        0,  "Defensivos ok, cíclicos evitar"),
        ("Commodities ex Oro",  -3,  "Demanda global se desploma"),
        ("Oro",                  3,  "Safe haven + tasas reales negativas"),
    ],
}



def score_phase(m: dict, pcts: dict = None) -> dict:
    """Wrapper público: calcula percentiles si no se pasan y llama a score_phase_core."""
    return score_phase_core(m, pcts or {})



# ══════════════════════════════════════════════════════════════════
#  REGRESIÓN LOGÍSTICA MULTINOMIAL
#
#  En lugar de umbrales manuales, entrenamos un clasificador sobre
#  datos históricos reales de FRED etiquetados con fases del ciclo.
#
#  METODOLOGÍA:
#   1. Descargamos 20 años de datos (ya los tenemos)
#   2. Etiquetamos cada mes con su fase real (cronología NBER +
#      ciclo inflación Fed) — con publication lag de 6 semanas
#   3. Construimos features: las mismas métricas que score_phase_core
#      pero normalizadas como percentiles históricos
#   4. Entrenamos LogisticRegression multinomial (sklearn)
#   5. Guardamos modelo en disco; recargamos en ejecuciones futuras
#   6. En cada ejecución, combinamos score tradicional + probas
#      del modelo logístico para obtener score híbrido
#
#  VENTAJAS SOBRE REGLAS MANUALES:
#   - Los pesos los aprende de los datos reales, no los ponemos nosotros
#   - Captura interacciones entre indicadores (curva invertida +
#     claims subiendo juntos predicen mucho mejor que cada uno solo)
#   - Produce probabilidades calibradas [0,1] en vez de puntos arbitrarios
#   - Genera su propia medida de confianza (max_proba - second_proba)
# ══════════════════════════════════════════════════════════════════

PHASE_LABELS = {
    "Recuperación":       0,
    "Sobrecalentamiento": 1,
    "Estanflación":       2,
    "Reflación/Recesión": 3,
}
PHASE_NAMES = {v: k for k, v in PHASE_LABELS.items()}

# Cronología histórica de fases para entrenamiento
# Basada en: NBER recessions + ciclos CPI Fed + Investment Clock académico

# ══════════════════════════════════════════════════════════════════════
#  MOTOR LOGÍSTICO
#  Entrena sobre datos históricos REALES de FRED etiquetados con
#  cronología NBER. Sin datos sintéticos, sin blend, sin mezclas.
#
#  Etiquetado de fases (publication lag ~6 semanas = 2 meses offset):
#  Los datos de mes T se etiquetan con la fase real de T+2.
#  Así el modelo aprende lo que el mercado veía en cada momento,
#  no lo que se sabe hoy con revisiones posteriores.
# ══════════════════════════════════════════════════════════════════════

# Cronología histórica de fases — fuente: NBER + ciclos CPI Fed
# Formato: (inicio, fin, fase)
NBER_PHASES = [
    ("2004-01", "2004-12", "Recuperación"),
    ("2005-01", "2006-06", "Sobrecalentamiento"),
    ("2006-07", "2007-06", "Sobrecalentamiento"),
    ("2007-07", "2008-06", "Estanflación"),
    ("2008-07", "2009-06", "Reflación/Recesión"),
    ("2009-07", "2010-12", "Recuperación"),
    ("2011-01", "2011-12", "Sobrecalentamiento"),
    ("2012-01", "2013-12", "Recuperación"),
    ("2014-01", "2015-06", "Sobrecalentamiento"),
    ("2015-07", "2016-06", "Reflación/Recesión"),
    ("2016-07", "2017-06", "Recuperación"),
    ("2017-07", "2018-12", "Sobrecalentamiento"),
    ("2019-01", "2019-12", "Reflación/Recesión"),
    ("2020-01", "2020-03", "Reflación/Recesión"),
    ("2020-04", "2021-06", "Recuperación"),
    ("2021-07", "2021-12", "Sobrecalentamiento"),
    ("2022-01", "2022-12", "Estanflación"),
    ("2023-01", "2023-06", "Reflación/Recesión"),
    ("2023-07", "2024-06", "Recuperación"),
    ("2024-07", "2025-03", "Recuperación"),
]

PHASE_INT = {
    "Recuperación":       0,
    "Sobrecalentamiento": 1,
    "Estanflación":       2,
    "Reflación/Recesión": 3,
}
INT_PHASE = {v: k for k, v in PHASE_INT.items()}

# Features que usa el modelo logístico
# Todas son métricas derivadas calculadas por calculate_metrics_at()
# Se normalizan con StandardScaler antes del entrenamiento
FEATURES = [
    "neworder_yoy",        # nuevos pedidos mfg YoY (real)
    "retail_yoy",          # ventas minoristas YoY
    "durable_yoy",         # bienes duraderos YoY
    "ipman_yoy",           # producción industrial YoY
    "awhman_yoy",          # horas mfg YoY — proxy PMI
    "proxy_pmi",           # composite z-score (mejor proxy ISM)
    "payroll_chg_3m",      # variación nóminas 3m
    "unrate",              # tasa desempleo nivel
    "unrate_delta",        # tendencia desempleo (sube = malo)
    "jobless_claims_yoy",  # peticiones desempleo YoY
    "core_yoy",            # Core CPI YoY
    "inflation_trend",     # aceleración inflación (reciente - anterior)
    "inflation_velocity",  # velocidad 3m
    "inf_exp",             # breakeven inflación 5Y
    "inf_exp_chg",         # cambio en expectativas
    "fed_funds",           # nivel Fed Funds
    "fed_chg",             # cambio anual Fed Funds
    "yield_curve",         # curva 10Y-2Y
    "yield_curve_10_3",    # curva 10Y-3M (mejor predictor recesión)
    "curve_velocity",      # velocidad de cambio curva
    "hy_spread",           # HY credit spread
    "hy_velocity",         # velocidad HY spread
    "ig_spread",           # IG credit spread
    "ig_stress",           # cambio IG spread
    "permit_yoy",          # permisos construcción YoY
    "houst_yoy",           # viviendas iniciadas YoY
    "sentiment_chg",       # cambio sentimiento consumidor
    "vix",                 # VIX nivel
]

MODEL_FILE = "ic_logistic_model.pkl"


def build_phase_map() -> dict:
    """Construye mapa fecha→etiqueta desde cronología NBER."""
    phase_map = {}
    for start_s, end_s, phase in NBER_PHASES:
        period = pd.date_range(start_s, end_s, freq="MS")
        for d in period:
            phase_map[d] = PHASE_INT[phase]
    return phase_map


def build_dataset(data: dict) -> tuple:
    """
    Construye X, y para entrenamiento usando datos reales de FRED.

    Para cada mes histórico etiquetado:
      - Calcula las métricas usando solo datos disponibles hasta ese mes
        (evita look-ahead bias)
      - Aplica publication lag de 2 meses: los datos de mes T
        se etiquetan con la fase de T+2

    Devuelve (X, y, fechas) o (None, None, None) si hay pocos datos.
    """
    phase_map = build_phase_map()

    # Serie de referencia para iterar fechas disponibles
    ref = data.get("CPILFESL", pd.Series(dtype=float))
    if ref.empty or len(ref) < 36:
        return None, None, None

    latest = ref.index[-1]
    X_rows, y_rows, dates = [], [], []

    for target_date, label in phase_map.items():
        # ¿Tenemos al menos 14 meses de historia antes de esta fecha?
        months_back = int(round(
            (latest.year - target_date.year) * 12 +
            (latest.month - target_date.month)
        ))
        if months_back < 14:
            continue  # datos demasiado recientes

        # Calcular métricas en ese punto temporal (con publication lag)
        m_hist = calculate_metrics_at(data, months_back + 2)

        # Feature vector — imputar NaN con 0 (se centrará con StandardScaler)
        row = []
        for feat in FEATURES:
            val = m_hist.get(feat, np.nan)
            if val is None or (isinstance(val, float) and np.isnan(val)):
                val = 0.0
            row.append(float(val))

        X_rows.append(row)
        y_rows.append(label)
        dates.append(target_date)

    if len(X_rows) < 40:
        return None, None, None

    return np.array(X_rows), np.array(y_rows), dates


def train_model(data: dict, force: bool = False):
    """
    Entrena el modelo logístico sobre datos reales de FRED.
    Guarda en disco para no reentrenar en cada ejecución.
    Devuelve None si hay datos insuficientes.
    """
    import os, pickle

    if os.path.exists(MODEL_FILE) and not force:
        try:
            saved = pickle.load(open(MODEL_FILE, "rb"))
            cv    = saved.get("cv_accuracy", 0)
            n     = saved.get("n_samples", 0)
            print(f"  ✓  Modelo cargado — CV {cv:.1%}  ·  {n} meses entrenamiento")
            return saved
        except Exception as e:
            print(f"  ↻  Error cargando modelo ({e}) — reentrenando")

    try:
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler
        from sklearn.pipeline import Pipeline
        from sklearn.model_selection import cross_val_score, StratifiedKFold
    except ImportError:
        print("  ✗  scikit-learn no instalado  →  pip install scikit-learn")
        return None

    print("  🔬 Construyendo dataset histórico...")
    X, y, dates = build_dataset(data)

    if X is None:
        print("  ⚠  Datos insuficientes para entrenar")
        return None

    from collections import Counter
    dist = Counter(y)
    n_classes = len(dist)
    print(f"  📊 {len(X)} meses  ·  {n_classes} fases:")
    for label, count in sorted(dist.items()):
        print(f"      {INT_PHASE[label]}: {count} meses")

    # Necesitamos al menos 2 muestras por clase para CV estratificada
    if any(v < 5 for v in dist.values()):
        print("  ⚠  Alguna fase tiene < 5 meses — insuficiente para entrenar")
        return None

    pipeline = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(
            solver="lbfgs",
            C=0.8,
            max_iter=3000,
            class_weight="balanced",
            random_state=42,
        ))
    ])

    n_splits = min(5, min(dist.values()))
    cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
    cv_scores = cross_val_score(pipeline, X, y, cv=cv, scoring="accuracy")

    pipeline.fit(X, y)
    train_acc = pipeline.score(X, y)

    # Importancia de features (media de |coeficientes| entre clases)
    coefs = pipeline.named_steps["clf"].coef_
    importance = {
        feat: float(np.abs(coefs).mean(axis=0)[i])
        for i, feat in enumerate(FEATURES)
    }
    top5 = sorted(importance.items(), key=lambda x: -x[1])[:5]

    cv_mean = float(cv_scores.mean())
    cv_std  = float(cv_scores.std())
    print(f"  ✓  CV accuracy: {cv_mean:.1%} ± {cv_std:.1%}  ·  Train: {train_acc:.1%}")
    print(f"  📈 Top features: {', '.join(f for f,_ in top5)}")

    model = {
        "pipeline":    pipeline,
        "features":    FEATURES,
        "cv_accuracy": cv_mean,
        "cv_std":      cv_std,
        "train_acc":   train_acc,
        "n_samples":   len(X),
        "importance":  importance,
        "trained_at":  datetime.now().isoformat(),
    }

    try:
        import pickle
        pickle.dump(model, open(MODEL_FILE, "wb"))
        print(f"  💾 Guardado en {MODEL_FILE}")
    except Exception as e:
        print(f"  ⚠  No se pudo guardar ({e})")

    return model


def predict(m: dict, model: dict):
    """
    Predice la fase actual con el modelo logístico.
    Devuelve dict con probabilidades, fase y confianza.
    """
    if model is None:
        return None

    pipeline = model.get("pipeline")
    features  = model.get("features", FEATURES)
    if pipeline is None:
        return None

    row = []
    for feat in features:
        val = m.get(feat, np.nan)
        if val is None or (isinstance(val, float) and np.isnan(val)):
            val = 0.0
        row.append(float(val))

    try:
        X   = np.array([row])
        proba  = pipeline.predict_proba(X)[0]
        classes = pipeline.classes_
        pred   = int(pipeline.predict(X)[0])

        probas = {INT_PHASE[int(c)]: float(p) for c, p in zip(classes, proba)}
        sorted_p = sorted(proba, reverse=True)
        margin   = float(sorted_p[0] - sorted_p[1]) if len(sorted_p) > 1 else 1.0

        return {
            "phase":      INT_PHASE[pred],
            "probas":     probas,          # {fase: probabilidad 0-1}
            "confidence": float(sorted_p[0]),
            "margin":     margin,          # diferencia entre 1ª y 2ª proba
        }
    except Exception as e:
        print(f"  ✗  Error en predicción: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════
#  SELECCIÓN DEL MOTOR
#  Lógica de prioridad sin ambigüedad:
#
#   1. ¿Hay modelo logístico con CV ≥ 60% y ≥ 80 muestras?
#      SÍ → motor logístico activo
#      NO → motor tradicional (fallback)
#
#   2. Si el motor logístico está activo:
#      ¿El scoring tradicional supera al logístico por más de 15pp?
#      SÍ → usar tradicional (es significativamente más seguro)
#      NO → usar logístico (que es el motor principal)
# ══════════════════════════════════════════════════════════════════════

MIN_CV_ACCURACY = 0.60   # mínimo de CV accuracy para confiar en el modelo
MIN_SAMPLES     = 80     # mínimo de meses de entrenamiento


def select_engine(logit_result, trad_result, model) -> dict:
    """
    Decide qué motor usa y devuelve el resultado final unificado.

    Parámetros:
        logit_result : salida de predict() o None
        trad_result  : salida de score_phase() (siempre disponible)
        model        : dict del modelo entrenado o None

    Devuelve resultado final con campo "engine" indicando el origen.
    """
    cv_acc  = model.get("cv_accuracy", 0.0) if model else 0.0
    n_samp  = model.get("n_samples",   0)   if model else 0

    logit_ok = (
        logit_result is not None
        and cv_acc  >= MIN_CV_ACCURACY
        and n_samp  >= MIN_SAMPLES
    )

    if not logit_ok:
        # Fallback: no hay modelo válido
        reason = "sin modelo" if model is None else f"CV {cv_acc:.0%} < {MIN_CV_ACCURACY:.0%} o {n_samp} < {MIN_SAMPLES} muestras"
        return _make_result(trad_result, engine="tradicional", reason=f"fallback — {reason}",
                            alt=None)

    # Comparar confianzas
    logit_conf = logit_result["confidence"]  # max proba logístico
    trad_conf  = trad_result["confidence"]   # max score normalizado (/100)

    # Convertir trad_conf a escala 0-1 si está en porcentaje
    if trad_conf > 1.0:
        trad_conf = trad_conf / 100.0

    # ¿El tradicional es significativamente mejor?
    THRESHOLD = 0.15   # 15pp de ventaja → usar tradicional
    if (trad_conf - logit_conf) > THRESHOLD:
        return _make_result(trad_result, engine="tradicional",
                            reason=f"trad. más seguro ({trad_conf:.0%} vs {logit_conf:.0%})",
                            alt=logit_result)
    else:
        return _make_result_logit(logit_result, engine="logístico",
                                  reason=f"CV {cv_acc:.0%}  ·  {n_samp} meses",
                                  alt=trad_result)


def _make_result(trad, engine, reason, alt):
    """Construye resultado final desde scoring tradicional."""
    scores    = trad["scores"]   # {fase: porcentaje 0-100}
    phase     = trad["phase"]
    conf_raw  = trad["confidence"]
    conf      = conf_raw / 100.0 if conf_raw > 1.0 else conf_raw
    sorted_sc = sorted(scores.items(), key=lambda x: -x[1])
    secondary = sorted_sc[1][0] if len(sorted_sc) > 1 else phase

    return {
        "phase":      phase,
        "secondary":  secondary,
        "scores":     scores,           # porcentajes 0-100
        "confidence": conf,
        "engine":     engine,
        "reason":     reason,
        "breakdown":  trad.get("breakdown", []),
        "alt":        alt,              # resultado alternativo (para mostrar en dashboard)
    }


def _make_result_logit(logit, engine, reason, alt):
    """Construye resultado final desde predicción logística."""
    probas    = logit["probas"]  # {fase: proba 0-1}
    scores    = {k: v * 100 for k, v in probas.items()}  # → porcentajes
    phase     = logit["phase"]
    conf      = logit["confidence"]
    margin    = logit.get("margin", 0)
    sorted_sc = sorted(scores.items(), key=lambda x: -x[1])
    secondary = sorted_sc[1][0] if len(sorted_sc) > 1 else phase

    return {
        "phase":      phase,
        "secondary":  secondary,
        "scores":     scores,
        "confidence": conf,
        "engine":     engine,
        "reason":     reason,
        "margin":     margin,
        "breakdown":  alt.get("breakdown", []) if alt else [],
        "alt":        alt,              # scoring tradicional como referencia
    }


def score_dual(m: dict, pcts: dict = None) -> dict:
    """
    Ejecuta scoring_core dos veces: una con solo indicadores adelantados
    y otra con solo coincidentes. Detecta divergencias automáticamente.
    """
    pcts = pcts or {}

    # ── Métricas solo adelantadas ──────────────────────────────────
    m_lead = {
        "neworder_yoy":   m.get("neworder_yoy"),
        "neworder_mom":   m.get("neworder_mom"),
        "permit_yoy":     m.get("permit_yoy"),
        "inf_exp":        m.get("inf_exp"),
        "inf_exp_chg":    m.get("inf_exp_chg"),
        "yield_curve":    m.get("yield_curve"),
        "hy_spread":      m.get("hy_spread"),
        "credit_stress":  m.get("credit_stress"),
    }

    # ── Métricas solo coincidentes ─────────────────────────────────
    m_coin = {
        "retail_yoy":      m.get("retail_yoy"),
        "payroll_chg_3m":  m.get("payroll_chg_3m"),
        "unrate":          m.get("unrate"),
        "unrate_delta":    m.get("unrate_delta"),
        "sentiment_chg":   m.get("sentiment_chg"),
        "core_yoy":        m.get("core_yoy"),
        "inflation_trend": m.get("inflation_trend"),
        "fed_funds":       m.get("fed_funds"),
        "fed_chg":         m.get("fed_chg"),
        "vix":             m.get("vix"),
    }

    r_lead = score_phase_core(m_lead, pcts)
    r_coin = score_phase_core(m_coin, pcts)
    r_full = score_phase_core(m, pcts)

    # ── Análisis de divergencia ────────────────────────────────────
    phase_lead = r_lead["phase"]
    phase_coin = r_coin["phase"]
    phase_full = r_full["phase"]

    diverge = (phase_lead != phase_coin)

    # Gap entre las dos lecturas (distancia euclidiana entre vectores de score)
    import math
    gap = math.sqrt(sum(
        (r_lead["scores"].get(ph,0) - r_coin["scores"].get(ph,0))**2
        for ph in r_full["scores"]
    ))

    if diverge:
        signal = "TRANSICIÓN"
        signal_detail = f"Adelantados→{phase_lead} | Coincidentes→{phase_coin}"
    elif gap < 8:
        signal = "ALINEADOS"
        signal_detail = f"Ambos confirman {phase_full}"
    else:
        signal = "DÉBILMENTE ALINEADOS"
        signal_detail = f"Misma fase pero con intensidades distintas"

    return {
        "full":          r_full,
        "leading":       r_lead,
        "lagging":       r_coin,
        "phase":         phase_full,
        "phase_lead":    phase_lead,
        "phase_coin":    phase_coin,
        "diverge":       diverge,
        "gap":           gap,
        "signal":        signal,
        "signal_detail": signal_detail,
        "secondary":     r_full["secondary"],
        "confidence":    r_full["confidence"],
        "scores":        r_full["scores"],
        "breakdown":     r_full["breakdown"],
    }


# ══════════════════════════════════════════════════════════════════
#  INTERPRETACIÓN VÍA API DE CLAUDE
#  Genera un comentario analítico breve basado en los datos reales.
# ══════════════════════════════════════════════════════════════════

def generate_interpretation(m: dict, dual: dict, momentum: dict, pcts: dict) -> str:
    """
    Llama a la API de Claude para generar una interpretación
    concisa y realista del estado del ciclo económico.
    Devuelve el texto o un fallback si la API no está disponible.
    """
    import json

    phase       = dual["phase"]
    phase_lead  = dual["phase_lead"]
    phase_coin  = dual["phase_coin"]
    signal      = dual["signal"]
    diverge     = dual["diverge"]
    conf_pct    = dual["confidence"] * 100
    arrows      = momentum.get("arrows", {})
    trend       = momentum.get("trend",  {})

    # Construir contexto compacto para el prompt
    ctx = {
        "fecha":          datetime.now().strftime("%B %Y"),
        "fase_principal": phase,
        "score_principal":f"{dual['scores'][phase]:.1f}%",
        "fase_adelantados": phase_lead,
        "score_adelantados": f"{dual['leading']['scores'][phase_lead]:.1f}%",
        "fase_coincidentes": phase_coin,
        "score_coincidentes": f"{dual['lagging']['scores'][phase_coin]:.1f}%",
        "señal":          signal,
        "divergencia":    diverge,
        "confianza":      f"{conf_pct:.0f}%",
        "momentum": {ph: f"{arrows.get(ph,'→')} {trend.get(ph,0):+.1f}pp"
                     for ph in dual["scores"]},
        "indicadores_clave": {
            "Core_CPI_YoY":    f"{m.get('core_yoy', float('nan')):.1f}%" if m.get('core_yoy') else "N/D",
            "Curva_10Y2Y":     f"{m.get('yield_curve', float('nan')):+.2f}%" if m.get('yield_curve') else "N/D",
            "Nominas_3m_avg":  f"{m.get('payroll_chg_3m', float('nan')):.0f}k" if m.get('payroll_chg_3m') else "N/D",
            "Desempleo":       f"{m.get('unrate', float('nan')):.1f}%" if m.get('unrate') else "N/D",
            "HY_Spread":       f"{m.get('hy_spread', float('nan')):.2f}%" if m.get('hy_spread') else "N/D",
            "VIX":             f"{m.get('vix', float('nan')):.1f}" if m.get('vix') else "N/D",
            "Pedidos_Mfg_YoY": f"{m.get('neworder_yoy', float('nan')):+.1f}%" if m.get('neworder_yoy') else "N/D",
            "Fed_Funds":       f"{m.get('fed_funds', float('nan')):.2f}%" if m.get('fed_funds') else "N/D",
            "Permisos_YoY":    f"{m.get('permit_yoy', float('nan')):+.1f}%" if m.get('permit_yoy') else "N/D",
        },
        "percentiles_clave": {
            k: f"{v:.0f}°" for k, v in (pcts or {}).items()
            if k in ["core_yoy","yield_curve","hy_spread","vix","neworder_yoy","payroll_chg_3m"]
        }
    }

    prompt = f"""Eres un analista macro senior. Basándote SOLO en los datos del modelo Investment Clock que te proporciono, escribe una interpretación concisa y realista del momento del ciclo económico.

DATOS DEL MODELO:
{json.dumps(ctx, ensure_ascii=False, indent=2)}

INSTRUCCIONES:
- 4-5 frases máximo, tono analítico directo
- Explica qué está pasando AHORA y qué sugiere para los próximos 6-12 meses
- Si hay divergencia entre adelantados y coincidentes, explícalo claramente
- Menciona las tensiones o contradicciones reales que ves en los datos
- NO uses frases genéricas como "el mercado muestra señales mixtas"
- NO inventes datos que no estén en el contexto
- Escribe en español"""

    try:
        import urllib.request
        payload = json.dumps({
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 300,
            "messages": [{"role": "user", "content": prompt}]
        }).encode()

        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            headers={
                "Content-Type":      "application/json",
                "anthropic-version": "2023-06-01",
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            result = json.loads(resp.read().decode())
            return result["content"][0]["text"].strip()

    except Exception as e:
        # Fallback: interpretación local basada en reglas
        lines = []
        if diverge:
            lines.append(
                f"⚠ SEÑAL DE TRANSICIÓN: los indicadores adelantados apuntan a {phase_lead} "
                f"mientras los coincidentes confirman {phase_coin}. "
                f"Esto sugiere que la economía está en un punto de inflexión."
            )
        else:
            lines.append(
                f"El modelo sitúa el ciclo en fase de {phase} con una confianza del {conf_pct:.0f}%. "
                f"Adelantados y coincidentes están {'alineados' if signal=='ALINEADOS' else 'parcialmente alineados'}."
            )
        # Mencionar el indicador más relevante
        yc = m.get("yield_curve")
        if yc is not None:
            if yc < -0.25:
                lines.append(f"La curva 10Y-2Y en {yc:+.2f}% sigue invertida, señal histórica de desaceleración futura.")
            elif yc > 0.5:
                lines.append(f"La curva 10Y-2Y en {yc:+.2f}% apoya el escenario de expansión continuada.")
        return " ".join(lines)



def common_assets(phase1: str, phase2: str, table: dict, min_score: int = 1):
    result = []
    for asset, r1, _ in table[phase1]:
        for asset2, r2, _ in table[phase2]:
            if asset == asset2 and r1 >= min_score and r2 >= min_score:
                result.append((asset, r1, r2))
    return result



# ══════════════════════════════════════════════════════════════════
#  PALETA — DISEÑO CLARO Y LEGIBLE
# ══════════════════════════════════════════════════════════════════
BG      = "#F5F6FA"      # fondo gris muy claro
CARD    = "#FFFFFF"      # tarjetas blancas
CARD2   = "#ECEEF5"      # tarjetas secundarias
BORDER  = "#D0D4E8"
TEXT    = "#1A1D2E"      # texto oscuro principal
MUTED   = "#6B7280"      # texto secundario
LINE    = "#C8CCDC"

PHASE_COLORS = {
    "Recuperación":       "#16A34A",   # verde sólido
    "Sobrecalentamiento": "#DC2626",   # rojo
    "Estanflación":       "#D97706",   # ámbar
    "Reflación/Recesión": "#2563EB",   # azul
}
PHASE_LIGHT = {
    "Recuperación":       "#DCFCE7",
    "Sobrecalentamiento": "#FEE2E2",
    "Estanflación":       "#FEF3C7",
    "Reflación/Recesión": "#DBEAFE",
}

def rating_to_str(r):
    return {3:"+++", 2:"++", 1:"+", 0:"0", -1:"−", -2:"−−", -3:"−−−"}.get(r,"0")

def rating_color(r):
    if r ==  3: return "#16A34A"
    if r ==  2: return "#22C55E"
    if r ==  1: return "#86EFAC"
    if r ==  0: return "#9CA3AF"
    if r == -1: return "#FCD34D"
    if r == -2: return "#F97316"
    if r == -3: return "#DC2626"
    return "#9CA3AF"

def card(ax, x, y, w, h, color=CARD, border=BORDER, radius=0.015):
    from matplotlib.patches import FancyBboxPatch
    p = FancyBboxPatch((x, y), w, h,
                       boxstyle=f"round,pad={radius}",
                       facecolor=color, edgecolor=border, linewidth=1.2, zorder=2)
    ax.add_patch(p)


# ══════════════════════════════════════════════════════════════════
#  RELOJ DEL CICLO
# ══════════════════════════════════════════════════════════════════
def draw_clock(ax, scores, phase):
    import numpy as np
    from matplotlib.patches import Wedge
    ax.set_facecolor(BG)
    ax.set_aspect("equal")
    ax.set_xlim(-1.35, 1.35)
    ax.set_ylim(-1.35, 1.35)
    ax.axis("off")

    # Mapa correcto del Investment Clock (sentido horario):
    #   12-3  Recuperación      → cuadrante superior-derecho  (matplotlib: 0-90°)
    #   3-6   Sobrecalentamiento→ cuadrante inferior-derecho  (matplotlib: 270-360°)
    #   6-9   Estanflación      → cuadrante inferior-izquierdo(matplotlib: 180-270°)
    #   9-12  Reflación/Recesión→ cuadrante superior-izquierdo(matplotlib: 90-180°)
    segments = [
        ("Recuperación",        0,   90),
        ("Reflación/Recesión",  90,  180),
        ("Estanflación",        180, 270),
        ("Sobrecalentamiento",  270, 360),
    ]
    labels_pos = {
        "Recuperación":        ( 0.72,  0.72),
        "Reflación/Recesión":  (-0.72,  0.72),
        "Estanflación":        (-0.72, -0.72),
        "Sobrecalentamiento":  ( 0.72, -0.72),
    }
    labels_short = {
        "Recuperación":        "RECUP.",
        "Sobrecalentamiento":  "SOBRE-\nCALENT.",
        "Estanflación":        "ESTAN-\nFLAC.",
        "Reflación/Recesión":  "REFLAC./\nRECES.",
    }

    # Normalizar scores para que la fase activa siempre domine visualmente
    # Independientemente de si son probabilidades logísticas o scores tradicionales
    total_sc = sum(scores.get(ph, 0) for ph,_,_ in segments) or 100
    for ph, a1, a2 in segments:
        col = PHASE_COLORS[ph]
        sc  = scores.get(ph, 0)
        is_active = (ph == phase)
        # La fase activa siempre al 90% alpha; el resto proporcional a su score
        # pero siempre por debajo de la activa (máx 0.45)
        if is_active:
            alpha = 0.90
        else:
            alpha = min(0.15 + 0.30 * (sc / total_sc), 0.45)
        lw    = 3.5 if is_active else 0.6
        w = Wedge((0,0), 1.15, a1, a2, facecolor=col, alpha=alpha,
                  edgecolor=col, linewidth=lw)
        ax.add_patch(w)
        # hueco interior
        inner = Wedge((0,0), 0.42, a1, a2, facecolor=BG, alpha=1.0,
                      edgecolor=BORDER, linewidth=0.5)
        ax.add_patch(inner)

    # labels de fase
    for ph, (x, y) in labels_pos.items():
        col = PHASE_COLORS[ph]
        is_active = (ph == phase)
        ax.text(x, y, labels_short[ph], ha="center", va="center",
                fontsize=9 if is_active else 8,
                fontweight="bold" if is_active else "normal",
                color=col, linespacing=1.35)

    # marcadores hora
    for deg, lbl in [(90,"12"),(0,"3"),(270,"6"),(180,"9")]:
        r = np.radians(deg)
        ax.text(1.27*np.cos(r), 1.27*np.sin(r), lbl,
                ha="center", va="center", fontsize=9, color=MUTED)

    # aguja
    # Centro de cada sector (ángulo medio del segmento correspondiente)
    needle_angles = {
        "Recuperación":        45,   # centro de 0-90°
        "Reflación/Recesión":  135,  # centro de 90-180°
        "Estanflación":        225,  # centro de 180-270°
        "Sobrecalentamiento":  315,  # centro de 270-360°
    }
    ang  = np.radians(needle_angles.get(phase, 0))
    col  = PHASE_COLORS[phase]
    ax.annotate("", xy=(0.9*np.cos(ang), 0.9*np.sin(ang)), xytext=(0,0),
                arrowprops=dict(arrowstyle="->, head_width=0.2, head_length=0.16",
                                color=col, lw=3.5))
    import matplotlib.pyplot as plt
    pivot = plt.Circle((0,0), 0.055, color=col, zorder=6)
    ax.add_patch(pivot)

    # score en el centro
    sc_val = scores.get(phase, 0)
    ax.text(0, -0.15, f"{sc_val:.0f}%", ha="center", va="center",
            fontsize=16, fontweight="bold", color=col)
    ax.text(0, -0.26, "score", ha="center", va="center",
            fontsize=9, color=MUTED)


# ══════════════════════════════════════════════════════════════════
#  BARRAS DE SCORE
# ══════════════════════════════════════════════════════════════════
def draw_bars(ax, scores, phase, momentum=None):
    ax.set_facecolor(BG)
    ax.axis("off")
    order = ["Recuperación","Sobrecalentamiento","Estanflación","Reflación/Recesión"]
    n = len(order)
    ax.set_xlim(0, 1)
    ax.set_ylim(-0.5, n - 0.3)

    arrows = momentum.get("arrows", {}) if momentum else {}
    trend  = momentum.get("trend",  {}) if momentum else {}

    for i, ph in enumerate(order):
        sc  = scores.get(ph, 0)
        col = PHASE_COLORS[ph]
        y   = n - 1 - i
        active = (ph == phase)
        arrow  = arrows.get(ph, "→")
        delta  = trend.get(ph, 0.0)

        # fondo barra
        card(ax, 0.0, y-0.32, 1.0, 0.64, color=CARD2 if active else CARD,
             border=col if active else BORDER, radius=0.01)
        # barra rellena
        bw = 0.55 * (sc / 100)
        card(ax, 0.02, y-0.22, bw, 0.44, color=col,
             border=col, radius=0.008)

        # nombre
        ax.text(0.04, y, ph, ha="left", va="center",
                fontsize=11 if active else 10,
                fontweight="bold" if active else "normal",
                color=col if active else MUTED)

        # score + flecha momentum
        arrow_col = "#16A34A" if arrow=="↑" else "#DC2626" if arrow=="↓" else MUTED
        # delta_str: variación de probabilidad vs hace 3 meses
        if momentum and delta != 0:
            sign = "+" if delta >= 0 else ""
            delta_str = f"{sign}{delta:.1f}pp vs 3m"
        else:
            delta_str = ""
        ax.text(0.96, y+0.12, f"{sc:.1f}%", ha="right", va="center",
                fontsize=11 if active else 10,
                fontweight="bold" if active else "normal",
                color=col if active else MUTED)
        ax.text(0.96, y-0.15, f"{arrow}  {delta_str}", ha="right", va="center",
                fontsize=9, color=arrow_col)


# ══════════════════════════════════════════════════════════════════
#  GRID DE INDICADORES
# ══════════════════════════════════════════════════════════════════
def draw_indicators(ax, m, pcts=None):
    import numpy as np
    ax.set_facecolor(BG)
    ax.axis("off")

    # Tupla: (label, valor, unidad, kind_color, pct_key)
    items = [
        ("Pedidos Mfg YoY",  m.get("neworder_yoy",      np.nan), "%",  "growth",  "neworder_yoy"),
        ("Retail YoY",       m.get("retail_yoy",        np.nan), "%",  "growth",  "retail_yoy"),
        ("Nóminas 3m",       m.get("payroll_chg_3m",    np.nan), "k",  "payroll", "payroll_chg_3m"),
        ("Desempleo",        m.get("unrate",            np.nan), "%",  "unrate",  "unrate"),
        ("Core CPI",         m.get("core_yoy",          np.nan), "%",  "cpi",     "core_yoy"),
        ("Infla. Vel. 3m",   m.get("inflation_velocity",np.nan), "pp", "cpi_vel", None),
        ("Breakeven 5Y",     m.get("inf_exp",           np.nan), "%",  "inf_exp", "inf_exp"),
        ("Curva 10Y-2Y",     m.get("yield_curve",       np.nan), "%",  "curve",   "yield_curve"),
        ("Curva 10Y-3M",     m.get("yield_curve_10_3",  np.nan), "%",  "curve",   "yield_curve"),
        ("HY Spread",        m.get("hy_spread",         np.nan), "%",  "credit",  "hy_spread"),
        ("IG Spread",        m.get("ig_spread",         np.nan), "%",  "ig",      None),
        ("Claims YoY",       m.get("jobless_claims_yoy",np.nan), "%",  "claims",  "payroll_chg_3m"),
    ]

    def icolor(val, kind):
        if np.isnan(val): return MUTED
        if kind=="growth":   return "#16A34A" if val>2 else "#D97706" if val>0 else "#DC2626"
        if kind=="payroll":  return "#16A34A" if val>150 else "#D97706" if val>0 else "#DC2626"
        if kind=="unrate":   return "#16A34A" if val<4.5 else "#D97706" if val<5.5 else "#DC2626"
        if kind=="cpi":      return "#16A34A" if val<2.5 else "#D97706" if val<4.0 else "#DC2626"
        if kind=="cpi_vel":  return "#16A34A" if val<-0.5 else "#D97706" if val<0.5 else "#DC2626"
        if kind=="inf_exp":  return "#D97706" if val>2.5 else "#16A34A"
        if kind=="rate":     return MUTED
        if kind=="curve":    return "#16A34A" if val>0.5 else "#D97706" if val>0 else "#DC2626"
        if kind=="credit":   return "#16A34A" if val<3.5 else "#D97706" if val<6.0 else "#DC2626"
        if kind=="ig":       return "#16A34A" if val<1.0 else "#D97706" if val<1.8 else "#DC2626"
        if kind=="claims":   return "#16A34A" if val<-5 else "#D97706" if val<10 else "#DC2626"
        if kind=="vix":      return "#16A34A" if val<18 else "#D97706" if val<28 else "#DC2626"
        return MUTED

    cols, rows = 4, 3
    ax.set_xlim(0, cols)
    ax.set_ylim(0, rows)

    for idx, (label, val, unit, kind, pct_key) in enumerate(items):
        c = idx % cols
        r = rows - 1 - idx // cols
        card(ax, c+0.06, r+0.08, 0.88, 0.84, color=CARD, border=BORDER, radius=0.02)

        ax.text(c+0.5, r+0.78, label, ha="center", va="top",
                fontsize=9, color=MUTED)

        col_v = icolor(val, kind)
        if np.isnan(val):
            vstr = "N/D"
        elif kind == "payroll":
            vstr = f"{'+' if val>=0 else ''}{val:.0f}{unit}"
        elif kind in ("rate","curve"):
            vstr = f"{'+' if val>=0 else ''}{val:.2f}{unit}"
        else:
            vstr = f"{val:.1f}{unit}"

        ax.text(c+0.5, r+0.42, vstr, ha="center", va="center",
                fontsize=17, fontweight="bold", color=col_v)

        # Mini barra de percentil histórico
        pct_val = (pcts or {}).get(pct_key, None)
        if pct_val is not None and not np.isnan(pct_val):
            bar_w = 0.76
            bar_x = c + 0.12
            bar_y = r + 0.12
            bar_h = 0.10
            # fondo
            from matplotlib.patches import FancyBboxPatch as FBP
            ax.add_patch(FBP((bar_x, bar_y), bar_w, bar_h,
                             boxstyle="round,pad=0.005",
                             facecolor=CARD2, edgecolor=LINE, linewidth=0.5))
            # relleno
            fill_w = bar_w * (pct_val / 100)
            pct_col = "#16A34A" if pct_val < 30 or pct_val > 70 else "#D97706"
            if fill_w > 0.01:
                ax.add_patch(FBP((bar_x, bar_y), fill_w, bar_h,
                                 boxstyle="round,pad=0.005",
                                 facecolor=pct_col, edgecolor=pct_col, linewidth=0,
                                 alpha=0.7))
            ax.text(bar_x + bar_w/2, bar_y + bar_h/2,
                    f"pct {pct_val:.0f}°",
                    ha="center", va="center", fontsize=7.5, color=TEXT)


# ══════════════════════════════════════════════════════════════════
#  TABLA DE RECOMENDACIONES
# ══════════════════════════════════════════════════════════════════
def draw_recs(ax, recs, col_ph):
    ax.set_facecolor(BG)
    ax.axis("off")
    n = len(recs)
    ax.set_xlim(0, 1)
    ax.set_ylim(-0.5, n - 0.3)

    for i, (asset, rating, reason) in enumerate(recs):
        y   = n - 1 - i
        col = rating_color(rating)
        rstr= rating_to_str(rating)
        active = (rating != 0)

        # fila fondo alternada
        card(ax, 0.0, y-0.40, 1.0, 0.80,
             color=CARD if i%2==0 else CARD2, border=BORDER, radius=0.008)

        # asset name
        ax.text(0.03, y, asset, ha="left", va="center",
                fontsize=11, color=TEXT if active else MUTED,
                fontweight="bold" if abs(rating)>=2 else "normal")

        # badge rating
        bx, bw, bh = 0.52, 0.095, 0.70
        from matplotlib.patches import FancyBboxPatch
        badge = FancyBboxPatch((bx, y-bh/2), bw, bh,
                               boxstyle="round,pad=0.01",
                               facecolor=col+"33", edgecolor=col, linewidth=1.2)
        ax.add_patch(badge)
        ax.text(bx+bw/2, y, rstr, ha="center", va="center",
                fontsize=10, fontweight="bold", color=col)

        # razón
        ax.text(0.64, y, reason, ha="left", va="center",
                fontsize=8.5, color=MUTED, style="italic")

        if i < n-1:
            ax.axhline(y=y-0.40, color=LINE, lw=0.5, alpha=0.8)


# ══════════════════════════════════════════════════════════════════
#  DESGLOSE SCORING
# ══════════════════════════════════════════════════════════════════
def draw_breakdown(ax, breakdown, max_items=12):
    import numpy as np
    ax.set_facecolor(BG)
    ax.axis("off")

    scored = []
    for label, contribs, weight in breakdown:
        pts = sum(abs(v)*weight for v in contribs.values())
        best = max(contribs, key=lambda k: contribs[k]) if contribs else None
        scored.append((pts, label, best, contribs, weight))
    scored.sort(reverse=True)
    items = scored[:max_items]

    ax.set_xlim(0, 1)
    ax.set_ylim(-0.5, max_items - 0.3)

    for i, (pts, label, best_ph, contribs, weight) in enumerate(items):
        y = max_items - 1 - i
        col = PHASE_COLORS.get(best_ph, MUTED) if best_ph else MUTED

        card(ax, 0.0, y-0.38, 1.0, 0.76,
             color=CARD if i%2==0 else CARD2, border=BORDER, radius=0.008)

        # punto de color
        import matplotlib.pyplot as plt
        ax.plot(0.025, y, marker="o", color=col, markersize=8, linestyle="None", zorder=3)

        # label
        ax.text(0.06, y, label, ha="left", va="center",
                fontsize=10, color=TEXT)

        # contribuciones
        cstr = "  ".join(
            f"{ph[:4]}:{v*weight:+.1f}"
            for ph,v in contribs.items() if v!=0
        )
        ax.text(0.99, y, cstr, ha="right", va="center",
                fontsize=8.5, color=MUTED)

        if i < len(items)-1:
            ax.axhline(y=y-0.38, color=LINE, lw=0.5, alpha=0.7)


def draw_logistic_breakdown(ax, logit_pred, result):
    """
    Panel de diagnóstico del modelo logístico.

    Muestra los indicadores más influyentes en la decisión con:
    - Valor actual del indicador
    - Percentil histórico (dónde está vs los últimos 20 años)
    - Dirección: hacia qué fase empuja este indicador
    - Explicación en lenguaje natural de por qué importa

    Esto responde a: "¿por qué el modelo eligió esta fase?"
    """
    ax.set_facecolor(BG)
    ax.axis("off")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    phase     = result.get("phase", "—")
    col_ph    = PHASE_COLORS.get(phase, MUTED)
    model_acc = result.get("model_acc", 0)
    margin    = logit_pred.get("margin", 0)
    probas    = sorted(logit_pred["probas"].items(), key=lambda x: -x[1])
    trad_phase = result.get("trad_phase", "—")
    trad_conf  = result.get("trad_conf", 0)
    trad_conf  = trad_conf / 100 if trad_conf > 1 else trad_conf
    m_data    = result.get("_m", {})    # métricas actuales (se pasa por result)
    pcts_data = result.get("_pcts", {}) # percentiles actuales

    # ── CABECERA ─────────────────────────────────────────────────
    ax.text(0.01, 0.985, "DIAGNÓSTICO DEL MODELO  —  indicadores clave y su influencia",
            fontsize=8.5, fontweight="bold", color=MUTED,
            va="top", transform=ax.transAxes)

    # Barra de confianza del modelo (compacta, arriba del todo)
    conf = logit_pred["confidence"]
    conf_col = "#90EE90" if conf >= 0.65 else "#FFD700" if conf >= 0.50 else "#FF6B6B"
    margin_col = "#90EE90" if margin >= 0.35 else "#FFD700" if margin >= 0.18 else "#FF6B6B"
    agree = trad_phase == phase
    agree_col = "#90EE90" if agree else "#FFD700"
    agree_txt = f"✓ Trad. coincide: {trad_phase}" if agree else f"≠ Trad. diverge: {trad_phase} ({trad_conf:.0%})"

    ax.text(0.01, 0.955,
            f"Confianza modelo: {conf:.0%}   ·   Margen 1ª-2ª: {margin:.0%}   ·   CV: {model_acc:.0%}   ·   {agree_txt}",
            fontsize=8, color=MUTED, va="top", transform=ax.transAxes)

    # Advertencia de margen bajo
    if margin < 0.18:
        ax.text(0.99, 0.955,
                "⚠ señal ambigua",
                fontsize=8, color="#FFD700", fontweight="bold",
                va="top", ha="right", transform=ax.transAxes)

    # ── LÍNEA SEPARADORA ─────────────────────────────────────────
    ax.plot([0, 1], [0.935, 0.935], color=BORDER, lw=0.8, transform=ax.transAxes)

    # ── TABLA DE INDICADORES CLAVE ───────────────────────────────
    # Cada fila: indicador | valor actual | percentil | → fase | explicación
    #
    # Los indicadores se eligen por importancia para el modelo logístico.
    # Si tenemos las métricas reales las usamos; si no, mostramos los fijos.
    # La explicación describe la lógica económica, no solo el número.

    # Tabla de indicadores clave
    # Campos: (m_key, nombre, pct_key, fmt, invert_pct, ph_high, ph_low, explicación)
    #
    # invert_pct=True: percentil ALTO es malo (spreads, claims, desempleo, fed_chg subiendo)
    #   → pct 80 en HY spread = spread muy alto = señal recesiva
    # invert_pct=False: percentil ALTO es bueno (curvas positivas, PMI, actividad)
    #   → pct 80 en curva = curva muy positiva = señal expansiva
    #
    # ph_high: fase que señala cuando el indicador está en zona FAVORABLE (tras invertir si aplica)
    # ph_low:  fase que señala cuando el indicador está en zona DESFAVORABLE
    INDICATORS_INFO = [
        # m_key               nombre           pct_key              fmt        inv   ph_alto                ph_bajo               explicación
        ("yield_curve_10_3", "Curva 10Y-3M",  "yield_curve_10_3", "{:.2f}%", False,"Recuperación",        "Reflación/Recesión", "La mejor predictor de recesión (Fed SF): invertida → recesión en 12-18m"),
        ("yield_curve",      "Curva 10Y-2Y",  "yield_curve",      "{:.2f}%", False,"Recuperación",        "Reflación/Recesión", "Positiva = mercado espera expansión; negativa = contracción futura"),
        ("proxy_pmi",        "Proxy PMI (z)", "proxy_pmi",        "{:+.2f}σ",False,"Recuperación",        "Reflación/Recesión", "Z-score combinando horas mfg + pedidos + claims: proxy del ISM sin suscripción"),
        ("awhman_yoy",       "Horas Mfg YoY", "awhman_yoy",      "{:+.1f}%", False,"Recuperación",        "Reflación/Recesión", "Empresas recortan horas ANTES de despedir: adelanta 2-3m a las nóminas"),
        ("core_yoy",         "Core CPI YoY",  "core_yoy",        "{:.1f}%",  False,"Estanflación",        "Recuperación",       "Inflación estructural: alta + crecimiento débil = estanflación clásica"),
        ("inflation_trend",  "Aceler. CPI",   "inflation_trend",  "{:+.2f}pp",False,"Estanflación",        "Recuperación",       "+ = inflación acelerando (últimos 6m vs anteriores): señal estanflacionaria"),
        ("inf_exp",          "Breakeven 5Y",  "inf_exp",          "{:.2f}%",  False,"Estanflación",        "Recuperación",       "Expectativas de inflación del mercado: >2.5% = presión persistente"),
        ("hy_spread",        "HY Spread",     "hy_spread",        "{:.2f}%",  True, "Sobrecalentamiento",  "Reflación/Recesión", "Spreads altos = mercado descuenta defaults; bajos = apetito de riesgo pleno"),
        ("ig_spread",        "IG Spread",     "ig_spread",        "{:.2f}%",  True, "Sobrecalentamiento",  "Reflación/Recesión", "Estrés en grado inversión confirma que el problema es sistémico, no solo HY"),
        ("jobless_claims_yoy","Claims YoY",   "jobless_claims_yoy","{:+.1f}%",True, "Sobrecalentamiento",  "Reflación/Recesión", "Subiendo = deterioro laboral inminente; adelanta 4-6 semanas a la tasa de paro"),
        ("houst_yoy",        "Viviendas YoY", "houst_yoy",        "{:+.1f}%", False,"Recuperación",        "Reflación/Recesión", "Primer sector en reaccionar a tipos: cayendo ya antes de que el ciclo gire"),
        ("fed_chg",          "Fed Funds Δ1Y", "fed_chg",          "{:+.2f}%", True, "Recuperación",        "Estanflación",       "Bajando = Fed ve riesgo recesivo o inflación controlada; subiendo = freno al ciclo"),
    ]

    # Construir filas de la tabla
    rows = []
    for (m_key, name, pct_key, fmt, invert_pct, ph_high, ph_low, explain) in INDICATORS_INFO:
        # Valor actual
        val = m_data.get(m_key, None)
        is_nan = val is None or (isinstance(val, float) and np.isnan(val))
        val_str = fmt.format(val) if not is_nan else "—"

        # Percentil histórico
        pct_raw = pcts_data.get(pct_key, None) if pct_key else None
        pct_str = f"pct {pct_raw:.0f}°" if pct_raw is not None else "—"

        # Dirección: invertir el percentil si el indicador es "malo cuando alto"
        if pct_raw is not None:
            pct_eff = (100 - pct_raw) if invert_pct else pct_raw
            if pct_eff >= 65:
                arrow = "↑"; dir_phase = ph_high; dir_col = PHASE_COLORS.get(ph_high, MUTED)
            elif pct_eff <= 35:
                arrow = "↓"; dir_phase = ph_low;  dir_col = PHASE_COLORS.get(ph_low, MUTED)
            else:
                arrow = "→"; dir_phase = "neutro"; dir_col = MUTED
        else:
            arrow = "·"; dir_phase = "—"; dir_col = MUTED

        rows.append((name, val_str, pct_str, arrow, dir_phase, dir_col, explain, invert_pct))

    # Dibujar tabla
    n_rows   = len(rows)
    row_h    = 0.068
    start_y  = 0.918
    col_w    = [0.185, 0.065, 0.055, 0.015, 0.13, 0.54]
    # cols:    nombre  | valor | pct   | flecha | → fase | explicación

    # Cabecera de tabla
    headers = ["INDICADOR", "VALOR", "HIST. ⟳=inv", "DIR", "→ FASE", "POR QUÉ IMPORTA"]
    x_pos = [0.01, 0.20, 0.27, 0.335, 0.36, 0.50]
    for hdr, x in zip(headers, x_pos):
        ax.text(x, start_y + 0.005, hdr,
                fontsize=7.5, fontweight="bold", color=MUTED,
                va="top", ha="left", transform=ax.transAxes)

    ax.plot([0, 1], [start_y - 0.005, start_y - 0.005],
            color=BORDER, lw=0.6, transform=ax.transAxes)

    for i, (name, val_str, pct_str, arrow, dir_phase, dir_col, explain, invert_pct) in enumerate(rows):
        y = start_y - 0.012 - i * row_h
        is_even = (i % 2 == 0)

        # Fondo alternado sutil
        card(ax, 0.0, y - row_h + 0.008, 1.0, row_h - 0.003,
             color=CARD if is_even else CARD2, border=CARD if is_even else CARD2, radius=0.004)

        # Punto de color en el indicador
        ax.plot(0.005, y - row_h/2 + 0.008, marker="o",
                color=dir_col, markersize=6, linestyle="None", zorder=3)

        # Nombre
        ax.text(0.015, y - row_h/2 + 0.009, name,
                fontsize=9, color=TEXT, va="center", ha="left",
                fontweight="bold" if dir_phase == phase else "normal",
                transform=ax.transAxes)

        # Valor actual
        ax.text(0.20, y - row_h/2 + 0.009, val_str,
                fontsize=9, color=dir_col, va="center", ha="left",
                fontweight="bold", transform=ax.transAxes)

        # Percentil histórico — mostrar el percentil EFECTIVO (el que usa el modelo)
        # Si invert_pct=True, el modelo usa 100-raw. Mostramos ese directamente
        # para que el usuario vea lo mismo que interpreta el modelo.
        # Añadimos ⟳ para indicar que se ha invertido respecto al valor bruto.
        if pct_raw is not None:
            pct_eff_val = (100 - pct_raw) if invert_pct else pct_raw
            pct_eff_str = f"pct {pct_eff_val:.0f}°"
            pct_display = f"{pct_eff_str} ⟳" if invert_pct else pct_eff_str
        else:
            pct_display = "—"
        ax.text(0.27, y - row_h/2 + 0.009, pct_display,
                fontsize=8, color=MUTED, va="center", ha="left",
                transform=ax.transAxes)

        # Flecha dirección
        arrow_col = dir_col if arrow != "→" else MUTED
        ax.text(0.335, y - row_h/2 + 0.009, arrow,
                fontsize=10, color=arrow_col, va="center", ha="left",
                fontweight="bold", transform=ax.transAxes)

        # Fase destino
        ax.text(0.36, y - row_h/2 + 0.009,
                dir_phase if dir_phase != "Neutro" else "—",
                fontsize=8.5, color=dir_col, va="center", ha="left",
                transform=ax.transAxes)

        # Explicación
        ax.text(0.50, y - row_h/2 + 0.009, explain,
                fontsize=8, color=MUTED, va="center", ha="left",
                transform=ax.transAxes)

    # ── NOTA INVERTIDOS ──────────────────────────────────────────
    # Explicar al usuario qué significa ⟳
    inv_names = [name for (name,_,_,_,_,_,_,inv) in rows if inv]
    nota_y = start_y - 0.012 - n_rows * row_h - 0.006
    ax.text(0.01, nota_y,
            f"⟳ = percentil invertido: para {', '.join(inv_names)}, "
            f"un valor ALTO del indicador es señal NEGATIVA (ej: HY Spread alto → recesión). "
            f"El percentil ya muestra el valor corregido — pct 95° en HY Spread significa "
            f"que el spread está en zona de euforia extrema (solo 5% de meses históricos "
            f"tuvo spreads más bajos). La flecha y la fase son coherentes con ese percentil.",
            fontsize=7, color=MUTED, va="top", style="italic",
            transform=ax.transAxes)

    # ── PIE: DIAGNÓSTICO SÍNTESIS ─────────────────────────────────
    footer_y = start_y - 0.012 - n_rows * row_h - 0.040
    ax.plot([0, 1], [footer_y + 0.015, footer_y + 0.015],
            color=BORDER, lw=0.6, transform=ax.transAxes)

    # Contar indicadores por dirección
    votes = {}
    for _, _, _, arrow, dir_phase, _, _, _ in rows:
        if arrow != "·" and dir_phase not in ("Neutro", "—"):
            votes[dir_phase] = votes.get(dir_phase, 0) + 1
    vote_str = "   ".join(
        f"{ph}: {cnt} indicadores"
        for ph, cnt in sorted(votes.items(), key=lambda x: -x[1])
    )
    if not vote_str:
        vote_str = "señal mixta"

    winner_phase = max(votes, key=votes.get) if votes else "—"
    winner_col   = PHASE_COLORS.get(winner_phase, MUTED)
    agree_model  = (winner_phase == phase)

    # Construir mensaje explicativo según si hay divergencia o no
    if agree_model:
        consensus_txt = (
            f"✓  Los indicadores individuales refuerzan la señal del modelo: "
            f"mayoría apunta a {winner_phase}"
        )
        consensus_col = "#90EE90"
    else:
        # Divergencia — explicar POR QUÉ no es una contradicción
        consensus_txt = (
            f"ℹ  Los indicadores individuales votan por {winner_phase}, "
            f"pero el modelo logístico detecta {phase}. "
            f"Esto es normal: el modelo evalúa combinaciones históricas, "
            f"no votos individuales. La divergencia indica señal mixta — "
            f"posible punto de transición entre fases."
        )
        consensus_col = "#FFD700"

    ax.text(0.01, footer_y,
            f"Votos individuales:  {vote_str}",
            fontsize=7.5, color=MUTED, va="top", transform=ax.transAxes)

    # Dividir el mensaje de consenso en dos líneas para que no se corte
    if len(consensus_txt) > 90:
        # Cortar en la mitad más cercana a un espacio
        mid = len(consensus_txt) // 2
        cut = consensus_txt.rfind(" ", 0, mid + 20)
        if cut == -1: cut = mid
        line1 = consensus_txt[:cut]
        line2 = consensus_txt[cut+1:]
    else:
        line1 = consensus_txt
        line2 = ""

    ax.text(0.01, footer_y - 0.04,
            line1,
            fontsize=8, color=consensus_col,
            fontweight="bold", va="top", transform=ax.transAxes)
    if line2:
        ax.text(0.01, footer_y - 0.075,
                line2,
                fontsize=8, color=consensus_col,
                fontweight="bold", va="top", transform=ax.transAxes)


# ══════════════════════════════════════════════════════════════════
#  PANEL CONSENSO / LEYENDA
# ══════════════════════════════════════════════════════════════════
def draw_consensus_or_legend(ax, phase, secondary, confidence,
                              FIXED_INCOME_RECS, EQUITY_RECS, common_assets):
    ax.set_facecolor(BG)
    ax.axis("off")

    if confidence >= 0.55:
        # Leyenda
        items = [
            ("+++  Muy Favorable",    "#16A34A"),
            ("++   Favorable",        "#22C55E"),
            ("+    Liger. Favorable", "#86EFAC"),
            ("0    Neutral",          "#9CA3AF"),
            ("−    Desfavorable",     "#FCD34D"),
            ("−−   Muy Desfavorable", "#F97316"),
            ("−−−  Evitar",           "#DC2626"),
        ]
        ax.set_xlim(0, 1); ax.set_ylim(0, len(items))
        for i, (lbl, c) in enumerate(items):
            y = len(items) - 1 - i + 0.5
            card(ax, 0.02, y-0.35, 0.96, 0.70,
                 color=CARD, border=BORDER, radius=0.015)
            ax.text(0.08, y, lbl, ha="left", va="center",
                    fontsize=12, fontweight="bold", color=c)
        return

    cf = common_assets(phase, secondary, FIXED_INCOME_RECS)
    ce = common_assets(phase, secondary, EQUITY_RECS)
    n  = len(cf) + len(ce) + 4
    ax.set_xlim(0, 1); ax.set_ylim(-0.5, max(n, 3))

    y = max(n, 3) - 1
    ax.text(0.5, y, "ACTIVOS CONSENSO", ha="center", va="center",
            fontsize=13, fontweight="bold", color=PHASE_COLORS.get(phase, TEXT))
    y -= 1
    ax.text(0.5, y, f"{phase}  ·  {secondary}",
            ha="center", va="center", fontsize=10, color=MUTED)
    y -= 1
    ax.text(0, y, "Renta Fija", ha="left", va="center",
            fontsize=11, color=MUTED, fontweight="bold")
    y -= 1
    for asset, r1, r2 in cf:
        ax.text(0.03, y, asset, ha="left", va="center", fontsize=10, color=TEXT)
        ax.text(0.97, y, f"{rating_to_str(r1)} / {rating_to_str(r2)}",
                ha="right", va="center", fontsize=10,
                color=rating_color(r1), fontweight="bold")
        y -= 1
    ax.text(0, y, "Renta Variable", ha="left", va="center",
            fontsize=11, color=MUTED, fontweight="bold")
    y -= 1
    for asset, r1, r2 in ce:
        ax.text(0.03, y, asset, ha="left", va="center", fontsize=10, color=TEXT)
        ax.text(0.97, y, f"{rating_to_str(r1)} / {rating_to_str(r2)}",
                ha="right", va="center", fontsize=10,
                color=rating_color(r1), fontweight="bold")
        y -= 1


# ══════════════════════════════════════════════════════════════════
#  BUILD DASHBOARD  — layout principal
# ══════════════════════════════════════════════════════════════════
def build_dashboard(m, result, FIXED_INCOME_RECS, EQUITY_RECS, common_assets, pcts=None, momentum=None, dual=None, interpretation=None):
    import matplotlib.pyplot as plt
    import matplotlib.gridspec as gridspec

    phase     = result["phase"]
    secondary = result["secondary"]
    scores    = result["scores"]
    conf      = result["confidence"]
    breakdown = result["breakdown"]
    col_ph    = PHASE_COLORS[phase]
    light_ph  = PHASE_LIGHT[phase]

    fig = plt.figure(figsize=(32, 22), facecolor=BG)

    # ── CABECERA ────────────────────────────────────────────────────
    hdr = fig.add_axes([0.0, 0.935, 1.0, 0.065])
    hdr.set_facecolor(col_ph)
    hdr.axis("off")

    hdr.text(0.02, 0.55, "INVESTMENT CLOCK ANALYZER",
             transform=hdr.transAxes,
             fontsize=22, fontweight="bold", color="white", va="center")
    hdr.text(0.02, 0.18, "Economic Cycle Intelligence  ·  FRED Real Data",
             transform=hdr.transAxes,
             fontsize=11, color="white", alpha=0.75, va="center")

    conf_pct     = conf * 100
    conf_lbl     = "ALTA" if conf>=0.65 else "MEDIA" if conf>=0.45 else "BAJA"
    engine       = result.get("engine", result.get("active_engine", "tradicional"))
    reason       = result.get("reason", "")
    model_acc    = result.get("model_acc", 0)
    model_samples= result.get("model_samples", 0)
    logit_pred   = result.get("logit_pred")
    trad_phase   = result.get("trad_phase", phase)
    trad_conf_raw= result.get("trad_conf", 0)
    trad_conf    = trad_conf_raw / 100 if trad_conf_raw > 1 else trad_conf_raw
    logit_active = result.get("logit_active", False)

    # Motor activo
    if "logístico" in engine:
        engine_lbl = f"▶ MOTOR: LOGÍSTICO  ·  CV {model_acc:.0%} (precisión histórica)  ·  {model_samples} meses de entrenamiento"
        engine_col = "#90EE90"
    else:
        engine_lbl = f"▶ MOTOR: TRADICIONAL  ·  {reason}"
        engine_col = "#FFD700"

    hdr.text(0.50, 0.68, f"FASE ACTUAL:  {phase.upper()}",
             transform=hdr.transAxes,
             fontsize=22, fontweight="bold", color="white", va="center", ha="center")
    hdr.text(0.50, 0.22, f"Confianza: {conf_lbl} {conf_pct:.0f}%  ·  Secundaria: {secondary}  ·  {datetime.now().strftime('%d %b %Y  %H:%M')}",
             transform=hdr.transAxes,
             fontsize=9.5, color="white", alpha=0.72, va="center", ha="center")

    hdr.text(0.98, 0.80, engine_lbl,
             transform=hdr.transAxes,
             fontsize=10, fontweight="bold", color=engine_col, va="center", ha="right")

    # Motor de referencia (el que no ganó)
    if logit_active and logit_pred:
        lp = logit_pred["phase"]
        lc = logit_pred.get("confidence", logit_pred.get("max_proba", 0))
        if "logístico" in engine:
            ref_lbl = f"Trad. (ref): {trad_phase}  {trad_conf:.0%}  {'✓' if trad_phase==phase else '≠'}"
        else:
            ref_lbl = f"Logístico (ref): {lp}  {lc:.0%}  {'✓' if lp==phase else '≠'}"
        ref_col = "#90EE90" if ref_lbl.endswith("✓") else "#FFD700"
        hdr.text(0.98, 0.32, ref_lbl,
                 transform=hdr.transAxes,
                 fontsize=9.5, color=ref_col, va="center", ha="right")

    # Señal dual — solo cuando motor es TRADICIONAL (en logístico no aplica)
    _hdr_engine = result.get("engine", result.get("active_engine", "tradicional"))
    if "logístico" not in _hdr_engine and dual:
        sig_col = "#FFD700" if dual.get("diverge") else "white"
        if dual.get("diverge"):
            dual_lbl = f"⚠ Adelantados → {dual['phase_lead']}  |  Coincidentes → {dual['phase_coin']}"
        else:
            dual_lbl = f"✓ Adelantados y coincidentes: {dual['phase']}"
        hdr.text(0.02, 0.32, dual_lbl,
                 transform=hdr.transAxes,
                 fontsize=9.5, color=sig_col, va="center")

    # ── GRID PRINCIPAL (3 columnas) ──────────────────────────────────
    # Layout: franja interpretación arriba, luego 3 columnas
    fig_gs = gridspec.GridSpec(
        1, 1, figure=fig,
        left=0.01, right=0.99,
        top=0.925, bottom=0.02,
    )

    # Franja eliminada por petición del usuario
    # (el panel de "ANÁLISIS DEL CICLO" con texto de recuperación)

    # Contenido principal en 3 columnas
    outer = gridspec.GridSpecFromSubplotSpec(
        1, 3, subplot_spec=fig_gs[0],
        wspace=0.025,
        width_ratios=[1.0, 1.15, 1.15]
    )

    left_gs = gridspec.GridSpecFromSubplotSpec(
        3, 1, subplot_spec=outer[0],
        height_ratios=[1.6, 0.9, 1.2], hspace=0.06
    )
    mid_gs = gridspec.GridSpecFromSubplotSpec(
        2, 1, subplot_spec=outer[1],
        height_ratios=[1.7, 1.0], hspace=0.06
    )
    right_gs = gridspec.GridSpecFromSubplotSpec(
        2, 1, subplot_spec=outer[2],
        height_ratios=[1.7, 1.0], hspace=0.06
    )

    def titled_ax(gs_pos, title, title_color=MUTED):
        ax = fig.add_subplot(gs_pos)
        ax.set_facecolor(BG)
        for sp in ax.spines.values():
            sp.set_color(BORDER)
        ax.set_title(title, fontsize=12, color=title_color,
                     fontweight="bold", pad=8, loc="left")
        return ax

    # Col izq
    ax_clock = titled_ax(left_gs[0], "RELOJ DEL CICLO")
    draw_clock(ax_clock, scores, phase)

    ax_bars = titled_ax(left_gs[1], "SCORING POR FASE  (ponderado)")
    draw_bars(ax_bars, scores, phase, momentum)

    ax_ind = titled_ax(left_gs[2], "INDICADORES MACROECONÓMICOS")
    draw_indicators(ax_ind, m, pcts)

    # Col centro
    ax_rf = titled_ax(mid_gs[0], f"RENTA FIJA  —  {phase}", col_ph)
    draw_recs(ax_rf, FIXED_INCOME_RECS[phase], col_ph)

    ax_bd = titled_ax(mid_gs[1], "DESGLOSE DEL SCORING")
    # Desglose: si motor logístico → mostrar probabilidades del modelo
    # Si motor tradicional → mostrar reglas del scoring
    _eng_bd = result.get("engine", result.get("active_engine", "tradicional"))
    _lp_bd  = result.get("logit_pred")
    if "logístico" in _eng_bd and _lp_bd:
        draw_logistic_breakdown(ax_bd, _lp_bd, result)
    else:
        draw_breakdown(ax_bd, breakdown)

    # Col derecha
    ax_rv = titled_ax(right_gs[0], f"RENTA VARIABLE  —  {phase}", col_ph)
    draw_recs(ax_rv, EQUITY_RECS[phase], col_ph)

    ax_con = titled_ax(right_gs[1],
                       "ACTIVOS CONSENSO (confianza < 55%)" if conf < 0.55 else "LEYENDA DE RATINGS")
    draw_consensus_or_legend(ax_con, phase, secondary, conf,
                             FIXED_INCOME_RECS, EQUITY_RECS, common_assets)

    return fig


# ══════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════
def main():
    print("╔══════════════════════════════════════════════════╗")
    print("║   INVESTMENT CLOCK  v3  —  Motor Logístico       ║")
    print("╚══════════════════════════════════════════════════╝\n")

    # ── 1. DATOS ───────────────────────────────────────────────────
    data = download_all()

    print("📐  Calculando métricas...")
    m = calculate_metrics(data)

    print("📊  Calculando percentiles históricos...")
    pcts = compute_percentiles(data)

    # ── 2. SCORING TRADICIONAL (siempre — puede ser fallback) ──────
    print("📏  Scoring tradicional...")
    trad_result = score_phase(m, pcts)

    # ── 3. MODELO LOGÍSTICO ────────────────────────────────────────
    print("🧠  Entrenando / cargando modelo logístico...")
    model = train_model(data)

    logit_result = predict(m, model) if model else None

    # ── 4. SELECCIÓN DEL MOTOR ─────────────────────────────────────
    result = select_engine(logit_result, trad_result, model)

    engine    = result["engine"]
    phase     = result["phase"]
    conf      = result["confidence"]
    secondary = result["secondary"]
    scores    = result["scores"]
    reason    = result["reason"]
    alt       = result["alt"]  # motor alternativo (para referencia)

    # ── 5. EXTRAS (momentum + interpretación) ──────────────────────
    print("📈  Calculando momentum...")
    momentum = calculate_momentum(data, pcts)

    print("🤖  Generando interpretación...")
    # score_dual para la interpretación (usa internamente dual signal)
    dual = score_dual(m, pcts)
    interpretation = generate_interpretation(m, dual, momentum, pcts)

    # ── 6. RESUMEN EN CONSOLA ──────────────────────────────────────
    conf_pct = conf * 100
    print(f"\n  ┌─────────────────────────────────────────────┐")
    print(f"  │  MOTOR    : {engine.upper():<33s}│")
    print(f"  │  RAZÓN    : {reason:<33s}│")
    print(f"  │  FASE     : {phase:<33s}│")
    print(f"  │  CONFIANZA: {conf_pct:.0f}%{' '*31}│")
    print(f"  │  SECUNDAR.: {secondary:<33s}│")
    print(f"  └─────────────────────────────────────────────┘\n")

    print("  Scores:")
    for ph, sc in sorted(scores.items(), key=lambda x: -x[1]):
        marker = "  ◀ ACTIVA" if ph == phase else ""
        print(f"    {ph:<25s}: {sc:5.1f}%{marker}")

    if alt:
        alt_engine = "tradicional" if engine == "logístico" else "logístico"
        alt_phase  = alt.get("phase","?")
        alt_conf   = alt.get("confidence", 0)
        alt_conf_pct = alt_conf * 100 if alt_conf <= 1 else alt_conf
        agree = "✓" if alt_phase == phase else "≠"
        print(f"\n  Referencia ({alt_engine}): {alt_phase} ({alt_conf_pct:.0f}%) {agree}")

    # ── 7. DASHBOARD ───────────────────────────────────────────────
    # Enriquecer result para el dashboard (compatibilidad con build_dashboard)
    result["logit_pred"]   = logit_result
    result["model_acc"]    = model.get("cv_accuracy", 0) if model else 0
    result["model_samples"]= model.get("n_samples", 0) if model else 0
    result["trad_phase"]   = trad_result["phase"]
    result["trad_conf"]    = trad_result["confidence"]
    result["trad_scores"]  = trad_result["scores"]
    result["logit_active"] = (engine == "logístico")
    result["_m"]           = m      # métricas actuales para diagnóstico
    result["_pcts"]        = pcts   # percentiles actuales para diagnóstico

    print("\n🎨  Generando dashboard...")
    fig = build_dashboard(m, result, FIXED_INCOME_RECS, EQUITY_RECS,
                          common_assets, pcts, momentum, dual, interpretation)

    fname = f"investment_clock_{datetime.now().strftime('%Y%m%d_%H%M')}.png"
    fig.savefig(fname, dpi=150, bbox_inches="tight", facecolor=BG, edgecolor="none")

    try:
        get_ipython
        import matplotlib.pyplot as plt
        plt.show()
        print(f"\n  ✅  Mostrado inline y guardado: {fname}")
    except NameError:
        import matplotlib.pyplot as plt
        plt.close(fig)
        import subprocess, sys
        try:
            if sys.platform == "win32":
                subprocess.Popen(["start", fname], shell=True)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", fname])
            else:
                subprocess.Popen(["xdg-open", fname])
        except Exception:
            pass
        print(f"\n  ✅  Imagen guardada: {fname}")
    print(f"  💡  VS Code: usa # %% para ejecutar como celda interactiva\n")


if __name__ == "__main__":
    main()
