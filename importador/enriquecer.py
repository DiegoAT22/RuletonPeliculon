"""
ETAPA 3 — ENRIQUECER CON CLAUDE
Lee datos/3_limpio.json y, para cada película, le pide a Claude:
  - confirmar los géneros (máximo 3) y elegir subgéneros de tu taxonomía
  - poner los tags: formato, audiencia, basado en, época, lugar, temática, tono, escala
  - escribir una sinopsis corta, con sus propias palabras y sin spoilers
Claude solo puede responder con valores de taxonomia.json (lista cerrada).

Genera:  datos/4_enriquecido.json   (listo para la etapa 4)
Caché:   datos/cache_claude.json    (no se le vuelve a pagar a Claude por la misma película)

Uso:  python enriquecer.py
"""
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import anthropic

import config

BASE = Path(__file__).parent
DATOS = BASE / "datos"
TAX = json.loads((BASE / "taxonomia.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------
# Llave de la API: se lee del archivo .env (que nunca se sube a GitHub)
# ---------------------------------------------------------------------
def cargar_env():
    """Regresa True si hay llave de API (en .env o en el sistema)."""
    env = BASE / ".env"
    if env.exists():
        for linea in env.read_text(encoding="utf-8").splitlines():
            if "=" in linea and not linea.strip().startswith("#"):
                k, v = linea.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


# ---------------------------------------------------------------------
# Lo que Claude puede responder: un "formulario" con listas cerradas
# ---------------------------------------------------------------------
SUBGENEROS = [f"{g}: {s}" for g in TAX["orden_generos"] for s in TAX["generos"][g]]


def lista(valores, minimo, maximo, descripcion):
    return {"type": "array", "items": {"type": "string", "enum": valores},
            "minItems": minimo, "maxItems": maximo, "description": descripcion}


T = TAX["tags"]
HERRAMIENTA = {
    "name": "clasificar_pelicula",
    "description": "Registra la clasificación de una película usando solo los valores permitidos.",
    "input_schema": {
        "type": "object",
        "properties": {
            "confianza": {"type": "string", "enum": ["alta", "media", "baja"],
                          "description": "Qué tan bien conoces ESTA película (no una con nombre parecido)."},
            "generos": lista(TAX["orden_generos"], 0, 3,
                             "Los géneros que de verdad la definen, el principal primero. Vacío solo si es un documental."),
            "subgeneros": lista(SUBGENEROS, 0, 3, "Solo si encajan claramente. Su género debe estar en 'generos'."),
            "formato": lista(T["formato"]["valores"], 1, 2, "Formato de producción."),
            "audiencia": lista(T["audiencia"]["valores"], 1, 1, "Público al que va dirigida."),
            "basado_en": lista(T["basado-en"]["valores"], 0, 2, "Original, o en qué se basa."),
            "epoca": lista(T["epoca"]["valores"], 0, 2, "Época en que transcurre la historia."),
            "lugar": lista(T["lugar"]["valores"], 0, 3, "Dónde transcurre, si es característico."),
            "tematica": lista(T["tematica"]["valores"], 0, 4, "Temas centrales, no secundarios."),
            "tono": lista(T["tono"]["valores"], 1, 2, "Tono dominante."),
            "escala": lista(T["escala"]["valores"], 1, 1, "Íntima o épica."),
            "sinopsis": {"type": "string",
                         "description": "1 o 2 oraciones en español de México, con tus propias palabras, sin spoilers. "
                                        "Vacío si la confianza es baja."},
            "nota": {"type": "string", "description": "Opcional: alguna duda para el revisor humano. Vacío si no hay."},
        },
        "required": ["confianza", "generos", "subgeneros", "formato", "audiencia", "basado_en",
                     "epoca", "lugar", "tematica", "tono", "escala", "sinopsis", "nota"],
    },
}

SISTEMA = """Eres un curador de cine que clasifica películas para una app mexicana de recomendaciones.
Recibes los datos de una película (sacados de Wikidata) y la clasificas con la herramienta clasificar_pelicula.

Reglas:
- Usa solo lo que sepas con seguridad sobre ESTA película (revisa título, año y director). Si no la conoces bien, pon confianza "baja", clasifica solo con los datos recibidos y deja la sinopsis vacía.
- Los géneros de Wikidata suelen ser excesivos: quédate con 1 a 3 que de verdad la definan, el principal primero.
- Un subgénero solo puede elegirse si su género está en la lista de géneros.
- Temática y lugar: solo lo central o característico, no cualquier cosa que aparezca.
- Audiencia: "Infantil" (pensada para niños), "Familiar" (todas las edades), "Adolescente" (equivale a una clasificación B o PG-13), "Adultos" (contenido maduro, violencia o sexo explícitos).
- La sinopsis la escribes tú, nunca copiada de otra fuente, en español natural de México, sin revelar giros ni el final.
- Si algo no aplica, deja la lista vacía. Es mejor poco y correcto que mucho y dudoso."""

_candado = threading.Lock()
_uso = {"entrada": 0, "salida": 0, "cache": 0}


def pedir_a_claude(cliente, peli):
    datos = {k: v for k, v in peli.items()
             if k in ("titulo", "titulo_original", "anio", "duracion_min", "idioma_original", "directores",
                      "actores", "paises", "estudios", "generos", "subgeneros", "tags")}
    datos["pistas_de_wikidata"] = peli.get("_pistas", {})
    r = cliente.messages.create(
        model=config.MODELO_CLAUDE,
        max_tokens=1000,
        system=[{"type": "text", "text": SISTEMA, "cache_control": {"type": "ephemeral"}}],
        tools=[HERRAMIENTA],
        tool_choice={"type": "tool", "name": "clasificar_pelicula"},
        messages=[{"role": "user", "content": json.dumps(datos, ensure_ascii=False)}],
    )
    with _candado:
        _uso["entrada"] += r.usage.input_tokens
        _uso["salida"] += r.usage.output_tokens
        _uso["cache"] += getattr(r.usage, "cache_read_input_tokens", 0) or 0
    for bloque in r.content:
        if bloque.type == "tool_use":
            return bloque.input
    raise ValueError("Claude no regresó la clasificación")


def validar(resp):
    """Segunda red de seguridad: descarta cualquier valor fuera de la taxonomía."""
    generos = [g for g in resp.get("generos", []) if g in TAX["generos"]][:3]
    subgeneros = [s for s in resp.get("subgeneros", []) if s in SUBGENEROS and s.split(":")[0] in generos][:3]
    tags = {}
    for campo, dim in [("formato", "formato"), ("audiencia", "audiencia"), ("basado_en", "basado-en"),
                       ("epoca", "epoca"), ("lugar", "lugar"), ("tematica", "tematica"),
                       ("tono", "tono"), ("escala", "escala")]:
        vals = list(dict.fromkeys(v for v in resp.get(campo, []) if v in T[dim]["valores"]))
        if T[dim]["unico"]:
            vals = vals[:1]
        if vals:
            tags[dim] = vals
    return generos, subgeneros, tags


def main():
    hay_llave = cargar_env()
    limpio = json.loads((DATOS / "3_limpio.json").read_text(encoding="utf-8"))
    lote = limpio[:config.LIMITE_ENRIQUECER] if config.LIMITE_ENRIQUECER else limpio
    cache_ruta = DATOS / "cache_claude.json"
    cache = json.loads(cache_ruta.read_text(encoding="utf-8")) if cache_ruta.exists() else {}
    faltan = [p for p in lote if p["wikidata_id"] not in cache]
    print(f"Enriquecer: {len(lote)} películas ({len(lote) - len(faltan)} ya en caché, {len(faltan)} por clasificar)")

    errores = []
    if faltan and not hay_llave:
        # Sin llave de API: solo arma la salida con lo que ya está en la caché
        # (por ejemplo, lo que llenó Claude Code). No llama a la API ni cobra nada.
        print("   Sin ANTHROPIC_API_KEY: no se llama a la API. Se usan solo las ya clasificadas en datos/cache_claude.json.")
    elif faltan:
        print(f"Modelo: {config.MODELO_CLAUDE}")
        cliente = anthropic.Anthropic(max_retries=6)   # reintenta solo si la API está saturada

        def una(p):
            try:
                return p["wikidata_id"], pedir_a_claude(cliente, p), None
            except Exception as e:                       # una película con error no detiene a las demás
                return p["wikidata_id"], None, f"{p['titulo']}: {e}"

        with ThreadPoolExecutor(config.HILOS_CLAUDE) as ex:
            for n, (qid, resp, err) in enumerate(ex.map(una, faltan), 1):
                if err:
                    errores.append(err)
                else:
                    cache[qid] = resp
                if n % 10 == 0 or n == len(faltan):
                    cache_ruta.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
                    print(f"   {n}/{len(faltan)}")

    salida, revisar = [], []
    for p in lote:
        resp = cache.get(p["wikidata_id"])
        if not resp:
            continue
        generos, subgeneros, tags = validar(resp)
        peli = {**p, "generos": generos, "subgeneros": subgeneros, "tags": tags,
                "sinopsis": resp.get("sinopsis") or None}
        peli["_revision"] = {"confianza": resp.get("confianza"), "nota": resp.get("nota") or None}
        if resp.get("confianza") != "alta" or resp.get("nota"):
            revisar.append(f"  [{resp.get('confianza')}] {p['titulo']} ({p['anio']})"
                           + (f" — {resp['nota']}" if resp.get("nota") else ""))
        salida.append(peli)

    (DATOS / "4_enriquecido.json").write_text(json.dumps(salida, ensure_ascii=False, indent=1), encoding="utf-8")

    costo = (_uso["entrada"] * config.PRECIO_ENTRADA + _uso["cache"] * config.PRECIO_ENTRADA * 0.1
             + _uso["salida"] * config.PRECIO_SALIDA) / 1_000_000
    print(f"\nListo: datos/4_enriquecido.json con {len(salida)} películas")
    if _uso["entrada"] or _uso["salida"]:
        print(f"Tokens en esta corrida: {_uso['entrada']:,} entrada + {_uso['cache']:,} de caché + "
              f"{_uso['salida']:,} salida  ≈ ${costo:.2f} USD (estimado)")
    if errores:
        print(f"\n{len(errores)} con error (vuelve a correr el script para reintentarlas):")
        print("\n".join("  " + e for e in errores[:10]))
    if revisar:
        print(f"\nPara revisar con más cuidado ({len(revisar)}):")
        print("\n".join(revisar[:25]))


if __name__ == "__main__":
    main()