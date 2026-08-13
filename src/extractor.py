'''
Descompresión de los .zip descargados de CDSE a directorios .SAFE.

Es el eslabón entre la descarga (que entrega .zip) y el preprocesado (que lee
estructuras .SAFE). Valida cada zip antes de extraerlo y cada .SAFE después de
extraerlo: una descarga interrumpida deja un fichero truncado, y una extracción
interrumpida (disco lleno, proceso matado a media escritura) deja un .SAFE a
medias — ambos reventarían el preprocesado mucho más tarde, con un error menos
claro. El .zip no se borra hasta que el .SAFE resultante pasa esta verificación.
'''

import shutil
import zipfile

from paths import RAW_DIR, read_manifest

# Bandas que preprocessor.py necesita sí o sí — si falta alguna, el .SAFE no
# sirve aunque la extracción no haya lanzado ningún error.
REQUIRED_BANDS_10M = ['B02', 'B03', 'B04', 'B08']
REQUIRED_BANDS_20M = ['B05', 'B11', 'B12', 'SCL']


def _is_valid_zip(path):
    try:
        with zipfile.ZipFile(path) as zf:
            return zf.testzip() is None
    except (zipfile.BadZipFile, OSError):
        return False


def _is_valid_safe(safe_path):
    '''Comprueba que el .SAFE tiene la estructura que preprocessor.py espera.'''
    try:
        granule = next((safe_path / 'GRANULE').iterdir())
    except (FileNotFoundError, StopIteration):
        return False

    r10m = granule / 'IMG_DATA' / 'R10m'
    r20m = granule / 'IMG_DATA' / 'R20m'
    if not r10m.is_dir() or not r20m.is_dir():
        return False

    for band in REQUIRED_BANDS_10M:
        if not any(r10m.glob(f'*_{band}_10m.jp2')):
            return False
    for band in REQUIRED_BANDS_20M:
        if not any(r20m.glob(f'*_{band}_20m.jp2')):
            return False

    return True


def extract(zone, keep_zips=False):
    '''
    Extrae los .zip de las escenas de la zona que aún no estén descomprimidas.
    Devuelve (extraídas, ya_presentes, inválidas).

    Por defecto (`keep_zips=False`) borra cada .zip justo después de extraerlo
    y **verificar** que el .SAFE resultante está completo: una vez confirmado,
    el .zip no aporta nada y una serie de 2 años puede rondar los 150-200 GB
    solo en zips. Si la verificación falla, se conserva el zip (para poder
    reintentar) y se borra el .SAFE incompleto (para que la próxima ejecución
    no lo dé por bueno). También revalida — y si hace falta limpia — zips
    sueltos de escenas que ya tenían su .SAFE de antes de este cambio.

    downloader.py comprueba el .SAFE (no el .zip) para decidir si una escena
    ya está descargada, así que borrar el zip no provoca una redescarga.
    '''
    names = read_manifest(zone)
    extracted, present, invalid = [], [], []

    for name in names:
        safe_name = name if name.endswith('.SAFE') else f'{name}.SAFE'
        safe_path = RAW_DIR / safe_name
        zip_path = RAW_DIR / f'{safe_name}.zip'

        if safe_path.is_dir():
            if not _is_valid_safe(safe_path):
                invalid.append((safe_name, '.SAFE existente incompleto o corrupto'))
                shutil.rmtree(safe_path)
                continue
            present.append(safe_name)
            if not keep_zips and zip_path.exists():
                zip_path.unlink()
            continue

        if not zip_path.exists():
            invalid.append((safe_name, 'zip no descargado'))
            continue

        if not _is_valid_zip(zip_path):
            invalid.append((safe_name, 'zip corrupto o incompleto'))
            continue

        print(f'  Extrayendo: {safe_name}')
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(RAW_DIR)

        if not _is_valid_safe(safe_path):
            invalid.append((safe_name, 'extracción incompleta — faltan bandas esperadas'))
            shutil.rmtree(safe_path, ignore_errors=True)
            continue

        extracted.append(safe_name)
        if not keep_zips:
            zip_path.unlink()

    print(f'Extracción — zona "{zone}": '
          f'{len(extracted)} extraídas, {len(present)} ya presentes, {len(invalid)} con problemas')

    if invalid:
        print('  Escenas no disponibles:')
        for name, reason in invalid:
            print(f'    · {name} — {reason}')
        print('  Vuelve a ejecutar la descarga para reintentarlas.')

    return extracted, present, invalid
