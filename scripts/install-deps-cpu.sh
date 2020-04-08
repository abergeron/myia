#!/bin/sh
set -e

poetry install
python scripts/make-reqs.py custom.tool.conda.dependencies > requirements.conda
python scripts/make-reqs.py custom.tool.conda.cpu-dependencies >> requirements.conda
conda install -y --file=requirements.conda
