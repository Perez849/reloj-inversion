"""Script TEMPORAL: confirma ICSH (bonos IG ultra corto plazo) como candidato
real -- mejora genuina y verificada en la ronda anterior (MaxDD -13,3%->-9,7%,
Worst12 -9,2%->-6,5%, Sharpe 0,68->0,72 en Inverso de la volatilidad, con CAGR
plano o mejor). Antes de implementarlo en producción, confirma que el techo de
2 sigue siendo el óptimo ahora que ICSH está en el universo (podría no serlo:
es un candidato de riesgo genuinamente bajo, distinto a por qué fallaba subir
el techo antes). Se borra tras decidir."""
import sys
import pandas as pd

sys.path.insert(0, "scripts")
import build_data as bd  # noqa: E402

bd.MARKET["Bonos IG ultra corto plazo (ICSH)"] = ("Renta fija", "ICSH", "icsh.us",
                                                    "investment-grade, ~6 meses de duración")

print("Cargando datos (macro + activos)…", flush=True)
df, raw_meta = bd.fetch_macro()
Z, ind_info = bd.build_blocks(df)
F, pca = bd.build_factors(Z)
F = F.dropna(subset=["growth", "inflation"])
phases = pd.Series([bd.classify(a, b) for a, b in zip(F["growth"], F["inflation"])],
                    index=F.index, name="phase")
sg = float(F["growth"].diff(bd.HORIZON_M).std())
si = float(F["inflation"].diff(bd.HORIZON_M).std())

X, ameta = bd.fetch_assets(df)
cls_map = {k: v.get("class", "Otros") for k, v in ameta.items()}
prob_rows = {}
for d, gg, ii in zip(F.index, F["growth"], F["inflation"]):
    prob_rows[d] = bd.phase_probs(float(gg), float(ii), sg, si)
probs_df = pd.DataFrame(prob_rows).T.shift(1)

n_fi = sum(1 for c in cls_map.values() if c in ("Renta fija", "Liquidez"))
print(f"\nUniverso total (Renta fija + Liquidez, incl. ICSH): {n_fi} activos\n")

print(f"{'techo':>5} | " + " | ".join(f"{s:^38}" for s in bd.SCHEMES.values()))
print(f"{'':>5} | " + " | ".join(f"{'CAGR':>6} {'Vol':>6} {'Sharpe':>7} {'MaxDD':>7} {'Worst12':>8}"
                                  for _ in bd.SCHEMES))
for n_max in range(2, 6):
    sleeves = {"Renta fija": ({"Renta fija", "Liquidez"}, 1.0, 1.0, 2, n_max)}
    rot = bd.rotation(X, phases, cls_map, probs_df, F, sleeves=sleeves,
                       bench_name="Renta fija EE.UU. (mercado)", include_6040=False)
    row = []
    for sch in bd.SCHEMES:
        p = rot["schemes"][sch]["portfolio"]
        row.append(f"{p.get('cagr'):>6} {p.get('vol'):>6} {p.get('sharpe'):>7} "
                    f"{p.get('maxdd'):>7} {p.get('worst12'):>8}")
    print(f"{n_max:>5} | " + " | ".join(row))
    if n_max == 2:
        best = rot["default"]
        S = rot["schemes"][best]
        icsh_phases = {}
        for phase, rows in S["playbook"].items():
            for r in rows:
                if "ICSH" in r["name"]:
                    icsh_phases[phase] = r["weight"]
        print(f"      -> ICSH en el manual por fase (esquema {best}, techo 2): {icsh_phases or 'nunca'}")
        all_phases_check = {}
        for sch2 in bd.SCHEMES:
            S2 = rot["schemes"][sch2]
            for phase, rows in S2["playbook"].items():
                for r in rows:
                    if "ICSH" in r["name"]:
                        all_phases_check.setdefault(sch2, {})[phase] = r["weight"]
        print(f"      -> ICSH en TODOS los esquemas (techo 2): {all_phases_check}")
