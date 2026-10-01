"""TEMPORAL - el usuario plantea, con razón, el estándar real: un gestor de
carteras que pierde contra su benchmark 5 años seguidos no cobra bonus. Dos
comprobaciones con datos reales, no intuición:

1. Lo que de verdad le pasó a los gestores ACTIVOS REALES en 2017-2021
   (verificado por separado con SPIVA vía búsqueda web): en 2021 el 85% de
   los gestores de gran capitalización perdió contra el S&P 500, y en el
   periodo de 5 años hasta 2017 perdió el 84%. No es una peculiaridad de
   este sistema -- es lo que le pasó a la inmensa mayoría de los
   profesionales reales en ese mismo tramo exacto.

2. Si esta racha de 5 años es un caso ÚNICO en los 56 años de histórico de
   ESTE sistema, o si ya había pasado antes. Si han existido rachas
   similares o peores en otros tramos (Volcker, dot-com, etc.), la racha de
   2017-2021 no es una anomalía que señale un fallo -- es una característica
   recurrente, esperable, de cualquier estrategia que de verdad diversifica
   en vez de apostarlo todo a lo que ya ha ganado. Se mide con el propio
   backtest, los 4 esquemas, buscando TODAS las rachas de 3+ años seguidos
   perdiendo contra el benchmark en toda la historia disponible."""
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

print(f"Datos listos en {time.time()-t0:.0f}s. Rotación…\n")

rot = bd.rotation(X, phases, cls_map, probs_df, F,
                   phase_sleeve_override=bd.ESTANFLACION_OVERRIDE)

eq = X["Renta variable EE.UU. (mercado)"]
bench_annual = {int(k): v for k, v in bd._annual(eq.dropna()).items()}

for sch, label in bd.SCHEMES.items():
    ann = {int(k): v for k, v in rot["schemes"][sch]["annual"].items()}
    years = sorted(y for y in ann if y in bench_annual)
    print(f"=== {label} ===")
    diffs = {y: ann[y] - bench_annual[y] for y in years}
    total_years = len(years)
    losing_years = sum(1 for d in diffs.values() if d < 0)
    print(f"  Años con datos: {total_years}  ·  años perdiendo: {losing_years} "
          f"({100*losing_years/total_years:.0f}%)")

    # Buscar rachas de años consecutivos perdiendo (diff < 0)
    streaks = []
    cur_start = None
    for y in years:
        if diffs[y] < 0:
            if cur_start is None:
                cur_start = y
        else:
            if cur_start is not None:
                streaks.append((cur_start, y - 1))
                cur_start = None
    if cur_start is not None:
        streaks.append((cur_start, years[-1]))

    streaks3 = [(a, b) for a, b in streaks if b - a + 1 >= 3]
    print(f"  Rachas de 3+ años seguidos perdiendo: {len(streaks3)}")
    for a, b in sorted(streaks3, key=lambda s: -(s[1] - s[0])):
        n = b - a + 1
        cum = sum(diffs[y] for y in range(a, b + 1))
        print(f"    {a}-{b} ({n} años): {', '.join(f'{diffs[y]:+.1f}' for y in range(a, b+1))}"
              f"  -> acumulado {cum:+.1f}pp")
    print()

print(f"Total: {time.time()-t0:.0f}s")
