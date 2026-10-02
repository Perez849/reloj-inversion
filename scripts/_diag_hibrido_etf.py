"""TEMPORAL - el usuario pide una opción híbrida: usar precios reales de ETFs
sectoriales (IYW, IYK, IYZ... -- en general, los de más historia) y Ken
French para rellenar hacia atrás, todo lo que el ETF no cubra. Si mejora el
backtest, implementarlo en producción.

ETFs elegidos por sector (el de más historia real disponible, no
necesariamente el más famoso):
  - Tecnología, Salud, Energía, Financiero, Industria, Materiales/Químicas,
    Utilities, Consumo discrecional, Consumo básico: los SPDR sectoriales
    (XLK/XLV/XLE/XLF/XLI/XLB/XLU/XLY/XLP), cotizando desde diciembre de 1998
    -- la familia de ETFs sectoriales más antigua que existe.
  - Comunicaciones: IYZ (iShares US Telecom, mayo 2000). No XLC -- existe
    desde 2018, demasiado corto para aportar nada; IYZ es telecom clásico,
    no "comunicaciones" al estilo GICS 2018 (incluye Meta/Alphabet), pero es
    la única familia con historia real larga para este bloque.
  - Semiconductores: SOXX (iShares Semiconductor, julio 2001).

Cada serie se construye: retorno real del ETF (Yahoo/Stooq, mismo mecanismo
que ya usa fetch_assets() para EEM/EFA/IWM/AGG) convertido a exceso sobre el
tipo sin riesgo de Ken French (mismo rf que usa todo lo demás en X) desde que
el ETF cotiza, y Ken French (industria 12 o "Chips" de las 49) para todos los
meses ANTERIORES a esa fecha. Se sustituye columna por columna en X (mismo
nombre, para no tocar cls_map/sleeves), se corre el backtest real completo,
4 esquemas, y se compara contra producción."""
import sys
import time
sys.path.insert(0, "scripts")
import build_data as bd
import pandas as pd
import numpy as np

t0 = time.time()
print("Descargando datos macro reales…")
df, raw_meta = bd.fetch_macro()
Z, ind_info = bd.build_blocks(df)
F, pca = bd.build_factors(Z)
F = F.dropna(subset=["growth", "inflation"])
phases = pd.Series([bd.classify(a, b) for a, b in zip(F["growth"], F["inflation"])],
                    index=F.index, name="phase")

print("Descargando activos reales (Ken French, base)…")
X, ameta = bd.fetch_assets(df)
cls_map = {k: v.get("class", "Otros") for k, v in ameta.items()}

sg = float(F["growth"].diff(bd.HORIZON_M).std())
si = float(F["inflation"].diff(bd.HORIZON_M).std())
prob_rows = {}
for d, gg, ii in zip(F.index, F["growth"], F["inflation"]):
    prob_rows[d] = bd.phase_probs(float(gg), float(ii), sg, si)
probs_df = pd.DataFrame(prob_rows).T.shift(1)

print(f"Datos listos en {time.time()-t0:.0f}s.\n")

print("Descargando el tipo sin riesgo de Ken French (mismo que usa todo X)…")
ff, _ = bd.french_zip(bd.FRENCH_BASE + "F-F_Research_Data_Factors_CSV.zip", "factores")
rf = ff["RF"]

SECTOR_ETF = {
    "Tecnología": ("XLK", "xlk.us"),
    "Salud": ("XLV", "xlv.us"),
    "Energía": ("XLE", "xle.us"),
    "Financiero": ("XLF", "xlf.us"),
    "Industria": ("XLI", "xli.us"),
    "Materiales / Químicas": ("XLB", "xlb.us"),
    "Utilities": ("XLU", "xlu.us"),
    "Consumo discrecional": ("XLY", "xly.us"),
    "Consumo básico": ("XLP", "xlp.us"),
    "Comunicaciones": ("IYZ", "iyz.us"),
    "Semiconductores": ("SOXX", "soxx.us"),
}

X_hybrid = X.copy()
print("=== Construcción por sector: ETF real + Ken French hacia atrás ===")
for sector, (ysym, stick) in SECTOR_ETF.items():
    if sector not in X.columns:
        print(f"  ✗ {sector}: no está en el universo base, se omite")
        continue
    r, e1 = bd.yahoo_monthly(ysym)
    if r is None:
        r, e2 = bd.stooq_monthly(stick)
        src = f"Stooq {stick}"
        if r is None:
            print(f"  ✗ {sector} ({ysym}): sin datos reales ({e1} | {e2}), se queda solo Ken French")
            continue
    else:
        src = f"Yahoo {ysym}"
    r_excess = (r - rf.reindex(r.index)).dropna()
    old = X[sector]
    splice_date = r_excess.index[0]
    combined = pd.concat([old[old.index < splice_date], r_excess])
    combined = combined[~combined.index.duplicated(keep="last")].sort_index()
    X_hybrid[sector] = combined.reindex(X.index)
    print(f"  ✓ {sector:<24} {src:<14} real desde {splice_date.date()} "
          f"({r_excess.size} meses reales de {X.index.size} totales)")


def run(label, X_):
    rot = bd.rotation(X_, phases, cls_map, probs_df, F,
                       phase_sleeve_override=bd.ESTANFLACION_OVERRIDE)
    print(f"\n=== {label} ===")
    for sch, lbl in bd.SCHEMES.items():
        p = rot["schemes"][sch]["portfolio"]
        wy, ny = rot["schemes"][sch]["wins_years"], rot["schemes"][sch]["n_years"]
        print(f"  {lbl:<22} CAGR {p.get('cagr')}%  Sharpe {p.get('sharpe')}  "
              f"MaxDD {p.get('maxdd')}%  años_batidos {wy}/{ny}")
    return rot


base = run("BASE (Ken French puro, producción actual)", X)
hyb = run("HÍBRIDO (ETF real + Ken French hacia atrás)", X_hybrid)

print("\n=== Comparación años recientes por esquema (donde manda el ETF real) ===")
YEARS = [2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025]
for sch, lbl in bd.SCHEMES.items():
    ann_b = base["schemes"][sch]["annual"]
    ann_h = hyb["schemes"][sch]["annual"]
    print(f"  {lbl}:")
    for y in YEARS:
        b, h = ann_b.get(y), ann_h.get(y)
        if b is None and h is None:
            continue
        print(f"    {y}: Ken French {b}%  ->  híbrido {h}%")

print(f"\nTotal: {time.time()-t0:.0f}s")
