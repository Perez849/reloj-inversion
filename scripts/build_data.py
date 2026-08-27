#!/usr/bin/env python3
"""
Investment Clock — motor de datos (v2).

Cambios frente a v1:
  * Diagnóstico por activo: todo intento de descarga deja rastro en el JSON.
    Ningún activo desaparece en silencio.
  * Universo ampliado con fuentes de historia larga en FRED para oro, materias
    primas, crédito, REITs y TIPS, que es donde la tesis del reloj se juega.
  * Anclaje de signo del PCA por correlación con la media del bloque, no por la
    carga de una serie concreta, que puede salir casi nula.
  * La curva de tipos sale del componente adelantado: anticipa 12-18 meses, no
    co-mueve, y forzarla dentro del PC la dejaba con peso cero.
  * Contracción empírica de Bayes (James-Stein) de las medias por fase.
  * Backtest en varias versiones, una neutral al mercado y otra con la volatilidad
    igualada al 60/40, para separar "acierta la fase" de "asume más riesgo".

Dependencias: pandas, numpy, requests.
"""

from __future__ import annotations

import io
import json
import math
import os
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import requests

OUT_PATH = os.environ.get("OUT_PATH", "docs/data/data.json")
# Matriz de retornos mensuales por activo. Se publica junto a data.json para poder
# reproducir y reprobar la lógica de cartera sin volver a descargar nada.
RETURNS_PATH = os.environ.get("RETURNS_PATH", "docs/data/returns.csv.gz")
START = "1959-01-01"
# La API oficial (api.stlouisfed.org) está pensada para acceso automático y responde
# en milisegundos. El endpoint de gráficos (fred.stlouisfed.org/graph) limita o
# bloquea las peticiones desde servidores, que es lo que tumba los runners de
# GitHub. Con clave se usa la API; sin ella, el CSV como respaldo.
FRED_API_KEY = os.environ.get("FRED_API_KEY", "").strip()
# FRED sirve series de 60 años y a veces tarda: necesita margen.
HTTP_TIMEOUT = 45
RETRIES = 3
# Las fuentes opcionales llevan correa corta. Stooq bloquea las IP de los runners
# de GitHub dejando la conexión abierta en vez de rechazarla: sin este tope, la
# ejecución se queda colgada hasta que el job expira.
OPTIONAL_TIMEOUT = 12
OPTIONAL_BUDGET_S = 90
HORIZON_M = 3
MIN_MONTHS = 60

T_START = time.time()
WARNINGS: list[str] = []
ASSET_LOG: list[dict] = []


def warn(msg: str) -> None:
    print(f"  ! {msg}")
    WARNINGS.append(msg)


def http_get(url: str, tries: int = RETRIES, expect: str | None = None,
             timeout: int = HTTP_TIMEOUT):
    """Descarga con reintentos. `expect` es un texto que debe aparecer al principio
    del cuerpo: algunas fuentes devuelven 200 con un mensaje de error, y sin esta
    comprobación el fallo pasaría desapercibido."""
    headers = {"User-Agent": "Mozilla/5.0 (compatible; investment-clock/2.0)"}
    last = "sin intentos"
    for attempt in range(tries):
        try:
            r = requests.get(url, timeout=timeout, headers=headers)
            if r.status_code != 200 or not r.content:
                raise RuntimeError(f"HTTP {r.status_code}")
            if expect and expect not in r.text[:400]:
                raise RuntimeError(f"cuerpo inesperado: {r.text[:80].strip()!r}")
            return r
        except Exception as exc:  # noqa: BLE001
            last = str(exc)
            if attempt < tries - 1:
                time.sleep(1.5 * (attempt + 1))
    return ("__fail__", last)


# ======================================================================================
# 1. Series macro
# ======================================================================================

@dataclass
class Series:
    fred_id: str
    name: str
    block: str                # growth | inflation | leading | standalone
    transform: str
    lag_m: int = 1
    invert: bool = False
    note: str = ""


SERIES: list[Series] = [
    Series("CFNAIMA3", "Chicago Fed National Activity (MA3)", "growth", "lvl", 1,
           note="PCA de 85 indicadores; 0 = crecimiento tendencial por construcción"),
    Series("INDPRO", "Producción industrial", "growth", "yoy", 1),
    Series("PAYEMS", "Nóminas no agrícolas", "growth", "ratio_yoy", 1),
    Series("ICSA", "Peticiones de desempleo", "growth", "yoy", 0, invert=True),
    Series("CMRMTSPL", "Ventas reales manufactura y comercio", "growth", "yoy", 2),
    Series("W875RX1", "Renta personal real ex transferencias", "growth", "yoy", 1),
    Series("RRSFS", "Ventas minoristas reales", "growth", "yoy", 1),
    Series("TCU", "Utilización de capacidad", "growth", "d12", 1),
    Series("UMCSENT", "Sentimiento del consumidor", "growth", "d12", 0),
    Series("HOUST", "Viviendas iniciadas", "growth", "yoy", 1),

    Series("PCEPILFE", "PCE subyacente", "inflation", "yoy", 2,
           note="Medida objetivo de la Fed"),
    Series("CPILFESL", "IPC subyacente", "inflation", "yoy", 1),
    Series("CPIAUCSL", "IPC general", "inflation", "yoy", 1),
    Series("MEDCPIM158SFRBCLE", "IPC mediano (Cleveland Fed)", "inflation", "lvl", 1),
    Series("PCETRIM12M159SFRBDAL", "PCE media truncada (Dallas Fed)", "inflation", "lvl", 2),
    Series("PPIACO", "Precios de producción", "inflation", "yoy", 1),
    Series("AHETPI", "Salario horario producción", "inflation", "yoy", 1),
    Series("T5YIE", "Breakeven 5 años", "inflation", "lvl", 0),
    Series("T5YIFR", "Breakeven 5a5a forward", "inflation", "lvl", 0),
    Series("DCOILWTICO", "Petróleo WTI", "inflation", "yoy_log", 0),

    Series("NFCI", "Condiciones financieras (Chicago Fed)", "leading", "lvl", 0,
           invert=True, note="0 = condiciones medias por construcción"),
    Series("BAA_AAA", "Diferencial de crédito Baa-Aaa", "leading", "lvl", 1, invert=True,
           note="Calculado de los rendimientos de Moody's: historia desde 1919. "
                "Sustituye al diferencial ICE, truncado a 3 años en abril de 2026"),
    Series("PERMIT", "Permisos de construcción", "leading", "yoy", 1),
    Series("USSLIND", "Índice adelantado (Philadelphia Fed)", "leading", "lvl", 2),
    Series("VIXCLS", "VIX", "leading", "lvl", 0, invert=True),
    Series("AWHMAN", "Horas semanales manufactura", "leading", "d12", 1),

    Series("T10Y3M", "Curva 10a-3m", "standalone", "lvl", 0,
           note="Anticipa 12-18 meses: se muestra aparte y alimenta el modelo de recesión"),
    Series("T10Y2Y", "Curva 10a-2a", "standalone", "lvl", 0),
]

FRED_EXTRA = ["USREC", "TB3MS", "DGS2", "DGS10", "DGS30", "UNRATE", "FEDFUNDS",
              "BAA", "AAA", "DFII10", "MORTGAGE30US"]
# Series que no se descargan: se calculan a partir de otras.
DERIVED = {"BAA_AAA"}

PHASES = ["Recuperación", "Sobrecalentamiento", "Estanflación", "Reflación"]
PHASE_LONG = {
    "Recuperación": "Recuperación (12-3)",
    "Sobrecalentamiento": "Sobrecalentamiento (3-6)",
    "Estanflación": "Estanflación (6-9)",
    "Reflación": "Reflación / Recesión (9-12)",
}


# ======================================================================================
# 2. Descarga FRED
# ======================================================================================

def _fred_api(series_id: str):
    url = ("https://api.stlouisfed.org/fred/series/observations"
           f"?series_id={series_id}&api_key={FRED_API_KEY}"
           f"&file_type=json&observation_start={START}")
    r = http_get(url)
    if isinstance(r, tuple):
        return None, f"API: {r[1]}"
    try:
        obs = r.json().get("observations", [])
        if not obs:
            return None, "API sin observaciones"
        s = pd.Series(
            [pd.to_numeric(o["value"], errors="coerce") for o in obs],
            index=pd.to_datetime([o["date"] for o in obs]),
        ).dropna()
        if s.empty:
            return None, "serie vacía"
        s.name = series_id
        return s, None
    except Exception as exc:  # noqa: BLE001
        return None, f"API parseo: {exc}"


def _fred_csv(series_id: str):
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={START}"
    r = http_get(url)
    if isinstance(r, tuple):
        return None, f"CSV: {r[1]}"
    try:
        df = pd.read_csv(io.StringIO(r.text))
        if df.shape[1] < 2:
            return None, "CSV sin columna de valores"
        s = pd.to_numeric(df[df.columns[1]], errors="coerce")
        s.index = pd.to_datetime(df[df.columns[0]])
        s = s.dropna()
        if s.empty:
            return None, "serie vacía"
        s.name = series_id
        return s, None
    except Exception as exc:  # noqa: BLE001
        return None, f"CSV parseo: {exc}"


def fred_series(series_id: str):
    """API oficial si hay clave; CSV público como respaldo.
    Un 400 de la API significa que la serie no existe: insistir por CSV solo
    gasta minutos de reloj, así que se corta ahí."""
    if FRED_API_KEY:
        s, err = _fred_api(series_id)
        if s is not None:
            return s, None
        if "HTTP 400" in err:
            return None, f"{err} (la serie no existe en FRED)"
        s2, err2 = _fred_csv(series_id)
        return (s2, None) if s2 is not None else (None, f"{err} | {err2}")
    return _fred_csv(series_id)


