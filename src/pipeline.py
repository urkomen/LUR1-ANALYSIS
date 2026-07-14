import argparse
import yaml


class Pipeline:
    def __init__(self, config_path: str):
        with open(config_path) as f:
            self.config = yaml.safe_load(f)
        print(f"Pipeline inicializado: {self.config['location']['name']}")

    def download(self):
        print("[download] pendiente de implementar")

    def preprocess(self):
        print("[preprocess] pendiente de implementar")

    def classify(self):
        print("[classify] pendiente de implementar")

    def detect_anomalies(self):
        print("[detect_anomalies] pendiente de implementar")

    def run_full(self):
        self.download()
        self.preprocess()
        self.classify()
        self.detect_anomalies()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, help="Ruta al fichero config.yaml")
    args = parser.parse_args()

    pipeline = Pipeline(args.config)
    pipeline.run_full()
