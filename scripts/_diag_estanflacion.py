"""TEMPORAL - diagnóstico: ¿existe un reparto de renta variable para la fase
Estanflación que mejore de verdad sobre el actual, dado que el propio
laboratorio mide persistencia negativa (rank_ic -0.27, asset_ic -0.44) para
esa fase? Se compara con datos reales, no con suposiciones.

Variantes probadas, todas vía el nuevo parámetro `phase_sleeve_override` de
rotation() (no-op por defecto, cero impacto fuera de este script):
  A: Estanflación toma TODOS los candidatos de renta variable disponibles
     (n_min=n_max=99 -> en la práctica, todo el universo), dejando que el
     esquema de reparto (equal/invvol/rank/blend) decida las proporciones.
     Equivale a "no afirmar que sabemos elegir sector en esta fase".
  B: banda intermedia, n_min=n_max=7 (la mitad del universo aprox.), una
     apuesta más suave que la actual (2-5) pero no total.
"""
import sys
import time
sys.path.insert(0, "scripts")
import build_data as bd

t0 = time.time()
print("Descargando datos macro reales…")
df, raw_meta = bd.fetch_macro()
Z, ind_info = bd.build_blocks(df)
F, pca = bd.build_factors(Z)
F = F.dropna(subset=["growth", "inflation"])
phases = __import__("pandas").Series(
    [bd.classify(a, b) for a, b in zip(F["growth"], F["inflation"])],
    index=F.index, name="phase")

print("Descargando activos reales…")
X, ameta = bd.fetch_assets(df)
cls_map = {k: v.get("class", "Otros") for k, v in ameta.items()}

sg = float(F["growth"].diff(bd.HORIZON_M).std())
si = float(F["inflation"].diff(bd.HORIZON_M).std())
prob_rows = {}
for d, gg, ii in zip(F.index, F["growth"], F["inflation"]):
    prob_rows[d] = bd.phase_probs(float(gg), float(ii), sg, si)
import pandas as pd
probs_df = pd.DataFrame(prob_rows).T.shift(1)

print(f"Datos listos en {time.time()-t0:.0f}s. Lanzando las 4 rotaciones…\n")


def summarize(name, rot):
    sch = rot["default"]
    S = rot["schemes"][sch]
    p = S["portfolio"]
    bench = rot["bench_annual"]
    ann = S["annual"]
    curve = S["curve"]
    hist_by_d = {h["d"]: h["p"] for h in
                 [{"d": d.strftime("%Y-%m"), "p": pp} for d, pp in zip(F.index, phases)]}
    # edge específico en meses de Estanflación, y desde 2009
    from collections import defaultdict
    agg = defaultdict(lambda: [0.0, 0.0, 0])
    agg2009 = defaultdict(lambda: [0.0, 0.0, 0])
    for pt in curve:
        d = pt["d"]
        ph = hist_by_d.get(d)
        if ph is None or pt["b"] is None:
            continue
        agg[ph][0] += pt["s"]; agg[ph][1] += pt["b"]; agg[ph][2] += 1
        if d >= "2009-01":
            agg2009[ph][0] += pt["s"]; agg2009[ph][1] += pt["b"]; agg2009[ph][2] += 1
    years = sorted(y for y in ann if y in bench and int(y) >= 2009)
    wins = sum(1 for y in years if ann[y] > bench[y])
    cum_a = 1.0
    cum_b = 1.0
    for y in years:
        cum_a *= (1 + ann[y] / 100)
        cum_b *= (1 + bench[y] / 100)
    print(f"=== {name} (esquema por defecto: {sch}) ===")
    print(f"  Histórico completo -> Sharpe {p['sharpe']} · CAGR {p['cagr']}% · MaxDD {p['maxdd']}%")
    s, b, n = agg.get("Estanflación", [0, 0, 0])
    print(f"  Estanflación (todo el histórico, n={n}): cartera {s/n if n else 0:.2f}%/mes vs mercado {b/n if n else 0:.2f}%/mes  edge {(s-b)/n if n else 0:+.2f}pp/mes")
    s9, b9, n9 = agg2009.get("Estanflación", [0, 0, 0])
    print(f"  Estanflación (desde 2009, n={n9}): cartera {s9/n9 if n9 else 0:.2f}%/mes vs mercado {b9/n9 if n9 else 0:.2f}%/mes  edge {(s9-b9)/n9 if n9 else 0:+.2f}pp/mes")
    print(f"  Desde 2009: {wins}/{len(years)} años ganados | acumulado cartera {100*(cum_a-1):.0f}% vs mercado {100*(cum_b-1):.0f}%")
    print()
    return p["sharpe"], p["cagr"]


rot_base = bd.rotation(X, phases, cls_map, probs_df, F)
summarize("BASE (producción actual)", rot_base)

rot_a = bd.rotation(X, phases, cls_map, probs_df, F,
                     phase_sleeve_override={("Estanflación", "Renta variable"): (99, 99)})
summarize("VARIANTE A: Estanflación = todo el universo (sin apuesta de sector)", rot_a)

rot_b = bd.rotation(X, phases, cls_map, probs_df, F,
                     phase_sleeve_override={("Estanflación", "Renta variable"): (7, 7)})
summarize("VARIANTE B: Estanflación = banda ancha (7 de ~14, apuesta suave)", rot_b)

# Variante C: igual que A pero también en Recuperación, la otra fase con IC
# negativo (-0.18) detectado en el laboratorio -- por si el problema no es
# solo de Estanflación.
rot_c = bd.rotation(X, phases, cls_map, probs_df, F,
                     phase_sleeve_override={
                         ("Estanflación", "Renta variable"): (99, 99),
                         ("Recuperación", "Renta variable"): (99, 99),
                     })
summarize("VARIANTE C: A + también Recuperación a universo completo", rot_c)

# A/B/C (diversificar más) empeoraron todo lo medido. Se prueba lo contrario
# (concentrar más) y una señal distinta (momentum, no condicionada a fase).
rot_d = bd.rotation(X, phases, cls_map, probs_df, F,
                     phase_sleeve_override={("Estanflación", "Renta variable"): (2, 2)})
summarize("VARIANTE D: Estanflación concentrada al mínimo (2 fijos, no 2-5)", rot_d)

rot_e = bd.rotation(X, phases, cls_map, probs_df, F,
                     momentum_phases={"Estanflación"}, momentum_window=6)
summarize("VARIANTE E: Estanflación por momentum puro (media 6m, no por fase)", rot_e)

rot_f = bd.rotation(X, phases, cls_map, probs_df, F,
                     momentum_phases={"Estanflación"}, momentum_window=12)
summarize("VARIANTE F: igual que E pero ventana de 12 meses", rot_f)

print(f"Total: {time.time()-t0:.0f}s")
