"""Script TEMPORAL de calibración: determina N_MAX_FI empíricamente, igual que
se hizo con el techo de 5 en SLEEVES["Renta variable"]. Se borra tras decidir
el valor. No forma parte del pipeline de producción."""
import sys
import pandas as pd

sys.path.insert(0, "scripts")
import build_data as bd  # noqa: E402

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

fi_assets = sorted(a for a, c in cls_map.items() if c == "Renta fija")
print(f"\nUniverso 'Renta fija' ({len(fi_assets)}): {fi_assets}")
print(f"Pares ASSET_OVERLAP relevantes: "
      f"{[(c, p) for c, p in bd.ASSET_OVERLAP.items() if p in fi_assets or c in fi_assets]}")
bench_row = X["Renta fija EE.UU. (mercado)"].dropna()
print(f"Benchmark AGG: {bench_row.index[0].date()} → {bench_row.index[-1].date()}, "
      f"{bench_row.size} meses\n")

print(f"{'n_max':>5} | " + " | ".join(f"{s:^38}" for s in bd.SCHEMES.values()))
print(f"{'':>5} | " + " | ".join(f"{'CAGR':>6} {'Vol':>6} {'Sharpe':>7} {'MaxDD':>7} {'Worst12':>8}"
                                  for _ in bd.SCHEMES))
for n_max in range(2, 11):
    sleeves_fi = {"Renta fija": ({"Renta fija"}, 1.0, 1.0, 2, n_max)}
    rot = bd.rotation(X, phases, cls_map, probs_df, F,
                       sleeves=sleeves_fi,
                       bench_name="Renta fija EE.UU. (mercado)",
                       include_6040=False)
    if not rot:
        print(f"{n_max:>5} | (sin resultado)")
        continue
    row = []
    for sch in bd.SCHEMES:
        p = rot["schemes"][sch]["portfolio"]
        row.append(f"{p.get('cagr'):>6} {p.get('vol'):>6} {p.get('sharpe'):>7} "
                    f"{p.get('maxdd'):>7} {p.get('worst12'):>8}")
    print(f"{n_max:>5} | " + " | ".join(row))

bench_perf = bd.rotation(X, phases, cls_map, probs_df, F,
                          sleeves={"Renta fija": ({"Renta fija"}, 1.0, 1.0, 2, 5)},
                          bench_name="Renta fija EE.UU. (mercado)",
                          include_6040=False)["bench_100eq"]
print(f"\nAGG solo (referencia): CAGR {bench_perf.get('cagr')} · Vol {bench_perf.get('vol')} · "
      f"Sharpe {bench_perf.get('sharpe')} · MaxDD {bench_perf.get('maxdd')} · "
      f"Worst12 {bench_perf.get('worst12')} · desde {bench_perf.get('from')}")
