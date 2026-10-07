"""
Convierte los CSV en lo que entra a los modelos. No se ejecuta solo: lo usa entrenar.py.

La idea, paso a paso:

  1. TABLA DE GUSTOS de cada persona: por cada rasgo (género, tono, director…),
     qué tanto le gusta, calculado con sus swipes:
         afinidad = suma(valor_del_swipe × peso_del_rasgo) / (veces_que_lo_vio + SUAVIZADO)
     Es la misma cuenta que hace el recomendador en Supabase.

  2. EJEMPLOS: cada swipe es un ejemplo (persona, película) → le gustó (1) o no (0).
     Las entradas del ejemplo salen de cruzar la tabla de gustos de la persona con
     los rasgos de la película.

  3. SIN TRAMPA: para el ejemplo "¿le gustó Alien a Diego?", la tabla de gustos de
     Diego se calcula SIN contar su swipe de Alien. Si no, el modelo solo tendría que
     leer la respuesta que ya viene escondida en la entrada. Y los swipes que se
     guardan para la prueba nunca entran en ninguna tabla de gustos.
"""
import csv
from pathlib import Path

import numpy as np

import config as C


def _leer(ruta):
    with open(ruta, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


class Datos:
    """Todo lo que se bajó de Supabase, ya en matrices."""

    def __init__(self, carpeta):
        carpeta = Path(carpeta)
        for nombre in ("interacciones.csv", "titulos.csv", "rasgos.csv", "claves.csv"):
            if not (carpeta / nombre).exists():
                raise SystemExit(f"Falta {carpeta / nombre}. Corre primero:  python descargar.py")

        titulos = _leer(carpeta / "titulos.csv")
        self.titulo_ids = [int(t["titulo_id"]) for t in titulos]
        self.titulo_nombre = [t["titulo"] for t in titulos]
        pos_titulo = {tid: i for i, tid in enumerate(self.titulo_ids)}
        pop = np.array([float(t["popularidad"] or 0) for t in titulos], dtype=np.float32)
        self.pop = np.log1p(np.maximum(pop, 0)) / max(np.log1p(max(float(pop.max()), 1.0)), 1e-9)

        claves = _leer(carpeta / "claves.csv")
        self.claves = [c["clave"] for c in claves]
        self.etiquetas = [c["etiqueta"] for c in claves]
        self.grupo_de = [c["grupo"] for c in claves]
        pos_clave = {c: i for i, c in enumerate(self.claves)}
        self.grupos = sorted(set(self.grupo_de))
        # G[rasgo, grupo] = 1 si el rasgo es de ese grupo
        self.G = np.zeros((len(self.claves), len(self.grupos)), dtype=np.float32)
        for i, g in enumerate(self.grupo_de):
            self.G[i, self.grupos.index(g)] = 1.0

        # X[película, rasgo] = peso del rasgo en esa película (0 si no lo tiene)
        self.X = np.zeros((len(self.titulo_ids), len(self.claves)), dtype=np.float32)
        for r in _leer(carpeta / "rasgos.csv"):
            t, c = pos_titulo.get(int(r["titulo_id"])), pos_clave.get(r["clave"])
            if t is not None and c is not None:
                self.X[t, c] = float(r["peso"])
        self.B = (self.X > 0).astype(np.float32)
        # rasgos frecuentes: los únicos que entran tal cual en la entrada "completa"
        self.frecuentes = np.where(self.B.sum(axis=0) >= C.MIN_TITULOS_RASGO)[0]

        usuarios, self.u, self.t, self.accion, self.origen, cuenta = {}, [], [], [], [], {}
        for r in _leer(carpeta / "interacciones.csv"):
            t = pos_titulo.get(int(r["titulo_id"]))
            if t is None or r["accion"] not in C.ETIQUETA:
                continue
            u = usuarios.setdefault(r["usuario"], len(usuarios))
            cuenta[u] = str(r.get("con_cuenta", "")).lower() in ("true", "t", "1")
            self.u.append(u); self.t.append(t); self.accion.append(r["accion"]); self.origen.append(r["origen"])
        self.u = np.array(self.u, dtype=np.int64)
        self.t = np.array(self.t, dtype=np.int64)
        self.y = np.array([C.ETIQUETA[a] for a in self.accion], dtype=np.float32)
        self.w_perfil = np.array([C.PESO_PERFIL[a] for a in self.accion], dtype=np.float32)
        self.w_ejemplo = np.array([C.PESO_EJEMPLO[a] for a in self.accion], dtype=np.float32)
        # "perfil" = la persona corrigió su respuesta desde su perfil: vale igual que un swipe de Descubrir
        self.es_swipe = np.array([o in ("swipe", "perfil") for o in self.origen])
        self.n_usuarios = len(usuarios)
        self.con_cuenta = np.array([cuenta.get(i, False) for i in range(self.n_usuarios)])

    def nombres_compacta(self):
        return ([f"afinidad: {g}" for g in self.grupos]
                + ["popularidad", "qué tanto dice que sí", "cuánto ha calificado"])

    def nombres_completa(self):
        f = self.frecuentes
        return ([f"gusto de la persona: {self.etiquetas[i]}" for i in f]
                + [f"la película tiene: {self.etiquetas[i]}" for i in f]
                + [f"coincide: {self.etiquetas[i]}" for i in f]
                + ["popularidad", "qué tanto dice que sí", "cuánto ha calificado"])


def repartir(d, semilla):
    """Reparte los swipes de cada persona en entrenamiento / validación / prueba (al azar)."""
    rng = np.random.default_rng(semilla)
    ent, val, pru = [], [], []
    for u in range(d.n_usuarios):
        idx = np.where(d.u == u)[0]
        if len(idx) < C.MIN_SWIPES_PERSONA:
            continue
        candidatos = idx[d.es_swipe[idx]] if C.SOLO_SWIPE_EN_PRUEBA else idx
        n_pru = min(int(round(C.FRACCION_PRUEBA * len(idx))), len(candidatos))
        p = rng.choice(candidatos, size=n_pru, replace=False) if n_pru else np.array([], dtype=np.int64)
        resto = rng.permutation(np.setdiff1d(idx, p))
        n_val = int(round(C.FRACCION_VALIDACION * len(resto)))
        pru.extend(p); val.extend(resto[:n_val]); ent.extend(resto[n_val:])
    return np.array(ent, dtype=np.int64), np.array(val, dtype=np.int64), np.array(pru, dtype=np.int64)


def entradas(d, historia, objetivo):
    """
    Arma las entradas de los ejemplos `objetivo`.
    `historia` = swipes con los que se vale armar las tablas de gustos (los de entrenamiento).
    Si un ejemplo está dentro de la historia, su propio swipe se descuenta (ver SIN TRAMPA arriba).

    Regresa (compacta, completa, formula):
      compacta: una columna por grupo de rasgos (afinidad con los géneros de la película,
                con su tono, con su director…) + 3 datos generales. Pocas entradas: aprende con pocos datos.
                Es lo mismo que suma la fórmula actual, pero separado por grupo para que el
                modelo decida cuánto pesa cada uno.
      completa: la tabla de gustos de la persona + los rasgos de la película + su cruce,
                rasgo por rasgo. Muchas entradas: necesita muchos datos.
      formula:  el puntaje que da hoy el recomendador de Supabase (para comparar).
    """
    n_g, F = len(d.grupos), d.frecuentes
    compacta = np.zeros((len(objetivo), n_g + 3), dtype=np.float32)
    formulas = np.zeros(len(objetivo), dtype=np.float32)
    completa = np.zeros((len(objetivo), 3 * len(F) + 3), dtype=np.float32)
    en_historia = np.zeros(len(d.u), dtype=bool)
    en_historia[historia] = True

    for u in np.unique(d.u[objetivo]):
        h = historia[d.u[historia] == u]
        S = (d.w_perfil[h, None] * d.X[d.t[h]]).sum(axis=0)       # suma(valor × peso) por rasgo
        Cn = d.B[d.t[h]].sum(axis=0)                              # veces que vio cada rasgo
        positivos, total = d.y[h].sum(), len(h)

        filas = np.where(d.u[objetivo] == u)[0]
        obj = objetivo[filas]
        Xm, Bm = d.X[d.t[obj]], d.B[d.t[obj]]
        propio = en_historia[obj].astype(np.float32)[:, None]     # 1 si hay que descontar su propio swipe
        S_i = S[None, :] - propio * d.w_perfil[obj, None] * Xm
        C_i = Cn[None, :] - propio * Bm
        A = S_i / (C_i + C.SUAVIZADO)                             # tabla de gustos (una por ejemplo)

        cruce = A * Xm
        por_grupo = (cruce @ d.G) / np.sqrt(np.maximum(Bm @ d.G, 1.0))
        formula = cruce.sum(axis=1) / np.sqrt(np.maximum(Bm.sum(axis=1), 1.0)) + C.PESO_POPULARIDAD * d.pop[d.t[obj]]
        # "Qué tanto dice que sí" esta persona. Para los ejemplos de la historia se calcula
        # con los OTROS cuatro quintos de sus swipes: si solo se descontara el propio, el
        # dato tomaría dos valores por persona (uno si dijo sí, otro si dijo no) y delataría la respuesta.
        tasa = np.full(len(obj), (positivos + 1.0) / (total + 2.0), dtype=np.float32)
        quinto = {int(i): k % 5 for k, i in enumerate(h)}
        for k in range(5):
            otros = np.array([i for i in h if quinto[int(i)] != k], dtype=np.int64)
            mios = np.array([en_historia[i] and quinto.get(int(i)) == k for i in obj])
            if mios.any():
                tasa[mios] = (d.y[otros].sum() + 1.0) / (len(otros) + 2.0)
        generales = np.stack([d.pop[d.t[obj]], tasa, np.full(len(obj), np.log1p(total), dtype=np.float32)], axis=1)

        compacta[filas, :n_g] = por_grupo
        compacta[filas, n_g:] = generales
        formulas[filas] = formula
        completa[filas] = np.concatenate([A[:, F], Xm[:, F], cruce[:, F], generales], axis=1)

    return compacta, completa, formulas