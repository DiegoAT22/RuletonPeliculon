"""
ETAPA 1 — EXTRAER
Jala de Wikidata las películas candidatas, sus visitas en la Wikipedia en
español y todos sus datos crudos. Todo se guarda en la carpeta datos/ con
caché: si lo vuelves a correr, solo descarga lo que falte.

Uso:  python extraer.py
"""
import datetime as dt
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

import config

DATOS = Path(__file__).parent / "datos"
DATOS.mkdir(exist_ok=True)

S = requests.Session()
S.headers["User-Agent"] = config.USER_AGENT

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
SPARQL_URL = "https://query.wikidata.org/sparql"

# Propiedades de Wikidata que usamos
PROPS_PELICULA = [
    "P31",    # instancia de (película, película animada…)
    "P577",   # fecha de estreno
    "P2047",  # duración
    "P57",    # director
    "P161",   # reparto
    "P272",   # productora
    "P136",   # género
    "P495",   # país de origen
    "P364",   # idioma original
    "P144",   # basado en
    "P1476",  # título original
    "P4947",  # ID de TMDB
    "P345",   # ID de IMDb
]
PROPS_REFERENCIA = ["P297", "P218", "P31"]  # código ISO de país, código ISO de idioma, tipo de obra
QUALIFICADORES = ["P453", "P4633"]          # personaje (como elemento / como texto)


# ---------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------
def cargar(nombre, defecto):
    p = DATOS / nombre
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else defecto


def guardar(nombre, obj):
    (DATOS / nombre).write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


_pausa_hasta = 0.0          # cuando un servidor pide calma, TODOS los hilos esperan
_candado = threading.Lock()


def _esperar_turno():
    while True:
        with _candado:
            falta = _pausa_hasta - time.time()
        if falta <= 0:
            return
        time.sleep(min(falta, 5))


def pedir(url, params=None, intentos=12):
    """GET con reintentos. Si el servidor responde 429 (demasiadas peticiones),
    pausa a todos los hilos el tiempo que el servidor indique."""
    global _pausa_hasta
    for i in range(intentos):
        _esperar_turno()
        try:
            r = S.get(url, params=params, timeout=120)
        except requests.RequestException as e:
            print(f"   error de red ({e}); reintento…")
            time.sleep(5 * (i + 1))
            continue
        if r.status_code == 429 or r.status_code >= 500:
            espera = int(r.headers.get("Retry-After", 5 * (i + 1))) + 1
            with _candado:
                if time.time() + espera > _pausa_hasta:
                    _pausa_hasta = time.time() + espera
                    print(f"   servidor ocupado ({r.status_code}); pausa de {espera}s…")
            continue
        time.sleep(config.PAUSA_ENTRE_PETICIONES)
        return r
    raise SystemExit(f"No se pudo completar la petición después de {intentos} intentos: {url}\n"
                     "Tu avance quedó guardado en datos/: vuelve a correr el script más tarde y sigue donde se quedó.")


# ---------------------------------------------------------------------
# Paso 1: candidatas (películas con artículo en Wikipedia en español)
# ---------------------------------------------------------------------
SPARQL = """
SELECT DISTINCT ?pelicula ?sitelinks ?articulo WHERE {
  VALUES ?tipo { wd:Q11424 wd:Q24869 wd:Q29168811 wd:Q202866 }
  ?pelicula wdt:P31 ?tipo ;
            wikibase:sitelinks ?sitelinks .
  FILTER(?sitelinks >= %d)
  ?art schema:about ?pelicula ;
       schema:isPartOf <https://es.wikipedia.org/> ;
       schema:name ?articulo .
}
"""


def paso_candidatas():
    guardado = cargar("1_candidatas.json", None)
    if guardado and guardado.get("min_sitelinks") == config.MIN_SITELINKS:
        print(f"1) Candidatas: {len(guardado['peliculas'])} (desde caché)")
        return guardado["peliculas"]

    print(f"1) Consultando Wikidata (películas con {config.MIN_SITELINKS}+ Wikipedias)…")
    r = pedir(SPARQL_URL, {"query": SPARQL % config.MIN_SITELINKS, "format": "json"}, intentos=2)
    if r.status_code != 200:
        raise SystemExit(f"Wikidata rechazó la consulta ({r.status_code}). "
                         "Si fue timeout, sube MIN_SITELINKS en config.py.")
    peliculas = {}
    for fila in r.json()["results"]["bindings"]:
        qid = fila["pelicula"]["value"].rsplit("/", 1)[1]
        peliculas[qid] = {
            "qid": qid,
            "sitelinks": int(fila["sitelinks"]["value"]),
            "articulo": fila["articulo"]["value"],
        }
    lista = list(peliculas.values())
    guardar("1_candidatas.json", {"min_sitelinks": config.MIN_SITELINKS, "peliculas": lista})
    print(f"   {len(lista)} candidatas")
    return lista


