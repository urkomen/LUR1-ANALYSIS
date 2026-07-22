# Plan de proyecto: Pipeline multiespectral LUR-1

Pipeline de análisis de imagen satelital multiespectral parametrizable por ubicación,
inspirado en la misión LUR-1 de AVS. Incluye clasificador de cobertura terrestre y
detector de anomalías temporales sobre series de 12 meses de datos Sentinel-2.

**Repositorio:** `lur1-analysis`
**Duración estimada:** 5 semanas · ~50 horas totales
**Versión actual:** v1 (candidable) → v2 (expansión tras primera entrevista)

---

## Arquitectura del sistema

El sistema recibe un fichero `config.yaml` como única entrada. Cambiar la ubicación,
las fechas o los modelos no requiere tocar código — solo editar el YAML.

```
lur1-analysis-pipeline/
├── config/
│   ├── costa_vasca.yaml         # ubicación por defecto
│   ├── urdaibai.yaml            # segunda demo
│   └── template.yaml            # plantilla para cualquier zona del mundo
├── src/
│   ├── pipeline.py              # clase Pipeline principal
│   ├── downloader.py            # descarga Sentinel-2 según config
│   ├── preprocessor.py          # máscaras de nubes, recorte al bbox
│   ├── indices.py               # NDVI, NDWI, MNDWI y otros índices
│   ├── classifier.py            # clasificador de cobertura terrestre
│   ├── anomaly_detector.py      # detector de anomalías temporales
│   └── visualizer.py            # mapas y gráficos exportables
├── notebooks/
│   ├── 00_demo.ipynb            # demo ejecutable de principio a fin
│   ├── 01_exploracion.ipynb
│   ├── 02_clasificador.ipynb
│   └── 03_anomalias.ipynb
├── data/                        # en .gitignore (demasiado grande)
│   ├── raw/
│   ├── processed/
│   └── labels/
├── figures/                     # visualizaciones exportadas para el README y CV
├── environment.yml
├── Makefile
└── README.md
```

Ejemplo de `config/costa_vasca.yaml`:

```yaml
location:
  name: "Costa vasca — Zarautz a Donostia"
  bbox: [-2.20, 43.25, -1.90, 43.40]   # [lon_min, lat_min, lon_max, lat_max]

dates:
  start: "2024-01-01"
  end:   "2024-12-31"

satellite:
  sensor:        "Sentinel-2"
  product_level: "L2A"
  max_cloud_pct: 20

indices: ["NDVI", "NDWI", "MNDWI"]

classifier:
  classes: ["agua", "vegetacion", "urbano", "litoral"]
  model:   "random_forest"           # "cnn" disponible en v2

anomaly_detector:
  method:          "statistical"     # "isolation_forest" disponible en v2
  window_days:     30
  threshold_sigma: 2.0
```

Ejecución desde terminal:

```bash
make run CONFIG=config/costa_vasca.yaml
make run CONFIG=config/urdaibai.yaml     # segunda demo — mismo código, otro lugar
```

---

## Fase 1 — Entorno, estructura y exploración

**Semana 1 · ~8 horas**
Objetivo: entorno funcional, arquitectura del repo definida desde el primer día,
primeros datos descargados y explorados visualmente.

### 1.1 Entorno reproducible

- [X] Crear entorno conda con dependencias geoespaciales (`rasterio`, `GDAL`, `geopandas`, `xarray`, `sentinelsat`, `scikit-learn`, `matplotlib`, `folium`)
- [X] Verificar que `import rasterio` y `import geopandas` funcionan sin errores
- [X] Generar `environment.yml` con `conda env export`
- [X] Añadir `.gitignore` con exclusiones estándar de Python + `/data/`

> **Nota:** Resolver GDAL/rasterio el primer día. Si hay conflictos de dependencias,
> usar `conda-forge` como canal prioritario. No avanzar hasta que el entorno esté limpio.

### 1.2 Estructura del repositorio y clase Pipeline

- [X] Inicializar repositorio Git y hacer primer commit con la estructura de carpetas
- [X] Crear `config/costa_vasca.yaml` con los campos definidos en la arquitectura
- [X] Crear `config/template.yaml` vacío con comentarios explicativos para cada campo
- [X] Crear `src/pipeline.py` con la clase `Pipeline` como stub: `__init__(config_path)`, métodos vacíos `download()`, `preprocess()`, `classify()`, `detect_anomalies()`, `run_full()`
- [X] Crear `Makefile` con regla `run: python src/pipeline.py --config $(CONFIG)`
- [X] Verificar que `make run CONFIG=config/costa_vasca.yaml` ejecuta sin errores (aunque no haga nada todavía)

