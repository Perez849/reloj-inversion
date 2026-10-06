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
DEBUG_TAILS: dict = {}


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


# Una serie cuya última observación queda a más de seis meses del final del panel
# está descontinuada o rota (caso real: USSLIND, último dato en febrero de 2020).
# Dejarla dentro del PCA hace que la definición del factor cambie en silencio en el
# punto en que desaparece, y le da carga al factor con un valor que ya no existe.
STALE_MAX_M = 6

# Borde irregular. Las series macro se publican con retrasos distintos, así que en
# el último mes del panel suelen estar al día solo unas pocas. El factor se calcula
# como media ponderada de las series DISPONIBLES, de modo que con una sola serie
# viva (octubre de 2026: solo las nóminas, 9% del peso de crecimiento) el último
# punto es esa serie y nada más: el crecimiento saltó de -0,04 a -1,06 en un mes sin
# que ningún otro dato cambiara. Se hace lo estándar en nowcasting: arrastrar el
# último z conocido de cada serie hasta TAIL_FILL_M meses y exigir que, tras eso,
# la cobertura de peso del bloque sea al menos MIN_TAIL_COVERAGE. Las filas finales
# que no lleguen se descartan y la lectura "actual" retrocede al último mes fiable.
TAIL_FILL_M = 2
MIN_TAIL_COVERAGE = 0.80
FULL_FRESH_COVERAGE = 0.90   # "mes completo": casi todo el peso con dato nuevo


def fill_tail(X: pd.DataFrame, limit: int = TAIL_FILL_M) -> pd.DataFrame:
    """Arrastra el último valor SOLO por el final de cada columna, hasta `limit`
    meses. No toca huecos interiores ni alarga series que terminaron hace tiempo."""
    out = X.copy()
    for c in out.columns:
        last = out[c].last_valid_index()
        if last is None:
            continue
        pos = out.index.get_loc(last)
        tail = out.index[pos + 1: pos + 1 + limit]
        if len(tail):
            out.loc[tail, c] = out.at[last, c]
    return out


# ======================================================================================
# 3b. Ampliación del panel: más series candidatas para el PCA
# ======================================================================================
# Pregunta: ¿cuánta de la variación conjunta de cada bloque recoge su primer
# componente, y mejora con más series? Se descargan candidatas con historia larga y
# se eligen por selección hacia delante: entra la que más sube la varianza explicada
# del primer componente del bloque, siempre que (a) tenga signo y correlación
# coherentes con el factor ya existente (|r| >= 0,30; si r < 0 se invierte) y (b) la
# mejora sea de al menos MIN_GAIN. Es selección sobre una MEDIDA DE AJUSTE DEL
# FACTOR, no sobre rentabilidades de activos, así que no mete sesgo de anticipación
# en las carteras; sí es selección con la misma muestra, y se declara en el payload.
CAND_MIN_OBS = 360
CAND_MIN_ABS_R = 0.30
CAND_MIN_GAIN = 0.005
CAND_MAX_PER_BLOCK = 8

CANDIDATES: list[Series] = [
    # crecimiento
    Series("USPRIV", "Nóminas privadas", "growth", "ratio_yoy", 1),
    Series("UNRATE", "Tasa de paro", "growth", "d12", 1, invert=True),
    Series("CCSA", "Peticiones continuadas", "growth", "yoy", 0, invert=True),
    Series("DSPIC96", "Renta disponible real", "growth", "yoy", 1),
    Series("PCEC96", "Consumo real", "growth", "yoy", 2),
    Series("TOTALSA", "Ventas de vehículos", "growth", "yoy", 1),
    Series("DGORDER", "Pedidos de bienes duraderos", "growth", "yoy", 2),
    Series("AMTMNO", "Pedidos nuevos manufactura", "growth", "yoy", 2),
    Series("CUMFNS", "Capacidad en manufactura", "growth", "d12", 1),
    Series("MANEMP", "Empleo en manufactura", "growth", "yoy", 1),
    Series("USCONS", "Empleo en construcción", "growth", "yoy", 1),
    Series("IPMAN", "Producción manufacturera", "growth", "yoy", 1),
    Series("IPCONGD", "Producción de bienes de consumo", "growth", "yoy", 1),
    Series("RSAFS", "Ventas minoristas nominales", "growth", "yoy", 1),
    Series("CE16OV", "Empleo (encuesta de hogares)", "growth", "yoy", 1),
    # inflación
    Series("PCEPI", "PCE general", "inflation", "yoy", 2),
    Series("CPIUFDSL", "IPC alimentos", "inflation", "yoy", 1),
    Series("CUSR0000SAS", "IPC servicios", "inflation", "yoy", 1),
    Series("CUSR0000SAH1", "IPC vivienda", "inflation", "yoy", 1),
    Series("CPIENGSL", "IPC energía", "inflation", "yoy", 1),
    Series("CPIMEDSL", "IPC sanidad", "inflation", "yoy", 1),
    Series("MICH", "Expectativas de inflación (Michigan)", "inflation", "lvl", 0),
    Series("GASREGW", "Gasolina", "inflation", "yoy_log", 0),
    Series("IR", "Precios de importación", "inflation", "yoy", 1),
    Series("WPSFD49207", "Precios de producción, demanda final", "inflation", "yoy", 1),
    # adelantados
    Series("M2SL", "Dinero M2", "leading", "yoy", 1),
    Series("BUSLOANS", "Préstamos comerciales", "leading", "yoy", 1),
    Series("STLFSI4", "Estrés financiero (St. Louis)", "leading", "lvl", 0, invert=True),
    Series("NEWORDER", "Pedidos de bienes de capital", "leading", "yoy", 2),
    Series("T10Y3M", "Curva 10a-3m (como adelantado)", "leading", "lvl", 0),
    Series("MORTGAGE30US", "Hipoteca a 30 años", "leading", "d12", 0, invert=True),
    Series("AWOTMAN", "Horas extra manufactura", "leading", "lvl", 1),
]


def fetch_candidates(df: pd.DataFrame):
    """Descarga las candidatas que aún no están en el panel. Si una falla, se avisa y
    se sigue (nombres de series no verificables desde el entorno de desarrollo)."""
    print("1b. Descargando series candidatas para ampliar el PCA…")
    add, meta = {}, {}
    for spec in CANDIDATES:
        sid = spec.fred_id
        if sid in df.columns:
            continue
        s, err = fred_series(sid)
        if s is None:
            warn(f"candidata {sid}: {str(err)[:80]}")
            continue
        m = to_monthly(s)
        m.index = m.index.to_period("M").to_timestamp("M")
        add[sid] = m
        meta[sid] = {"last_obs": str(s.index[-1].date())}
    if add:
        df = df.join(pd.DataFrame(add), how="outer")
    print(f"  ✓ {len(add)} candidatas descargadas")
    return df, meta


def _patch_recent_holes(raw: pd.Series, transform_kind: str) -> pd.Series:
    """Interpola huecos interiores de hasta 2 meses SOLO en los últimos 36 meses
    (cierre del Gobierno de otoño de 2025). En la historia lejana no se toca: hay
    series trimestrales o irregulares antiguas (p. ej. UMCSENT antes de 1978) y
    rellenarlas cambiaría las fases pasadas y, con ellas, el backtest."""
    if transform_kind == "lvl":
        return raw
    cut = raw.index[-1] - pd.DateOffset(months=36)
    filled = raw.interpolate(limit=2, limit_area="inside")
    return raw.where(raw.index <= cut, filled)


def _z_spec(spec: Series, raw: pd.Series) -> pd.Series:
    raw = _patch_recent_holes(raw, spec.transform)
    x = transform(raw, spec.transform)
    if spec.invert:
        x = -x
    return rolling_z(x).shift(spec.lag_m)


def select_candidates(df: pd.DataFrame):
    """Devuelve (informe, {bloque: [Series elegidas]}). NO toca SERIES: la decisión de
    adoptarlas se toma después con el backtest (ver choose_pca_variant)."""
    print("2a. Selección de series candidatas (varianza explicada del PC1)…")
    report = {"blocks": {}, "params": {"min_abs_r": CAND_MIN_ABS_R, "min_gain": CAND_MIN_GAIN,
                                       "min_obs": CAND_MIN_OBS, "max_per_block": CAND_MAX_PER_BLOCK}}
    panel_end = df.index[-1]
    base_specs = [sp for sp in SERIES if sp.fred_id in df.columns]
    picks_by_block: dict[str, list] = {}
    for block in ("growth", "inflation", "leading"):
        base = [sp for sp in base_specs if sp.block == block]
        zb = {}
        for sp in base:
            lv = df[sp.fred_id].last_valid_index()
            if lv is not None and ((panel_end.year - lv.year) * 12 + panel_end.month - lv.month) > STALE_MAX_M:
                continue
            zb[sp.fred_id] = _z_spec(sp, df[sp.fred_id])
        if len(zb) < 3:
            continue
        Zb = pd.DataFrame(zb)
        f0, d0, _, _ = first_pc(Zb)
        var0 = d0["explained_var"]
        pool = {}
        rejected = []
        for sp in [c for c in CANDIDATES if c.block == block and c.fred_id in df.columns]:
            lv = df[sp.fred_id].last_valid_index()
            if lv is None or ((panel_end.year - lv.year) * 12 + panel_end.month - lv.month) > STALE_MAX_M:
                rejected.append({"id": sp.fred_id, "why": "sin dato reciente"})
                continue
            z = _z_spec(sp, df[sp.fred_id])
            if int(z.notna().sum()) < CAND_MIN_OBS:
                rejected.append({"id": sp.fred_id, "why": f"historia corta ({int(z.notna().sum())} meses)"})
                continue
            r = z.corr(f0.reindex(z.index))
            if r != r or abs(r) < CAND_MIN_ABS_R:
                rejected.append({"id": sp.fred_id, "why": f"correlación baja con el factor ({r:+.2f})"})
                continue
            if r < 0:
                sp = Series(sp.fred_id, sp.name, sp.block, sp.transform, sp.lag_m,
                            not sp.invert, sp.note)
                z = -z
            pool[sp.fred_id] = (sp, z, float(abs(r)))
        cur = Zb.copy()
        cur_var = var0
        picked = []
        while pool and len(picked) < CAND_MAX_PER_BLOCK:
            best = None
            for sid, (sp, z, r) in pool.items():
                try:
                    _, dd, _, _ = first_pc(pd.concat([cur, z.rename(sid)], axis=1))
                except Exception:
                    continue
                v = dd["explained_var"]
                if best is None or v > best[1]:
                    best = (sid, v)
            if best is None or best[1] - cur_var < CAND_MIN_GAIN:
                break
            sid = best[0]
            sp, z, r = pool.pop(sid)
            cur = pd.concat([cur, z.rename(sid)], axis=1)
            picked.append({"id": sid, "name": sp.name, "gain_pp": round((best[1] - cur_var) * 100, 1),
                           "r": round(r, 2), "invert": sp.invert})
            picks_by_block.setdefault(block, []).append(sp)
            cur_var = best[1]
        for sid, (sp, z, r) in pool.items():
            rejected.append({"id": sid, "why": "no mejora la varianza explicada"})
        report["blocks"][block] = {
            "n_base": len(zb), "var_base": round(var0, 3), "var_final": round(cur_var, 3),
            "added": picked, "rejected": rejected,
        }
        print(f"  ✓ {block:<10} {var0:.1%} → {cur_var:.1%} con {len(picked)} series nuevas")
    return report, picks_by_block


def build_blocks(df: pd.DataFrame):
    print("2. Transformando y estandarizando…")
    zs, info = {}, {}
    panel_end = df.index[-1]
    for spec in SERIES:
        if spec.fred_id not in df.columns:
            warn(f"serie ausente del panel: {spec.fred_id} ({spec.name})")
            continue
        lv = df[spec.fred_id].last_valid_index()
        if lv is not None:
            gap = (panel_end.year - lv.year) * 12 + (panel_end.month - lv.month)
            if gap > STALE_MAX_M:
                warn(f"{spec.fred_id} ({spec.name}) excluida del PCA: última observación "
                     f"{lv.strftime('%Y-%m')}, {gap} meses antes del final del panel")
                continue
        raw = df[spec.fred_id]
        # Huecos interiores de publicación (p. ej. el IPC de octubre de 2025, que no
        # se publicó por el cierre del Gobierno): se interpolan hasta 2 meses seguidos.
        # Sin esto, un solo mes ausente deja sin valor la transformación interanual.
        raw = _patch_recent_holes(raw, spec.transform)
        x = transform(raw, spec.transform)
        if spec.fred_id in ("CPIAUCSL", "RRSFS", "CPILFESL"):
            DEBUG_TAILS[spec.fred_id] = {
                "raw": {d.strftime("%Y-%m-%d"): (None if v != v else round(float(v), 3))
                        for d, v in df[spec.fred_id].iloc[-16:].items()},
                "x": {d.strftime("%Y-%m"): (None if v != v else round(float(v), 3))
                      for d, v in x.iloc[-16:].items()}}
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

    # Proyección con arrastre del final (ver TAIL_FILL_M). Los pesos W salen de la
    # muestra con datos reales; el arrastre solo afecta a cómo se evalúa el borde.
    Xp = fill_tail(X)
    total = float(W.abs().sum())
    num = Xp.mul(W, axis=1).sum(axis=1, min_count=1)
    den = Xp.notna().mul(W.abs(), axis=1).sum(axis=1)
    cov_filled = den / total
    cov_fresh = X.notna().mul(W.abs(), axis=1).sum(axis=1) / total
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
    }, cov_filled.reindex(f.index), cov_fresh.reindex(f.index)


