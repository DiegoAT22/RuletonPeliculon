"""
PASO 1 — BAJAR LOS DATOS DE SUPABASE
Llama a exportar_datos_modelo() (15_exportar_modelo.sql) y guarda en modelo/datos/:
  interacciones.csv   persona, película, respuesta, origen, fecha, con_cuenta
  titulos.csv         el catálogo publicado
  rasgos.csv          los rasgos de cada película con su peso
  claves.csv          a qué grupo pertenece cada rasgo

Usa la misma llave que el importador: lee importador/.env (o modelo/.env si existe).
  SUPABASE_URL=https://tu-proyecto.supabase.co
  SUPABASE_SERVICE_KEY=tu-llave-secreta      (NUNCA en el frontend ni en el repo)

Uso:  python descargar.py
"""
import csv
import os
import sys
from pathlib import Path

import requests

BASE = Path(__file__).parent
DATOS = BASE / "datos"


def cargar_env():
    for env in (BASE / ".env", BASE.parent / "importador" / ".env"):
        if env.exists():
            for linea in env.read_text(encoding="utf-8").splitlines():
                if "=" in linea and not linea.strip().startswith("#"):
                    k, v = linea.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    faltan = [k for k in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY") if not os.environ.get(k)]
    if faltan:
        raise SystemExit(f"Faltan en importador/.env (o modelo/.env): {', '.join(faltan)}")


def proteger():
    """Los datos bajados y los modelos no deben subirse al repo (es público): se ignoran en git."""
    gi = BASE / ".gitignore"
    if not gi.exists():
        gi.write_text("datos/\ndatos_demo/\nsalidas/\nsalidas_demo/\n.env\n__pycache__/\n", encoding="utf-8")


def guardar(nombre, encabezado, filas):
    with open(DATOS / nombre, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(encabezado)
        w.writerows(filas)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    cargar_env()
    proteger()
    url = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/rpc/exportar_datos_modelo"
    llave = os.environ["SUPABASE_SERVICE_KEY"]
    headers = {"Content-Type": "application/json", "apikey": llave}
    if llave.startswith("eyJ"):                       # llave service_role del formato anterior
        headers["Authorization"] = "Bearer " + llave

    print("Bajando datos de Supabase…")
    r = requests.post(url, headers=headers, json={}, timeout=180)
    if r.status_code in (401, 403):
        raise SystemExit("Supabase rechazó la llave. Revisa SUPABASE_SERVICE_KEY en .env "
                         "(debe ser la secreta, no la publishable).")
    if r.status_code == 404:
        raise SystemExit("No existe exportar_datos_modelo(): corre primero 15_exportar_modelo.sql en Supabase.")
    if not r.ok:
        raise SystemExit(f"Error {r.status_code}: {r.text[:300]}")
    d = r.json()

    DATOS.mkdir(exist_ok=True)
    guardar("interacciones.csv", ["usuario", "titulo_id", "accion", "origen", "creado_en", "con_cuenta"], d["interacciones"])
    guardar("titulos.csv", ["titulo_id", "titulo", "anio", "popularidad"], d["titulos"])
    guardar("rasgos.csv", ["titulo_id", "clave", "peso"], d["rasgos"])
    guardar("claves.csv", ["clave", "grupo", "etiqueta"], d["claves"])

    inter = d["interacciones"]
    personas = {}
    for fila in inter:
        personas[fila[0]] = personas.get(fila[0], 0) + 1
    con_cuenta = {fila[0] for fila in inter if fila[5]}
    print(f"  {len(d['titulos'])} películas, {len(d['claves'])} rasgos distintos")
    print(f"  {len(inter)} opiniones de {len(personas)} personas ({len(con_cuenta)} con cuenta)")
    print(f"  con 20 o más: {sum(1 for n in personas.values() if n >= 20)}   con 50 o más: {sum(1 for n in personas.values() if n >= 50)}")
    print(f"Guardado en {DATOS}")
    print("Siguiente:  python entrenar.py")


if __name__ == "__main__":
    main()
