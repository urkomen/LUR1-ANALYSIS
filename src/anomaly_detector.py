import numpy as np
import pandas as pd

from paths import processing_opts, zone_dir


def load_timeseries(zone):
    ts = pd.read_csv(zone_dir(zone) / 'time_series.csv')
    ts['date'] = pd.to_datetime(ts['date'])
    return ts


def _normalized_doy(dates):
    '''
    Día del año remapeado a un calendario de referencia sin bisiesto (2001).

    pandas.dt.dayofyear usa el año real de cada fecha: en un año bisiesto
    (2024) todo lo posterior al 29 de febrero queda desplazado +1 respecto al
    mismo día calendario en un año normal (2025). Sin corregirlo, el 4 de
    octubre de 2024 y el 4 de octubre de 2025 —el mismo día del año— se
    calculan como si estuvieran a 1 día de distancia. El 29 de febrero se
    mapea al 28: es un único día cada 4 años y no afecta a una ventana de
    varias semanas.
    '''
    idx = pd.DatetimeIndex(dates)
    month = idx.month
    day = np.where((idx.month == 2) & (idx.day == 29), 28, idx.day)
    ref = pd.to_datetime({'year': 2001, 'month': month, 'day': day})
    return ref.dt.dayofyear.to_numpy()


def _doy_distance(doys, doy):
    '''
    Distancia en días del año, cerrando el círculo por fin de año: el 20 de
    diciembre y el 10 de enero están a 21 días, no a 344. `doys` y `doy` ya
    vienen normalizados a un año de referencia sin bisiesto (365 días), así
    que el módulo 365 es siempre correcto.
    '''
    d = np.abs(doys - doy)
    return np.minimum(d, 365 - d)


def detect_anomalies(config, zone):
    '''
    Marca como anómala cada escena que se aparta más de threshold_sigma de su
    climatología estacional.

    La referencia es una ventana de +-window_days alrededor del día del año de
    la escena, agrupando todos los años disponibles y *excluyendo la propia
    escena* (leave-one-out). Dos detalles importantes:

    - Ventana estacional, no mes natural. Agrupar por mes con dos años de
      datos deja 2-5 escenas por grupo, muestra con la que la desviación
      típica no significa nada. La ventana reúne 10-25 escenas usando
      exactamente los mismos datos, y evita el corte artificial por el que
      el 31 de julio y el 1 de agosto se comparaban contra poblaciones
      distintas.
    - Leave-one-out. Si la escena entra en la muestra que calcula su propia
      media y sigma, arrastra la referencia hacia sí misma y aparece el techo
      |z| = (n-1)/sqrt(n): con n=2 nada supera 0.71 sigma y con n=4 el techo
      es exactamente 1.5, así que los grupos pequeños serían incapaces de
      producir una anomalía por construcción, no por ausencia de eventos.
    '''
    threshold = config.get('anomaly_detector', {}).get('threshold_sigma', 2.0)
    window_days = config.get('anomaly_detector', {}).get('window_days', 45)
    indices = config.get('indices', ['NDVI', 'NDWI', 'MNDWI'])
    opts = processing_opts(config)
    max_bbox_cloud = opts['max_bbox_cloud_pct']
    min_ref = opts['min_ref_scenes']

    ts = load_timeseries(zone)

    ts_valid = ts[ts['cloud_pct'] <= max_bbox_cloud].copy().reset_index(drop=True)
    doys = _normalized_doy(ts_valid['date'])
    ts_valid['doy'] = doys

    results = []
    skipped = []

    for i, scene in ts_valid.iterrows():
        in_window = _doy_distance(doys, scene['doy']) <= window_days
        in_window[i] = False  # leave-one-out
        others = ts_valid[in_window]

        if len(others) < min_ref:
            skipped.append((scene['date'], len(others)))
            continue

        row = {
            'scene': scene['scene'],
            'date': scene['date'],
            'month': scene['date'].month,
            'cloud_pct': scene['cloud_pct'],
            'n_ref': len(others),
        }

        is_anomaly = False
        max_score = 0.0

        for idx in indices:
            mean_col = f'{idx}_mean'
            scene_val = scene.get(mean_col)
            ref_vals = others[mean_col].dropna() if mean_col in others else pd.Series(dtype=float)

            if pd.isna(scene_val) or len(ref_vals) < 2:
                row[f'{idx}_value'] = np.nan if pd.isna(scene_val) else float(scene_val)
                row[f'{idx}_zscore'] = np.nan
                row[f'{idx}_anomaly'] = False
                continue

            ref_mean = ref_vals.mean()
            ref_std = ref_vals.std()  # ddof=1

            if pd.isna(ref_std) or ref_std == 0:
                row[f'{idx}_value'] = float(scene_val)
                row[f'{idx}_zscore'] = np.nan
                row[f'{idx}_anomaly'] = False
                continue

            zscore = (scene_val - ref_mean) / ref_std
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

    if skipped:
        print(f'  Escenas omitidas por tener menos de {min_ref} referencias '
              f'en +-{window_days} días: {len(skipped)}')
        for date, n in skipped[:5]:
            print(f'    · {date.date()} (n_ref={n})')
        if len(skipped) > 5:
            print(f'    · ... y {len(skipped) - 5} más')

    out_path = zone_dir(zone) / 'anomalies.csv'

    if not results:
        # Sin resultados no hay columnas que ordenar; construimos el CSV vacío
        # con la cabecera esperada para no romper a quien lo lea después.
        cols = ['scene', 'date', 'month', 'cloud_pct', 'n_ref']
        for idx in indices:
            cols += [f'{idx}_value', f'{idx}_zscore', f'{idx}_anomaly']
        cols += ['is_anomaly', 'max_zscore']
        df = pd.DataFrame(columns=cols)
        df.to_csv(out_path, index=False)

        print(f'Detector de anomalías — zona "{zone}" (umbral: {threshold}σ)')
        print('  Ninguna escena evaluable.')
        if len(ts) == 0:
            print('  La serie temporal está vacía.')
        elif len(ts_valid) == 0:
            print(f'  Las {len(ts)} escenas superan el {max_bbox_cloud} % de nubes en el bbox.')
            print('  Sube processing.max_bbox_cloud_pct si quieres incluir escenas más nubosas.')
        else:
            print(f'  Ninguna escena reúne {min_ref} referencias en ±{window_days} días.')
            print('  Amplía el rango de fechas, sube anomaly_detector.window_days')
            print('  o baja processing.min_ref_scenes.')
        print(f'\n  Resultados guardados: {out_path}')
        return df

    df = pd.DataFrame(results).sort_values('date')
    df.to_csv(out_path, index=False)

    n_anomalies = df['is_anomaly'].sum()
    print(f'Detector de anomalías — zona "{zone}" (umbral: {threshold}σ)')
    print(f'  Escenas analizadas: {len(df)}')
    print(f'  Anomalías detectadas: {n_anomalies}')

    if n_anomalies > 0:
        print('\n  Escenas anómalas:')
        anomalies = df[df['is_anomaly']]
        for _, a in anomalies.iterrows():
            flags = []
            for idx in indices:
                if a.get(f'{idx}_anomaly', False):
                    flags.append(f'{idx} z={a[f"{idx}_zscore"]:+.2f}')
            print(f'    {a["date"].strftime("%Y-%m-%d")} — {", ".join(flags)}')

    print(f'\n  Resultados guardados: {out_path}')
    return df
