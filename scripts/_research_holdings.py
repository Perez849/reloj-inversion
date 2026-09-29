"""Script de investigación TEMPORAL: ¿se pueden descargar las posiciones reales
(holdings) de los ETFs que ya usa la web (iShares, SPDR/State Street, VanEck),
para sustituir los ejemplos de empresas "de memoria" por las posiciones de verdad
del propio fondo? Prueba un ticker de cada proveedor antes de escalar. Se borra
en cuanto se ha capturado el resultado — no forma parte del pipeline."""
import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"}


def try_fetch(url, tag, timeout=20):
    try:
        r = requests.get(url, timeout=timeout, headers=HEADERS)
        print(f"--- {tag}: HTTP {r.status_code}, {len(r.content)} bytes, "
              f"content-type={r.headers.get('content-type')} ---")
        if r.status_code == 200:
            print("    primeros 500 bytes:", r.content[:500])
        return r
    except Exception as exc:  # noqa: BLE001
        print(f"--- {tag}: ERROR {exc} ---")
        return None


# 1) iShares: patrón AJAX CSV conocido para IYW (US Technology)
try_fetch(
    "https://www.ishares.com/us/products/239600/ishares-us-technology-etf/"
    "1467271812596.ajax?fileType=csv&fileName=IYW_holdings&dataType=fund",
    "iShares IYW csv (product id conocido)")

# 2) iShares: página del fondo, buscar el link real de descarga
try_fetch("https://www.ishares.com/us/products/239600/ishares-us-technology-etf",
          "iShares IYW product page")

# 3) SPDR / State Street: patrón xlsx conocido para XLK
try_fetch(
    "https://www.ssga.com/us/en/individual/library-content/products/fund-data/"
    "etfs/us/holdings-daily-us-en-xlk.xlsx",
    "SPDR XLK holdings xlsx")

# 4) VanEck: SMH holdings
try_fetch("https://www.vaneck.com/us/en/investments/semiconductor-etf-smh/holdings/",
          "VanEck SMH holdings page")
try_fetch("https://www.vaneck.com/etf/equity/smh/holdings/",
          "VanEck SMH holdings alt path")