### 1.3 Descarga de datos Sentinel-2

- [x] Crear cuenta en Copernicus Open Hub (scihub.copernicus.eu) si no existe
- [x] Implementar `downloader.py`: función `download(config)` que usa la API OData de CDSE para buscar y descargar escenas L2A dentro del bbox y rango de fechas del config
- [x] Filtrar por `max_cloud_pct` del config
- [x] Descargar 2-3 escenas de la costa vasca (Zarautz–Donostia) con cobertura nubosa < 20%
- [x] Guardar en `/data/raw/`
- [x] Conectar `downloader.py` a `Pipeline.download()`

> **Truco:** Usar producto L2A directamente (ya corregido atmosféricamente por ESA).
> Evita tener que correr Sen2Cor localmente, que tarda 30-60 min por escena.

### 1.4 Exploración visual

- [x] Crear `notebooks/01_exploracion.ipynb`
- [x] Visualizar cada banda individualmente con `rasterio` + `matplotlib`
- [x] Composición RGB (bandas B04-B03-B02)
- [x] Composición falso color NIR (bandas B08-B04-B03)
- [x] Histograma de distribución de valores por banda
- [x] Scatter plot B08 (NIR) vs B04 (Red) — la base del NDVI
- [x] Confirmar que los datos tienen buena calidad visual antes de avanzar

**Entregables de F1:**

- `environment.yml` funcional
- Estructura de repo con `Pipeline` stub
- `config/costa_vasca.yaml` y `config/template.yaml`
- `downloader.py` conectado al Pipeline
- `notebooks/01_exploracion.ipynb` publicado

---

## Fase 2 — Preprocesado e índices espectrales

**Semana 2 · ~10 horas**
Objetivo: pipeline de preprocesado modular y documentado. Índices espectrales
calculados como funciones independientes y testeadas. Primeras visualizaciones
de calidad para el README.

### 2.1 Máscara de nubes y recorte

- [ ] Implementar `preprocessor.py`: función `mask_clouds(scene, max_cloud_pct)` usando la capa SCL (Scene Classification Layer) del L2A para enmascarar nubes, sombras de nubes y agua
- [ ] Implementar `clip_to_bbox(scene, bbox)` que recorta la escena al bbox del config
- [ ] Aplicar ambas funciones en secuencia sobre las escenas descargadas
- [ ] Verificar visualmente que la máscara elimina las nubes sin destruir datos válidos
- [ ] Conectar `preprocessor.py` a `Pipeline.preprocess()`

### 2.2 Módulo de índices espectrales

- [ ] Crear `src/indices.py`
- [ ] Implementar `ndvi(nir, red)` — Normalized Difference Vegetation Index: `(NIR - Red) / (NIR + Red)`
- [ ] Implementar `ndwi(green, nir)` — Normalized Difference Water Index: `(Green - NIR) / (Green + NIR)`
- [ ] Implementar `mndwi(green, swir)` — Modified NDWI para agua superficial: `(Green - SWIR) / (Green + SWIR)`
- [ ] Cada función tiene docstring con: fórmula, bandas Sentinel-2 usadas (B0X), rango de valores, interpretación física
- [ ] Implementar `calculate_indices(scene, index_list)` que lee la lista de índices del config y llama a las funciones correspondientes
- [ ] Escribir tests unitarios en `tests/test_indices.py` con arrays sintéticos (input conocido → output verificable)
- [ ] Conectar `indices.py` a `Pipeline.preprocess()`

> **Analogía astrofísica para el README:** La corrección atmosférica (L1C → L2A)
> es equivalente a la corrección telúrica en espectroscopía astronómica: eliminar
> la huella del medio entre la fuente y el detector. El NDVI es un cociente de
> bandas, exactamente como los índices de color estelares (B-V, J-H).

### 2.3 Visualizaciones científicas de los índices

- [ ] Mapa de NDVI con paleta divergente (`RdYlGn`) y barra de color
- [ ] Mapa de NDWI con paleta secuencial (`Blues`)
- [ ] Mapa de MNDWI sobre la zona litoral
- [ ] Añadir título, barra de escala y fuente ("Sentinel-2, ESA / Pipeline propio")
- [ ] Exportar a `/figures/indices_costa_vasca.png` en alta resolución (300 dpi)
- [ ] Añadir visualizaciones al `notebooks/02_clasificador.ipynb`

**Entregables de F2:**

