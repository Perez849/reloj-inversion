"""TEMPORAL - dos preguntas del usuario, con el motor real, nada se adopta
todavía:

A) "A mí me cuadra más un Sobrecalentamiento esos meses [2022-2026]."
   Contrafactual acotado: para todos los meses desde 2022-01 en que la
   clasificación real fue Estanflación, se fuerza Sobrecalentamiento (fase Y
   probabilidad, 100%) y se mide qué habría pasado -- solo en esa ventana, sin
   tocar el resto de los 56 años.

B) "Exigir 2 meses seguidos antes de cambiar" -- histéresis clásica: un
   cambio de fase solo se confirma si la nueva fase aparece 2 meses
   consecutivos; si no, se queda en la última fase confirmada. Se aplica a
   TODO el histórico (no solo a la ventana reciente), para no sobreajustar.

C) "Que durante ese mes se invierta en los activos de ambas fases" -- misma
   histéresis que B para decidir cuándo confirmar, pero mientras el cambio
   está pendiente de confirmar (el primer mes de la posible nueva fase) se
   usa una mezcla 50/50 entre la fase confirmada y la candidata, en vez de
   quedarse 100% en la antigua.

Las tres se comparan contra producción (con ESTANFLACION_OVERRIDE, igual que
siempre), con el motor real de rotation(), los 4 esquemas, y además B y C se
miran también solo en 2022-2026 para responder directamente a la pregunta."""
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


base = run("BASE (producción actual)", phases_raw, probs_raw)

# --- A: contrafactual Sobrecalentamiento 2022-2026 ---
RECENT_START = "2022-01"
phases_A = phases_raw.copy()
mask_recent_estanf = (phases_A.index >= RECENT_START) & (phases_A == "Estanflación")
phases_A[mask_recent_estanf] = "Sobrecalentamiento"
probs_A = probs_raw.copy()
for d in probs_A.index[mask_recent_estanf.reindex(probs_A.index, fill_value=False)]:
    probs_A.loc[d] = 0.0
    probs_A.loc[d, "Sobrecalentamiento"] = 1.0
rot_A = run("A: 2022-2026 reclasificado Sobrecalentamiento (contrafactual)", phases_A, probs_A)

print("\n  -- Solo 2022-01 en adelante, por esquema --")
YEARS = list(range(2022, 2027))
for sch, lbl in bd.SCHEMES.items():
    ann_b = base["schemes"][sch]["annual"]
    ann_a = rot_A["schemes"][sch]["annual"]
    print(f"  {lbl}:")
    for y in YEARS:
        b, a = ann_b.get(y), ann_a.get(y)
        if b is None and a is None:
            continue
        print(f"    {y}: base (Estanflación real) {b}%  ->  contrafactual Sobrecalentamiento {a}%")

# --- B y C: histéresis de confirmación a 2 meses ---


def confirmar_con_histeresis(raw: pd.Series, blend: bool):
    """Devuelve (phases_confirmadas, probs_ajustadas). `blend=False` es la
    prueba B (durante el mes pendiente se queda 100% en la fase confirmada);
    `blend=True` es la prueba C (ese mes se reparte 50/50 confirmada/candidata)."""
    idx = raw.index
    confirmed = raw.iloc[0]
    pending, pending_n = None, 0
    out_phase = []
    out_probs = []
    for d in idx:
        p = raw.loc[d]
        if p == confirmed:
            pending, pending_n = None, 0
        else:
            if p == pending:
                pending_n += 1
            else:
                pending, pending_n = p, 1
            if pending_n >= 2:
                confirmed = pending
                pending, pending_n = None, 0
        if blend and pending is not None and pending_n == 1:
            row = {ph: 0.0 for ph in bd.PHASES}
            row[confirmed] = 0.5
            row[pending] = row.get(pending, 0.0) + 0.5
            out_probs.append(row)
            out_phase.append(confirmed)
        else:
            row = {ph: (1.0 if ph == confirmed else 0.0) for ph in bd.PHASES}
            out_probs.append(row)
            out_phase.append(confirmed)
    phases_out = pd.Series(out_phase, index=idx, name="phase")
    probs_out = pd.DataFrame(out_probs, index=idx)
    return phases_out, probs_out


phases_B, probs_B = confirmar_con_histeresis(phases_raw, blend=False)
phases_C, probs_C = confirmar_con_histeresis(phases_raw, blend=True)

n_cambios_raw = int((phases_raw != phases_raw.shift(1)).sum())
n_cambios_B = int((phases_B != phases_B.shift(1)).sum())
print(f"\nCambios de fase: crudo {n_cambios_raw}  ->  con histéresis de 2 meses {n_cambios_B}")

rot_B = run("B: histéresis -- exige 2 meses seguidos antes de cambiar", phases_B, probs_B)
rot_C = run("C: histéresis + mezcla 50/50 el mes pendiente de confirmar", phases_C, probs_C)

print("\n  -- Solo 2022-01 en adelante, por esquema (B y C) --")
for sch, lbl in bd.SCHEMES.items():
    ann_b = base["schemes"][sch]["annual"]
    ann_B = rot_B["schemes"][sch]["annual"]
    ann_C = rot_C["schemes"][sch]["annual"]
    print(f"  {lbl}:")
    for y in YEARS:
        b, vb, vc = ann_b.get(y), ann_B.get(y), ann_C.get(y)
        if b is None and vb is None and vc is None:
            continue
        print(f"    {y}: base {b}%  ->  B(2 meses) {vb}%  ->  C(mezcla) {vc}%")

print(f"\nTotal: {time.time()-t0:.0f}s")
