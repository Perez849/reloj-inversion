"""TEMPORAL - última idea de la ronda de "nuevos horizontes" para renta
variable: el bloque de cobertura táctica (hoy solo oro/mineras) podría
ganar con un segundo instrumento distinto. TIPS (bonos ligados a la
inflación) se comportan distinto al oro en estanflación/reflación -- suben
con la inflación esperada pero sin la volatilidad de las mineras. Se prueba
añadiendo "TIPS (TIP)" (ETF real, 2003+) como candidato más dentro del mismo
bloque "Oro" (banda y techo sin cambiar: 0-20%, máximo 2 nombres), sobre
TODO el histórico, 4 esquemas."""
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
cls_map_base = {k: v.get("class", "Otros") for k, v in ameta.items()}

sg = float(F["growth"].diff(bd.HORIZON_M).std())
si = float(F["inflation"].diff(bd.HORIZON_M).std())
prob_rows = {}
for d, gg, ii in zip(F.index, F["growth"], F["inflation"]):
    prob_rows[d] = bd.phase_probs(float(gg), float(ii), sg, si)
probs_df = pd.DataFrame(prob_rows).T.shift(1)

print(f"Datos listos en {time.time()-t0:.0f}s.\n")


def run(label, cls_map_):
    rot = bd.rotation(X, phases, cls_map_, probs_df, F,
                       phase_sleeve_override=bd.ESTANFLACION_OVERRIDE)
    print(f"=== {label} ===")
    for sch, lbl in bd.SCHEMES.items():
        p = rot["schemes"][sch]["portfolio"]
        wy, ny = rot["schemes"][sch]["wins_years"], rot["schemes"][sch]["n_years"]
        print(f"  {lbl:<22} CAGR {p.get('cagr')}%  Sharpe {p.get('sharpe')}  "
              f"MaxDD {p.get('maxdd')}%  años_batidos {wy}/{ny}")
    return rot


run("BASE (producción actual)", cls_map_base)

cls_tips = dict(cls_map_base)
if "TIPS (TIP)" in cls_tips:
    cls_tips["TIPS (TIP)"] = "Oro"
    print(f"'TIPS (TIP)' reclasificado a Oro (antes: {cls_map_base.get('TIPS (TIP)')})\n")
else:
    print("AVISO: 'TIPS (TIP)' no está en el universo cargado\n")
run("+ TIPS como segundo instrumento de cobertura junto al oro", cls_tips)

print(f"\nTotal: {time.time()-t0:.0f}s")
