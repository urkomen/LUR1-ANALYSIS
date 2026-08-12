import os
import time
import zipfile
from datetime import datetime, timedelta

import requests

from paths import RAW_DIR, write_manifest

ODATA_URL = 'https://catalogue.dataspace.copernicus.eu/odata/v1/Products'
TOKEN_URL = 'https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token'


def _require_credentials():
    '''
    Lee las credenciales CDSE del entorno. Si faltan, explica cuál falta y
    cómo definirla en lugar de fallar con un mensaje genérico.
    '''
    user = os.environ.get('CDSE_USER')
    password = os.environ.get('CDSE_PASSWORD')

    if user and password:
        return user, password

    if not user and not password:
        que_falta = 'No están definidas CDSE_USER ni CDSE_PASSWORD.'
    elif not user:
        que_falta = 'CDSE_PASSWORD está definida pero falta CDSE_USER.'
    else:
        que_falta = f'CDSE_USER está definida ({user}) pero falta CDSE_PASSWORD.'

    raise EnvironmentError(
        f'No se puede descargar de Copernicus Data Space.\n\n'
        f'  {que_falta}\n\n'
        f'Defínelas en tu shell antes de ejecutar el pipeline:\n\n'
        f'    export CDSE_USER="tu_usuario@email.com"\n'
        f'    export CDSE_PASSWORD="tu_contraseña"\n\n'
        f'Necesitas una cuenta (gratuita) en https://dataspace.copernicus.eu/\n'
        f'Son las credenciales de acceso a la web, no un token de API.\n\n'
        f'Comprueba que han quedado definidas con:  echo $CDSE_USER\n\n'
        f'Si ya las tenías en el shell y aun así ves esto, probablemente las\n'
        f'exportaste en otra terminal o dentro de un script: las variables de\n'
        f'entorno no se heredan hacia atrás. Expórtalas en la misma sesión desde\n'
        f'la que lanzas el pipeline, o déjalas en tu perfil de shell.\n\n'
        f'Los pasos que no descargan (extract, timeseries, anomalies, classify)\n'
        f'funcionan sin credenciales:\n'
        f'    python src/pipeline.py --config <config> --steps timeseries anomalies'
    )


