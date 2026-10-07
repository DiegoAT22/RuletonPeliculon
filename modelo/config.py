"""
Ajustes del entrenamiento. Lo que quieras probar se cambia aquí, no en los scripts.
"""
from pathlib import Path

BASE = Path(__file__).parent

# ---------------------------------------------------------------------
# Qué significa cada respuesta
# ---------------------------------------------------------------------
# Para armar la "tabla de gustos" de cada persona (igual que el recomendador de Supabase)
PESO_PERFIL = {"vista_gusto": 2.0, "like": 1.0, "no_interesa": -0.3, "dislike": -1.0, "vista_no_gusto": -1.5}
SUAVIZADO = 4.0          # pocos datos de un rasgo pesan poco: afinidad = suma / (veces + SUAVIZADO)
PESO_POPULARIDAD = 0.15  # lo que suma la popularidad en la fórmula actual

# Lo que el modelo aprende a predecir: 1 = le gusta, 0 = no le gusta
ETIQUETA = {"vista_gusto": 1, "like": 1, "no_interesa": 0, "dislike": 0, "vista_no_gusto": 0}

# Cuánto cuenta cada ejemplo al entrenar. "Ya la vi" es una opinión real;
# like/dislike es una corazonada; "no me interesa" es la señal más débil.
PESO_EJEMPLO = {"vista_gusto": 1.0, "vista_no_gusto": 1.0, "like": 0.7, "dislike": 0.7, "no_interesa": 0.4}

# ---------------------------------------------------------------------
# Qué datos entran
# ---------------------------------------------------------------------
MIN_SWIPES_PERSONA = 20     # personas con menos swipes no se usan (su tabla de gustos es puro ruido)
MIN_TITULOS_RASGO = 5       # para la entrada "completa": un rasgo entra si aparece en al menos N películas
SOLO_SWIPE_EN_PRUEBA = True  # la prueba usa solo swipes de Descubrir (los de "Para ti" ya vienen filtrados)

# ---------------------------------------------------------------------
# Cómo se evalúa
# ---------------------------------------------------------------------
FRACCION_PRUEBA = 0.20      # de cada persona, esta parte se esconde y solo se usa para calificar al modelo
FRACCION_VALIDACION = 0.15  # del resto, esta parte decide en qué época parar
REPETICIONES = 5            # se repite todo con distintos repartos al azar; el ± sale de aquí

# ---------------------------------------------------------------------
# La red
# ---------------------------------------------------------------------
EPOCAS = 300                # máximo; casi siempre para antes
PACIENCIA = 25              # épocas sin mejorar en validación antes de parar
LOTE = 32
CAPAS = [32, 16]            # neuronas de cada capa oculta
DROPOUT = 0.3               # fracción de neuronas que se apagan al azar en cada paso (evita memorizar)
L2 = 1e-3                   # castigo a los pesos grandes (evita memorizar)
# La red de "tabla completa" tiene cientos de entradas: necesita frenos más fuertes
DROPOUT_COMPLETA = 0.5
DROPOUT_ENTRADA_COMPLETA = 0.3
L2_COMPLETA = 1e-2
TASA_RED = 1e-3
TASA_LOGISTICA = 1e-2
