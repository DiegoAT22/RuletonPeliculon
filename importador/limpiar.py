"""
ETAPA 2 — LIMPIAR
Lee datos/2_crudo.json (sin internet) y aplica las reglas de limpieza.
Genera:
  datos/3_limpio.json          películas en el formato de insertar_pelicula
  datos/reporte_limpieza.txt   qué falta, qué se excluyó y por qué

Puedes ajustar las reglas y volver a correrlo cuantas veces quieras.
Uso:  python limpiar.py
"""
import datetime as dt
import json
import re
from collections import Counter
from pathlib import Path

import config

DATOS = Path(__file__).parent / "datos"
ANIO_ACTUAL = dt.date.today().year

TIPOS_ANIMADOS = {"Q29168811", "Q202866"}   # largometraje animado, película animada
CORTOMETRAJE = "Q24862"

# Géneros de Wikidata (por su nombre en inglés) → tus 14 géneros.
# Si un género de Wikidata no entra en ninguna regla, sale en el reporte
# para que decidas si agregar una regla aquí.
REGLAS_GENERO = [
    (r"science fiction|sci-fi|cyberpunk|space opera", "Ciencia ficción"),
    (r"horror|slasher|zombie|splatter", "Terror"),
    (r"thriller", "Thriller"),
    (r"mystery|detective|whodunit", "Misterio"),
    (r"crime|gangster|heist|neo-noir|film noir|mafia", "Crimen"),
    (r"western", "Western"),
    (r"\bwar\b", "Bélico"),
    (r"comedy|parody|satir|slapstick", "Comedia"),
    (r"romance|romantic", "Romance"),
    (r"musical", "Musical"),
    (r"fantasy|sword and sorcery|fairy tale", "Fantasía"),
    (r"superhero|martial arts|action", "Acción"),
    (r"adventure|swashbuckler", "Aventura"),
    (r"drama", "Drama"),
]
# Señales de formato (solo las seguras; lo demás lo decide Claude en la etapa 3)
REGLAS_FORMATO = [
    (r"computer-animated|computer animation|cgi", "CGI/3D"),
    (r"stop-motion|stop motion|claymation", "Stop motion"),
    (r"\banime\b", "Anime"),
    (r"traditionally animated|hand-drawn", "Animación 2D tradicional"),
    (r"documentary", "Documental"),
]
# Tipo de obra en que se basa → tu dimensión "basado en"
REGLAS_BASADO_EN = [
    (r"novel|novella|book|literary work", "Novela"),
    (r"comic|manga|graphic novel", "Cómic"),
    (r"video game", "Videojuego"),
    (r"\bplay\b|stage musical|theatrical|opera", "Obra de teatro"),
    (r"\bfilm\b|motion picture", "Remake"),
]
# Géneros de Wikidata que en tu taxonomía son subgéneros o tags (no géneros).
# Se aplican además de REGLAS_GENERO. Un subgénero agrega su género automáticamente.
REGLAS_EXTRA = [
    (r"biograph",              {"tags": {"basado-en": ["Biografía"]}}),
    (r"\bteen\b|coming-of-age", {"tags": {"tematica": ["Crecer"]}}),
    (r"suspense",              {"generos": ["Thriller"]}),
    (r"children",              {"tags": {"audiencia": ["Infantil"]}}),
    (r"\bfamily film",         {"tags": {"audiencia": ["Familiar"]}}),
    (r"\bepic\b",              {"tags": {"escala": ["Épica"]}}),
    (r"dystopia",              {"subgeneros": ["Ciencia ficción: Distopía"]}),
    (r"lgbt",                  {"tags": {"tematica": ["LGBT"]}}),
    (r"trial film|courtroom|legal drama", {"tags": {"tematica": ["Legal"]}}),
    (r"buddy cop",             {"subgeneros": ["Acción: Acción policial"]}),
    (r"buddy",                 {"tags": {"tematica": ["Amistad"]}}),
    (r"post-apocalyptic",      {"tags": {"lugar": ["Mundo postapocalíptico"]}}),
    (r"ghost",                 {"subgeneros": ["Terror: Sobrenatural"]}),
    (r"\bspy\b|espionage",     {"tags": {"tematica": ["Espionaje"]}}),
    (r"sword-and-sandal",      {"tags": {"epoca": ["Antigüedad"]}}),
    (r"werewolf|vampire",      {"subgeneros": ["Terror: Criaturas y monstruos"]}),
    (r"police procedural",     {"subgeneros": ["Crimen: Procedimental policial"]}),
    (r"time-travel|time travel", {"subgeneros": ["Ciencia ficción: Viajes en el tiempo"]}),
    (r"vigilante",             {"subgeneros": ["Acción: Vigilantes"]}),
]
# Géneros de Wikidata que no se traducen solos, pero Claude los ve como pista
# (en _pistas) para decidir en la etapa 3. Ya no salen en el reporte.
SOLO_PISTA = r"historical|independent|monster|disaster|flashback|speculative|christmas|magic realis|prison|silent|anthology|ensemble|road movie|cult"