# ---------------------------------------------------------------------
# Paso 2: visitas de los últimos 60 días en es.wikipedia
# Usa la API de Wikipedia, que acepta 50 artículos por petición.
# ---------------------------------------------------------------------
def paso_visitas(peliculas):
    # v2: la versión anterior no seguía la "continuación" de la API y dejó en 0 a muchas películas
    cache = cargar("cache_visitas_60d_v2.json", {})
    faltan = list(dict.fromkeys(p["articulo"] for p in peliculas if p["articulo"] not in cache))
    lotes = [faltan[i:i + 50] for i in range(0, len(faltan), 50)]
    print(f"2) Visitas en Wikipedia (últimos 60 días): {len(cache)} en caché, "
          f"{len(faltan)} por descargar en {len(lotes)} lotes")

    def lote(titulos):
        base = {"action": "query", "prop": "pageviews", "pvipdays": 60, "titles": "|".join(titulos),
                "redirects": 1, "format": "json", "formatversion": 2}
        params, cambio, vistas = dict(base), {}, {}
        for _ in range(100):
            j = pedir("https://es.wikipedia.org/w/api.php", params).json()
            d = j.get("query", {})
            for x in d.get("normalized", []) + d.get("redirects", []):
                cambio[x["from"]] = x["to"]
            # La API reparte las visitas en varias respuestas: cada página trae sus datos una vez
            for pg in d.get("pages", []):
                if pg.get("pageviews"):
                    total = sum(v or 0 for v in pg["pageviews"].values())
                    vistas[pg["title"]] = max(vistas.get(pg["title"], 0), total)
            if "continue" not in j:
                break
            params = {**base, **j["continue"]}
        salida = {}
        for t in titulos:
            real, saltos = t, 0
            while real in cambio and saltos < 5:
                real, saltos = cambio[real], saltos + 1
            salida[t] = vistas.get(real, 0)
        return salida

    with ThreadPoolExecutor(config.HILOS) as ex:
        for n, res in enumerate(ex.map(lote, lotes), 1):
            cache.update(res)
            if n % 5 == 0 or n == len(lotes):
                guardar("cache_visitas_60d_v2.json", cache)
                print(f"   {n}/{len(lotes)}")
    guardar("cache_visitas_60d_v2.json", cache)

    ceros = sum(1 for p in peliculas if not cache.get(p["articulo"]))
    print(f"   películas con 0 visitas: {ceros} de {len(peliculas)}")
    if ceros > len(peliculas) * 0.2:
        print("   ⚠ Son demasiadas en 0: algo raro pasó con las visitas, avísale a Claude antes de seguir.")

    for p in peliculas:
        p["vistas_12m"] = cache.get(p["articulo"], 0)   # (nombre histórico del campo; son 60 días)
    return peliculas


# ---------------------------------------------------------------------
# Paso 3: datos completos (API de Wikidata, conserva el orden del reparto)
# ---------------------------------------------------------------------
def valor(snak):
    """Convierte un valor de Wikidata a algo simple."""
    if snak.get("snaktype") != "value":
        return None
    dv = snak["datavalue"]
    tipo, v = dv["type"], dv["value"]
    if tipo == "wikibase-entityid":
        return v["id"]
    if tipo == "time":
        return {"t": v["time"], "p": v["precision"]}
    if tipo == "quantity":
        return {"a": float(v["amount"]), "u": v["unit"].rsplit("/", 1)[-1]}
    if tipo == "monolingualtext":
        return {"text": v["text"], "lang": v["language"]}
    return v  # texto (IDs externos)


