"""Script de investigación TEMPORAL: ¿existe una fuente real, con historia larga
comparable a Ken French, con más granularidad que las 49 industrias, para los
sectores sin desglose (Utilities, Materiales/Químicas, Comunicaciones)? Se borra
en cuanto se ha capturado el resultado — no forma parte del pipeline."""
import re

import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; investment-clock/2.0)"}
FRENCH_BASE = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
LIB_BASE = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html"


def try_fetch(url, tag):
    try:
        r = requests.get(url, timeout=30, headers=HEADERS)
        print(f"--- {tag}: HTTP {r.status_code}, {len(r.content)} bytes ---")
        return r
    except Exception as exc:  # noqa: BLE001
        print(f"--- {tag}: ERROR {exc} ---")
        return None


# 1) Ver si hay algo más fino que 49 en el FTP de Ken French (100, industry-sic4, etc.)
for name in ["100_Industry_Portfolios_CSV.zip", "38_Industry_Portfolios_CSV.zip",
             "30_Industry_Portfolios_CSV.zip", "17_Industry_Portfolios_CSV.zip",
             "5_Industry_Portfolios_CSV.zip"]:
    r = try_fetch(FRENCH_BASE + name, name)

# 2) La página índice de la biblioteca de datos: listado completo de lo que ofrece
r = try_fetch(LIB_BASE, "data_library.html")
if r is not None and r.status_code == 200:
    text = r.text
    # busca cualquier mención a "industry" o "Industries" con su enlace, y cualquier
    # cosa con "SIC" en el nombre
    for m in re.finditer(r'href="([^"]+)"[^>]*>([^<]*[Ii]ndustr[^<]*)</a>', text):
        print("LIB:", m.group(1), "|", m.group(2).strip())
    for m in re.finditer(r'>([^<]{0,80}SIC[^<]{0,80})<', text):
        print("SIC mention:", m.group(1).strip())
