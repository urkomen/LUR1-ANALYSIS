CONFIG ?= config/costa_vasca.yaml

run:
	python src/pipeline.py --config $(CONFIG)

clean-raw:
	rm -rf data/raw/*
