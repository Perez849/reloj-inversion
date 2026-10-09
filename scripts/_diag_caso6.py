"""Diagnóstico temporal: holdings_log de renta variable, 2020-06 a 2024-06,
para reescribir el Caso 6 (shock de tipos 2021-2023) del manual técnico con el
mecanismo real mes a mes -- por qué 2021 y 2023 perdieron frente al S&P 500 y
por qué 2022 ganó, no solo el año que ya se explicaba. Replica el prefijo real
de main() hasta la llamada a rotation(). No se publica: se revierte tras leer
los logs."""
import json
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

from build_data import (
    fetch_macro, fetch_assets, fetch_candidates, select_candidates,
    choose_pca_variant, _factor_model,
    rotation, SERIES, ESTANFLACION_OVERRIDE,
)

df, raw_meta = fetch_macro()
X, ameta = fetch_assets(df)
pca_research, picks = {"error": "no ejecutado"}, {}
try:
    df, cand_meta = fetch_candidates(df)
    pca_research, picks = select_candidates(df)
except Exception as exc:
    print("ampliación del PCA omitida:", exc)
model = None
base_series_snapshot = list(SERIES)
if picks:
    try:
        model = choose_pca_variant(df, X, ameta, picks, pca_research)
    except Exception as exc:
        print("elección de variante de PCA omitida:", exc)
        SERIES[:] = base_series_snapshot
if model is None:
    model = _factor_model(df)
Z, ind_info, F, pca = model["Z"], model["ind_info"], model["F"], model["pca"]
phases, sg, si, probs_df = model["phases"], model["sg"], model["si"], model["probs_df"]

# fetch_extended/universe_test se omiten a propósito: el propio manual (Capítulo 6)
# confirma que esa ampliación nunca se adopta (adopted=[] en los datos reales), así
# que el universo de activos queda idéntico al de producción, solo más rápido.
cls_map = {k: v.get("class", "Otros") for k, v in ameta.items()}

log = []
rot = rotation(X, phases, cls_map, probs_df, F,
               phase_sleeve_override=ESTANFLACION_OVERRIDE, holdings_log=log)

print("\n=== rot keys ===", list(rot.keys())[:10])
print("default scheme:", rot.get("default"))
sch = rot["schemes"][rot["default"]]
print("annual 2019-2024:", {y: sch["annual"].get(str(y)) for y in range(2019, 2025)})
print("bench_annual 2019-2024:", {y: rot["bench_annual"].get(str(y)) for y in range(2019, 2025)})

print("\n=== holdings_log, 2020-06 a 2024-06 ===")
for row in log:
    if "2020-06" <= row["d"] <= "2024-06":
        print(json.dumps(row, ensure_ascii=False))
