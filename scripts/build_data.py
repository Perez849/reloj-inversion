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


ROLL_WINDOW_M = 120  # diez años: cubre un ciclo económico completo sin arrastrar
                     # un cambio de régimen de cuarenta años (ver nota más abajo)


def rolling_z(s: pd.Series, window: int = ROLL_WINDOW_M) -> pd.Series:
    """z-score en VENTANA MÓVIL de diez años, ROBUSTO (mediana y desviación
    absoluta mediana en lugar de media y desviación típica).

    Dos requisitos, y los dos importan.

    Posición cíclica, no nivel. Con ventana EXPANSIVA (toda la historia desde el
    arranque de la serie), el pico inflacionista de los setenta queda dentro de la
    referencia para siempre: de 1990 a 2020 la inflación aparece permanentemente
    por debajo de "lo normal" y el reloj se pasa dos décadas usando solo dos de
    sus cuatro cuadrantes — comprobado sobre los datos reales de este panel, los
    años noventa y la década de 2010 no registraban ni un solo mes de
    Sobrecalentamiento ni de Estanflación. Una ventana de diez años responde a la
    pregunta correcta, "¿alto o bajo respecto a lo que ha sido normal
    últimamente?", en vez de comparar contra medio siglo de historia.

    Robustez frente a valores extremos. Marzo y abril de 2020 y el rebote de 2021
    son valores de ±10 desviaciones; con media y desviación típica esos meses
    dominan una ventana de diez años durante todo el tiempo que permanecen dentro
    de ella. La mediana no se mueve por unos pocos valores extremos; la MAD
    tampoco. Escalada por 1,4826 equivale a la desviación típica cuando los datos
    son normales, así que los umbrales no cambian de significado.

    Ventana adaptativa al arranque: mientras no hay diez años de historia se usa
    toda la disponible (equivalente a expansiva), con suelo de 48 meses.
    """
    n = int(s.notna().sum())
    mp = min(window, max(48, n // 3))
    med = s.rolling(window, min_periods=mp).median()
    mad = (s - med).abs().rolling(window, min_periods=mp).median() * 1.4826
    # Si la MAD es degenerada (serie casi constante), se recurre a la desviación
    sd = s.rolling(window, min_periods=mp).std()
    scale = mad.where(mad > 1e-8, sd)
    return ((s - med) / scale).clip(-4, 4)


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
        z = rolling_z(x).shift(spec.lag_m)
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
    # "Durbl" (bienes duraderos: coches, electrodomésticos, muebles) se excluyó
    # aposta. Ken French la separa de "Shops" como industria propia, con su
    # propia serie de retornos, pero no existe un ETF sectorial real que la
    # trackee aparte del consumo discrecional — IYC y XLY cubren coches,
    # electrodomésticos y muebles igual que el resto del consumo discrecional.
    # Tenerla como sector aparte invitaba a recomendar "Consumo duradero" Y
    # "Consumo discrecional" a la vez, dos nombres para la misma orden de
    # compra (el mismo IYC dos veces en la misma cartera).
    "NoDur": "Consumo básico", "Manuf": "Industria",
    "Enrgy": "Energía", "Chems": "Materiales / Químicas", "BusEq": "Tecnología",
    "Telcm": "Comunicaciones", "Utils": "Utilities", "Shops": "Consumo discrecional",
    "Hlth": "Salud", "Money": "Financiero", "Other": "Otros sectores",
}

# De las 49 industrias solo se toman las exposiciones que NO existen en las 12
# industrias: oro, minería e inmobiliario. Bancos, Software, Chips y Petróleo
# duplicaban a Financiero, Tecnología y Energía, y el bloque acababa eligiendo seis
# nombres que eran tres exposiciones repetidas.
FRENCH_49 = {
    # Clase propia "Oro", separada de "Real / alternativos": es la única
    # exposición no bursátil que entra en la cartera de rotación (ver SLEEVES),
    # así que necesita poder seleccionarse sola sin arrastrar plata, cobre,
    # materias primas o inmobiliario.
    "Gold": ("Metales preciosos (mineras)", "Oro",
             "mineras de oro, no lingote: el oro físico ya no está en FRED"),
    "RlEst": ("Inmobiliario", "Real / alternativos",
              "sustituye al índice Wilshire, retirado de FRED"),
}

# ICE truncó a 3 años TODOS sus índices de retorno total en FRED en abril de 2026,
# incluidos los subconjuntos por rating. El crédito se cubre con los rendimientos de
# Moody's (duración, desde 1919) y con ETF reales vía Yahoo para el tramo moderno.
FRED_TR: dict[str, tuple[str, list[str]]] = {}

FRED_PX = {
    # No invertibles: se conservan como referencia en la matriz, fuera de la cartera.
    "Petróleo WTI (spot)": ("Referencia", ["WTISPLC", "MCOILWTICO"],
                            "precio spot, no comprable directamente"),
    "Cesta de producción (PPI)": ("Referencia", ["PPIACO"],
                                  "índice de precios, no invertible"),
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
    "Oro (lingote)": ("Oro", "GC=F", "xauusd",
                      "futuro continuo de oro; el histórico largo lo cubren las mineras"),

    "Plata": ("Real / alternativos", "SI=F", "xagusd", ""),
    "Materias primas (índice)": ("Real / alternativos", "^SPGSCI", "^spgsci", "GSCI"),

    "Cobre": ("Real / alternativos", "HG=F", "hg.f", ""),

    "Crédito Investment Grade (LQD)": ("Renta fija", "LQD", "lqd.us",
                                       "retorno total real, desde 2002"),
    "Crédito High Yield (HYG)": ("Renta fija", "HYG", "hyg.us",
                                 "retorno total real, desde 2007"),
    "Deuda emergente (EMB)": ("Renta fija", "EMB", "emb.us", ""),
    "TIPS (TIP)": ("Renta fija", "TIP", "tip.us", ""),
    "Municipales (MUB)": ("Renta fija", "MUB", "mub.us", ""),
    "Titulizaciones hipotecarias (MBB)": ("Renta fija", "MBB", "mbb.us", ""),
    "Renta variable emergente": ("Índice regional", "EEM", "eem.us",
                                 "índice de país, no sector: fuera de la selección"),
    "Renta variable internacional": ("Índice regional", "EFA", "efa.us",
                                     "índice de país, no sector: fuera de la selección"),
    "Small caps": ("Estilo", "IWM", "iwm.us", ""),
}

# Carteras internacionales de Ken French: misma fuente que ya funciona, historia
# desde 1990, sin depender de proveedores que bloquean servidores.
FRENCH_INTL = {
    "Desarrollados ex EE.UU. (French)": ("Índice regional",
                                         "Developed_ex_US_3_Factors_CSV.zip"),
    "Emergentes (French)": ("Índice regional", "Emerging_5_Factors_CSV.zip"),
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
        # Guardián de plausibilidad. Nace de un caso real: una fuente devolvió un
        # índice acumulado disfrazado de retornos mensuales (media del 25% mensual,
        # 99,9% de los meses en positivo, porque un índice acumulado casi nunca baja).
        # El primer filtro exige las DOS cosas a la vez, no una sola: la liquidez y
        # los bonos cortos son legítimamente positivos el 95%+ de los meses (es
        # interés devengado, casi nunca negativo) con una media baja, y un filtro
        # que solo mirara "casi siempre positivo" los habría descartado a ellos, no
        # al índice disfrazado. Lo que delata al índice acumulado es ir siempre en
        # positivo Y con una media que ningún retorno mensual real alcanza.
        share_pos = float((s > 0).mean())
        mean_m = float(s.mean())
        max_abs = float(s.abs().max())
        looks_like_index = share_pos > 0.90 and mean_m > 3.0
        implausible = looks_like_index or share_pos < 0.15 or mean_m > 8.0 or max_abs > 150.0
        if implausible:
            ASSET_LOG.append({"name": name, "source": source, "status": "descartado",
                              "detail": f"no parece un retorno mensual plausible "
                                        f"({share_pos:.0%} de meses positivos, media "
                                        f"{mean_m:.1f}%, máximo {max_abs:.0f}%)"})
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
        add("Renta variable EE.UU. (mercado)", ff["Mkt-RF"] + rf, "Índice regional",
            "Ken French", "índice agregado: referencia, no posición")
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


# ======================================================================================
# 7b. Rotación por fase, solo largo y sin apalancar
# ======================================================================================

# Cartera 100% renta variable de sectores, sin renta fija: por decisión explícita,
# no por hallazgo del backtest. El oro y las mineras de oro entran como única
# excepción no bursátil, con techo bajo — un seguro táctico para Estanflación y
# Reflación, nunca el núcleo de la cartera. Sin apalancamiento y sin cortos; la
# comparación que importa aquí es contra la propia renta variable (bench_100eq
# en rotation()), no contra un 60/40 que esta cartera ni tiene ni pretende imitar.
SLEEVES = {
    # El número de sectores NO es fijo: cada mes se queda con los que puntúan
    # positivo de verdad en esa fase (ver _sleeve_pick), entre un suelo y un
    # techo — nunca se mete un sector con puntuación floja o negativa solo por
    # rellenar un cupo. Suelo de 2, no más: la banda del 80% mínimo en renta
    # variable tiene que ir a algún sitio, así que nunca se queda vacía ni
    # concentrada en un único nombre, pero por debajo de eso manda la fase, no
    # un mínimo de diversificación inventado. Techo de 7: con 8 o más de los
    # 11 sectores ya casi es comprar el índice entero, y no queda rotación que
    # evaluar. Entre medias, lo que la fase sostenga, ni uno más.
    "Renta variable": ({"Renta variable"}, 0.80, 1.00, 2, 7),
    # Oro físico y mineras de oro, las dos únicas exposiciones de la clase
    # "Oro" (ver FRENCH_49 y MARKET). Sin suelo: puede quedarse en 0, 1 o 2
    # nombres. Es un seguro táctico, no una posición obligatoria, y nunca
    # supera a la renta variable en peso (banda 0-20%).
    "Oro": ({"Oro"}, 0.00, 0.20, 0, 2),
}

# Índices agregados: sirven de referencia, no de posición. Si entran en la selección
# copan siempre el bloque de renta variable y no hay rotación sectorial ninguna.
# La clase "Índice regional" no entra en ningún bloque: los índices agregados y de
# país sirven de referencia, no de posición. Si compiten con los sectores los barren
# siempre, porque un índice diversificado tiene mejor rentabilidad por unidad de
# riesgo que cualquier sector suelto, y entonces no hay rotación sectorial ninguna.
# La liquidez se mide como exceso sobre la propia liquidez: su rentabilidad es cero
# por construcción y su volatilidad casi cero. Al ordenar por rentabilidad entre
# volatilidad, ese cociente se dispara y se cuela como primera posición; después el
# reparto por inverso de volatilidad le da un peso enorme. La cartera acababa con un
# cuarto del dinero parado y la volatilidad hundida. No es una posición: es la
# unidad de medida.
NOT_SELECTABLE = {"Otros sectores", "Liquidez (letras 3m)"}

# Suelo de volatilidad para el reparto y la ordenación. Sin él, cualquier activo
# muy poco volátil acapara la cartera por el mismo mecanismo.
VOL_FLOOR_Q = 0.20

# Vida media de la ponderación temporal, en meses. Una media plana sobre cien años
# trata igual a 1935 y a 2025, y la composición de los sectores ha cambiado por
# completo: "Tecnología" en French son máquinas de oficina en los años treinta y
# semiconductores hoy. Con vida media de diez años, lo reciente pesa el doble que
# lo de hace una década y unas treinta veces más que lo de hace cincuenta años,
# sin que nada llegue a desaparecer. Se aplica igual a todos los activos.
HALF_LIFE_M = 120

# Meses mínimos de una fase que debe tener un activo para que se le estime una
# media PROPIA de esa fase. Por debajo, se usa su media general: sigue pudiendo
# entrar en cartera, pero no se le atribuye un comportamiento cíclico deducido de
# dos años de datos. Sin esta regla, la plata (27 meses en Estanflación) o las
# materias primas (29) entraban con estimaciones que eran puro ruido, y rendían
# -8 % y -27 % en la fase en la que se las compraba.
MIN_PHASE_OBS = 36


SCHEMES = {
    "equal": "Equiponderado",
    "invvol": "Inverso de la volatilidad",
    "rank": "Por puesto",
    "blend": "Mitad y mitad",
}


def _weights(names, vol, scheme: str) -> pd.Series:
    """Reparto dentro de un bloque. `names` viene ya ordenado de mejor a peor.
      equal  — 1/n. Ninguna opinión: la referencia contra la que medir el resto.
      invvol — proporcional a 1/volatilidad. Iguala la aportación de riesgo.
      rank   — proporcional al puesto (n, n-1, …, 1). Premia la convicción.
      blend  — media de equiponderado e inverso de volatilidad."""
    names = list(names)
    n = len(names)
    if n == 0:
        return pd.Series(dtype=float)
    eq = pd.Series(1.0 / n, index=names)
    v = vol.reindex(names).replace(0, np.nan)
    if v.notna().sum() > 1:
        fl = v.min() if v.notna().sum() < 3 else v.quantile(VOL_FLOOR_Q)
        if fl and fl > 0:
            v = v.clip(lower=fl)
    iv = (1.0 / v)
    iv = (iv / iv.sum()) if iv.notna().any() else eq
    iv = iv.fillna(0.0)
    if iv.sum() <= 0:
        iv = eq
    if scheme == "equal":
        return eq
    if scheme == "invvol":
        return iv / iv.sum()
    if scheme == "rank":
        r = pd.Series(np.arange(n, 0, -1, dtype=float), index=names)
        return r / r.sum()
    return (0.5 * eq + 0.5 * (iv / iv.sum()))


def _sleeve_pick(mu, vol, raw_phase, avail, classes, cls_map, n_min, n_max):
    """Selecciona los del bloque que de verdad convienen en esta fase y
    devuelve su orden y su puntuación. El número elegido no es fijo: se
    queda con los que puntúan **positivo** (ventaja de fase > 0) más los
    empatados en **cero** —contracción total, tau2 = 0: la fase no le
    sienta ni mejor ni peor que su propia media, según la ventaja
    CONTRAÍDA— cuyo rendimiento REAL en esta fase (sin contraer) entre
    volatilidad iguala o supera al típico del bloque esa misma fase
    (mediana de todos los candidatos, no solo los empatados). Acotado entre
    un suelo y un techo. Con menos aceptables que el suelo, se completa
    hasta el suelo con los siguientes mejores aunque puntúen negativo — el
    suelo evita la cartera vacía o concentrada en un único nombre, no es
    una opinión sobre esos activos. Con más aceptables que el techo, se
    recorta a los mejores, para que la cartera siga siendo una apuesta por
    unos pocos nombres y no el índice disfrazado.

    El empate en cero no basta por sí solo, y el motivo importa: descartar
    cualquier empate en cero (0 no es > 0) dejaba fuera a Tecnología de las
    cuatro fases pese a ser, de largo, uno de los dos sectores de mayor
    rendimiento incondicional de los diez — ninguna fase le sienta mal, así
    que no había motivo para excluirlo solo porque ninguna le sienta MEJOR
    que su ya alto promedio.

    Pero el desempate no puede ser el rendimiento INCONDICIONAL del activo
    (una versión anterior lo hacía así, con `grand`): cuando la contracción
    es total, `grand + mu` es literalmente `grand` —no aporta nada nuevo—,
    así que ese desempate acababa siendo "cuál es mejor en general",
    exactamente el mismo problema que el nivel absoluto original (el del
    oro) solo que un paso más allá. Con datos reales: en Estanflación,
    Tecnología rindió -0,85 % real (de los peores) frente al +3,58 % real
    de Utilities, pero el desempate por incondicional seguía prefiriendo a
    Tecnología (8,75 % de media general, frente al 6,57 % de Utilities) —
    exactamente al revés de lo que de verdad pasó esa fase. El desempate
    correcto es el rendimiento REAL de ESA fase sin contraer (`raw_phase`,
    la misma media por fase que se contrae para calcular `mu`, pero antes
    de contraerla): no se usa como criterio PRINCIPAL de selección porque
    con poca muestra es ruidoso —para eso está la contracción—, pero es
    estrictamente mejor que la única alternativa disponible cuando la
    ventaja contraída no diferencia nada, sea para decidir si un empate en
    cero es aceptable o para ordenar al rellenar el suelo con negativos.
    La selección es idéntica para los cuatro esquemas: lo único que cambia entre
    ellos es cómo se reparte el dinero entre los ya elegidos."""
    cand = [c for c in avail
            if cls_map.get(c) in classes and c not in NOT_SELECTABLE]
    if not cand:
        return [], 0.0
    vc = vol.reindex(cand).replace(0, np.nan)
    floor = vc.quantile(VOL_FLOOR_Q) if vc.notna().sum() > 2 else None
    if floor and floor > 0:
        vc = vc.clip(lower=floor)
    ir = (mu.reindex(cand) / vc).replace([np.inf, -np.inf], np.nan).dropna()
    if ir.empty:
        return [], 0.0
    raw = (raw_phase.reindex(ir.index) / vc.reindex(ir.index)).replace([np.inf, -np.inf], np.nan)
    raw_bar = raw.median()
    ok = (ir > 0) | ((ir >= 0) & (raw >= raw_bar))
    combo = pd.DataFrame({"ir": ir, "raw": raw, "ok": ok})
    combo = pd.concat([
        combo[combo["ok"]].sort_values(["ir", "raw"], ascending=[False, False]),
        combo[~combo["ok"]].sort_values("raw", ascending=False),
    ])
    ir = combo["ir"]
    n_positive = int(combo["ok"].sum())
    n_take = min(max(n_positive, n_min), n_max, len(ir))
    top = list(ir.head(n_take).index)
    if not top:
        return [], 0.0
    v = vc.reindex(top)
    iv = 1.0 / v
    w = (iv / iv.sum()) if iv.notna().any() else pd.Series(1.0 / len(top), index=top)
    # Dos métricas distintas, y la diferencia importa:
    #   - DENTRO del bloque se ordena por ventaja entre volatilidad, porque se
    #     comparan activos de riesgo parecido y así no gana el más volátil por serlo.
    #   - ENTRE bloques se compara la ventaja esperada A SECAS. Usar el cociente
    #     también aquí premiaría sistemáticamente al oro, bastante menos volátil que
    #     la renta variable, y dejaría la cartera con menos bolsa que su propio suelo
    #     del 80%: rendiría menos por invertir menos, no por elegir peor.
    score = float((mu.reindex(top) * w.fillna(0)).sum())
    return top, score


def _sleeve_weights(scores: dict) -> dict:
    """Reparte el 100 % entre bloques en proporción a lo que puntúa cada uno en la
    fase, respetando las bandas. Una puntuación negativa se trata como cero: ese
    bloque baja a su mínimo, y el oro puede quedarse fuera del todo.

    NOTA: una versión anterior forzaba la volatilidad de la cartera a igualar la de
    un benchmark externo (primero 60/40, antes de eso el propio mercado). Fue un
    error: el reparto proporcional ya sale con una volatilidad muy parecida a la del
    bloque dominante por sí solo, y forzarla dejaba la renta variable clavada en su
    suelo, costando rentabilidad sin comprar nada a cambio.
    """
    names = list(SLEEVES)
    lo = {k: SLEEVES[k][1] for k in names}
    hi = {k: SLEEVES[k][2] for k in names}
    pos = {k: max(0.0, scores.get(k, 0.0)) for k in names}
    tot = sum(pos.values())
    raw = ({k: (lo[k] + hi[k]) / 2 for k in names} if tot <= 0
           else {k: pos[k] / tot for k in names})
    w = {k: min(max(raw[k], lo[k]), hi[k]) for k in names}
    for _ in range(24):
        gap = 1.0 - sum(w.values())
        if abs(gap) < 1e-9:
            break
        room = {k: (hi[k] - w[k]) if gap > 0 else (w[k] - lo[k]) for k in names}
        total = sum(room.values())
        if total <= 1e-12:
            break
        for k in names:
            w[k] += gap * room[k] / total
        w = {k: min(max(w[k], lo[k]), hi[k]) for k in names}
    return w


def _annual(series: pd.Series) -> dict:
    y = (1 + series / 100.0).groupby(series.index.year).prod() - 1
    return {int(k): round(float(v * 100), 2) for k, v in y.items()}


def factor_betas(hist: pd.DataFrame, F: pd.DataFrame, half_life: int = HALF_LIFE_M):
    """Regresión ponderada de cada activo sobre los dos factores macro.

    Trocear la historia en cuatro cubos deja fases con veintitantos meses y
    estimaciones que son ruido. Aquí cada activo se regresa sobre crecimiento e
    inflación usando TODOS los meses disponibles: la estanflación deja de ser un
    cubo con pocos datos y pasa a ser una región del plano hacia la que el modelo
    extrapola con la muestra entera. Los meses recientes pesan más, igual que antes.

    Las pendientes se contraen hacia cero en proporción a su error típico: si un
    activo no muestra sensibilidad clara a un factor, se le asigna la media general.
    """
    idx = hist.index.intersection(F.index)
    if len(idx) < 60:
        return None
    g = F.loc[idx, "growth"].values
    i = F.loc[idx, "inflation"].values
    ref = idx[-1]
    months = np.array([(ref.year - d.year) * 12 + (ref.month - d.month)
                       for d in idx], dtype=float)
    w = 0.5 ** (months / half_life)
    A = np.column_stack([np.ones(len(idx)), g, i])
    out = {}
    for col in hist.columns:
        y = hist.loc[idx, col].values
        ok = np.isfinite(y)
        if ok.sum() < 48:
            continue
        Aw, yw, ww = A[ok], y[ok], w[ok]
        WA = Aw * ww[:, None]
        try:
            XtX = Aw.T @ WA
            beta = np.linalg.solve(XtX + 1e-6 * np.eye(3), Aw.T @ (ww * yw))
        except np.linalg.LinAlgError:
            continue
        resid = yw - Aw @ beta
        dof = max(ww.sum() - 3, 1.0)
        s2 = float((ww * resid ** 2).sum() / dof)
        try:
            cov = s2 * np.linalg.inv(XtX + 1e-6 * np.eye(3))
        except np.linalg.LinAlgError:
            continue
        se = np.sqrt(np.clip(np.diag(cov), 1e-12, None))
        # Contracción de cada pendiente hacia cero según su relación señal/ruido
        shrink = np.array([1.0,
                           beta[1] ** 2 / (beta[1] ** 2 + se[1] ** 2),
                           beta[2] ** 2 / (beta[2] ** 2 + se[2] ** 2)])
        out[col] = beta * shrink
    return out or None


def rotation(X: pd.DataFrame, phases: pd.Series, cls_map: dict,
             probs: pd.DataFrame | None = None, F: pd.DataFrame | None = None,
             min_train: int = 120) -> dict:
    """Cartera solo larga, siempre invertida al 100 %, sin apalancar ni cortos.
    La fase decide qué activos ocupan cada bloque y cuánto pesa cada bloque dentro
    de sus bandas. Se calculan los cuatro esquemas de reparto en paralelo sobre
    exactamente la misma selección, para que la comparación aísle el efecto del
    reparto y nada más.

    min_train=120, no 240: con historia desde 1970 y 240 meses de entrenamiento el
    backtest no arranca hasta 1990 y se pierde Volcker (1979-1982), el episodio de
    estanflación y desinflación forzada más severo del histórico — justo el tipo de
    tramo que más interesa ver atravesar a una cartera que rota por fase. El coste
    es que las estimaciones de los primeros años, con menos meses de referencia,
    son más ruidosas."""
    print("7. Rotación por fase (4 esquemas de reparto)…")
    common = X.dropna(how="all").index.intersection(phases.dropna().index)
    X = X.loc[common]
    ph = phases.loc[common]
    if len(common) < min_train + 60:
        return {}

    def _ew(frame, ref_date):
        """Pesos exponenciales por antigüedad respecto a la última fecha."""
        months = np.array([(ref_date.year - d.year) * 12 + (ref_date.month - d.month)
                           for d in frame.index], dtype=float)
        return pd.Series(0.5 ** (months / HALF_LIFE_M), index=frame.index)

    def _wmean(frame, w):
        ww = frame.notna().mul(w, axis=0)
        return frame.mul(w, axis=0).sum() / ww.sum().replace(0, np.nan)

    def centroid(hph, phase, upto):
        """Punto medio del plano (crecimiento, inflación) en el que vive la fase."""
        if F is None:
            return None
        m = hph[hph == phase].index.intersection(F.index)
        if len(m) < 6:
            return None
        return float(F.loc[m, "growth"].mean()), float(F.loc[m, "inflation"].mean())

    def factor_means(hist, hph, phase):
        """Rentabilidad esperada de cada activo en el centro de la fase, según la
        regresión sobre los dos factores. Usa toda la historia, no solo los meses
        de esa fase. Respaldo para cuando falta muestra directa de la fase — ver
        means() —, nunca la fuente principal: un modelo lineal de dos factores
        extrapola bien la tendencia media, pero no cosas como el comportamiento
        del oro, que no es lineal en crecimiento/inflación y que la propia
        matriz de evidencia (sección 6) muestra sin señal real fuera de
        Reflación. Usar la regresión como fuente principal recomendaba oro en
        fases donde la evidencia directa dice que no aporta nada."""
        b = factor_betas(hist, F) if F is not None else None
        c = centroid(hph, phase, hist.index[-1])
        if not b or c is None:
            return None
        g, i = c
        return pd.Series({k: v[0] + v[1] * g + v[2] * i for k, v in b.items()})

    def means(hist, hph, phase):
        """Ventaja esperada de cada activo EN ESTA FASE, relativa a su propia
        media incondicional (grand): cuánto mejor o peor rinde esta fase
        frente a lo que ese activo hace de media, contraída con la misma
        fórmula de James-Stein activo por activo que usa shrink() para la
        matriz de evidencia de la sección 6 — no el nivel absoluto.

        El nivel absoluto (grand + contracción, que es lo que devolvía una
        versión anterior) rompía la selección: casi cualquier sector de bolsa
        y el oro tienen media incondicional positiva a largo plazo, así que
        "puntúa positivo" casi nunca discriminaba nada (de ahí que renta
        variable tocara siempre el techo de 7) y, al comparar el nivel entre
        bloques, ganaba el bloque con mejor racha histórica general — el oro
        desde 2000, sin ninguna fase con señal real (rel_shrunk = 0.0 en las
        cuatro, ver sección 6) pero con una media incondicional del 12 % que
        competía de tú a tú con la renta variable EN TODAS LAS FASES por
        igual. Devolviendo la desviación respecto a la propia media (0 cuando
        no hay contracción, como en el oro), un activo solo cuenta como
        favorable cuando ESTA fase concreta le sienta mejor que su media —que
        es lo que hay que rotar— y dos activos solo compiten por sitio si los
        dos tienen de verdad algo que aportar en la fase, no porque uno de
        los dos rinda más en términos absolutos.
        """
        ref = hist.index[-1]
        grand = _wmean(hist, _ew(hist, ref))
        mu_p, se_p, n_p = {}, {}, {}
        for p in PHASES:
            sub = hist[hph == p]
            if sub.empty:
                continue
            mu_p[p] = _wmean(sub, _ew(sub, ref))
            n = sub.notna().sum()
            n_p[p] = n
            se_p[p] = sub.std() / np.sqrt(n.clip(lower=1))
        if phase not in mu_p or len(mu_p) < 2:
            fm = factor_means(hist, hph, phase)
            if fm is not None and fm.notna().sum() >= 5:
                return fm.reindex(hist.columns) - grand
            return mu_p.get(phase, grand) - grand
        M = pd.DataFrame(mu_p).T          # filas: fases con datos · columnas: activos
        SE2 = pd.DataFrame(se_p).T ** 2
        N = pd.DataFrame(n_p).T
        # tau2 por activo: dispersión de sus medias ENTRE FASES menos el ruido
        # medio de estimación. Igual que shrink(), aquí vectorizado por columna.
        tau2 = (M.var(axis=0, ddof=1) - SE2.mean(axis=0)).clip(lower=0.0)
        d = tau2 + SE2.loc[phase]
        w = (tau2 / d).where(d > 0, 0.0).fillna(0.0)
        # Sin muestra suficiente de ESTA fase para un activo, su media de fase
        # no se usa: se valora por su comportamiento general, es decir, 0 de
        # desviación — ni favorece ni penaliza.
        w = w.where(N.loc[phase] >= MIN_PHASE_OBS, 0.0)
        return w * (M.loc[phase] - grand)

    def ew_vol(hist):
        ref = hist.index[-1]
        w = _ew(hist, ref)
        m = _wmean(hist, w)
        dev2 = (hist.sub(m, axis=1) ** 2)
        ww = dev2.notna().mul(w, axis=0)
        return (dev2.mul(w, axis=0).sum() / ww.sum().replace(0, np.nan)) ** 0.5

    eq_c, bd_c = "Renta variable EE.UU. (mercado)", "Treasury 10 años"
    rets = {k: [] for k in SCHEMES}
    turn = {k: [] for k in SCHEMES}
    prev = {k: {} for k in SCHEMES}
    dates, held = [], []

    for k in range(min_train, len(common)):
        t = common[k]
        sig = ph.iloc[k - 1]
        hist, hph = X.iloc[:k], ph.iloc[:k]
        vol = ew_vol(hist)
        sub_sig = hist[hph == sig]
        raw_phase = (_wmean(sub_sig, _ew(sub_sig, hist.index[-1])) if not sub_sig.empty
                     else _wmean(hist, _ew(hist, hist.index[-1])))
        if probs is not None and t in probs.index:
            # Mezcla por probabilidad: cuando la clasificación es dudosa —y ahora
            # mismo lo es, con dos fases al 38 % y al 37 %— apostar el 100 % a la
            # ganadora tira información que ya tenemos calculada. Se ponderan las
            # rentabilidades esperadas de las cuatro fases por su probabilidad.
            pr = probs.loc[t]
            mu = None
            for phase in PHASES:
                w_p = float(pr.get(phase, 0.0))
                if w_p <= 0.01:
                    continue
                m_p = means(hist, hph, phase)
                mu = m_p * w_p if mu is None else mu.add(m_p * w_p, fill_value=0.0)
            if mu is None:
                mu = means(hist, hph, sig)
        else:
            mu = means(hist, hph, sig)
        avail = list(X.loc[t].dropna().index)
        picks, scores = {}, {}
        for name, (classes, lo, hi, n_min, n_max) in SLEEVES.items():
            picks[name], scores[name] = _sleeve_pick(
                mu, vol, raw_phase, avail, classes, cls_map, n_min, n_max)
        if not any(picks.values()):
            continue

        for sch in SCHEMES:
            inner = {name: _weights(top, vol, sch).to_dict()
                     for name, top in picks.items() if top}
            budgets = _sleeve_weights(scores)
            w_all = {}
            for name, w in inner.items():
                for c, wt in w.items():
                    w_all[c] = w_all.get(c, 0.0) + budgets[name] * float(wt)
            tot = sum(w_all.values())
            if tot <= 0:
                rets[sch].append(np.nan)
                turn[sch].append(0.0)
                continue
            w_all = {c: v / tot for c, v in w_all.items()}
            rets[sch].append(sum(w * float(X.loc[t, c]) for c, w in w_all.items()))
            keys = set(w_all) | set(prev[sch])
            turn[sch].append(sum(abs(w_all.get(c, 0) - prev[sch].get(c, 0))
                                 for c in keys) / 2)
            prev[sch] = w_all
        dates.append(t)
        held.append(sig)

    eq, bd = X.get(eq_c), X.get(bd_c)
    # La cartera es 100% renta variable (+ oro): la referencia primaria es la
    # propia renta variable EE.UU., no un 60/40 que esta cartera no tiene. El
    # 60/40 se conserva aparte, solo como contexto para quien lo quiera.
    bench = eq.reindex(dates) if eq is not None else None
    bench_6040 = (0.6 * eq + 0.4 * bd).reindex(dates) if eq is not None and bd is not None else None
    hp = pd.Series(held, index=dates)
    bench_annual = _annual(bench.dropna()) if bench is not None else {}

    vol_all = ew_vol(X)
    out_schemes = {}
    for sch, label in SCHEMES.items():
        R = pd.Series(rets[sch], index=dates).dropna()
        by_phase = {}
        for phase in PHASES:
            m = (hp == phase).reindex(R.index).fillna(False)
            if m.sum() < 12:
                continue
            e = {"n": int(m.sum()), "ann": round(float(R[m].mean() * 12), 2)}
            if bench is not None:
                e["bench_ann"] = round(float(bench.reindex(R.index)[m].mean() * 12), 2)
                e["edge"] = round(e["ann"] - e["bench_ann"], 2)
            by_phase[phase] = e

        playbook, mix = {}, {}
        for phase in PHASES:
            mu = means(X, ph, phase)
            sub_p = X[ph == phase]
            raw_phase = (_wmean(sub_p, _ew(sub_p, X.index[-1])) if not sub_p.empty
                         else _wmean(X, _ew(X, X.index[-1])))
            # Ken French publica con un mes de retraso: exigir dato en el último
            # mes dejaba fuera todos los sectores y el bloque salía vacío.
            avail = list(X.columns[X.tail(4).notna().any()])
            picks, scores = {}, {}
            for sl, (classes, lo, hi, n_min, n_max) in SLEEVES.items():
                picks[sl], scores[sl] = _sleeve_pick(
                    mu, vol_all, raw_phase, avail, classes, cls_map, n_min, n_max)
            inner_pb = {sl: _weights(top, vol_all, sch).to_dict()
                        for sl, top in picks.items() if top}
            budgets = _sleeve_weights(scores)
            rows = []
            for sl, w in inner_pb.items():
                for c in picks[sl]:
                    rows.append({"sleeve": sl, "name": c,
                                 "weight": round(budgets[sl] * float(w[c]) * 100, 1),
                                 "class": cls_map.get(c, "")})
            playbook[phase] = [r for r in rows if r["weight"] >= 0.3]
            mix[phase] = {k: round(v * 100, 1) for k, v in budgets.items()}

        ann = _annual(R)
        realized = float(R.std() * math.sqrt(12))
        bench_v = float(bench.dropna().std() * math.sqrt(12)) if bench is not None else None
        out_schemes[sch] = {
            "vol_check": {
                "cartera": round(realized, 2),
                "objetivo_mercado": round(bench_v, 2) if bench_v else None,
                "desvio": round(realized - bench_v, 2) if bench_v else None,
            },
            "label": label,
            "portfolio": perf(R),
            "by_phase": by_phase,
            "playbook": playbook,
            "sleeve_mix": mix,
            "annual": ann,
            "turnover": round(float(np.mean(turn[sch]) * 100), 1),
            "wins_years": sum(1 for y, v in ann.items()
                              if y in bench_annual and v > bench_annual[y]),
            "n_years": len([y for y in ann if y in bench_annual]),
            "curve": [{"d": d.strftime("%Y-%m"), "s": round(float(R.loc[d]), 4),
                       "b": (round(float(bench.loc[d]), 4)
                             if bench is not None and d in bench.index
                             and bench.loc[d] == bench.loc[d] else None)}
                      for d in R.index][-560:],
        }

    print("  ✓ " + " · ".join(
        f"{SCHEMES[k]}: Sharpe {out_schemes[k]['portfolio'].get('sharpe')}"
        for k in out_schemes))
    # El esquema por defecto es el de mayor CAGR realizado en el propio
    # walk-forward, no uno fijado a mano: la web deja elegir los cuatro,
    # pero lo que se muestra sin tocar nada tiene que ser el que de verdad
    # ha rentado más, no una preferencia de diseño.
    best_scheme = max(out_schemes, key=lambda k: out_schemes[k]["portfolio"].get("cagr", -1e9))
    return {"schemes": out_schemes, "default": best_scheme,
            "bench_100eq": perf(bench) if bench is not None else {},
            "bench_6040": perf(bench_6040) if bench_6040 is not None else {},
            "bench_annual": bench_annual,
            "bands": {k: [round(v[1] * 100), round(v[2] * 100)]
                      for k, v in SLEEVES.items()}}



# ======================================================================================
# 7c. Laboratorio: qué combinaciones funcionaron y si siguieron funcionando
# ======================================================================================

from itertools import combinations  # noqa: E402


def _spearman(a, b) -> float:
    a, b = np.asarray(a, float), np.asarray(b, float)
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < 8:
        return float("nan")
    ra = pd.Series(a[ok]).rank().values
    rb = pd.Series(b[ok]).rank().values
    ra, rb = ra - ra.mean(), rb - rb.mean()
    d = math.sqrt(float((ra @ ra) * (rb @ rb)))
    return float((ra @ rb) / d) if d > 0 else float("nan")


LAB_MIN_HALF = 12   # meses mínimos en cada mitad para que algo sea evaluable
LAB_MIN_TOTAL = 24  # meses mínimos de la fase para entrar en el universo


def laboratory(X: pd.DataFrame, phases: pd.Series, cls_map: dict,
               k_pick: int = 5, max_universe: int = 18) -> dict:
    """Para cada fase, evalúa todas las combinaciones posibles de k activos dentro
    de cada bloque y comprueba si la que mandaba en la primera mitad seguía
    mandando en la segunda.

    k es fijo a propósito, aunque la cartera real (SLEEVES) elige un número
    variable de sectores según cuántos puntúen positivo en la fase: evaluar
    "todas las combinaciones posibles" solo es tratable con un tamaño fijo, y
    5 es el valor típico dentro del rango 3-7 que usa la cartera real. Esta
    sección responde una pregunta distinta y más simple —¿lo que ganaba antes
    seguía ganando después, a tamaño de combinación constante?—, no reproduce
    el algoritmo de selección de la cartera.

    Ningún activo queda fuera por tener menos historia. La partición en mitades no
    usa una fecha común —que dejaría a un ETF de 2007 sin primera mitad— sino la
    MEDIANA DE SU PROPIA MUESTRA: cada activo y cada combinación se parte por la
    mitad de los meses en que existe. A cambio, las mitades ya no cubren las mismas
    fechas entre unos y otros, así que se publican los meses usados y el tramo
    temporal de cada uno para que la comparación se lea con esa cautela.
    """
    print("8. Laboratorio de combinaciones…")
    out = {}
    sleeve_defs = {
        "Renta variable": {"Renta variable"},
        "Oro": {"Oro"},
    }

    def halves(series):
        """Parte una serie por la mediana de SUS PROPIOS meses disponibles."""
        s2 = series.dropna()
        if s2.size < 2 * LAB_MIN_HALF:
            return None, None
        cut = s2.index[s2.size // 2]
        return s2[s2.index <= cut], s2[s2.index > cut]

    for phase in PHASES:
        months = phases[phases == phase].index.intersection(X.index)
        if len(months) < 2 * LAB_MIN_HALF:
            out[phase] = {"skipped": f"solo {len(months)} meses de esta fase"}
            continue
        Xi = X.loc[months]
        phase_out = {"n": len(months), "sleeves": {}}

        for sleeve, classes in sleeve_defs.items():
            cand = [c for c in Xi.columns
                    if cls_map.get(c) in classes and c not in NOT_SELECTABLE
                    and Xi[c].notna().sum() >= LAB_MIN_TOTAL]
            if len(cand) > max_universe:
                cov = Xi[cand].notna().sum().sort_values(ascending=False)
                cand = list(cov.head(max_universe).index)
            k = min(k_pick, max(2, len(cand) - 1))
            if len(cand) < k + 1:
                continue

            # Activo a activo, cada uno partido por su propia mediana
            arows, a1, a2 = [], [], []
            for c in cand:
                h1, h2 = halves(Xi[c])
                if h1 is None:
                    arows.append({"name": c, "h1": None, "h2": None,
                                  "n": int(Xi[c].notna().sum()),
                                  "span": None, "thin": True})
                    continue
                v1, v2 = float(h1.mean() * 12), float(h2.mean() * 12)
                a1.append(v1)
                a2.append(v2)
                arows.append({"name": c, "h1": round(v1, 2), "h2": round(v2, 2),
                              "n": int(h1.size + h2.size),
                              "span": f"{h1.index[0].year}-{h2.index[-1].year}",
                              "thin": h1.size < LAB_MIN_HALF * 1.5})

            combos = list(combinations(sorted(cand), k))
            r1, r2, nn, spans, keep = [], [], [], [], []
            for combo in combos:
                port = Xi[list(combo)].dropna().mean(axis=1)
                h1, h2 = halves(port)
                if h1 is None:
                    continue
                r1.append(float(h1.mean() * 12))
                r2.append(float(h2.mean() * 12))
                nn.append(int(h1.size + h2.size))
                spans.append(f"{h1.index[0].year}-{h2.index[-1].year}")
                keep.append(combo)
            if len(keep) < 10:
                phase_out["sleeves"][sleeve] = {
                    "universe": cand, "k": k, "n_combos": 0,
                    "note": ("los activos de este bloque no acumulan suficientes meses "
                             "en esta fase: la mayoría empieza en los años 2000 y esta "
                             "fase es sobre todo anterior"),
                    "assets_h1_h2": arows, "rank_ic": None, "asset_ic": None,
                }
                continue
            r1, r2 = np.array(r1), np.array(r2)
            ic = _spearman(r1, r2)
            order = np.argsort(-r1)
            top = order[:8]
            phase_out["sleeves"][sleeve] = {
                "universe": cand, "k": k, "n_combos": len(keep),
                "n_discarded": len(combos) - len(keep),
                "rank_ic": round(ic, 3) if ic == ic else None,
                "all_h2_mean": round(float(np.nanmean(r2)), 2),
                "all_h2_sd": round(float(np.nanstd(r2)), 2),
                "best_h1_pct_in_h2": round(float((r2 < r2[order[0]]).mean()), 3),
                "top": [{"assets": list(keep[i]), "h1": round(float(r1[i]), 2),
                         "h2": round(float(r2[i]), 2), "n": nn[i], "span": spans[i],
                         "pct_h2": round(float((r2 < r2[i]).mean()), 3)} for i in top],
                "assets_h1_h2": arows,
                "asset_ic": (round(_spearman(a1, a2), 3) if len(a1) > 7 else None),
            }
        out[phase] = phase_out
        eq = out[phase]["sleeves"].get("Renta variable", {})
        print(f"  · {phase:<20} {len(months):>4} meses · "
              f"persistencia {eq.get('rank_ic')} · "
              f"universos " + "/".join(str(len(v.get('universe', [])))
                                       for v in out[phase]["sleeves"].values()))
    return out


# ======================================================================================
# 8. Validación
# ======================================================================================

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
    assets, astats = conditional_stats(X, phases, ameta)
    bt = backtest(X, phases)
    cls_map = {k: v.get("class", "Otros") for k, v in ameta.items()}
    # Probabilidad de cada fase en cada mes, con la misma fórmula que el panel usa
    # para el mes actual. Se desplaza un mes: en t solo se conoce la de t-1.
    prob_rows = {}
    for d, gg, ii in zip(F.index, F["growth"], F["inflation"]):
        prob_rows[d] = phase_probs(float(gg), float(ii), sg, si)
    probs_df = pd.DataFrame(prob_rows).T.shift(1)
    rot = rotation(X, phases, cls_map, probs_df, F)
    lab = laboratory(X, phases, cls_map)
    val = validation(df, F, phases)
    rec = recession_model(df, F.index)

    p1, p2 = rank[0][0], rank[1][0]
    # Restringido a la clase invertible de la cartera (renta variable + oro): el
    # consenso alimenta directamente "qué comprar ahora" y no tiene sentido que
    # sugiera renta fija u otras clases que la cartera de rotación ya no toca.
    consensus = []
    for a in assets:
        if a["class"] not in {c for cls in SLEEVES.values() for c in cls[0]}:
            continue
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
        "backtest": bt, "rotation": rot, "lab": lab,
        "validation": val,
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
