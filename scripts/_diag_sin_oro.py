"""TEMPORAL - sigue la investigación de por qué 2017-2021 perdió 5 años
seguidos. Descartado ya: mala clasificación de fase, suelo forzado de
Tecnología/Semiconductores (sobreajuste), vida media mal calibrada (5 años ya
es óptimo), suelo=1 en vez de 2 en renta variable (empeora el histórico
completo, efecto mixto en 2017-2021).

Queda un cabo suelto real y medido: la aproximación mes a mes (ya revertida)
encontró que el oro costó -6,58pp acumulados 2017-2021, concentrado casi todo
en 2020 (-5,39pp) -- un año en el que, sin ese coste, la cartera habría
batido al mercado por +3,6pp en vez de perder -1,79pp. Pero esa cifra es una
aproximación (suma de diferencias mensuales, no compuesta, con reparto
equiponderado aproximado). Se prueba aquí con el MOTOR REAL de rotation():
quitar el oro del todo (banda 0-0%, techo 0) y comparar contra producción en
TODO el histórico (no solo 2017-2021, porque el oro es "seguro táctico" para
regímenes malos -- Volcker 1979-82, 2000-02, 2008 -- y quitarlo podría ayudar
en el periodo que motiva la pregunta pero salir caro en esos otros, igual que
pasó con el suelo de Tecnología/Semiconductores)."""
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
SLEEVES_NO_GOLD = {
    "Renta variable": ({"Renta variable"}, 1.00, 1.00, 2, 5),
    "Oro": ({"Oro"}, 0.00, 0.00, 0, 0),
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


base = run("BASE (con oro, producción actual)", SLEEVES_BASE)
nog = run("SIN ORO (100% renta variable siempre)", SLEEVES_NO_GOLD)

print("\n=== Comparación 2017-2021 por esquema ===")
YEARS = [2017, 2018, 2019, 2020, 2021]
for sch, lbl in bd.SCHEMES.items():
    ann_b = base["schemes"][sch]["annual"]
    ann_n = nog["schemes"][sch]["annual"]
    print(f"  {lbl}:")
    for y in YEARS:
        b, v = ann_b.get(y), ann_n.get(y)
        print(f"    {y}: con oro {b}%  ->  sin oro {v}%")

print("\n=== Otros episodios clave (¿el oro protege de verdad en los malos?) ===")
BAD_YEARS = [1974, 1975, 2000, 2001, 2002, 2008, 2022]
for sch, lbl in bd.SCHEMES.items():
    ann_b = base["schemes"][sch]["annual"]
    ann_n = nog["schemes"][sch]["annual"]
    print(f"  {lbl}:")
    for y in BAD_YEARS:
        b, v = ann_b.get(y), ann_n.get(y)
        if b is None and v is None:
            continue
        print(f"    {y}: con oro {b}%  ->  sin oro {v}%")

print(f"\nTotal: {time.time()-t0:.0f}s")