def build_factors(Z: pd.DataFrame):
    print("3. Extrayendo factores (PCA)…")
    out, diag, cov_f, cov_r = {}, {}, {}, {}
    tail_info = {c: (Z[c].last_valid_index().strftime("%Y-%m") if Z[c].last_valid_index() is not None else None)
                 for c in Z.columns}
    for block in ("growth", "inflation", "leading"):
        cols = [s.fred_id for s in SERIES if s.block == block and s.fred_id in Z.columns]
        if len(cols) < 2:
            warn(f"bloque {block} con muy pocas series")
            continue
        f, d, cf, cr = first_pc(Z[cols])
        out[block], diag[block] = f, d
        cov_f[block], cov_r[block] = cf, cr
        print(f"  ✓ {block:<10} {len(cols)} series · varianza {d['explained_var']:.0%}"
              f" · coherencia {d['coherence']:+.2f}")
        if d["explained_var"] < 0.40:
            warn(f"bloque {block}: el primer componente solo explica "
                 f"{d['explained_var']:.0%} de la varianza")
    F = pd.DataFrame(out).dropna(how="all")

    # Recorte del borde: se descartan las filas finales en que los dos ejes que
    # deciden la fase (crecimiento e inflación) no tienen cobertura suficiente.
    dropped = 0
    while len(F) > 1:
        d0 = F.index[-1]
        cg = float(cov_f["growth"].get(d0, 0.0)) if "growth" in cov_f else 0.0
        ci = float(cov_f["inflation"].get(d0, 0.0)) if "inflation" in cov_f else 0.0
        if min(cg, ci) >= MIN_TAIL_COVERAGE:
            break
        F = F.iloc[:-1]
        dropped += 1
    if dropped:
        warn(f"borde irregular: se descartaron {dropped} mes(es) finales con cobertura "
             f"< {MIN_TAIL_COVERAGE:.0%} del peso en crecimiento o inflación")

    d0 = F.index[-1]
    fresh = {b: float(cov_r[b].get(d0, 0.0)) for b in ("growth", "inflation") if b in cov_r}
    filled = {b: float(cov_f[b].get(d0, 0.0)) for b in ("growth", "inflation") if b in cov_f}
    # último mes con casi todo el peso actualizado (la lectura sin arrastre)
    last_full = None
    for d in reversed(list(F.index)):
        if all(float(cov_r[b].get(d, 0.0)) >= FULL_FRESH_COVERAGE for b in ("growth", "inflation")):
            last_full = d
            break
    diag["_edge"] = {
        "date": d0.strftime("%Y-%m"),
        "fresh": {k: round(v, 3) for k, v in fresh.items()},
        "coverage": {k: round(v, 3) for k, v in filled.items()},
        "nowcast": bool(min(fresh.values()) < FULL_FRESH_COVERAGE) if fresh else False,
        "last_full_month": last_full.strftime("%Y-%m") if last_full is not None else None,
        "rows_dropped": dropped,
        "z_last_valid": tail_info,
        "panel_end": Z.index[-1].strftime("%Y-%m"),
        "coverage_by_month": {d.strftime("%Y-%m"): [round(float(cov_f["growth"].get(d, 0)), 2),
                                                   round(float(cov_f["inflation"].get(d, 0)), 2)]
                              for d in cov_f["growth"].index[-14:]},
    }
    e = diag["_edge"]
    print(f"  ✓ lectura de {e['date']} · peso con dato nuevo {e['fresh']} · "
          f"cobertura con arrastre {e['coverage']}"
          + (f" · último mes completo {e['last_full_month']}" if e["nowcast"] else ""))
    return F, diag


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
    # "Renta variable" a propósito, igual que los otros diez sectores: hace treinta
    # años los semiconductores eran una pieza más de "equipo de negocio"; hoy son un
    # eje de inversión propio (capex de IA, escasez de capacidad de fabricación,
    # ciclo distinto al del resto del hardware/software). Por código SIC solapa casi
    # entero con Tecnología (BusEq) —de ahí que antes se excluyera sin más, ver
    # SUBSECTOR_EXCLUDED_MIXED—, así que no compite como una exposición más: ver
    # ASSET_OVERLAP, que impide que los dos cuenten a la vez por el mismo hueco.
    "Chips": ("Semiconductores", "Renta variable",
              "solapa con Tecnología por código SIC; resuelto en ASSET_OVERLAP"),
}

# Pares (activo más fino, activo más amplio que lo contiene) que NO pueden competir
# a la vez por el mismo hueco de un bloque: medirían, en parte, la misma exposición
# económica, y dejarlos competir libremente la sobreponderaría sin que sea
# diversificación real. Se resuelve en _sleeve_pick: de los dos, solo sigue en la
# lista de candidatos el que muestre mejor ventaja de fase — el mismo criterio que
# ya decide cualquier otro desempate del sistema, no una regla nueva por activo.
#
# Los tres pares de renta fija son el mismo caso que Semiconductores/Tecnología,
# pero entre un rendimiento FRED convertido a retorno sintético (ver FRED_YIELD)
# y el ETF real que mide, en esencia, la misma exposición:
#  - "Hipotecario 30 años (aprox.)" es el tipo hipotecario medio a 30 años;
#    "Titulizaciones hipotecarias (MBB)" son las propias titulizaciones cuyo precio
#    fija ese mismo tipo (el "current coupon"). Casi la misma serie con dos fuentes.
#  - "TIPS 10 años (aprox.)" es el tipo real de mercado a 10 años; "TIPS (TIP)" es
#    una cesta de esos mismos bonos ligados a la inflación. Mismo mercado.
#  - "Crédito Baa (aprox.)" es el rendimiento Moody's del escalón MÁS BAJO de grado
#    de inversión; "Crédito Investment Grade (LQD)" es una cesta amplia de grado de
#    inversión donde BBB pesa más que ningún otro escalón por capitalización, así
#    que las dos series se mueven, en la práctica, muy pegadas.
# "Crédito Aaa (aprox.)" NO entra en este último par a propósito: el escalón más
# alto (un puñado de emisores hoy) se comporta más como cuasi-Treasury que como el
# crédito medio de LQD — separarlos es la exposición correcta, no un descuido.
ASSET_OVERLAP = {
    "Semiconductores": "Tecnología",
    "Hipotecario 30 años (aprox.)": "Titulizaciones hipotecarias (MBB)",
    "TIPS 10 años (aprox.)": "TIPS (TIP)",
    "Crédito Baa (aprox.)": "Crédito Investment Grade (LQD)",
}

# ======================================================================================
# 5b. Subsectores — análisis COMPLEMENTARIO, no forma parte de la cartera
# ======================================================================================
# Qué subsector, DENTRO de cada uno de los 10 sectores que ya usa el sistema, ha
# pagado más en cada fase. Es solo para ver un poco más allá de lo que ya recomienda
# la cartera: no entra en means(), _sleeve_pick, rotation() ni en ningún otro punto
# de la selección o el backtest — la sección 8b del JSON se calcula aparte y por
# completo después de que la cartera principal ya está decidida.
#
# El mapeo subsector -> sector NO se ha adivinado por el nombre: se ha verificado
# contra los propios ficheros de definición por código SIC de Ken French
# (Siccodes12.txt y Siccodes49.txt, mismo origen que los retornos), comprobando qué
# rango SIC de cada una de las 49 industrias cae ENTERO dentro del rango SIC de
# cuál de los 12 sectores ya usados (FRENCH_IND). De las 49, solo estas caen limpias
# en un único sector — el resto (ver SUBSECTOR_EXCLUDED_MIXED) se reparte entre
# varios sectores a la vez por código SIC y se excluye en vez de asignarse a ojo.
# Gold y RlEst también caen limpios (bajo "Otros sectores" y "Financiero"), pero se
# excluyen aquí porque YA son activos propios del sistema (ver FRENCH_49): mostrarlos
# otra vez como "subsector de..." sería la misma exposición contada dos veces.
SUBSECTOR_MAP = {
    "Agric": ("Agricultura", "Consumo básico"),
    "Food": ("Alimentación", "Consumo básico"),
    "Soda": ("Golosinas y refrescos", "Consumo básico"),
    "Beer": ("Cerveza y licores", "Consumo básico"),
    "Smoke": ("Tabaco", "Consumo básico"),
    "Books": ("Edición e imprenta", "Consumo básico"),
    "Txtls": ("Textil", "Consumo básico"),
    "Hlth": ("Servicios de salud", "Salud"),
    "MedEq": ("Equipos médicos", "Salud"),
    "Drugs": ("Farmacéuticas", "Salud"),
    "Rubbr": ("Caucho y plástico", "Industria"),
    "Steel": ("Acero", "Industria"),
    "FabPr": ("Metal fabricado", "Industria"),
    "Mach": ("Maquinaria", "Industria"),
    "Aero": ("Aeronáutica", "Industria"),
    "Ships": ("Naval y ferroviario", "Industria"),
    "Guns": ("Defensa", "Industria"),
    "Coal": ("Carbón", "Energía"),
    "Oil": ("Petróleo y gas", "Energía"),
    "Hardw": ("Hardware", "Tecnología"),
    "Softw": ("Software", "Tecnología"),
    "Whlsl": ("Mayoristas", "Consumo discrecional"),
    "Rtail": ("Minoristas", "Consumo discrecional"),
    "Banks": ("Banca", "Financiero"),
    "Insur": ("Seguros", "Financiero"),
    "Fin": ("Bróker y gestión de activos", "Financiero"),
    "Fun": ("Ocio y entretenimiento", "Otros sectores"),
    "Cnstr": ("Construcción", "Otros sectores"),
    "Trans": ("Transporte", "Otros sectores"),
}

# Se reparten por código SIC entre varios de los 12 sectores a la vez, así que no
# hay un único sector "correcto" al que asignarlas sin decidir a ojo dónde trazar
# la línea. "Chips" (semiconductores) NO está en esta lista: por código SIC también
# se reparte (un solo código, 3622, "controles industriales", que pertenece a
# Industria y no a Tecnología), pero en vez de excluirlo se ha promovido a sector
# propio — ver FRENCH_49 y ASSET_OVERLAP — porque a diferencia del resto de esta
# lista tiene entidad e importancia propias como para no quedarse solo en un
# apunte del análisis complementario. Materiales/Químicas, Utilities y
# Comunicaciones no aparecen aquí porque su subsector de las 49 (Chems, Util,
# Telcm) es idéntico al sector de las 12: no hay desglose más fino que ofrecer.
SUBSECTOR_EXCLUDED_MIXED = [
    "Toys", "Hshld", "Clths", "BldMt", "ElcEq", "Autos", "PerSv", "BusSv",
    "LabEq", "Paper", "Boxes", "Meals",
]

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
    # Añadido tras verificar con datos reales que amortigua el tramo bajista de
    # renta fija de 2021-2024 (ver el comentario junto a SLEEVES_FI): grado de
    # inversión, ~6 meses de duración -- ni el riesgo de tipos de un bono largo
    # ni el riesgo de crédito de un préstamo bancario high-yield.
    "Crédito ultracorto plazo (ICSH)": ("Renta fija", "ICSH", "icsh.us",
                                        "investment-grade, ~6 meses de duración"),
    "Deuda emergente (EMB)": ("Renta fija", "EMB", "emb.us", ""),
    "TIPS (TIP)": ("Renta fija", "TIP", "tip.us", ""),
    "Municipales (MUB)": ("Renta fija", "MUB", "mub.us", ""),
    "Titulizaciones hipotecarias (MBB)": ("Renta fija", "MBB", "mbb.us", ""),
    "Renta variable emergente": ("Índice regional", "EEM", "eem.us",
                                 "índice de país, no sector: fuera de la selección"),
    "Renta variable internacional": ("Índice regional", "EFA", "efa.us",
                                     "índice de país, no sector: fuera de la selección"),
    "Small caps": ("Estilo", "IWM", "iwm.us", ""),
    # Referencia del reloj de renta fija (ver ROTATION_FI): mismo papel que
    # "Renta variable EE.UU. (mercado)" para el de renta variable — clase
    # "Índice regional" a propósito, para que quede fuera de SLEEVES_FI por
    # construcción (ver el comentario junto a NOT_SELECTABLE) y no compita
    # nunca como una posición más.
    "Renta fija EE.UU. (mercado)": ("Índice regional", "AGG", "agg.us",
                                    "índice agregado de bonos EE.UU.; referencia, no posición"),
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


# Ken French publica los rendimientos por industria con 1-2 meses de retraso, mientras
# los ETF y los rendimientos de FRED llegan al mes en curso. Sin tratarlo, el último
# mes de la cartera se calcula con un puñado de activos sueltos (p. ej. solo el oro) y
# el gráfico comparativo se corta en el último mes de French. Se hace dos cosas:
#  1) se descarta el mes en curso (incompleto: Yahoo da el mes a fecha de hoy);
#  2) los sectores de French sin dato de los últimos meses COMPLETOS se continúan con
#     el ETF sectorial equivalente (SPDR), marcado en meta.bridge. Composición algo
#     distinta, así que es un puente de uno o dos meses, no una serie nueva.
BRIDGE_ETFS = {
    "Tecnología": "XLK", "Energía": "XLE", "Financiero": "XLF", "Consumo básico": "XLP",
    "Consumo discrecional": "XLY", "Salud": "XLV", "Industria": "XLI",
    "Materiales / Químicas": "XLB", "Utilities": "XLU", "Comunicaciones": "XLC",
    "Semiconductores": "SMH", "Renta variable EE.UU. (mercado)": "SPY",
}
BRIDGE_INFO: dict = {}