- `src/preprocessor.py` con `mask_clouds()` y `clip_to_bbox()`
- `src/indices.py` con NDVI, NDWI, MNDWI y tests
- `Pipeline.preprocess()` funcional
- Figuras de índices exportadas a `/figures/`

---

## Fase 3 — Clasificador de cobertura terrestre

**Semana 3 · ~10 horas**
Objetivo: clasificador Random Forest sobre 7 bandas + 3 índices. 4 clases de
cobertura. Evaluación rigurosa con separación espacial. Mapa de clasificación
y análisis de errores documentado.

### 3.1 Etiquetado de muestras

- [ ] Abrir QGIS con la imagen Sentinel-2 de la zona de estudio
- [ ] Crear capa vectorial con 4 clases: `agua`, `vegetacion`, `urbano`, `litoral`
- [ ] Etiquetar mínimo 50 puntos por clase en zonas sin ambigüedad espectral
- [ ] Priorizar zonas con firmas espectrales claras — evitar píxeles en bordes o zonas mixtas en esta primera versión
- [ ] Exportar a `data/labels/costa_vasca_labels.geojson`
- [ ] Documentar brevemente el criterio de etiquetado en un comentario del notebook: qué zonas se etiquetaron y por qué

> **Nota metodológica para el README:** Documentar que las clases ambiguas
> (transición litoral-vegetación, zonas inundadas periódicamente) se dejan fuera
> del entrenamiento en v1 para mantener la pureza espectral de las muestras.
> Esto es rigor científico, no limitación.

### 3.2 Extracción de features y entrenamiento

- [ ] Implementar `classifier.py`: función `extract_features(scene, labels_path)` que extrae el vector de 10 features (7 bandas + 3 índices) para cada punto etiquetado
- [ ] Implementar separación train/test **espacialmente estratificada**: dividir el área de estudio en bloques espaciales y asignar bloques completos a train o test — no mezclar píxeles adyacentes entre train y test
- [ ] Entrenar `RandomForestClassifier` de scikit-learn con los features de train
- [ ] Evaluar sobre el conjunto de test:
  - [ ] Accuracy global
  - [ ] F1-score por clase (weighted y macro)
  - [ ] Matriz de confusión
- [ ] Guardar el modelo entrenado con `joblib.dump()` en `data/models/rf_costa_vasca.joblib`
- [ ] Conectar `classifier.py` a `Pipeline.classify()`

### 3.3 Mapa de clasificación y análisis de errores

- [ ] Aplicar el modelo a la imagen completa píxel a píxel
- [ ] Generar mapa de clasificación con colores diferenciados por clase
- [ ] Identificar las 2-3 zonas donde el modelo comete más errores
- [ ] Documentar en el notebook la causa física de cada error (p. ej. "el modelo confunde arena húmeda con zona urbana porque tienen NDVI similar negativo")
- [ ] Exportar mapa a `/figures/clasificacion_costa_vasca.png`

**Entregables de F3:**

- `src/classifier.py` con extracción de features, entrenamiento y predicción
- Modelo RF serializado en `data/models/`
- `notebooks/02_clasificador.ipynb` con métricas y análisis de errores
- Mapa de clasificación exportado

---

## Fase 4 — Detector de anomalías temporales (v1 simple)

**Semana 4 · ~10 horas**
Objetivo: serie temporal de 12 meses de NDVI. Detector estadístico simple
(media ± 2σ por mes). Eventos anómalos anotados. Segunda demo con Urdaibai
para demostrar que el pipeline es realmente parametrizable.

### 4.1 Serie temporal de índices

- [ ] Descargar todas las escenas válidas (< 20% nubes) de los últimos 12 meses para la costa vasca
- [ ] Para cada escena válida: aplicar preprocesado (máscara + recorte) y calcular NDVI medio por zona de estudio
- [ ] Construir DataFrame con columnas `fecha`, `ndvi_medio`, `ndwi_medio`, `n_pixels_validos`
- [ ] Guardar en `data/processed/timeseries_costa_vasca.csv`
- [ ] Implementar `build_timeseries(config)` en `anomaly_detector.py`
- [ ] Visualizar la serie temporal bruta antes de aplicar el detector

> **Si hay pocas escenas válidas por nubes:** documentarlo como limitación real
> de operar LUR-1 en el País Vasco. Ampliar el bbox o reducir el umbral de
> cobertura nubosa a 30% si es necesario para tener al menos 8-10 escenas.

### 4.2 Detector estadístico

