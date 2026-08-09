'''
Construcción de la serie temporal de índices espectrales.

Procesa las escenas de una zona de una en una y guarda solo los estadísticos
de cada índice, descartando el ráster antes de pasar a la siguiente escena.
Mantener las 99 escenas en memoria a la vez no es viable: cada una son 7
bandas de ~2000x2000 en float32.
'''

from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from indices import calculate_indices
from paths import processing_opts, zone_dir, zone_scene_dirs
from preprocessor import preprocess


def scene_date(scene_dir):
    '''Extrae la fecha de adquisición del nombre de la escena.'''
    date_str = Path(scene_dir).name.split('_')[2][:8]
    return datetime.strptime(date_str, '%Y%m%d').date()


def _scene_stats(scene_dir, config):
    '''Preprocesa una escena y devuelve los estadísticos de sus índices.'''
    try:
        result = preprocess(scene_dir, config)
        idx_arrays = calculate_indices(
            result['bands'],
            config.get('indices', ['NDVI', 'NDWI', 'MNDWI'])
        )

        row = {
            'scene': scene_dir.name,
            'date': scene_date(scene_dir),
            'cloud_pct': result['cloud_pct'],
        }

        for name, arr in idx_arrays.items():
            valid = arr[~np.isnan(arr)]
            if len(valid) == 0:
                row.update({f'{name}_{s}': np.nan for s in ('mean', 'std', 'p10', 'p90')})
            else:
                row[f'{name}_mean'] = float(np.mean(valid))
                row[f'{name}_std'] = float(np.std(valid))
                row[f'{name}_p10'] = float(np.percentile(valid, 10))
                row[f'{name}_p90'] = float(np.percentile(valid, 90))

        return row

    except Exception as e:
        print(f'  ERROR procesando {scene_dir.name}: {e}')
        return None


def build_timeseries(config, zone):
    '''
    Procesa las escenas de la zona y escribe time_series.csv y
    monthly_stats.csv en data/processed/<zona>/.
    '''
    scene_dirs = zone_scene_dirs(zone)
    if not scene_dirs:
        print(f'[timeseries] No hay escenas extraídas para la zona "{zone}"')
        return None, None

    out_dir = zone_dir(zone)
    print(f'Zona "{zone}": procesando {len(scene_dirs)} escenas...')

    rows = []
    for i, scene_dir in enumerate(scene_dirs, 1):
        print(f'[{i}/{len(scene_dirs)}] {scene_dir.name}')
        row = _scene_stats(scene_dir, config)
        if row:
            rows.append(row)

    if not rows:
        print('No se procesó ninguna escena correctamente.')
        return None, None

    df = pd.DataFrame(rows)
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date')
    df.to_csv(out_dir / 'time_series.csv', index=False)
    print(f'\nSerie temporal guardada: {out_dir / "time_series.csv"}')
    print(f'  Total escenas procesadas: {len(df)}')

    # Las escenas con demasiada nube dentro del bbox distorsionan la
    # climatología mensual, así que quedan fuera del cálculo de referencia.
    max_bbox_cloud = processing_opts(config)['max_bbox_cloud_pct']
    df_valid = df[df['cloud_pct'] <= max_bbox_cloud].copy()
    print(f'  Escenas con >{max_bbox_cloud}% nubes en bbox descartadas: {len(df) - len(df_valid)}')
    print(f'  Escenas válidas para estadísticas: {len(df_valid)}')

    df_valid['month'] = df_valid['date'].dt.month
    indices_list = config.get('indices', ['NDVI', 'NDWI', 'MNDWI'])

    monthly_rows = []
    for month in range(1, 13):
        subset = df_valid[df_valid['month'] == month]
        if len(subset) == 0:
            continue

        month_row = {'month': month, 'n_scenes': len(subset)}
        for idx in indices_list:
            col = f'{idx}_mean'
            if col in subset.columns:
                vals = subset[col].dropna()
                month_row[f'{idx}_mean'] = float(vals.mean()) if len(vals) > 0 else np.nan
                month_row[f'{idx}_std'] = float(vals.std()) if len(vals) > 1 else np.nan
        monthly_rows.append(month_row)

    monthly = pd.DataFrame(monthly_rows)
    monthly.to_csv(out_dir / 'monthly_stats.csv', index=False)
    print(f'Estadísticas mensuales guardadas: {out_dir / "monthly_stats.csv"}')
    print()
    print(monthly.to_string(index=False))

    return df, monthly
