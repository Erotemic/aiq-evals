# aiq-magnet integration plan for aiq-evals

This file contains work that should happen in `aiq-magnet`, not in the core
`aiq-evals` package.

## Goal

MAGNET should delegate native evaluation acquisition to `aiq-evals` while
retaining ownership of scheduling, evidence selection, claims, and dashboards.

```text
MAGNET recipe / kwdagger campaign
      |
      v
EvaluationNode
      |
      v
magnet_evals.ensure/run/import
      |
      v
EvaluationRun
      |
      v
MAGNET evidence projection
      |
      v
metrics.evaluate.* -> ClaimResultNamespace -> card/dashboard
```

## M1 - Dependency and compatibility seam

- [ ] Add `aiq-evals` as a MAGNET dependency only after its phase-2 core contract
  is usable.
- [ ] Keep `magnet evaluate` legacy behavior compatible.
- [ ] Integrate through `magnet evaluate_new` first.
- [ ] Preserve existing HELM commands/loaders while migrating their generic
  execution/import implementation underneath to `aiq-evals`.
- [ ] Keep HELM-specific predictor/instance-predictor APIs in MAGNET until a
  separate migration is justified.

## M2 - Generic EvaluationNode

Create a MAGNET/kwdagger node whose job is to invoke one `aiq-evals` evaluation
request.

The node owns:

- conversion from recipe parameters to `EvaluationRequest`;
- output product path known to kwdagger;
- scheduler/container/lease wiring;
- invocation of the worker/facade;
- result-loader projection into one flat kwdagger evidence row.

The node must not own native engine-specific execution logic.

Use `engine` for `helm`, `olmo_eval`, or `inspect_ai`. Retain `backend` for the
kwdagger/cmd_queue scheduler (`serial`, `tmux`, etc.).

## M3 - Resolve identity before cache assignment

MAGNET/kwdagger cache keys must consume a resolved `aiq-evals` measurement
identity rather than hashing unresolved mutable task paths.

Requirements:

- [ ] preflight resolution happens before reusable computation identity is
  assigned;
- [ ] an unresolved mutable input disables reuse;
- [ ] engine/upstream/adapter changes cannot collide;
- [ ] a stale result marker cannot hide a failed/incomplete `aiq-evals` run;
- [ ] changing a MAGNET evidence selector does not rerun an unchanged native
  evaluation unless it changes native computation.

## M4 - Evidence projection

MAGNET defines a separate evidence-view record containing at least:

- source evaluation identity/artifact;
- selected task/model binding;
- selected scorer/metric/reducer;
- coverage policy;
- eligibility result and reasons;
- denominator when known;
- claim-facing provenance.

Strict default evidence eligibility should continue to require the policy MAGNET
chooses (for example successful execution, sufficient coverage, and a finite
selected scalar metric), but that judgment must not mutate the underlying
`aiq-evals` run.

## M5 - One artifact -> one evidence row

Preserve the existing kwdagger contract: a completed result-node artifact maps
to exactly one row.

A multi-log Inspect run or OLMo Eval suite may contain many native result
records. The MAGNET loader still returns one flat row.

A selector must identify exactly one claim-facing task/model/scorer/metric (and
reducer where required), or select one explicit native suite aggregate.

Nonselected records remain available from `aiq-evals` readers but do not create
additional MAGNET claim votes.

Examples:

- two task logs x three epochs -> one evidence row when task A reduced accuracy
  is selected;
- separate task claims -> schedule separate nodes;
- cross-task comparison -> schedule an explicit downstream comparison node.

## M6 - Cardinality acceptance experiment

This remains an early MAGNET integration gate even though native fixture capture
happens in `aiq-evals`. On 2026-09-29 it moved here from the `aiq-evals` P1-10
acceptance gate, because it needs the M4/M5 projection, which does not exist
yet. Representative native inputs are committed in `aiq-evals`:
`tests/fixtures/inspect-native/multi/` (three task logs, two epochs, auxiliary
role) and `tests/fixtures/olmo-native/multi/` (one suite expanded to two
prefix-overlapping task names). Engine-free `json/` renderings of the Inspect
logs and `expected-normalized.json` goldens sit beside them.

Using representative multi-result fixtures:

- [ ] feed them through real `kwdagger.aggregate_loader.build_tables`;
- [ ] load with `KWDaggerProcessor.load_available_result_rows`;
- [ ] evaluate through `ClaimResultNamespace`;
- [ ] record flat column examples;
- [ ] assert exactly one row/verdict per artifact;
- [ ] test duplicate sample IDs across tasks/models;
- [ ] test repeated epochs/reducers;
- [ ] test ambiguous selector rejection;
- [ ] prove no silent averaging of unrelated results.

Repeat with production adapters before freezing the public integration schema.

## M7 - Recipes and mixed-engine examples

- [ ] generation recipe using HELM;
- [ ] generation recipe using OLMo Eval;
- [ ] generation recipe using Inspect;
- [ ] agent/tool recipe using OLMo Eval;
- [ ] agent/tool recipe using Inspect;
- [ ] mixed-engine pipeline with explicit task/metric mappings;
- [ ] explicit downstream comparison node rather than assuming cross-engine
  scores are interchangeable.

All should use a stable result node such as `evaluate` and expose
`metrics.evaluate.score` only when selection is unambiguous.

## M8 - Scheduling and resource ownership

kwdagger continues to own campaign scheduling and node attempt/cache policy.
`aiq-evals` owns execution inside the node.

For MAGNET leasing/container integration:

- [ ] pass leased endpoints/model role bindings into `aiq-evals` execution
  context;
- [ ] avoid duplicate model startup;
- [ ] propagate cancellation to engine workers/sandboxes;
- [ ] keep secrets in runtime bindings, not hash/manifests/commands;
- [ ] keep scheduler `backend` independent of evaluation `engine`.

## M9 - Dry-run semantics

`magnet evaluate_new --dry-run` must remain side-effect free:

- no arbitrary task-factory execution;
- no model startup;
- no tool calls;
- no dataset download;
- no evidence publication;
- no verdict.

Static compilation may validate serializable request shape. Runtime resolution
that executes arbitrary code belongs in a separate preflight worker and must not
be smuggled into dry-run.

## M10 - MAGNET integration validation

Required MAGNET-side tests include:

- common metric/provenance columns from all three engines;
- agentic results reaching the same evidence interface;
- requested versus accumulated evidence scopes;
- requested cached result behavior;
- execution failure provenance separate from scientific claim truth;
- same-measurement reuse and invalidation;
- no cross-engine cache collision;
- stale/failed attempt handling;
- serial and tmux scheduler behavior;
- existing dashboard/card compatibility;
- HELM legacy regression coverage.

## Migration principle

The migration should shrink MAGNET's engine-specific surface rather than copy it.
At the end, MAGNET should know how to *request and interpret* an evaluation, but
not how OLMo Eval's runner or Inspect's log reader works internally.
