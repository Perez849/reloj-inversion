"""TEMPORAL - el usuario pregunta si queda algo real por mejorar. Revisando
el código a fondo (no otra ronda de ideas de catálogo): el sistema calcula un
factor "leading" (NFCI, diferencial Baa-Aaa, permisos de construcción, índice
adelantado Philly Fed, VIX, horas semanales de manufactura -- PCA de 6 series,
normalizado a desviación típica 1, igual que growth/inflation) pero SOLO lo
muestra en pantalla (meta.leading/leading_6m) -- nunca entra en classify(),
phase_probs(), means() ni rotation(). Por diseño, un indicador adelantado se
mueve ANTES que el ciclo real: si de verdad anticipa growth, usarlo para
clasificar la fase podría ganar el mes de retraso que ya tiene Ken French (ver
comentario "Ken French publica con un mes de retraso" en rotation()), que es
una limitación real y reconocida, no resuelta hasta ahora.

Dos pasos, no uno: primero comprobar si `leading` tiene de verdad poder
predictivo sobre growth FUTURO en este dataset real (correlación con growth
desplazado 1, 3 y 6 meses hacia delante) -- si no lo tiene, no tiene sentido
gastar una ronda de backtest en ello. Si lo tiene, probar varias mezclas
growth_ajustado = growth + k*leading (misma escala, los dos factores ya están
normalizados a desviación típica 1) alimentando classify()/phase_probs(), con
el propio backtest, todo el histórico, los 4 esquemas."""
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

if "leading" not in F.columns:
    print("ERROR: no se pudo construir el factor 'leading'")
    sys.exit(1)

print("=== Paso 1: ¿anticipa 'leading' el growth futuro? ===")
common = F.dropna(subset=["leading"]).index
lead = F.loc[common, "leading"]
grow = F.loc[common, "growth"]
for h in (1, 3, 6, 12):
    fwd = grow.shift(-h).reindex(common)
    c = lead.corr(fwd)
    c0 = lead.corr(grow)  # referencia: correlación contemporánea, sin desplazar
    print(f"  corr(leading_t, growth_t+{h}) = {c:+.3f}   "
          f"(referencia: corr(leading_t, growth_t) = {c0:+.3f})")

print("\nDescargando activos reales…")
X, ameta = bd.fetch_assets(df)
cls_map = {k: v.get("class", "Otros") for k, v in ameta.items()}


def run_variant(label, growth_adj):
    phases = pd.Series([bd.classify(a, b) for a, b in zip(growth_adj, F["inflation"])],
                        index=F.index, name="phase")
    sg = float(growth_adj.diff(bd.HORIZON_M).std())
    si = float(F["inflation"].diff(bd.HORIZON_M).std())
    prob_rows = {}
    for d, gg, ii in zip(F.index, growth_adj, F["inflation"]):
        prob_rows[d] = bd.phase_probs(float(gg), float(ii), sg, si)
    probs_df = pd.DataFrame(prob_rows).T.shift(1)
    rot = bd.rotation(X, phases, cls_map, probs_df, F,
                       phase_sleeve_override=bd.ESTANFLACION_OVERRIDE)
    print(f"=== {label} ===")
    for sch, lbl in bd.SCHEMES.items():
        p = rot["schemes"][sch]["portfolio"]
        wy, ny = rot["schemes"][sch]["wins_years"], rot["schemes"][sch]["n_years"]
        print(f"  {lbl:<22} CAGR {p.get('cagr')}%  Sharpe {p.get('sharpe')}  "
              f"MaxDD {p.get('maxdd')}%  años_batidos {wy}/{ny}")


print("\n=== Paso 2: ¿mejora el backtest clasificando con growth + k*leading? ===")
run_variant("BASE (solo growth, producción actual)", F["growth"])
for k in (0.2, 0.4, 0.7, 1.0):
    leading_filled = F["leading"].reindex(F.index).fillna(0.0)
    growth_adj = F["growth"] + k * leading_filled
    run_variant(f"growth + {k}*leading", growth_adj)

print(f"\nTotal: {time.time()-t0:.0f}s")
