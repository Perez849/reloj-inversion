"""TEMPORAL - el usuario extiende la pregunta de 2017-2021 a "2017 a 2022" y
sugiere que la cartera no bate porque infrapondera Tecnología/Semiconductores,
o directamente mide mal su rentabilidad. Verificado con fuentes externas
(XLK y SOXX reales, vía búsqueda web): Tecnología y Semiconductores de Ken
French coinciden casi exactamente con XLK/SOXX reales año a año -- la
medición es correcta. Y con los datos de PRODUCCIÓN (data.json real): 2022
fue un año en el que semiconductores (-35% real) y tecnología (-27,7% real)
cayeron MUCHO más que el mercado (-18,1%) -- lo contrario de 2017-2021. La
cartera ganó al benchmark en 2022 por +22 a +35pp según esquema, lo que
convierte el acumulado 2017-2022 en una VICTORIA neta (+6 a +19pp según
esquema), no una derrota. Este script confirma el mecanismo exacto: qué
sectores llevó la cartera realmente en 2022, mes a mes."""
import sys
import time
sys.path.insert(0, "scripts")
import build_data as bd
import pandas as pd

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

print(f"Datos listos en {time.time()-t0:.0f}s. Rotación con log de holdings…\n")

log = []
rot = bd.rotation(X, phases, cls_map, probs_df, F,
                   phase_sleeve_override=bd.ESTANFLACION_OVERRIDE,
                   holdings_log=log)

months_2022 = [m for m in log if m["d"].startswith("2022")]
print("=== Cartera mes a mes en 2022 ===")
for m in months_2022:
    rv = m["picks"].get("Renta variable", [])
    has_tc = any(s in rv for s in ("Tecnología", "Comunicaciones", "Semiconductores"))
    flag = " <- tech/comm" if has_tc else ""
    print(f"  {m['d']} (fase {m['sig']}): {', '.join(rv)}{flag}")

sector_cols = [c for c in X.columns if cls_map.get(c) == "Renta variable"]
yr_idx = [d for d in X.index if d.strftime("%Y") == "2022"]
rets = {}
for c in sector_cols:
    s = X.loc[yr_idx, c].dropna()
    if len(s) < 6:
        continue
    rets[c] = float((1 + s / 100).prod() - 1) * 100
ranked = sorted(rets.items(), key=lambda kv: kv[1])
print("\n=== Ranking real 2022 (peor a mejor) ===")
for name, v in ranked:
    held = any(name in m["picks"].get("Renta variable", []) for m in months_2022)
    print(f"  {'[EN CARTERA] ' if held else '              '}{name:<30} {v:+.1f}%")
bench_s = X.loc[yr_idx, "Renta variable EE.UU. (mercado)"].dropna()
print(f"\n  {'Mercado total':<30} {100*((1+bench_s/100).prod()-1):+.1f}%")

print(f"\nTotal: {time.time()-t0:.0f}s")