def _bridge_and_trim(R: pd.DataFrame) -> pd.DataFrame:
    if R.empty:
        return R
    today = pd.Timestamp.today()
    cur_start = pd.Timestamp(today.year, today.month, 1)
    R = R[R.index < cur_start]                      # fuera el mes en curso
    last_complete = R.index.max()
    bridged = {}
    for col, sym in BRIDGE_ETFS.items():
        if col not in R.columns:
            continue
        lv = R[col].last_valid_index()
        if lv is None:
            continue
        r, _ = yahoo_monthly(sym)
        if r is None:
            r, _ = stooq_monthly(sym.lower() + ".us")
        if r is None:
            continue
        r = r.copy()
        r.index = r.index.to_period("M").to_timestamp("M")
        # Contraste de la fuente: ¿Ken French recoge bien este sector? Se compara con el
        # ETF en los meses en que ambos existen (retorno total mensual, en %).
        both = pd.concat([R[col].loc[:lv], r], axis=1, join="inner").dropna()
        if len(both) >= 36:
            a, b = both.iloc[:, 0] / 100, both.iloc[:, 1] / 100
            ga = float((1 + a).prod() ** (12 / len(a)) - 1) * 100
            gb = float((1 + b).prod() ** (12 / len(b)) - 1) * 100
            BRIDGE_INFO.setdefault("check", {})[col] = {
                "etf": sym, "months": int(len(both)), "from": str(both.index[0].date())[:7],
                "corr": round(float(a.corr(b)), 3),
                "cagr_french": round(ga, 1), "cagr_etf": round(gb, 1)}
        if lv >= last_complete:
            continue
        gap = r[(r.index > lv) & (r.index <= last_complete)].dropna()
        if gap.empty:
            continue
        R.loc[gap.index, col] = gap.values
        bridged[col] = {"etf": sym, "months": [d.strftime("%Y-%m") for d in gap.index]}
    # recorte del borde: filas finales con poca cobertura de activos
    cov = R.notna().mean(axis=1)
    ref = cov.iloc[-24:].max()
    keep_to = R.index[-1]
    for d in reversed(list(R.index)):
        if cov[d] >= 0.7 * ref:
            keep_to = d
            break
    trimmed = int((R.index > keep_to).sum())
    R = R[R.index <= keep_to]
    BRIDGE_INFO.update({"bridged": bridged, "last_month": R.index[-1].strftime("%Y-%m"),
                        "trimmed_months": trimmed})
    if bridged:
        print(f"  ✓ puente con ETF sectoriales en {len(bridged)} series hasta {R.index[-1].strftime('%Y-%m')}")
    return R


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
        global RF_M
        RF_M = rf.copy()
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
    R = _bridge_and_trim(R)
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


# Familia EXTENDIDA: más activos para aclarar Japón, China, biotech y small caps.
# Es una familia de contrastes aparte (su propio control de falsos descubrimientos) y
# NO entra en backtest, rotación, laboratorio ni consenso: así el historial publicado
# no cambia y un fallo de descarga aquí no puede tocar la cartera. Las descargas son
# opcionales: si una falla se anota en meta.extended_log y se sigue.
EXT_FRENCH_REGIONS = {
    "Japón (French)": "Japan_3_Factors_CSV.zip",
    "Europa (French)": "Europe_3_Factors_CSV.zip",
    "Asia-Pacífico ex Japón (French)": "Asia_Pacific_ex_Japan_3_Factors_CSV.zip",
    "Norteamérica (French)": "North_America_3_Factors_CSV.zip",
}
EXT_ETFS = {  # etiqueta: (símbolo Yahoo, ticker Stooq, clase, nota)
    "Biotecnología (IBB)": ("IBB", "ibb.us", "Biotecnología", "ETF; historia desde 2001"),
    "Biotecnología equiponderada (XBI)": ("XBI", "xbi.us", "Biotecnología", "ETF; desde 2006"),
    "China (MCHI)": ("MCHI", "mchi.us", "China", "ETF; desde 2011: muestra corta"),
    "China large caps (FXI)": ("FXI", "fxi.us", "China", "ETF; desde 2004"),
    "Japón (EWJ)": ("EWJ", "ewj.us", "Japón", "ETF; desde 1996"),
}


def fetch_extended():
    """Devuelve (X, meta, log) con excesos mensuales sobre el tipo libre de riesgo."""
    log, rets, meta = [], {}, {}
    ff, _ = french_zip(FRENCH_BASE + "F-F_Research_Data_Factors_CSV.zip", "factores (ext)")
    rf = ff["RF"] if ff is not None and "RF" in ff.columns else None

    def ok(name, ser, cls, src, note=""):
        s = ser.dropna() if ser is not None else None
        if s is None or s.size < MIN_MONTHS:
            log.append({"name": name, "source": src, "status": "descartado",
                        "detail": "sin datos suficientes" if s is None else f"{s.size} meses"})
            return
        if float(s.abs().max()) > 150 or float(s.mean()) > 8:
            log.append({"name": name, "source": src, "status": "descartado",
                        "detail": "retornos implausibles"})
            return
        rets[name] = s
        meta[name] = {"class": cls, "source": src, "note": note}
        log.append({"name": name, "source": src, "status": "ok", "detail": f"{s.size} meses"})

    for lab, fname in EXT_FRENCH_REGIONS.items():
        d, e = french_zip(FRENCH_BASE + fname, lab)
        if d is None:
            log.append({"name": lab, "source": "Ken French (regional)", "status": "fallo",
                        "detail": str(e)[:160]})
            continue
        col = next((c for c in d.columns if "Mkt" in c), None)
        ok(lab, d[col] if col else None, "Región (ext.)", "Ken French (regional)",
           "exceso de mercado, 3 factores")
    me, e = french_zip(FRENCH_BASE + "Portfolios_Formed_on_ME_CSV.zip", "small caps (ext)")
    if me is None or rf is None:
        log.append({"name": "Small caps EE.UU. (20% menores)", "source": "Ken French (tamaño)",
                    "status": "fallo", "detail": str(e)[:160] if me is None else "sin RF"})
    else:
        c20 = next((c for c in me.columns if c.strip() == "Lo 20"), None)
        ok("Small caps EE.UU. (20% menores)",
           (me[c20] - rf.reindex(me.index).ffill()) if c20 else None,
           "Tamaño (ext.)", "Ken French (tamaño)", "cartera Lo 20 ponderada por valor")
    t0 = time.time()
    for lab, (ysym, stick, cls, note) in EXT_ETFS.items():
        if time.time() - t0 > OPTIONAL_BUDGET_S:
            log.append({"name": lab, "source": "mercado", "status": "omitido",
                        "detail": "presupuesto de tiempo agotado"})
            continue
        r, e1 = yahoo_monthly(ysym)
        src = f"Yahoo / {ysym}"
        if r is None:
            r, e2 = stooq_monthly(stick)
            src = f"Stooq / {stick}"
            if r is None:
                log.append({"name": lab, "source": src, "status": "fallo",
                            "detail": f"yahoo: {e1} | stooq: {e2}"[:200]})
                continue
        if rf is not None:
            r = r - rf.reindex(r.index).ffill().fillna(0.0)
        ok(lab, r, cls, src, note)
    return (pd.DataFrame(rets) if rets else pd.DataFrame()), meta, log


def extended_analysis(phases: pd.Series, fetched=None):
    X, meta, log = fetched if fetched is not None else fetch_extended()
    if X.empty:
        return {"assets": [], "meta": {"log": log, "cells": 0}}
    rows, stats = conditional_stats(
        X, phases, meta, label="5c. Familia extendida (aparte, no altera la cartera)…")
    return {"assets": rows, "meta": {"log": log, **stats}}


def fetch_subsectors():
    """Universo de subsectores para el análisis COMPLEMENTARIO (sección 8b): las
    industrias de las 49 de Ken French que caen limpias dentro de un sector ya usado
    (ver SUBSECTOR_MAP). Descarga independiente de F-F_Research_Data_Factors y de
    49_Industry_Portfolios —no comparte el DataFrame ni el `rf` con fetch_assets()—
    precisamente para que un fallo o un cambio aquí no pueda tocar el universo de
    activos de la cartera principal. Mismo criterio de exceso sobre el tipo libre de
    riesgo que usa fetch_assets(), para que el `ann` de un subsector sea comparable
    al `ann` del sector en `assets`."""
    ff, err = french_zip(FRENCH_BASE + "F-F_Research_Data_Factors_CSV.zip",
                          "factores (subsectores)")
    ind49, err2 = french_zip(FRENCH_BASE + "49_Industry_Portfolios_CSV.zip",
                              "49 industrias (subsectores)")
    if ind49 is None:
        warn(f"Subsectores (Ken French 49 industrias): {err2}")
        return {}, {}, {}
    rf = ff["RF"] if ff is not None and "RF" in ff.columns else pd.Series(0.0, index=ind49.index)
    rets: dict[str, pd.Series] = {}
    meta: dict[str, dict] = {}
    parent_of: dict[str, str] = {}
    for col, (label, parent) in SUBSECTOR_MAP.items():
        if col not in ind49.columns:
            continue
        s = (ind49[col] - rf.reindex(ind49.index).ffill().fillna(0.0)).dropna()
        s = s[np.isfinite(s.values)]
        if s.size < MIN_MONTHS:
            continue
        rets[label] = s
        meta[label] = {"class": "Renta variable (subsector)",
                       "source": "Ken French (49 industrias)",
                       "note": f"subsector de {parent}"}
        parent_of[label] = parent
    return rets, meta, parent_of


# ======================================================================================
# 5c. Holdings reales (complementario): qué empresas pesan hoy en cada sector
# ======================================================================================
# Ken French da retornos por industria, no nombres de empresa — no publica la
# composición del índice. Para mostrar ejemplos reales (no elegidos de memoria) se
# usa el propio fichero de posiciones que cada SPDR/State Street Select Sector ETF
# publica a diario: mismo ticker que ya aparece en ETF_MAP, mismo proveedor, y
# fichero descargable de forma fiable con requests (verificado: iShares devuelve el
# HTML del sitio en vez del CSV que promete su URL, y VanEck no se ha podido
# verificar como fuente programática, así que quedan fuera). Comprobado con datos
# reales: la columna "Sector" del propio fichero viene vacía, así que no clasifica
# sola. Por eso TICKER_SUBSECTOR clasifica cada ticker a mano — pero contra el
# código SIC real y público de cada empresa (mismo criterio que usa Ken French para
# sus propias 49 industrias, verificable en SEC EDGAR), nunca por lo que "suene" del
# negocio. Si una posición del top-8 no tiene un código SIC que encaje limpio en
# ninguno de los subsectores DE SU MISMO SECTOR, se deja fuera de la clasificación
# — no se reasigna a otro sector ni se fuerza en el más parecido.
SPDR_HOLDINGS_URL = ("https://www.ssga.com/us/en/individual/library-content/"
                      "products/fund-data/etfs/us/holdings-daily-us-en-{ticker}.xlsx")

# Sector de la cartera -> ticker del SPDR que lo replica (mismos tickers que ETF_MAP).
# "Otros sectores" (Fama-French "Other": ocio, construcción, transporte, minería...)
# no tiene un SPDR sectorial propio por mezclar varios sectores GICS a la vez: su
# subsector con desglose limpio y fuente fiable (Transporte) se cubre aparte, más
# abajo, con el ETF específico de esa sub-industria — no del sector "Otros" entero.
SECTOR_HOLDINGS_TICKERS = {
    "Tecnología": "XLK", "Salud": "XLV",
    "Energía": "XLE", "Comunicaciones": "XLC", "Financiero": "XLF",
    "Industria": "XLI", "Materiales / Químicas": "XLB", "Utilities": "XLU",
    "Consumo discrecional": "XLY", "Consumo básico": "XLP", "Inmobiliario": "XLRE",
}

# Semiconductores NO tiene su propio ETF aquí a propósito: se probó XSD ("SPDR S&P
# Semiconductor Select Industry"), pero por ser un índice de ponderación casi
# igualada, verificado con datos reales, su top-20 NO incluye ni a Nvidia ni a
# Micron ni a Broadcom — los tres pesan mucho en el mercado real pero casi nada en
# un índice que reparte el peso a partes iguales entre fabricantes grandes y
# pequeños. Esas mismas empresas SÍ aparecen, y con peso real de mercado, dentro
# del propio XLK (Tecnología) que ya se descarga — GICS las agrupa ahí, aunque por
# código SIC (3674) sean semiconductores y no "Hardware" ni "Software" (ver
# CHIP_TICKERS). Así que el contenido de Semiconductores se deriva de la propia
# Tecnología en vez de descargar un cuarto proveedor: mismo dato fiable, sin sumar
# una fuente más que gestionar, y con los nombres que de verdad importan hoy.
CHIP_TICKERS = {
    "NVDA", "AMD", "AVGO", "MU", "INTC", "LRCX", "AMAT", "TXN", "KLAC", "MRVL", "SNDK",
}

# Subsectores con su propio ETF de sub-industria en la misma familia SPDR. Se probó
# también Construcción (XHB, "S&P Homebuilders Select Industry"): sus posiciones
# reales incluyen hoy un fabricante de pequeños electrodomésticos (SharkNinja) y una
# cadena de menaje del hogar (Williams-Sonoma) junto a los constructores — el fondo
# ya no es un proxy limpio de "Construcción" y mostrarlo sin poder separar caso a
# caso sería justo el tipo de ejemplo mal etiquetado que se quiere evitar, así que
# se descarta. "Ocio y entretenimiento" se queda sin fuente por la misma razón: no
# hay un SPDR de esa sub-industria exacta y no se inventa una alternativa.
DIRECT_SUBSECTOR_TICKERS = {
    "Transporte": "XTN",
}

