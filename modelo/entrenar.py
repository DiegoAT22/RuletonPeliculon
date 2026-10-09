"""
PASO 2 — ENTRENAR Y COMPARAR
Entrena con los swipes bajados por descargar.py y compara varias formas de adivinar
si a una persona le va a gustar una película:

  1. Tasa de la persona            siempre contesta "qué tanto dice que sí esa persona" (el piso)
  2. Fórmula actual                el puntaje que hoy usa "Para ti" en Supabase
  3. Logística (rasgos de hoy)     aprende cuánto pesa cada grupo de rasgos (una sola neurona)
  4. Logística (+ rasgos nuevos)   la misma, sumando país, idioma, estudio, saga, crítica, premios y duración
  5. Red compacta                  red neuronal con esas mismas pocas entradas (incluye los nuevos)
  6. Red tabla completa            red neuronal que recibe la tabla de gustos entera + la película

La 3 contra la 4 dice si los rasgos nuevos (17_mas_rasgos.sql) de verdad ayudan: es el mismo
modelo con y sin ellos, calificado con los mismos swipes escondidos.

Para que la calificación sea honesta, de cada persona se esconde una parte de sus
swipes (la "prueba"): los modelos nunca los ven al entrenar y con ellos se les califica.
Todo se repite varias veces con repartos distintos; el ± dice cuánto cambia el resultado.

Deja en modelo/salidas/:
  reporte.txt               la tabla comparativa
  curvas.png                pérdida por época (entrenamiento vs validación)
  pesos_logistica.csv       qué aprendió la regresión logística (con todo lo que haya)
  modelo_*.keras            los modelos entrenados con todos los datos
  entradas.json             nombres de las entradas de cada modelo

Uso:
  python entrenar.py            con tus datos reales (modelo/datos)
  python entrenar.py --demo     con los datos de mentira de sintetico.py
"""
import argparse
import csv
import json
import os
import sys

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

import numpy as np

import config as C
import preparar as P


# ---------------------------------------------------------------------
# Cómo se califica
# ---------------------------------------------------------------------
def auc(y, p):
    """Probabilidad de que una película que SÍ le gustó quede arriba de una que NO. 0.5 = al azar, 1 = perfecto."""
    y = np.asarray(y); p = np.asarray(p)
    pos, neg = int((y == 1).sum()), int((y == 0).sum())
    if pos == 0 or neg == 0:
        return float("nan")
    orden = np.argsort(p, kind="mergesort")
    rango = np.empty(len(p), dtype=np.float64)
    rango[orden] = np.arange(1, len(p) + 1)
    for v in np.unique(p):                           # empates: rango promedio
        m = p == v
        if m.sum() > 1:
            rango[m] = rango[m].mean()
    return float((rango[y == 1].sum() - pos * (pos + 1) / 2) / (pos * neg))


def auc_por_persona(u, y, p):
    """El AUC dentro de cada persona, promediado. Es lo que importa para recomendar: ordenar bien SUS películas."""
    vals = [auc(y[u == k], p[u == k]) for k in np.unique(u)]
    vals = [v for v in vals if not np.isnan(v)]
    return float(np.mean(vals)) if vals else float("nan")


