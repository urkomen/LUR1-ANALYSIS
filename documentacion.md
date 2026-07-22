# Documentación del proyecto LUR1-ANALYSIS

Pipeline de análisis de imagen satelital multiespectral parametrizable por ubicación.
Inspirado en la misión LUR-1 de AVS. Clasificador de cobertura terrestre + detector de anomalías temporales sobre series de 12 meses de Sentinel-2.

---

## Fase 1 — Entorno, estructura y exploración

### 1.1 Entorno reproducible

**Qué hicimos:** Instalamos Ubuntu en Windows mediante WSL2 y creamos un entorno conda con todas las dependencias geoespaciales del proyecto.

**Por qué:** Las librerías geoespaciales (GDAL, rasterio) están diseñadas para Linux y dan problemas frecuentes en Windows. WSL2 nos permite correr Linux dentro de Windows sin particiones ni reinicios. Conda gestiona las dependencias científicas de forma aislada, evitando conflictos entre proyectos.

**Decisiones que tomamos:**
- Optamos por WSL2 + Ubuntu 24.04 en lugar de instalación nativa en Windows — más estable para GDAL/rasterio
- Elegimos Miniforge (conda basado en conda-forge) en lugar de Anaconda — el canal conda-forge tiene mejor soporte para librerías geoespaciales
- Descartamos `sentinelsat` — la ESA migró a un nuevo sistema (CDSE) en 2023 y sentinelsat quedó obsoleto sin mantenimiento
- Descartamos `cdsetool` — tiene delays internos de 60 segundos entre peticiones, demasiado lento para uso práctico

**Cómo:** `conda env create -f environment.yml` recrea el entorno completo en cualquier máquina con un solo comando.

**Resultado:** Entorno `lur1` funcional. Verificamos con `import rasterio; import geopandas` → OK.

---

**Librerías principales instaladas:**

| Librería | Función en el proyecto |
|---|---|
| `rasterio` | Lectura y escritura de imágenes satelitales (GeoTIFF, JP2) |
| `GDAL` | Motor subyacente de procesado geoespacial |
| `geopandas` | Manejo de datos vectoriales (polígonos, puntos) |
| `xarray` | Series temporales de arrays multidimensionales |
| `scikit-learn` | Clasificador Random Forest y métricas de evaluación |
| `matplotlib` | Visualización de imágenes y gráficos |
| `folium` | Mapas interactivos en HTML |
| `shapely` | Operaciones geométricas (intersección, bbox) |

---

### 1.2 Estructura del repositorio y clase Pipeline

**Qué hicimos:** Definimos la arquitectura de carpetas del proyecto y creamos la clase `Pipeline` como esqueleto vacío.

**Por qué:** Fijar la arquitectura desde el primer día nos obliga a pensar en el diseño antes de escribir código. La clase `Pipeline` con métodos vacíos (`download`, `preprocess`, `classify`, `detect_anomalies`) define el contrato del sistema: cada fase del análisis es un método independiente, intercambiable y testeable por separado.

**Decisión de diseño clave — el `config.yaml` como única entrada:**
Decidimos que el sistema recibe un fichero YAML como parámetro. Cambiar de ubicación, fechas o modelo no requiere tocar código — solo editar el YAML. Esto hace el pipeline directamente aplicable a cualquier zona del mundo y es el argumento principal de valor para AVS, que opera LUR-1 para clientes globales.

```
lur1-analysis/
├── config/          # parámetros por ubicación (no código)
├── src/             # módulos Python del pipeline
├── data/            # en .gitignore — nunca sube a GitHub
├── figures/         # visualizaciones exportadas
└── notebooks/       # exploración y demos
```

**Resultado:** `make run CONFIG=config/costa_vasca.yaml` ejecuta el pipeline completo. En este punto los métodos imprimen "pendiente de implementar", pero la arquitectura está definida y funcional.

---

### 1.3 Descarga de datos Sentinel-2

**Qué hicimos:** Implementamos `downloader.py` y descargamos 3 escenas Sentinel-2 L2A del tile T30TWN (Costa Vasca).

**Por qué Sentinel-2:** Satélite de la ESA con 13 bandas espectrales a 10-60 m de resolución. Los datos L2A están corregidos atmosféricamente por ESA — producto listo para análisis, sin necesidad de correr Sen2Cor localmente. Son gratuitos y públicos a través de Copernicus Data Space Ecosystem (CDSE).

**Por qué L2A y no L1C:** L1C son datos en reflectancia de toa (top of atmosphere) — incluyen la atmósfera. L2A ya tiene la corrección atmosférica aplicada por ESA, equivalente a la corrección telúrica en espectroscopía astronómica: elimina la huella del medio entre la fuente (superficie terrestre) y el detector (satélite). Para analizar cobertura terrestre necesitamos reflectancia de superficie (BOA), que es L2A.

