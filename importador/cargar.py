"""
ETAPA 4 — CARGAR A SUPABASE
Sube datos/4_enriquecido.json usando la función importar_pelicula:
  - las que ya existen no se duplican (solo se les agregan sus IDs)
  - las nuevas entran como 'revisar' y no salen en la tragamonedas hasta que las apruebes

Necesita en importador/.env:
  SUPABASE_URL=https://tu-proyecto.supabase.co
  SUPABASE_SERVICE_KEY=tu-llave-secreta      (service_role o "secret key"; NUNCA en el frontend)

Uso:  python cargar.py
"""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

BASE = Path(__file__).parent
DATOS = BASE / "datos"


def cargar_env():
    env = BASE / ".env"
    if env.exists():
        for linea in env.read_text(encoding="utf-8").splitlines():
            if "=" in linea and not linea.strip().startswith("#"):
                k, v = linea.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    faltan = [k for k in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY") if not os.environ.get(k)]
    if faltan:
        raise SystemExit(f"Faltan en importador/.env: {', '.join(faltan)}")


def main():
    cargar_env()
    url = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/rpc/importar_pelicula"
    llave = os.environ["SUPABASE_SERVICE_KEY"]
    headers = {"Content-Type": "application/json", "apikey": llave}
    if llave.startswith("eyJ"):                     # llaves antiguas (JWT) también van como Bearer
        headers["Authorization"] = "Bearer " + llave
    sesion = requests.Session()
    sesion.headers.update(headers)

    pelis = json.loads((DATOS / "4_enriquecido.json").read_text(encoding="utf-8"))
    print(f"Cargando {len(pelis)} películas a Supabase…")

    def una(p):
        datos = {k: v for k, v in p.items() if not k.startswith("_")}   # _pistas y _revision no se suben
        try:
            r = sesion.post(url, json={"p": datos}, timeout=60)
        except requests.RequestException as e:
            return p, None, f"error de red: {e}"
        if r.status_code != 200:
            try:
                msg = r.json().get("message", r.text)
            except ValueError:
                msg = r.text
            return p, None, msg
        return p, r.json(), None

    conteo = {"nueva": 0, "existente": 0}
    errores = []
    with ThreadPoolExecutor(4) as ex:
        for n, (p, res, err) in enumerate(ex.map(una, pelis), 1):
            if err:
                errores.append(f"  {p['titulo']} ({p['anio']}): {err}")
                if len(errores) == 1 and ("401" in err or "Invalid API key" in err or "permission" in err.lower()):
                    raise SystemExit("Supabase rechazó la llave. Revisa SUPABASE_SERVICE_KEY en .env "
                                     "(debe ser la service_role / secret key, no la publishable).")
            else:
                conteo[res["resultado"]] += 1
            if n % 25 == 0 or n == len(pelis):
                print(f"   {n}/{len(pelis)}")

    print(f"\nNuevas (en 'revisar'): {conteo['nueva']}")
    print(f"Ya existían (solo se conectaron con Wikidata): {conteo['existente']}")
    if errores:
        print(f"Con error ({len(errores)}):")
        print("\n".join(errores[:20]))
    print("\nPara verlas en la tragamonedas, apruébalas en el SQL Editor de Supabase (ver LEEME.md).")


if __name__ == "__main__":
    main()