"""TEMPORAL - ¿ayuda ampliar el techo de sectores cuando la DISPERSIÓN entre
ellos es baja (se mueven todos juntos, como 2013: +16.5% a +45.6% TODOS
positivos) en vez de cuando la clasificación de fase es ambigua (ya probado
y descartado)? Hipótesis: en esos meses hay poco que "elegir bien" -- así
que tener solo 2-5 de ~12 sectores dejaba fuera parte de una subida que
pasaba en todos a la vez. Prueba con el nuevo parámetro dispersion_override
(no-op por defecto) de rotation(), sobre la producción actual (Estanflación
ya a techo 3)."""
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

print(f"Datos listos en {time.time()-t0:.0f}s.\n")


def summarize(name, rot):
    sch = rot["default"]
    S = rot["schemes"][sch]
    p = S["portfolio"]
    ann = S["annual"]
    bench = rot["bench_annual"]
    years = sorted(y for y in ann if y in bench and int(y) >= 2009)
    wins = sum(1 for y in years if ann[y] > bench[y])
    cum_a = cum_b = 1.0
    for y in years:
        cum_a *= (1 + ann[y] / 100); cum_b *= (1 + bench[y] / 100)
    y2013 = ann.get("2013"); b2013 = bench.get("2013")
    diff2013 = (y2013 - b2013) if y2013 is not None and b2013 is not None else None
    print(f"=== {name} (esquema: {sch}) ===")
    print(f"  Histórico completo -> Sharpe {p['sharpe']} · CAGR {p['cagr']}% · MaxDD {p['maxdd']}%")
    print(f"  Desde 2009: {wins}/{len(years)} años ganados | acumulado cartera {100*(cum_a-1):.0f}% vs mercado {100*(cum_b-1):.0f}%")
    print(f"  2013: cartera {y2013}% vs mercado {b2013}%  (diff {diff2013:+.2f}pp)" if diff2013 is not None else "  2013: sin datos")
    print()


rot_base = bd.rotation(X, phases, cls_map, probs_df, F,
                        phase_sleeve_override=bd.ESTANFLACION_OVERRIDE)
summarize("BASE (producción actual)", rot_base)

# N: dispersión en el tercil más bajo de su propio histórico -> techo a 8
# (acercarse al universo completo, no todo, sigue dejando algo de selección).
rot_n = bd.rotation(X, phases, cls_map, probs_df, F,
                     phase_sleeve_override=bd.ESTANFLACION_OVERRIDE,
                     dispersion_override=(0.33, 8, 8))
summarize("VARIANTE N: dispersión tercil bajo -> techo 8", rot_n)

# O: umbral más estricto (solo el 20% de dispersión más baja) -- menos meses
# afectados, por si N diluye demasiado.
rot_o = bd.rotation(X, phases, cls_map, probs_df, F,
                     phase_sleeve_override=bd.ESTANFLACION_OVERRIDE,
                     dispersion_override=(0.20, 8, 8))
summarize("VARIANTE O: dispersión percentil<20 -> techo 8", rot_o)

# P: igual que N pero menos agresivo (techo 6, no 8).
rot_p = bd.rotation(X, phases, cls_map, probs_df, F,
                     phase_sleeve_override=bd.ESTANFLACION_OVERRIDE,
                     dispersion_override=(0.33, 6, 6))
summarize("VARIANTE P: dispersión tercil bajo -> techo 6", rot_p)

print(f"Total: {time.time()-t0:.0f}s")
