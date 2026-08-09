'''
Descompresión de los .zip descargados de CDSE a directorios .SAFE.

Es el eslabón entre la descarga (que entrega .zip) y el preprocesado (que lee
estructuras .SAFE). Valida cada zip antes de extraerlo: una descarga
interrumpida deja un fichero truncado que reventaría el preprocesado más tarde,
con un error mucho menos claro.
'''

import zipfile

from paths import RAW_DIR, read_manifest


def _is_valid_zip(path):
    try:
        with zipfile.ZipFile(path) as zf:
            return zf.testzip() is None
    except (zipfile.BadZipFile, OSError):
        return False


def extract(zone):
    '''
    Extrae los .zip de las escenas de la zona que aún no estén descomprimidas.
    Devuelve (extraídas, ya_presentes, inválidas).
    '''
    names = read_manifest(zone)
    extracted, present, invalid = [], [], []

    for name in names:
        safe_name = name if name.endswith('.SAFE') else f'{name}.SAFE'
        safe_path = RAW_DIR / safe_name
        zip_path = RAW_DIR / f'{safe_name}.zip'

        if safe_path.is_dir():
            present.append(safe_name)
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
        extracted.append(safe_name)

    print(f'Extracción — zona "{zone}": '
          f'{len(extracted)} extraídas, {len(present)} ya presentes, {len(invalid)} con problemas')

    if invalid:
        print('  Escenas no disponibles:')
        for name, reason in invalid:
            print(f'    · {name} — {reason}')
        print('  Vuelve a ejecutar la descarga para reintentarlas.')

    return extracted, present, invalid
