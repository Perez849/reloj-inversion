"""Script de investigación TEMPORAL: descubrir el mapeo real (por código SIC) entre
las 49 industrias de Ken French y las 12 industrias ya usadas en build_data.py.
Se borra en cuanto se ha capturado el resultado — no forma parte del pipeline."""
import io
import zipfile

import requests

FRENCH_BASE = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; investment-clock/2.0)"}


def try_fetch(name):
    url = FRENCH_BASE + name
    try:
        r = requests.get(url, timeout=30, headers=HEADERS)
        print(f"--- {name}: HTTP {r.status_code}, {len(r.content)} bytes ---")
        if r.status_code != 200:
            return None
        return r.content
    except Exception as exc:  # noqa: BLE001
        print(f"--- {name}: ERROR {exc} ---")
        return None


CANDIDATES = [
    "Siccodes12.zip", "Siccodes49.zip",
    "Siccodes12.txt", "Siccodes49.txt",
]

for name in CANDIDATES:
    content = try_fetch(name)
    if content is None:
        continue
    if name.endswith(".zip"):
        try:
            zf = zipfile.ZipFile(io.BytesIO(content))
            print("    namelist:", zf.namelist())
            for n in zf.namelist():
                text = zf.read(n).decode("latin-1")
                print(f"    === contenido de {n} ({len(text)} chars) ===")
                print(text)
        except Exception as exc:  # noqa: BLE001
            print("    no es un zip válido:", exc)
    else:
        print(content.decode("latin-1"))
