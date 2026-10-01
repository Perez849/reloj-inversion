"""TEMPORAL - comprobación puntual: Ken French publica cada fichero de
industrias con DOS tablas mensuales seguidas en el mismo CSV -- "Average
Value Weighted Returns" (ponderada por capitalización, como el S&P 500) y
"Average Equal Weighted Returns" (cada empresa pesa igual, grande o
pequeña). french_zip() coge la PRIMERA tabla que encuentra con una fecha de
6 dígitos en la primera columna, dando por hecho que es la value-weighted
(el orden estándar de Ken French). Nunca se ha verificado leyendo el CSV
crudo. Si estuviera leyendo la equiponderada por error, sería una causa
estructural real de 2017-2021: el S&P 500 (cap-weighted) subió por un puñado
de mega-caps tecnológicas, pero un "Tecnología" equiponderado entre cientos
de empresas pequeñas y grandes diluiría ese efecto por completo -- la
comparación dejaría de ser como con como."""
import sys
sys.path.insert(0, "scripts")
import build_data as bd
import zipfile
import io

url = bd.FRENCH_BASE + "12_Industry_Portfolios_CSV.zip"
r = bd.http_get(url)
if isinstance(r, tuple):
    print("ERROR descargando:", r)
    sys.exit(1)

zf = zipfile.ZipFile(io.BytesIO(r.content))
name = zf.namelist()[0]
print(f"Fichero dentro del zip: {name}\n")
lines = zf.read(name).decode("latin-1").splitlines()

# Mostrar las primeras ~15 líneas (cabecera del fichero + título de la primera tabla)
print("=== Primeras 15 líneas del CSV crudo ===")
for i, line in enumerate(lines[:15]):
    print(f"{i:3}: {line}")

# Encontrar TODAS las líneas que parecen títulos de tabla (contienen "Weighted")
print("\n=== Líneas que contienen 'Weighted' (marcan el inicio de cada tabla) ===")
for i, line in enumerate(lines):
    if "Weighted" in line:
        print(f"{i:5}: {line.strip()}")

# Replicar la lógica exacta de french_zip(): primera fila con token de 6 dígitos
start = None
for idx, line in enumerate(lines):
    tok = line.strip().split(",")[0].strip()
    if len(tok) == 6 and tok.isdigit():
        start = idx
        break
print(f"\n=== french_zip() usaría la primera fila de datos en la línea {start} ===")
h = start - 1
while h > 0 and not lines[h].strip():
    h -= 1
print(f"Cabecera (columnas) en la línea {h}: {lines[h].strip()}")
# Mirar hacia atrás desde esa cabecera para ver bajo qué título de tabla cae
for j in range(h, max(0, h - 10), -1):
    if "Weighted" in lines[j]:
        print(f"\n>>> La tabla que se está leyendo es: \"{lines[j].strip()}\" (línea {j})")
        break
else:
    print("\n>>> No se encontró título 'Weighted' en las 10 líneas previas a la cabecera.")

print(f"\nPrimera fila de datos real que se usaría: {lines[start].strip()}")

# Repetir exactamente igual para el fichero de 49 industrias, que es el que de verdad
# alimenta Tecnología, Semiconductores, etc. en la cartera.
print("\n\n########## 49_Industry_Portfolios_CSV.zip ##########\n")
url49 = bd.FRENCH_BASE + "49_Industry_Portfolios_CSV.zip"
r49 = bd.http_get(url49)
if isinstance(r49, tuple):
    print("ERROR descargando 49 industrias:", r49)
    sys.exit(1)
zf49 = zipfile.ZipFile(io.BytesIO(r49.content))
name49 = zf49.namelist()[0]
lines49 = zf49.read(name49).decode("latin-1").splitlines()

print("=== Líneas que contienen 'Weighted' (49 industrias) ===")
for i, line in enumerate(lines49):
    if "Weighted" in line:
        print(f"{i:5}: {line.strip()}")

start49 = None
for idx, line in enumerate(lines49):
    tok = line.strip().split(",")[0].strip()
    if len(tok) == 6 and tok.isdigit():
        start49 = idx
        break
h49 = start49 - 1
while h49 > 0 and not lines49[h49].strip():
    h49 -= 1
print(f"\nfrench_zip() usaría la primera fila de datos en la línea {start49}")
print(f"Cabecera en la línea {h49}: {lines49[h49].strip()[:200]}")
for j in range(h49, max(0, h49 - 10), -1):
    if "Weighted" in lines49[j]:
        print(f"\n>>> La tabla que se está leyendo (49 industrias) es: \"{lines49[j].strip()}\" (línea {j})")
        break
else:
    print("\n>>> No se encontró título 'Weighted' en las 10 líneas previas a la cabecera (49 industrias).")
