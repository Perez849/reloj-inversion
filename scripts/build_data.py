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
HTTP_TIMEOUT = 60
RETRIES = 4
HORIZON_M = 3
MIN_MONTHS = 60

WARNINGS: list[str] = []
ASSET_LOG: list[dict] = []


def warn(msg: str) -> None:
    print(f"  ! {msg}")
    WARNINGS.append(msg)


def http_get(url: str, tries: int = RETRIES, expect: str | None = None):
    """Descarga con reintentos. `expect` es un texto que debe aparecer al principio
    del cuerpo: algunas fuentes devuelven 200 con un mensaje de error, y sin esta
    comprobación el fallo pasaría desapercibido."""
    headers = {"User-Agent": "Mozilla/5.0 (compatible; investment-clock/2.0)"}
    last = "sin intentos"
    for attempt in range(tries):
        try:
            r = requests.get(url, timeout=HTTP_TIMEOUT, headers=headers)
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
    Series("BAMLH0A0HYM2", "Diferencial High Yield", "leading", "lvl", 0, invert=True),
    Series("PERMIT", "Permisos de construcción", "leading", "yoy", 1),
    Series("USSLIND", "Índice adelantado (Philadelphia Fed)", "leading", "lvl", 2),
    Series("VIXCLS", "VIX", "leading", "lvl", 0, invert=True),
    Series("AWHMAN", "Horas semanales manufactura", "leading", "d12", 1),

    Series("T10Y3M", "Curva 10a-3m", "standalone", "lvl", 0,
           note="Anticipa 12-18 meses: se muestra aparte y alimenta el modelo de recesión"),
    Series("T10Y2Y", "Curva 10a-2a", "standalone", "lvl", 0),
]

FRED_EXTRA = ["USREC", "TB3MS", "DGS2", "DGS10", "DGS30", "UNRATE", "FEDFUNDS",
              "BAA", "AAA", "DFII10"]

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

def fred_series(series_id: str):
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={START}"
    r = http_get(url)
    if isinstance(r, tuple):
        return None, f"descarga: {r[1]}"
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
        return None, f"parseo: {exc}"


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
    print("1. Descargando FRED…")
    raw, meta = {}, {}
    for sid in [s.fred_id for s in SERIES] + FRED_EXTRA:
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


