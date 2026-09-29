#!/usr/bin/env bash
# Clean-environment walkthrough (plan phase 8): a fresh engine-free core venv
# drives the public CLI; each engine runs only in its own worker interpreter.
# Covers generation (HELM, Inspect, OLMo), agentic/tool examples (Inspect tool
# and sandbox tool, OLMo OpenAI Agents against the example local endpoint), and
# content-keyed native import. Every request uses installed example modules
# (magnet_evals.examples), so no source checkout is needed on the worker side.
#
# Usage (repository root): dev/walkthrough.sh WORK_DIR
#   INSPECT_PY / HELM_PY / OLMO_PY select worker interpreters.
set -euo pipefail
WORK=${1:?usage: dev/walkthrough.sh WORK_DIR}
INSPECT_PY=${INSPECT_PY:?set INSPECT_PY to an Inspect worker interpreter}
HELM_PY=${HELM_PY:?set HELM_PY to a HELM worker interpreter}
OLMO_PY=${OLMO_PY:?set OLMO_PY to an OLMo worker interpreter}
STORE=$WORK/store
mkdir -p "$WORK"

uv venv -q --python 3.11 "$WORK/core"
uv build -q --wheel --out-dir "$WORK/dist" .
uv pip install -q --python "$WORK/core/bin/python" "$WORK"/dist/*.whl
"$WORK/core/bin/python" -c "
import importlib.util
assert not [m for m in ('inspect_ai', 'olmo_eval', 'helm') if importlib.util.find_spec(m)]
print('core venv is engine-free')"
CLI="$WORK/core/bin/aiq-magnet-evals"

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

# Agentic / tools: all from the installed magnet_evals.examples modules.
ensure examples/inspect_tool_request.json "$INSPECT_PY" executed
ensure examples/inspect_local_sandbox_request.json "$INSPECT_PY" executed
"$WORK/core/bin/python" -m magnet_evals.examples.chat_server --port-file "$WORK/port" > /dev/null &
SERVER=$!
trap 'kill $SERVER 2>/dev/null || true' EXIT
for _ in $(seq 50); do [ -s "$WORK/port" ] && break; sleep 0.1; done
"$WORK/core/bin/python" - "$WORK/port" examples/olmo_agent_request.json "$WORK/olmo_agent_request.json" <<'PY'
import json, sys
port = open(sys.argv[1]).read().strip()
request = json.load(open(sys.argv[2]))
request["models"][0]["provider_options"]["base_url"] = f"http://127.0.0.1:{port}/v1"
json.dump(request, open(sys.argv[3], "w"))
PY
OPENAI_API_KEY=local-walkthrough-key ensure "$WORK/olmo_agent_request.json" "$OLMO_PY" executed

# Import the same native artifacts twice (reused), then edited ones (imported).
IMPORT_SRC=$WORK/inspect-run/native/inspect_ai/logs
ensure_import() {  # ensure_import EXPECTED_ACTION
  out=$("$CLI" ensure examples/inspect_generation_request.json --store "$WORK/import-store" \
        --worker-python "$INSPECT_PY" --import-source "$IMPORT_SRC")
  action=$(printf '%s' "$out" | "$WORK/core/bin/python" -c 'import json,sys; print(json.load(sys.stdin)["action"])')
  echo "import-native via ensure: $action"
  [ "$action" = "$1" ] || { echo "expected $1" >&2; exit 1; }
}
ensure_import imported
ensure_import reused
cp -r "$IMPORT_SRC" "$WORK/logs-copy" && IMPORT_SRC=$WORK/logs-copy
printf 'extra\n' > "$IMPORT_SRC/NOTE.txt"
ensure_import imported

if grep -rq local-walkthrough-key "$STORE" --include='*.json'; then
  echo "secret value found in the store" >&2; exit 1
fi
echo "walkthrough passed"
