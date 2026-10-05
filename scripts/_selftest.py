"""Autotest sin red: inyecta series sintéticas y comprueba que el pipeline
produce un data.json completo y coherente. No se despliega, solo valida lógica."""
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
os.environ["OUT_PATH"] = "/tmp/test_data.json"

import build_data as bd  # noqa: E402

rng = np.random.default_rng(7)
IDX_D = pd.date_range("1959-01-01", "2026-08-01", freq="D")
IDX_M = pd.date_range("1959-01-31", "2026-08-31", freq="ME")

# ciclo macro latente para que los factores tengan estructura real
t = np.arange(len(IDX_M))
cycle = np.sin(2 * np.pi * t / 78) + 0.4 * np.sin(2 * np.pi * t / 31)
infl_cycle = np.sin(2 * np.pi * t / 78 - 1.1)


def synth(sid: str):
    if sid == "USREC":
        return pd.Series((cycle < -0.85).astype(float), index=IDX_M, name=sid)
    if sid in ("T5YIE", "T5YIFR", "DCOILWTICO", "VIXCLS", "T10Y3M", "T10Y2Y",
               "BAMLH0A0HYM2", "NFCI", "DGS2", "DGS10", "DGS30"):
        base = {"T5YIE": 2.2, "T5YIFR": 2.3, "DCOILWTICO": 60, "VIXCLS": 19,
                "T10Y3M": 1.2, "T10Y2Y": 0.9, "BAMLH0A0HYM2": 4.5,
                "NFCI": 0.0, "DGS2": 3.0, "DGS10": 3.8, "DGS30": 4.2}[sid]
        drive = np.interp(np.arange(len(IDX_D)),
                          np.linspace(0, len(IDX_D), len(IDX_M)), cycle)
        v = base + 0.7 * drive + rng.normal(0, 0.15, len(IDX_D))
        if sid == "DCOILWTICO":
            v = base * np.exp(0.35 * drive + rng.normal(0, 0.03, len(IDX_D)).cumsum() * 0.01)
        return pd.Series(np.abs(v), index=IDX_D, name=sid)
    if sid.startswith("BAML") and sid.endswith("TRIV"):
        r = 0.004 + 0.01 * np.gradient(cycle) + rng.normal(0, 0.012, len(IDX_M))
        return pd.Series(100 * np.cumprod(1 + r), index=IDX_M, name=sid)
    spec = next((s for s in bd.SERIES if s.fred_id == sid), None)
    block = spec.block if spec else "growth"
    drive = cycle if block != "inflation" else infl_cycle
    if sid in ("CFNAIMA3", "USSLIND", "MEDCPIM158SFRBCLE", "PCETRIM12M159SFRBDAL",
               "TCU", "UMCSENT", "AWHMAN", "UNRATE", "TB3MS", "FEDFUNDS",
               "BAA", "AAA", "DFII10", "MORTGAGE30US"):
        base = {"CFNAIMA3": 0, "USSLIND": 1.5, "MEDCPIM158SFRBCLE": 2.8,
                "PCETRIM12M159SFRBDAL": 2.4, "TCU": 78, "UMCSENT": 85,
                "AWHMAN": 40.5, "UNRATE": 5.5, "TB3MS": 3.0, "FEDFUNDS": 3.2,
                "BAA": 6.5, "AAA": 5.5, "DFII10": 1.6, "MORTGAGE30US": 6.5}[sid]
        return pd.Series(base + 1.2 * drive + rng.normal(0, 0.2, len(IDX_M)),
                         index=IDX_M, name=sid)
    growth = 0.003 + 0.004 * drive + rng.normal(0, 0.004, len(IDX_M))
    return pd.Series(100 * np.cumprod(1 + growth), index=IDX_M, name=sid)


def fake_french(url, hint=""):
    if "49_Industry" in url:
        cols = list(bd.FRENCH_49) + list(bd.SUBSECTOR_MAP)
    elif "12_Industry" in url:
        cols = list(bd.FRENCH_IND)
    elif "Portfolios_Formed_on_ME" in url:
        cols = ["Lo 20", "Qnt 2"]
    elif "Factors" in url:
        cols = ["Mkt-RF", "SMB", "HML", "RF"]
    else:
        cols = ["Mom"]
    data = {}
    for c in cols:
        if c == "RF":
            data[c] = 0.25 + 0.1 * cycle
        else:
            data[c] = 0.7 + 2.5 * np.gradient(cycle) * (1 + 0.3 * rng.random()) \
                      + rng.normal(0, 3.5, len(IDX_M))
    return pd.DataFrame(data, index=IDX_M), None


def fake_yahoo(sym):
    if sym in ("MUB", "MBB", "BTC-USD", "MCHI"):
        return None, "429 Too Many Requests (simulado)"
    n = len(IDX_M) if sym not in ("HYG", "LQD", "TIP") else 240
    idx = IDX_M[-n:]
    return pd.Series(0.5 + 2.0 * np.gradient(cycle)[-n:] + rng.normal(0, 3.0, n),
                     index=idx), None


def fake_stooq(ticker):
    if ticker in ("mub.us", "mbb.us"):
        return None, "limite diario excedido (simulado)"
    return pd.Series(0.5 + 2.0 * np.gradient(cycle) + rng.normal(0, 3.0, len(IDX_M)),
                     index=IDX_M), None