def expanding_z(s: pd.Series, min_periods: int = 120) -> pd.Series:
    mu = s.expanding(min_periods=min_periods).mean()
    sd = s.expanding(min_periods=min_periods).std()
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
            warn(f"{spec.fred_id}: sin z-score utilizable (historia insuficiente)")
            continue
        zs[spec.fred_id] = z
        info[spec.fred_id] = {
            "id": spec.fred_id, "name": spec.name, "block": spec.block,
            "transform": spec.transform, "lag_m": spec.lag_m,
            "invert": spec.invert, "note": spec.note,
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

FRED_TR = {
    "BAMLCC0A0CMTRIV": ("Crédito Investment Grade", "Renta fija"),
    "BAMLHYH0A0HYM2TRIV": ("Crédito High Yield", "Renta fija"),
    "BAMLEMCBPITRIV": ("Deuda emergente corporativa", "Renta fija"),
    "BAMLCC1A013YTRIV": ("Crédito IG 1-3 años", "Renta fija"),
    "BAMLCC8A015PYTRIV": ("Crédito IG 15+ años", "Renta fija"),
}

FRED_PX = {
    "GOLDAMGBD228NLBM": ("Oro", "Real / alternativos", "London fix"),
    "WTISPLC": ("Petróleo WTI (spot)", "Real / alternativos", "mensual desde 1946"),
    "PPIACO": ("Cesta de producción (PPI)", "Real / alternativos",
               "proxy de precios, no invertible directamente"),
    "WILLREITIND": ("Inmobiliario (REITs)", "Real / alternativos", "Wilshire REIT"),
    "WILL5000IND": ("Renta variable EE.UU. (Wilshire)", "Renta variable", ""),
}

FRED_YIELD = {
    "DGS2": (1.9, 4.5, "Treasury 2 años", "Renta fija"),
    "DGS10": (8.2, 80.0, "Treasury 10 años", "Renta fija"),
    "DGS30": (18.5, 450.0, "Treasury 30 años", "Renta fija"),
    "BAA": (7.5, 70.0, "Crédito Baa (aprox.)", "Renta fija"),
    "AAA": (8.0, 80.0, "Crédito Aaa (aprox.)", "Renta fija"),
    "DFII10": (8.5, 85.0, "TIPS 10 años (aprox.)", "Renta fija"),
}

STOOQ = {
    "xauusd": ("Oro (spot Stooq)", "Real / alternativos"),
    "^spgsci": ("Materias primas (GSCI)", "Real / alternativos"),
    "vnq.us": ("REITs (VNQ)", "Real / alternativos"),
    "eem.us": ("Renta variable emergente", "Renta variable"),
    "efa.us": ("Renta variable internacional", "Renta variable"),
    "iwm.us": ("Small caps", "Estilo"),
    "tip.us": ("TIPS (TIP)", "Renta fija"),
    "mub.us": ("Municipales", "Renta fija"),
    "mbb.us": ("Titulizaciones hipotecarias", "Renta fija"),
}


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
                     tries=2, expect="Date")
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
        add("Prima Value (HML)", ff["HML"], "Estilo", "Ken French")
        add("Prima Tamaño (SMB)", ff["SMB"], "Estilo", "Ken French")
    else:
        warn(f"Ken French factores: {err}")

    ind, err = french_zip(FRENCH_BASE + "12_Industry_Portfolios_CSV.zip", "industrias")
    if ind is not None:
        for col, lab in FRENCH_IND.items():
            if col in ind.columns:
                add(lab, ind[col], "Renta variable", "Ken French")
    else:
        warn(f"Ken French industrias: {err}")

    mom, err = french_zip(FRENCH_BASE + "F-F_Momentum_Factor_CSV.zip", "momentum")
    if mom is not None:
        c = [x for x in mom.columns if "Mom" in x]
        if c:
            add("Prima Momentum", mom[c[0]], "Estilo", "Ken French")

    for sid, (lab, cls) in FRED_TR.items():
        s, e = fred_series(sid)
        if s is None:
            add(lab, None, cls, f"ICE BofA / {sid}", err=e)
        else:
            add(lab, to_monthly(s, how="last").pct_change() * 100.0, cls,
                f"ICE BofA / {sid}")

    for sid, (lab, cls, note) in FRED_PX.items():
        s, e = fred_series(sid)
        if s is None:
            add(lab, None, cls, f"FRED / {sid}", note, err=e)
        else:
            add(lab, to_monthly(s, how="last").pct_change() * 100.0, cls,
                f"FRED / {sid}", note)

    for sid, (dur, cvx, lab, cls) in FRED_YIELD.items():
        if sid not in df.columns:
            add(lab, None, cls, f"FRED / {sid}", err="no descargado")
        else:
            add(lab, yield_to_return(df[sid], dur, cvx), cls, f"FRED / {sid}",
                f"aproximación por duración {dur} y convexidad {cvx}")

    if "TB3MS" in df.columns:
        add("Liquidez (letras 3m)", (df["TB3MS"] / 12.0).dropna(), "Liquidez",
            "FRED / TB3MS")

    for tick, (lab, cls) in STOOQ.items():
        s, e = stooq_monthly(tick)
        add(lab, s, cls, f"Stooq / {tick}", err=e if s is None else None)

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
    return {"cagr": round(float(cagr * 100), 2), "vol": round(float(vol * 100), 2),
            "sharpe": round(float(cagr / vol), 2) if vol > 0 else None,
            "maxdd": round(float((curve / curve.cummax() - 1).min() * 100), 2),
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

    lg, sp, ins, dates = [], [], [], []
    full = {p: means(X, ph, p) for p in PHASES}
    for k in range(min_train, len(common)):
        t = common[k]
        sig = ph.iloc[k - 1]
        mu = means(X.iloc[:k], ph.iloc[:k], sig)
        avail = X.loc[t].dropna().index
        rank = mu.reindex(avail).dropna().sort_values(ascending=False)
        if rank.size < 2 * top_k:
            continue
        top, bot = rank.head(top_k).index, rank.tail(top_k).index
        lg.append(float(X.loc[t, top].mean()))
        sp.append(float(X.loc[t, top].mean() - X.loc[t, bot].mean()))
        rk = full[sig].reindex(avail).dropna().sort_values(ascending=False)
        ins.append(float(X.loc[t, rk.head(top_k).index].mean()))
        dates.append(t)

    L = pd.Series(lg, index=dates)
    S = pd.Series(sp, index=dates)
    I = pd.Series(ins, index=dates)
    eq = X.get("Renta variable EE.UU. (mercado)")
    bd = X.get("Treasury 10 años")
    bench = (0.6 * eq + 0.4 * bd).reindex(dates) if eq is not None and bd is not None else None
    scaled = L * float(bench.std() / L.std()) if bench is not None and L.std() > 0 else None

    curve = [{"d": d.strftime("%Y-%m"), "s": round(float(L.loc[d]), 4),
              "p": round(float(S.loc[d]), 4),
              "b": (round(float(bench.loc[d]), 4)
                    if bench is not None and d in bench.index
                    and bench.loc[d] == bench.loc[d] else None)} for d in dates]

    print(f"  ✓ {len(L)} meses fuera de muestra desde {dates[0].date()}")
    return {"long": perf(L), "spread": perf(S),
            "scaled": perf(scaled) if scaled is not None else {},
            "in_sample": perf(I),
            "bench_6040": perf(bench) if bench is not None else {},
            "equal_weight": perf(X.reindex(dates).mean(axis=1)),
            "top_k": top_k, "curve": curve[-460:]}


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
        "backtest": bt, "validation": val,
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