- [ ] Para cada mes del año, calcular media y desviación estándar del NDVI usando todos los valores disponibles
- [ ] Implementar `detect_anomalies(timeseries, config)`: marcar como anomalía todo valor que supere `media ± threshold_sigma` del mes correspondiente
- [ ] El umbral `threshold_sigma` se lee del config.yaml (por defecto 2.0)
- [ ] Devolver DataFrame con columna `is_anomaly` (bool) y `anomaly_score` (distancia a la media en sigmas)
- [ ] Verificar que el detector funciona con un caso sintético simple antes de aplicarlo a los datos reales

### 4.3 Anotación de eventos

- [ ] Para cada fecha marcada como anomalía, buscar qué evento físico real la explica:
  - [ ] Consultar registros meteorológicos de la AEMET para la zona y periodo
  - [ ] Revisar noticias de sequías, inundaciones, proliferación de algas en el litoral vasco
  - [ ] Si no hay explicación identificable, documentarlo como "artefacto candidato" con la hipótesis más probable
- [ ] Guardar anotaciones en `data/events/anomalies_annotated.csv` con columnas: `fecha`, `ndvi_medio`, `anomaly_score`, `evento`, `fuente`, `notas`

### 4.4 Visualización de la serie temporal

- [ ] Gráfico de línea de NDVI a lo largo del año
- [ ] Banda de confianza (media ± 2σ) sombreada en gris
- [ ] Puntos anómalos marcados en rojo con etiqueta del evento
- [ ] Eje X con fechas legibles, eje Y con escala de NDVI (-1 a 1)
- [ ] Exportar a `/figures/timeseries_anomalias_costa_vasca.png`
- [ ] Crear `notebooks/03_anomalias.ipynb` con el análisis completo
- [ ] Conectar `anomaly_detector.py` a `Pipeline.detect_anomalies()`

### 4.5 Segunda demo — Urdaibai

- [ ] Crear `config/urdaibai.yaml` con el bbox de la ría de Urdaibai
- [ ] Ejecutar `make run CONFIG=config/urdaibai.yaml` y verificar que el pipeline completo corre sin modificar código
- [ ] Exportar las figuras de Urdaibai a `/figures/`
- [ ] Añadir comparativa de resultados entre las dos zonas en el README

**Entregables de F4:**

- `src/anomaly_detector.py` con `build_timeseries()` y `detect_anomalies()`
- `data/processed/timeseries_costa_vasca.csv`
- `data/events/anomalies_annotated.csv`
- Figura de serie temporal con anomalías marcadas
- `config/urdaibai.yaml` + segunda demo funcional
- `Pipeline.detect_anomalies()` conectado

---

## Fase 5 — Presentación científica del proyecto

**Semana 5 · ~10 horas**
Objetivo: README que cuenta la historia completa. Notebook demo ejecutable en
5 minutos. Nota técnica de una página para adjuntar a la candidatura de AVS.

### 5.1 README científico

- [ ] Sección 1 — Motivación: qué hace LUR-1, por qué este pipeline es directamente aplicable, quiénes son los clientes (Azti, Hazi)
- [ ] Sección 2 — Analogía científica: reducción de datos astronómicos vs pipeline de teledetección (corrección telúrica = corrección atmosférica, índices de color = índices espectrales)
- [ ] Sección 3 — Arquitectura: el config.yaml como interfaz, estructura del repo, cómo ejecutar
- [ ] Sección 4 — Resultados en costa vasca: mapa de clasificación, métricas del RF, serie temporal con anomalías anotadas
- [ ] Sección 5 — Resultados en Urdaibai: comparativa breve con la primera zona
- [ ] Sección 6 — Limitaciones y diferencias con LUR-1: resolución 10 m (Sentinel-2) vs 1,5 m (LUR-1), qué habría que adaptar en el pipeline real
- [ ] Sección 7 — Trabajo futuro (v2): Isolation Forest, CNN espectral, tercera ubicación fuera del País Vasco, CLI con argparse
- [ ] Añadir todas las figuras de `/figures/` en las secciones correspondientes

### 5.2 Notebook demo ejecutable

- [ ] Crear `notebooks/00_demo.ipynb`
- [ ] El notebook carga `config/costa_vasca.yaml`, ejecuta `Pipeline.run_full()` y genera las 3 figuras principales en menos de 5 minutos
- [ ] Incluir una escena de ejemplo pre-descargada y cacheada en el repo (escena pequeña recortada al bbox) para que funcione sin credenciales de Copernicus
- [ ] Instrucciones de instalación de 3 pasos al inicio del README:
  ```
  git clone https://github.com/tuusuario/lur1-analysis-pipeline
  conda env create -f environment.yml
  jupyter notebook notebooks/00_demo.ipynb
  ```
