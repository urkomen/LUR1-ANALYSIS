'''
Resolución de rutas por zona.

data/raw/ se comparte entre zonas: el nombre de escena Sentinel-2 es un
identificador único global, así que dos zonas que cubran el mismo tile
reutilizan el mismo fichero en lugar de duplicarlo. Cada zona lleva un
manifiesto con las escenas que le pertenecen, y sus resultados viven en
un directorio propio.
'''

from pathlib import Path

RAW_DIR = Path('data/raw')
PROCESSED_DIR = Path('data/processed')
MODELS_DIR = Path('data/models')
FIGURES_DIR = Path('figures')


MANIFEST_NAME = 'manifest.txt'

# Parámetros de procesado y sus valores por defecto si el config no los trae.
PROCESSING_DEFAULTS = {
    'max_bbox_cloud_pct': 50,
    'min_ref_scenes': 5,
}


def processing_opts(config):
    '''
    Opciones del bloque `processing` del config, con defaults.

    max_bbox_cloud_pct no es lo mismo que satellite.max_cloud_pct: aquel
    filtra la escena completa en la descarga, este la nubosidad medida
    dentro del bbox ya recortado.
    '''
    opts = dict(PROCESSING_DEFAULTS)
    opts.update(config.get('processing') or {})
    return opts


def zone_from_config(config_path):
    '''Deriva el nombre de zona del fichero de config: config/nervion.yaml -> nervion'''
    return Path(config_path).stem


def zone_dir(zone):
    '''Directorio de resultados de una zona, creado si no existe.'''
    d = PROCESSED_DIR / zone
    d.mkdir(parents=True, exist_ok=True)
    return d


def figures_dir(zone):
    '''Directorio de figuras de una zona, creado si no existe.'''
    d = FIGURES_DIR / zone
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_manifest(zone, scene_names):
    '''Guarda la lista de escenas que pertenecen a una zona.'''
    path = zone_dir(zone) / MANIFEST_NAME
    path.write_text('\n'.join(sorted(scene_names)) + '\n')
    print(f'Manifiesto actualizado: {path} ({len(scene_names)} escenas)')
    return path


def read_manifest(zone):
    '''
    Devuelve los nombres de escena de la zona. Lanza FileNotFoundError si
    la zona no se ha descargado todavía.
    '''
    path = zone_dir(zone) / MANIFEST_NAME
    if not path.exists():
        raise FileNotFoundError(
            f'No existe manifiesto para la zona "{zone}" ({path}). '
            f'Ejecuta primero la descarga: python src/pipeline.py --config config/{zone}.yaml'
        )
    return [line.strip() for line in path.read_text().splitlines() if line.strip()]


def zone_scene_dirs(zone):
    '''
    Directorios .SAFE de data/raw/ que pertenecen a la zona, según su
    manifiesto. Avisa de las escenas del manifiesto que aún no están
    extraídas en disco.
    '''
    names = read_manifest(zone)
    found, missing = [], []
    for name in names:
        safe = RAW_DIR / (name if name.endswith('.SAFE') else f'{name}.SAFE')
        (found if safe.is_dir() else missing).append(safe)

    if missing:
        print(f'  AVISO: {len(missing)} escena(s) del manifiesto sin extraer en {RAW_DIR}/')
    return sorted(found)
