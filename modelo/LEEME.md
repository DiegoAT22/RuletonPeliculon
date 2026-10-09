# Modelo de recomendación (entrenamiento)

Entrena con los swipes de RuletonPeliculon y compara contra la fórmula que hoy usa "Para ti".

## Una sola vez

1. Corre `15_exportar_modelo.sql` y `17_mas_rasgos.sql` en Supabase.
2. Instala lo necesario (Python 3.10 a 3.13):

       cd modelo
       pip install -r requirements.txt

   La llave se lee de `importador/.env` (la misma del importador). No hay que copiarla.

## Cada vez que quieras entrenar

    python descargar.py     # baja los swipes a modelo/datos/
    python entrenar.py      # entrena, compara y deja todo en modelo/salidas/

Abre `salidas/reporte.txt` y `salidas/curvas.png`.

## Rasgos nuevos

Con `17_mas_rasgos.sql` cada película trae además país, idioma, estudio, saga, crítica, premios y
duración. La app todavía no los usa: primero se miden aquí. `entrenar.py` entrena el mismo modelo con
y sin ellos y lo dice en la sección **¿AYUDAN LOS RASGOS NUEVOS?** del reporte. Solo si la mejora es
más grande que su variación conviene prenderlos en "Para ti".

## Para probar sin datos reales

    python sintetico.py     # inventa 40 personas con gustos que sí se pueden aprender
    python entrenar.py --demo

## Qué hace cada archivo

| Archivo | Qué hace |
|---|---|
| `config.py` | Todos los ajustes: capas, dropout, épocas, cuántos swipes mínimo por persona… |
| `descargar.py` | Baja de Supabase los swipes, el catálogo y los rasgos |
| `preparar.py` | Arma la tabla de gustos de cada persona y las entradas de los modelos |
| `entrenar.py` | Entrena por épocas, califica con swipes escondidos y guarda los modelos |
| `sintetico.py` | Datos de mentira para probar el entrenamiento |

`datos/` y `salidas/` no se suben al repo (lo dice `.gitignore`): ahí hay swipes de personas reales.