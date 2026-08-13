from pathlib import Path

import numpy as np
import rasterio
from rasterio.mask import mask as rio_mask
from rasterio.warp import reproject, Resampling
from pyproj import Transformer
from shapely.geometry import box, mapping

from paths import processing_opts

# Clases SCL que marcamos como inválidas
# 0=sin datos, 1=saturado, 3=sombra de nube, 8=nube media, 9=nube alta, 10=cirrus
INVALID_SCL = {0, 1, 3, 8, 9, 10}

BANDS_10M = ['B02', 'B03', 'B04', 'B08']
BANDS_20M = ['B05', 'B11', 'B12']


def _find_img_dirs(scene_dir):
    granule = next((Path(scene_dir) / 'GRANULE').iterdir())
    r10m = granule / 'IMG_DATA' / 'R10m'
    r20m = granule / 'IMG_DATA' / 'R20m'
    return r10m, r20m


def _bbox_to_geom(bbox, crs):
    lon_min, lat_min, lon_max, lat_max = bbox
    transformer = Transformer.from_crs('EPSG:4326', crs, always_xy=True)
    x_min, y_min = transformer.transform(lon_min, lat_min)
    x_max, y_max = transformer.transform(lon_max, lat_max)
    return [mapping(box(x_min, y_min, x_max, y_max))]


def clip_to_bbox(band_file, geom):
    '''Lee un archivo de banda y lo recorta a la geometría dada.'''
    with rasterio.open(band_file) as src:
        data, transform = rio_mask(src, geom, crop=True)
        return data[0].astype(np.float32), transform, src.crs


def _reproject_to_grid(band_file, geom, ref_transform, ref_shape, ref_crs, resampling):
    '''
    Recorta y reproyecta una banda a la rejilla de referencia (B02 a 10m)
    explícitamente, en vez de asumir que un upscale por repetición (nearest
    ×2) y un recorte al tamaño mínimo común quedan alineados por casualidad.

    El recorte de rasterio a 10m y a 20m no comparte necesariamente el mismo
    origen de rejilla — cada resolución nativa del producto puede recortar en
    un punto ligeramente distinto del bbox — así que sincronizar por tamaño
    mínimo garantiza dimensiones iguales pero no garantiza que el píxel
    (i, j) de una banda y el de la máscara SCL cubran el mismo suelo.
    Reproyectar contra el transform/CRS/shape exactos de la referencia sí lo
    garantiza.
    '''
    with rasterio.open(band_file) as src:
        clipped, clipped_transform = rio_mask(src, geom, crop=True)
        src_crs = src.crs

    dst = np.empty(ref_shape, dtype=np.float32)
    reproject(
        source=clipped[0].astype(np.float32),
        destination=dst,
        src_transform=clipped_transform,
        src_crs=src_crs,
        dst_transform=ref_transform,
        dst_crs=ref_crs,
        resampling=resampling,
    )
    return dst


def mask_clouds(scl_file, geom, ref_transform, ref_shape, ref_crs, max_bbox_cloud_pct=50):
    '''
    Reproyecta la SCL (nativa a 20m) a la rejilla de referencia a 10m y
    devuelve máscara booleana válida. True = píxel válido, False =
    nube/sombra/sin datos.

    `max_bbox_cloud_pct` es solo informativo aquí (el filtrado real de
    escenas nubosas lo hace timeseries/anomaly_detector con este mismo
    umbral): sirve para que el aviso en consola compare contra el criterio
    que de verdad decide si la escena se usa, no contra
    satellite.max_cloud_pct, que es un umbral distinto — ese filtra la
    escena completa al descargar, no la nubosidad ya recortada al bbox.
    '''
    scl = _reproject_to_grid(scl_file, geom, ref_transform, ref_shape, ref_crs,
                              resampling=Resampling.nearest)
    scl = np.round(scl).astype(int)

    valid = ~np.isin(scl, list(INVALID_SCL))
    cloud_pct = (~valid).sum() / valid.size * 100
    print(f'  Cobertura nubosa en bbox: {cloud_pct:.1f}%')
    if cloud_pct > max_bbox_cloud_pct:
        print(f'  AVISO: supera el umbral de {max_bbox_cloud_pct}% del bbox '
              f'(processing.max_bbox_cloud_pct) — la escena se descartará '
              f'de la climatología de referencia')

    return valid, cloud_pct


def preprocess(scene_dir, config):
    '''
    Aplica máscara de nubes y recorte al bbox sobre todas las bandas.
    Devuelve dict con arrays por banda (NaN donde hay nube) y metadatos.

    B02 a 10m recortada al bbox es la rejilla de referencia: todas las demás
    bandas (10m y 20m) y la máscara SCL se reproyectan explícitamente contra
    su transform/shape/CRS exactos, así que el píxel (i, j) siempre
    representa el mismo punto del suelo en todas ellas.
    '''
    bbox = config['location']['bbox']
    max_bbox_cloud = processing_opts(config)['max_bbox_cloud_pct']

    r10m, r20m = _find_img_dirs(scene_dir)

    ref_file = next(r10m.glob('*_B02_10m.jp2'))
    with rasterio.open(ref_file) as src:
        crs = src.crs
    geom = _bbox_to_geom(bbox, crs.to_epsg() or crs.to_string())

    ref_band, transform, _ = clip_to_bbox(ref_file, geom)
    ref_shape = ref_band.shape

    print('Aplicando máscara de nubes (SCL)...')
    scl_file = next(r20m.glob('*_SCL_20m.jp2'))
    valid_mask, cloud_pct = mask_clouds(scl_file, geom, transform, ref_shape, crs, max_bbox_cloud)

    print('Recortando bandas a bbox...')
    bands = {'B02': ref_band}

    for band_name in BANDS_10M[1:]:
        f = next(r10m.glob(f'*_{band_name}_10m.jp2'))
        bands[band_name] = _reproject_to_grid(f, geom, transform, ref_shape, crs,
                                               resampling=Resampling.nearest)

    for band_name in BANDS_20M:
        f = next(r20m.glob(f'*_{band_name}_20m.jp2'))
        bands[band_name] = _reproject_to_grid(f, geom, transform, ref_shape, crs,
                                               resampling=Resampling.nearest)

    for data in bands.values():
        data[~valid_mask] = np.nan

    print(f'  Bandas procesadas: {list(bands.keys())}')
    print(f'  Tamaño del recorte: {ref_shape}')

    return {
        'bands': bands,
        'transform': transform,
        'crs': crs,
        'cloud_pct': cloud_pct,
        'scene_dir': str(scene_dir),
    }