def fred_ragged(sid):
    """Reproduce el borde irregular real: nóminas con 2 meses más que el resto y
    USSLIND descontinuada en 2020-02."""
    s = synth(sid)
    if s is None:
        return None, "sintetico"
    if sid == "PAYEMS":
        ext = pd.date_range(s.index[-1], periods=3, freq="ME")[1:]
        s = pd.concat([s, pd.Series([s.iloc[-1] * 0.97, s.iloc[-1] * 0.94], index=ext)])
    if sid == "USSLIND":
        s = s[s.index <= "2020-02-29"]
    return s, None


bd.fred_series = fred_ragged
bd.french_zip = fake_french
bd.stooq_monthly = fake_stooq
bd.yahoo_monthly = fake_yahoo
bd.main()

d = json.load(open("/tmp/test_data.json", encoding="utf-8"))
assert d["current"]["phase"] in bd.PHASES
assert abs(sum(d["current"]["probs"].values()) - 1) < 5e-4, "probabilidades no suman 1"
assert len(d["history"]) > 500
assert len(d["indicators"]) >= 20
assert len(d["assets"]) >= 10
assert d["backtest"].get("long"), "backtest vacío"
assert d["validation"]["transition"]
print("\nOK — claves:", sorted(d.keys()))
print("fase:", d["current"]["phase"], "| conf:", d["current"]["confidence"])
print("activos:", len(d["assets"]), "| larga:", d["backtest"]["long"])
print("spread:", d["backtest"]["spread"])
print("escalada:", d["backtest"]["scaled"])
print("in-sample:", d["backtest"]["in_sample"])
print("stats casillas:", d["asset_stats"])
print("rotacion:", d["validation"].get("rotation"))
fallos=[a for a in d["meta"]["asset_log"] if a["status"]!="ok"]
print("activos no cargados:", [(a["name"],a["status"]) for a in fallos])
clases = {}
for a in d["assets"]:
    clases[a["class"]] = clases.get(a["class"], 0) + 1
print("por clase:", clases)
nombres = {a["name"] for a in d["assets"]}
assert any("Oro" in n for n in nombres), "falta el oro"
assert any(a["class"] == "Real / alternativos" for a in d["assets"]), "sin activos reales"
assert d["backtest"].get("tilt"), "falta la cartera inclinada"
ids = {i["id"] for i in d["indicators"]}
assert "BAA_AAA" in ids, "falta el diferencial derivado"
print("indicadores:", len(d["indicators"]), "/", d["meta"]["series_total"])
print("validación NBER:", d["validation"].get("nber"))

sub = d.get("subsectors")
assert sub and sub.get("por_sector"), "faltan subsectores (análisis complementario)"
assert sub["meta"]["n_subsectores"] == len(bd.SUBSECTOR_MAP), \
    "no se cargaron todos los subsectores esperados"
for sector, byphase in sub["por_sector"].items():
    for phase, items in byphase.items():
        assert phase in bd.PHASES
        anns = [it["ann"] for it in items]
        assert anns == sorted(anns, reverse=True), f"{sector}/{phase} no viene ordenado"
print("subsectores:", sub["meta"], "| sectores con desglose:", sorted(sub["por_sector"]))

# --- borde irregular: un solo dato adelantado no puede definir la lectura actual ---
cur = d["current"]
assert cur["edge"] is not None and "coverage" in cur["edge"], "falta info de borde"
# con arrastre de 2 meses la cobertura es alta, pero debe marcarse como estimación
assert cur["edge"]["nowcast"] is True, "borde con series arrastradas sin marcar como nowcast"
assert min(cur["edge"]["fresh"].values()) < 0.5, "el dato fresco no debería dominar"
assert min(cur["edge"]["coverage"].values()) >= bd.MIN_TAIL_COVERAGE
assert abs(cur["growth"]) < 3, "crecimiento extremo: borde irregular sin corregir"
assert cur["call_strength"] in ("Fuerte", "Moderada", "Débil")
assert not any(i["id"] == "USSLIND" for i in d["indicators"]) or \
    "USSLIND" in " ".join(d["meta"]["warnings"]), "USSLIND descontinuada sin avisar"
assert "USSLIND" not in d["pca"]["growth"]["loadings"], "USSLIND sigue en el PCA"
assert d["asset_stats"]["reliability"], "faltan etiquetas de fiabilidad"
assert all("reliability" in x for a in d["assets"] for x in a["phases"].values())
print("fiabilidad:", d["asset_stats"]["reliability"])
print("borde:", cur["edge"], "| fuerza:", cur["call_strength"])

ext = d["extended"]
assert ext["assets"], "familia extendida vacía"
names = {a["name"] for a in ext["assets"]}
assert "Japón (French)" in names and "Biotecnología (IBB)" in names
assert not (names & {a["name"] for a in d["assets"]}), "la familia extendida contamina la principal"
print("extendida:", sorted(names), "| fiabilidad:", ext["meta"]["reliability"])

ne = d["now_edge"]
assert ne["assets"], "contraste ahora vacío"
assert all(a["reliability"] in ("Fuerte", "Moderada", "Débil", "Sin señal") for a in ne["assets"])
print("ahora:", ne["meta"]["counts"], "| top:", [(a["name"], a["now_ann"], a["reliability"]) for a in ne["assets"][:3]])
