"""TEMPORAL - el usuario, con razón, no acepta "es un trade-off estructural"
como respuesta final a 5 años seguidos perdiendo contra el S&P 500 (2017-2021).
Ya se descartó: (a) mala clasificación de fase, (b) suelo forzado de
Tecnología/Semiconductores (mejora 2017-2021 pero rompe Sharpe/MaxDD en el
histórico completo -- sobreajuste), (c) vida media mal calibrada (5 años ya es
el punto óptimo). Queda sin comprobar, con números reales, una hipótesis
concreta que SÍ se mencionó pero nunca se midió: en 2021 la cartera llevaba
case todos los sectores ganadores reales (Energía, Semiconductores,
Tecnología, Financiero) y aun así perdió -6,33pp. Si acertó con los sectores,
¿de dónde sale la pérdida?

Dos sospechosos concretos, medidos mes a mes con datos reales:

1. EL ORO COMO LASTRE: la cartera nunca va 100% renta variable -- el bloque
   Oro puede llevarse hasta el 20% según la fase. Si durante 2017-2021 (un
   mercado alcista fuerte) hubo meses con peso en oro mientras la renta
   variable elegida subía más que el oro, eso es pérdida pura y cuantificable
   frente a ir 100% a los sectores elegidos. Se mide el coste exacto, mes a
   mes: peso_oro * (rendimiento_renta_variable_elegida - rendimiento_oro).

2. DILUCIÓN DENTRO DEL BLOQUE: el suelo de 2 sectores en renta variable obliga
   a incluir al menos 2 nombres aunque solo 1 esté puntuando de verdad. Si el
   segundo (o tercero) sector elegido rinde mucho peor que el mejor del mes,
   eso también diluye el resultado frente a concentrarse en el único ganador.
   Se mide: mejor rendimiento individual del mes entre los elegidos vs.
   rendimiento medio equiponderado del bloque completo elegido.

Todo con el esquema "equal" (1/n dentro de cada bloque), representativo de
los 4 (ya verificado que dan resultados parecidos), sobre 2017-2021 real."""
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

print(f"Datos listos en {time.time()-t0:.0f}s. Rotación con log de bloques…\n")

log = []
rot = bd.rotation(X, phases, cls_map, probs_df, F,
                   phase_sleeve_override=bd.ESTANFLACION_OVERRIDE,
                   sleeve_log=log)

YEARS = ["2017", "2018", "2019", "2020", "2021"]

print(f"{'mes':<9}{'fase':<16}{'peso_oro':>9}{'ret_RV':>9}{'ret_oro':>9}"
      f"{'coste_oro':>11}{'mejor_RV':>10}{'media_RV':>10}{'dilución':>11}")

tot_oro_cost = 0.0
tot_dilution = 0.0
yearly_oro = {y: 0.0 for y in YEARS}
yearly_dil = {y: 0.0 for y in YEARS}
months_with_oro = 0

for m in log:
    y = m["d"][:4]
    if y not in YEARS:
        continue
    t = pd.Period(m["d"], freq="M").to_timestamp("M")
    # Buscar la fecha real en el índice de X (fin de mes puede no coincidir exacto)
    idx_candidates = [d for d in X.index if d.strftime("%Y-%m") == m["d"]]
    if not idx_candidates:
        continue
    t = idx_candidates[0]

    rv_names = m["picks"].get("Renta variable", [])
    oro_names = m["picks"].get("Oro", [])
    w_oro = m["budgets"].get("Oro", 0.0)
    w_rv = m["budgets"].get("Renta variable", 0.0)

    rv_rets = {c: float(X.loc[t, c]) for c in rv_names if c in X.columns and pd.notna(X.loc[t, c])}
    oro_rets = {c: float(X.loc[t, c]) for c in oro_names if c in X.columns and pd.notna(X.loc[t, c])}

    if not rv_rets:
        continue
    ret_rv = sum(rv_rets.values()) / len(rv_rets)
    ret_oro = (sum(oro_rets.values()) / len(oro_rets)) if oro_rets else 0.0

    coste_oro = w_oro * (ret_rv - ret_oro)
    mejor_rv = max(rv_rets.values())
    dilucion = mejor_rv - ret_rv

    tot_oro_cost += coste_oro
    tot_dilution += dilucion
    yearly_oro[y] += coste_oro
    yearly_dil[y] += dilucion
    if w_oro > 0.001:
        months_with_oro += 1

    print(f"{m['d']:<9}{m['sig']:<16}{w_oro*100:>8.1f}%{ret_rv:>8.1f}%{ret_oro:>8.1f}%"
          f"{coste_oro:>10.2f}p{mejor_rv:>9.1f}%{ret_rv:>9.1f}%{dilucion:>10.2f}p")

print(f"\nMeses 2017-2021 con oro > 0: {months_with_oro}/60")
print(f"\nCoste acumulado del oro 2017-2021 (suma mensual, en puntos porcentuales, "
      f"aprox.): {tot_oro_cost:+.2f}")
print("Por año:")
for y in YEARS:
    print(f"  {y}: coste_oro {yearly_oro[y]:+.2f}pp   dilución_intra-bloque {yearly_dil[y]:+.2f}pp")

print(f"\nDilución acumulada dentro del bloque de renta variable 2017-2021 "
      f"(mejor del mes vs media del bloque): {tot_dilution:+.2f}pp")

print(f"\nTotal: {time.time()-t0:.0f}s")
