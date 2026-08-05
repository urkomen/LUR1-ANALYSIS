#!/usr/bin/env python3
'''
Procesa todas las escenas en data/raw/*.SAFE y guarda estadísticas mensuales.
Salida: data/processed/time_series.csv y data/processed/monthly_stats.csv
'''

import sys
import json
import yaml
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent / 'src'))
from preprocessor import preprocess
from indices import calculate_indices


def scene_date(scene_dir):
    '''Extrae la fecha de adquisición del nombre de la escena.'''
    name = Path(scene_dir).name
    date_str = name.split('_')[2][:8]
    return datetime.strptime(date_str, '%Y%m%d').date()


def process_scene(scene_dir, config):
    '''Procesa una escena y devuelve sus estadísticas de índices.'''
    try:
        result = preprocess(scene_dir, config)
        indices = calculate_indices(
            result['bands'],
            config.get('indices', ['NDVI', 'NDWI', 'MNDWI'])
        )

        row = {
            'scene': scene_dir.name,
            'date': scene_date(scene_dir),
            'cloud_pct': result['cloud_pct'],
        }

        for name, arr in indices.items():
            valid = arr[~np.isnan(arr)]
            if len(valid) == 0:
                row[f'{name}_mean'] = np.nan
                row[f'{name}_std']  = np.nan
                row[f'{name}_p10']  = np.nan
                row[f'{name}_p90']  = np.nan
            else:
                row[f'{name}_mean'] = float(np.mean(valid))
                row[f'{name}_std']  = float(np.std(valid))
                row[f'{name}_p10']  = float(np.percentile(valid, 10))
                row[f'{name}_p90']  = float(np.percentile(valid, 90))

        return row

    except Exception as e:
        print(f'  ERROR procesando {scene_dir.name}: {e}')
        return None


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='config/costa_vasca.yaml', help='Config file path')
    parser.add_argument('--suffix', default='', help='Suffix for output files (e.g., Donostia, Nervion)')
    args = parser.parse_args()

    with open(args.config) as f:
        config = yaml.safe_load(f)

    raw_dir = Path('data/raw')
    out_dir = Path('data/processed')
    out_dir.mkdir(parents=True, exist_ok=True)

    # Nombres de salida con sufijo opcional
    ts_name = f'time_series_{args.suffix}.csv' if args.suffix else 'time_series.csv'
    ms_name = f'monthly_stats_{args.suffix}.csv' if args.suffix else 'monthly_stats.csv'

    scene_dirs = sorted(raw_dir.glob('*.SAFE'))
    if not scene_dirs:
        print('No hay escenas en data/raw/. Descomprime primero los .zip.')
        sys.exit(1)

    print(f'Procesando {len(scene_dirs)} escenas...')
    print()

    rows = []
    for i, scene_dir in enumerate(scene_dirs, 1):
        print(f'[{i}/{len(scene_dirs)}] {scene_dir.name}')
        row = process_scene(scene_dir, config)
        if row:
            rows.append(row)
        print()

    if not rows:
        print('No se procesó ninguna escena correctamente.')
        sys.exit(1)

    # Serie temporal completa
    df = pd.DataFrame(rows)
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date')
    df.to_csv(out_dir / ts_name, index=False)
    print(f'\nSerie temporal guardada: {out_dir / ts_name}')
    print(f'  Total escenas procesadas: {len(df)}')

    # Filtrar escenas con demasiada nube en el bbox
    bbox_cloud_max = 50
    n_before = len(df)
    df_valid = df[df['cloud_pct'] <= bbox_cloud_max].copy()
    n_dropped = n_before - len(df_valid)
    print(f'  Escenas con >50% nubes en bbox descartadas: {n_dropped}')
    print(f'  Escenas válidas para estadísticas: {len(df_valid)}')

    # Estadísticas mensuales (solo con escenas válidas)
    df_valid['year_month'] = df_valid['date'].dt.to_period('M')
    df_valid['month'] = df_valid['date'].dt.month
    df = df_valid

    indices_list = config.get('indices', ['NDVI', 'NDWI', 'MNDWI'])
    monthly_rows = []

    for month in range(1, 13):
        subset = df[df['month'] == month]
        if len(subset) == 0:
            continue

        month_row = {'month': month, 'n_scenes': len(subset)}
        for idx in indices_list:
            col = f'{idx}_mean'
            if col in subset.columns:
                vals = subset[col].dropna()
                month_row[f'{idx}_mean'] = float(vals.mean()) if len(vals) > 0 else np.nan
                month_row[f'{idx}_std']  = float(vals.std())  if len(vals) > 1 else np.nan
        monthly_rows.append(month_row)

    monthly = pd.DataFrame(monthly_rows)
    monthly.to_csv(out_dir / ms_name, index=False)
    print(f'Estadísticas mensuales guardadas: {out_dir / ms_name}')
    print()
    print(monthly.to_string(index=False))


if __name__ == '__main__':
    main()
