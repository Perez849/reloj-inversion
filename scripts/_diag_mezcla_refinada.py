"""TEMPORAL - afina la idea C de la ronda anterior (histéresis de 2 meses +
mezcla 50/50 solo en el mes de duda). Resultado de esa ronda: mejora la
caída máxima en los 4 esquemas, pero pierde años frente al benchmark y algo
de CAGR -- todavía no gana limpio. Dos refinamientos, ambos probados contra
el mismo BASE y la propia C original, todo el histórico, 4 esquemas:

  D) Mezclar también el mes en que se CONFIRMA el cambio (el segundo mes
     consecutivo), no solo el primer mes de duda. C original pasaba a
     100% de la fase nueva justo en ese segundo mes; D lo suaviza: 50/50
     en el mes 1 Y en el mes 2, 100% a partir del mes 3.
  E) Rampa asimétrica en vez de 50/50 plano: 25% nueva / 75% vieja en el
     mes 1 (la nueva fase aún no ha demostrado nada), 75% nueva / 25%
     vieja en el mes 2 (ya lleva dos meses seguidos), 100% desde el mes 3.

El umbral de confirmación sigue siendo 2 meses seguidos en los tres casos
(C, D, E) -- lo que cambia es SOLO cuánto se mezcla mientras tanto."""
import sys
import time
sys.path.insert(0, "scripts")
import build_data as bd
import pandas as pd

t0 = time.time()
print("Descargando datos macro reales…")
df, raw_meta = bd.fetch_macro()
Z, ind_info = bd.build_blocks(df)
F, pca = bd.build_factors(Z)
F = F.dropna(subset=["growth", "inflation"])
phases_raw = pd.Series([bd.classify(a, b) for a, b in zip(F["growth"], F["inflation"])],
                       index=F.index, name="phase")

print("Descargando activos reales…")
X, ameta = bd.fetch_assets(df)
cls_map = {k: v.get("class", "Otros") for k, v in ameta.items()}

sg = float(F["growth"].diff(bd.HORIZON_M).std())
si = float(F["inflation"].diff(bd.HORIZON_M).std())
prob_rows = {}
for d, gg, ii in zip(F.index, F["growth"], F["inflation"]):
    prob_rows[d] = bd.phase_probs(float(gg), float(ii), sg, si)
probs_raw = pd.DataFrame(prob_rows).T.shift(1)

print(f"Datos listos en {time.time()-t0:.0f}s.\n")


def run(label, phases_, probs_):
    rot = bd.rotation(X, phases_, cls_map, probs_, F,
                       phase_sleeve_override=bd.ESTANFLACION_OVERRIDE)
    print(f"=== {label} ===")
    for sch, lbl in bd.SCHEMES.items():
        p = rot["schemes"][sch]["portfolio"]
        wy, ny = rot["schemes"][sch]["wins_years"], rot["schemes"][sch]["n_years"]
        print(f"  {lbl:<22} CAGR {p.get('cagr')}%  Sharpe {p.get('sharpe')}  "
              f"MaxDD {p.get('maxdd')}%  años_batidos {wy}/{ny}")
    return rot


def confirmar_con_mezcla(raw: pd.Series, weights_new):
    """weights_new[j] = peso de la fase candidata en el (j+1)-ésimo mes
    consecutivo distinto de la confirmada (incluido el propio mes en que se
    confirma, el último de la lista). Se confirma el cambio en cuanto el
    candidato lleva len(weights_new) meses seguidos -- a partir del mes
    SIGUIENTE ya es 100% la fase nueva sin más mezcla. Una racha que no
    llega a ese umbral nunca se confirma y la fase vuelve a la confirmada
    previa en cuanto deja de repetirse, igual que la prueba B/C anterior."""
    idx = raw.index
    k = len(weights_new)
    confirmed = raw.iloc[0]
    candidate, run_n = None, 0
    out_phase, out_probs = [], []
    for d in idx:
        p = raw.loc[d]
        if p == confirmed:
            candidate, run_n = None, 0
            row = {ph: (1.0 if ph == confirmed else 0.0) for ph in bd.PHASES}
            out_probs.append(row)
            out_phase.append(confirmed)
            continue
        run_n = run_n + 1 if p == candidate else 1
        candidate = p
        w = weights_new[min(run_n, k) - 1]
        old_confirmed = confirmed
        if run_n >= k:
            confirmed = candidate  # desde el mes siguiente, 100% automático
        row = {ph: 0.0 for ph in bd.PHASES}
        row[old_confirmed] = row.get(old_confirmed, 0.0) + (1.0 - w)
        row[candidate] = row.get(candidate, 0.0) + w
        out_probs.append(row)
        out_phase.append(old_confirmed if run_n < k else candidate)
        if run_n >= k:
            candidate, run_n = None, 0
    phases_out = pd.Series(out_phase, index=idx, name="phase")
    probs_out = pd.DataFrame(out_probs, index=idx)
    return phases_out, probs_out


# C original (ronda anterior, para tener los tres juntos y comparables):
# confirma a los 2 meses, pero el propio mes 2 (de confirmación) ya pasa a
# 100% nueva -- solo el mes 1 se mezcla. Se reconstruye aquí con el mismo
# armazón que D/E dándole al mes 2 un peso de 1.0 (sin mezcla real en él).
phases_C, probs_C = confirmar_con_mezcla(phases_raw, weights_new=[0.5, 1.0])
phases_D, probs_D = confirmar_con_mezcla(phases_raw, weights_new=[0.5, 0.5])
phases_E, probs_E = confirmar_con_mezcla(phases_raw, weights_new=[0.25, 0.75])

base = run("BASE (producción actual)", phases_raw, probs_raw)
rot_C = run("C: mezcla solo en el mes de duda (ronda anterior)", phases_C, probs_C)
rot_D = run("D: mezcla también en el mes en que se confirma", phases_D, probs_D)
rot_E = run("E: rampa asimétrica 25/75 -> 75/25", phases_E, probs_E)

print("\n  -- Solo 2022-01 en adelante, por esquema --")
YEARS = list(range(2022, 2027))
for sch, lbl in bd.SCHEMES.items():
    ann_b = base["schemes"][sch]["annual"]
    ann_C = rot_C["schemes"][sch]["annual"]
    ann_D = rot_D["schemes"][sch]["annual"]
    ann_E = rot_E["schemes"][sch]["annual"]
    print(f"  {lbl}:")
    for y in YEARS:
        b, c, d_, e = ann_b.get(y), ann_C.get(y), ann_D.get(y), ann_E.get(y)
        if b is None and c is None and d_ is None and e is None:
            continue
        print(f"    {y}: base {b}%  ->  C {c}%  ->  D {d_}%  ->  E {e}%")

print(f"\nTotal: {time.time()-t0:.0f}s")
