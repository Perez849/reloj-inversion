"""TEMPORAL - diagnóstico: los meses con margen de probabilidad bajo entre fases
(clasificación ambigua) rinden peor que los meses con margen claro -- confirmado
con el tercio más ambiguo del histórico real: edge -0.09pp/mes y solo 46% de
meses ganados, frente a +0.27/+0.46pp/mes y ~50% en los otros dos tercios.

¿Diversificar MÁS en los meses de margen bajo (no por fase, por mes concreto)
mejora las cosas? Se prueba con el nuevo parámetro low_confidence_override
(threshold, n_min, n_max), aplicado sobre la producción actual (que ya incluye
el techo de 3 en Estanflación)."""
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


def margin_series(rot):
    """Margen real (top1-top2 de probs) alineado a cada fecha del histórico."""
    out = {}
    for d in F.index:
        if d not in probs_df.index:
            continue
        pr = probs_df.loc[d].dropna()
        if len(pr) < 2:
            continue
        srt = pr.sort_values(ascending=False)
        out[d.strftime("%Y-%m")] = float(srt.iloc[0] - srt.iloc[1])
    return out


def bucket_report(name, rot, margins):
    sch = rot["default"]
    curve = rot["schemes"][sch]["curve"]
    rows = []
    for p in curve:
        m = margins.get(p["d"])
        if m is None or p["b"] is None:
            continue
        rows.append((m, p["s"], p["b"]))
    rows.sort(key=lambda x: x[0])
    n = len(rows)
    terc = n // 3
    buckets = {"ambiguo (margen bajo)": rows[:terc], "medio": rows[terc:2*terc],
               "claro (margen alto)": rows[2*terc:]}
    print(f"=== {name} (esquema: {sch}) ===")
    for bname, b in buckets.items():
        if not b:
            continue
        s_mean = sum(x[1] for x in b) / len(b)
        b_mean = sum(x[2] for x in b) / len(b)
        wins = sum(1 for x in b if x[1] > x[2])
        print(f"  {bname:<22} n={len(b):<5} cartera {s_mean:+.3f}%/mes  mercado {b_mean:+.3f}%/mes  "
              f"edge {s_mean-b_mean:+.3f}pp/mes  gana {wins}/{len(b)} ({100*wins/len(b):.0f}%)")
    p = rot["schemes"][sch]["portfolio"]
    print(f"  Histórico completo -> Sharpe {p['sharpe']} · CAGR {p['cagr']}% · MaxDD {p['maxdd']}%")
    print()


# Baseline: producción actual (techo 3 en Estanflación, sin tocar el margen bajo).
rot_base = bd.rotation(X, phases, cls_map, probs_df, F,
                        phase_sleeve_override=bd.ESTANFLACION_OVERRIDE)
margins = margin_series(rot_base)
bucket_report("BASE (producción actual)", rot_base, margins)

# Variante K: margen < 15 puntos -> todo el universo ese mes (máxima diversificación
# cuando la clasificación es casi una moneda al aire).
rot_k = bd.rotation(X, phases, cls_map, probs_df, F,
                     phase_sleeve_override=bd.ESTANFLACION_OVERRIDE,
                     low_confidence_override=(0.15, 99, 99))
bucket_report("VARIANTE K: margen<15pp -> universo completo ese mes", rot_k, margins)

# Variante L: margen < 15 puntos -> banda ancha (7), menos drástico que K.
rot_l = bd.rotation(X, phases, cls_map, probs_df, F,
                     phase_sleeve_override=bd.ESTANFLACION_OVERRIDE,
                     low_confidence_override=(0.15, 7, 7))
bucket_report("VARIANTE L: margen<15pp -> banda de 7", rot_l, margins)

# Variante M: margen < 15 puntos -> MÁS concentrado (3 fijos), probando si lo que
# ya funcionó en Estanflación (menos nombres, más convicción en el ranking) es
# también la respuesta correcta a la ambigüedad de fase, no solo a esa fase.
rot_m = bd.rotation(X, phases, cls_map, probs_df, F,
                     phase_sleeve_override=bd.ESTANFLACION_OVERRIDE,
                     low_confidence_override=(0.15, 3, 3))
bucket_report("VARIANTE M: margen<15pp -> 3 fijos (más concentrado, no menos)", rot_m, margins)

print(f"Total: {time.time()-t0:.0f}s")
