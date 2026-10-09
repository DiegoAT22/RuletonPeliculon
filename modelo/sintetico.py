"""
DATOS INVENTADOS PARA PROBAR EL ENTRENAMIENTO (opcional)
Crea en modelo/datos_demo/ un catálogo y unas personas de mentira con gustos
"escondidos" que sí se pueden aprender. Sirve para dos cosas:
  - ver el entrenamiento funcionar antes de tener suficientes datos reales
  - comprobar que el código aprende cuando SÍ hay señal: aquí los modelos deben quedar
    claramente arriba de 0.50 de AUC por persona. Si con tus datos reales no pasa lo
    mismo, no es el código: faltan datos.

Uso:
  python sintetico.py                 40 personas
  python sintetico.py 8               8 personas (parecido a lo que hay hoy)
  python entrenar.py --demo
"""
import csv
import sys
from pathlib import Path

import numpy as np

BASE = Path(__file__).parent
DEMO = BASE / "datos_demo"
FUERZA_NUEVOS = 1.0     # 1 = los rasgos nuevos sí influyen en los gustos de mentira; 0 = no influyen nada


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    n_personas = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    rng = np.random.default_rng(7)
    n_titulos = 600

    grupos = {"genero": (14, 1.0), "subgenero": (45, 1.3), "tono": (8, 0.8), "tematica": (22, 0.8),
              "epoca": (8, 0.5), "lugar": (12, 0.5), "formato": (6, 0.6), "director": (160, 1.1),
              "actor": (500, 0.8), "decada": (8, 0.4)}
    # Rasgos nuevos (17_mas_rasgos.sql): la app todavía no los usa
    NUEVOS = {"pais": (12, 1.0), "idioma": (6, 1.0), "estudio": (40, 1.0), "saga": (30, 1.0),
              "critica": (4, 1.0), "premios": (3, 1.0), "duracion": (3, 1.0)}
    grupos.update(NUEVOS)
    claves, peso_de = [], {}
    for g, (n, peso) in grupos.items():
        for i in range(n):
            claves.append((f"{g[:3]}{i}", g, f"{g} {i}", "true" if g in NUEVOS else "false"))
            peso_de[f"{g[:3]}{i}"] = peso
    por_grupo = {g: [c for c, gg, _, _ in claves if gg == g] for g in grupos}

    titulos, rasgos = [], []
    for t in range(1, n_titulos + 1):
        cal = round(float(np.clip(rng.normal(6.8, 1.3), 1, 10)), 1) if rng.random() < 0.85 else ""
        dur = int(np.clip(rng.normal(112, 22), 70, 210))
        titulos.append((t, f"Película {t}", int(rng.integers(1950, 2025)), round(float(rng.gamma(2.0, 20.0)), 1), cal, dur))
        elegidos = {}
        gen = rng.choice(por_grupo["genero"], size=int(rng.integers(1, 3)), replace=False)
        elegidos[gen[0]] = 1.5
        for c in gen[1:]:
            elegidos[c] = 1.0
        for g, cuantos in (("subgenero", rng.integers(0, 3)), ("tono", rng.integers(1, 3)), ("tematica", rng.integers(1, 4)),
                           ("epoca", 1), ("lugar", rng.integers(1, 3)), ("formato", 1), ("director", 1), ("actor", 3), ("decada", 1),
                           ("pais", 1), ("idioma", 1), ("estudio", rng.integers(1, 3)), ("saga", int(rng.random() < 0.25)),
                           ("premios", int(rng.random() < 0.15))):
            for c in rng.choice(por_grupo[g], size=int(cuantos), replace=False):
                elegidos[c] = peso_de[c]
        if cal != "":                                   # mismos cortes que la vista rasgos_modelo
            elegidos[por_grupo["critica"][0 if cal >= 8 else 1 if cal >= 6.5 else 2 if cal >= 5 else 3]] = 1.0
        elegidos[por_grupo["duracion"][0 if dur < 95 else 1 if dur <= 130 else 2]] = 1.0
        rasgos.extend((t, c, p) for c, p in elegidos.items())

    pos = {c: i for i, (c, _, _, _) in enumerate(claves)}
    X = np.zeros((n_titulos, len(claves)), dtype=np.float32)
    for t, c, p in rasgos:
        X[t - 1, pos[c]] = p
    # Qué tanto pesa cada grupo en los gustos escondidos. FUERZA_NUEVOS = 0 simula que los rasgos nuevos no sirven.
    fuerza = np.array([{"genero": 1.2, "subgenero": 0.8, "tono": 0.9, "tematica": 0.6, "director": 0.5,
                        "actor": 0.3, "saga": 1.0 * FUERZA_NUEVOS, "critica": 0.5 * FUERZA_NUEVOS, "estudio": 0.4 * FUERZA_NUEVOS,
                        "pais": 0.3 * FUERZA_NUEVOS, "idioma": 0.3 * FUERZA_NUEVOS, "premios": 0.3 * FUERZA_NUEVOS,
                        "duracion": 0.3 * FUERZA_NUEVOS}.get(g, 0.2) for _, g, _, _ in claves], dtype=np.float32)
    pop = np.array([t[3] for t in titulos])
    cal01 = np.array([(t[4] if t[4] != "" else 6.8) / 10 for t in titulos])

    inter = []
    for u in range(n_personas):
        gusto = rng.normal(0, 1, len(claves)) * fuerza * (rng.random(len(claves)) < 0.6)   # sus gustos escondidos
        base = rng.normal(0.2, 0.6)
        vistas = rng.choice(n_titulos, size=int(rng.integers(30, 120)), replace=False, p=pop / pop.sum())
        for t in vistas:
            calidad = 2.5 * FUERZA_NUEVOS * (cal01[t] - 0.68)          # a casi todos les gustan más las bien calificadas
            le_gusta = rng.random() < 1 / (1 + np.exp(-(base + X[t] @ gusto + calidad + rng.normal(0, 0.8))))
            if rng.random() < 0.25:
                accion = "vista_gusto" if le_gusta else "vista_no_gusto"
            elif not le_gusta and rng.random() < 0.15:
                accion = "no_interesa"
            else:
                accion = "like" if le_gusta else "dislike"
            origen = "recomendacion" if (le_gusta and rng.random() < 0.08) else "swipe"
            inter.append((f"persona-{u:03d}", t + 1, accion, origen, "2026-10-01T00:00:00+00:00", "true" if u % 2 else "false"))

    DEMO.mkdir(exist_ok=True)
    gi = BASE / ".gitignore"
    if not gi.exists():
        gi.write_text("datos/\ndatos_demo/\nsalidas/\nsalidas_demo/\n.env\n__pycache__/\n", encoding="utf-8")
    for nombre, encabezado, filas in (
            ("interacciones.csv", ["usuario", "titulo_id", "accion", "origen", "creado_en", "con_cuenta"], inter),
            ("titulos.csv", ["titulo_id", "titulo", "anio", "popularidad", "calificacion", "duracion_min"], titulos),
            ("rasgos.csv", ["titulo_id", "clave", "peso"], rasgos),
            ("claves.csv", ["clave", "grupo", "etiqueta", "nuevo"], claves)):
        with open(DEMO / nombre, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(encabezado)
            w.writerows(filas)
    print(f"Datos de mentira en {DEMO}: {n_personas} personas, {len(inter)} opiniones, {n_titulos} películas.")
    print("Siguiente:  python entrenar.py --demo")


if __name__ == "__main__":
    main()