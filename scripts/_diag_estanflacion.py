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


def maxdd_date(curve):
    """Fecha (año-mes) en la que se tocó el peor valle tras el pico anterior."""
    s = 100.0
    peak, peak_d = 100.0, None
    worst, worst_d = 0.0, None
    for p in curve:
        s *= 1 + p["s"] / 100
        if s > peak:
            peak, peak_d = s, p["d"]
        dd = s / peak - 1
        if dd < worst:
            worst, worst_d = dd, p["d"]
    return worst_d, round(worst * 100, 1)


def summarize(name, rot):
    sch = rot["default"]
    S = rot["schemes"][sch]
    p = S["portfolio"]
    bench = rot["bench_annual"]
    ann = S["annual"]
    curve = S["curve"]
    dd_d, dd_v = maxdd_date(curve)
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
    print(f"  Histórico completo -> Sharpe {p['sharpe']} · CAGR {p['cagr']}% · MaxDD {p['maxdd']}% (en {dd_d}, recalculado {dd_v}%)")
    s, b, n = agg.get("Estanflación", [0, 0, 0])
    print(f"  Estanflación (todo el histórico, n={n}): cartera {s/n if n else 0:.2f}%/mes vs mercado {b/n if n else 0:.2f}%/mes  edge {(s-b)/n if n else 0:+.2f}pp/mes")
    s9, b9, n9 = agg2009.get("Estanflación", [0, 0, 0])
    print(f"  Estanflación (desde 2009, n={n9}): cartera {s9/n9 if n9 else 0:.2f}%/mes vs mercado {b9/n9 if n9 else 0:.2f}%/mes  edge {(s9-b9)/n9 if n9 else 0:+.2f}pp/mes")
    print(f"  Desde 2009: {wins}/{len(years)} años ganados | acumulado cartera {100*(cum_a-1):.0f}% vs mercado {100*(cum_b-1):.0f}%")
    print()
    return p["sharpe"], p["cagr"]


rot_base = bd.rotation(X, phases, cls_map, probs_df, F)
summarize("BASE (producción actual)", rot_base)

# Ronda 1 (A/B/C: diversificar más) empeoró todo. Ronda 2 encontró que lo
# contrario -- concentrar a 2 fijos en vez de 2-5 -- mejora TODO: Sharpe,
# CAGR, edge de Estanflación entero y desde 2009, años ganados desde 2009.
# Ronda 3: ¿es un efecto específico de Estanflación, o concentrar más ayuda
# en general (y debería tocar el n_max global, no solo esta fase)? Y ¿2 es
# realmente el óptimo, o 3 es igual de bueno con menos riesgo de MaxDD?
# Confirmación final: I descartó que fuera un efecto general (empeora el
# Sharpe global, 0.62). D y H (Estanflación a 2 o 3 fijos) son casi
# idénticos y ambos claramente mejores que BASE. Candidata real a
# implementar: banda (2,3) -- no fija, igual que las demás fases, solo más
# estrecha que la actual (2,5) -- dejando que el propio mecanismo decida
# entre 2 y 3 según cuántos puntúen positivo.
rot_j = bd.rotation(X, phases, cls_map, probs_df, F,
                     phase_sleeve_override={("Estanflación", "Renta variable"): (2, 3)})
summarize("VARIANTE J (candidata final): Estanflación banda (2,3), no fija", rot_j)
for sch in rot_j["schemes"]:
    Sj = rot_j["schemes"][sch]
    Sb = rot_base["schemes"][sch]
    print(f"    {rot_j['schemes'][sch]['label']:<24} Sharpe {Sb['portfolio']['sharpe']} -> {Sj['portfolio']['sharpe']}  "
          f"MaxDD {Sb['portfolio']['maxdd']}% -> {Sj['portfolio']['maxdd']}%")

print(f"Total: {time.time()-t0:.0f}s")
