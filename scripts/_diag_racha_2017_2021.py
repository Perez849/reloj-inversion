"""TEMPORAL - el usuario señala, con razón confirmada, que 2017-2021 son 5
AÑOS SEGUIDOS perdiendo contra el S&P 500 (-10.9, -4.1, -2.8, -1.8, -6.3 pp).
Una racha de 5 años consecutivos no es "ruido disperso" -- busca si hay un
mecanismo COMÚN a los 5 años, no 5 explicaciones sueltas. Hipótesis concreta:
2017-2021 fue la era de máxima concentración del S&P 500 en mega-cap
tecnológica/comunicaciones (FAANG y sucesoras) -- si el sistema, por rotar
fuera de esos 2 sectores buena parte de esos 5 años, se quedó sistemáticamente
atrás de un índice cada vez más dominado por un puñado de nombres."""
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

YEARS = ["2017", "2018", "2019", "2020", "2021"]
sector_cols = [c for c in X.columns if cls_map.get(c) == "Renta variable"]

tech_comm_months_held = 0
tech_comm_months_total = 0
for y in YEARS:
    months = [m for m in log if m["d"].startswith(y)]
    print(f"=== {y} ===")
    for m in months:
        rv = m["picks"].get("Renta variable", [])
        has_tc = any(s in rv for s in ("Tecnología", "Comunicaciones", "Semiconductores"))
        tech_comm_months_total += 1
        if has_tc:
            tech_comm_months_held += 1
        flag = " <- tech/comm" if has_tc else ""
        print(f"  {m['d']} (fase {m['sig']}): {', '.join(rv)}{flag}")
    yr_idx = [d for d in X.index if d.strftime('%Y') == y]
    if yr_idx:
        rets = {}
        for c in sector_cols:
            s = X.loc[yr_idx, c].dropna()
            if len(s) < 6:
                continue
            rets[c] = float((1 + s / 100).prod() - 1) * 100
        ranked = sorted(rets.items(), key=lambda kv: -kv[1])
        print(f"  Ranking real {y}:")
        for name, v in ranked[:6]:
            held = any(name in m["picks"].get("Renta variable", []) for m in months)
            print(f"    {'[EN CARTERA] ' if held else '              '}{name:<30} {v:+.1f}%")
    print()

print(f"Meses con Tecnología/Comunicaciones/Semiconductores en cartera, 2017-2021: "
      f"{tech_comm_months_held}/{tech_comm_months_total}")

# Rendimiento real agregado 2017-2021 de Tecnología/Comunicaciones/Semis vs el
# resto del universo y vs el mercado total, para confirmar si de verdad lideraron.
idx_period = [d for d in X.index if d.strftime('%Y') in YEARS]
print("\nRentabilidad acumulada 2017-2021 por sector (todo el periodo, comprando y manteniendo):")
accum = {}
for c in sector_cols:
    s = X.loc[idx_period, c].dropna()
    if len(s) < 40:
        continue
    accum[c] = float((1 + s / 100).prod() - 1) * 100
for name, v in sorted(accum.items(), key=lambda kv: -kv[1]):
    print(f"  {name:<30} {v:+.1f}%")
bench_s = X.loc[idx_period, "Renta variable EE.UU. (mercado)"].dropna()
print(f"  {'Mercado total':<30} {100*((1+bench_s/100).prod()-1):+.1f}%")

print(f"\nTotal: {time.time()-t0:.0f}s")
