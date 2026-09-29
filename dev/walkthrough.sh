#!/usr/bin/env bash
# Clean-environment walkthrough (plan phase 8): a fresh engine-free core venv
# drives the public CLI; each engine runs only in its own worker interpreter.
# Covers generation (HELM, Inspect, OLMo) and agentic/tool examples (Inspect
# sandbox tool, OLMo OpenAI Agents against a local OpenAI-compatible server).
#
# Usage (repository root): dev/walkthrough.sh WORK_DIR
#   INSPECT_PY / HELM_PY / OLMO_PY select worker interpreters.
set -euo pipefail
WORK=${1:?usage: dev/walkthrough.sh WORK_DIR}
INSPECT_PY=${INSPECT_PY:-/tmp/aiq-inspect-p1/bin/python}
HELM_PY=${HELM_PY:-/tmp/aiq-helm-p1/bin/python}
OLMO_PY=${OLMO_PY:-/tmp/olmo-eval-p1/.venv/bin/python}
STORE=$WORK/store
mkdir -p "$WORK"

uv venv -q --python 3.11 "$WORK/core"
uv pip install -q --python "$WORK/core/bin/python" -e .
"$WORK/core/bin/python" -c "
import importlib.util
assert not [m for m in ('inspect_ai', 'olmo_eval', 'helm') if importlib.util.find_spec(m)]
print('core venv is engine-free')"
CLI="$WORK/core/bin/aiq-evals"

for example in examples/*.json; do "$CLI" validate "$example" > /dev/null; done
echo "all examples validate statically"

ensure() {  # ensure REQUEST WORKER EXPECTED_ACTION
  out=$("$CLI" ensure "$1" --store "$STORE" --worker-python "$2")
  action=$(printf '%s' "$out" | "$WORK/core/bin/python" -c 'import json,sys; d=json.load(sys.stdin); print(d["action"], d["status"])')
  echo "$(basename "$1"): $action"
  [ "$action" = "$3 succeeded" ] || { echo "expected $3 succeeded" >&2; exit 1; }
  RUN_PATH=$(printf '%s' "$out" | "$WORK/core/bin/python" -c 'import json,sys; print(json.load(sys.stdin)["path"])')
}

# Generation.
ensure examples/helm_request.json "$HELM_PY" executed
ensure examples/helm_request.json "$HELM_PY" reused
"$CLI" show "$RUN_PATH" > "$WORK/helm-show.json"
ensure examples/inspect_generation_request.json "$INSPECT_PY" executed
ensure examples/olmo_local_request.json "$OLMO_PY" executed
ensure examples/olmo_local_request.json "$OLMO_PY" reused

# One-shot run and native import, also resolved/read only inside the worker.
"$CLI" run examples/inspect_generation_request.json --output "$WORK/inspect-run" --worker-python "$INSPECT_PY" > /dev/null
"$CLI" import-native examples/inspect_generation_request.json "$WORK/inspect-run/native/inspect_ai/logs" \
  --output "$WORK/inspect-import" --worker-python "$INSPECT_PY" > /dev/null
echo "inspect run + import-native through the worker: succeeded"

# Agentic / tools.
ensure examples/inspect_local_sandbox_request.json "$INSPECT_PY" executed
"$WORK/core/bin/python" -m tests.native.chat_server --port-file "$WORK/port" &
SERVER=$!
trap 'kill $SERVER 2>/dev/null || true' EXIT
for _ in $(seq 50); do [ -s "$WORK/port" ] && break; sleep 0.1; done
"$WORK/core/bin/python" - "$WORK/port" "$WORK/olmo_agent_request.json" <<'PY'
import json, sys
port = open(sys.argv[1]).read().strip()
request = {
    "schema_version": 1, "engine": "olmo_eval", "task": "aiq_p1_tool",
    "task_revision": "fixture-v1", "data_revision": "fixture-v1",
    "models": [{"role": "primary", "model": "gpt-4o-mini", "provider": "litellm",
                "revision": "local-script-v1", "cache_token": None,
                "provider_options": {"base_url": f"http://127.0.0.1:{port}/v1"}}],
    "task_options": {}, "generation": {},
    "engine_options": {
        "upstream_revision": "73ade80e24f796af55caeb8fd7b75a7f3fd607fd",
        "task_modules": ["tests.native.olmo_fixture"],
        "required_secrets": ["OPENAI_API_KEY"],
        "harness_config": {"scaffold": "openai_agents", "tools": ["double"],
                           "scaffold_kwargs": {"enable_compaction": False}},
    },
}
json.dump(request, open(sys.argv[2], "w"))
PY
OPENAI_API_KEY=local-walkthrough-key ensure "$WORK/olmo_agent_request.json" "$OLMO_PY" executed
if grep -rq local-walkthrough-key "$STORE" --include='*.json'; then
  echo "secret value found in the store" >&2; exit 1
fi
echo "walkthrough passed"
