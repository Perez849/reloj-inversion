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
               "BAA", "AAA", "DFII10"):
        base = {"CFNAIMA3": 0, "USSLIND": 1.5, "MEDCPIM158SFRBCLE": 2.8,
                "PCETRIM12M159SFRBDAL": 2.4, "TCU": 78, "UMCSENT": 85,
                "AWHMAN": 40.5, "UNRATE": 5.5, "TB3MS": 3.0, "FEDFUNDS": 3.2,
                "BAA": 6.5, "AAA": 5.5, "DFII10": 1.6}[sid]
        return pd.Series(base + 1.2 * drive + rng.normal(0, 0.2, len(IDX_M)),
                         index=IDX_M, name=sid)
    growth = 0.003 + 0.004 * drive + rng.normal(0, 0.004, len(IDX_M))
    return pd.Series(100 * np.cumprod(1 + growth), index=IDX_M, name=sid)


def fake_french(url, hint=""):
    if "49_Industry" in url:
        cols = list(bd.FRENCH_49)
    elif "12_Industry" in url:
        cols = list(bd.FRENCH_IND)
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


def fake_stooq(ticker):
    if ticker in ("mub.us", "mbb.us"):
        return None, "limite diario excedido (simulado)"
    return pd.Series(0.5 + 2.0 * np.gradient(cycle) + rng.normal(0, 3.0, len(IDX_M)),
                     index=IDX_M), None


bd.fred_series = lambda sid: (synth(sid), None) if synth(sid) is not None else (None, "sintetico")
bd.french_zip = fake_french
bd.stooq_monthly = fake_stooq
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
assert any(a["class"] == "Real / alternativos" for a in d["assets"]), "sin activos reales"
ids = {i["id"] for i in d["indicators"]}
assert "BAA_AAA" in ids, "falta el diferencial derivado"
print("indicadores:", len(d["indicators"]), "/", d["meta"]["series_total"])
print("validación NBER:", d["validation"].get("nber"))
