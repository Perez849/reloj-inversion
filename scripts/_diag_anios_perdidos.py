"""TEMPORAL - diagnóstico: por qué perdimos contra el S&P 500 en los años más
graves (2013 -19.4pp, 2023 -15.4pp, 2017 -10.9pp, 1999 -9.6pp). Reconstruye,
mes a mes, qué sectores sostuvo de verdad la cartera esos años (vía el nuevo
parámetro holdings_log de rotation(), no-op por defecto) y lo compara con el
rendimiento REAL de cada sector ese mismo año, para ver si el patrón es
"diversificar costó caro frente a un mercado muy concentrado" o algo distinto."""
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

print(f"Datos listas en {time.time()-t0:.0f}s. Rotación con log de holdings…\n")

log = []
rot = bd.rotation(X, phases, cls_map, probs_df, F,
                   phase_sleeve_override=bd.ESTANFLACION_OVERRIDE,
                   holdings_log=log)

YEARS = ["1999", "2013", "2017", "2023"]

# Rentabilidad REAL de cada sector ese año natural (no exceso, retorno bruto
# del índice French), para comparar contra lo que la cartera sí tenía.
sector_cols = [c for c in X.columns if cls_map.get(c) == "Renta variable"]
for y in YEARS:
    months = [m for m in log if m["d"].startswith(y)]
    if not months:
        print(f"=== {y}: sin meses en el log (fuera de la ventana del walk-forward) ===\n")
        continue
    print(f"=== {y} ===")
    # qué se mantuvo cada mes
    for m in months:
        rv = m["picks"].get("Renta variable", [])
        print(f"  {m['d']} (fase {m['sig']}): {', '.join(rv)}")
    # rendimiento real de cada sector ESE AÑO (acumulado, en %)
    yr_idx = [d for d in X.index if d.strftime('%Y') == y]
    if yr_idx:
        rets = {}
        for c in sector_cols:
            s = X.loc[yr_idx, c].dropna()
            if len(s) < 6:
                continue
            rets[c] = float((1 + s / 100).prod() - 1) * 100
        ranked = sorted(rets.items(), key=lambda kv: -kv[1])
        print(f"  Ranking real de sectores en {y} (retorno del año completo):")
        for name, v in ranked:
            held = any(name in m["picks"].get("Renta variable", []) for m in months)
            print(f"    {'[EN CARTERA] ' if held else '              '}{name:<30} {v:+.1f}%")
    print()

print(f"Total: {time.time()-t0:.0f}s")
