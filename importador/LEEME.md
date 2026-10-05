# Importador de películas (Wikidata → Supabase)

Etapas:

1. `python extraer.py` — baja de Wikidata las películas, sus visitas en Wikipedia en español y sus datos crudos. Gratis.
2. `python limpiar.py` — aplica las reglas de limpieza sin internet. Gratis. Se puede repetir cuantas veces quieras.
3. *(siguiente)* enriquecer con Claude: subgéneros y tags de tu taxonomía.
4. *(siguiente)* cargar a Supabase como "revisar".

## Primera vez

```
cd importador
python -m venv .venv
.venv\Scripts\activate          (en Windows)
pip install -r requirements.txt
```

Edita `config.py` y pon tu correo en `USER_AGENT`.

## Archivos que genera (carpeta datos/)

- `1_candidatas.json`, `cache_*.json` — caché; bórralos solo si quieres bajar todo de nuevo
- `2_crudo.json` — datos crudos de Wikidata
- `3_limpio.json` — películas limpias, listas para la etapa 3
- `reporte_limpieza.txt` — qué se excluyó, qué falta y qué géneros no tienen regla

La carpeta `datos/` y el archivo `.env` (etapas 3 y 4) están en `.gitignore`: nunca los subas a GitHub.

## Etapa 3: enriquecer con Claude

1. Crea una API key en https://console.anthropic.com (sección API Keys) y carga saldo.
2. Crea el archivo `importador/.env` con una sola línea:  `ANTHROPIC_API_KEY=sk-ant-...`
3. `pip install -r requirements.txt`
4. `python enriquecer.py`  (empieza con LIMITE_ENRIQUECER = 20 en config.py)

`taxonomia.json` es la lista cerrada de géneros, subgéneros y tags: Claude solo puede responder con esos valores.
Si agregas valores nuevos en Supabase, hay que actualizar este archivo.
