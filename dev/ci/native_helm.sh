#!/usr/bin/env bash
# HELM adapter native acceptance + conformance at crfm-helm 0.5.14.
# MAGNET compatibility tests run only when MAGNET_DIR names a checkout.
# Usage: dev/ci/native_helm.sh [VENV_DIR]
set -euo pipefail
VENV=${1:-${RUNNER_TEMP:-/tmp}/aiq-ci-helm}
uv venv -q --python 3.12 "$VENV"
EXTRA=()
if [ -n "${MAGNET_DIR:-}" ]; then EXTRA+=(-e "$MAGNET_DIR[helm]"); fi
for attempt in 1 2 3; do
  uv pip install -q --python "$VENV/bin/python" \
    -c dev/environments/phase1/helm-py312-constraints.txt \
    -e '.[tests]' 'crfm-helm==0.5.14' "${EXTRA[@]}" && break
  [ "$attempt" = 3 ] && { echo 'external: dependency installation failed 3 times' >&2; exit 1; }
  sleep $((attempt * 10))
done
PATH="$VENV/bin:$PATH" "$VENV/bin/python" -m pytest -q \
  tests/native/test_helm_adapter_native.py tests/native/test_helm_native.py tests/native/test_conformance.py
