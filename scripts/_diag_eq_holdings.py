"""Diagnóstico temporal: qué tuvo realmente la cartera de renta variable, mes a mes,
durante los episodios históricos citados en el manual (Volcker, puntocom, GFC, COVID,
shock de tipos 2021-23), con la ventaja de fase (mu) y volatilidad reales de cada pick
en ese momento -- no la foto de hoy. Replica el prefijo de main() hasta rot (equity)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_data as bd

df, raw_meta = bd.fetch_macro()
X, ameta = bd.fetch_assets(df)
pca_research, picks = {"error": "no ejecutado"}, {}
try:
    df, cand_meta = bd.fetch_candidates(df)
    raw_meta.update(cand_meta)
    pca_research, picks = bd.select_candidates(df)
except Exception as exc:
    print(f"ampliación del PCA omitida: {exc}")

model = None
base_series_snapshot = list(bd.SERIES)
if picks:
    try:
        model = bd.choose_pca_variant(df, X, ameta, picks, pca_research)
    except Exception as exc:
        print(f"elección de variante de PCA omitida: {exc}")
        bd.SERIES[:] = base_series_snapshot
if model is None:
    model = bd._factor_model(df)
Z, ind_info, F, pca = model["Z"], model["ind_info"], model["F"], model["pca"]
phases, sg, si, probs_df = model["phases"], model["sg"], model["si"], model["probs_df"]

Xe, emeta, elog = bd.fetch_extended()
try:
    X, ameta, universe = bd.universe_test(X, ameta, Xe, emeta, phases, probs_df, F)
except Exception as exc:
    print(f"test del universo omitido: {exc}")

cls_map = {k: v.get("class", "Otros") for k, v in ameta.items()}

log = []
rot = bd.rotation(X, phases, cls_map, probs_df, F,
                   phase_sleeve_override=bd.ESTANFLACION_OVERRIDE, holdings_log=log)

WINDOWS = [
    ("VOLCKER 1980-1982", "1980-01", "1982-12"),
    ("PUNTOCOM 2000-2002", "2000-01", "2002-12"),
    ("GFC 2007-2009", "2007-06", "2009-12"),
    ("COVID 2020", "2020-01", "2020-12"),
    ("SHOCK DE TIPOS 2021-2023", "2021-01", "2023-12"),
]

for label, a, b in WINDOWS:
    print(f"\n========== {label} ==========")
    for row in log:
        if a <= row["d"] <= b:
            rv = row["picks"].get("Renta variable", [])
            oro = row["picks"].get("Oro", [])
            rv_s = ", ".join(f"{p['c']}(mu={p['mu']:+.2f}/vol={p['vol']:.1f})" for p in rv)
            oro_s = ", ".join(f"{p['c']}(mu={p['mu']:+.2f})" for p in oro) if oro else "-"
            print(f"{row['d']}  fase={row['sig']:<20}  RV: {rv_s}  |  Oro: {oro_s}")
