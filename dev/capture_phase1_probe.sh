#!/usr/bin/env bash
set -euo pipefail
mkdir -p phase1-artifacts
python -m magnet_evals phase1-probe --output phase1-artifacts/environment.json "$@"