# Clasificación ticker -> subsector, construida sobre los holdings REALES observados
# (top-20 real de cada sector) contra el código SIC público de cada empresa. Cada
# entrada omitida se dejó fuera a propósito (ver comentarios): o su SIC real cae en
# otro sector, o cae en una de las industrias mixtas que ya excluye SUBSECTOR_MAP.
TICKER_SUBSECTOR = {
    # Tecnología: los fabricantes de chips (Nvidia, AMD, Broadcom, Micron, Intel,
    # Lam Research, Applied Materials, Texas Instruments, KLA, Marvell, SanDisk) son
    # SIC 3674/3559 -- "Chips" en Ken French, no "Hardw" ni "Softw". No se
    # reclasifican aquí: alimentan directamente el sector Semiconductores (ver
    # CHIP_TICKERS). Cisco y Arista (equipos de red) y Seagate (almacenamiento) se
    # dejan fuera: ninguno encaja limpio en Hardware (ordenadores) ni Software.
    "AAPL": "Hardware",
    "MSFT": "Software", "PLTR": "Software", "PANW": "Software", "CRWD": "Software",
    "ORCL": "Software",
    # Salud: Abbott (tras escindir su negocio farma como AbbVie en 2013, su núcleo
    # es diagnóstico y dispositivos), Intuitive Surgical (robot Da Vinci), Danaher
    # (instrumentación de laboratorio, como Thermo Fisher), Medtronic y Stryker son
    # equipo médico, no farmacéuticas. McKesson (distribuidor mayorista de fármacos,
    # SIC 5122) no encaja en ninguno de los 3 subsectores de Salud y se deja fuera.
    "LLY": "Farmacéuticas", "JNJ": "Farmacéuticas", "ABBV": "Farmacéuticas",
    "MRK": "Farmacéuticas", "AMGN": "Farmacéuticas", "GILD": "Farmacéuticas",
    "PFE": "Farmacéuticas", "VRTX": "Farmacéuticas", "BMY": "Farmacéuticas",
    "REGN": "Farmacéuticas",
    # Moderna fabrica y vende fármacos aprobados (vacunas de ARNm): mismo SIC
    # 2836 ("Biological products") que el resto de este bloque, no un caso
    # aparte por ser "biotech" en el lenguaje común.
    "MRNA": "Farmacéuticas",
    "UNH": "Servicios de salud", "CVS": "Servicios de salud", "ELV": "Servicios de salud",
    "TMO": "Equipos médicos", "ABT": "Equipos médicos", "ISRG": "Equipos médicos",
    "DHR": "Equipos médicos", "MDT": "Equipos médicos", "SYK": "Equipos médicos",
    # Energía: todas las posiciones del top-20 son petroleras integradas, E&P,
    # midstream, refino u oilfield services -- todas "Oil", ninguna minera de carbón.
    "XOM": "Petróleo y gas", "CVX": "Petróleo y gas", "COP": "Petróleo y gas",
    "VLO": "Petróleo y gas", "MPC": "Petróleo y gas", "PSX": "Petróleo y gas",
    "WMB": "Petróleo y gas", "SLB": "Petróleo y gas", "EOG": "Petróleo y gas",
    "KMI": "Petróleo y gas", "TRGP": "Petróleo y gas", "BKR": "Petróleo y gas",
    "OKE": "Petróleo y gas", "DVN": "Petróleo y gas", "OXY": "Petróleo y gas",
    "FANG": "Petróleo y gas", "EQT": "Petróleo y gas", "HAL": "Petróleo y gas",
    "TPL": "Petróleo y gas", "EXE": "Petróleo y gas",
    # Financiero: Visa, Mastercard, S&P Global y CME Group quedan fuera -- por SIC
    # real son procesamiento de datos (7389) o bolsas/proveedores de datos, no
    # banca, seguro ni bróker, aunque GICS los agrupe junto al resto en
    # "Financiero". American Express sí entra en Banca: a diferencia de Visa/MA,
    # concede crédito directamente y es una entidad bancaria regulada desde 2008.
    "JPM": "Banca", "BAC": "Banca", "WFC": "Banca", "C": "Banca", "AXP": "Banca",
    "COF": "Banca", "USB": "Banca",
    "BRK.B": "Seguros", "PGR": "Seguros", "CB": "Seguros",
    "GS": "Bróker y gestión de activos", "MS": "Bróker y gestión de activos",
    "SCHW": "Bróker y gestión de activos", "BLK": "Bróker y gestión de activos",
    "HOOD": "Bróker y gestión de activos",
    # BNY (Bank of New York Mellon) estaba en Banca solo por el nombre -- el
    # único de todo este bloque sin verificar contra su negocio real. BNY no
    # toma depósitos ni presta como JPM/BAC/WFC/C/USB: su negocio es custodia
    # de activos, compensación de valores y servicios a inversores
    # institucionales -- "Asset Management & Custody Banks", no "Banks", en
    # la clasificación GICS real. Encaja con BlackRock (gestión de activos),
    # no con la banca comercial.
    "BNY": "Bróker y gestión de activos",
    # Industria: Union Pacific y CSX son operadores ferroviarios (SIC 4011, "Trans"
    # -- Otros sectores), no fabricantes; Eaton, Trane, Vertiv, Johnson Controls y
    # Emerson son equipo eléctrico ("ElcEq", mixta y excluida); Uber es transporte,
    # no industria; ADP es servicios empresariales; 3M es demasiado diversificada
    # para clasificar con confianza. Ninguno encaja limpio y se dejan fuera.
    "CAT": "Maquinaria", "DE": "Maquinaria", "GEV": "Maquinaria", "PH": "Maquinaria",
    "GE": "Aeronáutica", "BA": "Aeronáutica", "HWM": "Aeronáutica",
    "RTX": "Defensa", "LMT": "Defensa",
    # Consumo discrecional: Tesla/GM/Ford (fabricantes de coches, "Autos"),
    # McDonald's/Starbucks (restauración, "Meals"), Booking/Marriott/Hilton/Royal
    # Caribbean (viaje y alojamiento), DoorDash/Airbnb (plataformas) y Nike (su SIC
    # real es fabricación de calzado, no venta al por menor) no son mayoristas ni
    # minoristas en la definición de Ken French.
    "AMZN": "Minoristas", "HD": "Minoristas", "TJX": "Minoristas", "LOW": "Minoristas",
    "ROST": "Minoristas", "ORLY": "Minoristas", "AZO": "Minoristas",
    # Consumo básico: Walmart/Costco/Target/Kroger/Dollar General son minoristas
    # generalistas (SIC 5331/5411, "Rtail" -- el subsector de Consumo DISCRECIONAL,
    # no de aquí). P&G/Colgate/Kenvue/Kimberly-Clark/Estée Lauder son "Hshld"/
    # "PerSv" (bienes e higiene personal/del hogar), industrias mixtas y excluidas.
    # Sysco es un mayorista de distribución alimentaria (SIC 5140, "Whlsl" -- de
    # Consumo discrecional, no de aquí) y se deja fuera por la misma razón.
    "KO": "Golosinas y refrescos", "MDLZ": "Golosinas y refrescos",
    "PEP": "Golosinas y refrescos", "MNST": "Golosinas y refrescos",
    "KDP": "Golosinas y refrescos", "HSY": "Golosinas y refrescos",
    "PM": "Tabaco", "MO": "Tabaco",
    "ADM": "Agricultura",
}

# Para Comunicaciones, Utilities y Materiales/Químicas Ken French no ofrece ningún
# desglose (su única industria de las 49 que cae limpia es idéntica al sector
# entero, ver SUBSECTOR_MAP). A petición expresa del usuario, en vez de enseñar
# solo la lista plana de posiciones, se deducen sub-grupos reales -- mismo
# tratamiento visual que Salud o Financiero, pero el número ya no es rentabilidad
# por fase (no hay historia que medir para un grupo inventado) sino el peso real
# agregado de ese grupo en el ETF hoy. Cada grupo se construye sumando tickers REALES
# observados en el top-20 de cada sector, clasificados contra su sub-industria GICS
# pública y verificable -- nunca a ojo. Una empresa del top-20 que no encaje con
# confianza en ningún grupo se deja fuera, igual que en TICKER_SUBSECTOR.
HOLDINGS_GROUPS = {
    "Comunicaciones": {
        # Meta/Alphabet (publicidad + plataforma), AppLovin (publicidad in-app) y
        # Reddit son "Interactive Media & Services". Omnicom (agencia de
        # publicidad tradicional) y News Corp (editorial, SIC de imprenta) quedan
        # fuera: ni son plataformas ni caen en este sector por SIC real.
        "Medios interactivos y redes": {"META", "GOOGL", "GOOG", "APP", "RDDT"},
        # AT&T, T-Mobile y Verizon son telecomunicaciones integradas; Comcast,
        # Charter y EchoStar son cable/satélite -- misma infraestructura de
        # conectividad, se agrupan juntas.
        "Telecomunicaciones": {"T", "TMUS", "VZ", "CMCSA", "CHTR", "ECHO"},
        # Warner Bros Discovery, Disney y Fox son "Movies & Entertainment"/
        # "Broadcasting"; Netflix es streaming (misma sub-industria que WBD/Disney);
        # Live Nation y TKO (WWE/UFC) son ocio y espectáculos en vivo.
        "Entretenimiento": {"WBD", "DIS", "NFLX", "LYV", "FOXA", "TKO"},
        "Videojuegos": {"TTWO"},
    },
    "Utilities": {
        # NextEra, Southern, Duke, AEP, Entergy, Exelon y PPL son eléctricas puras
        # (regulated electric utilities).
        "Eléctricas reguladas": {"NEE", "SO", "DUK", "AEP", "ETR", "EXC", "PPL"},
        # Dominion, Sempra, Xcel, ConEd, PSEG, WEC, Ameren, PG&E y DTE distribuyen
        # electricidad Y gas a la vez -- "Multi-Utilities" en la clasificación GICS.
        "Multiservicios (electricidad y gas)": {
            "D", "SRE", "XEL", "ED", "PEG", "WEC", "AEE", "PCG", "DTE",
        },
        # Constellation y Vistra son generadoras competitivas/mercantiles (nuclear
        # y gas, sobre todo), no distribuidoras reguladas -- "Independent Power
        # Producers".
        "Generación independiente": {"CEG", "VST"},
        "Agua": {"AWK"},
        "Gas natural": {"ATO"},
    },
    "Materiales / Químicas": {
        # Linde/Air Products (gases industriales), Ecolab/Sherwin-Williams/PPG
        # (química especializada), Dow (química de base), Corteva/CF Industries
        # (agroquímica) e IFF (aromas y fragancias) son todas "Chemicals" GICS.
        "Química": {"LIN", "ECL", "SHW", "APD", "PPG", "IFF", "DOW", "CTVA", "CF"},
        "Minería": {"NEM", "FCX"},
        "Acero": {"STLD", "NUE"},
        # Vulcan Materials, Martin Marietta y CRH son áridos y materiales de
        # construcción -- "Construction Materials" GICS.
        "Materiales de construcción": {"VMC", "MLM", "CRH"},
        # Smurfit WestRock, Packaging Corp, Amcor e International Paper son
        # envases/embalaje -- "Containers & Packaging" GICS.
        "Envases y embalaje": {"SW", "PKG", "AMCR", "IP"},
    },
}

N_HOLDINGS = 20


def _fetch_spdr_xlsx(ticker: str):
    """Descarga y parsea el .xlsx de posiciones de un SPDR/State Street. Devuelve
    (posiciones, fecha "as of" del propio fichero) recortado a N_HOLDINGS, o
    (None, None) si falla — nunca inventa una posición que no esté en el fichero."""
    url = SPDR_HOLDINGS_URL.format(ticker=ticker.lower())
    headers = {"User-Agent": "Mozilla/5.0 (compatible; investment-clock/2.0)"}
    last = "sin intentos"
    for attempt in range(RETRIES):
        try:
            r = requests.get(url, timeout=OPTIONAL_TIMEOUT, headers=headers)
            if r.status_code != 200 or r.content[:2] != b"PK":
                raise RuntimeError(f"HTTP {r.status_code}, no es un .xlsx válido")
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(r.content), data_only=True)
            ws = wb[wb.sheetnames[0]]
            rows = list(ws.iter_rows(values_only=True))
            as_of = None
            if len(rows) > 2 and rows[2] and rows[2][0] == "Holdings:":
                as_of = str(rows[2][1]).replace("As of ", "")
            header_idx = next((i for i, row in enumerate(rows)
                               if row and row[0] == "Name"), None)
            if header_idx is None:
                raise RuntimeError("no se encontró la fila de cabecera")
            out = []
            for row in rows[header_idx + 1:]:
                if not row or not row[0] or row[1] is None:
                    break
                try:
                    weight = float(row[4])
                except (TypeError, ValueError):
                    break
                # El fichero sustituye el símbolo "&" por "+" en los nombres
                # (JPMORGAN CHASE + CO, AT+T INC...): se deshace, es una
                # codificación del propio proveedor, no una invención nuestra.
                name = str(row[0]).replace("+", "&").title()
                out.append({"name": name, "ticker": str(row[1]),
                           "weight": round(weight, 2)})
                if len(out) >= N_HOLDINGS:
                    break
            if not out:
                raise RuntimeError("fichero sin posiciones")
            return out, as_of
        except Exception as exc:  # noqa: BLE001
            last = str(exc)
            if attempt < RETRIES - 1:
                time.sleep(1.5 * (attempt + 1))
    warn(f"Holdings {ticker}: {last}")
    return None, None