def _get_token(user, password):
    resp = requests.post(
        TOKEN_URL,
        data={
            'client_id': 'cdse-public',
            'username': user,
            'password': password,
            'grant_type': 'password',
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()['access_token']


class TokenManager:
    '''
    El token de CDSE caduca a los ~10 minutos. Con 74 escenas de ~1.6 GB cada
    una, una descarga larga lo agota a mitad de camino: las primeras escenas
    bajan bien y el resto falla con 401, porque _download_scene pedía un
    único token antes de empezar el bucle entero.

    Renueva antes de cada escena si el token tiene más de refresh_after
    segundos, y expone force_refresh() para el caso en que el servidor
    devuelva 401 pese a la renovación preventiva (reloj desincronizado,
    revocación, lo que sea).
    '''

    def __init__(self, user, password, refresh_after=480):
        self._user = user
        self._password = password
        self._refresh_after = refresh_after
        self._token = None
        self._issued_at = 0

    def get(self):
        if self._token is None or (time.monotonic() - self._issued_at) > self._refresh_after:
            self._token = _get_token(self._user, self._password)
            self._issued_at = time.monotonic()
        return self._token

    def force_refresh(self):
        self._token = _get_token(self._user, self._password)
        self._issued_at = time.monotonic()
        return self._token


def _bbox_to_wkt(bbox):
    '''Convierte [lon_min, lat_min, lon_max, lat_max] a POLYGON WKT cerrado.'''
    lon_min, lat_min, lon_max, lat_max = bbox
    return (
        f'POLYGON(({lon_min} {lat_min},{lon_max} {lat_min},'
        f'{lon_max} {lat_max},{lon_min} {lat_max},{lon_min} {lat_min}))'
    )


def _search_scenes(bbox, date_start, date_end, max_cloud, max_scenes, tile=None):
    footprint = _bbox_to_wkt(bbox)

    # dates.end es inclusivo: para incluir las escenas del propio día final
    # el límite superior se pone en la medianoche del día siguiente.
    end_exclusive = (
        datetime.strptime(date_end, '%Y-%m-%d') + timedelta(days=1)
    ).strftime('%Y-%m-%d')

    filter_expr = (
        f"Collection/Name eq 'SENTINEL-2' and "
        f"OData.CSC.Intersects(area=geography'SRID=4326;{footprint}') and "
        f"Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' "
        f"and att/OData.CSC.StringAttribute/Value eq 'S2MSI2A') and "
        f"ContentDate/Start ge {date_start}T00:00:00.000Z and "
        f"ContentDate/Start lt {end_exclusive}T00:00:00.000Z and "
        f"Attributes/OData.CSC.DoubleAttribute/any(att:att/Name eq 'cloudCover' "
        f"and att/OData.CSC.DoubleAttribute/Value le {float(max_cloud)})"
    )
    if tile:
        filter_expr += f" and contains(Name, '{tile}')"

    resp = requests.get(
        ODATA_URL,
        params={'$filter': filter_expr, '$top': max_scenes, '$orderby': 'ContentDate/Start desc'},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json().get('value', [])


def _looks_like_complete_zip(path):
    '''
    Comprueba que el zip tiene un directorio central legible. Es una lectura
    del final del fichero, no una descompresión: basta para detectar un
    truncamiento y no cuesta nada aunque el zip pese gigas.
    '''
    try:
        with zipfile.ZipFile(path) as zf:
            return bool(zf.namelist())
    except (zipfile.BadZipFile, OSError):
        return False


def _do_download(url, token, partial, name):
    '''Un único intento de descarga. Deja el .part escrito; no lo valida ni lo renombra.'''
    session = requests.Session()

    class _AuthRedirect(requests.adapters.HTTPAdapter):
        def send(self, request, **kwargs):
            request.headers['Authorization'] = f'Bearer {token}'
            return super().send(request, **kwargs)

    session.mount('https://', _AuthRedirect())
    session.headers.update({'Authorization': f'Bearer {token}'})

    with session.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        total = int(r.headers.get('content-length', 0))
        downloaded = 0
        with open(partial, 'wb') as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = downloaded / total * 100
                    print(f'\r  · {name}  {pct:.1f}%', end='', flush=True)
    print()

    if total and downloaded != total:
        raise IOError(f'transferencia incompleta: {downloaded} de {total} bytes')


def _download_scene(scene, output_path, tokens):
    '''
    Descarga una escena a un fichero temporal .part y solo lo renombra al
    nombre definitivo cuando la transferencia se ha completado y verificado.

    Así un corte de red nunca deja un .zip truncado con nombre bueno: si
    existe el .zip, está entero. Antes, una descarga interrumpida dejaba un
    fichero que las siguientes ejecuciones daban por descargado y saltaban
    para siempre, y el fallo aparecía mucho después al extraer.

    `tokens` es un TokenManager: renueva el token si ha caducado antes de
    empezar, y si aun así el servidor devuelve 401 a mitad de descarga
    (el token dura ~10 min y una escena de 1.6 GB puede tardar más),
    fuerza una renovación y reintenta una vez.
    '''
    scene_id = scene['Id']
    name = scene['Name']
    dest = output_path / f'{name}.zip'
    partial = output_path / f'{name}.zip.part'

    if dest.exists():
        print(f'  · Ya existe, omitiendo: {name}')
        return dest

    url = f'https://catalogue.dataspace.copernicus.eu/odata/v1/Products({scene_id})/$value'

    try:
        try:
            _do_download(url, tokens.get(), partial, name)
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 401:
                print(f'\n  · Token caducado a mitad de descarga, renovando y reintentando: {name}')
                _do_download(url, tokens.force_refresh(), partial, name)
            else:
                raise

        if not _looks_like_complete_zip(partial):
            raise IOError('el fichero descargado no es un zip válido')

        partial.replace(dest)
        return dest

    except BaseException as e:
        # Incluye KeyboardInterrupt: si se corta con Ctrl-C, tampoco debe
        # quedar un .part suelto ocupando espacio.
        partial.unlink(missing_ok=True)
        if isinstance(e, (KeyboardInterrupt, SystemExit)):
            raise
        print(f'\n  ! Fallo descargando {name}: {e}')
        return None


def download(config, zone, max_scenes=500):
    location = config['location']['name']
    bbox = config['location']['bbox']
    date_start = config['dates']['start']
    date_end = config['dates']['end']
    max_cloud = config['satellite']['max_cloud_pct']
    tile = config.get('satellite', {}).get('tile')

    # Se comprueban antes de buscar: si faltan, mejor avisar de inmediato que
    # después de una consulta al catálogo que no va a servir para nada.
    user, password = _require_credentials()

    print(f'Buscando escenas Sentinel-2 L2A para: {location}')
    print(f'  Bbox:      {bbox}')
    print(f'  Periodo:   {date_start} → {date_end}')
    print(f'  Nubes max: {max_cloud}%')
    if tile:
        print(f'  Tile:      {tile} (filtro adicional)')
    scenes = _search_scenes(bbox, date_start, date_end, max_cloud, max_scenes, tile=tile)

    if not scenes:
        print('No se encontraron escenas con los criterios del config.')
        return []

    print(f'Encontradas {len(scenes)} escena(s). Descargando...')
    for s in scenes:
        print(f'  · {s["Name"]}')

    # El manifiesto se escribe antes de descargar: define qué escenas
    # pertenecen a la zona aunque la descarga se interrumpa a medias.
    write_manifest(zone, [s['Name'] for s in scenes])

    tokens = TokenManager(user, password)
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    fallidas = []
    for scene in scenes:
        if _download_scene(scene, RAW_DIR, tokens) is None:
            fallidas.append(scene['Name'])

    if fallidas:
        print(f'\nDescarga terminada con {len(fallidas)} fallo(s) de {len(scenes)}:')
        for name in fallidas:
            print(f'  · {name}')
        print('Vuelve a ejecutar el paso de descarga para reintentarlas: '
              'las ya completadas se saltan.')
    else:
        print('Descarga completada.')

    return scenes
