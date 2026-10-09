"""Prueba el candidato require_positive_raw=True contra producción (False):
exige que un activo gane dinero DE VERDAD en la fase (raw>0), no solo que
pierda menos que su propia media general. Caso real que lo motiva: TLT en
Estanflación (ir=+0.03 pero raw<0, ver sesión). Replica el prefijo de main()
hasta tener X/phases/cls_map/probs_df/F, luego compara rotation() equity y FI
con y sin el candidato, en los 4 esquemas."""
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


def dump(label, rot):
    print(f"\n--- {label} ---")
    sch_dict = rot["schemes"]
    for sch in bd.SCHEMES:
        p = sch_dict[sch]["portfolio"]
        by = sch_dict[sch]["by_phase"].get("Estanflación", {})
        print(f"  {sch:10s} sharpe={p.get('sharpe')!s:>6} cagr={p.get('cagr')!s:>6} "
              f"maxdd={p.get('maxdd')!s:>7} wins={sch_dict[sch]['wins_years']}/{sch_dict[sch]['n_years']}  "
              f"Estanflación: n={by.get('n')} ann={by.get('ann')} edge={by.get('edge')}")


print("\n########## RENTA VARIABLE (equity + oro) ##########")
rot_base = bd.rotation(X, phases, cls_map, probs_df, F, phase_sleeve_override=bd.ESTANFLACION_OVERRIDE,
                        require_positive_raw=False)
rot_cand = bd.rotation(X, phases, cls_map, probs_df, F, phase_sleeve_override=bd.ESTANFLACION_OVERRIDE,
                        require_positive_raw=True)
dump("BASE (producción)", rot_base)
dump("CANDIDATO (require_positive_raw=True)", rot_cand)
print("\nPlaybook Estanflación, candidato, scheme=rank:")
print(rot_cand["schemes"]["rank"]["playbook"]["Estanflación"])

print("\n########## RENTA FIJA ##########")
fi_base = bd.rotation(X, phases, cls_map, probs_df, F, sleeves=bd.SLEEVES_FI,
                       bench_name="Renta fija EE.UU. (mercado)", include_6040=False,
                       require_positive_raw=False)
fi_cand = bd.rotation(X, phases, cls_map, probs_df, F, sleeves=bd.SLEEVES_FI,
                       bench_name="Renta fija EE.UU. (mercado)", include_6040=False,
                       require_positive_raw=True)
dump("BASE (producción)", fi_base)
dump("CANDIDATO (require_positive_raw=True)", fi_cand)
print("\nPlaybook Estanflación, candidato, scheme=rank:")
print(fi_cand["schemes"]["rank"]["playbook"]["Estanflación"])
print("\nPlaybook Estanflación, BASE, scheme=rank (para comparar):")
print(fi_base["schemes"]["rank"]["playbook"]["Estanflación"])