**Dificultades que encontramos y cómo las resolvimos:**
- La API OData de CDSE con filtro de geometría espacial tardaba >60s y daba timeout. Lo resolvimos filtrando por nombre de tile (`contains(Name, 'T30TWN')`) en la query OData, que es instantáneo.
- El header de autenticación Bearer se perdía en redirecciones entre dominios (`catalogue.` → `download.dataspace.copernicus.eu`). Lo resolvimos con un HTTPAdapter personalizado que preserva el header en cada redirect.
- Verificamos que el STAC de CDSE no indexa Sentinel-2 — solo hay otros productos, no es una opción viable.
- La primera descarga cogió tiles de Australia porque sin filtro espacial la API devuelve las escenas más recientes del mundo. Lo resolvimos añadiendo el campo `tile` al config.yaml.

**Credenciales:** Las almacenamos como variables de entorno en `~/.bashrc` de Ubuntu (`CDSE_USER`, `CDSE_PASSWORD`). Nunca en el código ni en el repositorio.

**Resultado:** 3 escenas descargadas en `data/raw/`:
- `S2A_MSIL2A_20241228` — 28 diciembre 2024
- `S2A_MSIL2A_20241128` — 28 noviembre 2024
- `S2C_MSIL2A_20241128` — 28 noviembre 2024 (satélite Sentinel-2C)

---

### 1.4 Exploración visual

**Qué hicimos:** Creamos el notebook `01_exploracion.ipynb` que abre las escenas descargadas, visualiza cada banda individualmente, genera composiciones RGB y falso color NIR, histogramas y un scatter plot NIR vs Red.

**Por qué explorar antes de procesar:** Antes de aplicar cualquier algoritmo necesitamos confirmar que los datos tienen buena calidad visual. Un error en la descarga, una escena con nubes no detectadas o un problema de calibración se detecta aquí. En ciencia de datos satelital, mirar los datos es un paso científico, no opcional.

**Por qué estas bandas y no otras:**

Sentinel-2 tiene 13 bandas espectrales. Elegimos B02, B03, B04 y B08 porque son las únicas a 10 m de resolución — el resto están a 20 o 60 m. Para la exploración inicial queremos el máximo detalle posible.

| Banda | Longitud de onda | Qué mide |
|---|---|---|
| B02 | 490 nm — Azul visible | Reflexión en azul, penetra el agua |
| B03 | 560 nm — Verde visible | Reflexión en verde, picos de vegetación |
| B04 | 665 nm — Rojo visible | Absorbido por clorofila — clave para el NDVI |
| B08 | 842 nm — Infrarrojo cercano | Reflectado fuertemente por vegetación sana |

**Por qué cada superficie se ve como se ve:**

Las imágenes muestran reflectancia — cuánta luz de cada longitud de onda rebota desde la superficie hacia el satélite. Cada tipo de superficie tiene una firma espectral distinta:
- **Vegetación:** absorbe azul y rojo para la fotosíntesis, refleja fuertemente en NIR. En B08 aparece brillante; en RGB aparece verdosa/marrón en invierno por menor clorofila.
- **Agua:** absorbe casi todo el NIR — aparece negra en B08 y oscura en el RGB.
- **Nieve:** refleja intensamente en todas las bandas visibles — blanca en RGB, cian en falso color NIR porque absorbe algo de NIR.
- **Urbano:** refleja de forma similar en todas las bandas visibles — aparece gris.

**Por qué estas tres composiciones y no otras:**

| Composición | Razón |
|---|---|
| RGB (B04-B03-B02) | Imita lo que ve el ojo humano. Primera verificación: si no reconocemos la zona, algo va mal |
| Falso color NIR (B08-B04-B03) | Estándar histórico en teledetección desde los 70. Maximiza el contraste entre vegetación y todo lo demás — justo lo que necesitamos para el NDVI |
| Bandas individuales en gris | Permite detectar artefactos, rayas de sensor o problemas de calibración en una banda concreta antes de combinarlas |

**Dificultades que encontramos:**
- `libgdal-jp2openjpeg` se instaló en versión 3.10.0 mientras el resto de GDAL estaba en 3.12.4 — versiones incompatibles que impedían leer archivos JP2. Lo resolvimos con `conda install "libgdal-jp2openjpeg=3.12"` para alinear versiones.
- El servidor Jupyter lanzado desde el directorio home (`/home/urko`) no encontraba los datos del proyecto. Lo resolvimos lanzándolo siempre desde la raíz del proyecto.

**Resultados de la exploración:**
- Escena de diciembre 2024 — buena calidad visual, sin nubes significativas en tierra
- RGB confirma zona reconocible: costa vasca, Donostia, Pirineos con nieve en el este
- Falso color NIR confirma 4 clases espectralmente distinguibles: vegetación (rojo intenso), agua (negro), urbano (gris-rosa), nieve/litoral (cian/blanco)
- Histogramas: distribución normal para escena invernal, sin saturación ni artefactos
- Scatter B08 vs B04: forma triangular clásica confirma que el NDVI será discriminante — vegetación sana aparece claramente separada del resto

**Conclusión Fase 1:** entorno funcional, arquitectura definida, datos descargados y validados visualmente. Listos para la Fase 2.

---

*Documento actualizado a: Fase 1 completada*