def recortar(entidad, props):
    """Se queda solo con etiquetas es/mul/en y las propiedades que usamos."""
    etiquetas = entidad.get("labels", {})
    claims = {}
    for p in props:
        salida = []
        for c in entidad.get("claims", {}).get(p, []):
            if c.get("rank") == "deprecated":
                continue
            v = valor(c["mainsnak"])
            if v is None:
                continue
            quals = {}
            for q in QUALIFICADORES:
                vals = [valor(s) for s in c.get("qualifiers", {}).get(q, [])]
                vals = [x for x in vals if x is not None]
                if vals:
                    quals[q] = vals
            salida.append({"v": v, "q": quals} if quals else {"v": v})
        if salida:
            claims[p] = salida
    return {
        "l": {idioma: etiquetas.get(idioma, {}).get("value") for idioma in ("es", "mul", "en")},
        "c": claims,
    }


def entidades(ids, con_claims, props, archivo_cache, etiqueta):
    cache = cargar(archivo_cache, {})
    faltan = [i for i in dict.fromkeys(ids) if i not in cache]
    lotes = [faltan[i:i + 50] for i in range(0, len(faltan), 50)]
    print(f"   {etiqueta}: {len(cache)} en caché, {len(faltan)} por descargar")

    def lote(ids_lote):
        while True:
            r = pedir(WIKIDATA_API, {
                "action": "wbgetentities", "ids": "|".join(ids_lote),
                "props": "labels|claims" if con_claims else "labels",
                "languages": "es|mul|en", "format": "json", "maxlag": 5,
            })
            d = r.json()
            if d.get("error", {}).get("code") == "maxlag":
                time.sleep(5)
                continue
            if "error" in d:
                raise SystemExit(f"Error de Wikidata: {d['error']}")
            return ids_lote, d.get("entities", {})

    with ThreadPoolExecutor(config.HILOS) as ex:
        for n, (pedidos, ents) in enumerate(ex.map(lote, lotes), 1):
            for qid, e in ents.items():
                limpio = {} if "missing" in e else recortar(e, props)
                cache[qid] = limpio
                origen = e.get("redirects", {}).get("from")
                if origen:
                    cache[origen] = limpio
            for qid in pedidos:              # evita volver a pedir IDs inexistentes
                cache.setdefault(qid, {})
            if n % 20 == 0:
                guardar(archivo_cache, cache)
                print(f"   {n}/{len(lotes)} lotes")
    guardar(archivo_cache, cache)
    return cache


def ids_en(ent, props, con_personaje=False):
    salida = []
    for p in props:
        for c in ent.get("c", {}).get(p, []):
            if isinstance(c["v"], str) and c["v"].startswith("Q"):
                salida.append(c["v"])
            if con_personaje:
                salida += [x for x in c.get("q", {}).get("P453", []) if isinstance(x, str)]
    return salida


def paso_detalles(peliculas):
    seleccion = sorted(peliculas, key=lambda p: p["vistas_12m"], reverse=True)[:config.LIMITE]
    print(f"3) Datos completos de las {len(seleccion)} más vistas")
    pelis = entidades([p["qid"] for p in seleccion], True, PROPS_PELICULA, "cache_peliculas.json", "películas")

    # Países, idiomas y obras en que se basan: necesitamos sus códigos y tipos
    con_codigos = []
    for p in seleccion:
        con_codigos += ids_en(pelis.get(p["qid"], {}), ["P495", "P364", "P144"])
    refs = entidades(con_codigos, True, PROPS_REFERENCIA, "cache_referencias.json", "países/idiomas/obras")

    # Personas, productoras, géneros, personajes y tipos de obra: solo nombres
    nombres = []
    for p in seleccion:
        ent = pelis.get(p["qid"], {})
        nombres += ids_en(ent, ["P57", "P272", "P136", "P31"])
        nombres += ids_en(ent, ["P161"], con_personaje=True)
    for qid in dict.fromkeys(con_codigos):
        nombres += ids_en(refs.get(qid, {}), ["P31"])
    solo_nombres = entidades(nombres, False, [], "cache_nombres.json", "nombres")

    todas_refs = {**solo_nombres, **refs}
    crudo = {
        "generado": dt.datetime.now().isoformat(timespec="seconds"),
        "peliculas": [{**p, "entidad": pelis.get(p["qid"], {})} for p in seleccion],
        "refs": {q: todas_refs[q] for q in dict.fromkeys(nombres + con_codigos) if q in todas_refs},
    }
    guardar("2_crudo.json", crudo)
    print(f"\nListo: datos/2_crudo.json con {len(seleccion)} películas. Ahora corre:  python limpiar.py")


if __name__ == "__main__":
    candidatas = paso_candidatas()
    candidatas = paso_visitas(candidatas)
    paso_detalles(candidatas)