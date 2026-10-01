"""TEMPORAL - el usuario insiste (con razón parcial, ya confirmada con datos
reales) en que 2017-2021 se perdió por no llevar suficiente Tecnología /
Semiconductores: esos dos sectores hicieron +256,7% y +348,3% acumulado en el
periodo frente a +121,4% el mercado -- una divergencia real y extrema, no
ruido. Pero ASSET_OVERLAP ya trata Tecnología y Semiconductores como la MISMA
exposición económica y solo deja competir al más fuerte de los dos cada mes
-- así que incluso en los meses en que el sistema SÍ acierta con uno de ellos,
nunca lleva los dos a la vez, y en 2019 (10 de 12 meses en Estanflación)
ninguno de los dos entró porque el bloque defensivo (Utilities/Materiales/
Financiero) puntuaba mejor según la fase.

Hipótesis concreta a probar, con datos reales de TODO el histórico (no solo
2017-2021, para no sobreajustar a la propia racha que la motiva): un "suelo
de crecimiento secular" que garantiza que, si Tecnología o Semiconductores
está disponible, al menos uno de los dos entra siempre en el bloque de renta
variable, desplazando al candidato más débil si hace falta. Se mide el efecto
en Sharpe/CAGR/caída máxima/años batidos AL S&P 500 en los 4 esquemas de
reparto, exactamente igual que las rondas de Estanflación, confianza y
dispersión ya probadas y (las dos últimas) descartadas esta sesión."""
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

print("Descargando activos reales…")
X, ameta = bd.fetch_assets(df)
cls_map = {k: v.get("class", "Otros") for k, v in ameta.items()}

sg = float(F["growth"].diff(bd.HORIZON_M).std())
si = float(F["inflation"].diff(bd.HORIZON_M).std())
prob_rows = {}
for d, gg, ii in zip(F.index, F["growth"], F["inflation"]):
    prob_rows[d] = bd.phase_probs(float(gg), float(ii), sg, si)
probs_df = pd.DataFrame(prob_rows).T.shift(1)

print(f"Datos listos en {time.time()-t0:.0f}s.\n")

GROWTH = {"Tecnología", "Semiconductores"}
orig_pick = bd._sleeve_pick


def patched_pick(mu, vol, raw_phase, avail, classes, cls_map_, n_min, n_max):
    top, score = orig_pick(mu, vol, raw_phase, avail, classes, cls_map_, n_min, n_max)
    if classes != {"Renta variable"}:
        return top, score
    if any(g in top for g in GROWTH):
        return top, score
    cand = [c for c in GROWTH if c in avail and c not in bd.NOT_SELECTABLE]
    if not cand:
        return top, score
    best = max(cand, key=lambda c: mu.get(c, -1e9))
    new_top = (top + [best]) if len(top) < n_max else (top[:-1] + [best])
    v = vol.reindex(new_top).replace(0, np.nan)
    iv = 1.0 / v
    w = (iv / iv.sum()) if iv.notna().any() else pd.Series(1.0 / len(new_top), index=new_top)
    new_score = float((mu.reindex(new_top) * w.fillna(0)).sum())
    return new_top, new_score


def run(label, patched):
    if patched:
        bd._sleeve_pick = patched_pick
    else:
        bd._sleeve_pick = orig_pick
    rot = bd.rotation(X, phases, cls_map, probs_df, F,
                       phase_sleeve_override=bd.ESTANFLACION_OVERRIDE)
    bd._sleeve_pick = orig_pick
    print(f"=== {label} ===")
    for sch, label_sch in bd.SCHEMES.items():
        p = rot["schemes"][sch]["portfolio"]
        wy, ny = rot["schemes"][sch]["wins_years"], rot["schemes"][sch]["n_years"]
        print(f"  {label_sch:<22} CAGR {p.get('cagr')}%  Sharpe {p.get('sharpe')}  "
              f"MaxDD {p.get('maxdd')}%  años_batidos {wy}/{ny}")
    return rot


base = run("BASE (producción actual, con techo Estanflación=3)", patched=False)
var = run("CON SUELO Tecnología/Semiconductores", patched=True)

print("\n=== Comparación 2017-2021 por esquema ===")
YEARS = [2017, 2018, 2019, 2020, 2021]
for sch, label_sch in bd.SCHEMES.items():
    ann_b = base["schemes"][sch]["annual"]
    ann_v = var["schemes"][sch]["annual"]
    print(f"  {label_sch}:")
    for y in YEARS:
        b, v = ann_b.get(y), ann_v.get(y)
        print(f"    {y}: base {b}%  ->  con suelo {v}%")

print(f"\nTotal: {time.time()-t0:.0f}s")
