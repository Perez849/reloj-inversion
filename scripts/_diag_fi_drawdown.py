"""Script TEMPORAL: diagnostica el tramo bajista real de 2021-2024 del reloj de
renta fija (4 años seguidos en negativo pese a rotar). Para cada mes: fase vigente,
qué dos activos sostuvo la cartera y su peso, retorno de la cartera ese mes, y el
retorno crudo de TODOS los candidatos -- del universo actual MÁS un candidato nuevo,
préstamos bancarios a tipo flotante (BKLN) -- para ver si había algo mejor
disponible que el algoritmo no cogió, o si de verdad no había nada que no cayera.
BKLN se inyecta en MARKET antes de fetch_assets() para que pase por el mismo
guardián de plausibilidad y la misma resta del tipo sin riesgo que cualquier otro
activo -- no un cálculo aparte con una convención distinta. Se borra tras decidir."""
import sys
import pandas as pd

sys.path.insert(0, "scripts")
import build_data as bd  # noqa: E402

# Préstamos bancarios a tipo flotante (Invesco Senior Loan ETF): casi sin
# duración porque el cupón se revisa cada 30-90 días con el tipo de referencia,
# a diferencia de TODO lo demás en el universo actual, que es a cupón fijo.
# Clase propia ("Préstamos"), NO "Renta fija": así queda fuera de SLEEVES_FI por
# defecto y el primer backtest de abajo reproduce el sistema actual sin
# contaminar -- solo se hace elegible explícitamente en la prueba de comparación
# final, añadiendo esa clase al conjunto de bloques.
bd.MARKET["Préstamos bancarios (BKLN)"] = ("Préstamos", "BKLN", "bkln.us",
                                            "tipo flotante, casi sin duración")

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

bkln_name = "Préstamos bancarios (BKLN)"
has_bkln = bkln_name in X.columns
if has_bkln:
    b = X[bkln_name].dropna()
    print(f"\n{bkln_name}: {b.index[0].date()} -> {b.index[-1].date()}, {b.size} meses. "
          f"Exceso sobre rf: media anualizada {b.mean()*12:.2f}%, vol anualizada {b.std()*(12**0.5):.2f}%")
else:
    print(f"\n{bkln_name}: NO se cargó (revisar ASSET_LOG más abajo)")
    for a in bd.ASSET_LOG:
        if "BKLN" in a.get("name", "") or "bancarios" in a.get("name", ""):
            print(" ", a)

fi_candidates = sorted(a for a, c in cls_map.items() if c in ("Renta fija", "Liquidez"))
compare_universe = sorted(set(fi_candidates) | ({bkln_name} if has_bkln else set()))
print(f"Universo de comparación ({len(compare_universe)}): {compare_universe}\n")

sleeves_fi = {"Renta fija": bd.SLEEVES_FI["Renta fija"]}
rot = bd.rotation(X, phases, cls_map, probs_df, F, sleeves=sleeves_fi,
                   bench_name="Renta fija EE.UU. (mercado)", include_6040=False)
print(f"\nEsquema por defecto: {rot['default']}\n")

# Recalcular manualmente picks mes a mes para el tramo 2021-2024 (rotation() no
# expone el historial de picks, solo el resumen). Reproduce fielmente la lógica
# interna de rotation() para ese tramo.
common = X.dropna(how="all").index.intersection(phases.dropna().index)
Xc = X.loc[common]
ph = phases.loc[common]


def _ew(frame, ref_date, half_life=bd.HALF_LIFE_M):
    months = pd.Series([(ref_date.year - d.year) * 12 + (ref_date.month - d.month)
                        for d in frame.index], index=frame.index, dtype=float)
    return 0.5 ** (months / half_life)


def _wmean(frame, w):
    ww = frame.notna().mul(w, axis=0)
    return frame.mul(w, axis=0).sum() / ww.sum().replace(0, float("nan"))


def ew_vol(hist):
    ref = hist.index[-1]
    w = _ew(hist, ref)
    m = _wmean(hist, w)
    dev2 = (hist.sub(m, axis=1) ** 2)
    ww = dev2.notna().mul(w, axis=0)
    return (dev2.mul(w, axis=0).sum() / ww.sum().replace(0, float("nan"))) ** 0.5


def means(hist, hph, phase):
    ref = hist.index[-1]
    grand = _wmean(hist, _ew(hist, ref))
    mu_p, se_p, n_p = {}, {}, {}
    for p in bd.PHASES:
        sub = hist[hph == p]
        if sub.empty:
            continue
        mu_p[p] = _wmean(sub, _ew(sub, ref))
        n = sub.notna().sum()
        n_p[p] = n
        se_p[p] = sub.std() / (n.clip(lower=1) ** 0.5)
    if phase not in mu_p or len(mu_p) < 2:
        return mu_p.get(phase, grand) - grand
    M = pd.DataFrame(mu_p).T
    SE2 = pd.DataFrame(se_p).T ** 2
    N = pd.DataFrame(n_p).T
    tau2 = (M.var(axis=0, ddof=1) - SE2.mean(axis=0)).clip(lower=0.0)
    d = tau2 + SE2.loc[phase]
    w = (tau2 / d).where(d > 0, 0.0).fillna(0.0)
    w = w.where(N.loc[phase] >= bd.MIN_PHASE_OBS, 0.0)
    return w * (M.loc[phase] - grand)


