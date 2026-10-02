"""TEMPORAL - el usuario pide explícitamente abrir horizontes: nuevos
sectores (biotecnología, emergentes...), nuevas ideas, sin apalancamiento ni
cortos. Cuatro candidatos concretos, todos datos YA presentes en el sistema
pero excluidos por diseño de "Renta variable" (clase "Índice regional" o
"Estilo"), o derivables del mismo modo en que ya se separó Semiconductores
de Tecnología (ver FRENCH_49/ASSET_OVERLAP):

  V1 - Renta variable emergente (EEM) + internacional (EFA): ETFs reales,
       historia desde 2001-2003. Hoy excluidos como "índice de país, no
       sector" -- razón de diseño: "un índice diversificado tiene mejor
       rentabilidad por unidad de riesgo que cualquier sector suelto y
       siempre barre". Pero esa razón es de ANTES de que means() pasara a
       medir ventaja RELATIVA a la media propia del activo (ver su
       docstring) -- un índice ya diversificado puede tener una ventaja de
       FASE más plana que un sector concentrado, así que puede que ya no
       sea cierto que siempre gane. Se comprueba, no se asume.
  V2 - Lo mismo pero con las carteras internacionales de Ken French
       (Desarrollados ex EE.UU. / Emergentes), misma fuente que ya
       funciona, historia desde 1990 -- más larga que los ETFs.
  V3 - Small caps (IWM, clase "Estilo" hoy, excluida por el mismo motivo
       que V1/V2). Early-cycle outperformance de las small caps es un
       patrón real y conocido -- ¿lo captura el reloj si se le deja competir?
  V4 - Biotecnología/Farmacéuticas como sector PROPIO de renta variable,
       separado de Salud -- exactamente el mismo tratamiento que ya recibió
       Semiconductores (separado de Tecnología): se toma la industria 49 de
       Ken French "Drugs" (la pieza SIC 2830-2836, lo más parecido a
       "biotech" que Ken French publica) como candidato independiente, con
       un ASSET_OVERLAP contra Salud para que no cuenten la misma exposición
       dos veces.

Cada variante se prueba SOLA (no todas a la vez) para aislar su efecto,
sobre TODO el histórico, en los 4 esquemas de reparto -- misma disciplina
que el resto de la sesión: si gana, se adopta; si no, se descarta con los
números por delante."""
import sys
import time
sys.path.insert(0, "scripts")
import build_data as bd
import pandas as pd
import numpy as np

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

# --- V4: construir la serie de "Drugs" (biotecnología/farma) de las 49 ---
print("Descargando 49 industrias para extraer Farmacéuticas/biotech…")
ff, _ = bd.french_zip(bd.FRENCH_BASE + "F-F_Research_Data_Factors_CSV.zip", "factores")
ind49, _ = bd.french_zip(bd.FRENCH_BASE + "49_Industry_Portfolios_CSV.zip", "49 industrias")
drugs_excess = None
if ff is not None and ind49 is not None and "Drugs" in ind49.columns:
    rf = ff["RF"].reindex(ind49.index)
    drugs_excess = (ind49["Drugs"] - rf).dropna()
    print(f"  ✓ Farmacéuticas/biotech: {drugs_excess.size} meses "
          f"desde {drugs_excess.index[0].date()}")
else:
    print("  ✗ no se pudo construir la serie de Farmacéuticas/biotech")


def run(label, X_, cls_map_, asset_overlap_extra=None):
    orig_overlap = dict(bd.ASSET_OVERLAP)
    if asset_overlap_extra:
        bd.ASSET_OVERLAP = {**orig_overlap, **asset_overlap_extra}
    try:
        rot = bd.rotation(X_, phases, cls_map_, probs_df, F,
                           phase_sleeve_override=bd.ESTANFLACION_OVERRIDE)
    finally:
        bd.ASSET_OVERLAP = orig_overlap
    print(f"=== {label} ===")
    for sch, lbl in bd.SCHEMES.items():
        p = rot["schemes"][sch]["portfolio"]
        wy, ny = rot["schemes"][sch]["wins_years"], rot["schemes"][sch]["n_years"]
        print(f"  {lbl:<22} CAGR {p.get('cagr')}%  Sharpe {p.get('sharpe')}  "
              f"MaxDD {p.get('maxdd')}%  años_batidos {wy}/{ny}")
    return rot


run("BASE (producción actual)", X, cls_map_base)

cls_v1 = dict(cls_map_base)
for name in ("Renta variable emergente", "Renta variable internacional"):
    if name in cls_v1:
        cls_v1[name] = "Renta variable"
run("V1: + EEM/EFA (ETFs reales, 2001-2003+) como renta variable", X, cls_v1)

cls_v2 = dict(cls_map_base)
for name in ("Desarrollados ex EE.UU. (French)", "Emergentes (French)"):
    if name in cls_v2:
        cls_v2[name] = "Renta variable"
run("V2: + internacional/emergente Ken French (1990+) como renta variable", X, cls_v2)

cls_v3 = dict(cls_map_base)
if "Small caps" in cls_v3:
    cls_v3["Small caps"] = "Renta variable"
run("V3: + Small caps (IWM) como renta variable", X, cls_v3)

if drugs_excess is not None:
    X_v4 = X.copy()
    X_v4["Farmacéuticas (biotech)"] = drugs_excess.reindex(X_v4.index)
    cls_v4 = dict(cls_map_base)
    cls_v4["Farmacéuticas (biotech)"] = "Renta variable"
    run("V4: + Farmacéuticas/biotech como sector propio (vs Salud)", X_v4, cls_v4,
        asset_overlap_extra={"Farmacéuticas (biotech)": "Salud"})

print(f"\nTotal: {time.time()-t0:.0f}s")
