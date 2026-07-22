from pathlib import Path

import numpy as np
import rasterio
from rasterio.mask import mask as rio_mask
from pyproj import Transformer
from shapely.geometry import box, mapping

# Clases SCL que marcamos como inválidas
# 0=sin datos, 1=saturado, 3=sombra de nube, 8=nube media, 9=nube alta, 10=cirrus
INVALID_SCL = {0, 1, 3, 8, 9, 10}

BANDS_10M = ['B02', 'B03', 'B04', 'B08']
BANDS_20M = ['B05', 'B06', 'B07', 'B8A', 'B11', 'B12']


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


def mask_clouds(scene_dir, bbox, max_cloud_pct=20):
    """
    Lee la SCL, recorta al bbox y devuelve máscara booleana válida a 10m.
    True = píxel válido, False = nube/sombra/sin datos.
    """
    r10m, r20m = _find_img_dirs(scene_dir)
    scl_file = next(r20m.glob('*_SCL_20m.jp2'))

    with rasterio.open(scl_file) as src:
        geom = _bbox_to_geom(bbox, src.crs.to_epsg() or src.crs.to_string())
        scl_clipped, _ = rio_mask(src, geom, crop=True)
        scl = scl_clipped[0]

    valid_20m = ~np.isin(scl, list(INVALID_SCL))
    cloud_pct = (~valid_20m).sum() / valid_20m.size * 100
    print(f'  Cobertura nubosa en bbox: {cloud_pct:.1f}%')
    if cloud_pct > max_cloud_pct:
        print(f'  AVISO: supera el umbral de {max_cloud_pct}%')

    # Upscale 20m → 10m (factor 2) con nearest neighbor
    valid_10m = np.repeat(np.repeat(valid_20m, 2, axis=0), 2, axis=1)
    return valid_10m, cloud_pct


def clip_to_bbox(band_file, geom):
    """Lee un archivo de banda y lo recorta a la geometría dada."""
    with rasterio.open(band_file) as src:
        data, transform = rio_mask(src, geom, crop=True)
        return data[0].astype(np.float32), transform, src.crs


def preprocess(scene_dir, config):
    """
    Aplica máscara de nubes y recorte al bbox sobre todas las bandas.
    Devuelve dict con arrays por banda (NaN donde hay nube) y metadatos.
    """
    bbox = config['location']['bbox']
    max_cloud = config['satellite']['max_cloud_pct']

    r10m, r20m = _find_img_dirs(scene_dir)

    # Geometría en CRS de la escena (calculada desde el primer archivo 10m)
    ref_file = next(r10m.glob('*_B02_10m.jp2'))
    with rasterio.open(ref_file) as src:
        crs = src.crs
    geom = _bbox_to_geom(bbox, crs.to_epsg() or crs.to_string())

    print('Aplicando máscara de nubes (SCL)...')
    valid_10m, cloud_pct = mask_clouds(scene_dir, bbox, max_cloud)

    print('Recortando bandas a bbox...')
    bands = {}
    transform = None

    for band_name in BANDS_10M:
        f = next(r10m.glob(f'*_{band_name}_10m.jp2'))
        data, transform, _ = clip_to_bbox(f, geom)

        # Ajustar tamaño si hay diferencia de un píxel por redondeo
        h = min(data.shape[0], valid_10m.shape[0])
        w = min(data.shape[1], valid_10m.shape[1])
        data = data[:h, :w]
        mask = valid_10m[:h, :w]

        data[~mask] = np.nan
        bands[band_name] = data

    # Banda SWIR (B11 a 20m) — necesaria para MNDWI, resampled a 10m
    b11_file = next(r20m.glob('*_B11_20m.jp2'))
    b11_20m, _, _ = clip_to_bbox(b11_file, geom)
    b11_10m = np.repeat(np.repeat(b11_20m, 2, axis=0), 2, axis=1)
    h = min(b11_10m.shape[0], valid_10m.shape[0])
    w = min(b11_10m.shape[1], valid_10m.shape[1])
    b11_10m = b11_10m[:h, :w]
    b11_10m[~valid_10m[:h, :w]] = np.nan
    bands['B11'] = b11_10m

    print(f'  Bandas procesadas: {list(bands.keys())}')
    print(f'  Tamaño del recorte: {list(bands.values())[0].shape}')

    return {
        'bands': bands,
        'transform': transform,
        'crs': crs,
        'cloud_pct': cloud_pct,
        'scene_dir': str(scene_dir),
    }