start_win = pd.Timestamp("2021-01-01")
end_win = pd.Timestamp("2024-12-31")
print(f"{'fecha':<8} {'fase':<16} {'picks (peso%)':<45} {'ret cartera':>11} | BKLN | mejores/peores del mes (incl. BKLN)")
for k in range(120, len(common)):
    t = common[k]
    if t < start_win or t > end_win:
        continue
    sig = ph.iloc[k - 1]
    hist, hph = Xc.iloc[:k], ph.iloc[:k]
    vol = ew_vol(hist)
    sub_sig = hist[hph == sig]
    raw_phase = (_wmean(sub_sig, _ew(sub_sig, hist.index[-1])) if not sub_sig.empty
                 else _wmean(hist, _ew(hist, hist.index[-1])))
    mu = means(hist, hph, sig)
    avail = list(Xc.loc[t].dropna().index)
    (classes, lo, hi, n_min, n_max) = sleeves_fi["Renta fija"]
    top, score = bd._sleeve_pick(mu, vol, raw_phase, avail, classes, cls_map, n_min, n_max)
    if not top:
        continue
    w = bd._weights(top, vol, "equal")
    port_ret = sum(float(w[c]) * float(Xc.loc[t, c]) for c in top)
    picks_str = ", ".join(f"{c} ({w[c]*100:.0f}%)" for c in top)
    bkln_ret = Xc.loc[t, bkln_name] if has_bkln and bkln_name in Xc.columns and pd.notna(Xc.loc[t, bkln_name]) else None
    bkln_str = f"{bkln_ret:+.1f}" if bkln_ret is not None else "s/d"
    month_rets = Xc.loc[t, compare_universe].dropna().sort_values(ascending=False)
    best3 = ", ".join(f"{n}:{v:.1f}" for n, v in month_rets.head(3).items())
    worst2 = ", ".join(f"{n}:{v:.1f}" for n, v in month_rets.tail(2).items())
    print(f"{t.strftime('%Y-%m')}  {sig:<16} {picks_str:<45} {port_ret:>10.2f}% | {bkln_str:>4} | mejores: {best3} | peores: {worst2}")

if has_bkln:
    print("\n--- ¿Habría cambiado algo con BKLN en el universo elegible? ---")
    sleeves_with_bkln = {"Renta fija": ({"Renta fija", "Liquidez", "Préstamos"}, 1.0, 1.0, 2, 2)}
    rot2 = bd.rotation(X, phases, cls_map, probs_df, F, sleeves=sleeves_with_bkln,
                        bench_name="Renta fija EE.UU. (mercado)", include_6040=False)
    for sch in bd.SCHEMES:
        p = rot2["schemes"][sch]["portfolio"]
        print(f"  {bd.SCHEMES[sch]}: CAGR {p.get('cagr')} · Sharpe {p.get('sharpe')} · "
              f"MaxDD {p.get('maxdd')} · Worst12 {p.get('worst12')}")
    best = rot2["default"]
    Sb = rot2["schemes"][best]
    bkln_phases = {}
    for phase, rows in Sb["playbook"].items():
        for r in rows:
            if r["name"] == bkln_name:
                bkln_phases[phase] = r["weight"]
    print(f"  BKLN en el manual por fase (esquema {best}): {bkln_phases or 'nunca'}")

print("\n--- ¿Ayuda soltar el suelo de 2 a 1 (sin BKLN, universo actual)? ---")
print("Si Liquidez es, con mucho, la mejor puntuada un mes, el suelo de 2 la obliga")
print("a compartir la mitad del bloque con la segunda mejor aunque puntúe negativo.")
print("Con suelo 1, esos meses podrían quedarse al 100% en Liquidez.\n")
sleeves_floor1 = {"Renta fija": ({"Renta fija", "Liquidez"}, 1.0, 1.0, 1, 2)}
rot3 = bd.rotation(X, phases, cls_map, probs_df, F, sleeves=sleeves_floor1,
                    bench_name="Renta fija EE.UU. (mercado)", include_6040=False)
for sch in bd.SCHEMES:
    p = rot3["schemes"][sch]["portfolio"]
    print(f"  {bd.SCHEMES[sch]}: CAGR {p.get('cagr')} · Sharpe {p.get('sharpe')} · "
          f"MaxDD {p.get('maxdd')} · Worst12 {p.get('worst12')}")
best3name = rot3["default"]
S3 = rot3["schemes"][best3name]
single_phases = {ph_: [r["name"] for r in rows] for ph_, rows in S3["playbook"].items()
                  if len(rows) == 1}
print(f"  Fases con una sola posición (esquema {best3name}): {single_phases or 'ninguna'}")

print("\n(referencia, suelo=techo=2, universo actual sin BKLN):")
for sch in bd.SCHEMES:
    p = rot["schemes"][sch]["portfolio"]
    print(f"  {bd.SCHEMES[sch]}: CAGR {p.get('cagr')} · Sharpe {p.get('sharpe')} · "
          f"MaxDD {p.get('maxdd')} · Worst12 {p.get('worst12')}")