def fetch_holdings():
    """Universo COMPLEMENTARIO (sección 8c): posiciones reales y actuales de los
    SPDR sectoriales, para (a) dar contenido de verdad a los sectores sin desglose
    en Ken French (Utilities, Materiales/Químicas, Comunicaciones y Semiconductores)
    y (b) sustituir ejemplos de empresas elegidos de memoria por las posiciones
    reales de hoy en cada subsector. No participa en means(), _sleeve_pick,
    rotation() ni el backtest — es análisis aparte, igual que subsector_analysis()."""
    por_sector: dict[str, list] = {}
    as_of = None
    for sector, ticker in SECTOR_HOLDINGS_TICKERS.items():
        pos, d = _fetch_spdr_xlsx(ticker)
        if pos:
            por_sector[sector] = pos
            as_of = as_of or d
    # Semiconductores se deriva de Tecnología (ver CHIP_TICKERS), no de un fetch
    # propio: filtra, entre las posiciones reales ya descargadas de XLK, las que por
    # SIC real son semiconductores, y las ordena por su propio peso dentro de XLK.
    tecnologia = por_sector.get("Tecnología", [])
    chips = sorted((p for p in tecnologia if p["ticker"] in CHIP_TICKERS),
                   key=lambda r: -r["weight"])
    if chips:
        por_sector["Semiconductores"] = chips

    por_subsector: dict[str, list] = {}
    for sub, ticker in DIRECT_SUBSECTOR_TICKERS.items():
        pos, d = _fetch_spdr_xlsx(ticker)
        if pos:
            por_subsector[sub] = pos
            as_of = as_of or d
    for sector, pos_list in por_sector.items():
        if sector == "Semiconductores":
            continue  # ya clasificado en su totalidad: no vuelve a pasar por aquí.
        for pos in pos_list:
            sub = TICKER_SUBSECTOR.get(pos["ticker"])
            if sub:
                por_subsector.setdefault(sub, []).append(pos)
    for sub, rows in por_subsector.items():
        rows.sort(key=lambda r: -r["weight"])

    # Grupos derivados (Comunicaciones, Utilities, Materiales/Químicas): mismo
    # tratamiento que un subsector Ken French en la interfaz, pero el número es el
    # peso real agregado del grupo en el ETF, no una rentabilidad por fase.
    grupos: dict[str, list] = {}
    for sector, groups in HOLDINGS_GROUPS.items():
        pos_by_ticker = {p["ticker"]: p for p in por_sector.get(sector, [])}
        rows = []
        for name, tickers in groups.items():
            miembros = sorted((pos_by_ticker[t] for t in tickers if t in pos_by_ticker),
                              key=lambda r: -r["weight"])
            if miembros:
                rows.append({"grupo": name,
                            "peso": round(sum(m["weight"] for m in miembros), 2),
                            "empresas": miembros})
        if rows:
            rows.sort(key=lambda r: -r["peso"])
            grupos[sector] = rows

    # Salvaguarda permanente: por construcción TICKER_SUBSECTOR asigna cada ticker a
    # un único subsector, así que la misma empresa no debería poder aparecer nunca
    # en dos subsectores a la vez. Se comprueba en vez de asumirlo: un futuro cambio
    # en la tabla (o un ticker que coincida con uno de DIRECT_SUBSECTOR_TICKERS)
    # podría romper esa garantía en silencio.
    seen: dict[str, str] = {}
    for sub, rows in por_subsector.items():
        for r in rows:
            prev = seen.get(r["ticker"])
            if prev and prev != sub:
                warn(f"Holdings: {r['ticker']} aparece en dos subsectores a la vez "
                     f"({prev} y {sub})")
            seen[r["ticker"]] = sub
    # Misma salvaguarda para HOLDINGS_GROUPS: un ticker no debería caer en dos
    # grupos del mismo sector a la vez.
    for sector, rows in grupos.items():
        seen_g: dict[str, str] = {}
        for row in rows:
            for m in row["empresas"]:
                prev = seen_g.get(m["ticker"])
                if prev and prev != row["grupo"]:
                    warn(f"Holdings: {m['ticker']} aparece en dos grupos de "
                         f"{sector} a la vez ({prev} y {row['grupo']})")
                seen_g[m["ticker"]] = row["grupo"]
    return {"por_sector": por_sector, "por_subsector": por_subsector, "grupos": grupos,
            "meta": {"as_of": as_of, "source": "SPDR / State Street (holdings diarios)"}}


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


RELIAB_MIN_N_STRONG = 60
RELIAB_MIN_N = 36


def _cell_checks(s: pd.Series, ph: pd.Series, phase: str, grand: float,
                 rel_full: float) -> dict:
    """Tres comprobaciones independientes del contraste principal.
    - split: el signo del exceso sobre la media se repite en las dos mitades del
      tiempo (no depende de una sola época).
    - lag: con la fase desplazada un mes (lo que realmente se sabría) el signo se
      mantiene. Si solo funciona con la fase contemporánea, no es accionable.
    - n: observaciones suficientes."""
    sub = s[ph == phase]
    sg = np.sign(rel_full)
    out = {"n": int(sub.size)}
    if sub.size >= 8:
        h = sub.size // 2
        a, b = sub.iloc[:h].mean() - grand, sub.iloc[h:].mean() - grand
        out["split"] = bool(np.sign(a) == sg and np.sign(b) == sg)
    else:
        out["split"] = False
    lagged = ph.shift(1).reindex(s.index)
    sl = s[lagged == phase]
    out["lag"] = bool(sl.size >= 12 and np.sign(sl.mean() - grand) == sg)
    return out


def reliability_label(d: dict) -> str:
    """Fuerte / Moderada / Débil / Sin señal. Es una etiqueta de fiabilidad
    ESTADÍSTICA de la casilla, no una predicción: Fuerte exige t robusta, control
    de falsos descubrimientos, estabilidad temporal, utilidad con la fase conocida
    con retraso y muestra amplia."""
    g = str(d.get("grade", "0"))
    if g in ("0", "s/d") or not g:
        return "Sin señal"
    c = d.get("checks") or {}
    q = d.get("q")
    fdr = q is not None and q <= 0.10
    if (len(g) >= 2 and fdr and c.get("split") and c.get("lag")
            and c.get("n", 0) >= RELIAB_MIN_N_STRONG):
        return "Fuerte"
    if (len(g) >= 2 and c.get("split") and c.get("n", 0) >= RELIAB_MIN_N
            and (fdr or c.get("lag"))):
        return "Moderada"
    return "Débil"


def conditional_stats(X: pd.DataFrame, phases: pd.Series, meta: dict,
                       label: str = "5. Estimando retornos condicionales…"):
    print(label)
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
                "checks": _cell_checks(s, ph, phase, grand, float(mu - grand)),
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
            d["reliability"] = reliability_label(d)

    for e in rows:
        for d in e["phases"].values():
            d.setdefault("reliability", "Sin señal")
    graded = sum(1 for e in rows for d in e["phases"].values()
                 if d.get("grade") not in (None, "0", "s/d"))
    fdr = sum(1 for e in rows for d in e["phases"].values()
              if d.get("q") is not None and d["q"] <= 0.10)
    print(f"  ✓ {len(rows)} activos · {len(cells)} casillas · {graded} con nota · "
          f"{fdr} robustas al control de falsos descubrimientos")
    rel_counts = {k: sum(1 for e in rows for d in e["phases"].values()
                        if d.get("reliability") == k)
                  for k in ("Fuerte", "Moderada", "Débil", "Sin señal")}
    print(f"  ✓ fiabilidad por casilla: {rel_counts}")
    return rows, {"cells": len(cells), "graded": graded, "fdr_survivors": fdr,
                  "reliability": rel_counts}


# ======================================================================================
# 6b. Contraste "ahora": regresión sobre las probabilidades de fase
# ======================================================================================
# La matriz de evidencia clasifica cada mes en UNA fase y promedia, tirando la
# información de cuánto de cada fase hay. Aquí se regresa el exceso de retorno del
# mes t sobre las probabilidades de fase conocidas en t-1 (la misma `probs_df`
# desplazada que usa la rotación) y se contrasta una sola cosa: ¿la predicción de HOY,
# p_hoy, difiere de la media histórica p̄? Es un contraste único por activo con toda la
# muestra, bastante más potente que 4 medias condicionadas con ~100 meses cada una.
# Validación fuera de muestra: ventana creciente desde NOW_MIN_TRAIN meses, R² OOS frente
# a la media creciente y estadístico de Clark-West (modelos anidados).
NOW_MIN_TRAIN = 180


def _hac_cov(Xm: np.ndarray, e: np.ndarray, lags: int = 3) -> np.ndarray:
    n, k = Xm.shape
    XtXi = np.linalg.pinv(Xm.T @ Xm)
    u = Xm * e[:, None]
    S = u.T @ u
    for l in range(1, min(lags, n - 1) + 1):
        w = 1 - l / (lags + 1)
        G = u[l:].T @ u[:-l]
        S += w * (G + G.T)
    return XtXi @ S @ XtXi


def now_edge(X: pd.DataFrame, probs_df: pd.DataFrame, p_now: dict, meta: dict):
    print("5d. Contraste «ahora» (regresión sobre probabilidades de fase)…")
    P = probs_df[PHASES].dropna()
    keep = PHASES[1:]          # se omite la primera fase para evitar colinealidad
    pbar = P.mean()
    c = np.array([p_now[k] - pbar[k] for k in keep])
    rows, pv = [], []
    for col in X.columns:
        y = X[col].dropna()
        idx = y.index.intersection(P.index)
        if len(idx) < max(MIN_MONTHS, 96):
            continue
        y, Pm = y.loc[idx].values, P.loc[idx, keep].values
        Xm = np.column_stack([np.ones(len(idx)), Pm])
        beta = np.linalg.lstsq(Xm, y, rcond=None)[0]
        e = y - Xm @ beta
        V = _hac_cov(Xm, e)
        cc = np.concatenate([[0.0], c])
        est = float(cc @ beta)
        se = float(math.sqrt(max(cc @ V @ cc, 1e-12)))
        t = est / se
        # fuera de muestra
        oos = {"r2": None, "cw_t": None, "hit": None, "n": 0}
        n = len(y)
        if n > NOW_MIN_TRAIN + 36:
            f_m, f_b, act = [], [], []
            for i in range(NOW_MIN_TRAIN, n):
                b = np.linalg.lstsq(Xm[:i], y[:i], rcond=None)[0]
                f_m.append(float(Xm[i] @ b))
                f_b.append(float(y[:i].mean()))
                act.append(float(y[i]))
            f_m, f_b, act = map(np.array, (f_m, f_b, act))
            sse_m, sse_b = ((act - f_m) ** 2).sum(), ((act - f_b) ** 2).sum()
            adj = (act - f_b) * (f_m - f_b)       # Clark-West
            _, _, cw_t = newey_west(adj)
            dev_m, dev_b = f_m - f_b, act - f_b
            oos = {"r2": round(float(1 - sse_m / sse_b), 4) if sse_b > 0 else None,
                   "cw_t": round(float(cw_t), 2) if cw_t == cw_t else None,
                   "hit": round(float((np.sign(dev_m) == np.sign(dev_b)).mean()), 3),
                   "n": int(len(act))}
        rows.append({"name": col, "class": meta.get(col, {}).get("class", "Otros"),
                     "now_ann": round(est * 12, 2), "se_ann": round(se * 12, 2),
                     "t": round(float(t), 2), "n": int(n), "oos": oos})
        pv.append(two_sided_p(t))
    qs = benjamini_hochberg(pv)
    for r, q in zip(rows, qs):
        r["q"] = round(q, 3) if q == q else None
        o = r["oos"]
        oos_ok = (o["r2"] is not None and o["r2"] > 0 and o["cw_t"] is not None
                  and o["cw_t"] >= 1.28)
        t_ok = abs(r["t"]) >= 1.96
        fdr = r["q"] is not None and r["q"] <= 0.10
        if t_ok and fdr and oos_ok:
            r["reliability"] = "Fuerte"
        elif t_ok and (fdr or oos_ok):
            r["reliability"] = "Moderada"
        elif abs(r["t"]) >= 1.28:
            r["reliability"] = "Débil"
        else:
            r["reliability"] = "Sin señal"
    rows.sort(key=lambda r: -r["now_ann"])
    cnt = {k: sum(1 for r in rows if r["reliability"] == k)
           for k in ("Fuerte", "Moderada", "Débil", "Sin señal")}
    print(f"  ✓ {len(rows)} activos · fiabilidad {cnt}")
    return {"assets": rows, "meta": {"p_now": {k: round(float(v), 3) for k, v in p_now.items()},
                                     "p_mean": {k: round(float(v), 3) for k, v in pbar.items()},
                                     "min_train": NOW_MIN_TRAIN, "counts": cnt}}



# ======================================================================================
# 7b. Test del universo: ¿mejoran la cartera los activos nuevos?
# ======================================================================================
UNI_GROUPS = {
    "Biotecnología": lambda m: [n for n, v in m.items() if v["class"] == "Biotecnología"],
    "Small caps (20% menores)": lambda m: [n for n in m if n.startswith("Small caps")],
    "Regiones (French)": lambda m: [n for n, v in m.items() if v["class"] == "Región (ext.)"],
    "China": lambda m: [n for n, v in m.items() if v["class"] == "China"],
    "Japón (ETF)": lambda m: [n for n, v in m.items() if v["class"] == "Japón"],
}
UNI_MIN_DSHARPE = 0.01
UNI_MIN_SCHEMES = 3


def _scheme_metrics(rot: dict) -> dict:
    out = {}
    for sch, d in (rot.get("schemes") or {}).items():
        pf = d.get("portfolio") or {}
        out[sch] = {k: pf.get(k) for k in ("cagr", "sharpe", "maxdd")}
    return out


def universe_test(X, ameta, Xe, emeta, phases, probs_df, F):
    """Cada grupo de activos nuevos se prueba solo, sumado al bloque de renta variable
    de la cartera walk-forward, y se compara con la cartera base en los cuatro
    esquemas de reparto. Se adopta el grupo si mejora el Sharpe en al menos
    UNI_MIN_SCHEMES de 4 esquemas (>= UNI_MIN_DSHARPE) SIN bajar el CAGR en esos
    mismos esquemas. Después se comprueba la unión de los adoptados contra la base;
    si no mejora igual, no se adopta ninguno. Es selección con la misma muestra del
    backtest (se declara): mejora observada, no garantía fuera de muestra."""
    print("5e. Test del universo ampliado (cartera con y sin los activos nuevos)…")
    res = {"groups": {}, "adopted": [], "final_check": None}
    if Xe is None or Xe.empty:
        return X, ameta, res
    cls_map = {k: v.get("class", "Otros") for k, v in ameta.items()}
    base = _scheme_metrics(rotation(X, phases, cls_map, probs_df, F,
                                    phase_sleeve_override=ESTANFLACION_OVERRIDE))
    res["base"] = base
    if not base:
        return X, ameta, res

    def better(var):
        wins = 0
        for sch, b in base.items():
            v = var.get(sch) or {}
            if None in (b.get("sharpe"), v.get("sharpe"), b.get("cagr"), v.get("cagr")):
                continue
            if v["sharpe"] - b["sharpe"] >= UNI_MIN_DSHARPE and v["cagr"] >= b["cagr"] - 0.02:
                wins += 1
        return wins

    def run(cols):
        X2 = X.join(Xe[cols], how="outer")
        c2 = {**cls_map, **{c: "Renta variable" for c in cols}}
        return _scheme_metrics(rotation(X2, phases, c2, probs_df, F,
                                        phase_sleeve_override=ESTANFLACION_OVERRIDE))

    adopt = []
    for g, pick in UNI_GROUPS.items():
        cols = [c for c in pick(emeta) if c in Xe.columns]
        if not cols:
            continue
        var = run(cols)
        w = better(var)
        res["groups"][g] = {"cols": cols, "wins": w, "schemes": var,
                            "adopted": w >= UNI_MIN_SCHEMES}
        print(f"  · {g:<26} mejora en {w}/4 esquemas")
        if w >= UNI_MIN_SCHEMES:
            adopt += cols
    if adopt:
        var = run(adopt)
        w = better(var)
        res["final_check"] = {"cols": adopt, "wins": w, "schemes": var}
        if w < UNI_MIN_SCHEMES:
            print("  · la unión no mejora a la base: no se adopta ninguno")
            adopt = []
    res["adopted"] = adopt
    if adopt:
        X = X.join(Xe[adopt], how="outer")
        ameta = {**ameta, **{c: {**emeta[c], "class": "Renta variable"} for c in adopt}}
        for a, b in (("Biotecnología equiponderada (XBI)", "Biotecnología (IBB)"),
                     ("Biotecnología (IBB)", "Salud")):
            ASSET_OVERLAP.setdefault(a, b)
        print(f"  ✓ adoptados en la cartera: {adopt}")
    return X, ameta, res



