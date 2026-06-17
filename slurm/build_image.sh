#!/usr/bin/env bash
# Build the TPC solver runtime WITHOUT root on this cluster.
#
# Why this exists: `singularity build` from a `Bootstrap: docker` source with a
# `%post` step requires root (or --fakeroot / --remote / proot). This cluster has
# no subuid/subgid allocation for us, no fakeroot/proot binary, and no Sylabs
# remote token, so slurm/tpc-solver-py312.def cannot be baked here directly.
# (That .def remains the declarative, fully-baked spec and builds on any node
#  that has fakeroot/root -- keep its pinned deps in sync with the list below.)
#
# Rootless equivalent (what this script does):
#   1. Pull the base python:3.12-slim SIF. Pulling is a pure image conversion
#      (no %post), so it works as a non-root user.
#   2. Create a 3.12 venv on the shared BeeGFS ($HOME/tpc-venv), bind-mounted at
#      runtime. The container interpreter is 3.12, so the venv is 3.12 too --
#      this preserves the repo's 3.12-only convention without fakeroot.
#   3. pip install the SAME pinned deps as the .def into that venv.
# Result: compute nodes run the solver with the container's 3.12 interpreter and
# the pinned deps -- no root, no internet at runtime.
#
# Keep this pinned list IN SYNC with slurm/tpc-solver-py312.def.
set -euo pipefail

SIF_DIR="$HOME/sif"
BASE_SIF="$SIF_DIR/python-312-slim.sif"
VENV_DIR="$HOME/tpc-venv"   # on BeeGFS via $HOME -> /beegfs/...

source /usr/share/modules/init/bash
module purge
module load singularity/4.4
echo "[build] singularity $(singularity version)"

mkdir -p "$SIF_DIR"

# 1. Base image (idempotent: reuse if present).
if [[ ! -f "$BASE_SIF" ]]; then
    echo "[build] pulling python:3.12-slim -> $BASE_SIF"
    singularity pull --force "$BASE_SIF" docker://python:3.12-slim
else
    echo "[build] base image present: $BASE_SIF"
fi

# 2. (Re)create the venv with the container's 3.12 interpreter.
echo "[build] creating venv at $VENV_DIR"
rm -rf "$VENV_DIR"
singularity exec --bind /beegfs "$BASE_SIF" python -m venv "$VENV_DIR"

# 3. Install pinned deps (mirrors tpc-solver-py312.def %post).
echo "[build] pip install pinned deps"
singularity exec --bind /beegfs "$BASE_SIF" "$VENV_DIR/bin/python" -m pip install --no-cache-dir --upgrade pip
singularity exec --bind /beegfs "$BASE_SIF" "$VENV_DIR/bin/python" -m pip install --no-cache-dir \
    numpy==2.4.6 \
    pandas==2.2.3 \
    geopy==2.4.1 \
    fuzzywuzzy==0.18.0 \
    python-Levenshtein==0.27.1 \
    scikit-learn==1.5.2 \
    tqdm==4.66.6 \
    func-timeout==4.3.5 \
    datasets==3.3.2 \
    ortools==9.15.6755 \
    z3-solver==4.14.1.0 \
    jsonschema==4.23.0 \
    json-repair==0.30.0 \
    packaging==24.2

# 4. Self-check (every solver import must resolve; 3.12 confirmed).
echo "[build] self-check"
singularity exec --bind /beegfs "$BASE_SIF" "$VENV_DIR/bin/python" -c \
    "import sys,ortools,z3,numpy,pandas,sklearn,geopy,func_timeout,datasets,json_repair,jsonschema,fuzzywuzzy; print('import-ok', sys.version.split()[0])"

echo "[build] done."
echo "[build] Run the solver with:"
echo "       module load singularity/4.4"
echo "       singularity exec --bind /beegfs $BASE_SIF $VENV_DIR/bin/python scripts/solve.py --split <name> ..."
