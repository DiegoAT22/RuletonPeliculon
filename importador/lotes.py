"""
ETAPA 3 CON CLAUDE CODE — REPARTIR, REVISAR Y JUNTAR
Para clasificar películas con Claude Code (sin llave de API). El trabajo va en archivos chicos:

  python lotes.py             reparte las películas que faltan en datos/lotes/pendiente_NNN.json
  (Claude Code lee cada pendiente_NNN.json y escribe respuesta_NNN.json; ver INSTRUCCIONES_CLAUDE_CODE.md)
  python lotes.py --juntar    revisa cada respuesta contra taxonomia.json y guarda las correctas en
                              datos/cache_claude.json; las que traen errores se quedan pendientes
  python lotes.py --estado    cuántas faltan
  python lotes.py --ejemplos  muestra 3 películas ya clasificadas (para copiar el estilo)

Cuando ya no falte ninguna:  python enriquecer.py   y luego   python cargar.py
"""
import json
import sys
from collections import Counter
from pathlib import Path

import config

BASE = Path(__file__).parent
DATOS = BASE / "datos"
LOTES = DATOS / "lotes"
HECHOS = LOTES / "hechos"
TAX = json.loads((BASE / "taxonomia.json").read_text(encoding="utf-8"))
T = TAX["tags"]
SUBGENEROS = [f"{g}: {s}" for g in TAX["orden_generos"] for s in TAX["generos"][g]]

# campo de la respuesta → (valores permitidos, mínimo, máximo)   — igual que el formulario de enriquecer.py
LISTAS = {
    "generos":    (TAX["orden_generos"], 0, 3),
    "subgeneros": (SUBGENEROS, 0, 3),
    "formato":    (T["formato"]["valores"], 1, 2),
    "audiencia":  (T["audiencia"]["valores"], 1, 1),
    "basado_en":  (T["basado-en"]["valores"], 0, 2),
    "epoca":      (T["epoca"]["valores"], 0, 2),
    "lugar":      (T["lugar"]["valores"], 0, 3),
    "tematica":   (T["tematica"]["valores"], 0, 4),
    "tono":       (T["tono"]["valores"], 1, 2),
    "escala":     (T["escala"]["valores"], 1, 1),
}
SINOPSIS_MAX = 400


def leer(ruta, defecto=None):
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else defecto


