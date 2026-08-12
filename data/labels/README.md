# Etiquetas de entrenamiento

Puntos etiquetados a mano en QGIS sobre la escena de referencia de Costa Vasca
(`20241228`, elegida por su baja nubosidad). Son los que entrenan el modelo de producción
`data/models/production/rf_prod.joblib`.

| Fichero | Qué es | Lo usa |
|---|---|---|
| `costa_vasca_labels.geojson` | Los puntos: geometría + columna `etiquetas` | `src/classifier.py` |
| `costa_vasca_labels.gpkg` | Los mismos puntos en GeoPackage | — |
| `costa_vasca_labels.qmd` | Estilo QGIS (colores por clase) | QGIS |
| `labels_costa_zarautz.qgz` | Proyecto QGIS del etiquetado | QGIS |

Los dos últimos no los lee el pipeline: están para poder **abrir, revisar y ampliar el
etiquetado**, o rehacerlo sobre otra zona. El `.qgz` puede llevar rutas absolutas de la
máquina donde se creó; si las capas salen rotas, vuelve a apuntarlas al `.geojson`.

## Etiquetar una zona nueva

1. Abre en QGIS una escena de referencia de tu zona con poca nubosidad.
2. Crea una capa de puntos con un campo de texto llamado **`etiquetas`** (el nombre importa:
   `classifier.py` lo busca por ese nombre).
3. Coloca puntos sobre zonas inequívocas de cada clase. Las cuatro usadas aquí son
   `agua`, `vegetacion`, `urbano` y `litoral`, pero puedes definir las tuyas: las clases
   salen del propio GeoJSON, no están fijadas en el código.
4. Exporta a GeoJSON y apunta `classifier.labels_path` de tu config al fichero.
5. Entrena (guarda en `data/models/rf_mi_zona.joblib`, no toca `production/`):

   ```bash
   python src/classifier.py --config config/mi_zona.yaml --name rf_mi_zona
   ```

6. Si el modelo te convence, cópialo a mano a producción y apúntalo desde el config:

   ```bash
   cp data/models/rf_mi_zona.joblib data/models/production/rf_mi_zona.joblib
   ```

   `classifier.model_name: "rf_mi_zona"` en el config.

Reparte los puntos por toda la extensión del bbox: el split train/test es por bloques
espaciales de 500 m, así que puntos concentrados en una esquina dejan bloques enteros sin
representación.
