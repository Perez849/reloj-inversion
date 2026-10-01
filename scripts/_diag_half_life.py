"""TEMPORAL - el usuario pregunta si el sistema pesa el pasado lejano igual que
el reciente ("lo que funcionaba en 1950 no es lo que funciona en 1980... tiene
que haber adaptabilidad generacional"). Respuesta corta: SÍ existe ya ese
mecanismo -- means() y ew_vol() usan una media exponencialmente ponderada por
antigüedad (_ew), con HALF_LIFE_M = 60 meses (5 años): lo de hace 5 años pesa
la mitad que lo de hoy, lo de hace 50 años pesa ~1000 veces menos. Ya se probó
bajar de 10 a 5 años (ver comentario en build_data.py, línea ~1785) con mejora
real. Esta pasada comprueba si 60 sigue siendo el mejor punto, probando un
rango real alrededor (24, 36, 48, 60, 90, 120 meses) sobre TODO el histórico,
en los 4 esquemas de reparto, con el mismo rigor que las rondas anteriores."""
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

ORIG_HL = bd.HALF_LIFE_M
CANDIDATES = [24, 36, 48, 60, 90, 120]

for hl in CANDIDATES:
    bd.HALF_LIFE_M = hl
    rot = bd.rotation(X, phases, cls_map, probs_df, F,
                       phase_sleeve_override=bd.ESTANFLACION_OVERRIDE)
    tag = " (actual)" if hl == ORIG_HL else ""
    print(f"=== HALF_LIFE_M = {hl} meses ({hl/12:.1f} años){tag} ===")
    for sch, label in bd.SCHEMES.items():
        p = rot["schemes"][sch]["portfolio"]
        wy, ny = rot["schemes"][sch]["wins_years"], rot["schemes"][sch]["n_years"]
        print(f"  {label:<22} CAGR {p.get('cagr')}%  Sharpe {p.get('sharpe')}  "
              f"MaxDD {p.get('maxdd')}%  años_batidos {wy}/{ny}")
    print()

bd.HALF_LIFE_M = ORIG_HL
print(f"Total: {time.time()-t0:.0f}s")
