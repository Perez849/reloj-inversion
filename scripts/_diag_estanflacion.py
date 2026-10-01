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


def summarize(name, rot, sch=None):
    # OJO: rot["default"] es el esquema de MAYOR CAGR, y ESE ESQUEMA CAMBIA
    # entre variantes -- comparar "el Sharpe del default" entre dos rotation()
    # distintas mezcla el efecto de la variante con el efecto de qué esquema
    # ganó por CAGR. Se fija un esquema explícito para comparar lo mismo
    # contra lo mismo.
    sch = sch or rot["default"]
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


def edge_2009(rot, sch, phase="Estanflación"):
    S = rot["schemes"][sch]
    hist_by_d = {d.strftime("%Y-%m"): pp for d, pp in zip(F.index, phases)}
    s = b = n = 0.0
    for pt in S["curve"]:
        if pt["d"] < "2009-01" or pt["b"] is None:
            continue
        if hist_by_d.get(pt["d"]) != phase:
            continue
        s += pt["s"]; b += pt["b"]; n += 1
    return (s - b) / n if n else None


def compare_schemes(name, rot_base, rot_var):
    print(f"--- {name}: comparación esquema a esquema (NO el 'default', que cambia) ---")
    for sch in rot_base["schemes"]:
        Sb, Sv = rot_base["schemes"][sch]["portfolio"], rot_var["schemes"][sch]["portfolio"]
        eb, ev = edge_2009(rot_base, sch), edge_2009(rot_var, sch)
        print(f"  {rot_base['schemes'][sch]['label']:<24} Sharpe {Sb['sharpe']} -> {Sv['sharpe']}  "
              f"CAGR {Sb['cagr']}% -> {Sv['cagr']}%  MaxDD {Sb['maxdd']}% -> {Sv['maxdd']}%  "
              f"edge Estanf.09+ {eb:+.2f} -> {ev:+.2f}pp/mes")
    print()


rot_base = bd.rotation(X, phases, cls_map, probs_df, F)
summarize("BASE (producción actual)", rot_base)

# Rondas 1-3: A/B/C (diversificar) empeoraron todo. D/H (concentrar
# Estanflación a 2 o 3 fijos) parecían mejorar mucho el Sharpe -- pero esa
# comparación usaba rot["default"] (el esquema de mayor CAGR), que CAMBIA
# de esquema entre variantes: parte de esa "mejora" podía ser solo el
# cambio de qué esquema gana, no una mejora real del mismo esquema. Esta
# ronda repite D, H y J comparando los 4 esquemas uno a uno contra BASE.
rot_d = bd.rotation(X, phases, cls_map, probs_df, F,
                     phase_sleeve_override={("Estanflación", "Renta variable"): (2, 2)})
rot_h = bd.rotation(X, phases, cls_map, probs_df, F,
                     phase_sleeve_override={("Estanflación", "Renta variable"): (3, 3)})
rot_j = bd.rotation(X, phases, cls_map, probs_df, F,
                     phase_sleeve_override={("Estanflación", "Renta variable"): (2, 3)})

compare_schemes("D: Estanflación 2 fijos", rot_base, rot_d)
compare_schemes("H: Estanflación 3 fijos", rot_base, rot_h)
compare_schemes("J: Estanflación banda (2,3)", rot_base, rot_j)

print(f"Total: {time.time()-t0:.0f}s")
