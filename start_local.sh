#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
python -m pip install -r requirements.txt
# Python supervisor starts/stops the separate run_web.py and run.py processes.
python -m scripts.local_supervisor
