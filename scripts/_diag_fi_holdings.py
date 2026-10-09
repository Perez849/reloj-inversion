"""Diagnóstico temporal: qué tuvo realmente el reloj de renta fija cada mes
desde 2021, y cómo se compara con el rendimiento real de TLT/MBB/AGG en 2022.
Replica EXACTAMENTE el prefijo de main() hasta rot_fi (ver build_data.py)."""
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

holdings_log = []
rot_fi = bd.rotation(X, phases, cls_map, probs_df, F, sleeves=bd.SLEEVES_FI,
                      bench_name="Renta fija EE.UU. (mercado)", include_6040=False,
                      holdings_log=holdings_log)

print("\n=== ACTIVOS DISPONIBLES (nombres relacionados con TLT/MBB/AGG) ===")
for name in X.columns:
    if any(s in name for s in ("Treasury 20", "TLT", "hipotecari", "MBB", "agregado",
                                "AGG", "Renta fija EE.UU")):
        print(" -", name)

print("\n=== HOLDINGS MES A MES DEL RELOJ DE RENTA FIJA, 2021-01 en adelante ===")
for row in holdings_log:
    if row["d"] >= "2021-01":
        print(f"{row['d']}  fase={row['sig']:<16}  cartera={row['picks'].get('Renta fija')}")

# X está en EXCESO sobre letras y en puntos porcentuales (ver _annual/_add_rf en
# build_data.py: "(1 + series/100.0)"). Para el retorno TOTAL real hay que sumar
# el tipo libre de riesgo (bd._add_rf) y luego SOLO dividir entre 100, no *100.
targets = [c for c in X.columns
           if "Treasury 20" in c or c == "Titulizaciones hipotecarias (MBB)"
           or "Renta fija EE.UU" in c]

print("\n=== RENDIMIENTOS MENSUALES TOTALES REALES 2021-2023 (TLT, MBB, AGG) ===")
for col in targets:
    sub = bd._add_rf(X[col])
    sub = sub[(sub.index >= "2021-01") & (sub.index <= "2023-12")]
    print(f"\n--- {col} ---")
    for d, v in sub.items():
        if v == v:
            print(f"  {d.strftime('%Y-%m')}: {v:+.2f}%")

print("\n=== ACUMULADO 2022 REAL (producto de 1+r mensual, retorno TOTAL) ===")
for col in targets:
    sub = bd._add_rf(X[col])
    sub2022 = sub[(sub.index >= "2022-01") & (sub.index <= "2022-12")].dropna()
    if len(sub2022):
        cum = 1.0
        for v in sub2022:
            cum *= (1 + v / 100.0)
        print(f"  {col}: {len(sub2022)} meses, acumulado 2022 = {(cum-1)*100:+.2f}%")
