# LUR1-ANALYSIS

Pipeline de detección de anomalías en imagen satelital multiespectral, parametrizable
por ubicación. Le das un bounding box y un rango de fechas, y te devuelve **en qué días
la zona se comportó de forma anómala** para que investigues qué ocurrió.

Inspirado en la misión LUR-1 de [AVS (Added Value Solutions)](https://www.avs-added-value.com/).

## Qué hace

Recibe un único fichero YAML con una ubicación y ejecuta la cadena completa:

1. **Descarga** escenas Sentinel-2 L2A del [Copernicus Data Space](https://dataspace.copernicus.eu/)
   que intersecan el bounding box en el rango de fechas indicado, saltando las que ya
   tengan su `.SAFE` extraída.
2. **Extrae** cada `.zip`, de uno en uno: valida que no esté corrupto antes de
   descomprimirlo, comprueba que el `.SAFE` resultante tiene las bandas esperadas y solo
   entonces borra el `.zip` — así el disco no se llena de zips que ya no hacen falta. Si la
   verificación falla en cualquiera de los dos puntos, conserva el `.zip` (o lo pide de
   nuevo) para poder reintentar en la siguiente ejecución.
3. **Preprocesa** cada escena: máscara de nubes con la banda SCL, recorte al bbox y
   remuestreo de todas las bandas a 10 m.
4. **Calcula índices espectrales** (NDVI, NDWI, MNDWI) y construye una serie temporal.
5. **Detecta anomalías** comparando cada escena con su climatología estacional.
6. **Clasifica** la cobertura de las escenas anómalas con un Random Forest, para saber de
   qué está compuesta cada anomalía.

La salida es una lista de fechas con el índice que las dispara y su z-score:

```
==============================================================
RESULTADO — Costa vasca — Zarautz a Donostia
==============================================================
5 fecha(s) anómala(s) por encima de 2.0σ:

  2024-10-04   NDVI z=-4.21, NDWI z=+4.59, MNDWI z=+3.92
  2025-01-27   NDVI z=+2.57, NDWI z=-2.36, MNDWI z=-2.40
  2025-02-06   NDWI z=+2.07, MNDWI z=+2.05
  2025-04-09   NDWI z=-2.21, MNDWI z=-3.07
  2025-07-11   NDVI z=-4.31, NDWI z=+5.72, MNDWI z=+4.01

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

No hace falta entrenar nada: el repositorio incluye el clasificador ya entrenado
(`data/models/production/rf_prod.joblib`, 420 KB).

### Espacio en disco

Sentinel-2 pesa: cada escena `.zip` ronda 1-1.6 GB, y una serie de 2 años sobre un tile
completo son cerca de **100 escenas** (99 en nuestras pruebas). Sin limpieza de zips,
`data/raw/` llegó a **165 GB**; con la limpieza automática (ver más abajo) el mismo conjunto
se queda en **~80 GB** una vez extraído todo — el pico sigue siendo el momento de la
descarga, antes de que `extract` borre los zips. Antes de lanzar una descarga larga:

```bash
df -h .
```

Ten en cuenta:

- `data/raw/` se comparte entre zonas — si ya descargaste una zona sobre el mismo tile, las
  demás reutilizan las mismas escenas sin volver a ocupar espacio
- reduce el rango de `dates` en el YAML si solo quieres probar el pipeline (con 2-3 meses
  basta para validar que todo funciona)
- el paso `extract` borra cada `.zip` justo después de descomprimirlo **y comprobar que el
  `.SAFE` resultante tiene las bandas esperadas** (también limpia los zips sueltos que
  queden de escenas ya extraídas antes de este cambio) — el `.SAFE` ya tiene todo lo
  necesario para el resto del pipeline, así que en la práctica el espacio se queda en la
  mitad una vez extraído todo. Si la verificación falla, el `.zip` no se borra y la escena
  queda marcada para reintentar en la siguiente ejecución
- una descarga posterior no vuelve a traer una escena si ya existe su `.SAFE` validado,
  aunque el `.zip` ya no esté

### Credenciales de Copernicus

Descargar escenas requiere una cuenta gratuita en
[Copernicus Data Space](https://dataspace.copernicus.eu/). El pipeline las lee de dos
variables de entorno, `CDSE_USER` y `CDSE_PASSWORD` — las credenciales de acceso a la web,
no un token de API.

**Solo para esta sesión de terminal** (bash/zsh en WSL2 o Linux, que es donde se ejecuta el
pipeline):

```bash
export CDSE_USER="tu_usuario@email.com"
export CDSE_PASSWORD="tu_contraseña"
```

**Para no repetirlo cada vez**, añádelas a tu perfil de shell con este bloque (detecta si
usas bash o zsh y las deja ya exportadas):

```bash
PROFILE=$( [ -n "$ZSH_VERSION" ] && echo ~/.zshrc || echo ~/.bashrc )
cat >> "$PROFILE" <<'EOF'
export CDSE_USER="tu_usuario@email.com"
export CDSE_PASSWORD="tu_contraseña"
EOF
source "$PROFILE"
```

Edita `tu_usuario@email.com` y `tu_contraseña` antes de pegarlo, o hazlo después directamente
en el fichero. Si prefieres no dejar la contraseña en texto plano en el perfil, usa un
gestor de secretos en su lugar.

Si las exportas en una terminal distinta de la que lanza el pipeline, no se heredan: las
variables de entorno solo pasan a los procesos hijos. Y si trabajas desde PowerShell en
Windows, esto no aplica ahí — las credenciales se definen dentro de la sesión de WSL2/Linux
donde corres el pipeline, no en PowerShell.

Los pasos que no descargan (`extract`, `timeseries`, `anomalies`, `classify`) funcionan sin
credenciales, así que puedes reprocesar datos ya descargados sin configurarlas.

Si falla la descarga de alguna escena, el pipeline se detiene ahí (para no calcular
anomalías sobre un conjunto incompleto sin que se note). Vuelve a lanzarlo — las escenas ya
descargadas se saltan — o usa `--allow-partial` para continuar a propósito con lo que sí se
descargó.

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

Esto entrena y guarda en `data/models/rf_mi_zona.joblib` — nunca toca
`data/models/production/`, que es lo que usa el pipeline para clasificar. Es una zona de
pruebas: entrena, evalúa las métricas y, si el modelo te convence, cópialo tú mismo a
`data/models/production/` para que el pipeline empiece a usarlo:

```bash
cp data/models/rf_mi_zona.joblib data/models/production/rf_mi_zona.joblib
```

Y apunta el config a él con `classifier.model_name: "rf_mi_zona"`.

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
│   ├── models/
│   │   └── production/rf_prod.joblib  # el que usa el pipeline (incluido, versionado)
│   │       # modelos sueltos en data/models/ (fuera de production/) son zona de
│   │       # pruebas del notebook/CLI de entrenamiento, no versionados
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

| Índice | Fórmula                   | Detecta                              |
| ------- | -------------------------- | ------------------------------------ |
| NDVI    | (B08 − B04) / (B08 + B04) | Vigor de la vegetación              |
| NDWI    | (B03 − B08) / (B03 + B08) | Contenido hídrico de la vegetación |
| MNDWI   | (B03 − B11) / (B03 + B11) | Láminas de agua superficial         |

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

| Parámetro                           | Descripción                                                   |
| ------------------------------------ | -------------------------------------------------------------- |
| `location.bbox`                    | `[lon_min, lat_min, lon_max, lat_max]` en WGS84              |
| `dates.start` / `end`            | Rango temporal, ambas inclusivas                               |
| `satellite.max_cloud_pct`          | Nubosidad máxima de la**escena completa**, al descargar |
| `satellite.tile`                   | Opcional. El bbox ya filtra; úsalo si cruza varios tiles      |
| `processing.max_bbox_cloud_pct`    | Nubosidad máxima**dentro del bbox** ya recortado        |
| `processing.min_ref_scenes`        | Escenas de referencia mínimas para evaluar una escena         |
| `classifier.model_name`            | Qué modelo de`data/models/production/` usa el pipeline      |
| `anomaly_detector.window_days`     | Anchura de la ventana estacional (±días)                     |
| `anomaly_detector.threshold_sigma` | Umbral en sigmas                                               |

Los dos filtros de nubes son distintos y complementarios: una escena puede estar muy nublada
en global y despejada justo sobre tu zona.

## Zonas de estudio

Tres zonas de la costa vasca, las tres bajo el tile Sentinel-2 `T30TWN`, con datos de
2024–2025:

| Zona                                | Escenas del catálogo | Escenas válidas | Anomalías (2.0σ) | Referencias por escena |
| ----------------------------------- | --------------------- | ---------------- | ------------------ | ---------------------- |
| Costa Vasca (Zarautz–Donostia)     | 49                    | 41               | 5                  | 10 de media            |
| Ría del Nervión (Bilbao)          | 98                    | 84               | 7                  | 22 de media            |
| Ría de Urdaibai (Gernika–Mundaka) | 98                    | 83               | 9                  | 21 de media            |

Resultados verificados ejecutando el pipeline de cero: descarga de las tres zonas desde el
catálogo, sin ningún dato local previo. Coinciden fecha a fecha y z-score a z-score con la
ejecución original.

Costa Vasca tiene la mitad de escenas que las otras dos por geometría orbital, no por
nubosidad. El tile `T30TWN` lo cubren dos órbitas, R094 y R137, pero en R137 el tile queda al
borde del swath: esos productos llevan la etiqueta del tile y no contienen datos sobre el
extremo oriental, donde cae el bbox de Costa Vasca. Los bboxes de Nervión y Urdaibai, más al
oeste, sí quedan dentro de ambas órbitas.

El filtro por bbox de la búsqueda descarta esos productos antes de descargarlos. Una vez
descontados, el porcentaje de escenas que se pierden por nubes es prácticamente el mismo en
las tres zonas (~15 %).

### Fechas anómalas y contraste meteorológico

Las 21 fechas están contrastadas con boletines de Euskalmet y resúmenes de AEMET, con un
marcador de confianza por fecha: 🟢 evento confirmado con fuente numérica · 🟡 mecanismo
plausible sin evento puntual con nombre · 🔴 sin explicación sólida (declarado así en vez de
forzar una narrativa). Interpretación completa, con fuentes y mecanismo, en el notebook de
cada zona.

**Costa Vasca — Zarautz a Donostia** ([`04_anomalias_Donostia.ipynb`](notebooks/04_anomalias_Donostia.ipynb))

| Fecha      | z-scores                              |    |
| ---------- | ------------------------------------- | -- |
| 2024-10-04 | NDVI −4.21, NDWI +4.59, MNDWI +3.92  | 🟡 |
| 2025-01-27 | NDVI +2.57, NDWI −2.36, MNDWI −2.40 | 🟢 |
| 2025-02-06 | NDWI +2.07, MNDWI +2.05               | 🟡 |
| 2025-04-09 | NDWI −2.21, MNDWI −3.07             | 🔴 |
| 2025-07-11 | NDVI −4.31, NDWI +5.72, MNDWI +4.01  | 🟢 |

**Ría del Nervión — Bilbao y alrededores** ([`04_anomalias_Nervion.ipynb`](notebooks/04_anomalias_Nervion.ipynb))

| Fecha      | z-scores                             |    |
| ---------- | ------------------------------------ | -- |
| 2024-06-26 | MNDWI +2.35                          | 🟢 |
| 2024-08-28 | NDWI +2.48, MNDWI +4.07              | 🟢 |
| 2024-09-14 | NDVI +2.14, NDWI −2.06              | 🟡 |
| 2025-01-15 | MNDWI +2.79                          | 🔴 |
| 2025-05-17 | NDVI +2.03                           | 🟡 |
| 2025-07-04 | NDVI −3.42, NDWI +4.18, MNDWI +3.10 | 🟡 |
| 2025-10-14 | NDVI −2.56, NDWI +3.67, MNDWI +2.86 | 🟢 |

**Ría de Urdaibai — Gernika, Mundaka, Bermeo** ([`04_anomalias_Urdaibai.ipynb`](notebooks/04_anomalias_Urdaibai.ipynb))

| Fecha      | z-scores                |    |
| ---------- | ----------------------- | -- |
| 2024-04-10 | MNDWI +2.56             | 🟡 |
| 2024-09-14 | NDVI +2.26, NDWI −2.19 | 🟢 |
| 2025-01-15 | NDVI −2.51, NDWI +2.47 | 🔴 |
| 2025-01-27 | MNDWI −2.10            | 🟡 |
| 2025-02-14 | NDVI −2.77, NDWI +2.81 | 🟢 |
| 2025-06-09 | MNDWI +2.65             | 🔴 |
| 2025-08-03 | MNDWI +3.01             | 🟢 |
| 2025-08-23 | NDWI +2.37, MNDWI +2.11 | 🟢 |
| 2025-10-14 | NDWI +2.14              | 🟡 |

**Total: 21 fechas · 9 🟢 evento confirmado · 8 🟡 mecanismo plausible · 4 🔴 sin explicación
sólida.** Tres fechas comparten escena exacta entre dos zonas (mismo satélite, mismo día,
tile `T30TWN`), lo que permite corroborar o contrastar el mecanismo de forma cruzada:
2024-09-14 (Nervión/Urdaibai), 2025-01-15 (Nervión/Urdaibai) y 2025-01-27 (Costa
Vasca/Urdaibai). El hallazgo más notable es un mecanismo puramente astronómico en Urdaibai
(2025-08-03): la anomalía más fuerte de las 21 fechas no tiene causa meteorológica, sino que
la escena se tomó a los pocos minutos de la pleamar.

> **Estado:** las 21 fechas y sus z-scores están verificados campo a campo contra
> `anomalies.csv` (13 agosto 2026), tras una revisión de código que corrigió un sesgo de
> calendario en el detector (años bisiestos) y otros seis hallazgos menores — ver
> `plan_LUR1.md` / `documentacion.md` para el detalle.

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
