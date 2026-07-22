import os
from pathlib import Path

import requests

STAC_URL = 'https://catalogue.dataspace.copernicus.eu/stac/search'
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


def _search_scenes(bbox, date_start, date_end, max_cloud, max_scenes, tile=None):
    filter_expr = (
        f"Collection/Name eq 'SENTINEL-2' and "
        f"Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' "
        f"and att/OData.CSC.StringAttribute/Value eq 'S2MSI2A') and "
        f"ContentDate/Start gt {date_start}T00:00:00.000Z and "
        f"ContentDate/End lt {date_end}T00:00:00.000Z and "
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


def download(config, max_scenes=3):
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

    print(f'Buscando escenas Sentinel-2 L2A para: {location}')
    print(f'  Periodo:   {date_start} → {date_end}')
    print(f'  Nubes max: {max_cloud}%')

    tile = config.get('satellite', {}).get('tile')
    scenes = _search_scenes(bbox, date_start, date_end, max_cloud, max_scenes, tile=tile)

    if not scenes:
        print('No se encontraron escenas con los criterios del config.')
        return []

    print(f'Encontradas {len(scenes)} escena(s). Descargando...')
    for s in scenes:
        print(f'  · {s["Name"]}')

    token = _get_token(user, password)
    output_path = Path('data/raw')
    output_path.mkdir(parents=True, exist_ok=True)

    for scene in scenes:
        _download_scene(scene, output_path, token)

    print('Descarga completada.')
    return scenes
