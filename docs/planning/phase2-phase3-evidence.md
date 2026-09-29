# Phase-2 / phase-3 implementation evidence

This ledger records what is implemented in the repository separately from the
native-runtime acceptance evidence in `phase1-evidence.md`.

The distinction matters: source-grounded adapter code and fake-native contract
tests can establish internal semantics, but they do not establish that a selected
OLMo Eval revision is a supported runtime.

## Phase 2 - shared runtime

Status: IMPLEMENTED, PROVISIONAL.

Implemented surfaces:

- `aiq_evals.contracts`: strict versioned JSON request/resolution/result contracts;
- `aiq_evals.identity`: canonical measurement identity and no-reuse reasons;
- `aiq_evals.backends.registry`: lazy adapter loading;
- `aiq_evals.runner`: sync/async/import facades plus isolated worker process path;
- `aiq_evals.worker`: multiprocessing-safe subprocess protocol;
- `aiq_evals.artifacts`: atomic terminal bundles, native checksums, native artifact
  identity, and normalized artifact identity;
- `aiq_evals.store`: filesystem content-addressed successful-run store;
- `aiq_evals.outputs`: engine-free result readers;
- `tests/fixtures/run-v1`: frozen dependency-free schema-v1 bundle.

Behavior covered by the repository tests includes:

- strict unknown-field and non-JSON rejection;
- credential-value rejection while allowing names such as `required_secrets`;
- stable identity and identity invalidation when measurement inputs change;
- unknown revision facts disabling reusable identity;
- successful vs failed terminal markers;
- secret values excluded from persisted execution context;
- native checksum and normalized-payload tamper detection;
- content-addressed lookup only for reusable successful runs;
- conservative rejection of unknown future manifest/result schema versions;
- synchronous facade rejection inside an active event loop.

Remaining before phase-2 API freeze:

- native evidence from all three production adapters;
- EEE normalization decision;
- a real schema-N+1 migration path (v1 currently only needs version rejection);
- conformance across the eventual selected worker environments.

## Phase 3 - OLMo Eval adapter

Status: IMPLEMENTED, EXPERIMENTAL; NATIVE ACCEPTANCE OPEN.

The adapter is source-grounded against the candidate revision originally inspected
by the MAGNET plan:

`73ade80e24f796af55caeb8fd7b75a7f3fd607fd`

Implemented behavior:

- lazy import of `HarnessConfig`, `AsyncEvalRunner`, `SamplingParams`, `TaskConfig`,
  and `expand_tasks`;
- `HarnessConfig.from_dict` canonicalization;
- explicit runner `validate()` followed by `run_async()`;
- request/provider conflict detection;
- canonical expanded task membership in measurement identity;
- nested `metric -> scorer -> value` preservation;
- saved/processed/failed coverage accounting;
- prediction and trajectory extraction when present;
- native request/prediction/metric files retained by the run bundle;
- hard-failure artifacts retained without being published as successful execution;
- cancellation propagated to the caller;
- native import validates resolved task membership plus recorded model/provider facts;
- missing resolved tasks become an incomplete import rather than fabricated success;
- native top-level task errors become failed records;
- imported revision provenance is explicitly labeled caller-supplied when the native
  metrics do not prove it.

Repository tests use a narrow fake-native surface matching the inspected public API.
They do not count as the native P1-03/P1-06 acceptance fixtures.

## Native gates still open

Do not mark the OLMo adapter supported until the selected real upstream environment
records all of the following in `phase1-evidence.md`:

1. scored deterministic generation;
2. real multi-turn tool invocation and trajectory;
3. a hard-failure-after-diagnostics run;
4. custom registration behavior through owned workers;
5. cancellation and cleanup evidence;
6. clean installation/isolated-worker packaging decision.