def perdida(y, p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def exactitud(y, p):
    return float(np.mean((p >= 0.5) == (y == 1)))


def calibrar(s, y):
    """Convierte el puntaje de la fórmula en probabilidad (una logística de 2 números, por Newton)."""
    a, b = 0.0, 0.0
    for _ in range(50):
        p = 1 / (1 + np.exp(-(a * s + b)))
        g = np.array([np.sum((p - y) * s), np.sum(p - y)])
        w = p * (1 - p) + 1e-9
        H = np.array([[np.sum(w * s * s) + 1e-6, np.sum(w * s)], [np.sum(w * s), np.sum(w) + 1e-6]])
        paso = np.linalg.solve(H, g)
        a, b = a - paso[0], b - paso[1]
    return lambda x: 1 / (1 + np.exp(-(a * x + b)))


# ---------------------------------------------------------------------
# Los modelos (Keras)
# ---------------------------------------------------------------------
def escala(keras, X_ent):
    """Pone todas las entradas en la misma escala (media 0, desviación 1) usando solo el entrenamiento.
    La varianza tiene un piso: una entrada que casi no cambia en el entrenamiento no debe volverse enorme después."""
    return keras.layers.Normalization(mean=X_ent.mean(axis=0), variance=np.maximum(X_ent.var(axis=0), 0.01))


def crear_logistica(keras, X_ent):
    norm = escala(keras, X_ent)
    m = keras.Sequential([
        keras.Input(shape=(X_ent.shape[1],)),
        norm,
        keras.layers.Dense(1, activation="sigmoid", kernel_regularizer=keras.regularizers.l2(C.L2)),
    ])
    m.compile(optimizer=keras.optimizers.Adam(C.TASA_LOGISTICA), loss="binary_crossentropy",
              metrics=[keras.metrics.BinaryCrossentropy(name="bce")])
    return m


def crear_red(keras, X_ent, dropout=None, l2=None, dropout_entrada=0.0):
    dropout = C.DROPOUT if dropout is None else dropout
    l2 = C.L2 if l2 is None else l2
    capas = [keras.Input(shape=(X_ent.shape[1],)), escala(keras, X_ent)]
    if dropout_entrada:
        capas.append(keras.layers.Dropout(dropout_entrada))
    for n in C.CAPAS:
        capas.append(keras.layers.Dense(n, activation="relu", kernel_regularizer=keras.regularizers.l2(l2)))
        capas.append(keras.layers.Dropout(dropout))                    # apaga neuronas al azar: evita memorizar
    capas.append(keras.layers.Dense(1, activation="sigmoid"))
    m = keras.Sequential(capas)
    m.compile(optimizer=keras.optimizers.Adam(C.TASA_RED), loss="binary_crossentropy",
              metrics=[keras.metrics.BinaryCrossentropy(name="bce")])
    return m


def crear_red_completa(keras, X_ent):
    return crear_red(keras, X_ent, dropout=C.DROPOUT_COMPLETA, l2=C.L2_COMPLETA, dropout_entrada=C.DROPOUT_ENTRADA_COMPLETA)


def ajustar(keras, modelo, ent, val, nombre, mostrar):
    """Entrena por épocas y se queda con los pesos de la mejor época en validación."""
    (X_ent, y_ent, w_ent), (X_val, y_val) = ent, val
    y_ent, y_val = y_ent.reshape(-1, 1), y_val.reshape(-1, 1)

    class Avance(keras.callbacks.Callback):
        def on_epoch_end(self, epoca, logs=None):
            if mostrar and (epoca == 0 or (epoca + 1) % 10 == 0):
                print(f"    época {epoca + 1:3d}   pérdida entrenamiento {logs['bce']:.3f}   validación {logs['val_bce']:.3f}")

    w_ent = w_ent / w_ent.mean()          # promedio 1: así la pérdida de entrenamiento se compara con la de validación
    if mostrar:
        pesos = sum(int(np.prod(w.shape)) for w in modelo.trainable_weights)
        print(f"\n  {nombre}: {X_ent.shape[1]} entradas, {pesos} pesos por aprender, {len(y_ent)} ejemplos")
    # Se vigila la pérdida "limpia" (entropía cruzada, sin el castigo L2) en validación
    parar = keras.callbacks.EarlyStopping(monitor="val_bce", mode="min", patience=C.PACIENCIA, min_delta=1e-4, restore_best_weights=True)
    h = modelo.fit(X_ent, y_ent, sample_weight=w_ent, validation_data=(X_val, y_val), epochs=C.EPOCAS,
                   batch_size=C.LOTE, verbose=0, callbacks=[parar, Avance()])
    mejor = int(np.argmin(h.history["val_bce"])) + 1
    if mostrar:
        print(f"    paró en la época {len(h.history['bce'])}; la mejor fue la {mejor} (validación {min(h.history['val_bce']):.3f})")
    return h.history, mejor


def predecir(modelo, X):
    return modelo.predict(X, verbose=0, batch_size=512)[:, 0]


# ---------------------------------------------------------------------
def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Entrena y compara los modelos de recomendación.")
    ap.add_argument("--demo", action="store_true", help="usar los datos de mentira de sintetico.py")
    args = ap.parse_args()
    carpeta = C.BASE / ("datos_demo" if args.demo else "datos")
    salidas = C.BASE / ("salidas_demo" if args.demo else "salidas")

    d = P.Datos(carpeta)
    por_persona = np.bincount(d.u, minlength=d.n_usuarios)
    validas = np.where(por_persona >= C.MIN_SWIPES_PERSONA)[0]
    usados = np.isin(d.u, validas)
    lineas = []

    def di(t=""):
        print(t)
        lineas.append(t)

    di("=" * 78)
    di("DATOS" + ("  (DE MENTIRA: sintetico.py)" if args.demo else ""))
    di(f"  personas con {C.MIN_SWIPES_PERSONA} o más swipes: {len(validas)} de {d.n_usuarios}"
       f"   (con cuenta: {int(d.con_cuenta[validas].sum())})")
    di(f"  ejemplos: {int(usados.sum())}   le gustó: {100 * d.y[usados].mean():.0f}%"
       f"   de Descubrir: {int((usados & d.es_swipe).sum())}   de Para ti: {int((usados & ~d.es_swipe).sum())}")
    di(f"  catálogo: {len(d.titulo_ids)} películas, {len(d.claves)} rasgos ({len(d.frecuentes)} aparecen en "
       f"{C.MIN_TITULOS_RASGO}+ películas), {len(d.grupos)} grupos")
    if d.hay_nuevos:
        di(f"  rasgos nuevos: {int(d.es_nuevo.sum())} en {len(d.grupos_nuevos)} grupos ({', '.join(d.grupos_nuevos) or 'ninguno'});"
           f"  con calificación de la crítica: {d.con_calificacion} películas")
    else:
        di("  rasgos nuevos: ninguno todavía (corre 17_mas_rasgos.sql, el importador y luego descargar.py)")
    if len(validas) == 0:
        raise SystemExit(f"\nTodavía nadie llega a {C.MIN_SWIPES_PERSONA} swipes. Junta más datos y vuelve a correr descargar.py.")

    print("\nCargando TensorFlow/Keras…")
    import keras

    LOG_HOY, LOG_NUEVOS = "Logística (rasgos de hoy)", "Logística (+ rasgos nuevos)"
    nombres = (["Tasa de la persona", "Fórmula actual", LOG_HOY] + ([LOG_NUEVOS] if d.hay_nuevos else [])
               + ["Red compacta", "Red tabla completa"])
    hoy = d.columnas_de_hoy()                       # columnas de la entrada compacta que la app ya usa
    res = {n: {"auc": [], "aucp": [], "exa": [], "per": []} for n in nombres}
    curvas, tamanos = {}, None

    for rep in range(C.REPETICIONES):
        keras.utils.set_random_seed(1000 + rep)
        ent, val, pru = P.repartir(d, semilla=rep)
        if len(pru) == 0 or len(val) == 0:
            raise SystemExit("No alcanzan los swipes para apartar validación y prueba.")
        tamanos = (len(ent), len(val), len(pru))
        ce, fe, se = P.entradas(d, ent, ent)        # entrenamiento: su propio swipe no cuenta en su tabla de gustos
        cv, fv, _ = P.entradas(d, ent, val)         # validación y prueba: tablas de gustos solo con el entrenamiento
        cp, fp, sp = P.entradas(d, ent, pru)
        ye, yv, yp, we = d.y[ent], d.y[val], d.y[pru], d.w_ejemplo[ent]
        up = d.u[pru]
        mostrar = rep == 0
        if mostrar:
            di(f"  cada repetición: {len(ent)} para entrenar, {len(val)} para validar, {len(pru)} de prueba")
            print("\n" + "=" * 78 + f"\nENTRENAMIENTO (se muestra la repetición 1 de {C.REPETICIONES})")

        pred = {
            "Tasa de la persona": cp[:, len(d.grupos) + 1],
            "Fórmula actual": calibrar(se, ye)(sp),
        }
        a_entrenar = [(LOG_HOY, crear_logistica, ce[:, hoy], cv[:, hoy], cp[:, hoy])]
        if d.hay_nuevos:
            a_entrenar.append((LOG_NUEVOS, crear_logistica, ce, cv, cp))
        a_entrenar += [("Red compacta", crear_red, ce, cv, cp), ("Red tabla completa", crear_red_completa, fe, fv, fp)]
        for nombre, crear, Xe, Xv, Xp in a_entrenar:
            m = crear(keras, Xe)
            hist, mejor = ajustar(keras, m, (Xe, ye, we), (Xv, yv), nombre, mostrar)
            if mostrar:
                curvas[nombre] = (hist, mejor)
            pred[nombre] = predecir(m, Xp)
        for nombre, p in pred.items():
            res[nombre]["auc"].append(auc(yp, p))
            res[nombre]["aucp"].append(auc_por_persona(up, yp, p))
            res[nombre]["exa"].append(exactitud(yp, p))
            res[nombre]["per"].append(perdida(yp, p))
        if not mostrar:
            print(f"  repetición {rep + 1} de {C.REPETICIONES} lista")

    # -----------------------------------------------------------------
    def pm(v):
        v = np.array(v, dtype=np.float64)
        v = v[~np.isnan(v)]
        return f"{v.mean():.3f} ± {v.std():.3f}" if len(v) else "   sin dato  "

    di("")
    di("=" * 78)
    di(f"RESULTADOS en los swipes escondidos (promedio de {C.REPETICIONES} repeticiones ± variación)")
    di(f"  {'':28s}{'AUC por persona':>18s}{'AUC general':>16s}{'exactitud':>16s}{'pérdida':>16s}")
    for n in nombres:
        r = res[n]
        di(f"  {n:28s}{pm(r['aucp']):>18s}{pm(r['auc']):>16s}{pm(r['exa']):>16s}{pm(r['per']):>16s}")
    di("")
    di("CÓMO LEERLO")
    di("  AUC por persona: de dos películas de la misma persona, una que le gustó y otra que no,")
    di("    qué tan seguido el modelo pone arriba la buena. 0.50 = al azar, 1.00 = perfecto.")
    di("    Es el número que importa para recomendar. La 'tasa de la persona' siempre da 0.50 aquí.")
    di("  AUC general: lo mismo pero mezclando personas (premia saber quién dice que sí a todo).")
    di("  Exactitud: porcentaje de aciertos diciendo sí/no. Pérdida: mientras más baja, mejor.")
    di("  El ± es cuánto cambia el resultado al cambiar qué swipes se esconden. Si la diferencia")
    di("    entre dos modelos es más chica que su ±, es un empate: no hay ganador todavía.")

    def media(n, k="aucp"):
        v = np.array(res[n][k], dtype=np.float64)
        v = v[~np.isnan(v)]
        return (v.mean(), v.std()) if len(v) else (float("nan"), float("nan"))

    f_m, f_s = media("Fórmula actual")
    aprendidos = [(media(n)[0], media(n)[1], n) for n in nombres[2:] if not np.isnan(media(n)[0])]
    di("")
    di("VEREDICTO")
    if aprendidos and not np.isnan(f_m):
        m_m, m_s, m_n = max(aprendidos)
        dif = m_m - f_m
        if dif > f_s + m_s:
            di(f"  {m_n} le gana a la fórmula actual por {dif:.3f} de AUC por persona (más que el ±).")
        elif -dif > f_s + m_s:
            di(f"  La fórmula actual sigue ganando: el mejor modelo entrenado ({m_n}) queda {-dif:.3f} abajo.")
        else:
            di(f"  Empate entre la fórmula actual y el mejor modelo entrenado ({m_n}): la diferencia ({dif:+.3f}) cabe en el ±.")
    else:
        di("  No hay suficientes swipes de prueba con 'sí' y 'no' de la misma persona para comparar.")
    avisos = []
    if len(validas) < 15:
        avisos.append(f"solo {len(validas)} personas (para confiar en los números conviene tener 20 o más)")
    if tamanos and tamanos[2] < 200:
        avisos.append(f"la prueba tiene {tamanos[2]} swipes (con menos de 200 el ± es muy grande)")
    if avisos:
        di("  OJO: " + "; ".join(avisos) + ".")
        di("  Con tan pocos datos estos números todavía no dicen qué modelo es mejor; sirven para ver que todo corre.")

    # ¿Sirvieron los rasgos nuevos? Mismo modelo, mismos swipes escondidos: se compara repetición por repetición.
    di("")
    di("¿AYUDAN LOS RASGOS NUEVOS?")
    if d.hay_nuevos:
        dif = np.array(res[LOG_NUEVOS]["aucp"], dtype=np.float64) - np.array(res[LOG_HOY]["aucp"], dtype=np.float64)
        dif = dif[~np.isnan(dif)]
        if len(dif) == 0:
            di("  No se pudo comparar (faltan swipes de prueba con 'sí' y 'no' de la misma persona).")
        else:
            m, sd, gano = dif.mean(), dif.std(), int((dif > 0).sum())
            di(f"  Con ellos el AUC por persona cambia {m:+.3f} en promedio (± {sd:.3f}); "
               f"fue mejor en {gano} de {len(dif)} repeticiones.")
            if m > sd and gano >= len(dif) - 1:
                di("  Sí ayudan: la mejora es más grande que su variación. Vale la pena prenderlos en la app.")
            elif -m > sd and gano <= 1:
                di("  Estorban: el modelo queda peor con ellos. No conviene prenderlos todavía.")
            else:
                di("  Todavía no se nota: la diferencia cabe en la variación. Se quedan guardados y se vuelve a medir con más swipes.")
    else:
        di("  Aún no hay rasgos nuevos en los datos: corre 17_mas_rasgos.sql, el importador y descargar.py.")

    # -----------------------------------------------------------------
    salidas.mkdir(exist_ok=True)
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ejes = plt.subplots(1, len(curvas), figsize=(5 * len(curvas), 3.8), sharey=True)
        for eje, (nombre, (hist, mejor)) in zip(np.atleast_1d(ejes), curvas.items()):
            x = np.arange(1, len(hist["bce"]) + 1)
            eje.plot(x, hist["bce"], label="entrenamiento", color="#2a78d6")
            eje.plot(x, hist["val_bce"], label="validación", color="#e34948")
            eje.axvline(mejor, color="#888888", linestyle="--", linewidth=1, label=f"mejor época ({mejor})")
            eje.set_title(nombre)
            eje.set_xlabel("época")
            eje.grid(alpha=0.25)
            eje.legend(frameon=False, fontsize=8)
        np.atleast_1d(ejes)[0].set_ylabel("pérdida")
        fig.suptitle("Pérdida por época (repetición 1)" + ("  ·  datos de mentira" if args.demo else ""))
        fig.tight_layout()
        fig.savefig(salidas / "curvas.png", dpi=130)
        plt.close(fig)
    except Exception as e:                                  # la gráfica es un extra: que no tumbe el entrenamiento
        print(f"(No se pudo dibujar curvas.png: {e})")

    # Modelos finales: ya con la comparación hecha, se entrena con TODO (la prueba ya no se esconde)
    print("\nEntrenando los modelos finales con todos los datos…")
    keras.utils.set_random_seed(999)
    ent, val, pru = P.repartir(d, semilla=0)
    todo = np.concatenate([ent, pru])
    ce, fe, _ = P.entradas(d, todo, todo)
    cv, fv, _ = P.entradas(d, todo, val)
    ye, yv, we = d.y[todo], d.y[val], d.w_ejemplo[todo]
    finales = {}
    a_guardar = [("modelo_logistica_hoy", crear_logistica, ce[:, hoy], cv[:, hoy])]
    if d.hay_nuevos:
        a_guardar.append(("modelo_logistica_nuevos", crear_logistica, ce, cv))
    a_guardar += [("modelo_red_compacta", crear_red, ce, cv), ("modelo_red_completa", crear_red_completa, fe, fv)]
    for archivo, crear, Xe, Xv in a_guardar:
        m = crear(keras, Xe)
        ajustar(keras, m, (Xe, ye, we), (Xv, yv), archivo, False)
        m.save(salidas / f"{archivo}.keras")
        finales[archivo] = m

    # Lo que aprendió la logística más completa que haya (con rasgos nuevos si existen)
    if d.hay_nuevos:
        pesos = finales["modelo_logistica_nuevos"].layers[-1].get_weights()[0][:, 0]
        entradas_log, nueva = d.nombres_compacta(), d.es_entrada_nueva()
    else:
        pesos = finales["modelo_logistica_hoy"].layers[-1].get_weights()[0][:, 0]
        entradas_log, nueva = [d.nombres_compacta()[i] for i in hoy], [False] * len(hoy)
    with open(salidas / "pesos_logistica.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["entrada", "peso", "es_nueva"])
        for i in np.argsort(-np.abs(pesos)):
            w.writerow([entradas_log[i], f"{pesos[i]:.4f}", "sí" if nueva[i] else "no"])
    (salidas / "entradas.json").write_text(json.dumps({
        "compacta": d.nombres_compacta(), "compacta_de_hoy": [d.nombres_compacta()[i] for i in hoy],
        "completa": d.nombres_completa(), "grupos": d.grupos, "grupos_nuevos": d.grupos_nuevos,
        "rasgos_frecuentes": [d.claves[i] for i in d.frecuentes],
        "ajustes": {k: getattr(C, k) for k in ("PESO_PERFIL", "SUAVIZADO", "PESO_POPULARIDAD", "MIN_TITULOS_RASGO", "CAPAS", "DROPOUT", "L2",
                                                 "DROPOUT_COMPLETA", "DROPOUT_ENTRADA_COMPLETA", "L2_COMPLETA")},
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    di("")
    di("QUÉ APRENDIÓ LA REGRESIÓN LOGÍSTICA (peso de cada entrada; más grande = importa más)")
    for i in np.argsort(-np.abs(pesos))[:10]:
        di(f"  {pesos[i]:+.2f}   {entradas_log[i]}" + ("   ← nuevo" if nueva[i] else ""))
    (salidas / "reporte.txt").write_text("\n".join(lineas) + "\n", encoding="utf-8")
    print(f"\nListo. Revisa {salidas}: reporte.txt, curvas.png, pesos_logistica.csv y los modelos .keras")


if __name__ == "__main__":
    main()