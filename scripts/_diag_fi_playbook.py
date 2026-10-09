"""Diagnóstico temporal: por qué el playbook de Estanflación (foto de HOY) recomienda
TLT/MBB, cuando el backtest real walk-forward lleva desde 2024 sin tocarlos.
Replica el prefijo de main() hasta rot_fi; build_data.py tiene un print de depuración
temporal dentro de rotation() (bloque playbook) que se activa solo."""
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

rot_fi = bd.rotation(X, phases, cls_map, probs_df, F, sleeves=bd.SLEEVES_FI,
                      bench_name="Renta fija EE.UU. (mercado)", include_6040=False)

print("\n=== PLAYBOOK FINAL (scheme=rank) PARA ESTANFLACIÓN ===")
print(rot_fi["rank"]["playbook"]["Estanflación"])
