"""TEMPORAL - prueba la idea de ponderar los meses históricos de cada fase por
lo PARECIDOS que fueron a la lectura actual de (growth, inflación), en vez de
una media histórica plana de la fase. Motivación, con datos reales: el
growth medio de 2024-2026 (-0.24) es menos de un tercio de severo que el
episodio histórico de Estanflación más suave (1979-82: -0.80), y la inflación
ya se ha normalizado (+0.72 frente a +2.38 en 2022). classify() no distingue
intensidad -- este episodio suave recibe la misma etiqueta y, con la media
histórica plana, las mismas expectativas de rentabilidad que 1973 o el 2000.

Implementación (ver _ew_sim en build_data.py, parámetro nuevo
`similarity_bandwidth`, por defecto None = comportamiento idéntico al
actual): dentro de cada fase, el peso de un mes histórico ya no es solo por
antigüedad (_ew) sino antigüedad x un núcleo gaussiano de distancia en el
plano (growth, inflación) a la lectura de HOY. Con bandwidth pequeño, un
episodio suave como el actual pesa casi solo hacia otros episodios suaves;
con bandwidth grande, se acerca a la media plana de siempre.

Se prueban varios anchos de banda (0.5, 0.75, 1.0, 1.5, 2.0 -- en las mismas
unidades que growth/inflación, ya normalizados a desviación típica 1) contra
producción, con el motor real, todo el histórico, 4 esquemas."""
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


def run(label, bandwidth):
    rot = bd.rotation(X, phases, cls_map, probs_df, F,
                       phase_sleeve_override=bd.ESTANFLACION_OVERRIDE,
                       similarity_bandwidth=bandwidth)
    print(f"=== {label} ===")
    for sch, lbl in bd.SCHEMES.items():
        p = rot["schemes"][sch]["portfolio"]
        wy, ny = rot["schemes"][sch]["wins_years"], rot["schemes"][sch]["n_years"]
        print(f"  {lbl:<22} CAGR {p.get('cagr')}%  Sharpe {p.get('sharpe')}  "
              f"MaxDD {p.get('maxdd')}%  años_batidos {wy}/{ny}")
    return rot


base = run("BASE (sin ponderar por similitud, producción actual)", None)
results = {}
for bw in (0.5, 0.75, 1.0, 1.5, 2.0):
    results[bw] = run(f"bandwidth = {bw}", bw)

print("\n=== Comparación 2022-2026 por esquema (solo el mejor y el peor bandwidth en CAGR global) ===")
YEARS = list(range(2022, 2027))
best_bw = max(results, key=lambda bw: results[bw]["schemes"]["equal"]["portfolio"].get("cagr", -1e9))
for sch, lbl in bd.SCHEMES.items():
    ann_b = base["schemes"][sch]["annual"]
    ann_best = results[best_bw]["schemes"][sch]["annual"]
    print(f"  {lbl} (bandwidth {best_bw}):")
    for y in YEARS:
        b, v = ann_b.get(y), ann_best.get(y)
        if b is None and v is None:
            continue
        print(f"    {y}: base {b}%  ->  bandwidth {best_bw} {v}%")

print(f"\nTotal: {time.time()-t0:.0f}s")