def to_monthly(s: pd.Series, how: str = "mean") -> pd.Series:
    if s.empty:
        return s
    inferred = pd.infer_freq(s.index[:25]) if len(s) > 25 else None
    if inferred is not None and inferred.upper().startswith(("M", "Q")):
        out = s.resample("ME").last()
    else:
        out = s.resample("ME").last() if how == "last" else s.resample("ME").mean()
    out = out.dropna()
    out.index = out.index.to_period("M").to_timestamp("M")
    return out


def fetch_macro():
    print(f"1. Descargando FRED… ({'API oficial con clave' if FRED_API_KEY else 'CSV público, sin clave'})")
    raw, meta = {}, {}
    for sid in [s.fred_id for s in SERIES if s.fred_id not in DERIVED] + FRED_EXTRA:
        s, err = fred_series(sid)
        if s is None:
            warn(f"FRED {sid}: {err}")
            continue
        raw[sid] = to_monthly(s)
        meta[sid] = {"last_obs": str(s.index[-1].date())}
        print(f"  ✓ {sid:<22} {len(s):>6} obs  hasta {s.index[-1].date()}")
    if len(raw) < 12:
        raise SystemExit("Datos insuficientes de FRED; abortando.")
    df = pd.DataFrame(raw)
    df.index = df.index.to_period("M").to_timestamp("M")
    if "BAA" in df.columns and "AAA" in df.columns:
        df["BAA_AAA"] = df["BAA"] - df["AAA"]
        meta["BAA_AAA"] = {"last_obs": meta.get("BAA", {}).get("last_obs")}
        print("  ✓ BAA_AAA               derivada de BAA - AAA")
    return df, meta


# ======================================================================================
# 3. Transformaciones, z-scores, factores
# ======================================================================================

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
    if kind == "d12":
        return s - s.shift(12)
    if kind == "d3":
        return s - s.shift(3)
    raise ValueError(kind)


# Ventana de referencia para estandarizar, en meses. El reloj mide posición
# CÍCLICA, no nivel absoluto: la pregunta es "¿alto o bajo respecto a lo que ha
# sido normal últimamente?", no "¿respecto a la media desde 1959?". Con media
# expansiva, el pico inflacionista de los setenta se queda dentro de la referencia
# para siempre y el resultado es que de 1990 a 2020 la inflación aparece
# permanentemente por debajo de lo normal: en los años noventa y en la década de
# 2010 no hay ni un solo mes de Sobrecalentamiento ni de Estanflación. El reloj se
# pasó veinte años usando dos de sus cuatro cuadrantes.
# 120 meses es la elección: cubre un ciclo económico completo y no arrastra un
# cambio de régimen de cuarenta años. Es un parámetro, y como tal se declara.
Z_WINDOW_M = int(os.environ.get("Z_WINDOW_M", "120"))


