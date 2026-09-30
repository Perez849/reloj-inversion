"""Script TEMPORAL: diagnostica el tramo bajista real de 2021-2024 del reloj de
renta fija (4 años seguidos en negativo pese a rotar). Para cada mes: fase vigente,
qué dos activos sostuvo la cartera y su peso, retorno de la cartera ese mes, y el
retorno crudo de TODOS los candidatos actuales de renta fija ese mes -- para ver si
había algo mejor disponible que el algoritmo no cogió, o si de verdad no había nada
que no cayera. También prueba un candidato nuevo (préstamos bancarios a tipo
variable, BKLN) para ver si habría amortiguado el tramo. Se borra tras decidir."""
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

fi_candidates = sorted(a for a, c in cls_map.items() if c in ("Renta fija", "Liquidez"))
print(f"\nUniverso actual ({len(fi_candidates)}): {fi_candidates}\n")

# Intento de un candidato NUEVO: préstamos bancarios a tipo flotante (BKLN,
# Invesco Senior Loan ETF) -- casi sin duración, distinto del resto del universo.
bkln, e1 = bd.yahoo_monthly("BKLN")
if bkln is None:
    bkln, e2 = bd.stooq_monthly("bkln.us")
    print(f"BKLN: yahoo falló ({e1}), stooq {'OK' if bkln is not None else 'también falló (' + str(e2) + ')'}")
else:
    print(f"BKLN (Yahoo): {bkln.index[0].date()} -> {bkln.index[-1].date()}, {bkln.size} meses")
if bkln is not None:
    rf_series = (df["TB3MS"] / 12.0).reindex(bkln.index).ffill()
    bkln_excess = (bkln - rf_series).dropna()
    print(f"BKLN exceso sobre rf: media anualizada {bkln_excess.mean()*12:.2f}%, "
          f"vol anualizada {bkln_excess.std()*(12**0.5):.2f}%")

sleeves_fi = bd.SLEEVES_FI
rot = bd.rotation(X, phases, cls_map, probs_df, F, sleeves=sleeves_fi,
                   bench_name="Renta fija EE.UU. (mercado)", include_6040=False)
S = rot["schemes"][rot["default"]]
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
    import numpy as np
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
print(f"{'fecha':<8} {'fase':<16} {'picks (peso%)':<45} {'ret cartera':>11} | mejores/peores candidatos del mes")
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
    month_rets = Xc.loc[t, fi_candidates].dropna().sort_values(ascending=False)
    best3 = ", ".join(f"{n}:{v:.1f}" for n, v in month_rets.head(3).items())
    worst2 = ", ".join(f"{n}:{v:.1f}" for n, v in month_rets.tail(2).items())
    print(f"{t.strftime('%Y-%m')}  {sig:<16} {picks_str:<45} {port_ret:>10.2f}% | mejores: {best3} | peores: {worst2}")
