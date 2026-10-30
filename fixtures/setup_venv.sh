#!/usr/bin/env bash
# Rebuild the pinned eval venv (gitignored) used by eval/verify_ground_truth.py and eval/run_eval.py.
set -euo pipefail
cd "$(dirname "$0")/.."
uv pip compile fixtures/requirements.in -o fixtures/requirements.lock --python-version 3.12
uv venv --python 3.12 fixtures/.venv
uv pip install --python fixtures/.venv/bin/python -r fixtures/requirements.lock
fixtures/.venv/bin/python -c "import numpy, pandas, requests, yfinance; print(numpy.__version__, pandas.__version__, requests.__version__, yfinance.__version__)"
