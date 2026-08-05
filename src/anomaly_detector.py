import numpy as np
import pandas as pd
from pathlib import Path


def load_timeseries(processed_dir='data/processed'):
    ts = pd.read_csv(Path(processed_dir) / 'time_series.csv')
    ts['date'] = pd.to_datetime(ts['date'])
    return ts


def load_monthly_stats(processed_dir='data/processed'):
    ms = pd.read_csv(Path(processed_dir) / 'monthly_stats.csv')
    return ms


def detect_anomalies(config, processed_dir='data/processed', bbox_cloud_max=50):
    threshold = config.get('anomaly_detector', {}).get('threshold_sigma', 2.0)
    indices = config.get('indices', ['NDVI', 'NDWI', 'MNDWI'])

    ts = load_timeseries(processed_dir)
    ms = load_monthly_stats(processed_dir)

    ts_valid = ts[ts['cloud_pct'] <= bbox_cloud_max].copy()
    ts_valid['month'] = ts_valid['date'].dt.month

    monthly_lookup = {}
    for _, row in ms.iterrows():
        monthly_lookup[int(row['month'])] = row

    results = []
    for _, scene in ts_valid.iterrows():
        month = scene['month']
        ref = monthly_lookup.get(month)
        if ref is None:
            continue

        row = {
            'scene': scene['scene'],
            'date': scene['date'],
            'month': month,
            'cloud_pct': scene['cloud_pct'],
        }

        is_anomaly = False
        max_score = 0.0

        for idx in indices:
            mean_col = f'{idx}_mean'
            std_col = f'{idx}_std'

            scene_val = scene.get(mean_col)
            month_mean = ref.get(mean_col)
            month_std = ref.get(std_col)

            if pd.isna(scene_val) or pd.isna(month_mean) or pd.isna(month_std) or month_std == 0:
                row[f'{idx}_value'] = scene_val if not pd.isna(scene_val) else np.nan
                row[f'{idx}_zscore'] = np.nan
                row[f'{idx}_anomaly'] = False
                continue

            zscore = (scene_val - month_mean) / month_std
            anomalous = abs(zscore) > threshold

            row[f'{idx}_value'] = float(scene_val)
            row[f'{idx}_zscore'] = float(zscore)
            row[f'{idx}_anomaly'] = anomalous

            if anomalous:
                is_anomaly = True
            max_score = max(max_score, abs(zscore))

        row['is_anomaly'] = is_anomaly
        row['max_zscore'] = max_score
        results.append(row)

    df = pd.DataFrame(results)
    df = df.sort_values('date')

    out_path = Path(processed_dir) / 'anomalies.csv'
    df.to_csv(out_path, index=False)

    n_anomalies = df['is_anomaly'].sum()
    print(f'Detector de anomalías (umbral: {threshold}σ)')
    print(f'  Escenas analizadas: {len(df)}')
    print(f'  Anomalías detectadas: {n_anomalies}')

    if n_anomalies > 0:
        print(f'\n  Escenas anómalas:')
        anomalies = df[df['is_anomaly']]
        for _, a in anomalies.iterrows():
            flags = []
            for idx in indices:
                if a.get(f'{idx}_anomaly', False):
                    flags.append(f'{idx} z={a[f"{idx}_zscore"]:+.2f}')
            print(f'    {a["date"].strftime("%Y-%m-%d")} — {", ".join(flags)}')

    print(f'\n  Resultados guardados: {out_path}')
    return df
