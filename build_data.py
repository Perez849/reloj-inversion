#!/usr/bin/env python3
"""
Investment Clock — motor de datos.

Genera docs/data/data.json con:
  1. Factores macro (Crecimiento / Inflación / Condiciones adelantadas) construidos
     por componentes principales sobre z-scores, sin ponderaciones a mano.
  2. Clasificación de fase con probabilidades cerradas (normal bivariante).
  3. Retornos condicionales por fase de un universo amplio de activos, con
     t-stat Newey-West y control de falsos descubrimientos (Benjamini-Hochberg).
  4. Backtest walk-forward (sin look-ahead) frente al in-sample, para medir
     cuánto del resultado es sobreajuste.

Dependencias: pandas, numpy, requests.
"""

from __future__ import annotations

import io
import json
import math
import os
import sys
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import requests

# --------------------------------------------------------------------------------------
# Configuración general
# --------------------------------------------------------------------------------------

OUT_PATH = os.environ.get("OUT_PATH", "docs/data/data.json")
START = "1959-01-01"
HTTP_TIMEOUT = 60
RETRIES = 4
WARNINGS: list[str] = []


def warn(msg: str) -> None:
    print(f"  ! {msg}")
    WARNINGS.append(msg)


def http_get(url: str, tries: int = RETRIES) -> requests.Response | None:
    headers = {"User-Agent": "investment-clock/2.0 (+github pages dashboard)"}
    for attempt in range(tries):
        try:
            r = requests.get(url, timeout=HTTP_TIMEOUT, headers=headers)
            if r.status_code == 200 and r.content:
                return r
            raise RuntimeError(f"HTTP {r.status_code}")
        except Exception as exc:  # noqa: BLE001
            if attempt == tries - 1:
                warn(f"descarga fallida: {url.split('?')[0]} ({exc})")
                return None
            time.sleep(1.5 * (attempt + 1))
    return None


# --------------------------------------------------------------------------------------
# 1. Definición de series
# --------------------------------------------------------------------------------------
# transform:
#   yoy      -> variación interanual en %
#   yoy_log  -> variación interanual log (para series muy volátiles: petróleo)
#   d3       -> cambio a 3 meses (nivel)
#   d12      -> cambio a 12 meses (nivel)
#   lvl      -> nivel tal cual
#   g3_ann   -> crecimiento a 3 meses anualizado en %
#   ratio_yoy-> variación interanual de la media de 3m (empleo)
# lag_m: meses de retraso de publicación. Se aplica al histórico para que el
#        backtest use solo información realmente disponible en cada fecha.

@dataclass
class Series:
    fred_id: str
    name: str
    block: str                 # growth | inflation | leading
    transform: str
    lag_m: int = 1
    invert: bool = False
    note: str = ""


SERIES: list[Series] = [
    # ---------------- Crecimiento (coincidente) --------------------------------------
    Series("CFNAIMA3", "Chicago Fed National Activity (MA3)", "growth", "lvl", 1,
           note="PCA de 85 indicadores; 0 = crecimiento tendencial por construcción"),
    Series("INDPRO", "Producción industrial", "growth", "yoy", 1),
    Series("PAYEMS", "Nóminas no agrícolas", "growth", "ratio_yoy", 1),
    Series("ICSA", "Peticiones de desempleo", "growth", "yoy", 0, invert=True,
           note="Semanal; se promedia a mes. Invertida: más paro = menos crecimiento"),
    Series("CMRMTSPL", "Ventas reales manufactura y comercio", "growth", "yoy", 2),
    Series("W875RX1", "Renta personal real ex transferencias", "growth", "yoy", 1),
    Series("RRSFS", "Ventas minoristas reales", "growth", "yoy", 1),
    Series("TCU", "Utilización de capacidad", "growth", "d12", 1),
    Series("UMCSENT", "Sentimiento del consumidor", "growth", "d12", 0),
    Series("HOUST", "Viviendas iniciadas", "growth", "yoy", 1),

    # ---------------- Inflación -------------------------------------------------------
    Series("PCEPILFE", "PCE subyacente", "inflation", "yoy", 2,
           note="Medida objetivo de la Fed"),
    Series("CPILFESL", "IPC subyacente", "inflation", "yoy", 1),
    Series("CPIAUCSL", "IPC general", "inflation", "yoy", 1),
    Series("MEDCPIM158SFRBCLE", "IPC mediano (Cleveland Fed)", "inflation", "lvl", 1,
           note="Estimador robusto: mediana ponderada de la cesta"),
    Series("PCETRIM12M159SFRBDAL", "PCE media truncada (Dallas Fed)", "inflation", "lvl", 2),
    Series("PPIACO", "Precios de producción", "inflation", "yoy", 1),
    Series("AHETPI", "Salario horario producción", "inflation", "yoy", 1),
    Series("T5YIE", "Breakeven 5 años", "inflation", "lvl", 0),
    Series("T5YIFR", "Breakeven 5a5a forward", "inflation", "lvl", 0),
    Series("DCOILWTICO", "Petróleo WTI", "inflation", "yoy_log", 0),

    # ---------------- Condiciones adelantadas ----------------------------------------
    Series("T10Y3M", "Curva 10a-3m", "leading", "lvl", 0,
           note="Predictor de recesión más contrastado (Estrella-Mishkin)"),
    Series("T10Y2Y", "Curva 10a-2a", "leading", "lvl", 0),
    Series("NFCI", "Condiciones financieras (Chicago Fed)", "leading", "lvl", 0,
           invert=True, note="0 = condiciones medias por construcción"),
    Series("BAMLH0A0HYM2", "Diferencial High Yield", "leading", "lvl", 0, invert=True),
    Series("PERMIT", "Permisos de construcción", "leading", "yoy", 1),
    Series("USSLIND", "Índice adelantado (Philadelphia Fed)", "leading", "lvl", 2),
    Series("VIXCLS", "VIX", "leading", "lvl", 0, invert=True),
    Series("AWHMAN", "Horas semanales manufactura", "leading", "d12", 1),
]