# Países históricos sin código ISO propio → el más cercano para filtrar
PAISES_HISTORICOS = {"Países Bajos": "NL", "Reino de los Países Bajos": "NL", "Alemania Occidental": "DE",
                     "Alemania Oriental": "DE", "Unión Soviética": "SU", "Checoslovaquia": "CZ", "Yugoslavia": "YU"}
DIMENSIONES_UNICAS = {"audiencia", "escala"}

IDIOMAS_LATINOS = {"en", "es", "fr", "it", "pt", "de", "nl", "sv", "da", "no", "pl", "cs", "ro", "ca", "tr", "fi"}

# Premios que cuentan como rasgo (por su nombre en inglés en Wikidata)
PREMIO_OSCAR = r"academy award"
PREMIO_FESTIVAL = r"palme d'or|palme d’or|golden lion|golden bear"
MAX_SAGAS = 2

# Calificación de la crítica. Cada fuente califica distinto (en Rotten Tomatoes casi todo lo famoso
# pasa de 80%; en Metacritic un 75 ya es muy bueno), así que antes de promediar se pone cada fuente
# en la misma escala: qué tan arriba o abajo queda la película frente a las demás del catálogo.
CAL_MEDIA, CAL_DESV = 6.5, 1.5     # la película promedio queda en 6.5; "aclamada" (8 o más) es más o menos 1 de cada 6
MIN_PARA_CALIBRAR = 30             # con menos películas en una fuente no se puede comparar: se usa su número tal cual
NOMBRE_FUENTE = {"rotten": "Rotten Tomatoes (% de críticas positivas)", "rotten_promedio": "Rotten Tomatoes (promedio)",
                 "metacritic": "Metacritic", "imdb": "IMDb"}


def leer_calificacion(texto, quien, metodo):
    """Convierte una calificación de Wikidata a escala 0–10.
    Regresa (fuente, valor) o (None, None) si no es de una fuente conocida o no se entiende."""
    texto = texto.strip().replace(",", ".")
    del_publico = "audience" in metodo or "user" in metodo      # Rotten y Metacritic también publican la del público
    if "rotten tomatoes" in quien and not del_publico:
        m = re.fullmatch(r"(\d{1,3})\s*%", texto)
        if m and int(m.group(1)) <= 100:
            return "rotten", int(m.group(1)) / 10
        m = re.fullmatch(r"(\d{1,2}(?:\.\d+)?)\s*/\s*10", texto)
        if m and float(m.group(1)) <= 10:
            return "rotten_promedio", float(m.group(1))
    elif "metacritic" in quien and not del_publico:
        m = re.fullmatch(r"(\d{1,3})(?:\s*/\s*100)?", texto)
        if m and int(m.group(1)) <= 100:
            return "metacritic", int(m.group(1)) / 10
    elif "imdb" in quien or "internet movie database" in quien:
        m = re.fullmatch(r"(\d{1,2}(?:\.\d+)?)(?:\s*/\s*10)?", texto)
        if m and float(m.group(1)) <= 10:
            return "imdb", float(m.group(1))
    return None, None


