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
    claves, peso_de = [], {}
    for g, (n, peso) in grupos.items():
        for i in range(n):
            claves.append((f"{g[:3]}{i}", g, f"{g} {i}"))
            peso_de[f"{g[:3]}{i}"] = peso
    por_grupo = {g: [c for c, gg, _ in claves if gg == g] for g in grupos}

    titulos, rasgos = [], []
    for t in range(1, n_titulos + 1):
        titulos.append((t, f"Película {t}", int(rng.integers(1950, 2025)), round(float(rng.gamma(2.0, 20.0)), 1)))
        elegidos = {}
        gen = rng.choice(por_grupo["genero"], size=int(rng.integers(1, 3)), replace=False)
        elegidos[gen[0]] = 1.5
        for c in gen[1:]:
            elegidos[c] = 1.0
        for g, cuantos in (("subgenero", rng.integers(0, 3)), ("tono", rng.integers(1, 3)), ("tematica", rng.integers(1, 4)),
                           ("epoca", 1), ("lugar", rng.integers(1, 3)), ("formato", 1), ("director", 1), ("actor", 3), ("decada", 1)):
            for c in rng.choice(por_grupo[g], size=int(cuantos), replace=False):
                elegidos[c] = peso_de[c]
        rasgos.extend((t, c, p) for c, p in elegidos.items())

    pos = {c: i for i, (c, _, _) in enumerate(claves)}
    X = np.zeros((n_titulos, len(claves)), dtype=np.float32)
    for t, c, p in rasgos:
        X[t - 1, pos[c]] = p
    fuerza = np.array([{"genero": 1.2, "subgenero": 0.8, "tono": 0.9, "tematica": 0.6, "director": 0.5,
                        "actor": 0.3}.get(g, 0.2) for _, g, _ in claves], dtype=np.float32)
    pop = np.array([t[3] for t in titulos])

    inter = []
    for u in range(n_personas):
        gusto = rng.normal(0, 1, len(claves)) * fuerza * (rng.random(len(claves)) < 0.6)   # sus gustos escondidos
        base = rng.normal(0.2, 0.6)
        vistas = rng.choice(n_titulos, size=int(rng.integers(30, 120)), replace=False, p=pop / pop.sum())
        for t in vistas:
            le_gusta = rng.random() < 1 / (1 + np.exp(-(base + X[t] @ gusto + rng.normal(0, 0.8))))
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
            ("titulos.csv", ["titulo_id", "titulo", "anio", "popularidad"], titulos),
            ("rasgos.csv", ["titulo_id", "clave", "peso"], rasgos),
            ("claves.csv", ["clave", "grupo", "etiqueta"], claves)):
        with open(DEMO / nombre, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(encabezado)
            w.writerows(filas)
    print(f"Datos de mentira en {DEMO}: {n_personas} personas, {len(inter)} opiniones, {n_titulos} películas.")
    print("Siguiente:  python entrenar.py --demo")


if __name__ == "__main__":
    main()