# Satélite táctico: un bloque más de la rotación, con banda propia, para los activos
# nuevos con evidencia por fase. Se usa el MISMO motor walk-forward (misma selección
# por ventaja de fase contraída, mismos esquemas de reparto), así que las cifras son
# comparables con la cartera base. Banda 0-15% y 0-2 nombres: nunca obligatorio.
SAT_MIN_SCHEMES = 3
SAT_CLASSES = {"Biotecnología", "Tamaño (ext.)", "Región (ext.)", "China", "Japón"}


def satellite_test(X, Xe, emeta, ameta, phases, probs_df, F, rot_base, level_weight=0.0):
    """Compara la cartera base con la cartera con satélite. Devuelve (rot_final, info).
    Se adopta (rot_final = con satélite) si mejora el Sharpe >= UNI_MIN_DSHARPE en al
    menos UNI_MIN_SCHEMES de 4 esquemas sin bajar el CAGR más de 0,05 puntos. Si no,
    rot_final = base y el satélite se publica como opcional con sus cifras."""
    print("7c. Satélite táctico (bloque de activos nuevos con banda 0-15%)…")
    info = {"adopted": False, "bands": "0-15%", "assets": []}
    if Xe is None or Xe.empty:
        return rot_base, info
    cols = [c for c in Xe.columns if c not in X.columns and emeta[c]["class"] in SAT_CLASSES]
    if not cols:
        return rot_base, info
    X2 = X.join(Xe[cols], how="outer")
    cls2 = {k: v.get("class", "Otros") for k, v in ameta.items()}
    cls2.update({c: emeta[c]["class"] for c in cols})
    sleeves_sat = {**SLEEVES, "Satélite táctico": (SAT_CLASSES, 0.00, 0.15, 0, 2)}
    rot_sat = rotation(X2, phases, cls2, probs_df, F, sleeves=sleeves_sat,
                       phase_sleeve_override=ESTANFLACION_OVERRIDE, level_weight=level_weight)
    if not rot_sat.get("schemes"):
        return rot_base, info
    mb, ms = _scheme_metrics(rot_base), _scheme_metrics(rot_sat)
    wins = 0
    for sch, b in mb.items():
        v = ms.get(sch) or {}
        if None in (b.get("sharpe"), v.get("sharpe"), b.get("cagr"), v.get("cagr")):
            continue
        if v["sharpe"] - b["sharpe"] >= UNI_MIN_DSHARPE and v["cagr"] >= b["cagr"] - 0.05:
            wins += 1
    info.update({"assets": cols, "wins": wins, "base": mb, "with_satellite": ms,
                 "adopted": wins >= SAT_MIN_SCHEMES, "playbook_default": rot_sat.get("default")})
    # el playbook del satélite se publica siempre, para poder mostrarlo como opción
    keep = ("label", "portfolio", "by_phase", "playbook", "sleeve_mix")
    info["rotation"] = {"default": rot_sat.get("default"), "bands": rot_sat.get("bands"),
                        "schemes": {k: {kk: v.get(kk) for kk in keep}
                                    for k, v in rot_sat["schemes"].items()}}
    print(f"  ✓ satélite: mejora en {wins}/4 esquemas → "
          f"{'incorporado a «Qué comprar»' if info['adopted'] else 'queda como opción'}")
    return (rot_sat if info["adopted"] else rot_base), info




def buy_hold_table(X: pd.DataFrame, rot: dict, cls_map: dict) -> dict:
    """Cartera rotada frente a comprar y mantener cada activo de renta variable y el
    oro durante EL MISMO periodo (el de la rotación walk-forward). Con retornos en
    exceso sobre el tipo libre de riesgo, igual que las cifras de la cartera."""
    try:
        sch = rot["schemes"][rot["default"]]
        start = pd.Timestamp(sch["portfolio"]["from"])
    except Exception:
        return {}
    rows = []
    for c in X.columns:
        if cls_map.get(c) not in ("Renta variable", "Oro") and c != "Renta variable EE.UU. (mercado)":
            continue
        s = X[c].loc[start:]
        if s.notna().sum() < max(60, int(0.8 * len(X.loc[start:]))):
            continue
        p = perf(s)
        if p:
            rows.append({"name": c, **{k: p[k] for k in ("cagr", "cagr_tot", "vol", "sharpe", "maxdd")}})
    rows.sort(key=lambda r: -r["cagr"])
    return {"from": str(start.date()), "portfolio": {k: sch["portfolio"].get(k) for k in ("cagr", "cagr_tot", "vol", "sharpe", "maxdd")},
            "label": sch.get("label"), "assets": rows}


LEVEL_WEIGHTS = (0.5, 1.0)


def level_test(X, ameta, phases, probs_df, F, rot_base):
    """Pregunta de usuario: ¿por qué un sector con rentabilidad absoluta altísima en
    varias fases (semiconductores) casi no sale? Porque el motor puntúa la ventaja de
    la fase FRENTE A LA PROPIA MEDIA del activo, no su nivel absoluto. Aquí se prueba
    sumar al criterio de ordenación DENTRO del bloque de renta variable una fracción
    (level_weight) de su media histórica. El bloque frente a los demás se sigue
    puntuando con la ventaja pura. Se adopta si mejora el Sharpe >= UNI_MIN_DSHARPE en
    al menos 3 de 4 esquemas sin bajar el CAGR más de 0,05 puntos."""
    print("7d. Test de criterio de nivel absoluto dentro de renta variable…")
    cls_map = {k: v.get("class", "Otros") for k, v in ameta.items()}
    mb = _scheme_metrics(rot_base)
    info = {"base": mb, "variants": {}, "adopted_weight": 0.0}
    best, best_key, best_rot = 0.0, None, rot_base
    for lw in LEVEL_WEIGHTS:
        r = rotation(X, phases, cls_map, probs_df, F,
                     phase_sleeve_override=ESTANFLACION_OVERRIDE, level_weight=lw)
        m = _scheme_metrics(r)
        wins = 0
        for sch, b in mb.items():
            v = m.get(sch) or {}
            if None in (b.get("sharpe"), v.get("sharpe"), b.get("cagr"), v.get("cagr")):
                continue
            if v["sharpe"] - b["sharpe"] >= UNI_MIN_DSHARPE and v["cagr"] >= b["cagr"] - 0.05:
                wins += 1
        msh = float(np.mean([v["sharpe"] for v in m.values() if v.get("sharpe") is not None] or [0]))
        info["variants"][str(lw)] = {"wins": wins, "schemes": m}
        if wins >= UNI_MIN_SCHEMES and (best_key is None or (wins, msh) > best_key):
            best, best_key, best_rot = lw, (wins, msh), r
    info["adopted_weight"] = best
    print(f"  ✓ peso del nivel absoluto adoptado: {best} "
          + ", ".join("%s: %s/4" % (k, v["wins"]) for k, v in info["variants"].items()))
    return best_rot, info


def subsector_analysis(phases: pd.Series):
    """Análisis COMPLEMENTARIO (sección 8b): qué subsector, dentro de cada uno de
    los sectores que ya usa la cartera principal, ha pagado más en cada fase. Usa
    la MISMA metodología que la matriz de evidencia de la sección 6
    (conditional_stats: t de Newey-West, contracción de James-Stein para
    rel_shrunk, control de FDR — propio y separado del de la matriz principal,
    porque es una familia de contrastes distinta) sobre un universo de activos
    aparte (fetch_subsectors). No participa en means(), _sleeve_pick, rotation()
    ni en ningún otro punto de la selección o el backtest: es solo para ver un
    poco más allá de lo que ya recomienda la cartera, nunca para decidir por
    ella."""
    rets, meta, parent_of = fetch_subsectors()
    if not rets:
        return None
    X_sub = pd.DataFrame(rets)
    rows, stats = conditional_stats(
        X_sub, phases, meta,
        label="5b. Subsectores (complementario, no altera la cartera)…")
    by_sector: dict[str, dict[str, list]] = {}
    for row in rows:
        parent = parent_of.get(row["name"])
        if not parent:
            continue
        for phase in PHASES:
            d = row["phases"].get(phase)
            if not d or "ann" not in d:
                continue
            by_sector.setdefault(parent, {}).setdefault(phase, []).append({
                "name": row["name"], "ann": d["ann"], "rel": d.get("rel"),
                "rel_shrunk": d.get("rel_shrunk"), "grade": d.get("grade"),
                "n": d["n"],
            })
    for byphase in by_sector.values():
        for items in byphase.values():
            items.sort(key=lambda r: -(r["ann"] if r["ann"] is not None else -999.0))
    return {
        "por_sector": by_sector,
        "meta": {
            "n_subsectores": len(rows),
            "n_excluidos_mixtos": len(SUBSECTOR_EXCLUDED_MIXED),
            "cells": stats["cells"],
            "fdr_survivors": stats["fdr_survivors"],
        },
    }


# ======================================================================================
# 7. Backtest
# ======================================================================================

RF_M = None   # tipo libre de riesgo mensual (%), para pasar de exceso a retorno total


def perf(series: pd.Series) -> dict:
    s = series.dropna() / 100.0
    if s.size < 24:
        return {}
    curve = (1 + s).cumprod()
    cagr = curve.iloc[-1] ** (12 / s.size) - 1
    vol = s.std() * math.sqrt(12)
    _, _, t = newey_west(s.values * 100)
    roll12 = (1 + s).rolling(12).apply(np.prod, raw=True) - 1
    cagr_tot = None
    if RF_M is not None:
        rfa = RF_M.reindex(s.index)
        if rfa.notna().mean() > 0.8:
            tot = (1 + s + rfa.fillna(rfa.mean()) / 100.0).cumprod()
            cagr_tot = round(float(tot.iloc[-1] ** (12 / s.size) - 1) * 100, 2)
    return {"cagr_tot": cagr_tot, "cagr": round(float(cagr * 100), 2), "vol": round(float(vol * 100), 2),
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
    # un mínimo de diversificación inventado. Techo de 5, no 7: verificado con el
    # propio backtest que concentrarse en los cinco con mejor ir de la fase —
    # dejando fuera a los más débiles aunque también puntúen positivo, como pasaba
    # con Industria en Recuperación o con Industria y Tecnología en Reflación—
    # rinde mejor que diversificar hasta 7. Con datos reales, en los 4 esquemas de
    # reparto: CAGR +0,25 a +0,29 puntos, Sharpe igual o mejor, caída máxima
    # prácticamente igual (dentro de medio punto). Lo único que empeora un poco es
    # el número de años individuales que baten al S&P 500 (unos 2 de 47 menos en la
    # mayoría de esquemas): concentrar en menos nombres da más rentabilidad total a
    # cambio de alguna caída interanual más marcada — un cambio real, no ruido.
    # Excepción: en Estanflación el techo real es 3, no 5 (ver
    # ESTANFLACION_OVERRIDE más abajo, aplicado en la llamada a rotation()).
    "Renta variable": ({"Renta variable"}, 0.80, 1.00, 2, 5),
    # Oro físico y mineras de oro, las dos únicas exposiciones de la clase
    # "Oro" (ver FRENCH_49 y MARKET). Sin suelo: puede quedarse en 0, 1 o 2
    # nombres. Es un seguro táctico, no una posición obligatoria, y nunca
    # supera a la renta variable en peso (banda 0-20%).
    "Oro": ({"Oro"}, 0.00, 0.20, 0, 2),
}

# Excepción al techo de 5 de SLEEVES, solo para Estanflación (ver rotation(),
# parámetro phase_sleeve_override). Origen: un usuario señaló, con razón, que
# la cartera de renta variable llevaba demasiados años perdiendo contra el
# S&P 500 desde 2009 y pidió investigarlo en vez de aceptar la explicación
# fácil de "la diversificación cuesta rentabilidad en mercados alcistas
# concentrados". El propio laboratorio (ver lab["Estanflación"]["sleeves"]
# ["Renta variable"]) ya medía la causa: persistencia NEGATIVA entre la
# primera y segunda mitad cronológica de la fase (rank_ic -0,27, asset_ic
# -0,44) -- la ÚNICA de las 4 fases donde "lo que fue mejor en esta fase
# antes" predice lo CONTRARIO de lo que pasa después, no simplemente "sin
# relación". Las otras tres fases muestran persistencia POSITIVA real
# (Sobrecalentamiento +0,51, Reflación +0,30) o débil (Recuperación -0,18,
# dentro de ruido) -- el problema es específico de Estanflación, no un fallo
# general del método de selección.
#
# Probado con datos reales, en este orden:
#   1. Diversificar MÁS en Estanflación (todo el universo, o una banda ancha
#      de 7): empeora todo lo medible -- Sharpe, CAGR, caída máxima, Y el
#      propio edge de Estanflación desde 2009 (-0,16pp/mes de partida a
#      -0,25/-0,30pp/mes). Diluir hacia sectores de peor "information ratio"
#      (ventaja/volatilidad) no sustituye tener razón, empeora las cosas.
#   2. Reemplazar la ventaja condicionada a la fase por momentum puro (media
#      simple de los últimos 6 o 12 meses, sin condicionar a qué fase fue
#      cada uno): la peor de todas las variantes probadas (Sharpe 0,64,
#      caída máxima -44,6%, edge -0,47pp/mes) -- el momentum no sustituye a
#      la señal de fase aquí.
#   3. CONCENTRAR más (lo contrario de 1): 2 o 3 sectores fijos en vez de la
#      banda 2-5 normal. Aislado con un control (2 fijos en las OTRAS tres
#      fases, dejando Estanflación intacta: el Sharpe EMPEORA a 0,62 -- el
#      efecto no es general, es específico de concentrar esta fase). 3 fijos
#      es la variante ganadora: mejora el Sharpe en los 4 esquemas de
#      reparto a la vez (aunque modesto, +0,01 a +0,02 -- no es una bala de
#      plata) y reduce el edge de Estanflación desde 2009 a menos de la
#      mitad en los 4 esquemas (-0,16/-0,18/-0,27/-0,17 -> -0,04/-0,07/
#      -0,13/-0,06 pp/mes). El coste real: caída máxima histórica algo peor
#      en los 4 esquemas (del orden de 1 a 3 puntos) -- pero ocurre en
#      1982-07 (Volcker), no en el periodo reciente que motivó la pregunta.
#      Una banda (2,3), dejando que el propio mecanismo eligiera entre 2 y 3
#      según cuántos puntuaran positivo, quedó peor que fijarlo siempre a 3
#      -- alternar mes a mes entre 2 y 3 nombres no capturaba lo bueno de
#      ninguno de los dos extremos.
#
# Esto NO convierte Estanflación en una fase ganadora -- sigue sin batir al
# mercado ahí (edge aún negativo) -- pero reduce sustancialmente cuánto
# pierde, con el mismo nivel de riesgo. Ver METODOLOGIA.md para la versión
# larga.
ESTANFLACION_OVERRIDE = {("Estanflación", "Renta variable"): (3, 3)}

