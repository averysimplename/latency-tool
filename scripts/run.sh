#!/usr/bin/env bash
set -euo pipefail

# shellcheck disable=SC1091
source myenv/bin/activate
python run.py
