# aiq-magnet-evals API, CLI, and contracts

This surface is not frozen: it changes as the MAGNET integration requires, until
a PyPI release freezes it (ADR-0010). Adapter modules (`magnet_evals.backends.*`)
and the worker protocol are internal. What each engine/task/provider combination
actually supports is recorded in `planning/phase1-capabilities.md`.

## Python API (`import magnet_evals`)

| Name | Purpose |
| --- | --- |
| `EvaluationRequest`, `ModelBinding` | Measurement inputs: engine, task, revisions, model roles, task/generation/engine options. JSON-shaped; credential-bearing keys are rejected. |
| `ExecutionContext` | Operational inputs that never enter identity: `output_dir`, `env` (secrets), `worker_python`, `timeout_seconds`. |
| `validate_request(request)` | Static validation. Imports no engine and no task code. |
| `resolve_evaluation(request)` / `resolve_evaluation_async(request, context)` | Native resolution and measurement identity. The async form runs inside `context.worker_python` when one is given. |
| `run_evaluation[_async](request_or_resolved, context)` | Execute once and atomically publish a run bundle at `context.output_dir`. The sync form refuses to run inside an active event loop. |
| `import_evaluation[_async](request_or_resolved, source, context, *, allow_external_symlinks=False)` | Normalize existing native artifacts into a bundle. Resolution and native reading run in `context.worker_python` when given. |
| `ensure_evaluation[_async](request, store, *, env, worker_python, timeout_seconds, import_source, allow_external_symlinks, model_endpoints)` | Reuse a validated stored result, otherwise import or execute into a new attempt and promote a success. Single-flight per reusable identity (ADR-0011). With `import_source`, reuse only an import of the same native content. Returns `EnsureOutcome(action, run, resolved, attempt, reuse_reason, import_identity, waited)`. |
| `native_source_identity(source, *, allow_external_symlinks=False)` | Engine-free content identity of native artifacts, equal to the `native_artifact_identity` their import publishes. |
| `ResultStore(root)` | Content-addressed store: `lookup`, `check_reuse`, `check_import_reuse`, `attempts(digest)`, `publish`, `promote`, `promote_import`, `acquisition_lock`. |
| `load_run(path)` | Engine-free bundle reader. `magnet_evals.outputs` also provides `select_metrics`, `sample_records`, `native_artifacts`, `trajectory_detail`, and related helpers. |
| `MeasurementIdentity`, `ResolvedEvaluation`, `EvaluationResult` | Result contracts. |
| `ENGINE_SPECS`, `EngineSpec` | Verified pins and engine notes. |

Errors derive from `magnet_evals.errors.AiqEvalsError`. The main ones are
`RequestValidationError`, `MissingDependencyError`, `EngineCompatibilityError`,
`ExecutionError`, `ArtifactError`, and `ActiveEventLoopError`.

## CLI (`aiq-evals`)

| Command | Purpose |
| --- | --- |
| `validate REQUEST` | Static validation |
| `resolve REQUEST [--worker-python PY] [--output F]` | Print the resolved request and its identity |
| `ensure REQUEST --store DIR [--worker-python PY] [--timeout S] [--import-source SRC] [--allow-external-symlinks]` | The central operation; prints the action, path, status, identity, reuse reason, import identity, and whether it waited for a concurrent acquisition |
| `run REQUEST --output DIR [--worker-python PY] [--timeout S]` | Execute once |
| `import-native REQUEST SOURCE --output DIR [--worker-python PY] [--allow-external-symlinks]` | Import native artifacts |
| `show RUN_DIR [--no-verify]` | Inspect a bundle without engines |
| `backends`, `engines`, `phase1-status`, `phase1-probe` | Introspection |

Exit status is 0 on success. `ensure`, `run`, and `import-native` return 2
when the published result is not `succeeded`.

## Request (schema 1)

```json
{"schema_version": 1, "engine": "helm|olmo_eval|inspect_ai", "task": "...",
 "task_revision": "...|null", "data_revision": "...|null",
 "models": [{"role": "primary", "model": "...", "provider": "...|null",
             "revision": "...|null", "cache_token": "...|null", "provider_options": {}}],
 "task_options": {}, "generation": {}, "engine_options": {"required_secrets": ["NAME"]}}
```

Secrets: values come from `ExecutionContext.env` or, for names declared in
`required_secrets`, the inherited environment. Declared secrets are checked
before any resolution code runs, and every such value of 8 characters or more
is scrubbed from logs and published results.

Identity is reusable only when the task is pinned (`task_revision` or a
hashed source), `data_revision` is set, every model has a `revision` or
`cache_token`, and the engine revision/version is known and verified. Otherwise
`unknown_reasons` explains why, and `ensure` always executes.

Engine options:

- **HELM:** `task` is a run entry without `model=`; `task_options` accepts
  `max_eval_instances` and `num_train_trials`; `engine_options.plugins` takes
  module names.
- **OLMo Eval:** `harness_config`, `task_modules`, `upstream_revision`, and
  save flags.
- **Inspect:** `eval_options`, `registration_modules`, `log_format`, and
  `upstream_revision`. `provider_options.base_url` becomes `model_base_url`.

## Run bundle (manifest schema 1)

```text
run_manifest.json   identity, reusable flag, native inventory + checksums (exact set),
                    native/normalized artifact identities, metadata_checksums for
                    resolved_request/results/attempt JSON, symlink notes
resolved_request.json
results.json        EvaluationResult (records, metrics, coverage, samples, diagnostics)
attempt.json        status, diagnostics, public execution context (env keys only);
                    canonical runs also carry source_attempt (path, identities)
ATTEMPT_TERMINAL    always; the terminal status
RUN_COMPLETE        only for succeeded
native/             retained native artifacts (authoritative)
```

Status (`succeeded`, `failed`, `cancelled`, `incomplete`) is separate from
coverage (`complete`, `partial`, `unknown`), as ADR-0004 requires.

## Result store layout

```text
runs/<dd>/<digest>/                    canonical successful runs (reusable)
imports/<dd>/<digest>/<native-id>/     successful imports, keyed by native content
attempts/<dd>/<digest>/<utc>-<rand>/   every terminal attempt
attempts/_unkeyed/<utc>-<rand>/        attempts with non-reusable identity
quarantine/<name>-<utc>-<rand>/        published runs that later failed validation
locks/<dd>/<key>.lock                  single-flight acquisition locks (flock)
```