def expanding_z(s: pd.Series, min_periods: int = 120) -> pd.Series:
    """Z-score móvil y causal sobre Z_WINDOW_M meses. Mientras no hay historia
    suficiente se comporta como una ventana expansiva. Ventana adaptativa: una
    serie corta no debe quedarse fuera en silencio, se le exige un tercio de su
    historia con un suelo de 48 meses."""
    n = int(s.notna().sum())
    mp = min(min_periods, max(48, n // 3))
    mu = s.rolling(Z_WINDOW_M, min_periods=mp).mean()
    sd = s.rolling(Z_WINDOW_M, min_periods=mp).std()
    return ((s - mu) / sd).clip(-4, 4)


def build_blocks(df: pd.DataFrame):
    print("2. Transformando y estandarizando…")
    zs, info = {}, {}
    for spec in SERIES:
        if spec.fred_id not in df.columns:
            warn(f"serie ausente del panel: {spec.fred_id} ({spec.name})")
            continue
        x = transform(df[spec.fred_id], spec.transform)
        if spec.invert:
            x = -x
        z = expanding_z(x).shift(spec.lag_m)
        if z.dropna().empty:
            warn(f"{spec.fred_id}: sin z-score utilizable "
                 f"({int(x.notna().sum())} observaciones tras transformar)")
            continue
        zs[spec.fred_id] = z
        info[spec.fred_id] = {
            "id": spec.fred_id, "name": spec.name, "block": spec.block,
            "transform": spec.transform, "lag_m": spec.lag_m,
            "invert": spec.invert, "note": spec.note,
            "obs": int(x.notna().sum()),
        }
    return pd.DataFrame(zs), info


def first_pc(Z: pd.DataFrame):
    """Primer componente principal. El signo se ancla por correlación con la media
    del bloque: todas las series entran ya orientadas en el mismo sentido, así que
    el factor debe co-moverse con su promedio simple. Anclar a una serie concreta
    falla cuando esa serie tiene carga casi nula."""
    X = Z.dropna(how="all")
    core = X.dropna(thresh=max(3, int(X.shape[1] * 0.6)))
    filled = core.apply(lambda c: c.fillna(c.mean()), axis=0)
    C = np.nan_to_num(np.corrcoef(filled.values, rowvar=False), nan=0.0)
    vals, vecs = np.linalg.eigh(C)
    order = np.argsort(vals)[::-1]
    vals, vecs = vals[order], vecs[:, order]
    W = pd.Series(vecs[:, 0], index=list(X.columns))
    explained = float(vals[0] / vals.sum())

    num = X.mul(W, axis=1).sum(axis=1, min_count=1)
    den = X.notna().mul(W.abs(), axis=1).sum(axis=1)
    f = (num / den.replace(0, np.nan)).dropna()

    simple = X.mean(axis=1).reindex(f.index)
    coh = f.corr(simple)
    if coh < 0:
        f, W, coh = -f, -W, -coh
    f = f / f.std()
    return f, {
        "explained_var": round(explained, 3),
        "loadings": {c: round(float(v), 3) for c, v in W.items()},
        "coherence": round(float(coh), 3),
    }


def build_factors(Z: pd.DataFrame):
    print("3. Extrayendo factores (PCA)…")
    out, diag = {}, {}
    for block in ("growth", "inflation", "leading"):
        cols = [s.fred_id for s in SERIES if s.block == block and s.fred_id in Z.columns]
        if len(cols) < 2:
            warn(f"bloque {block} con muy pocas series")
            continue
        f, d = first_pc(Z[cols])
        out[block], diag[block] = f, d
        print(f"  ✓ {block:<10} {len(cols)} series · varianza {d['explained_var']:.0%}"
              f" · coherencia {d['coherence']:+.2f}")
        if d["explained_var"] < 0.40:
            warn(f"bloque {block}: el primer componente solo explica "
                 f"{d['explained_var']:.0%} de la varianza")
    return pd.DataFrame(out).dropna(how="all"), diag


# ======================================================================================
# 4. Fase, probabilidades y recesión
# ======================================================================================

def classify(g: float, i: float) -> str:
    if g >= 0:
        return "Sobrecalentamiento" if i >= 0 else "Recuperación"
    return "Estanflación" if i >= 0 else "Reflación"


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def phase_probs(g, i, sg, si):
    pg, pi = norm_cdf(g / sg), norm_cdf(i / si)
    return {"Recuperación": pg * (1 - pi), "Sobrecalentamiento": pg * pi,
            "Estanflación": (1 - pg) * pi, "Reflación": (1 - pg) * (1 - pi)}


def fit_logit(X, y, iters: int = 80):
    X = np.column_stack([np.ones(len(X)), X])
    beta = np.zeros(X.shape[1])
    for _ in range(iters):
        eta = np.clip(X @ beta, -30, 30)
        p = 1 / (1 + np.exp(-eta))
        W = np.clip(p * (1 - p), 1e-6, None)
        z = eta + (y - p) / W
        A = X.T @ (X * W[:, None]) + 1e-4 * np.eye(X.shape[1])
        new = np.linalg.solve(A, X.T @ (W * z))
        if np.max(np.abs(new - beta)) < 1e-9:
            return new
        beta = new
    return beta


def recession_model(df: pd.DataFrame, idx) -> dict:
    if "USREC" not in df.columns or "T10Y3M" not in df.columns:
        return {}
    rec = df["USREC"].reindex(idx).fillna(0)
    fwd = rec[::-1].rolling(12, min_periods=1).max()[::-1].shift(-1)
    feats = ["T10Y3M"] + (["NFCI"] if "NFCI" in df.columns else [])
    data = pd.concat([df[feats].reindex(idx), fwd.rename("y")], axis=1).dropna()
    if len(data) < 200:
        return {}
    beta = fit_logit(data[feats].values, data["y"].values)
    last = df[feats].dropna().iloc[-1].values
    p = 1 / (1 + math.exp(-max(min(beta[0] + float(np.dot(beta[1:], last)), 30), -30)))
    ph = 1 / (1 + np.exp(-np.clip(beta[0] + data[feats].values @ beta[1:], -30, 30)))
    y = data["y"].values
    auc = float("nan")
    if 0 < y.sum() < len(y):
        ranks = np.empty(len(ph))
        ranks[np.argsort(ph)] = np.arange(1, len(ph) + 1)
        n1, n0 = y.sum(), (1 - y).sum()
        auc = float((ranks[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))
    return {"prob_12m": round(p, 4), "auc": round(auc, 3) if auc == auc else None,
            "features": feats, "coef": [round(float(b), 4) for b in beta],
            "n_obs": int(len(data))}


# ======================================================================================
# 5. Universo de activos
# ======================================================================================

FRENCH_BASE = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
FRENCH_IND = {
    "NoDur": "Consumo básico", "Durbl": "Consumo duradero", "Manuf": "Industria",
    "Enrgy": "Energía", "Chems": "Materiales / Químicas", "BusEq": "Tecnología",
    "Telcm": "Comunicaciones", "Utils": "Utilities", "Shops": "Consumo discrecional",
    "Hlth": "Salud", "Money": "Financiero", "Other": "Otros sectores",
}

FRENCH_49 = {
    "Gold": ("Metales preciosos (mineras)", "Real / alternativos",
             "mineras de oro, no lingote: el oro físico ya no está en FRED"),
    "Mines": ("Minería no férrea", "Real / alternativos", ""),
    "RlEst": ("Inmobiliario", "Real / alternativos",
              "sector inmobiliario cotizado; sustituye al índice Wilshire retirado"),
    "Oil": ("Petróleo y gas", "Real / alternativos", ""),
    "Banks": ("Bancos", "Renta variable", ""),
    "Softw": ("Software", "Renta variable", ""),
    "Chips": ("Semiconductores", "Renta variable", ""),
}

# ICE truncó a 3 años TODOS sus índices de retorno total en FRED en abril de 2026,
# incluidos los subconjuntos por rating. El crédito se cubre con los rendimientos de
# Moody's (duración, desde 1919) y con ETF reales vía Yahoo para el tramo moderno.
FRED_TR: dict[str, tuple[str, list[str]]] = {}

FRED_PX = {
    "Petróleo WTI (spot)": ("Real / alternativos", ["WTISPLC", "MCOILWTICO"],
                            "spot mensual desde 1946"),
    "Cesta de producción (PPI)": ("Real / alternativos", ["PPIACO"],
                                  "proxy de precios, no invertible directamente"),
}

FRED_YIELD = {
    "MORTGAGE30US": (5.5, 40.0, "Hipotecario 30 años (aprox.)", "Renta fija"),
    "DGS2": (1.9, 4.5, "Treasury 2 años", "Renta fija"),
    "DGS10": (8.2, 80.0, "Treasury 10 años", "Renta fija"),
    "DGS30": (18.5, 450.0, "Treasury 30 años", "Renta fija"),
    "BAA": (7.5, 70.0, "Crédito Baa (aprox.)", "Renta fija"),
    "AAA": (8.0, 80.0, "Crédito Aaa (aprox.)", "Renta fija"),
    "DFII10": (8.5, 85.0, "TIPS 10 años (aprox.)", "Renta fija"),
}

# Fuentes de mercado. Yahoo primero (los runners de GitHub llegan bien), Stooq de
# respaldo. Cada entrada: etiqueta -> (clase, símbolo Yahoo, ticker Stooq, nota).
MARKET = {
    "Oro (lingote)": ("Real / alternativos", "GC=F", "xauusd",
                      "futuro continuo de oro; el histórico largo lo cubren las mineras"),
    "Oro (ETF físico)": ("Real / alternativos", "GLD", "gld.us", "respaldado por lingote"),
    "Plata": ("Real / alternativos", "SI=F", "xagusd", ""),
    "Materias primas (índice)": ("Real / alternativos", "^SPGSCI", "^spgsci", "GSCI"),
    "Materias primas (ETF)": ("Real / alternativos", "DBC", "dbc.us", ""),
    "Cobre": ("Real / alternativos", "HG=F", "hg.f", ""),
    "REITs": ("Real / alternativos", "VNQ", "vnq.us", ""),
    "Crédito Investment Grade (LQD)": ("Renta fija", "LQD", "lqd.us",
                                       "retorno total real, desde 2002"),
    "Crédito High Yield (HYG)": ("Renta fija", "HYG", "hyg.us",
                                 "retorno total real, desde 2007"),
    "Deuda emergente (EMB)": ("Renta fija", "EMB", "emb.us", ""),
    "TIPS (TIP)": ("Renta fija", "TIP", "tip.us", ""),
    "Municipales (MUB)": ("Renta fija", "MUB", "mub.us", ""),
    "Titulizaciones hipotecarias (MBB)": ("Renta fija", "MBB", "mbb.us", ""),
    "Renta variable emergente": ("Renta variable", "EEM", "eem.us", ""),
    "Renta variable internacional": ("Renta variable", "EFA", "efa.us", ""),
    "Small caps": ("Estilo", "IWM", "iwm.us", ""),
}

# Carteras internacionales de Ken French: misma fuente que ya funciona, historia
# desde 1990, sin depender de proveedores que bloquean servidores.
FRENCH_INTL = {
    "Desarrollados ex EE.UU. (French)": ("Renta variable",
                                         "Developed_ex_US_3_Factors_CSV.zip"),
    "Emergentes (French)": ("Renta variable", "Emerging_5_Factors_CSV.zip"),
}


def yahoo_monthly(symbol: str):
    """Serie mensual de retornos desde el endpoint de gráficos de Yahoo.
    Se prueban los dos hosts porque uno de ellos limita por IP con frecuencia."""
    last = "sin respuesta"
    for host in ("query1", "query2"):
        url = (f"https://{host}.finance.yahoo.com/v8/finance/chart/{symbol}"
               "?range=max&interval=1mo")
        r = http_get(url, tries=1, timeout=OPTIONAL_TIMEOUT)
        if isinstance(r, tuple):
            last = r[1]
            continue
        try:
            res = r.json()["chart"]["result"][0]
            ts = res["timestamp"]
            ind = res["indicators"]
            vals = None
            if "adjclose" in ind and ind["adjclose"]:
                vals = ind["adjclose"][0].get("adjclose")
            if not vals:
                vals = ind["quote"][0].get("close")
            px = pd.Series(vals, index=pd.to_datetime(ts, unit="s")).dropna()
            px.index = px.index.to_period("M").to_timestamp("M")
            px = px[~px.index.duplicated(keep="last")]
            if px.size < MIN_MONTHS + 1:
                last = f"solo {px.size} meses"
                continue
            return px.pct_change().dropna() * 100.0, None
        except Exception as exc:  # noqa: BLE001
            last = f"parseo: {exc}"
    return None, last


def french_zip(url: str, tag: str):
    r = http_get(url)
    if isinstance(r, tuple):
        return None, r[1]
    try:
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        lines = zf.read(zf.namelist()[0]).decode("latin-1").splitlines()
        start = None
        for idx, line in enumerate(lines):
            tok = line.strip().split(",")[0].strip()
            if len(tok) == 6 and tok.isdigit():
                start = idx
                break
        if start is None:
            return None, "no se encontró la tabla mensual"
        h = start - 1
        while h > 0 and not lines[h].strip():
            h -= 1
        rows = []
        for line in lines[start:]:
            tok = line.strip().split(",")[0].strip()
            if not (len(tok) == 6 and tok.isdigit()):
                break
            rows.append(line)
        header = [c.strip() for c in lines[h].split(",")]
        if not header[0]:
            header[0] = "date"
        d = pd.read_csv(io.StringIO(",".join(header) + "\n" + "\n".join(rows)))
        d["date"] = pd.to_datetime(d["date"].astype(int).astype(str), format="%Y%m")
        d = d.set_index("date").apply(pd.to_numeric, errors="coerce")
        d.index = d.index.to_period("M").to_timestamp("M")
        return d.replace([-99.99, -999], np.nan), None
    except Exception as exc:  # noqa: BLE001
        return None, f"{tag}: {exc}"


def stooq_monthly(ticker: str):
    """Stooq devuelve 200 con un mensaje de error al superar el límite diario:
    de ahí la comprobación del cuerpo. Se intenta la serie diaria como respaldo."""
    last = "sin respuesta"
    for interval, needs_resample in (("m", False), ("d", True)):
        r = http_get(f"https://stooq.com/q/d/l/?s={ticker}&i={interval}",
                     tries=1, expect="Date", timeout=OPTIONAL_TIMEOUT)
        if isinstance(r, tuple):
            last = r[1]
            continue
        try:
            d = pd.read_csv(io.StringIO(r.text))
            s = d.set_index(pd.to_datetime(d["Date"]))["Close"].astype(float)
            if needs_resample:
                s = s.resample("ME").last()
            s.index = s.index.to_period("M").to_timestamp("M")
            s = s.dropna()
            if s.size < MIN_MONTHS + 1:
                last = f"solo {s.size} meses"
                continue
            return s.pct_change().dropna() * 100.0, None
        except Exception as exc:  # noqa: BLE001
            last = str(exc)
    return None, last


def yield_to_return(y_pct: pd.Series, dur: float, cvx: float) -> pd.Series:
    y = y_pct.dropna() / 100.0
    dy = y.diff()
    return ((y.shift(1) / 12.0 - dur * dy + 0.5 * cvx * dy ** 2) * 100.0).dropna()


def fetch_assets(df: pd.DataFrame):
    print("4. Construyendo el universo de activos…")
    rets: dict[str, pd.Series] = {}
    meta: dict[str, dict] = {}

    def add(name, series, cls, source, note="", err=None):
        if err is not None or series is None:
            ASSET_LOG.append({"name": name, "source": source, "status": "fallo",
                              "detail": err or "sin datos"})
            return
        s = series.dropna()
        s = s[np.isfinite(s.values)]
        if s.size < MIN_MONTHS:
            ASSET_LOG.append({"name": name, "source": source, "status": "descartado",
                              "detail": f"{s.size} meses, mínimo {MIN_MONTHS}"})
            return
        if name in rets:
            ASSET_LOG.append({"name": name, "source": source, "status": "duplicado",
                              "detail": "ya cargado desde otra fuente"})
            return
        rets[name] = s
        meta[name] = {"class": cls, "source": source, "note": note,
                      "from": str(s.index[0].date()), "to": str(s.index[-1].date())}
        ASSET_LOG.append({"name": name, "source": source, "status": "ok",
                          "detail": f"{s.size} meses desde {s.index[0].date()}"})

    ff, err = french_zip(FRENCH_BASE + "F-F_Research_Data_Factors_CSV.zip", "factores")
    rf = None
    if ff is not None and "RF" in ff.columns:
        rf = ff["RF"]
        add("Renta variable EE.UU. (mercado)", ff["Mkt-RF"] + rf, "Renta variable",
            "Ken French")
        add("Prima Value (HML)", ff["HML"], "Prima (largo-corto)", "Ken French",
            "no invertible en una cartera solo larga: queda fuera de la asignación")
        add("Prima Tamaño (SMB)", ff["SMB"], "Prima (largo-corto)", "Ken French",
            "no invertible en una cartera solo larga: queda fuera de la asignación")
    else:
        warn(f"Ken French factores: {err}")

    ind, err = french_zip(FRENCH_BASE + "12_Industry_Portfolios_CSV.zip", "industrias")
    if ind is not None:
        for col, lab in FRENCH_IND.items():
            if col in ind.columns:
                add(lab, ind[col], "Renta variable", "Ken French")
    else:
        warn(f"Ken French industrias: {err}")

    ind49, err = french_zip(FRENCH_BASE + "49_Industry_Portfolios_CSV.zip", "49 industrias")
    if ind49 is not None:
        for col, (lab, cls, note) in FRENCH_49.items():
            if col in ind49.columns:
                add(lab, ind49[col], cls, "Ken French (49 industrias)", note)
            else:
                add(lab, None, cls, "Ken French (49 industrias)", note,
                    err=f"columna {col} ausente")
    else:
        warn(f"Ken French 49 industrias: {err}")

    mom, err = french_zip(FRENCH_BASE + "F-F_Momentum_Factor_CSV.zip", "momentum")
    if mom is not None:
        c = [x for x in mom.columns if "Mom" in x]
        if c:
            add("Prima Momentum", mom[c[0]], "Prima (largo-corto)", "Ken French",
                "no invertible en una cartera solo larga: queda fuera de la asignación")

    def first_usable(candidates, label, cls, prefix, note=""):
        """Prueba los IDs en orden y se queda con el primero que traiga historia."""
        errs = []
        for sid in candidates:
            raw, e = fred_series(sid)
            if raw is None:
                errs.append(f"{sid}: {e}")
                continue
            r = to_monthly(raw, how="last").pct_change() * 100.0
            if r.dropna().size >= MIN_MONTHS:
                add(label, r, cls, f"{prefix} / {sid}", note)
                return
            errs.append(f"{sid}: solo {r.dropna().size} meses")
        add(label, None, cls, f"{prefix} / {candidates[0]}", note,
            err=" · ".join(errs)[:200])

    for lab, (cls, cands) in FRED_TR.items():
        first_usable(cands, lab, cls, "ICE BofA")

    for lab, (cls, cands, note) in FRED_PX.items():
        first_usable(cands, lab, cls, "FRED", note)

    for sid, (dur, cvx, lab, cls) in FRED_YIELD.items():
        if sid not in df.columns:
            add(lab, None, cls, f"FRED / {sid}", err="no descargado")
        else:
            add(lab, yield_to_return(df[sid], dur, cvx), cls, f"FRED / {sid}",
                f"aproximación por duración {dur} y convexidad {cvx}")

    if "TB3MS" in df.columns:
        add("Liquidez (letras 3m)", (df["TB3MS"] / 12.0).dropna(), "Liquidez",
            "FRED / TB3MS")

    # Carteras internacionales de French (fuente fiable, historia desde 1990)
    for lab, (cls, fname) in FRENCH_INTL.items():
        d, e = french_zip(FRENCH_BASE + fname, lab)
        if d is None:
            add(lab, None, cls, "Ken French (internacional)", err=e)
            continue
        cols = [c for c in d.columns if "Mkt" in c]
        rfc = [c for c in d.columns if c.strip() == "RF"]
        if not cols:
            add(lab, None, cls, "Ken French (internacional)", err="sin columna de mercado")
            continue
        serie = d[cols[0]] + (d[rfc[0]] if rfc else 0)
        add(lab, serie, cls, "Ken French (internacional)")

    # Fuentes de mercado: Yahoo primero, Stooq de respaldo
    t_opt = time.time()
    for lab, (cls, ysym, stick, note) in MARKET.items():
        if time.time() - t_opt > OPTIONAL_BUDGET_S:
            add(lab, None, cls, "mercado", note,
                err="omitido: presupuesto de tiempo agotado")
            continue
        r, e1 = yahoo_monthly(ysym)
        if r is not None:
            add(lab, r, cls, f"Yahoo / {ysym}", note)
            continue
        r2, e2 = stooq_monthly(stick)
        if r2 is not None:
            add(lab, r2, cls, f"Stooq / {stick}", note)
        else:
            add(lab, None, cls, f"Yahoo {ysym} · Stooq {stick}", note,
                err=f"yahoo: {e1} | stooq: {e2}"[:200])

    R = pd.DataFrame(rets)
    if rf is None:
        rf = (df["TB3MS"] / 12.0) if "TB3MS" in df.columns else pd.Series(0.0, index=R.index)
    rf = rf.reindex(R.index).ffill().fillna(0.0)
    X = R.sub(rf, axis=0)

    ok = sum(1 for a in ASSET_LOG if a["status"] == "ok")
    print(f"  ✓ {ok} activos cargados, {len(ASSET_LOG) - ok} descartados o fallidos")
    for a in ASSET_LOG:
        if a["status"] != "ok":
            print(f"    – {a['name']}: {a['status']} ({a['detail']})")
    return X, meta


# ======================================================================================
# 6. Estadística condicional
# ======================================================================================

def newey_west(x: np.ndarray, lags: int = 3):
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 12:
        return float("nan"), float("nan"), float("nan")
    mu = x.mean()
    e = x - mu
    var = (e @ e) / n
    for l in range(1, min(lags, n - 1) + 1):
        var += 2 * (1 - l / (lags + 1)) * ((e[l:] @ e[:-l]) / n)
    se = math.sqrt(max(var, 1e-12) / n)
    return mu, se, mu / se


def benjamini_hochberg(p: list[float]) -> list[float]:
    arr = np.array(p, dtype=float)
    q = np.full_like(arr, np.nan)
    idx = np.where(np.isfinite(arr))[0]
    if idx.size == 0:
        return q.tolist()
    order = idx[np.argsort(arr[idx])]
    m, prev = len(order), 1.0
    for rank in range(m - 1, -1, -1):
        i = order[rank]
        prev = min(prev, arr[i] * m / (rank + 1))
        q[i] = min(prev, 1.0)
    return q.tolist()


def two_sided_p(t: float) -> float:
    return float("nan") if t != t else 2 * (1 - norm_cdf(abs(t)))


def grade_from_t(t: float, q: float) -> str:
    if t != t:
        return "s/d"
    a, sign = abs(t), ("+" if t > 0 else "-")
    if a >= 2.58 and (q != q or q <= 0.10):
        return sign * 3
    if a >= 1.96:
        return sign * 2
    if a >= 1.28:
        return sign * 1
    return "0"


def shrink(mu: dict, se: dict, grand: float) -> dict:
    """Contracción empírica de Bayes. Las medias por fase se estiman con pocas
    observaciones y son ruidosas: contraerlas hacia la media del propio activo
    mejora la predicción fuera de muestra. Si la dispersión entre fases no supera
    al ruido de estimación, la contracción es total y las fases se igualan."""
    keys = [p for p in PHASES if p in mu]
    if len(keys) < 2:
        return {p: mu.get(p) for p in PHASES}
    ms = np.array([mu[p] for p in keys])
    vs = np.array([se[p] ** 2 for p in keys])
    tau2 = max(0.0, float(ms.var(ddof=1) - vs.mean()))
    out = {}
    for p in PHASES:
        if p not in mu:
            out[p] = None
            continue
        d = tau2 + se[p] ** 2
        w = tau2 / d if d > 0 else 0.0
        out[p] = grand + w * (mu[p] - grand)
    return out


def conditional_stats(X: pd.DataFrame, phases: pd.Series, meta: dict):
    print("5. Estimando retornos condicionales…")
    rows, cells = [], []
    for col in X.columns:
        s = X[col].dropna()
        ph = phases.reindex(s.index).dropna()
        s = s.reindex(ph.index)
        if s.size < MIN_MONTHS:
            continue
        grand, _, _ = newey_west(s.values)
        entry = {
            "id": col, "name": col,
            "class": meta.get(col, {}).get("class", "Otros"),
            "source": meta.get(col, {}).get("source", ""),
            "note": meta.get(col, {}).get("note", ""),
            "from": str(s.index[0].date()), "to": str(s.index[-1].date()),
            "n": int(s.size), "uncond_ann": round(float(grand * 12), 2),
            "phases": {},
        }
        mu_d, se_d = {}, {}
        for phase in PHASES:
            sub = s[ph == phase]
            if sub.size < 12:
                entry["phases"][phase] = {"n": int(sub.size), "grade": "s/d"}
                continue
            mu, se, _ = newey_west(sub.values)
            _, _, t = newey_west(sub.values - grand)
            mu_d[phase], se_d[phase] = mu, se
            entry["phases"][phase] = {
                "ann": round(float(mu * 12), 2),
                "rel": round(float((mu - grand) * 12), 2),
                "t": round(float(t), 2) if t == t else None,
                "hit": round(float((sub.values > 0).mean()), 3),
                "n": int(sub.size),
                "vol": round(float(sub.std() * math.sqrt(12)), 2),
            }
            cells.append((col, phase, two_sided_p(t)))
        sh = shrink(mu_d, se_d, grand)
        for phase in PHASES:
            if sh.get(phase) is not None and "ann" in entry["phases"][phase]:
                entry["phases"][phase]["rel_shrunk"] = round(
                    float((sh[phase] - grand) * 12), 2)
        rows.append(entry)

    qs = benjamini_hochberg([c[2] for c in cells])
    qmap = {(c[0], c[1]): q for c, q in zip(cells, qs)}
    for e in rows:
        for phase, d in e["phases"].items():
            if d.get("t") is None:
                d.setdefault("grade", "s/d")
                continue
            q = qmap.get((e["id"], phase), float("nan"))
            d["q"] = round(q, 3) if q == q else None
            d["grade"] = grade_from_t(d["t"], q)

    graded = sum(1 for e in rows for d in e["phases"].values()
                 if d.get("grade") not in (None, "0", "s/d"))
    fdr = sum(1 for e in rows for d in e["phases"].values()
              if d.get("q") is not None and d["q"] <= 0.10)
    print(f"  ✓ {len(rows)} activos · {len(cells)} casillas · {graded} con nota · "
          f"{fdr} robustas al control de falsos descubrimientos")
    return rows, {"cells": len(cells), "graded": graded, "fdr_survivors": fdr}


# ======================================================================================
# 7. Backtest
# ======================================================================================

def perf(series: pd.Series) -> dict:
    s = series.dropna() / 100.0
    if s.size < 24:
        return {}
    curve = (1 + s).cumprod()
    cagr = curve.iloc[-1] ** (12 / s.size) - 1
    vol = s.std() * math.sqrt(12)
    _, _, t = newey_west(s.values * 100)
    roll12 = (1 + s).rolling(12).apply(np.prod, raw=True) - 1
    return {"cagr": round(float(cagr * 100), 2), "vol": round(float(vol * 100), 2),
            "sharpe": round(float(cagr / vol), 2) if vol > 0 else None,
            "maxdd": round(float((curve / curve.cummax() - 1).min() * 100), 2),
            "worst12": round(float(roll12.min() * 100), 2) if roll12.notna().any() else None,
            "hit": round(float((s > 0).mean()), 3),
            "t": round(float(t), 2) if t == t else None,
            "months": int(s.size), "from": str(s.index[0].date())}


def backtest(X: pd.DataFrame, phases: pd.Series, top_k: int = 5, min_train: int = 240):
    """Walk-forward estricto. Tres carteras:
      larga    — top-k por media contraída de la fase vigente
      spread   — larga menos la peor k: aísla la señal, sin beta de mercado
      escalada — la larga con la volatilidad igualada a la del 60/40
    Más la larga estimada con la muestra completa, para medir el sobreajuste."""
    print("6. Backtest walk-forward…")
    common = X.dropna(how="all").index.intersection(phases.dropna().index)
    X = X.loc[common]
    ph = phases.loc[common]
    X = X[X.columns[X.notna().mean() > 0.6]]
    if X.shape[1] < 2 * top_k or len(common) < min_train + 60:
        warn("histórico insuficiente para el backtest")
        return {}

    def means(hist, hp, phase):
        sub = hist[hp == phase]
        if sub.empty:
            return pd.Series(dtype=float)
        grand = hist.mean()
        mu = sub.mean()
        se = sub.std() / np.sqrt(sub.notna().sum().clip(lower=1))
        tau2 = (mu - grand).var()
        w = (tau2 / (tau2 + se ** 2)).fillna(0.0)
        return grand + w * (mu - grand)

    def inv_vol_weights(hist, names):
        """Pesos por inverso de la volatilidad. Es un criterio a priori, no ajustado
        a los datos: evita que la cartera sea de facto una apuesta apalancada a
        renta variable solo porque es lo más volátil del universo."""
        v = hist[list(names)].std()
        v = v.replace(0, np.nan).dropna()
        if v.empty:
            return pd.Series(1.0 / len(names), index=list(names))
        w = 1.0 / v
        return w / w.sum()

    lg, sp, ins, tl, dates = [], [], [], [], []
    full = {p: means(X, ph, p) for p in PHASES}
    eq_col = "Renta variable EE.UU. (mercado)"
    bd_col = "Treasury 10 años"

    for k in range(min_train, len(common)):
        t = common[k]
        sig = ph.iloc[k - 1]
        hist, hph = X.iloc[:k], ph.iloc[:k]
        mu = means(hist, hph, sig)
        avail = X.loc[t].dropna().index
        # Ordenar por media contraída dividida por volatilidad, no por media bruta.
        # Con media bruta el ranking lo copan siempre los activos más volátiles y
        # la cartera acaba siendo una apuesta apalancada disfrazada de rotación.
        vol_h = hist.std().replace(0, np.nan)
        score = (mu / vol_h).replace([np.inf, -np.inf], np.nan)
        rank = score.reindex(avail).dropna().sort_values(ascending=False)
        if rank.size < 2 * top_k:
            continue
        top, bot = rank.head(top_k).index, rank.tail(top_k).index
        wt = inv_vol_weights(hist, top)
        lg.append(float((X.loc[t, top] * wt).sum()))
        sp.append(float(X.loc[t, top].mean() - X.loc[t, bot].mean()))
        rk = full[sig].reindex(avail).dropna().sort_values(ascending=False)
        wi = inv_vol_weights(hist, rk.head(top_k).index)
        ins.append(float((X.loc[t, rk.head(top_k).index] * wi).sum()))

        # Inclinación realista: 60/40 de base, ±20 puntos hacia lo mejor de la fase
        if eq_col in avail and bd_col in avail:
            base = 0.6 * float(X.loc[t, eq_col]) + 0.4 * float(X.loc[t, bd_col])
            tilt = float((X.loc[t, top] * wt).sum())
            tl.append(0.8 * base + 0.2 * tilt)
        else:
            tl.append(float("nan"))
        dates.append(t)

    L = pd.Series(lg, index=dates)
    S = pd.Series(sp, index=dates)
    I = pd.Series(ins, index=dates)
    T = pd.Series(tl, index=dates).dropna()
    eq = X.get(eq_col)
    bd = X.get(bd_col)
    bench = (0.6 * eq + 0.4 * bd).reindex(dates) if eq is not None and bd is not None else None
    scaled = L * float(bench.std() / L.std()) if bench is not None and L.std() > 0 else None

    curve = [{"d": d.strftime("%Y-%m"), "s": round(float(L.loc[d]), 4),
              "p": round(float(S.loc[d]), 4),
              "b": (round(float(bench.loc[d]), 4)
                    if bench is not None and d in bench.index
                    and bench.loc[d] == bench.loc[d] else None)} for d in dates]

    print(f"  ✓ {len(L)} meses fuera de muestra desde {dates[0].date()}")
    return {"long": perf(L), "spread": perf(S), "tilt": perf(T),
            "scaled": perf(scaled) if scaled is not None else {},
            "in_sample": perf(I),
            "bench_6040": perf(bench) if bench is not None else {},
            "equal_weight": perf(X.reindex(dates).mean(axis=1)),
            "top_k": top_k, "curve": curve[-460:]}


def defensive(X: pd.DataFrame, growth: pd.Series) -> dict:
    """Superposición defensiva sobre un 60/40.

    Tres reglas fijadas ANTES de mirar el resultado, todas con el mismo disparador:
    el signo del eje de crecimiento del mes anterior, que es información disponible
    en tiempo real porque los z-scores ya llevan aplicado el retraso de publicación.
    No hay ningún umbral ajustado: el umbral es cero, que por construcción significa
    "crecimiento en tendencia".

    Se prueban tres variantes. Elegir la mejor de tres infla el Sharpe, así que se
    publican las tres y el número de variantes probadas.
    """
    need = ["Renta variable EE.UU. (mercado)", "Treasury 10 años", "Treasury 2 años"]
    if any(c not in X.columns for c in need):
        return {}
    gold = next((c for c in ("Metales preciosos (mineras)", "Oro (lingote)",
                             "Oro (ETF físico)") if c in X.columns), None)
    eq, b10, b2 = need
    # Todas las variantes tienen que cubrir los mismos meses que su propia base.
    # Los índices de Ken French publican con dos meses de desfase, así que sin este
    # recorte el 60/40 salía con 678 meses y las reglas defensivas con 680: dos
    # meses de ventaja gratis para las variantes, justo los más recientes.
    idx = X.index.intersection(growth.dropna().index)
    last = X[eq].dropna().index.max()
    if last is not None:
        idx = idx[idx <= last]
    sig = (growth.reindex(idx).shift(1) < 0)
    D = X.reindex(idx)

    def run(defensive_w):
        base = {eq: 0.6, b10: 0.4}
        out = []
        for t in idx:
            w = defensive_w if bool(sig.get(t, False)) else base
            cols = [c for c in w if c in D.columns and D.loc[t, c] == D.loc[t, c]]
            if not cols:
                out.append(np.nan)
                continue
            tot = sum(w[c] for c in cols)
            out.append(sum(w[c] / tot * float(D.loc[t, c]) for c in cols))
        return pd.Series(out, index=idx).dropna()

    variants = {
        "base_6040": None,
        "a_bonos": {eq: 0.30, b10: 0.70},
        "b_corto": {eq: 0.30, b2: 0.70},
    }
    if gold:
        variants["c_oro"] = {eq: 0.30, b10: 0.50, gold: 0.20}

    res = {}
    base_series = None
    for name, w in variants.items():
        if w is None:
            cols = [eq, b10]
            base_series = (0.6 * D[eq] + 0.4 * D[b10]).dropna()
            res[name] = perf(base_series)
        else:
            res[name] = perf(run(w))

    res["n_variants"] = len(variants) - 1
    res["months_defensive"] = int(sig.sum())
    res["share_defensive"] = round(float(sig.mean()), 3)
    res["trigger"] = "eje de crecimiento del mes anterior por debajo de cero"
    return res



# ======================================================================================
# 7b. Rotación por fase, solo largo y sin apalancar
# ======================================================================================

# Presupuesto fijo, idéntico en todas las fases: 60 % activos de riesgo, 30 % renta
# fija, 10 % activos reales. Lo que cambia con la fase es QUÉ hay dentro de cada
# bloque, no cuánto pesa. Así la comparación con el 60/40 es limpia: misma postura
# de riesgo, distinto contenido. Sin apalancamiento y sin posiciones cortas.
# Bandas de cada bloque. Los pesos NO son fijos: se mueven con la fase dentro de
# estas bandas, en proporción a lo bien que el bloque puntúa en esa fase. Siempre
# queda algo de renta variable y algo de renta fija; el oro y demás activos reales
# pueden quedarse a cero si no aportan.
SLEEVES = {
    "Renta variable": ({"Renta variable"}, 0.30, 0.70, 4),
    "Renta fija": ({"Renta fija"}, 0.20, 0.60, 3),
    "Activos reales": ({"Real / alternativos"}, 0.00, 0.15, 2),
}

# Postura neutra de la cartera: la misma que el índice de referencia. La fase
# desvía alrededor de este punto, no lo sustituye. Sin esto la comparación con el
# 60/40 no mide rotación, mide nivel de riesgo: una cartera estructuralmente al
# 40 % de renta variable pierde contra el 60/40 aunque acierte todas las fases.
NEUTRAL = {"Renta variable": 0.60, "Renta fija": 0.30, "Activos reales": 0.10}

# Desviación máxima respecto al neutro, en desviaciones típicas de la puntuación
# del bloque entre fases. Es el único parámetro de diseño y se fija por prudencia:
# una fase excepcional lleva el bloque al borde de su banda, no más allá.
MAX_Z = 1.0

# Historia mínima para poder entrar en cartera. Evita que un ETF con dos años de
# datos gane la selección por ruido.
MIN_HISTORY_M = 60

# Retraso máximo de publicación tolerado en el guion de cartera. Las carteras de
# Ken French salen con dos meses de desfase; sin esta tolerancia el guion solo veía
# los tickers de Yahoo y por eso el bloque de renta variable acababa siendo
# siempre "internacional + emergentes" en lugar de sectores.
LAG_TOLERANCE_M = 4

# No seleccionables. Dos motivos distintos:
#   - Índices agregados de mercado: sirven de referencia, no de posición. Si entran
#     copan el bloque de renta variable y no hay rotación sectorial ninguna.
#   - Series de precio no invertibles: no existe forma de mantener la posición.
NOT_SELECTABLE = {
    # agregados de renta variable
    "Renta variable EE.UU. (mercado)",
    "Renta variable EE.UU. (Wilshire)",
    "Renta variable internacional",
    "Renta variable emergente",
    "Desarrollados ex EE.UU. (French)",
    "Emergentes (French)",
    "Small caps",
    "Otros sectores",
    # no invertibles
    "Cesta de producción (PPI)",
    "Petróleo WTI (spot)",
}

# Exposiciones duplicadas: distintos vehículos sobre el mismo subyacente. Solo una
# de cada grupo puede entrar en cartera. Sin esto el bloque de activos reales se
# llenaba con oro lingote y oro ETF a la vez —15 % de oro disfrazado de
# diversificación— y lo mismo pasaba con GSCI/DBC y con el hipotecario.
# El representante se elige por historia disponible, antes de mirar retornos.
# --- Duplicados, dos tipos distintos ---------------------------------------
#
# VEHICLE_GROUPS: el mismo subyacente por vehículos distintos. Oro lingote y oro
# ETF son literalmente lo mismo. Se colapsan ANTES de puntuar y gana el de más
# historia, porque con datos idénticos el criterio es la calidad de la serie.
VEHICLE_GROUPS = {
    "Oro (lingote)": "oro lingote",
    "Oro (ETF físico)": "oro lingote",
    "Materias primas (índice)": "materias primas",
    "Materias primas (ETF)": "materias primas",
    "Hipotecario 30 años (aprox.)": "hipotecario",
    "Titulizaciones hipotecarias (MBB)": "hipotecario",
    "Crédito Baa (aprox.)": "crédito investment grade",
    "Crédito Investment Grade (LQD)": "crédito investment grade",
    "TIPS 10 años (aprox.)": "tips",
    "TIPS (TIP)": "tips",
    "Renta variable internacional": "desarrollados ex EE.UU.",
    "Desarrollados ex EE.UU. (French)": "desarrollados ex EE.UU.",
    "Renta variable emergente": "emergentes",
    "Emergentes (French)": "emergentes",
}

# OVERLAP_GROUPS: exposiciones distintas pero solapadas o anidadas. Bancos está
# DENTRO de Financiero; Software y Semiconductores están DENTRO de Tecnología.
# Comprar Financiero y Bancos a la vez no es diversificar, es la misma apuesta
# escrita dos veces, y en un bloque de cuatro nombres se lleva media cartera de
# renta variable. Aquí no se puede colapsar por historia —las series de Ken
# French empiezan todas en 1970 y el desempate sería alfabético, o sea
# arbitrario—, así que la restricción se aplica al elegir: se ordena por ventaja
# de fase y se va cogiendo, saltando cualquier candidato que comparta grupo con
# algo ya seleccionado. Gana el representante que mejor puntúe, que es lo que
# tiene sentido.
OVERLAP_GROUPS = {
    "Financiero": "financiero",
    "Bancos": "financiero",
    "Tecnología": "tecnología",
    "Software": "tecnología",
    "Semiconductores": "tecnología",
    "Inmobiliario": "inmobiliario",
    "REITs": "inmobiliario",
    "Cobre": "metales industriales",
    "Minería no férrea": "metales industriales",
    "Oro (lingote)": "oro",
    "Oro (ETF físico)": "oro",
    "Metales preciosos (mineras)": "oro",
    "Materias primas (índice)": "energía y materias primas",
    "Materias primas (ETF)": "energía y materias primas",
    "Petróleo y gas": "energía y materias primas",
}


def _shrunk_means(hist, hph, phase):
    """Media condicional a la fase, contraída hacia la media incondicional."""
    sub = hist[hph == phase]
    if sub.empty:
        return pd.Series(dtype=float)
    grand = hist.mean()
    mu = sub.mean()
    se = sub.std() / np.sqrt(sub.notna().sum().clip(lower=1))
    tau2 = (mu - grand).var()
    return grand + (tau2 / (tau2 + se ** 2)).fillna(0.0) * (mu - grand)


# Tope de peso de un activo dentro de su bloque. Sin él, la ponderación por
# inverso de volatilidad se lo lleva todo al activo menos volátil: las letras a 3
# meses acaparaban del 23 % al 40 % de la cartera entera y el resto de la renta
# fija se quedaba en el 0,6 %. Ponderar por riesgo no puede significar concentrar.
def _inner_weights(v: pd.Series) -> pd.Series:
    """Equiponderación entre los elegidos del bloque.

    El reparto por inverso de volatilidad era defendible como criterio a priori,
    pero dentro de un bloque cancela justo la señal que lo motiva: si el reloj
    dice "duración larga en Reflación", eliges el Treasury a 30 años y acto
    seguido le pones cuatro veces menos peso que al de 2 años por ser cuatro
    veces más volátil. Lo mismo con materias primas en Estanflación. El nivel de
    riesgo ya lo fijan las bandas entre bloques; dentro del bloque el reparto
    neutral es el equitativo, y no penaliza al activo que lleva la información.
    """
    return pd.Series(1.0 / len(v), index=v.index)


def _phase_edge(hist, hph, phase, vol):
    """Lo único que el reloj dice saber: cuánto mejor o peor se comporta cada
    activo EN esta fase respecto a su propio comportamiento habitual, por unidad
    de riesgo. La versión anterior ordenaba por rentabilidad/volatilidad absoluta,
    y eso selecciona el mismo puñado de activos defensivos en las cuatro fases:
    Utilities y Consumo básico salían en tres de cuatro. Ordenar por ventaja
    condicional es lo que convierte esto en una rotación y no en una cartera de
    baja volatilidad con etiquetas de fase encima."""
    mu = _shrunk_means(hist, hph, phase)
    if mu.empty:
        return pd.Series(dtype=float)
    return (mu - hist.mean()) / vol.replace(0, np.nan)


def _dedupe(cand, depth):
    """Un solo activo por exposición económica. Se queda el que más historia tiene
    en ese momento; el desempate es alfabético. Regla previa a los retornos."""
    best, out = {}, []
    for c in cand:
        g = VEHICLE_GROUPS.get(c)
        if g is None:
            out.append(c)
            continue
        d = float(depth.get(c, 0) or 0)
        if g not in best or (d, c) > best[g][0]:
            best[g] = ((d, c), c)
    return out + [v[1] for v in best.values()]


def _sleeve_pick(edge, vol, avail, classes, cls_map, n_pick, depth=None):
    """Selección por ventaja de fase; reparto interno por riesgo, con tope.
    Devuelve los pesos del bloque y su puntuación agregada."""
    cand = [c for c in avail
            if cls_map.get(c) in classes and c not in NOT_SELECTABLE]
    if depth is not None:
        cand = [c for c in cand if float(depth.get(c, 0) or 0) >= MIN_HISTORY_M]
        cand = _dedupe(cand, depth)
    if not cand:
        return {}, 0.0
    e = edge.reindex(cand).replace([np.inf, -np.inf], np.nan).dropna()
    if e.empty:
        return {}, 0.0
    # Selección voraz por ventaja, saltando exposiciones ya cubiertas.
    top, taken = [], set()
    for c in e.sort_values(ascending=False).index:
        g = OVERLAP_GROUPS.get(c)
        if g is not None and g in taken:
            continue
        top.append(c)
        if g is not None:
            taken.add(g)
        if len(top) == n_pick:
            break
    top = pd.Index(top)
    v = vol.reindex(top).replace(0, np.nan).dropna()
    w = _inner_weights(v) if not v.empty else pd.Series(
        1.0 / len(top), index=top)
    # Puntuación del bloque: ventaja media ponderada por riesgo de lo elegido
    score = float((e.reindex(w.index) * w).sum())
    return w.to_dict(), score


def _sleeve_weights(scores_by_phase: dict, phase: str) -> dict:
    """Reparte el 100 % entre bloques partiendo de la postura neutra 60/30/10 y
    desviándose según lo bien que cada bloque puntúe EN ESA FASE respecto a su
    propio nivel habitual, no respecto a los otros bloques.

    El reparto anterior comparaba bloques por rentabilidad/riesgo absoluta. En una
    muestra de 1990 a hoy la renta fija gana esa comparación en las cuatro fases
    —mercado alcista de bonos de 35 años—, así que la cartera salía al 40 % de
    renta variable en todas ellas: ni rotaba ni tenía el riesgo del índice contra
    el que se mide. Estandarizar cada bloque contra sí mismo elimina ese sesgo."""
    w = {}
    for k in SLEEVES:
        vals = np.array([float(scores_by_phase.get(p, {}).get(k, np.nan))
                         for p in PHASES], dtype=float)
        cur = float(scores_by_phase.get(phase, {}).get(k, np.nan))
        m, sd = np.nanmean(vals), np.nanstd(vals)
        if not np.isfinite(cur) or not np.isfinite(sd) or sd <= 1e-12:
            z = 0.0
        else:
            z = float(np.clip((cur - m) / sd, -MAX_Z, MAX_Z)) / MAX_Z
        lo, hi = SLEEVES[k][1], SLEEVES[k][2]
        neutral = NEUTRAL[k]
        # Banda completa y asimétrica. Antes se usaba min(neutral-lo, hi-neutral),
        # que en renta variable daba 10pp y dejaba el rango efectivo en 50-70 %
        # teniendo declarado 30-70. La palanca principal del reloj —bajar renta
        # variable de verdad en Estanflación— quedaba amputada por simetría.
        span = (hi - neutral) if z >= 0 else (neutral - lo)
        w[k] = min(max(neutral + z * span, lo), hi)
    for _ in range(24):
        gap = 1.0 - sum(w.values())
        if abs(gap) < 1e-9:
            break
        room = {k: (SLEEVES[k][2] - w[k]) if gap > 0 else (w[k] - SLEEVES[k][1])
                for k in SLEEVES}
        total_room = sum(room.values())
        if total_room <= 1e-12:
            break
        for k in SLEEVES:
            w[k] += gap * room[k] / total_room
        w = {k: min(max(w[k], SLEEVES[k][1]), SLEEVES[k][2]) for k in SLEEVES}
    return w


def rotation(X: pd.DataFrame, phases: pd.Series, cls_map: dict,
             min_train: int = 120) -> dict:
    """Cartera solo larga, siempre invertida al 100 %, con el mismo reparto por
    bloques en todas las fases. La fase decide únicamente qué activos ocupan cada
    bloque. Selección por rentabilidad contraída dividida entre volatilidad, y
    reparto dentro del bloque por inverso de la volatilidad."""
    print("7. Rotación por fase (solo largo, sin apalancar)…")
    common = X.dropna(how="all").index.intersection(phases.dropna().index)
    # La estrategia y el índice de referencia tienen que cubrir exactamente los
    # mismos meses. Las carteras de Ken French publican con dos meses de desfase,
    # así que los dos últimos meses de la muestra tenían estrategia pero no
    # benchmark, y además se calculaban con menos de la mitad del universo
    # disponible. Se corta ahí.
    for _c in ("Renta variable EE.UU. (mercado)", "Treasury 10 años"):
        if _c in X.columns:
            last = X[_c].dropna().index.max()
            if last is not None:
                common = common[common <= last]
    X = X.loc[common]
    ph = phases.loc[common]
    if len(common) < min_train + 60:
        return {}

    def run(full_sample: bool = False):
        """Recorre la muestra montando la cartera mes a mes. Con full_sample=True
        las medias por fase se estiman con TODO el histórico, incluido el futuro:
        es la misma regla jugada con ventaja, y la distancia entre las dos curvas
        es la medida directa de cuánto de este resultado es sobreajuste."""
        rets, dates, held = [], [], []
        for k in range(min_train, len(common)):
            t = common[k]
            sig = ph.iloc[k - 1]
            hist, hph = (X, ph) if full_sample else (X.iloc[:k], ph.iloc[:k])
            vol, depth = hist.std(), hist.notna().sum()
            avail = list(X.loc[t].dropna().index)
            picks, scores = {}, {}
            for phase in PHASES:
                edge_p = _phase_edge(hist, hph, phase, vol)
                scores[phase] = {}
                for name, (classes, lo, hi, n_pick) in SLEEVES.items():
                    w_p, s_p = _sleeve_pick(edge_p, vol, avail, classes,
                                            cls_map, n_pick, depth)
                    scores[phase][name] = s_p
                    if phase == sig:
                        picks[name] = w_p
            budgets = _sleeve_weights(scores, sig)
            w_all, r = {}, 0.0
            for name, inner in picks.items():
                for c, wt in inner.items():
                    w_all[c] = w_all.get(c, 0.0) + budgets[name] * wt
            if not w_all:
                continue
            tot = sum(w_all.values())
            for c, wt in w_all.items():
                r += (wt / tot) * float(X.loc[t, c])
            rets.append(r)
            dates.append(t)
            held.append(sig)
        return pd.Series(rets, index=dates), dates, held

    R_is, _, _ = run(full_sample=True)

    rets, dates, held = [], [], []
    for k in range(min_train, len(common)):
        t = common[k]
        sig = ph.iloc[k - 1]
        hist, hph = X.iloc[:k], ph.iloc[:k]
        vol, depth = hist.std(), hist.notna().sum()
        avail = list(X.loc[t].dropna().index)
        # Puntuación de cada bloque en las cuatro fases, solo con datos pasados:
        # hace falta para estandarizar la desviación respecto al neutro.
        picks, scores = {}, {}
        for phase in PHASES:
            edge_p = _phase_edge(hist, hph, phase, vol)
            scores[phase] = {}
            for name, (classes, lo, hi, n_pick) in SLEEVES.items():
                w_p, s_p = _sleeve_pick(edge_p, vol, avail, classes, cls_map,
                                        n_pick, depth)
                scores[phase][name] = s_p
                if phase == sig:
                    picks[name] = w_p
        budgets = _sleeve_weights(scores, sig)
        w_all, r = {}, 0.0
        for name, inner in picks.items():
            for c, wt in inner.items():
                w_all[c] = w_all.get(c, 0.0) + budgets[name] * wt
        if not w_all:
            continue
        tot = sum(w_all.values())
        for c, wt in w_all.items():
            r += (wt / tot) * float(X.loc[t, c])
        rets.append(r)
        dates.append(t)
        held.append(sig)

    R = pd.Series(rets, index=dates)
    eq, bd = X.get("Renta variable EE.UU. (mercado)"), X.get("Treasury 10 años")
    bench = (0.6 * eq + 0.4 * bd).reindex(dates) if eq is not None and bd is not None else None

    # Comportamiento por fase, para ver dónde gana y dónde pierde
    by_phase = {}
    hp = pd.Series(held, index=dates)
    for phase in PHASES:
        m = hp == phase
        if m.sum() < 12:
            continue
        entry = {"n": int(m.sum()),
                 "ann": round(float(R[m].mean() * 12), 2)}
        if bench is not None:
            entry["bench_ann"] = round(float(bench[m].mean() * 12), 2)
            entry["edge"] = round(entry["ann"] - entry["bench_ann"], 2)
        by_phase[phase] = entry

    # Guion de cartera: qué compraría hoy en cada fase, con toda la historia
    playbook, sleeve_mix = {}, {}
    vol_all, depth_all = X.std(), X.notna().sum()
    # Un activo está vigente si ha publicado en los últimos LAG_TOLERANCE_M meses.
    # Antes se exigía dato en el último mes exacto, y eso dejaba fuera todas las
    # carteras sectoriales de Ken French, que van con dos meses de retraso.
    recent = X.tail(LAG_TOLERANCE_M)
    avail = [c for c in X.columns if recent[c].notna().any()]
    picks_by_phase, scores_all = {}, {}
    for phase in PHASES:
        edge = _phase_edge(X, ph, phase, vol_all)
        picks_by_phase[phase], scores_all[phase] = {}, {}
        for sleeve, (classes, lo, hi, n_pick) in SLEEVES.items():
            w_p, s_p = _sleeve_pick(edge, vol_all, avail, classes, cls_map,
                                    n_pick, depth_all)
            picks_by_phase[phase][sleeve] = w_p
            scores_all[phase][sleeve] = s_p
    for phase in PHASES:
        picks = picks_by_phase[phase]
        budgets = _sleeve_weights(scores_all, phase)
        rows = []
        for sleeve, inner in picks.items():
            for c, wt in sorted(inner.items(), key=lambda kv: -kv[1]):
                rows.append({"sleeve": sleeve, "name": c,
                             "weight": round(budgets[sleeve] * wt * 100, 1),
                             "class": cls_map.get(c, "")})
        playbook[phase] = [r for r in rows if r["weight"] >= 0.5]
        sleeve_mix[phase] = {k: round(v * 100, 1) for k, v in budgets.items()}

    curve = [{"d": d.strftime("%Y-%m"), "s": round(float(R.loc[d]), 4),
              "b": (round(float(bench.loc[d]), 4)
                    if bench is not None and bench.loc[d] == bench.loc[d] else None)}
             for d in dates]
    print(f"  ✓ {len(R)} meses desde {dates[0].date()}")
    return {"portfolio": perf(R),
            "in_sample": perf(R_is),
            "bench_6040": perf(bench) if bench is not None else {},
            "by_phase": by_phase, "playbook": playbook, "sleeve_mix": sleeve_mix,
            "bands": {k: [round(v[1] * 100), round(v[2] * 100)] for k, v in SLEEVES.items()},
            "curve": curve[-460:]}


# ======================================================================================
# 8. Validación
# ======================================================================================

def _phase_by_decade(phases: pd.Series) -> dict:
    """Reparto de fases por década. Si dos cuadrantes salen vacíos durante veinte
    años, la rotación no tiene nada que rotar y ningún ajuste de cartera lo
    arregla. Es el primer sitio donde mirar."""
    out = {}
    for dec, sub in phases.dropna().groupby((phases.dropna().index.year // 10) * 10):
        out[str(int(dec))] = {ph: int((sub == ph).sum()) for ph in PHASES}
    return out


def validation(df, F, phases):
    out = {}
    if "USREC" in df.columns:
        rec = df["USREC"].reindex(phases.index).dropna()
        p = phases.reindex(rec.index)
        inr = rec == 1
        neg = F["growth"].reindex(rec.index) < 0
        out["nber"] = {
            "recall": round(float(neg[inr].mean()), 3),
            "specificity": round(float((~neg[~inr]).mean()), 3),
            "share_recession_months": round(float(inr.mean()), 3),
            "phase_mix_in_recession": {ph: round(float((p[inr] == ph).mean()), 3)
                                       for ph in PHASES},
        }
    runs = {ph: [] for ph in PHASES}
    cur, n = None, 0
    for v in phases.dropna():
        if v == cur:
            n += 1
        else:
            if cur:
                runs[cur].append(n)
            cur, n = v, 1
    if cur:
        runs[cur].append(n)
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
    out["by_decade"] = _phase_by_decade(phases)
    out["factor_corr"] = round(float(F["growth"].corr(F["inflation"])), 3)
    cw = [("Recuperación", "Sobrecalentamiento"), ("Sobrecalentamiento", "Estanflación"),
          ("Estanflación", "Reflación"), ("Reflación", "Recuperación")]
    moves = [(a, b) for a, b in zip(seq[:-1], seq[1:]) if a != b]
    if moves:
        out["rotation"] = {"n_transitions": len(moves),
                           "clockwise_share": round(
                               sum((a, b) in cw for a, b in moves) / len(moves), 3)}
    return out


# ======================================================================================
# 9. Ensamblado
# ======================================================================================

def main() -> None:
    t0 = time.time()
    df, raw_meta = fetch_macro()
    Z, ind_info = build_blocks(df)
    F, pca = build_factors(Z)
    F = F.dropna(subset=["growth", "inflation"])

    phases = pd.Series([classify(a, b) for a, b in zip(F["growth"], F["inflation"])],
                       index=F.index, name="phase")
    sg = float(F["growth"].diff(HORIZON_M).std())
    si = float(F["inflation"].diff(HORIZON_M).std())
    g, i = float(F["growth"].iloc[-1]), float(F["inflation"].iloc[-1])
    probs = phase_probs(g, i, sg, si)
    rank = sorted(probs.items(), key=lambda kv: kv[1], reverse=True)
    conf = rank[0][1] - rank[1][1]

    X, ameta = fetch_assets(df)
    if RETURNS_PATH:
        try:
            os.makedirs(os.path.dirname(RETURNS_PATH) or ".", exist_ok=True)
            out = X.copy()
            out.insert(0, "fase", phases.reindex(out.index))
            out.round(6).to_csv(RETURNS_PATH, compression="gzip")
            print(f"  ✓ retornos volcados en {RETURNS_PATH} "
                  f"({os.path.getsize(RETURNS_PATH)/1024:.0f} KB)")
        except Exception as exc:  # el volcado nunca debe tumbar la build
            print(f"  ! no se pudo volcar retornos: {exc}")
    assets, astats = conditional_stats(X, phases, ameta)
    bt = backtest(X, phases)
    prot = defensive(X, F["growth"])
    cls_map = {k: v.get("class", "Otros") for k, v in ameta.items()}
    rot = rotation(X, phases, cls_map)
    val = validation(df, F, phases)
    rec = recession_model(df, F.index)

    p1, p2 = rank[0][0], rank[1][0]
    consensus = []
    for a in assets:
        d1, d2 = a["phases"].get(p1, {}), a["phases"].get(p2, {})
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
        indicators.append({
            **ind_info[spec.fred_id],
            "z": round(float(z.iloc[-1]), 2),
            "z_prev": round(float(z.iloc[-13]), 2) if z.size > 13 else None,
            "loading": pca.get(spec.block, {}).get("loadings", {}).get(spec.fred_id),
            "last_obs": raw_meta.get(spec.fred_id, {}).get("last_obs"),
        })
    missing = [s.fred_id for s in SERIES if s.fred_id not in {x["id"] for x in indicators}]
    if missing:
        warn(f"series sin z-score utilizable: {', '.join(missing)}")

    history = [{"d": d.strftime("%Y-%m"), "g": round(float(a), 3),
                "i": round(float(b), 3), "p": p}
               for d, a, b, p in zip(F.index, F["growth"], F["inflation"], phases)]

    nber = []
    if "USREC" in df.columns:
        r = df["USREC"].reindex(F.index).fillna(0)
        st = None
        for d, v in r.items():
            if v == 1 and st is None:
                st = d
            elif v == 0 and st is not None:
                nber.append([st.strftime("%Y-%m"), d.strftime("%Y-%m")])
                st = None
        if st is not None:
            nber.append([st.strftime("%Y-%m"), F.index[-1].strftime("%Y-%m")])

    payload = {
        "meta": {
            "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "version": 2,
            "series_ok": int(Z.shape[1]), "series_total": len(SERIES),
            "assets_ok": sum(1 for a in ASSET_LOG if a["status"] == "ok"),
            "assets_tried": len(ASSET_LOG),
            "history_from": history[0]["d"],
            "warnings": WARNINGS, "asset_log": ASSET_LOG,
            "build_seconds": round(time.time() - t0, 1),
        },
        "current": {
            "date": F.index[-1].strftime("%Y-%m"),
            "phase": rank[0][0], "phase_long": PHASE_LONG[rank[0][0]],
            "alt_phase": rank[1][0],
            "growth": round(g, 3), "inflation": round(i, 3),
            "leading": round(float(F["leading"].iloc[-1]), 3) if "leading" in F else None,
            "leading_6m": round(float(F["leading"].iloc[-7]), 3)
                          if "leading" in F and len(F) > 7 else None,
            "sigma_g": round(sg, 3), "sigma_i": round(si, 3), "horizon_m": HORIZON_M,
            "probs": {k: round(v, 4) for k, v in probs.items()},
            "confidence": round(conf, 4),
            "momentum": {
                "growth_3m": round(float(F["growth"].iloc[-1] - F["growth"].iloc[-4]), 3)
                             if len(F) > 4 else None,
                "inflation_3m": round(float(F["inflation"].iloc[-1] - F["inflation"].iloc[-4]), 3)
                                if len(F) > 4 else None,
            },
            "recession": rec,
        },
        "pca": pca, "indicators": indicators, "history": history, "nber": nber,
        "assets": assets, "asset_stats": astats, "consensus": consensus[:14],
        "backtest": bt, "defensive": prot, "rotation": rot, "validation": val,
        "phases": PHASES, "phase_long": PHASE_LONG,
    }

    os.makedirs(os.path.dirname(OUT_PATH) or ".", exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"\n✓ {OUT_PATH} ({os.path.getsize(OUT_PATH)/1024:.0f} KB) — "
          f"{rank[0][0]} (confianza {conf:.0%}) · "
          f"{payload['meta']['assets_ok']}/{payload['meta']['assets_tried']} activos · "
          f"{astats['fdr_survivors']} casillas robustas  [{time.time()-t0:.0f}s]")


if __name__ == "__main__":
    main()
