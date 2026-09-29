#!/usr/bin/env bash
# Inspect native acceptance + conformance at the verified pin.
# Usage: dev/ci/native_inspect.sh [VENV_DIR]
set -euo pipefail
VENV=${1:-${RUNNER_TEMP:-/tmp}/aiq-ci-inspect}
uv venv -q --python 3.11 "$VENV"
for attempt in 1 2 3; do  # bounded retries: installation is the external step
  uv pip install -q --python "$VENV/bin/python" \
    -c dev/environments/phase1/inspect-py311-constraints.txt -e '.[inspect,tests]' && break
  [ "$attempt" = 3 ] && { echo 'external: dependency installation failed 3 times' >&2; exit 1; }
  sleep $((attempt * 10))
done
"$VENV/bin/python" -m pytest -q tests/native/test_inspect_native.py tests/native/test_conformance.py \
  tests/native/test_examples_native.py
