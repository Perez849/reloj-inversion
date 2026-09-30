"""Script TEMPORAL: tercera ronda de pruebas reales para el tramo bajista
2021-2024 del reloj de renta fija. Las dos primeras hipótesis (préstamos
bancarios BKLN, aflojar el suelo de 2 a 1) se probaron con datos reales y las
dos empeoraron el resultado. Esta ronda prueba tres candidatos genuinamente
distintos, cada uno inyectado en MARKET con su PROPIA clase (para poder
probarlos uno a uno y juntos, cada uno fuera de SLEEVES_FI por defecto) para
pasar por el mismo fetch_assets()/guardián de plausibilidad/resta de rf que
cualquier otro activo -- nunca un cálculo aparte:

- VTIP (TIPS de corto plazo, 0-5 años): mucha menos sensibilidad a tipos
  reales que el TIPS a 10 años que ya hay en el universo, conservando la
  protección de inflación.
- ICSH (bonos investment-grade ultra corto plazo, ~6 meses de duración):
  perfil de crédito mucho más conservador que BKLN (grado de inversión, no
  high yield), a ver si evita el problema de diferencial de crédito que hundió
  a los préstamos bancarios.
- BNDX (bonos soberanos internacionales, cubiertos en dólares): ciclo de tipos
  distinto al de la Reserva Federal, sin el riesgo de traducción de divisa que
  habría lastrado a una versión sin cubrir en un año de dólar fuerte como 2022.

Se prueba cada uno por separado y los tres juntos, con datos reales. Se borra
tras decidir."""
import sys
import pandas as pd

sys.path.insert(0, "scripts")
import build_data as bd  # noqa: E402

CANDIDATES = {
    "VTIP": ("VTIP", "vtip.us", "TIPS corto plazo (0-5 años)", "Cand_VTIP"),
    "ICSH": ("ICSH", "icsh.us", "bonos IG ultra corto plazo (~6 meses)", "Cand_ICSH"),
    "BNDX": ("BNDX", "bndx.us", "soberanos internacionales, cubiertos en USD", "Cand_BNDX"),
}
for label, (ysym, stick, note, cls) in CANDIDATES.items():
    bd.MARKET[f"Candidato: {label}"] = (cls, ysym, stick, note)

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

print()
loaded = {}
for label, (ysym, stick, note, cls) in CANDIDATES.items():
    name = f"Candidato: {label}"
    if name in X.columns:
        s = X[name].dropna()
        loaded[label] = (name, cls)
        print(f"{label}: {s.index[0].date()} -> {s.index[-1].date()}, {s.size} meses. "
              f"Exceso sobre rf: media anualizada {s.mean()*12:.2f}%, "
              f"vol anualizada {s.std()*(12**0.5):.2f}%")
        worst_months = ["2022-01", "2022-04", "2022-06", "2022-09",
                         "2023-08", "2023-09", "2023-10", "2024-04",
                         "2024-10", "2024-11", "2024-12"]
        vals = []
        for wm in worst_months:
            t = pd.Timestamp(wm + "-01") + pd.offsets.MonthEnd(0)
            if t in s.index:
                vals.append(f"{wm}:{s.loc[t]:+.1f}")
        print(f"  en los peores meses del tramo: {', '.join(vals)}")
    else:
        print(f"{label}: NO se cargó")
        for a in bd.ASSET_LOG:
            if label in a.get("name", ""):
                print(" ", a)
print()

sleeves_base = {"Renta fija": bd.SLEEVES_FI["Renta fija"]}
rot_base = bd.rotation(X, phases, cls_map, probs_df, F, sleeves=sleeves_base,
                        bench_name="Renta fija EE.UU. (mercado)", include_6040=False)
p0 = rot_base["schemes"]["equal"]["portfolio"]
print(f"Referencia (universo actual, sin candidatos nuevos), Equiponderado: "
      f"CAGR {p0.get('cagr')} · Sharpe {p0.get('sharpe')} · MaxDD {p0.get('maxdd')} · "
      f"Worst12 {p0.get('worst12')}\n")

base_classes = {"Renta fija", "Liquidez"}


def test_combo(label, extra_classes):
    classes = base_classes | extra_classes
    sleeves = {"Renta fija": (classes, 1.0, 1.0, 2, 2)}
    rot = bd.rotation(X, phases, cls_map, probs_df, F, sleeves=sleeves,
                       bench_name="Renta fija EE.UU. (mercado)", include_6040=False)
    print(f"--- {label} ---")
    for sch in bd.SCHEMES:
        p = rot["schemes"][sch]["portfolio"]
        print(f"  {bd.SCHEMES[sch]}: CAGR {p.get('cagr')} · Sharpe {p.get('sharpe')} · "
              f"MaxDD {p.get('maxdd')} · Worst12 {p.get('worst12')}")
    best = rot["default"]
    Sb = rot["schemes"][best]
    picked = {}
    for phase, rows in Sb["playbook"].items():
        for r in rows:
            if r["class"] in extra_classes:
                picked.setdefault(phase, []).append((r["name"], r["weight"]))
    print(f"  candidatos nuevos en el manual (esquema {best}): {picked or 'ninguno'}\n")


if "VTIP" in loaded:
    test_combo("+ VTIP (TIPS corto plazo) elegible", {loaded["VTIP"][1]})
if "ICSH" in loaded:
    test_combo("+ ICSH (IG ultra corto plazo) elegible", {loaded["ICSH"][1]})
if "BNDX" in loaded:
    test_combo("+ BNDX (soberanos internacionales cubiertos) elegible", {loaded["BNDX"][1]})
if len(loaded) == 3:
    test_combo("+ los tres a la vez elegibles", {loaded[k][1] for k in loaded})
