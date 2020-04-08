#!/bin/bash

set -x
set -e

DEV=cpu

while [[ $# -gt 0 ]]; do
  key="$1"
  case $key in
    --gpu)
    DEV=gpu
    shift
    ;;
esac
done

if [ ! -d $HOME/miniconda ]; then
    wget -nv https://repo.continuum.io/miniconda/Miniconda3-latest-`uname -s`-`uname -m`.sh -O miniconda.sh
    bash miniconda.sh -b -p $HOME/miniconda
fi
export PATH="$HOME/miniconda/bin:$PATH"
hash -r
conda config --set always_yes yes --set changeps1 no
conda update -q conda
conda create -y -n test python=3.7
conda init
. $HOME/miniconda/etc/profile.d/conda.sh
conda activate test
pip install poetry
poetry install
python scripts/make-reqs.py custom.tool.conda.dependencies > requirements.conda
python scripts/make-reqs.py custom.tool.conda.$DEV-dependencies >> requirements.conda
conda install -y --file=requirements.conda
cat blahblahblah