# Reloj de renta fija (ver rotation()/laboratory() con sleeves=SLEEVES_FI): un único
# bloque, banda fija al 100% -- no compite con renta variable ni oro, es un reloj
# aparte que nunca se combina con el de arriba (ver docs/assets/app.js, clockMode).
#
# Techo de 2, igual que el suelo -- así que el bloque sostiene SIEMPRE los dos
# activos con mejor ventaja de fase, ni uno más -- verificado con el propio
# backtest walk-forward sobre datos reales, probando cada techo entre 2 y 10 sobre
# las hasta 10 exposiciones únicas del universo de clase "Renta fija" (13 activos,
# 3 pares que se solapan vía ASSET_OVERLAP). El techo de 2 gana con claridad en los
# 4 esquemas de reparto A LA VEZ y en las 5 métricas a la vez -- no es un esquema
# concreto sacando ventaja por azar. Con datos reales, techo 2 frente a techo 5
# (referencia: el mismo techo que usa renta variable), esquema Equiponderado: CAGR
# 4,01% frente a 3,14%, Sharpe 0,63 frente a 0,48, caída máxima -27,7% frente a
# -31,6%, peor 12 meses -19,4% frente a -23,1% -- el mismo patrón, sin excepción,
# en Inverso de la volatilidad, Por puesto y Mitad y mitad.
#
# La diferencia con renta variable (techo 5, ver arriba) tiene una explicación
# económica, no es a lo mejor porque sí: los sectores de bolsa son exposiciones
# genuinamente distintas entre sí (Energía no se mueve como Tecnología), así que
# diversificar entre varios reduce riesgo idiosincrático real. Casi todo el universo
# de renta fija, en cambio, comparte el mismo factor de fondo -- tipos de interés y
# duración -- así que añadir un tercer o cuarto activo no añade una exposición
# nueva de verdad: solo diluye la apuesta de fase hacia la media del conjunto.
# Suelo de 2 por el mismo motivo que en renta variable, no por lo que midió el
# backtest: nunca una única posición, aunque puntúe mejor que cualquier otra.
#
# "Liquidez" SÍ entra en las clases del bloque -- a diferencia de renta variable,
# donde queda fuera vía NOT_SELECTABLE (ver el comentario junto a esa constante,
# más abajo, y por qué el motivo NO es el mismo aquí). Probado con datos reales,
# con el propio techo de 2: dejar que Liquidez (letras 3m) compita por un hueco
# mejora el Sharpe en los 4 esquemas a la vez (0,63->0,69, 0,60->0,68, 0,63->0,70,
# 0,62->0,71) y reduce la caída máxima con fuerza (p.ej. Inverso de la volatilidad,
# -29,6%->-15,2%), con el CAGR prácticamente plano. Entra solo en Sobrecalentamiento
# (mitad del bloque, nunca desplaza a los dos activos en las otras tres fases) --
# tiene sentido: es la fase en la que subir tipos presiona a la baja a toda la
# curva a la vez, y un ancla de duración casi nula amortigua sin sacrificar
# apenas rentabilidad. Comprobado también que NO reproduce el problema de renta
# variable al subir el techo con Liquidez ya elegible (3 o 4): empeora en las
# mismas métricas que ya empeoraba sin ella, así que el techo se queda en 2.
#
# "Crédito ultracorto plazo (ICSH)" se añadió, con la misma exigencia de prueba
# real, para atacar el tramo bajista de 2021-2024 (2022 fue el peor mercado
# bajista de bonos en décadas: hasta el propio AGG cayó -14,24% ese año). Antes
# de añadirlo se probaron y RECHAZARON dos hipótesis con datos reales: (1)
# préstamos bancarios a tipo flotante (BKLN), que empeoraba el resultado --
# 2022 no fue solo un shock de tipos, también de diferencial de crédito, y los
# préstamos bancarios sí tienen riesgo de crédito (cayeron a la par que el
# resto en los peores meses); (2) aflojar el suelo de 2 a 1 para que Liquidez
# pudiera quedarse sola al 100%, que también empeoraba -- renunciar a toda
# diversificación justo cuando peor pinta no evita la caída, solo la
# opcionalidad al alza. ICSH sí funciona: grado de inversión (no el riesgo de
# crédito que hundió a BKLN) y ~6 meses de duración (ni el riesgo de tipos de
# un bono largo ni el de una letra a 3 meses sin apenas rendimiento). Con
# datos reales, esquema Inverso de la volatilidad: Sharpe 0,68->0,72, caída
# máxima -13,3%->-9,7%, peor 12 meses -9,2%->-6,5%, CAGR prácticamente plano
# o mejor -- mejora en los 4 esquemas a la vez, no solo en uno. Entra solo en
# Sobrecalentamiento, compitiendo con Liquidez por el mismo hueco defensivo
# (gana el que puntúe mejor cada mes, ninguno tiene preferencia fija).
# Confirmado también que el techo sigue en 2 con ICSH ya en el universo: el
# Sharpe cae de forma monótona al subir el techo a 3, 4 o 5 en los 4 esquemas
# a la vez, el mismo patrón que sin él.
SLEEVES_FI = {
    "Renta fija": ({"Renta fija", "Liquidez"}, 1.00, 1.00, 2, 2),
}

# Índices agregados: sirven de referencia, no de posición. Si entran en la selección
# copan siempre el bloque de renta variable y no hay rotación sectorial ninguna.
# La clase "Índice regional" no entra en ningún bloque: los índices agregados y de
# país sirven de referencia, no de posición. Si compiten con los sectores los barren
# siempre, porque un índice diversificado tiene mejor rentabilidad por unidad de
# riesgo que cualquier sector suelto, y entonces no hay rotación sectorial ninguna.
#
# "Otros sectores" queda fuera de renta variable porque es un cajón de sastre, no
# una exposición con entidad propia (ver FRENCH_49/SUBSECTOR_EXCLUDED_MIXED).
#
# "Liquidez (letras 3m)" queda fuera de renta variable, pero SÍ entra en renta fija
# (ver SLEEVES_FI) -- el motivo no es que "no tenga señal", es que el mecanismo de
# selección la trata mal cuando compite contra sectores de bolsa. Su exceso no es
# una resta tautológica contra sí misma (una versión anterior de este comentario lo
# decía así, impreciso): es FRED TB3MS/12 (letra a 3 meses) menos el tipo sin
# riesgo global, que es el de Ken French a 1 mes -- un spread real entre dos
# referencias de tipo a corto, diminuto (0,11% anualizado de media, 0,15% de
# volatilidad) pero no exactamente cero. El problema es justo esa volatilidad
# casi nula: al ordenar por rentabilidad entre volatilidad, ese cociente se
# dispara frente a cualquier sector de bolsa (15-20% de volatilidad típica) y se
# cuela como primera posición; el reparto por inverso de volatilidad, comprobado
# con datos reales, le daba un peso enorme -- la cartera de renta variable acababa
# con un cuarto del dinero parado y la volatilidad hundida muy por debajo de lo
# que aporta en rentabilidad real. Frente a renta fija (4-7% de volatilidad
# típica, no 15-20%) el mismo mecanismo pesa mucho menos y, comprobado con el
# propio backtest (ver SLEEVES_FI), no reproduce ese problema: entra en un único
# hueco de dos, en una única fase, y mejora el resultado en vez de acapararlo.
NOT_SELECTABLE = {"Otros sectores"}

# Suelo de volatilidad para el reparto y la ordenación. Sin él, cualquier activo
# muy poco volátil acapara la cartera por el mismo mecanismo.
VOL_FLOOR_Q = 0.20

# Vida media de la ponderación temporal, en meses. Una media plana sobre cien años
# trata igual a 1935 y a 2025, y la composición de los sectores ha cambiado por
# completo: "Tecnología" en French son máquinas de oficina en los años treinta y
# semiconductores hoy. Con vida media de cinco años, lo reciente pesa el doble que
# lo de hace un lustro y más de mil veces más que lo de hace cincuenta años, sin
# que nada llegue a desaparecer. Se aplica igual a todos los activos.
#
# Antes eran diez años. Con diez, un sector recién salido de un año horrible
# (p.ej. tecnología tras 2022) tardaba demasiado en dejar de arrastrar esa mala
# racha en su ventaja condicionada, incluso cuando ya llevaba meses recuperándose.
# Verificado con el backtest real: con cinco años el CAGR sube en los cuatro
# esquemas de reparto (9,6-9,7% -> 9,8-9,9%), el máximo drawdown mejora (~-38% ->
# ~-37%) y sube el número de años que baten al S&P 500 (26-28/47 -> 27-29/47). No
# es gratis: reacciona más rápido, así que también es más sensible a rachas cortas
# que luego no se repiten.
HALF_LIFE_M = 60

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


