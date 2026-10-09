# =====================================================================
#  Configuración del importador (aquí NO van llaves secretas)
# =====================================================================

# Wikimedia pide identificarse. Pon un correo real para que te contacten
# si algo sale mal, en lugar de bloquearte.
USER_AGENT = "RuletaPeliculas/0.1 (https://djsolution.com.mx; 2digitaljob@gmail.com)"

# Etapa 1 — qué películas se consideran
MIN_SITELINKS = 40   # en cuántas Wikipedias debe tener artículo (más alto = menos y más famosas).
                     # Si la consulta marca timeout, súbelo.
LIMITE = 1500         # cuántas se quedan, ordenadas por visitas en Wikipedia en español.
                     # Empieza chico para probar; luego súbelo a 2000 o más.
HILOS = 2            # peticiones en paralelo (no lo subas mucho, por respeto a Wikimedia)
PAUSA_ENTRE_PETICIONES = 0.3   # segundos de respiro entre peticiones de cada hilo

# Etapa 2 — reglas de limpieza
MAX_DIRECTORES = 3
MAX_ACTORES = 8
MAX_ESTUDIOS = 3
DURACION_MIN = 40    # menos que esto es cortometraje
DURACION_MAX = 600

# Etapa 3 — Claude
MODELO_CLAUDE = "claude-haiku-4-5-20251001"   # solo se usa si algún día pones una llave de API
PRECIO_ENTRADA = 1.0
PRECIO_SALIDA = 5.0
LIMITE_ENRIQUECER = 1500   # cuántas películas toma de 3_limpio.json
HILOS_CLAUDE = 4
# Películas que nunca deben entrar (IDs de Wikidata), ej. {"Q12345", "Q67890"}
EXCLUIR = {"Q832093"}

# Etapa 3 con Claude Code (lotes.py)
TAMANO_LOTE = 40     # películas por archivo de lote: Claude Code clasifica un archivo a la vez