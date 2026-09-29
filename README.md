# aiq-evals

`aiq-evals` is a backend-agnostic evaluation runtime and artifact interface.
Its intended high-level operation is:

```text
fully specified evaluation request
        |
        v
resolve measurement identity
        |
        +---- reusable compatible result exists? ----+
        |                                            |
       yes                                           no
        |                                            |
        v                                            v
load / import                                 execute native engine
        |                                            |
        +----------------------+---------------------+
                               |
                               v
                  normalized evaluation result
```

The initial engines are HELM, OLMo Eval, and Inspect. `aiq-evals` is not a
scheduler and is not a scientific claim system. MAGNET is expected to consume
its results and decide how a selected metric becomes claim evidence.

## Current status

Phases 2 and 3 now have an implementation, while the native phase-1 acceptance
gates remain deliberately open. The OLMo adapter targets the API seam inspected
at commit `73ade80e24f796af55caeb8fd7b75a7f3fd607fd`; it is not declared a
supported upstream pin until the native smoke/tool/cancellation fixtures pass.

Implemented now:

- versioned dependency-free request, resolution, result, sample, and metric contracts;
- strict JSON/static validation with credentials separated into execution context;
- canonical measurement identity and explicit no-reuse reasons;
- lazy backend registration;
- sync/async execution and native-import facades;
- isolated worker-process execution with timeout/cancellation termination;
- atomic terminal run bundles with native checksums and normalized artifact identity;
- a content-addressed filesystem result store and engine-free readers;
- a frozen schema-v1 compatibility fixture;
- an experimental OLMo Eval adapter using `HarnessConfig`, `AsyncEvalRunner.validate()`,
  and `run_async()`;
- OLMo nested metric/scorer preservation, coverage accounting, predictions/trajectories,
  hard-failure handling, and native artifact import validation.

The implementation is intentionally provisional. Native OLMo runtime acceptance,
OLMo packaging selection, EEE gap analysis, Inspect, HELM, and MAGNET integration
remain open and are tracked under `docs/planning/`.

## Bootstrap

```bash
python -m pip install -e '.[tests]'
pytest -q
aiq-evals phase1-status
aiq-evals phase1-probe
aiq-evals backends
```

A request is JSON-shaped and contains measurement inputs only. Credentials stay
in the execution environment rather than the persisted request. For example:

```json
{
  "schema_version": 1,
  "engine": "olmo_eval",
  "task": "my_registered_task",
  "task_revision": "<immutable-task-revision>",
  "data_revision": "<immutable-data-revision>",
  "models": [{
    "role": "primary",
    "model": "my-model",
    "provider": "mock",
    "revision": "<immutable-model-revision>",
    "cache_token": null,
    "provider_options": {}
  }],
  "task_options": {"limit": 4},
  "generation": {"temperature": 0.0},
  "engine_options": {
    "upstream_revision": "73ade80e24f796af55caeb8fd7b75a7f3fd607fd"
  }
}
```

Static validation does not import OLMo Eval:

```bash
aiq-evals validate request.json
```

Resolution and execution require the native engine environment. A separate
worker interpreter can be selected without adding the engine to core:

```bash
aiq-evals resolve request.json
aiq-evals run request.json --output run-dir --worker-python /path/to/worker/python
aiq-evals show run-dir
```

To inspect exact upstream source checkouts without importing them:

```bash
aiq-evals phase1-probe \
    --checkout olmo_eval=/path/to/olmo-eval \
    --checkout inspect_ai=/path/to/inspect_ai \
    --checkout helm=/path/to/helm \
    --output phase1-artifacts/local-probe.json
```

The probe is deliberately non-executing. Native generation/tool/cancellation
fixtures are the next phase-1 acceptance work.

## Planning

- `docs/planning/aiq-evals-plan.md`: work owned by this repository.
- `docs/planning/aiq-magnet-integration-plan.md`: work that belongs in MAGNET.
- `docs/planning/phase1-evidence.md`: canonical phase-1 native acceptance ledger.
- `docs/planning/phase2-phase3-evidence.md`: implementation evidence and remaining native gates.
- `docs/planning/architecture.md`: package boundary and identity model.
