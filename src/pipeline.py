import argparse
import sys
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).parent))
from downloader import download as _download
from extractor import extract as _extract
from timeseries import build_timeseries as _build_timeseries
from classifier import (
    class_composition,
    classify_scene,
    load_model,
    model_name_from_config,
)
from anomaly_detector import detect_anomalies as _detect_anomalies
from paths import RAW_DIR, zone_from_config, zone_dir
from preprocessor import preprocess as _preprocess

STEPS = ['download', 'extract', 'timeseries', 'anomalies', 'classify']


class Pipeline:
    def __init__(self, config_path: str):
        with open(config_path) as f:
            self.config = yaml.safe_load(f)
        self.zone = zone_from_config(config_path)
        self.anomalies = None
        print(f'Pipeline: {self.config["location"]["name"]} (zona: {self.zone})')

    def download(self):
        print('\n=== Descarga ===')
        _download(self.config, self.zone)

    def extract(self):
        print('\n=== Extracción ===')
        _extract(self.zone)

    def timeseries(self):
        print('\n=== Serie temporal ===')
        _build_timeseries(self.config, self.zone)

    def anomalies_step(self):
        print('\n=== Detección de anomalías ===')
        self.anomalies = _detect_anomalies(self.config, self.zone)

    def classify(self):
        '''
        Clasifica la cobertura de las escenas anómalas y guarda la composición
        por clase. Solo las anómalas: son las que interesan y así el consumo de
        memoria no depende del tamaño de la serie.
        '''
        print('\n=== Clasificación de escenas anómalas ===')
        anomalies = self._load_anomalies()
        if anomalies is None or anomalies.empty:
            print('No hay anomalías que clasificar.')
            return

        # Paso auxiliar: el entregable son las fechas anómalas, así que si el
        # modelo no está disponible se avisa y se continúa hasta el informe.
        try:
            model = load_model(model_name_from_config(self.config))
        except FileNotFoundError as e:
            print(f'Clasificación omitida — {e}')
            return

        rows = []

        for _, a in anomalies.iterrows():
            scene_dir = RAW_DIR / a['scene']
            if not scene_dir.is_dir():
                print(f'  Escena no disponible, omitiendo: {a["scene"]}')
                continue

            print(f'  Clasificando {a["date"].date()} — {a["scene"]}')
            scene = _preprocess(scene_dir, self.config)
            composition = class_composition(classify_scene(scene, model))

            row = {'date': a['date'].date(), 'scene': a['scene']}
            row.update({f'pct_{c}': pct for c, pct in composition.items()})
            rows.append(row)

        if not rows:
            return

        df = pd.DataFrame(rows).fillna(0.0)
        out_path = zone_dir(self.zone) / 'anomalies_classified.csv'
        df.to_csv(out_path, index=False)
        print(f'\nComposición por clase guardada: {out_path}')
        print(df.to_string(index=False))

    def _load_anomalies(self):
        if self.anomalies is not None:
            df = self.anomalies
        else:
            path = zone_dir(self.zone) / 'anomalies.csv'
            if not path.exists():
                print(f'No existe {path}. Ejecuta antes el paso "anomalies".')
                return None
            df = pd.read_csv(path)
            df['date'] = pd.to_datetime(df['date'])
        return df[df['is_anomaly']].sort_values('date')

    def report(self):
        '''Resumen final: las fechas anómalas, que son el resultado del pipeline.'''
        anomalies = self._load_anomalies()
        threshold = self.config.get('anomaly_detector', {}).get('threshold_sigma', 2.0)

        print('\n' + '=' * 62)
        print(f'RESULTADO — {self.config["location"]["name"]}')
        print('=' * 62)

        if anomalies is None or anomalies.empty:
            print(f'Sin anomalías por encima de {threshold}σ.')
            print('Prueba a bajar anomaly_detector.threshold_sigma en el config.')
            return

        indices = self.config.get('indices', ['NDVI', 'NDWI', 'MNDWI'])
        print(f'{len(anomalies)} fecha(s) anómala(s) por encima de {threshold}σ:\n')
        for _, a in anomalies.iterrows():
            flags = [
                f'{idx} z={a[f"{idx}_zscore"]:+.2f}'
                for idx in indices
                if a.get(f'{idx}_anomaly', False)
            ]
            print(f'  {a["date"].date()}   {", ".join(flags)}')

        print('\nContrasta estas fechas con registros meteorológicos para')
        print('identificar qué evento las provocó.')
        print(f'Detalle completo: {zone_dir(self.zone) / "anomalies.csv"}')

    def run(self, steps=None):
        steps = steps or STEPS
        actions = {
            'download': self.download,
            'extract': self.extract,
            'timeseries': self.timeseries,
            'anomalies': self.anomalies_step,
            'classify': self.classify,
        }
        for step in steps:
            actions[step]()
        self.report()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Detecta anomalías espectrales en una zona a partir de imagen Sentinel-2.'
    )
    parser.add_argument('--config', required=True, help='Ruta al fichero config.yaml')
    parser.add_argument(
        '--steps', nargs='+', choices=STEPS, default=None,
        help=f'Pasos a ejecutar (por defecto todos: {" ".join(STEPS)}). '
             f'Útil para reprocesar sin volver a descargar.'
    )
    args = parser.parse_args()

    Pipeline(args.config).run(args.steps)
