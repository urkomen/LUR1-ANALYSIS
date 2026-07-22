import argparse
import sys
from pathlib import Path
import yaml

sys.path.insert(0, str(Path(__file__).parent))
from downloader import download as _download
from preprocessor import preprocess as _preprocess
from indices import calculate_indices


class Pipeline:
    def __init__(self, config_path: str):
        with open(config_path) as f:
            self.config = yaml.safe_load(f)
        self.scenes = []
        self.processed = []
        print(f'Pipeline inicializado: {self.config["location"]["name"]}')

    def download(self):
        self.scenes = _download(self.config)

    def preprocess(self):
        raw_dir = Path('data/raw')
        scene_dirs = sorted(raw_dir.glob('*.SAFE'))
        if not scene_dirs:
            print('[preprocess] No hay escenas en data/raw/')
            return
        for scene_dir in scene_dirs:
            print(f'Preprocesando: {scene_dir.name}')
            result = _preprocess(scene_dir, self.config)
            print('Calculando índices espectrales...')
            result['indices'] = calculate_indices(
                result['bands'],
                self.config.get('indices', ['NDVI', 'NDWI', 'MNDWI'])
            )
            self.processed.append(result)
        print(f'Preprocesado completado: {len(self.processed)} escena(s)')

    def classify(self):
        print('[classify] pendiente de implementar')

    def detect_anomalies(self):
        print('[detect_anomalies] pendiente de implementar')

    def run_full(self):
        self.download()
        self.preprocess()
        self.classify()
        self.detect_anomalies()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True, help='Ruta al fichero config.yaml')
    args = parser.parse_args()

    pipeline = Pipeline(args.config)
    pipeline.run_full()