FRED_EXTRA = ["USREC", "TB3MS", "DGS2", "DGS10", "DGS30", "UNRATE", "FEDFUNDS"]

PHASES = [
    "Recuperación",
    "Sobrecalentamiento",
    "Estanflación",
    "Reflación",
]
PHASE_LONG = {
    "Recuperación": "Recuperación (12-3)",
    "Sobrecalentamiento": "Sobrecalentamiento (3-6)",
    "Estanflación": "Estanflación (6-9)",
    "Reflación": "Reflación / Recesión (9-12)",
}


# --------------------------------------------------------------------------------------
# 2. Descarga
# --------------------------------------------------------------------------------------

def fred_series(series_id: str) -> pd.Series | None:
    url = (
        "https://fred.stlouisfed.org/graph/fredgraph.csv"
        f"?id={series_id}&cosd={START}"
    )
    r = http_get(url)
    if r is None:
        return None
    try:
        df = pd.read_csv(io.StringIO(r.text))
        date_col = df.columns[0]
        val_col = df.columns[1]
        df[date_col] = pd.to_datetime(df[date_col])
        s = pd.to_numeric(df[val_col], errors="coerce")
        s.index = df[date_col]
        s = s.dropna()
        s.name = series_id
        return s
    except Exception as exc:  # noqa: BLE001
        warn(f"parseo FRED {series_id}: {exc}")
        return None


def to_monthly(s: pd.Series, how: str = "mean") -> pd.Series:
    """Colapsa a fin de mes. Diarias/semanales -> media del mes (menos ruido de fecha)."""
    if s.empty:
        return s
    inferred = pd.infer_freq(s.index[:20]) if len(s) > 20 else None
    if inferred is not None and inferred.startswith(("M", "Q")):
        out = s.resample("ME").last()
    else:
        out = s.resample("ME").mean() if how == "mean" else s.resample("ME").last()
    return out.dropna()


def fetch_macro() -> tuple[pd.DataFrame, dict]:
    print("1. Descargando FRED…")
    raw: dict[str, pd.Series] = {}
    meta: dict[str, dict] = {}
    ids = [s.fred_id for s in SERIES] + FRED_EXTRA
    for sid in ids:
        s = fred_series(sid)
        if s is None or s.empty:
            continue
        raw[sid] = to_monthly(s)
        meta[sid] = {
            "last_obs": str(s.index[-1].date()),
            "last_raw": float(s.iloc[-1]),
        }
        print(f"  ✓ {sid:<22} {len(s):>6} obs  hasta {s.index[-1].date()}")
    if len(raw) < 10:
        raise SystemExit("Datos insuficientes de FRED; abortando.")
    df = pd.DataFrame(raw)
    df.index = df.index.to_period("M").to_timestamp("M")
    return df, meta


# --------------------------------------------------------------------------------------
# 3. Transformaciones y z-scores
# --------------------------------------------------------------------------------------

def transform(s: pd.Series, kind: str) -> pd.Series:
    s = s.astype(float)
    if kind == "lvl":
        return s
    if kind == "yoy":
        return (s / s.shift(12) - 1.0) * 100.0
    if kind == "yoy_log":
        return np.log(s / s.shift(12)) * 100.0
    if kind == "ratio_yoy":
        r = s.rolling(3).mean()
        return (r / r.shift(12) - 1.0) * 100.0
    if kind == "d3":
        return s - s.shift(3)
    if kind == "d12":
        return s - s.shift(12)
    if kind == "g3_ann":
        return ((s / s.shift(3)) ** 4 - 1.0) * 100.0
    raise ValueError(kind)


def expanding_z(s: pd.Series, min_periods: int = 120) -> pd.Series:
    """
    z-score con media y desviación *expansivas*: en cada fecha solo usa el pasado.
    Evita el look-ahead que introduce estandarizar con la muestra completa.
    """
    mu = s.expanding(min_periods=min_periods).mean()
    sd = s.expanding(min_periods=min_periods).std()
    z = (s - mu) / sd
    return z.clip(-4, 4)


