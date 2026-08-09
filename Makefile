CONFIG ?= config/costa_vasca.yaml

# Pipeline completo: descarga, extrae, calcula la serie temporal,
# detecta anomalías y clasifica las escenas anómalas.
run:
	python src/pipeline.py --config $(CONFIG)

# Reprocesa a partir de las escenas ya descargadas.
reprocess:
	python src/pipeline.py --config $(CONFIG) --steps timeseries anomalies classify

# Recalcula solo las anomalías (p. ej. tras cambiar threshold_sigma).
anomalies:
	python src/pipeline.py --config $(CONFIG) --steps anomalies

# Entrena el modelo de clasificación (necesita etiquetas manuales).
train:
	python src/classifier.py --config $(CONFIG)

# Figuras de las escenas anómalas.
figures:
	python run_visualizations.py --config $(CONFIG)

.PHONY: run reprocess anomalies train figures