def escribir(ruta, obj):
    """Escribe a un archivo temporal y luego lo cambia de nombre: si algo falla a media escritura, el original queda intacto."""
    tmp = ruta.with_name(ruta.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(ruta)


def cache():
    return leer(DATOS / "cache_claude.json", {})


def pendientes():
    limpio = leer(DATOS / "3_limpio.json")
    if limpio is None:
        raise SystemExit("Falta datos/3_limpio.json. Corre primero:  python extraer.py  y  python limpiar.py")
    lote = limpio[:config.LIMITE_ENRIQUECER] if config.LIMITE_ENRIQUECER else limpio
    hechas = cache()
    return [p for p in lote if p["wikidata_id"] not in hechas], len(lote)


def resumen(p):
    """Lo que Claude Code necesita ver de una película (sin lo que no ayuda a clasificar)."""
    return {
        "id": p["wikidata_id"],
        "titulo": p["titulo"],
        "titulo_original": p["titulo_original"],
        "anio": p["anio"],
        "duracion_min": p["duracion_min"],
        "idioma_original": p["idioma_original"],
        "paises": p["paises"],
        "directores": p["directores"],
        "actores": [a["nombre"] if isinstance(a, dict) else a for a in p["actores"][:5]],
        "sugerido_por_reglas": {"generos": p["generos"], "subgeneros": p["subgeneros"], "tags": p["tags"]},
        "pistas_de_wikidata": p.get("_pistas", {}),
    }


def revisar(r):
    """Regresa la lista de errores de una respuesta (vacía si está bien)."""
    if not isinstance(r, dict):
        return ["la respuesta no es un objeto"]
    errores = []
    if r.get("confianza") not in ("alta", "media", "baja"):
        errores.append('confianza debe ser "alta", "media" o "baja"')
    for campo, (permitidos, minimo, maximo) in LISTAS.items():
        v = r.get(campo)
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            errores.append(f"{campo}: debe ser una lista de textos")
            continue
        malos = [x for x in v if x not in permitidos]
        if malos:
            errores.append(f"{campo}: no existe en taxonomia.json → {malos}")
        if len(set(v)) != len(v):
            errores.append(f"{campo}: valores repetidos")
        if not minimo <= len(v) <= maximo:
            errores.append(f"{campo}: lleva {len(v)} valores y deben ser de {minimo} a {maximo}")
    def lista(campo):
        return r[campo] if isinstance(r.get(campo), list) else []

    if isinstance(r.get("generos"), list):
        for s in lista("subgeneros"):
            if isinstance(s, str) and s.split(":")[0] not in r["generos"]:
                errores.append(f'subgeneros: "{s}" necesita su género en "generos"')
        if not r["generos"] and "Documental" not in lista("formato"):
            errores.append("generos: solo puede ir vacío si el formato es Documental")
    for campo in ("sinopsis", "nota"):
        if not isinstance(r.get(campo), str):
            errores.append(f"{campo}: debe ser texto (vacío si no aplica)")
    if isinstance(r.get("sinopsis"), str):
        if len(r["sinopsis"]) > SINOPSIS_MAX:
            errores.append(f"sinopsis: {len(r['sinopsis'])} caracteres; el máximo es {SINOPSIS_MAX} (1 o 2 oraciones)")
        if not r["sinopsis"].strip() and r.get("confianza") in ("alta", "media"):
            errores.append("sinopsis: vacía; solo puede ir vacía con confianza baja")
    return errores


def repartir():
    faltan, total = pendientes()
    LOTES.mkdir(parents=True, exist_ok=True)
    for viejo in LOTES.glob("pendiente_*.json"):
        viejo.unlink()                       # se vuelven a armar con lo que falte hoy
    n = config.TAMANO_LOTE
    # La numeración sigue después de las respuestas que ya existen, para no encimar archivos
    usados = [int(r.stem.split("_")[1]) for carpeta in (LOTES, HECHOS) if carpeta.exists()
              for r in carpeta.glob("respuesta_*.json") if r.stem.split("_")[1].isdigit()]
    numero, archivos = max(usados, default=0), 0
    for i in range(0, len(faltan), n):
        numero, archivos = numero + 1, archivos + 1
        escribir(LOTES / f"pendiente_{numero:03d}.json", {
            "que_hacer": "Clasifica cada película siguiendo importador/INSTRUCCIONES_CLAUDE_CODE.md "
                         f"y escribe datos/lotes/respuesta_{numero:03d}.json",
            "peliculas": [resumen(p) for p in faltan[i:i + n]],
        })
    print(f"Películas en el lote: {total}   ya clasificadas: {total - len(faltan)}   faltan: {len(faltan)}")
    if archivos:
        print(f"Quedaron {archivos} archivos en {LOTES} (de hasta {n} películas cada uno).")
        print("Ahora pídele a Claude Code que los clasifique (el texto para pegarle está en INSTRUCCIONES_CLAUDE_CODE.md).")
    else:
        print("No falta ninguna. Sigue con:  python enriquecer.py")


def juntar():
    faltan, _ = pendientes()
    validos = {p["wikidata_id"]: p for p in faltan}
    respuestas = sorted(LOTES.glob("respuesta_*.json")) if LOTES.exists() else []
    if not respuestas:
        raise SystemExit(f"No hay archivos respuesta_NNN.json en {LOTES}.")
    hechas = cache()
    guardadas, con_error, nuevas, completos = 0, [], {}, []
    for ruta in respuestas:
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8-sig"))
        except (ValueError, UnicodeDecodeError, OSError) as e:
            con_error.append(f"{ruta.name}: no se pudo leer como JSON ({e})")
            continue
        if not isinstance(datos, dict):
            con_error.append(f"{ruta.name}: debe ser un objeto {{\"Q123\": {{…}}, …}}")
            continue
        limpio_del_archivo = True
        for qid, r in datos.items():
            if qid in hechas:
                continue                                    # ya estaba guardada de una corrida anterior
            if qid not in validos:
                con_error.append(f"{ruta.name} · {qid}: ese ID no está entre las películas pendientes")
                limpio_del_archivo = False
                continue
            try:
                errores = revisar(r)
            except Exception as e:                              # una respuesta rara no debe tumbar a las demás
                errores = [f"no se pudo revisar ({type(e).__name__}: {e})"]
            if errores:
                limpio_del_archivo = False
                titulo = validos[qid]["titulo"]
                con_error += [f"{ruta.name} · {qid} ({titulo}): {e}" for e in errores]
            else:
                nuevas[qid] = {k: r[k] for k in ("confianza", *LISTAS, "sinopsis", "nota")}
                guardadas += 1
        if limpio_del_archivo:
            completos.append(ruta)
    if nuevas:                                              # primero se guarda; solo después se archivan las respuestas
        hechas.update(nuevas)
        escribir(DATOS / "cache_claude.json", hechas)
    for ruta in completos:
        try:
            HECHOS.mkdir(parents=True, exist_ok=True)
            ruta.replace(HECHOS / ruta.name)
        except OSError as e:                                # archivo abierto en otro programa: no pasa nada, ya se guardó
            print(f"   (no se pudo archivar {ruta.name}: {e})")

    print(f"Guardadas en datos/cache_claude.json: {guardadas}")
    if nuevas:
        print("\nCómo quedaron (para detectar si algo se está repitiendo de más):")
        print("  confianza:", dict(Counter(r["confianza"] for r in nuevas.values())))
        for campo in ("generos", "tono", "audiencia", "escala"):
            top = Counter(x for r in nuevas.values() for x in r[campo]).most_common(6)
            print(f"  {campo}: " + ", ".join(f"{v} {n}" for v, n in top))
        notas = [(validos[q]["titulo"], r["nota"]) for q, r in nuevas.items() if r["nota"].strip()]
        if notas:
            print(f"\nCon nota para ti ({len(notas)}):")
            for titulo, nota in notas[:15]:
                print(f"  {titulo}: {nota}")
    if con_error:
        (LOTES / "errores.txt").write_text("\n".join(con_error) + "\n", encoding="utf-8")
        print(f"\n{len(con_error)} errores (también en datos/lotes/errores.txt). Corrige esos archivos respuesta_NNN.json "
              "y vuelve a correr  python lotes.py --juntar :")
        print("\n".join("  " + e for e in con_error[:30]))
    elif (LOTES / "errores.txt").exists():
        (LOTES / "errores.txt").unlink()
    repartir_silencioso()


def repartir_silencioso():
    faltan, total = pendientes()
    hay = {p["id"] for ruta in LOTES.glob("pendiente_*.json") for p in leer(ruta, {}).get("peliculas", [])}
    quedan = {p["wikidata_id"] for p in faltan}
    for ruta in LOTES.glob("pendiente_*.json"):             # borra los pendientes que ya quedaron completos
        if not any(p["id"] in quedan for p in leer(ruta, {}).get("peliculas", [])):
            ruta.unlink()
    print(f"\nFaltan {len(faltan)} de {total}."
          + ("  Listo: sigue con  python enriquecer.py" if not faltan else
             "" if hay & quedan else "  Corre  python lotes.py  para armar los lotes que faltan."))


def estado():
    faltan, total = pendientes()
    archivos = len(list(LOTES.glob("pendiente_*.json"))) if LOTES.exists() else 0
    print(f"Películas en el lote: {total}   ya clasificadas: {total - len(faltan)}   faltan: {len(faltan)}"
          f"   archivos pendientes: {archivos}")


def ejemplos():
    hechas = cache()
    limpio = {p["wikidata_id"]: p for p in leer(DATOS / "3_limpio.json", [])}
    buenas = [(q, r) for q, r in hechas.items() if r.get("confianza") == "alta" and r.get("sinopsis") and q in limpio]
    if not buenas:
        print("Todavía no hay películas clasificadas.")
        return
    paso = max(len(buenas) // 3, 1)
    for q, r in buenas[::paso][:3]:
        print(json.dumps({"pelicula": resumen(limpio[q]), "respuesta": {q: r}}, ensure_ascii=False, indent=1))
        print()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    {"": repartir, "--juntar": juntar, "--estado": estado, "--ejemplos": ejemplos}.get(arg, lambda: print(__doc__))()