def calibrar_calificaciones(limpio):
    """Llena r["calificacion"] (0–10) a partir de r["_cal"] = {fuente: valor 0–10}. Regresa las estadísticas por fuente."""
    stats = {}
    for fuente in NOMBRE_FUENTE:
        vals = [r["_cal"][fuente] for r in limpio if fuente in r["_cal"]]
        if not vals:
            continue
        media = sum(vals) / len(vals)
        desv = (sum((v - media) ** 2 for v in vals) / len(vals)) ** 0.5
        stats[fuente] = {"n": len(vals), "media": media, "desv": desv,
                         "calibrada": len(vals) >= MIN_PARA_CALIBRAR and desv > 0.05}
    for r in limpio:
        cal = r.pop("_cal")
        if not cal:
            r["calificacion"] = None
            continue
        z = [(v - stats[f]["media"]) / stats[f]["desv"] for f, v in cal.items() if stats[f]["calibrada"]]
        valor = CAL_MEDIA + CAL_DESV * sum(z) / len(z) if z else sum(cal.values()) / len(cal)
        r["calificacion"] = round(min(max(valor, 0.0), 10.0), 1)
    return stats


def main():
    crudo = json.loads((DATOS / "2_crudo.json").read_text(encoding="utf-8"))
    refs = crudo["refs"]

    def etiqueta(qid, orden=("es", "mul", "en")):
        l = refs.get(qid, {}).get("l", {})
        for idioma in orden:
            if l.get(idioma):
                return l[idioma]
        return None

    def en(qid):
        return (etiqueta(qid, ("en", "mul", "es")) or "").lower()

    def claims(ent, p):
        return ent.get("c", {}).get(p, [])

    def items(ent, p):
        return [c["v"] for c in claims(ent, p) if isinstance(c["v"], str)]

    def unicos(xs, limite=None):
        salida = list(dict.fromkeys(x for x in xs if x))
        return salida[:limite] if limite else salida

    def aplicar(reglas, textos):
        return unicos(destino for t in textos for patron, destino in reglas if re.search(patron, t))

    limpio, excluidas = [], Counter()
    faltantes = Counter()
    generos_sin_regla = Counter()
    paises_sin_codigo = Counter()
    calificaciones_vistas = Counter()      # (quién califica, método, cómo se tomó) → para revisar que se lean bien

    for p in crudo["peliculas"]:
        ent = p["entidad"]
        if not ent:
            excluidas["no existe en Wikidata"] += 1
            continue
        tipos = set(items(ent, "P31"))

        # --- Año: el estreno más antiguo con precisión de año o mejor
        fechas = []
        for c in claims(ent, "P577"):
            t, prec = c["v"]["t"], c["v"]["p"]
            if not t.startswith("+") or prec < 9:
                continue
            mes = int(t[6:8]) or 1 if prec >= 10 else 1
            dia = int(t[9:11]) or 1 if prec >= 11 else 1
            fechas.append(dt.date(int(t[1:5]), mes, dia))
        if not fechas:
            excluidas["sin año"] += 1
            continue
        estreno = min(fechas)
        anio = estreno.year
        if estreno > dt.date.today():
            excluidas["aún no se estrena"] += 1
            continue

        # --- Duración: la versión más corta dentro de un rango razonable (= versión de cine)
        duraciones = []
        for c in claims(ent, "P2047"):
            a, u = c["v"]["a"], c["v"]["u"]
            minutos = a / 60 if u == "Q11574" else a * 60 if u == "Q25235" else a
            duraciones.append(minutos)
        validas = [d for d in duraciones if config.DURACION_MIN <= d <= config.DURACION_MAX]
        if CORTOMETRAJE in tipos or (duraciones and not validas and max(duraciones) < config.DURACION_MIN):
            excluidas["cortometraje"] += 1
            continue
        duracion = round(min(validas)) if validas else None

        # --- Títulos
        l = ent.get("l", {})
        titulo = l.get("es") or l.get("mul") or l.get("en")
        if not titulo:
            excluidas["sin título"] += 1
            continue
        original = None
        for c in claims(ent, "P1476"):
            if c["v"]["lang"] in IDIOMAS_LATINOS:
                original = c["v"]["text"]
                break
        en_label = l.get("en") or ""
        if original and en_label.lower().startswith(original.lower()) and len(en_label) > len(original):
            original = en_label        # Wikidata a veces guarda el subtítulo aparte ("Spider-Man" + "Across the Spider-Verse")
        original = original or l.get("en") or l.get("mul") or titulo

        # --- Personas y productoras
        directores = unicos([etiqueta(q) for q in items(ent, "P57")], config.MAX_DIRECTORES)
        actores, vistos = [], set()
        for c in claims(ent, "P161"):
            if not isinstance(c["v"], str) or c["v"] in vistos:
                continue
            nombre = etiqueta(c["v"])
            if not nombre:
                continue
            vistos.add(c["v"])
            q = c.get("q", {})
            personaje = (q.get("P4633") or [None])[0]
            if not personaje and q.get("P453"):
                personaje = etiqueta(q["P453"][0])
            actores.append({"nombre": nombre, "personaje": personaje} if personaje else nombre)
            if len(actores) >= config.MAX_ACTORES:
                break
        estudios = unicos([etiqueta(q) for q in items(ent, "P272")], config.MAX_ESTUDIOS)

        # --- País (código ISO) e idioma original (código ISO 639-1)
        paises = []
        for q in items(ent, "P495"):
            codigos = [c["v"] for c in refs.get(q, {}).get("c", {}).get("P297", [])]
            if codigos:
                paises.append(codigos[0].upper())
            elif PAISES_HISTORICOS.get(etiqueta(q) or ""):
                paises.append(PAISES_HISTORICOS[etiqueta(q)])
            else:
                paises_sin_codigo[etiqueta(q) or q] += 1
        paises = unicos(paises, 3)
        idioma = None
        for q in items(ent, "P364"):
            codigos = [c["v"] for c in refs.get(q, {}).get("c", {}).get("P218", [])]
            if codigos:
                idioma = codigos[0].lower()
                break

        # --- Géneros, formato y "basado en"
        generos_wd = [en(q) for q in items(ent, "P136")]
        if p["qid"] in config.EXCLUIR or any("pornograph" in g for g in generos_wd):
            excluidas["excluida (porno o lista manual)"] += 1
            continue
        generos = aplicar(REGLAS_GENERO, generos_wd)
        subgeneros, extra_tags = [], {}
        for g in generos_wd:
            for patron, efecto in REGLAS_EXTRA:
                if g and re.search(patron, g):
                    generos += efecto.get("generos", [])
                    subgeneros += efecto.get("subgeneros", [])
                    for dim, vals in efecto.get("tags", {}).items():
                        extra_tags.setdefault(dim, []).extend(vals)
        generos += [s.split(":")[0].strip() for s in subgeneros]   # el subgénero exige su género
        generos, subgeneros = unicos(generos), unicos(subgeneros)
        for g in generos_wd:
            if g and not any(re.search(pat, g) for pat, _ in REGLAS_GENERO + REGLAS_FORMATO + REGLAS_EXTRA) \
                    and not re.search(SOLO_PISTA, g):
                generos_sin_regla[g] += 1

        formato = aplicar(REGLAS_FORMATO, generos_wd)
        es_animada = bool(tipos & TIPOS_ANIMADOS) or any("animat" in g for g in generos_wd)

        fuentes = []
        for q in items(ent, "P144"):
            tipos_obra = [en(t) for t in items(refs.get(q, {}), "P31")]
            fuentes.append({"obra": etiqueta(q), "tipos": tipos_obra})
        basado_en = aplicar(REGLAS_BASADO_EN, [t for f in fuentes for t in f["tipos"]])[:1]

        tags = {}
        if formato:
            tags["formato"] = formato
        if basado_en:
            tags["basado-en"] = basado_en
        for dim, vals in extra_tags.items():
            tags[dim] = unicos(tags.get(dim, []) + vals)
        for dim in DIMENSIONES_UNICAS & tags.keys():
            tags[dim] = tags[dim][:1]                      # audiencia y escala: solo un valor

        # --- Saga o franquicia (candidatas; al final se eligen las que más se repiten en el catálogo)
        sagas_cand = unicos(items(ent, "P8345") + items(ent, "P179"))

        # --- Calificación de la crítica: promedio de las fuentes conocidas, en escala 0–10
        fuentes_cal = {}
        for c in claims(ent, "P444"):
            if not isinstance(c["v"], str):
                continue
            q = c.get("q", {})
            quien = " ".join(en(x) for x in q.get("P447", []) if isinstance(x, str))
            metodo = " ".join(en(x) for x in q.get("P459", []) if isinstance(x, str))
            fuente, val = leer_calificacion(c["v"], quien, metodo)
            calificaciones_vistas[(quien or "(sin fuente)", metodo or "-", fuente or "NO SE USA")] += 1
            if fuente and (fuente not in fuentes_cal or c.get("r", 0) >= fuentes_cal[fuente][0]):
                fuentes_cal[fuente] = (c.get("r", 0), val)       # gana el dato marcado como vigente; si no, el último
        if "rotten" in fuentes_cal:
            fuentes_cal.pop("rotten_promedio", None)             # con el porcentaje basta

        # --- Premios
        ganados = [en(x) for x in items(ent, "P166")]
        nominada = [en(x) for x in items(ent, "P1411")]
        oscars = sum(1 for t in ganados if re.search(PREMIO_OSCAR, t))
        oscar_nominaciones = max(oscars, sum(1 for t in nominada if re.search(PREMIO_OSCAR, t)))
        premio_festival = any(re.search(PREMIO_FESTIVAL, t) for t in ganados)

        # --- IDs externos
        tmdb = next((c["v"] for c in claims(ent, "P4947")), None)
        imdb = next((c["v"] for c in claims(ent, "P345")), None)

        registro = {
            "titulo": titulo,
            "titulo_original": original,
            "anio": anio,
            "duracion_min": duracion,
            "idioma_original": idioma,
            "generos": generos,
            "subgeneros": subgeneros,
            "tags": tags,
            "directores": directores,
            "actores": actores,
            "paises": paises,
            "estudios": estudios,
            "plataformas": [],
            "wikidata_id": p["qid"],
            "tmdb_id": int(tmdb) if tmdb and str(tmdb).isdigit() else None,
            "imdb_id": imdb,
            "popularidad": p["vistas_12m"],
            # Rasgos extra para el modelo
            "sagas": [],                               # se llena al final
            "calificacion": None,                      # crítica, 0–10; se calcula al final (None si Wikidata no la tiene)
            "oscars": oscars,
            "oscar_nominaciones": oscar_nominaciones,
            "premio_festival": premio_festival,
            # Contexto para Claude en la etapa 3 (no se guarda en la base)
            "_pistas": {
                "generos_wikidata": unicos(generos_wd),
                "animada": es_animada,
                "basado_en": fuentes,
                "sitelinks": p["sitelinks"],
                "temas": unicos([etiqueta(x) for x in items(ent, "P921")], 6),
                "lugares": unicos([etiqueta(x) for x in items(ent, "P840")], 5),
                "epoca": unicos([etiqueta(x) for x in items(ent, "P2408")], 3),
            },
            "_sagas_cand": sagas_cand,
            "_cal": {f: v for f, (_, v) in fuentes_cal.items()},
        }
        for campo in ("duracion_min", "idioma_original", "directores", "actores", "paises", "estudios", "generos"):
            if not registro[campo]:
                faltantes[campo] += 1
        limpio.append(registro)

    # --- Calificación de la crítica: todas las fuentes a la misma escala y luego el promedio
    stats_cal = calibrar_calificaciones(limpio)

    # --- Sagas: de las candidatas de cada película se quedan las que más se repiten en el catálogo
    #     (así "Universo Marvel" le gana a "trilogía de Iron Man"); si empatan, la franquicia va primero.
    veces_saga = Counter(q for r in limpio for q in r["_sagas_cand"])
    for r in limpio:
        orden = sorted(r.pop("_sagas_cand"), key=lambda q: -veces_saga[q])     # sorted es estable: respeta el empate
        elegidas = []
        for q in orden:
            nombre = etiqueta(q)
            if not nombre or re.match(r"^(list of|anexo:|lista de)", nombre.lower()):
                continue
            clave = re.sub(r"[^a-z0-9]+", " ", nombre.lower()).strip()
            if any(clave in c or c in clave for c, _ in elegidas):              # "El padrino" y "trilogía de El padrino"
                continue
            elegidas.append((clave, {"nombre": nombre, "wikidata_id": q}))
            if len(elegidas) >= MAX_SAGAS:
                break
        r["sagas"] = [s for _, s in elegidas]
        if r["sagas"]:
            r["_pistas"]["saga"] = [s["nombre"] for s in r["sagas"]]

    limpio.sort(key=lambda r: r["popularidad"], reverse=True)
    (DATOS / "3_limpio.json").write_text(json.dumps(limpio, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---------------- Reporte ----------------
    total = len(crudo["peliculas"])
    lineas = [
        f"REPORTE DE LIMPIEZA — {dt.datetime.now():%Y-%m-%d %H:%M}",
        f"Películas leídas: {total}    Limpias: {len(limpio)}    Excluidas: {total - len(limpio)}",
        "",
        "Excluidas por motivo:",
        *([f"  {motivo}: {n}" for motivo, n in excluidas.most_common()] or ["  ninguna"]),
        "",
        "Películas limpias a las que les falta algo (Claude o tú lo pueden completar):",
        *[f"  sin {campo}: {n} ({n * 100 // max(len(limpio), 1)}%)" for campo, n in faltantes.most_common()],
        "",
        "Rasgos extra para el modelo (cuántas películas los traen desde Wikidata):",
        *[f"  {nombre}: {n} ({n * 100 // max(len(limpio), 1)}%)" for nombre, n in [
            ("con calificación de la crítica", sum(1 for r in limpio if r["calificacion"] is not None)),
            ("con saga o franquicia", sum(1 for r in limpio if r["sagas"])),
            ("  de esas, con otra película de la misma saga en el catálogo",
             sum(1 for r in limpio if any(veces_saga[s["wikidata_id"]] >= 2 for s in r["sagas"]))),
            ("ganadoras de algún Óscar", sum(1 for r in limpio if r["oscars"])),
            ("nominadas al Óscar", sum(1 for r in limpio if r["oscar_nominaciones"])),
            ("premiadas en Cannes, Venecia o Berlín", sum(1 for r in limpio if r["premio_festival"])),
            ("con pistas de tema / lugar / época",
             sum(1 for r in limpio if r["_pistas"]["temas"] or r["_pistas"]["lugares"] or r["_pistas"]["epoca"])),
        ]],
        "  (si alguno sale en 0% o muy bajo, avísale a Claude: hay que ajustar cómo se lee de Wikidata)",
        "",
        "Calificación de la crítica, por fuente:",
        *([f"  {NOMBRE_FUENTE[f]}: {e['n']} películas, promedio {e['media']:.1f} de 10"
           + ("" if e["calibrada"] else "  (muy pocas: se usa su número tal cual)") for f, e in stats_cal.items()] or ["  ninguna"]),
        "  Cómo quedaron repartidas: " + ", ".join(f"{nombre} {n}" for nombre, n in [
            ("aclamadas (8+)", sum(1 for r in limpio if (r["calificacion"] or 0) >= 8)),
            ("bien recibidas (6.5–8)", sum(1 for r in limpio if 6.5 <= (r["calificacion"] or 0) < 8)),
            ("divididas (5–6.5)", sum(1 for r in limpio if 5 <= (r["calificacion"] or 0) < 6.5)),
            ("mal recibidas (<5)", sum(1 for r in limpio if r["calificacion"] is not None and r["calificacion"] < 5)),
            ("sin dato", sum(1 for r in limpio if r["calificacion"] is None))]),
        "  Calificaciones encontradas en Wikidata (quién | método | cómo se tomó | cuántas):",
        *[f"    {quien} | {metodo} | {uso} | {n}" for (quien, metodo, uso), n in calificaciones_vistas.most_common(15)],
        "",
        "Géneros de Wikidata SIN regla (considera agregarlos a REGLAS_GENERO):",
        *([f"  {n:>4}  {g}" for g, n in generos_sin_regla.most_common(30)] or ["  ninguno"]),
        "",
        "Países sin código ISO (países históricos, se omiten):",
        *([f"  {n:>4}  {pais}" for pais, n in paises_sin_codigo.most_common(15)] or ["  ninguno"]),
        "",
        "Las 25 más vistas (revisa que tengan sentido):",
        *[f"  {r['popularidad']:>9,}  {r['titulo']} ({r['anio']}) — {', '.join(r['generos']) or 'sin género'}"
          for r in limpio[:25]],
    ]
    (DATOS / "reporte_limpieza.txt").write_text("\n".join(lineas) + "\n", encoding="utf-8")
    ini = lineas.index("Rasgos extra para el modelo (cuántas películas los traen desde Wikidata):")
    print("\n".join(lineas[:min(12, ini - 1)]))
    fin = lineas.index("Géneros de Wikidata SIN regla (considera agregarlos a REGLAS_GENERO):")
    print("\n".join(lineas[ini - 1:fin - 1]))
    print("\nListo: datos/3_limpio.json y datos/reporte_limpieza.txt")


if __name__ == "__main__":
    main()