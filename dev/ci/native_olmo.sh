#!/usr/bin/env bash
# OLMo Eval native acceptance + conformance in an isolated checkout synced
# from its frozen upstream lock (the only supported OLMo delivery mode).
# Usage: dev/ci/native_olmo.sh [CHECKOUT_DIR]
set -euo pipefail
REVISION=73ade80e24f796af55caeb8fd7b75a7f3fd607fd
CHECKOUT=${1:-${RUNNER_TEMP:-/tmp}/aiq-ci-olmo}
REPO=${OLMO_REPO:-https://github.com/allenai/olmo-eval.git}
if [ ! -d "$CHECKOUT/.git" ]; then
  git clone -q "$REPO" "$CHECKOUT"
fi
git -C "$CHECKOUT" checkout -q "$REVISION"
test -z "$(git -C "$CHECKOUT" status --porcelain --untracked-files=no)"
for attempt in 1 2 3; do
  (cd "$CHECKOUT" && uv sync -q --frozen --no-default-groups --extra litellm --extra agents --python 3.12) && break
  [ "$attempt" = 3 ] && { echo 'external: uv sync failed 3 times' >&2; exit 1; }
  sleep $((attempt * 10))
done
uv pip install -q --python "$CHECKOUT/.venv/bin/python" pytest
PYTHONPATH="$PWD" "$CHECKOUT/.venv/bin/python" -m pytest -q \
  tests/native/test_olmo_native.py tests/native/test_conformance.py
