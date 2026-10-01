"""TEMPORAL - el usuario sigue, con razón, sin aceptar "trade-off estructural"
como respuesta a 5 años seguidos perdiendo (2017-2021). La descomposición
mes a mes (ver _diag_oro_y_dilucion.py, ya revertido) encontró dos costes
reales:

  - El oro: -6,58pp acumulados 2017-2021 (sobre todo 2020: -5,39pp). Real
    pero modesto.
  - La DILUCIÓN dentro del bloque de renta variable: +165,86pp acumulados
    -- la diferencia, mes a mes, entre el mejor de los sectores YA
    elegidos y la media equiponderada del bloque completo. Esto es mucho
    más grande que el oro, y tiene una causa concreta, no es "ruido":
    SLEEVES fuerza un SUELO de 2 sectores en renta variable, y cuando
    solo 1 puntúa de verdad, _sleeve_pick() añade un segundo aunque
    puntúe NEGATIVO ("se completa hasta el suelo con los siguientes
    mejores aunque puntúen negativo" -- ver docstring de _sleeve_pick).
    Ese segundo nombre, forzado y sin convicción, es justo lo que diluye.

El suelo de 2 nunca se ha probado contra un suelo de 1 con el propio
backtest -- la razón en el comentario de SLEEVES es de diseño ("evitar
concentración"), no un resultado medido. Se prueba aquí, con datos
reales, TODO el histórico, los 4 esquemas de reparto, pasando un `sleeves`
alternativo a rotation() (ya acepta ese parámetro, sin tocar producción)."""
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

SLEEVES_BASE = bd.SLEEVES
SLEEVES_N1 = {
    "Renta variable": ({"Renta variable"}, 0.80, 1.00, 1, 5),
    "Oro": ({"Oro"}, 0.00, 0.20, 0, 2),
}


def run(label, sleeves):
    rot = bd.rotation(X, phases, cls_map, probs_df, F,
                       sleeves=sleeves,
                       phase_sleeve_override=bd.ESTANFLACION_OVERRIDE)
    print(f"=== {label} ===")
    for sch, lbl in bd.SCHEMES.items():
        p = rot["schemes"][sch]["portfolio"]
        wy, ny = rot["schemes"][sch]["wins_years"], rot["schemes"][sch]["n_years"]
        print(f"  {lbl:<22} CAGR {p.get('cagr')}%  Sharpe {p.get('sharpe')}  "
              f"MaxDD {p.get('maxdd')}%  años_batidos {wy}/{ny}")
    return rot


base = run("BASE (suelo=2, producción actual)", SLEEVES_BASE)
n1 = run("SUELO=1 (concentración completa cuando solo 1 puntúa)", SLEEVES_N1)

print("\n=== Comparación 2017-2021 por esquema ===")
YEARS = [2017, 2018, 2019, 2020, 2021]
for sch, lbl in bd.SCHEMES.items():
    ann_b = base["schemes"][sch]["annual"]
    ann_n1 = n1["schemes"][sch]["annual"]
    print(f"  {lbl}:")
    for y in YEARS:
        b, v = ann_b.get(y), ann_n1.get(y)
        print(f"    {y}: suelo=2 {b}%  ->  suelo=1 {v}%")

print(f"\nTotal: {time.time()-t0:.0f}s")
