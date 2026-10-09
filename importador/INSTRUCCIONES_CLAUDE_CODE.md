# Clasificar películas (instrucciones para Claude Code)

Este archivo lo lee Claude Code. Diego solo tiene que pegarle esto en el chat de Claude Code,
con la terminal parada en la carpeta del proyecto:

```
Lee importador/INSTRUCCIONES_CLAUDE_CODE.md y sigue sus pasos hasta que no queden lotes pendientes.
```

---

## Qué vas a hacer

Eres el curador de cine de RuletonPeliculon, una app mexicana de recomendaciones de películas.
En `importador/datos/lotes/` hay archivos `pendiente_NNN.json`, cada uno con hasta 40 películas
sacadas de Wikidata. Por cada película eliges sus géneros, subgéneros y tags **de una lista cerrada**
y escribes una sinopsis corta. Con eso el recomendador aprende qué le gusta a cada persona, así que
vale más poco y correcto que mucho y dudoso.

## Pasos

1. Lee `importador/taxonomia.json`: ahí están TODOS los valores permitidos. No existe ningún otro.
2. Corre `python lotes.py --ejemplos` dentro de `importador/` para ver 3 películas ya clasificadas
   y copiar el estilo de las sinopsis.
3. Toma el `pendiente_NNN.json` con el número más bajo. Clasifica todas sus películas y escribe
   `importador/datos/lotes/respuesta_NNN.json` (mismo número).
4. Corre `python lotes.py --juntar` dentro de `importador/`. Revisa cada respuesta contra la taxonomía:
   las correctas se guardan y las que traen errores te las lista. Corrige esos errores en el mismo
   `respuesta_NNN.json` y vuelve a correr `--juntar` hasta que no marque ninguno.
5. Repite 3 y 4 con el siguiente archivo hasta que `--juntar` diga `Faltan 0`.
6. Al terminar dile a Diego cuántas clasificaste, cuántas quedaron con confianza "baja" y las notas
   que dejaste. No corras `enriquecer.py` ni `cargar.py`: eso lo hace él.

## Formato de `respuesta_NNN.json`

Un objeto cuya llave es el `id` de cada película del archivo pendiente:

```json
{
 "Q25188": {
  "confianza": "alta",
  "generos": ["Ciencia ficción", "Thriller"],
  "subgeneros": [],
  "formato": ["Live action"],
  "audiencia": ["Adolescente"],
  "basado_en": ["Original"],
  "epoca": ["Contemporánea"],
  "lugar": ["Urbano"],
  "tematica": ["Secretos"],
  "tono": ["Tenso", "Psicológico"],
  "escala": ["Épica"],
  "sinopsis": "Un ladrón que roba secretos metiéndose en los sueños de otros recibe el encargo contrario: sembrar una idea en la mente de un heredero.",
  "nota": ""
 }
}
```

Todos los campos van siempre, aunque sea como lista vacía `[]` o texto vacío `""`.

| Campo | Cuántos | De dónde salen los valores |
|---|---|---|
| `confianza` | 1 | `"alta"`, `"media"` o `"baja"` |
| `generos` | 0 a 3 | `orden_generos` (vacío solo si es documental) |
| `subgeneros` | 0 a 3 | `generos` → se escribe `"Género: Subgénero"`, y su género debe estar en `generos` |
| `formato` | 1 a 2 | `tags.formato.valores` |
| `audiencia` | exactamente 1 | `tags.audiencia.valores` |
| `basado_en` | 0 a 2 | `tags.basado-en.valores` |
| `epoca` | 0 a 2 | `tags.epoca.valores` |
| `lugar` | 0 a 3 | `tags.lugar.valores` |
| `tematica` | 0 a 4 | `tags.tematica.valores` |
| `tono` | 1 a 2 | `tags.tono.valores` |
| `escala` | exactamente 1 | `tags.escala.valores` |
| `sinopsis` | texto | 1 o 2 oraciones, máximo 400 caracteres |
| `nota` | texto | duda para Diego; vacío si no hay |

Los valores se copian tal cual de `taxonomia.json`, con sus acentos y mayúsculas.

## Reglas para clasificar

- **Clasifica con lo que sabes de ESA película.** Confirma que sea la correcta con título, año y
  director: hay muchas con nombre parecido. Si no la conoces bien, pon confianza `"baja"`, clasifica
  solo con los datos del archivo y deja la sinopsis vacía. No inventes.
- **Géneros:** `sugerido_por_reglas` y `pistas_de_wikidata.generos_wikidata` suelen traer de más.
  Quédate con 1 a 3 que de verdad la definan, el principal primero.
- **Subgéneros:** solo si encaja claramente.
- **Temática y lugar:** solo lo central o característico, no cualquier cosa que aparezca. Las pistas
  `temas`, `lugares` y `epoca` ayudan, pero tú decides si son centrales.
- **Tono:** el dominante de la película completa, no el de una escena.
- **Audiencia:** "Infantil" (pensada para niños), "Familiar" (todas las edades), "Adolescente"
  (equivale a clasificación B o PG-13), "Adultos" (contenido maduro, violencia o sexo explícitos).
- **Escala:** "Íntima" (pocos personajes, conflicto personal) o "Épica" (gran producción o lo que
  está en juego es enorme).
- **Sinopsis:** con tus propias palabras, nunca copiada de Wikipedia ni de otra fuente, en español
  natural de México, sin revelar giros ni el final. Usa el título en español que viene en el archivo.
- **Parejo:** que no todas terminen con el mismo tono o la misma temática por inercia. `--juntar`
  imprime cómo se repartieron los valores; si uno domina sin razón, revisa ese lote.

## Lo que NO debes hacer

- No escribas un script que adivine las etiquetas con palabras clave: cada película se decide una por una.
- No edites `datos/cache_claude.json` a mano: solo `lotes.py --juntar` escribe ahí.
- No modifiques `taxonomia.json` ni agregues valores nuevos. Si crees que falta uno, dilo en `nota`.
- No abras, imprimas ni copies `importador/.env` (trae llaves secretas) y no subas nada a GitHub.
- No toques nada fuera de `importador/datos/lotes/`.