- [ ] Verificar que un usuario nuevo puede ejecutarlo desde cero

### 5.3 Nota técnica de una página para AVS

- [ ] Crear `project_summary.pdf` (una página, formato limpio)
- [ ] Contenido: título del proyecto, qué hace el sistema en dos frases, métricas del clasificador (F1 global), los dos eventos anómalos más interesantes detectados, diferencias con LUR-1 y cómo escalaría, enlace al repositorio GitHub
- [ ] Tono: nota técnica, no CV — habla del sistema, no de ti
- [ ] Este documento va adjunto al email de candidatura a AVS, no el README

**Entregables de F5:**

- `README.md` científico completo con figuras
- `notebooks/00_demo.ipynb` ejecutable sin configuración
- `/figures/` con todas las visualizaciones en alta resolución
- `project_summary.pdf` listo para adjuntar

---

## Versiones del proyecto

### v1 — Candidable (estas 5 semanas)

| Componente   | Implementación                                               |
| ------------ | ------------------------------------------------------------- |
| Pipeline     | Parametrizable por config.yaml · dos ubicaciones demo        |
| Clasificador | Random Forest · 4 clases · métricas documentadas           |
| Anomalías   | Detector estadístico (media ± 2σ) · eventos anotados      |
| Docs         | README científico · demo ejecutable · PDF para candidatura |

### v2 — Expansión (tras primera entrevista)

| Componente   | Qué añadir                                                          |
| ------------ | --------------------------------------------------------------------- |
| Anomalías   | Isolation Forest como segundo método · comparativa con estadístico |
| Clasificador | CNN 1D espectral · comparativa con RF                                |
| Spatial      | Mapa de distribución espacial de anomalías por zona                 |
| Datos        | Tercera ubicación fuera del País Vasco                              |
| CLI          | `argparse` para ejecutar desde terminal sin tocar Python            |
| Descarga     | Modo interactivo: mostrar escenas disponibles y elegir cuáles descargar |

> **Nota de diseño:** El `config.yaml` ya tiene los campos `method: "isolation_forest"`
> y `model: "cnn"` aunque no estén implementados en v1. Cuando llegue el momento,
> solo hay que añadir la función — la arquitectura ya lo contempla.

---

## Riesgos conocidos

| Riesgo                              | Probabilidad | Solución                                                                   |
| ----------------------------------- | ------------ | --------------------------------------------------------------------------- |
| Dependencias GDAL en Windows        | Alta         | Usar conda-forge o WSL2/Linux                                               |
| Pocas escenas válidas por nubes    | Media        | Ampliar bbox o subir umbral a 30% de nubosidad                              |
| Etiquetado lento en QGIS            | Media        | Empezar por clases espectralmente muy distintas (agua vs urbano)            |
| Sen2Cor lento                       | Baja         | Usar L2A directamente desde Copernicus Hub (ya está resuelto en este plan) |
| CNN consume toda la semana          | Baja         | Opcional en v1 — el RF ya es suficiente                                    |
| Anomalías sin explicación física | Media        | Documentar honestamente como "artefacto candidato"                          |

---

## Conexión con LUR-1 — argumentos para la entrevista

- **El pipeline es directamente aplicable a LUR-1.** Sentinel-2 tiene 10 m de resolución vs 1,5 m de LUR-1. La física es la misma, la escala cambia. En la entrevista: "el pipeline escala bien — mayor resolución implica mayor demanda computacional y corrección geométrica más exigente, pero los módulos de índices y detección son agnósticos a la resolución."
- **La arquitectura parametrizable es lo que necesita AVS.** AVS opera LUR-1 para clientes globales (Azti, Hazi, y mercado comercial internacional). Un sistema donde cambiar de cliente es solo cambiar el config.yaml es exactamente la herramienta que necesitan.
- **La analogía astrofísica es el argumento científico.** En la entrevista: "la reducción de datos de detector CCD en astrofísica y la calibración de imagen satelital son el mismo problema físico. Corrección de dark current, flat-field, efectos sistemáticos del detector — lo que cambia es que aquí el objeto es la Tierra."
- **Los eventos anotados demuestran criterio científico.** Cualquier data scientist puede entrenar un modelo. Lo que distingue a alguien con formación física es que puede decir "este pico en el NDVI de agosto corresponde a la ola de calor del día X según los registros de la AEMET, y este descenso en marzo es consistente con las inundaciones de la ría reportadas en prensa."