def _sleeve_pick(mu, vol, raw_phase, avail, classes, cls_map, n_min, n_max, mu_rank=None):
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
    ellos es cómo se reparte el dinero entre los ya elegidos.

    Antes de nada, ASSET_OVERLAP quita del candidato más débil de cada par que
    solapa exposición económica (hoy solo Semiconductores/Tecnología): que
    compitan los dos sería, en parte, contar la misma exposición dos veces, así
    que solo sigue en carrera el que muestre mejor ir — el mismo criterio que
    decide cualquier otro desempate de esta función, no una regla especial."""
    # mu_rank: puntuación SOLO para ordenar/seleccionar dentro del bloque (puede incluir
    # parte del nivel absoluto, ver rotation(level_weight=...)); `mu` (ventaja de fase
    # pura) sigue mandando en la puntuación del bloque frente a los demás.
    rmu = mu if mu_rank is None else mu_rank
    cand = [c for c in avail
            if cls_map.get(c) in classes and c not in NOT_SELECTABLE]
    if not cand:
        return [], 0.0
    for child, parent in ASSET_OVERLAP.items():
        if child in cand and parent in cand:
            ir_child = rmu.get(child, -1e9) / max(abs(vol.get(child, 0.0)), 1e-9)
            ir_parent = rmu.get(parent, -1e9) / max(abs(vol.get(parent, 0.0)), 1e-9)
            cand.remove(child if ir_child <= ir_parent else parent)
    vc = vol.reindex(cand).replace(0, np.nan)
    floor = vc.quantile(VOL_FLOOR_Q) if vc.notna().sum() > 2 else None
    if floor and floor > 0:
        vc = vc.clip(lower=floor)
    ir = (rmu.reindex(cand) / vc).replace([np.inf, -np.inf], np.nan).dropna()
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


def _sleeve_weights(scores: dict, sleeves: dict | None = None) -> dict:
    """Reparte el 100 % entre bloques en proporción a lo que puntúa cada uno en la
    fase, respetando las bandas. Una puntuación negativa se trata como cero: ese
    bloque baja a su mínimo, y el oro puede quedarse fuera del todo.

    NOTA: una versión anterior forzaba la volatilidad de la cartera a igualar la de
    un benchmark externo (primero 60/40, antes de eso el propio mercado). Fue un
    error: el reparto proporcional ya sale con una volatilidad muy parecida a la del
    bloque dominante por sí solo, y forzarla dejaba la renta variable clavada en su
    suelo, costando rentabilidad sin comprar nada a cambio.

    `sleeves` por defecto es el diccionario global SLEEVES (renta variable + oro);
    se pasa uno distinto para reutilizar el mismo reparto con otro conjunto de
    bloques (por ejemplo SLEEVES_FI, un único bloque de renta fija al 100%).
    """
    sleeves = SLEEVES if sleeves is None else sleeves
    names = list(sleeves)
    lo = {k: sleeves[k][1] for k in names}
    hi = {k: sleeves[k][2] for k in names}
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
             min_train: int = 120, sleeves: dict | None = None,
             bench_name: str = "Renta variable EE.UU. (mercado)",
             bd_name: str = "Treasury 10 años",
             include_6040: bool = True,
             phase_sleeve_override: dict | None = None,
             level_weight: float = 0.0,
             level_sleeves: frozenset = frozenset({"Renta variable"})) -> dict:
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
    son más ruidosas.

    `sleeves`/`bench_name`/`bd_name`/`include_6040` por defecto reproducen EXACTAMENTE
    la cartera de renta variable + oro; se pasan valores distintos para reutilizar el
    mismo motor de backtest con otro conjunto de bloques (ver SLEEVES_FI, el reloj de
    renta fija). `include_6040=False` omite el 60/40 de contexto, que no tiene sentido
    como referencia de una cartera que ya es 100% renta fija.

    `phase_sleeve_override`: suelo/techo de un bloque PARA UNA FASE CONCRETA, distinto
    del de `sleeves` (ver ESTANFLACION_OVERRIDE más abajo y por qué Estanflación tiene
    uno propio)."""
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

    sleeves = SLEEVES if sleeves is None else sleeves
    eq_c, bd_c = bench_name, bd_name
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
        grand_t = _wmean(hist, _ew(hist, hist.index[-1]))
        picks, scores = {}, {}
        for name, (classes, lo, hi, n_min, n_max) in sleeves.items():
            if phase_sleeve_override and (sig, name) in phase_sleeve_override:
                n_min, n_max = phase_sleeve_override[(sig, name)]
            mr = None
            if level_weight and name in level_sleeves:
                mr = mu + level_weight * grand_t
            picks[name], scores[name] = _sleeve_pick(
                mu, vol, raw_phase, avail, classes, cls_map, n_min, n_max, mu_rank=mr)
        if not any(picks.values()):
            continue

        for sch in SCHEMES:
            inner = {name: _weights(top, vol, sch).to_dict()
                     for name, top in picks.items() if top}
            budgets = _sleeve_weights(scores, sleeves)
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
    # La referencia primaria es siempre el propio benchmark de este reloj (renta
    # variable EE.UU. para el de acciones, el agregado de bonos para el de renta
    # fija), no un 60/40 que ninguna de las dos carteras tiene. El 60/40 se
    # conserva aparte, solo como contexto adicional, y solo cuando include_6040.
    bench = eq.reindex(dates) if eq is not None else None
    bench_6040 = ((0.6 * eq + 0.4 * bd).reindex(dates)
                  if include_6040 and eq is not None and bd is not None else None)
    hp = pd.Series(held, index=dates)
    bench_valid = bench.dropna() if bench is not None else None
    bench_annual = _annual(bench_valid) if bench_valid is not None else {}
    # Si el benchmark cotiza desde más tarde que la propia rotación —el caso real:
    # el agregado de bonos (AGG) tiene datos desde 2003, pero el universo de renta
    # fija arranca antes vía rendimientos FRED— comparar curva, cifras y año a año
    # desde el inicio de la rotación mostraría al benchmark plano (a 100, sin
    # moverse) durante años en los que sencillamente no existía: no es una caída
    # a cero, es que no cotizaba. La selección de cada mes sigue aprendiendo de
    # todo el histórico disponible hasta esa fecha (eso no cambia); lo que se
    # ajusta es desde cuándo se MUESTRA el resultado frente al benchmark, para
    # comparar siempre desde la fecha en la que los dos cotizan.
    cmp_start = bench_valid.index[0] if bench_valid is not None and len(bench_valid) else None

    vol_all = ew_vol(X)
    out_schemes = {}
    for sch, label in SCHEMES.items():
        R = pd.Series(rets[sch], index=dates).dropna()
        turn_s = pd.Series(turn[sch], index=dates)
        if cmp_start is not None:
            R = R[R.index >= cmp_start]
            turn_s = turn_s[turn_s.index >= cmp_start]
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
            for sl, (classes, lo, hi, n_min, n_max) in sleeves.items():
                if phase_sleeve_override and (phase, sl) in phase_sleeve_override:
                    n_min, n_max = phase_sleeve_override[(phase, sl)]
                picks[sl], scores[sl] = _sleeve_pick(
                    mu, vol_all, raw_phase, avail, classes, cls_map, n_min, n_max)
            inner_pb = {sl: _weights(top, vol_all, sch).to_dict()
                        for sl, top in picks.items() if top}
            budgets = _sleeve_weights(scores, sleeves)
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
            "turnover": round(float(turn_s.mean() * 100), 1),
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
                      for k, v in sleeves.items()},
            # Suelo/techo REAL de cada bloque (n_min, n_max de SLEEVES), para que el
            # frontend nunca tenga que citar el número a mano — el bug real que motivó
            # esto: el texto de la web decía "entre 2 y 7 sectores" bastante después de
            # que el código ya usara 5, porque nadie sincronizó el literal a mano.
            "counts": {k: [v[3], v[4]] for k, v in sleeves.items()}}



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
               k_pick: int = 5, max_universe: int = 18,
               sleeve_defs: dict | None = None) -> dict:
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

    `sleeve_defs` por defecto son los bloques {nombre: clases} de la cartera de
    renta variable + oro; se pasa un dict distinto (p.ej. {"Renta fija": {"Renta
    fija"}}) para repetir exactamente el mismo análisis sobre otro conjunto de
    bloques, como el reloj de renta fija.
    """
    print("8. Laboratorio de combinaciones…")
    out = {}
    sleeve_defs = sleeve_defs if sleeve_defs is not None else {
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
        first_sleeve = out[phase]["sleeves"].get(next(iter(sleeve_defs), ""), {})
        print(f"  · {phase:<20} {len(months):>4} meses · "
              f"persistencia {first_sleeve.get('rank_ic')} · "
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

def _factor_model(df: pd.DataFrame) -> dict:
    Z, ind_info = build_blocks(df)
    F, pca = build_factors(Z)
    F = F.dropna(subset=["growth", "inflation"])
    phases = pd.Series([classify(a, b) for a, b in zip(F["growth"], F["inflation"])],
                       index=F.index, name="phase")
    sg = float(F["growth"].diff(HORIZON_M).std())
    si = float(F["inflation"].diff(HORIZON_M).std())
    # Probabilidad de cada fase en cada mes; se desplaza un mes: en t solo se conoce t-1.
    prob_rows = {d: phase_probs(float(a), float(b), sg, si)
                 for d, a, b in zip(F.index, F["growth"], F["inflation"])}
    probs_df = pd.DataFrame(prob_rows).T.shift(1)
    return {"Z": Z, "ind_info": ind_info, "F": F, "pca": pca, "phases": phases,
            "sg": sg, "si": si, "probs_df": probs_df}


def choose_pca_variant(df, X, ameta, picks_by_block: dict, report: dict):
    """Más series explican más varianza, pero eso NO garantiza un reloj más útil. Se
    prueban las combinaciones (base, +crecimiento, +inflación, +ambas) con la cartera
    walk-forward y se adopta la que mejora el Sharpe >= UNI_MIN_DSHARPE en al menos
    3 de 4 esquemas sin bajar el CAGR más de 0,05 puntos; si ninguna, se queda la base.
    Los bloques «leading» no alimentan la fase y se adoptan si mejoran su varianza."""
    base_series = list(SERIES)
    cls_map = {k: v.get("class", "Otros") for k, v in ameta.items()}
    variants = {"base": []}
    g, i = picks_by_block.get("growth", []), picks_by_block.get("inflation", [])
    if g:
        variants["crecimiento"] = g
    if i:
        variants["inflación"] = i
    if g and i:
        variants["ambas"] = g + i
    results, models = {}, {}
    for name, extra in variants.items():
        SERIES[:] = base_series + extra
        m = _factor_model(df)
        models[name] = m
        results[name] = _scheme_metrics(rotation(
            X, m["phases"], cls_map, m["probs_df"], m["F"],
            phase_sleeve_override=ESTANFLACION_OVERRIDE))
    base = results["base"]
    best, best_key = "base", None
    for name, res in results.items():
        if name == "base":
            continue
        wins = 0
        for sch, b in base.items():
            v = res.get(sch) or {}
            if None in (b.get("sharpe"), v.get("sharpe"), b.get("cagr"), v.get("cagr")):
                continue
            if v["sharpe"] - b["sharpe"] >= UNI_MIN_DSHARPE and v["cagr"] >= b["cagr"] - 0.05:
                wins += 1
        mean_sh = float(np.mean([v["sharpe"] for v in res.values() if v.get("sharpe") is not None] or [0]))
        report.setdefault("variants", {})[name] = {"wins": wins, "schemes": res}
        if wins >= UNI_MIN_SCHEMES and (best_key is None or (wins, mean_sh) > best_key):
            best, best_key = name, (wins, mean_sh)
    report.setdefault("variants", {})["base"] = {"schemes": base}
    report["adopted_variant"] = best
    # leading: no afecta a la fase; se adopta si sube la varianza (informativo)
    SERIES[:] = base_series + variants[best]
    m = models[best]
    if best == "base" and picks_by_block.get("leading"):
        SERIES.extend(picks_by_block["leading"])
        m = _factor_model(df)
        report["leading_adopted"] = [sp.fred_id for sp in picks_by_block["leading"]]
    resumen = ", ".join("%s: %s/4" % (k, v.get("wins", "-")) for k, v in report["variants"].items())
    print(f"  ✓ variante de PCA adoptada: {best} ({resumen})")
    return m


def main() -> None:
    t0 = time.time()
    df, raw_meta = fetch_macro()
    X, ameta = fetch_assets(df)
    pca_research, picks = {"error": "no ejecutado"}, {}
    try:
        df, cand_meta = fetch_candidates(df)
        raw_meta.update(cand_meta)
        pca_research, picks = select_candidates(df)
    except Exception as exc:  # la ampliación es opcional: nunca debe tumbar el modelo
        warn(f"ampliación del PCA omitida: {exc}")
        pca_research = {"error": str(exc)}
    model = None
    base_series_snapshot = list(SERIES)
    if picks:
        try:
            model = choose_pca_variant(df, X, ameta, picks, pca_research)
        except Exception as exc:
            warn(f"elección de variante de PCA omitida: {exc}")
            pca_research["error"] = str(exc)
            SERIES[:] = base_series_snapshot
    if model is None:
        model = _factor_model(df)
    Z, ind_info, F, pca = model["Z"], model["ind_info"], model["F"], model["pca"]
    phases, sg, si, probs_df = model["phases"], model["sg"], model["si"], model["probs_df"]
    g, i = float(F["growth"].iloc[-1]), float(F["inflation"].iloc[-1])
    probs = phase_probs(g, i, sg, si)
    rank = sorted(probs.items(), key=lambda kv: kv[1], reverse=True)
    conf = rank[0][1] - rank[1][1]

    # Activos nuevos: se prueban y, si mejoran la cartera, se incorporan al universo.
    Xe, emeta, elog = fetch_extended()
    try:
        X, ameta, universe = universe_test(X, ameta, Xe, emeta, phases, probs_df, F)
    except Exception as exc:
        warn(f"test del universo omitido: {exc}")
        universe = {"error": str(exc), "adopted": []}
    assets, astats = conditional_stats(X, phases, ameta)
    bt = backtest(X, phases)
    cls_map = {k: v.get("class", "Otros") for k, v in ameta.items()}
    rot = rotation(X, phases, cls_map, probs_df, F,
                   phase_sleeve_override=ESTANFLACION_OVERRIDE)
    buy_hold = buy_hold_table(X, rot, cls_map)
    try:
        rot, level_info = level_test(X, ameta, phases, probs_df, F, rot)
    except Exception as exc:
        warn(f"test de nivel absoluto omitido: {exc}")
        level_info = {"error": str(exc), "adopted_weight": 0.0}
    try:
        rot, satellite = satellite_test(X, Xe, emeta, ameta, phases, probs_df, F, rot,
                                        level_info.get("adopted_weight", 0.0))
    except Exception as exc:
        warn(f"satélite táctico omitido: {exc}")
        satellite = {"error": str(exc), "adopted": False}
    lab = laboratory(X, phases, cls_map)
    # Reloj de renta fija: mismo motor, otro conjunto de bloques (ver SLEEVES_FI) y
    # otro benchmark (el agregado de bonos, no el S&P 500). include_6040=False: un
    # 60/40 no tiene sentido como referencia de una cartera ya 100% renta fija.
    # Nunca se combina con rot/lab -- son dos relojes independientes, ver app.js.
    rot_fi = rotation(X, phases, cls_map, probs_df, F, sleeves=SLEEVES_FI,
                      bench_name="Renta fija EE.UU. (mercado)", include_6040=False)
    lab_fi = laboratory(X, phases, cls_map, k_pick=2,
                        sleeve_defs={"Renta fija": {"Renta fija", "Liquidez"}})
    val = validation(df, F, phases)
    rec = recession_model(df, F.index)
    subsectors = subsector_analysis(phases)
    holdings = fetch_holdings()
    extended = extended_analysis(phases, (Xe, emeta, elog))
    now = now_edge(X, probs_df, probs, ameta)

    p1, p2 = rank[0][0], rank[1][0]

    def consensus_for(sleeves):
        # Restringido a la clase invertible de la cartera correspondiente: el
        # consenso alimenta directamente "qué comprar ahora" de CADA reloj y no
        # tiene sentido que sugiera clases que esa cartera ya no toca.
        classes = {c for cls in sleeves.values() for c in cls[0]}
        out = []
        for a in assets:
            if a["class"] not in classes:
                continue
            d1, d2 = a["phases"].get(p1, {}), a["phases"].get(p2, {})
            if str(d1.get("grade", "0")).startswith("+") and str(d2.get("grade", "0")).startswith("+"):
                out.append({"name": a["name"], "class": a["class"],
                            "g1": d1["grade"], "g2": d2["grade"],
                            "r1": d1.get("rel"), "r2": d2.get("rel")})
        out.sort(key=lambda r: -(r["r1"] or 0))
        return out

    consensus = consensus_for(SLEEVES)
    consensus_fi = consensus_for(SLEEVES_FI)

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
            "warnings": WARNINGS, "asset_log": ASSET_LOG, "bridge": BRIDGE_INFO, "debug_tails": DEBUG_TAILS,
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
            # Fuerza de la lectura de fase: Fuerte >= 0,6; Moderada 0,3-0,6; Débil < 0,3.
            "call_strength": ("Fuerte" if conf >= 0.6 else "Moderada" if conf >= 0.3 else "Débil"),
            "edge": pca.get("_edge"),
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
        "consensus_fi": consensus_fi[:14],
        "backtest": bt, "rotation": rot, "lab": lab,
        "rotation_fi": rot_fi, "lab_fi": lab_fi,
        "validation": val, "subsectors": subsectors, "holdings": holdings,
        "extended": extended, "universe": universe, "satellite": satellite, "level_test": level_info, "buy_hold": buy_hold, "now_edge": now, "pca_research": pca_research,
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