def build_blocks(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    print("2. Transformando y estandarizando…")
    zs: dict[str, pd.Series] = {}
    info: dict[str, dict] = {}
    for spec in SERIES:
        if spec.fred_id not in df.columns:
            warn(f"serie ausente: {spec.fred_id} ({spec.name})")
            continue
        x = transform(df[spec.fred_id], spec.transform)
        if spec.invert:
            x = -x
        z = expanding_z(x)
        # Retraso de publicación: la observación del mes t no está disponible hasta t+lag
        z = z.shift(spec.lag_m)
        zs[spec.fred_id] = z
        info[spec.fred_id] = {
            "id": spec.fred_id,
            "name": spec.name,
            "block": spec.block,
            "transform": spec.transform,
            "lag_m": spec.lag_m,
            "invert": spec.invert,
            "note": spec.note,
            "raw_last": float(x.dropna().iloc[-1]) if x.dropna().size else None,
        }
    Z = pd.DataFrame(zs)
    return Z, info


# --------------------------------------------------------------------------------------
# 4. Factores por componentes principales
# --------------------------------------------------------------------------------------

def first_pc(Z: pd.DataFrame, anchor: str | None = None) -> tuple[pd.Series, dict]:
    """
    Primer componente principal de un bloque de z-scores.
    Los pesos salen de la matriz de correlaciones: no hay ninguna elección manual.
    El signo se ancla a una serie de referencia para que el factor sea interpretable.
    """
    X = Z.dropna(how="all")
    # Para el cálculo de la matriz de covarianzas usamos el tramo con cobertura amplia
    core = X.dropna(thresh=max(3, int(X.shape[1] * 0.6)))
    filled = core.apply(lambda c: c.fillna(c.mean()), axis=0)
    C = np.corrcoef(filled.values, rowvar=False)
    C = np.nan_to_num(C, nan=0.0)
    vals, vecs = np.linalg.eigh(C)
    order = np.argsort(vals)[::-1]
    vals, vecs = vals[order], vecs[:, order]
    w = vecs[:, 0]
    explained = float(vals[0] / vals.sum())

    cols = list(X.columns)
    if anchor and anchor in cols and w[cols.index(anchor)] < 0:
        w = -w
    elif w.sum() < 0:
        w = -w

    # Proyección tolerante a huecos: media ponderada de las series disponibles
    W = pd.Series(w, index=cols)
    num = X.mul(W, axis=1).sum(axis=1, min_count=1)
    den = X.notna().mul(W.abs(), axis=1).sum(axis=1)
    f = num / den.replace(0, np.nan)
    f = f / f.std()
    loadings = {c: round(float(v), 3) for c, v in W.items()}
    return f.dropna(), {"explained_var": round(explained, 3), "loadings": loadings}


def build_factors(Z: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    print("3. Extrayendo factores (PCA)…")
    out = {}
    diag = {}
    for block, anchor in [("growth", "CFNAIMA3"),
                          ("inflation", "PCEPILFE"),
                          ("leading", "T10Y3M")]:
        cols = [s.fred_id for s in SERIES
                if s.block == block and s.fred_id in Z.columns]
        if len(cols) < 2:
            warn(f"bloque {block} con muy pocas series")
            continue
        f, d = first_pc(Z[cols], anchor=anchor)
        out[block] = f
        diag[block] = d
        print(f"  ✓ {block:<10} {len(cols)} series, "
              f"varianza explicada {d['explained_var']:.0%}")
    F = pd.DataFrame(out).dropna(how="all")
    return F, diag


# --------------------------------------------------------------------------------------
# 5. Clasificación de fase y probabilidades
# --------------------------------------------------------------------------------------

def classify(g: float, i: float) -> str:
    if g >= 0 and i < 0:
        return "Recuperación"
    if g >= 0 and i >= 0:
        return "Sobrecalentamiento"
    if g < 0 and i >= 0:
        return "Estanflación"
    return "Reflación"


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def phase_probs(g: float, i: float, sg: float, si: float) -> dict[str, float]:
    """
    Probabilidad de cada cuadrante tratando el factor medido como una estimación
    ruidosa del factor verdadero: g_obs ~ N(g_true, sg²).
    Los componentes principales son ortogonales, de modo que la probabilidad
    conjunta factoriza y se resuelve en forma cerrada.
    sg, si son la desviación típica del desplazamiento del factor a lo largo del
    horizonte de inversión (3 meses), estimada del propio histórico: recoge a la vez
    el ruido de medición y el hecho de que la economía se mueve mientras mantienes
    la cartera.
    """
    pg_pos = norm_cdf(g / sg)
    pi_pos = norm_cdf(i / si)
    return {
        "Recuperación": pg_pos * (1 - pi_pos),
        "Sobrecalentamiento": pg_pos * pi_pos,
        "Estanflación": (1 - pg_pos) * pi_pos,
        "Reflación": (1 - pg_pos) * (1 - pi_pos),
    }


# --------------------------------------------------------------------------------------
# 6. Probabilidad de recesión (logit sobre la curva) — estimada, no importada
# --------------------------------------------------------------------------------------

def fit_logit(X: np.ndarray, y: np.ndarray, iters: int = 60) -> np.ndarray:
    """IRLS con pequeña regularización ridge para estabilidad numérica."""
    X = np.column_stack([np.ones(len(X)), X])
    beta = np.zeros(X.shape[1])
    for _ in range(iters):
        eta = X @ beta
        p = 1.0 / (1.0 + np.exp(-np.clip(eta, -30, 30)))
        W = np.clip(p * (1 - p), 1e-6, None)
        z = eta + (y - p) / W
        A = X.T @ (X * W[:, None]) + 1e-4 * np.eye(X.shape[1])
        beta_new = np.linalg.solve(A, X.T @ (W * z))
        if np.max(np.abs(beta_new - beta)) < 1e-8:
            beta = beta_new
            break
        beta = beta_new
    return beta


def recession_model(df: pd.DataFrame, F: pd.DataFrame) -> dict:
    """Logit: P(recesión NBER en los próximos 12 meses) ~ curva 10a-3m + NFCI."""
    if "USREC" not in df.columns or "T10Y3M" not in df.columns:
        return {}
    rec = df["USREC"].reindex(F.index).fillna(0)
    fwd = rec[::-1].rolling(12, min_periods=1).max()[::-1].shift(-1)
    feats = ["T10Y3M"]
    if "NFCI" in df.columns:
        feats.append("NFCI")
    X = df[feats].reindex(F.index)
    data = pd.concat([X, fwd.rename("y")], axis=1).dropna()
    if len(data) < 200:
        return {}
    beta = fit_logit(data[feats].values, data["y"].values)
    last = df[feats].dropna().iloc[-1].values
    eta = beta[0] + float(np.dot(beta[1:], last))
    p = 1.0 / (1.0 + math.exp(-max(min(eta, 30), -30)))

    # Calidad en muestra: AUC
    eta_all = beta[0] + data[feats].values @ beta[1:]
    p_all = 1 / (1 + np.exp(-np.clip(eta_all, -30, 30)))
    y = data["y"].values
    auc = float("nan")
    if 0 < y.sum() < len(y):
        order = np.argsort(p_all)
        ranks = np.empty(len(p_all))
        ranks[order] = np.arange(1, len(p_all) + 1)
        n1, n0 = y.sum(), (1 - y).sum()
        auc = float((ranks[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))
    return {
        "prob_12m": round(p, 4),
        "auc": round(auc, 3) if auc == auc else None,
        "features": feats,
        "coef": [round(float(b), 4) for b in beta],
        "n_obs": int(len(data)),
    }


# --------------------------------------------------------------------------------------
# 7. Universo de activos y retornos
# --------------------------------------------------------------------------------------

def french_zip(url: str, skip_hint: str = "") -> pd.DataFrame | None:
    r = http_get(url)
    if r is None:
        return None
    try:
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        name = zf.namelist()[0]
        text = zf.read(name).decode("latin-1")
        lines = text.splitlines()
        start = None
        for idx, line in enumerate(lines):
            token = line.strip().split(",")[0].strip()
            if len(token) == 6 and token.isdigit():
                start = idx
                break
        if start is None:
            return None
        header_idx = start - 1
        while header_idx > 0 and not lines[header_idx].strip():
            header_idx -= 1
        rows = []
        for line in lines[start:]:
            token = line.strip().split(",")[0].strip()
            if not (len(token) == 6 and token.isdigit()):
                break
            rows.append(line)
        header = [c.strip() for c in lines[header_idx].split(",")]
        if header[0] == "":
            header[0] = "date"
        buf = io.StringIO(",".join(header) + "\n" + "\n".join(rows))
        df = pd.read_csv(buf)
        df["date"] = pd.to_datetime(df["date"].astype(int).astype(str), format="%Y%m")
        df = df.set_index("date").apply(pd.to_numeric, errors="coerce")
        df.index = df.index.to_period("M").to_timestamp("M")
        return df.replace([-99.99, -999], np.nan)
    except Exception as exc:  # noqa: BLE001
        warn(f"French {skip_hint}: {exc}")
        return None


FRENCH_BASE = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"

FRENCH_IND_MAP = {
    "NoDur": ("Consumo básico", "Renta variable"),
    "Durbl": ("Consumo duradero", "Renta variable"),
    "Manuf": ("Industria", "Renta variable"),
    "Enrgy": ("Energía", "Renta variable"),
    "Chems": ("Materiales / Químicas", "Renta variable"),
    "BusEq": ("Tecnología", "Renta variable"),
    "Telcm": ("Comunicaciones", "Renta variable"),
    "Utils": ("Utilities", "Renta variable"),
    "Shops": ("Consumo discrecional", "Renta variable"),
    "Hlth": ("Salud", "Renta variable"),
    "Money": ("Financiero", "Renta variable"),
    "Other": ("Otros sectores", "Renta variable"),
}

FRED_TR = {
    "BAMLCC0A0CMTRIV": ("Crédito Investment Grade", "Renta fija"),
    "BAMLHYH0A0HYM2TRIV": ("Crédito High Yield", "Renta fija"),
    "BAMLEMCBPITRIV": ("Deuda emergente corporativa", "Renta fija"),
    "BAMLCC1A013YTRIV": ("IG 1-3 años", "Renta fija"),
    "BAMLCC4A0710YTRIV": ("IG 7-10 años", "Renta fija"),
    "BAMLCC8A015PYTRIV": ("IG 15+ años", "Renta fija"),
}

STOOQ = {
    "xauusd": ("Oro", "Real / alternativos"),
    "^spgsci": ("Materias primas (GSCI)", "Real / alternativos"),
    "vnq.us": ("Inmobiliario (REITs)", "Real / alternativos"),
    "eem.us": ("Renta variable emergente", "Renta variable"),
    "efa.us": ("Renta variable internacional", "Renta variable"),
    "iwd.us": ("Value (Russell 1000 Value)", "Estilo"),
    "iwf.us": ("Growth (Russell 1000 Growth)", "Estilo"),
    "iwm.us": ("Small caps", "Estilo"),
    "tip.us": ("TIPS (ligados a inflación)", "Renta fija"),
    "mub.us": ("Municipales", "Renta fija"),
    "mbb.us": ("Titulizaciones hipotecarias (MBS)", "Renta fija"),
}


def stooq_monthly(ticker: str) -> pd.Series | None:
    url = f"https://stooq.com/q/d/l/?s={ticker}&i=m"
    r = http_get(url, tries=2)
    if r is None or "Date" not in r.text[:200]:
        return None
    try:
        df = pd.read_csv(io.StringIO(r.text))
        df["Date"] = pd.to_datetime(df["Date"])
        s = df.set_index("Date")["Close"].astype(float)
        s.index = s.index.to_period("M").to_timestamp("M")
        return s.pct_change().dropna() * 100.0
    except Exception as exc:  # noqa: BLE001
        warn(f"stooq {ticker}: {exc}")
        return None


def treasury_returns(df: pd.DataFrame) -> dict[str, pd.Series]:
    """
    Retorno total aproximado de un bono cupón par mediante duración y convexidad:
        r ≈ y/12 - D*Δy + 0.5*C*Δy²
    Es una aproximación (no un índice real), suficiente para ordenar fases y
    documentada como tal en la metodología.
    """
    out = {}
    spec = {"DGS2": (1.9, 4.5, "Treasury 2 años"),
            "DGS10": (8.2, 80.0, "Treasury 10 años"),
            "DGS30": (18.5, 450.0, "Treasury 30 años")}
    for col, (dur, cvx, label) in spec.items():
        if col not in df.columns:
            continue
        y = df[col].dropna() / 100.0
        dy = y.diff()
        r = (y.shift(1) / 12.0 - dur * dy + 0.5 * cvx * dy ** 2) * 100.0
        out[label] = r.dropna()
    if "TB3MS" in df.columns:
        out["Liquidez (letras 3m)"] = (df["TB3MS"] / 12.0).dropna()
    return out


def fetch_assets(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    print("4. Descargando retornos de activos…")
    rets: dict[str, pd.Series] = {}
    meta: dict[str, dict] = {}

    def add(key, series, cls, source):
        if series is None or series.dropna().size < 60:
            return
        rets[key] = series.dropna()
        meta[key] = {"class": cls, "source": source,
                     "from": str(series.dropna().index[0].date())}

    # Ken French: 12 industrias + factores (desde 1926)
    ind = french_zip(FRENCH_BASE + "12_Industry_Portfolios_CSV.zip", "industrias")
    ff = french_zip(FRENCH_BASE + "F-F_Research_Data_Factors_CSV.zip", "factores")
    rf = None
    if ff is not None and "RF" in ff.columns:
        rf = ff["RF"]
        add("Renta variable EE.UU. (mercado)", ff["Mkt-RF"] + rf,
            "Renta variable", "Ken French")
        if "HML" in ff.columns:
            add("Prima Value (HML)", ff["HML"], "Estilo", "Ken French")
            add("Prima Tamaño (SMB)", ff["SMB"], "Estilo", "Ken French")
    if ind is not None:
        for col, (label, cls) in FRENCH_IND_MAP.items():
            if col in ind.columns:
                add(label, ind[col], cls, "Ken French")

    mom = french_zip(FRENCH_BASE + "F-F_Momentum_Factor_CSV.zip", "momentum")
    if mom is not None:
        col = [c for c in mom.columns if "Mom" in c]
        if col:
            add("Prima Momentum", mom[col[0]], "Estilo", "Ken French")

    # Índices de retorno total ICE BofA vía FRED
    for sid, (label, cls) in FRED_TR.items():
        s = fred_series(sid)
        if s is None:
            continue
        m = to_monthly(s, how="last")
        m.index = m.index.to_period("M").to_timestamp("M")
        add(label, m.pct_change() * 100.0, cls, "ICE BofA / FRED")

    # Treasuries sintéticos
    for label, s in treasury_returns(df).items():
        cls = "Liquidez" if "Liquidez" in label else "Renta fija"
        add(label, s, cls, "FRED (aprox. duración)")

    # Stooq (mejor esfuerzo)
    for tick, (label, cls) in STOOQ.items():
        add(label, stooq_monthly(tick), cls, "Stooq")

    R = pd.DataFrame(rets)
    # Exceso sobre liquidez
    if rf is None:
        rf = (df["TB3MS"] / 12.0) if "TB3MS" in df.columns else pd.Series(0.0, index=R.index)
    rf = rf.reindex(R.index).ffill().fillna(0.0)
    X = R.sub(rf, axis=0)
    print(f"  ✓ {X.shape[1]} activos, {X.dropna(how='all').shape[0]} meses")
    return X, meta


# --------------------------------------------------------------------------------------
# 8. Estadística condicional
# --------------------------------------------------------------------------------------

def newey_west_t(x: np.ndarray, lags: int = 3) -> tuple[float, float]:
    """Media y t-stat con errores estándar robustos a autocorrelación."""
    x = x[~np.isnan(x)]
    n = len(x)
    if n < 12:
        return float("nan"), float("nan")
    mu = x.mean()
    e = x - mu
    gamma0 = (e @ e) / n
    var = gamma0
    for l in range(1, min(lags, n - 1) + 1):
        g = (e[l:] @ e[:-l]) / n
        var += 2 * (1 - l / (lags + 1)) * g
    se = math.sqrt(max(var, 1e-12) / n)
    return mu, mu / se


def benjamini_hochberg(pvals: list[float], alpha: float = 0.10) -> list[float]:
    """q-values (FDR). Controla falsos positivos al testar muchas casillas."""
    p = np.array(pvals, dtype=float)
    ok = ~np.isnan(p)
    q = np.full_like(p, np.nan)
    idx = np.where(ok)[0]
    if idx.size == 0:
        return q.tolist()
    order = idx[np.argsort(p[idx])]
    m = len(order)
    prev = 1.0
    for rank in range(m - 1, -1, -1):
        i = order[rank]
        val = p[i] * m / (rank + 1)
        prev = min(prev, val)
        q[i] = min(prev, 1.0)
    return q.tolist()


def two_sided_p(t: float) -> float:
    if t != t:
        return float("nan")
    return 2 * (1 - norm_cdf(abs(t)))


def grade_from_t(t: float, q: float) -> str:
    """
    La nota sale del contraste estadístico, no de una opinión:
      |t| >= 2.58 (p<0.01) y FDR ok -> +++/---
      |t| >= 1.96 (p<0.05)          -> ++/--
      |t| >= 1.28 (p<0.20)          -> +/-
      resto                         -> 0
    """
    if t != t:
        return "s/d"
    a = abs(t)
    sign = "+" if t > 0 else "-"
    if a >= 2.58 and (q != q or q <= 0.10):
        return sign * 3
    if a >= 1.96:
        return sign * 2
    if a >= 1.28:
        return sign * 1
    return "0"


def conditional_stats(X: pd.DataFrame, phases: pd.Series, meta: dict) -> list[dict]:
    print("5. Estimando retornos condicionales por fase…")
    rows = []
    cells = []
    for col in X.columns:
        s = X[col].dropna()
        ph = phases.reindex(s.index).dropna()
        s = s.reindex(ph.index)
        if s.size < 60:
            continue
        uncond_mu, _ = newey_west_t(s.values)
        entry = {
            "id": col,
            "name": col,
            "class": meta.get(col, {}).get("class", "Otros"),
            "source": meta.get(col, {}).get("source", ""),
            "from": str(s.index[0].date()),
            "n": int(s.size),
            "uncond_ann": round(float(uncond_mu * 12), 2),
            "phases": {},
        }
        for phase in PHASES:
            sub = s[ph == phase]
            if sub.size < 12:
                entry["phases"][phase] = {"n": int(sub.size)}
                continue
            mu, _ = newey_west_t(sub.values)
            # Contraste relevante: exceso CONDICIONAL frente al comportamiento medio
            diff = sub.values - uncond_mu
            _, t = newey_west_t(diff)
            hit = float((sub.values > 0).mean())
            entry["phases"][phase] = {
                "ann": round(float(mu * 12), 2),
                "rel": round(float((mu - uncond_mu) * 12), 2),
                "t": round(float(t), 2) if t == t else None,
                "hit": round(hit, 3),
                "n": int(sub.size),
                "vol": round(float(sub.std() * math.sqrt(12)), 2),
            }
            cells.append((col, phase, two_sided_p(t)))
        rows.append(entry)

    qs = benjamini_hochberg([c[2] for c in cells])
    qmap = {(c[0], c[1]): q for c, q in zip(cells, qs)}
    for entry in rows:
        for phase, d in entry["phases"].items():
            if "t" not in d or d.get("t") is None:
                d["grade"] = "s/d"
                continue
            q = qmap.get((entry["id"], phase), float("nan"))
            d["q"] = round(q, 3) if q == q else None
            d["grade"] = grade_from_t(d["t"], q)
    sig = sum(1 for e in rows for d in e["phases"].values()
              if d.get("grade") not in (None, "0", "s/d"))
    print(f"  ✓ {len(rows)} activos · {sig} casillas con señal estadística")
    return rows


# --------------------------------------------------------------------------------------
# 9. Backtest walk-forward
# --------------------------------------------------------------------------------------

def perf(series: pd.Series) -> dict:
    s = series.dropna() / 100.0
    if s.size < 24:
        return {}
    curve = (1 + s).cumprod()
    yrs = s.size / 12
    cagr = curve.iloc[-1] ** (1 / yrs) - 1
    vol = s.std() * math.sqrt(12)
    dd = float((curve / curve.cummax() - 1).min())
    _, t = newey_west_t(s.values * 100)
    return {
        "cagr": round(float(cagr * 100), 2),
        "vol": round(float(vol * 100), 2),
        "sharpe": round(float(cagr / vol), 2) if vol > 0 else None,
        "maxdd": round(dd * 100, 2),
        "hit": round(float((s > 0).mean()), 3),
        "t": round(float(t), 2) if t == t else None,
        "months": int(s.size),
        "from": str(s.index[0].date()),
    }


def backtest(X: pd.DataFrame, phases: pd.Series, top_k: int = 5,
             min_train: int = 240) -> dict:
    """
    Walk-forward estricto:
      en el mes t se estima la media por fase SOLO con datos hasta t-1,
      se selecciona el top-k de la fase vigente en t-1 (ya publicada) y se
      mantiene durante el mes t. Ninguna observación futura entra en la decisión.
    El mismo cálculo repetido con la muestra completa da la versión in-sample:
    la diferencia entre ambas es la medida directa de sobreajuste.
    """
    print("6. Backtest walk-forward…")
    common = X.dropna(how="all").index.intersection(phases.dropna().index)
    X = X.loc[common]
    ph = phases.loc[common]
    liquid = X.columns[X.loc[common].notna().mean() > 0.6]
    X = X[liquid]
    if X.shape[1] < 4 or len(common) < min_train + 60:
        warn("histórico insuficiente para el backtest")
        return {}

    oos, is_, dates = [], [], []
    full_means = {p: X[ph == p].mean() for p in PHASES}

    for k in range(min_train, len(common)):
        t = common[k]
        train_idx = common[:k]
        signal_phase = ph.iloc[k - 1]
        hist = X.loc[train_idx]
        hp = ph.loc[train_idx]
        mu = hist[hp == signal_phase].mean()
        avail = X.loc[t].dropna().index
        pick = mu.reindex(avail).dropna().sort_values(ascending=False).head(top_k).index
        if len(pick) == 0:
            continue
        oos.append(float(X.loc[t, pick].mean()))
        pick_is = (full_means[signal_phase].reindex(avail).dropna()
                   .sort_values(ascending=False).head(top_k).index)
        is_.append(float(X.loc[t, pick_is].mean()))
        dates.append(t)

    oos_s = pd.Series(oos, index=dates)
    is_s = pd.Series(is_, index=dates)
    eq = X.get("Renta variable EE.UU. (mercado)")
    bond = X.get("Treasury 10 años")
    bench = None
    if eq is not None and bond is not None:
        bench = (0.6 * eq + 0.4 * bond).reindex(dates)
    ew = X.reindex(dates).mean(axis=1)

    curve = [{"d": d.strftime("%Y-%m"),
              "s": round(float(v), 4),
              "b": round(float(bench.loc[d]), 4) if bench is not None
                   and d in bench.index and bench.loc[d] == bench.loc[d] else None}
             for d, v in oos_s.items()]

    print(f"  ✓ {len(oos_s)} meses fuera de muestra desde {dates[0].date()}")
    return {
        "oos": perf(oos_s),
        "in_sample": perf(is_s),
        "bench_6040": perf(bench) if bench is not None else {},
        "equal_weight": perf(ew),
        "top_k": top_k,
        "curve": curve[-420:],
    }


# --------------------------------------------------------------------------------------
# 10. Validación de la clasificación
# --------------------------------------------------------------------------------------

def validation(df: pd.DataFrame, F: pd.DataFrame, phases: pd.Series) -> dict:
    out: dict = {}
    if "USREC" in df.columns:
        rec = df["USREC"].reindex(phases.index).dropna()
        p = phases.reindex(rec.index)
        in_rec = rec == 1
        neg_growth = F["growth"].reindex(rec.index) < 0
        out["nber"] = {
            "recall": round(float(neg_growth[in_rec].mean()), 3),
            "specificity": round(float((~neg_growth[~in_rec]).mean()), 3),
            "share_recession_months": round(float(in_rec.mean()), 3),
            "phase_mix_in_recession": {
                ph: round(float((p[in_rec] == ph).mean()), 3) for ph in PHASES
            },
        }
    # Duración media de cada fase y matriz de transición
    runs = {ph: [] for ph in PHASES}
    cur, length = None, 0
    for v in phases.dropna():
        if v == cur:
            length += 1
        else:
            if cur is not None:
                runs[cur].append(length)
            cur, length = v, 1
    if cur is not None:
        runs[cur].append(length)
    out["duration_months"] = {ph: round(float(np.mean(v)), 1) if v else None
                              for ph, v in runs.items()}
    out["share"] = {ph: round(float((phases == ph).mean()), 3) for ph in PHASES}

    T = pd.DataFrame(0.0, index=PHASES, columns=PHASES)
    seq = phases.dropna().tolist()
    for a, b in zip(seq[:-1], seq[1:]):
        T.loc[a, b] += 1
    T = T.div(T.sum(axis=1).replace(0, np.nan), axis=0).fillna(0)
    out["transition"] = {a: {b: round(float(T.loc[a, b]), 3) for b in PHASES}
                         for a in PHASES}
    out["factor_corr"] = round(float(F["growth"].corr(F["inflation"])), 3)
    return out


# --------------------------------------------------------------------------------------
# 11. Ensamblado
# --------------------------------------------------------------------------------------

def main() -> None:
    t0 = time.time()
    df, raw_meta = fetch_macro()
    Z, ind_info = build_blocks(df)
    F, pca_diag = build_factors(Z)

    F = F.dropna(subset=["growth", "inflation"])
    phases = pd.Series([classify(g, i) for g, i in zip(F["growth"], F["inflation"])],
                       index=F.index, name="phase")

    # Incertidumbre relevante: no es el error de un mes, es cuánto se desplaza el
    # factor durante el horizonte en el que se mantiene la posición (3 meses).
    # Se estima directamente del histórico, sin suponer nada.
    HORIZON_M = 3
    sg = float(F["growth"].diff(HORIZON_M).std())
    si = float(F["inflation"].diff(HORIZON_M).std())
    g_now, i_now = float(F["growth"].iloc[-1]), float(F["inflation"].iloc[-1])
    probs = phase_probs(g_now, i_now, sg, si)
    ranked = sorted(probs.items(), key=lambda kv: kv[1], reverse=True)
    confidence = ranked[0][1] - ranked[1][1]

    X, asset_meta = fetch_assets(df)
    assets = conditional_stats(X, phases, asset_meta)
    bt = backtest(X, phases)
    val = validation(df, F, phases)
    rec = recession_model(df, F)

    # Consenso: activos con nota positiva en la fase principal y en la alternativa
    p1, p2 = ranked[0][0], ranked[1][0]
    consensus = []
    for a in assets:
        d1 = a["phases"].get(p1, {})
        d2 = a["phases"].get(p2, {})
        if str(d1.get("grade", "0")).startswith("+") and str(d2.get("grade", "0")).startswith("+"):
            consensus.append({"name": a["name"], "class": a["class"],
                              "g1": d1["grade"], "g2": d2["grade"],
                              "r1": d1.get("rel"), "r2": d2.get("rel")})
    consensus.sort(key=lambda r: -(r["r1"] or 0))

    indicators = []
    for spec in SERIES:
        if spec.fred_id not in Z.columns:
            continue
        z = Z[spec.fred_id].dropna()
        if z.empty:
            continue
        info = ind_info[spec.fred_id]
        block_load = pca_diag.get(spec.block, {}).get("loadings", {})
        indicators.append({
            **info,
            "z": round(float(z.iloc[-1]), 2),
            "z_prev": round(float(z.iloc[-13]), 2) if z.size > 13 else None,
            "loading": block_load.get(spec.fred_id),
            "last_obs": raw_meta.get(spec.fred_id, {}).get("last_obs"),
            "spark": [round(float(v), 2) for v in z.tail(60).tolist()],
        })

    history = [{"d": d.strftime("%Y-%m"),
                "g": round(float(g), 3),
                "i": round(float(i), 3),
                "p": p}
               for d, g, i, p in zip(F.index, F["growth"], F["inflation"], phases)]

    nber_spans = []
    if "USREC" in df.columns:
        r = df["USREC"].reindex(F.index).fillna(0)
        start = None
        for d, v in r.items():
            if v == 1 and start is None:
                start = d
            elif v == 0 and start is not None:
                nber_spans.append([start.strftime("%Y-%m"), d.strftime("%Y-%m")])
                start = None
        if start is not None:
            nber_spans.append([start.strftime("%Y-%m"), F.index[-1].strftime("%Y-%m")])

    payload = {
        "meta": {
            "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "series_ok": int(Z.shape[1]),
            "series_total": len(SERIES),
            "history_from": history[0]["d"],
            "warnings": WARNINGS,
            "build_seconds": round(time.time() - t0, 1),
        },
        "current": {
            "date": F.index[-1].strftime("%Y-%m"),
            "phase": ranked[0][0],
            "phase_long": PHASE_LONG[ranked[0][0]],
            "alt_phase": ranked[1][0],
            "growth": round(g_now, 3),
            "inflation": round(i_now, 3),
            "leading": round(float(F["leading"].iloc[-1]), 3) if "leading" in F else None,
            "leading_6m": round(float(F["leading"].iloc[-7]), 3)
                          if "leading" in F and len(F) > 7 else None,
            "sigma_g": round(sg, 3),
            "sigma_i": round(si, 3),
            "horizon_m": HORIZON_M,
            "probs": {k: round(v, 4) for k, v in probs.items()},
            "confidence": round(confidence, 4),
            "momentum": {
                "growth_3m": round(float(F["growth"].iloc[-1] - F["growth"].iloc[-4]), 3)
                             if len(F) > 4 else None,
                "inflation_3m": round(float(F["inflation"].iloc[-1] - F["inflation"].iloc[-4]), 3)
                                if len(F) > 4 else None,
            },
            "recession": rec,
        },
        "pca": pca_diag,
        "indicators": indicators,
        "history": history,
        "nber": nber_spans,
        "assets": assets,
        "consensus": consensus[:14],
        "backtest": bt,
        "validation": val,
        "phases": PHASES,
        "phase_long": PHASE_LONG,
    }

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
    size = os.path.getsize(OUT_PATH) / 1024
    print(f"\n✓ {OUT_PATH} ({size:.0f} KB) — fase: {ranked[0][0]} "
          f"(confianza {confidence:.0%})  [{time.time() - t0:.0f}s]")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
