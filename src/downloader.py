import os
from datetime import datetime, timedelta

import requests

from paths import RAW_DIR, write_manifest

ODATA_URL = 'https://catalogue.dataspace.copernicus.eu/odata/v1/Products'
TOKEN_URL = 'https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token'


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


def _download_scene(scene, output_path, token):
    scene_id = scene['Id']
    name = scene['Name']
    dest = output_path / f'{name}.zip'
    if dest.exists():
        print(f'  · Ya existe, omitiendo: {name}')
        return dest

    url = f'https://catalogue.dataspace.copernicus.eu/odata/v1/Products({scene_id})/$value'

    session = requests.Session()
    session.headers.update({'Authorization': f'Bearer {token}'})

    class _AuthRedirect(requests.adapters.HTTPAdapter):
        def send(self, request, **kwargs):
            request.headers['Authorization'] = f'Bearer {token}'
            return super().send(request, **kwargs)

    session.mount('https://', _AuthRedirect())

    with session.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        total = int(r.headers.get('content-length', 0))
        downloaded = 0
        with open(dest, 'wb') as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = downloaded / total * 100
                    print(f'\r  · {name}  {pct:.1f}%', end='', flush=True)
    print()
    return dest


def download(config, zone, max_scenes=500):
    location = config['location']['name']
    bbox = config['location']['bbox']
    date_start = config['dates']['start']
    date_end = config['dates']['end']
    max_cloud = config['satellite']['max_cloud_pct']

    user = os.environ.get('CDSE_USER')
    password = os.environ.get('CDSE_PASSWORD')
    if not user or not password:
        raise EnvironmentError(
            'Define las variables CDSE_USER y CDSE_PASSWORD antes de descargar.'
        )

    tile = config.get('satellite', {}).get('tile')

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

    token = _get_token(user, password)
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    for scene in scenes:
        _download_scene(scene, RAW_DIR, token)

    print('Descarga completada.')
    return scenes
