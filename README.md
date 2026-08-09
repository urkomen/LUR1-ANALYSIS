# LUR1-ANALYSIS

Pipeline de detección de anomalías en imagen satelital multiespectral, parametrizable
por ubicación. Le das un bounding box y un rango de fechas, y te devuelve **en qué días
la zona se comportó de forma anómala** para que investigues qué ocurrió.

Inspirado en la misión LUR-1 de [AVS (Added Value Solutions)](https://www.avs-added-value.com/).

## Qué hace

Recibe un único fichero YAML con una ubicación y ejecuta la cadena completa:

1. **Descarga** escenas Sentinel-2 L2A del [Copernicus Data Space](https://dataspace.copernicus.eu/)
   que intersecan el bounding box en el rango de fechas indicado.
2. **Extrae** los `.zip` descargados, validándolos antes (una descarga interrumpida deja un
   fichero truncado que fallaría mucho más tarde).
3. **Preprocesa** cada escena: máscara de nubes con la banda SCL, recorte al bbox y
   remuestreo de todas las bandas a 10 m.
4. **Calcula índices espectrales** (NDVI, NDWI, MNDWI) y construye una serie temporal.
5. **Detecta anomalías** comparando cada escena con su climatología estacional.
6. **Clasifica** la cobertura de las escenas anómalas con un Random Forest, para saber de
   qué está compuesta cada anomalía.

La salida es una lista de fechas con el índice que las dispara y su z-score:

```
==============================================================
RESULTADO — Ría del Nervión — Bilbao y alrededores
==============================================================
7 fecha(s) anómala(s) por encima de 2.0σ:

  2024-06-26   MNDWI z=+2.35
  2024-08-28   NDWI z=+2.48, MNDWI z=+4.07
  2025-07-04   NDVI z=-3.42, NDWI z=+4.18, MNDWI z=+3.10
  ...

Contrasta estas fechas con registros meteorológicos para
identificar qué evento las provocó.
```

Cambiar de zona, de fechas o de umbral no requiere tocar código: solo editar el YAML.

## Instalación

Requiere **WSL2 (Ubuntu) en Windows, o Linux nativo**. Las dependencias geoespaciales
(GDAL, rasterio) no funcionan bien en el Python nativo de Windows.

```bash
git clone https://github.com/urkomen/lur1-analysis.git
cd lur1-analysis
conda env create -f environment.yml
conda activate lur1
```

Para descargar escenas necesitas una cuenta gratuita en
[Copernicus Data Space](https://dataspace.copernicus.eu/):

```bash
export CDSE_USER="tu_usuario@email.com"
export CDSE_PASSWORD="tu_contraseña"
```

> Guárdalas en un `.env` o en un gestor de secretos, no en el `.bashrc`.

No hace falta entrenar nada: el repositorio incluye el clasificador ya entrenado
(`data/models/rf.joblib`, 420 KB).

## Uso

### Una zona ya configurada

```bash
make run CONFIG=config/costa_vasca.yaml
```

### Una zona nueva

Copia `config/template.yaml`, rellena `location.bbox` y `dates`, y ejecuta:

```bash
make run CONFIG=config/mi_zona.yaml
```

El nombre del fichero define la zona: `mi_zona.yaml` escribe en `data/processed/mi_zona/`.

### Reejecutar fases sueltas

El pipeline se compone de cinco pasos (`download`, `extract`, `timeseries`, `anomalies`,
`classify`) y puedes ejecutar solo los que necesites:

```bash
make reprocess CONFIG=config/mi_zona.yaml   # sin volver a descargar
make anomalies CONFIG=config/mi_zona.yaml   # solo redetectar, p. ej. con otro umbral
python src/pipeline.py --config config/mi_zona.yaml --steps timeseries anomalies
```

### Figuras de las escenas anómalas

```bash
make figures CONFIG=config/mi_zona.yaml
```

Genera en `figures/{zona}/` una comparación RGB visible + clasificación y otra
RGB + falso color NIR de cada escena anómala.

### Entrenar tu propio clasificador (opcional)

Solo si quieres uno adaptado a tu zona. Necesitas etiquetas manuales en GeoJSON
(puntos con una columna `etiquetas`, creados en QGIS sobre una escena de referencia):

```bash
python src/classifier.py --config config/mi_zona.yaml --name rf_mi_zona
```

Y después apunta a él con `classifier.model_name: "rf_mi_zona"` en el YAML. El modelo
del repositorio no se toca salvo que uses `--force`.

## Estructura

```
lur1-analysis/
├── config/
│   ├── template.yaml           # plantilla comentada para zonas nuevas
│   ├── costa_vasca.yaml        # zona 1 — la única con etiquetas manuales
│   ├── nervion.yaml            # zona 2
│   └── urdaibai.yaml           # zona 3
├── src/
│   ├── pipeline.py             # orquestador: run(steps)
│   ├── paths.py                # rutas por zona, manifiestos, opciones
│   ├── downloader.py           # búsqueda OData por bbox + descarga
│   ├── extractor.py            # .zip → .SAFE con validación
│   ├── preprocessor.py         # máscara de nubes (SCL) + recorte
│   ├── indices.py              # NDVI, NDWI, MNDWI
│   ├── timeseries.py           # serie temporal + climatología
│   ├── classifier.py           # Random Forest: entrenar / cargar / aplicar
│   └── anomaly_detector.py     # z-score estacional con leave-one-out
├── data/
│   ├── models/rf.joblib        # clasificador entrenado (incluido)
│   ├── labels/                 # etiquetas QGIS + estilo y proyecto para reentrenar
│   ├── raw/                    # escenas descargadas (no versionado)
│   └── processed/{zona}/       # resultados por zona (no versionado)
├── run_visualizations.py
├── environment.yml
└── Makefile
```

Las escenas y los resultados no se versionan por tamaño; se regeneran ejecutando el
pipeline. `data/raw/` **se comparte entre zonas a propósito**: el nombre de escena
Sentinel-2 es un identificador único global, así que dos zonas sobre el mismo tile
reutilizan el mismo fichero en vez de duplicar decenas de GB. Qué escenas pertenecen a
cada zona lo resuelve el `manifest.txt` de la zona.

## Cómo funciona

### Preprocesado

Cada escena L2A trae una banda SCL (Scene Classification Layer) que etiqueta cada píxel.
Se enmascaran como `NaN` los píxeles sin datos, saturados, de sombra de nube, nube media,
nube alta y cirrus (clases SCL 0, 1, 3, 8, 9, 10). Después se recorta al bbox y se
remuestrean las bandas de 20 m (B05, B11, B12) a 10 m.

### Índices espectrales

| Índice | Fórmula | Detecta |
|--------|---------|---------|
| NDVI | (B08 − B04) / (B08 + B04) | Vigor de la vegetación |
| NDWI | (B03 − B08) / (B03 + B08) | Contenido hídrico de la vegetación |
| MNDWI | (B03 − B11) / (B03 + B11) | Láminas de agua superficial |

### Detección de anomalías

Para cada escena se calcula el z-score de cada índice frente a su **climatología
estacional**: las escenas que caen dentro de una ventana de ±`window_days` alrededor de su
día del año, agrupando todos los años disponibles.

Dos detalles que importan más de lo que parece:

**La escena se excluye de su propia referencia** (leave-one-out). Si una escena entra en la
muestra que calcula su propia media y σ, arrastra la referencia hacia sí misma y aparece un
techo de `|z| = (n−1)/√n`. Con 2 escenas de referencia ese techo es 0.71σ y con 4 es
exactamente 1.5σ: grupos pequeños serían incapaces de superar el umbral por aritmética, no
por ausencia de eventos.

**La ventana es estacional, no mensual.** Agrupar por mes natural con dos años de datos deja
2-5 escenas por grupo, muestra con la que una desviación típica no significa nada. La ventana
reúne 10-25 escenas usando exactamente los mismos datos, y evita el corte artificial por el
que el 31 de julio y el 1 de agosto se comparaban contra poblaciones distintas.

`window_days: 45` es un compromiso: ventanas más estrechas comparan contra fenología más
parecida pero reúnen pocas escenas; más anchas estabilizan la σ pero mezclan estados de
vegetación distintos y diluyen las anomalías reales.

### Clasificador

Random Forest de 200 árboles sobre 10 features (7 bandas + 3 índices), entrenado con
etiquetas manuales de QGIS sobre una escena de referencia, con split train/test por **bloques
espaciales de 500 m** en lugar de por píxeles: píxeles vecinos son casi idénticos por
autocorrelación espacial, y repartirlos entre train y test infla las métricas artificialmente.

El modelo es **global**: se entrena una vez y se reutiliza en todas las zonas. Solo se aplica
a las escenas anómalas, que son las que interesan.

## Configuración

Todo se parametriza desde el YAML. Ver `config/template.yaml` para la plantilla comentada.

| Parámetro | Descripción |
|---|---|
| `location.bbox` | `[lon_min, lat_min, lon_max, lat_max]` en WGS84 |
| `dates.start` / `end` | Rango temporal, ambas inclusivas |
| `satellite.max_cloud_pct` | Nubosidad máxima de la **escena completa**, al descargar |
| `satellite.tile` | Opcional. El bbox ya filtra; úsalo si cruza varios tiles |
| `processing.max_bbox_cloud_pct` | Nubosidad máxima **dentro del bbox** ya recortado |
| `processing.min_ref_scenes` | Escenas de referencia mínimas para evaluar una escena |
| `classifier.model_name` | Qué modelo de `data/models/` usar |
| `anomaly_detector.window_days` | Anchura de la ventana estacional (±días) |
| `anomaly_detector.threshold_sigma` | Umbral en sigmas |

Los dos filtros de nubes son distintos y complementarios: una escena puede estar muy nublada
en global y despejada justo sobre tu zona.

## Zonas de estudio

Tres zonas de la costa vasca, las tres bajo el tile Sentinel-2 `T30TWN`, con datos de
2024–2025 (99 escenas descargadas por zona):

| Zona | Escenas válidas | Anomalías (2.0σ) | Referencias por escena |
|------|-----------------|------------------|------------------------|
| Costa Vasca (Zarautz–Donostia) | 41 | 5 | 10 de media |
| Ría del Nervión (Bilbao) | 84 | 7 | 22 de media |
| Ría de Urdaibai (Gernika–Mundaka) | 83 | 9 | 21 de media |

Costa Vasca tiene menos escenas válidas porque su bbox es más pequeño y costero: más píxeles
de mar, donde la máscara SCL es más conservadora.

> **Estado:** cada fecha anómala se ha contrastado con los boletines climatológicos de
> Euskalmet y los resúmenes de AEMET para identificar el evento que la provocó. Ese análisis
> se hizo con una versión anterior del detector y **está siendo rehecho** con las fechas
> actuales; se publicará, junto con los notebooks que lo documentan, cuando esté terminado.

## Limitaciones

- **El clasificador solo tiene etiquetas de Costa Vasca.** Aplicado a otras zonas generaliza
  regular: en la ría del Nervión clasifica el agua del estuario como "litoral". Para
  resultados fiables fuera de la zona etiquetada, entrena tu propio modelo.
- **El detector no distingue causas.** Marca desviaciones respecto a la climatología, sea
  cual sea el motivo. Turbidez por sedimentos y sequía reducen ambas el MNDWI.
- **Dos años de datos son pocos** para una climatología robusta. La ventana estacional
  mitiga el problema pero no lo elimina: `anomalies.csv` incluye una columna `n_ref` con
  cuántas escenas de referencia tuvo cada evaluación, para poder juzgar su solidez.
- **Escenas muy nubosas pueden dar falsos positivos** por píxeles mal enmascarados.

## Tecnologías

Sentinel-2 L2A vía Copernicus Data Space · GDAL, rasterio, geopandas, pyproj, shapely ·
scikit-learn · matplotlib · Jupyter · conda (miniforge) sobre WSL2 Ubuntu · QGIS para el
etiquetado.

## Licencia

Proyecto académico / portfolio. Datos Sentinel-2 bajo licencia Copernicus (uso libre con
atribución).
