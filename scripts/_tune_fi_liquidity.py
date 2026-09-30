"""Script TEMPORAL: ¿mejora el reloj de renta fija si se permite Liquidez (letras 3m)
como candidato, además de los 13 activos de clase "Renta fija"? Prueba real, con
datos reales, en vez de extrapolar del hallazgo de renta variable (donde el
mecanismo degenerado -- vol casi nula, IR se dispara -- ya se documentó, pero el
contexto de pares (bonos frente a bonos, no bonos frente a acciones) es distinto y
merece su propia comprobación). Se borra tras decidir. No forma parte del pipeline
de producción."""
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

liq = X["Liquidez (letras 3m)"].dropna()
print(f"\nLiquidez (letras 3m): {liq.index[0].date()} -> {liq.index[-1].date()}, "
      f"{liq.size} meses. Media anualizada {liq.mean()*12:.3f}% · "
      f"vol anualizada {liq.std()*(12**0.5):.3f}%")
print(f"(rf global = Ken French RF, 1 mes; Liquidez = FRED TB3MS/12, 3 meses -- "
f"la diferencia mide el spread 3m/1m, no un exceso tautológico)\n")

# bd.NOT_SELECTABLE bloquea "Liquidez (letras 3m)" globalmente; para esta prueba se
# quita SOLO de una copia local, sin tocar el módulo real.
not_selectable_sin_liquidez = bd.NOT_SELECTABLE - {"Liquidez (letras 3m)"}

configs = [
    ("n_max=2, sin liquidez (actual, referencia)", 2, False),
    ("n_max=2, CON liquidez elegible", 2, True),
    ("n_max=3, CON liquidez elegible", 3, True),
    ("n_max=4, CON liquidez elegible", 4, True),
]

print(f"{'config':<42} | " + " | ".join(f"{s:^38}" for s in bd.SCHEMES.values()))
print(f"{'':<42} | " + " | ".join(f"{'CAGR':>6} {'Vol':>6} {'Sharpe':>7} {'MaxDD':>7} {'Worst12':>8}"
                                  for _ in bd.SCHEMES))
for label, n_max, allow_liq in configs:
    classes = {"Renta fija", "Liquidez"} if allow_liq else {"Renta fija"}
    sleeves_fi = {"Renta fija": (classes, 1.0, 1.0, 2, n_max)}
    orig_ns = bd.NOT_SELECTABLE
    if allow_liq:
        bd.NOT_SELECTABLE = not_selectable_sin_liquidez
    try:
        rot = bd.rotation(X, phases, cls_map, probs_df, F,
                           sleeves=sleeves_fi,
                           bench_name="Renta fija EE.UU. (mercado)",
                           include_6040=False)
    finally:
        bd.NOT_SELECTABLE = orig_ns
    if not rot:
        print(f"{label:<42} | (sin resultado)")
        continue
    row = []
    for sch in bd.SCHEMES:
        p = rot["schemes"][sch]["portfolio"]
        row.append(f"{p.get('cagr'):>6} {p.get('vol'):>6} {p.get('sharpe'):>7} "
                    f"{p.get('maxdd'):>7} {p.get('worst12'):>8}")
    print(f"{label:<42} | " + " | ".join(row))

    # ¿Cuántos meses tuvo liquidez en cartera, y en qué fases, con el esquema ganador?
    if allow_liq:
        best = rot["default"]
        S = rot["schemes"][best]
        liq_phases = {}
        for phase, rows in S["playbook"].items():
            for r in rows:
                if r["name"] == "Liquidez (letras 3m)":
                    liq_phases[phase] = r["weight"]
        print(f"    -> Liquidez en el manual por fase (esquema {best}): {liq_phases or 'nunca'}")
