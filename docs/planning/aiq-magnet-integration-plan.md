# aiq-magnet integration plan for aiq-magnet-evals

This file contains work that should happen in `aiq-magnet`, not in the core
`aiq-magnet-evals` package.

Status (2026-09-29): M1-M10 implemented and tested on the MAGNET branch
`dev/aiq-evals-integration`. Checked items cite their evidence in
`integration-evidence.md`. One item is explicitly deferred (M1, migrating the
legacy HELM internals), and hosted CI has not run yet.

## Goal

MAGNET should delegate native evaluation acquisition to `aiq-magnet-evals` while
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

- [x] Add `aiq-magnet-evals` as a MAGNET dependency only after its phase-2 core contract
  is usable. (Optional extra `aiq-magnet[aiq-magnet-evals]`, imported lazily;
  resolved from git until it is on PyPI.)
- [x] Keep `magnet evaluate` legacy behavior compatible. (MAGNET's full suite;
  E-M1.)
- [x] Integrate through `magnet evaluate_new` first.
- [ ] Preserve existing HELM commands/loaders while migrating their generic
  execution/import implementation underneath to `aiq-magnet-evals`.
  **Deferred.** The preservation half holds: legacy HELM commands, loaders, and
  recipes are unchanged and pass. HELM through `EvaluationNode` uses the
  aiq-magnet-evals HELM adapter, which also imports MAGNET-materialized run
  directories. Rewiring MAGNET's legacy materialization code onto
  aiq-magnet-evals is not required for those guarantees and has not been done.
  It is the remaining step of the migration principle below.
- [x] Keep HELM-specific predictor/instance-predictor APIs in MAGNET until a
  separate migration is justified.

## M2 - Generic EvaluationNode

Create a MAGNET/kwdagger node whose job is to invoke one `aiq-magnet-evals` evaluation
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

Status: done. `magnet.backends.aiq_evals.EvaluationNode`; the node runs
`cli.run_node` and preflights with `cli.resolve_node`, both wrapped identically
for host or container execution.

## M3 - Resolve identity before cache assignment

MAGNET/kwdagger cache keys must consume a resolved `aiq-magnet-evals` measurement
identity rather than hashing unresolved mutable task paths.

Requirements:

- [x] preflight resolution happens before reusable computation identity is
  assigned, in the node's own execution environment (host or container);
  the computed `measurement_identity`/`import_identity` cannot be configured;
- [x] an unresolved mutable input disables reuse;
- [x] engine/upstream/adapter changes cannot collide (and task-code or
  imported-content changes schedule new nodes);
- [x] a stale result marker cannot hide a failed/incomplete `aiq-magnet-evals` run;
- [x] changing a MAGNET evidence selector does not rerun an unchanged native
  evaluation unless it changes native computation; concurrent selector nodes
  execute it once (aiq-magnet-evals ADR-0011).

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
`aiq-magnet-evals` run.

Status: done. The node's `evaluation.json` records only the run reference and
the projection (selector, coverage policy). The view is recomputed from the
validated run every time a row is loaded, so editing `evaluation.json` cannot
change what a claim sees (E-M4).

## M5 - One artifact -> one evidence row

Preserve the existing kwdagger contract: a completed result-node artifact maps
to exactly one row.

A multi-log Inspect run or OLMo Eval suite may contain many native result
records. The MAGNET loader still returns one flat row.

A selector must identify exactly one claim-facing task/model/scorer/metric (and
reducer where required), or select one explicit native suite aggregate.

Nonselected records remain available from `aiq-magnet-evals` readers but do not create
additional MAGNET claim votes.

Examples:

- two task logs x three epochs -> one evidence row when task A reduced accuracy
  is selected;
- separate task claims -> schedule separate nodes;
- cross-task comparison -> schedule an explicit downstream comparison node.

## M6 - Cardinality acceptance experiment

This remains an early MAGNET integration gate even though native fixture capture
happens in `aiq-magnet-evals`. On 2026-09-29 it moved here from the `aiq-magnet-evals` P1-10
acceptance gate, because it needs the M4/M5 projection, which does not exist
yet. Representative native inputs are committed in `aiq-magnet-evals`:
`tests/fixtures/inspect-native/multi/` (three task logs, two epochs, auxiliary
role) and `tests/fixtures/olmo-native/multi/` (one suite expanded to two
prefix-overlapping task names). Engine-free `json/` renderings of the Inspect
logs and `expected-normalized.json` goldens sit beside them.

Using representative multi-result fixtures:

- [x] feed them through real `kwdagger.aggregate_loader.build_tables`;
- [x] load with `KWDaggerProcessor.load_available_result_rows`;
- [x] evaluate through `ClaimResultNamespace`;
- [x] record flat column examples (E-M6);
- [x] assert exactly one row/verdict per artifact;
- [x] test duplicate sample IDs across tasks/models;
- [x] test repeated epochs/reducers;
- [x] test ambiguous selector rejection;
- [x] prove no silent averaging of unrelated results.

Repeat with production adapters. Nothing on either side is frozen before a PyPI
release (aiq-magnet-evals ADR-0010).

## M7 - Recipes and mixed-engine examples

- [x] generation recipe using HELM;
- [x] generation recipe using OLMo Eval;
- [x] generation recipe using Inspect;
- [x] agent/tool recipe using OLMo Eval;
- [x] agent/tool recipe using Inspect;
- [x] mixed-engine pipeline with explicit task/metric mappings;
- [x] explicit downstream comparison node rather than assuming cross-engine
  scores are interchangeable.

The recipes live in MAGNET's `magnet/examples/aiq_evals/`, ship as package data,
and use only the installed `magnet_evals.examples` tasks (E-M7).

All should use a stable result node such as `evaluate` and expose
`metrics.evaluate.score` only when selection is unambiguous.

## M8 - Scheduling and resource ownership

kwdagger continues to own campaign scheduling and node attempt/cache policy.
`aiq-magnet-evals` owns execution inside the node.

For MAGNET leasing/container integration:

- [x] pass leased endpoints/model role bindings into `aiq-magnet-evals` execution
  context;
- [x] avoid duplicate model startup (no lease for a stored run or an import;
  one native execution per measurement under concurrency);
- [x] propagate cancellation to engine workers/sandboxes;
- [x] keep secrets in runtime bindings, not hash/manifests/commands;
- [x] keep scheduler `backend` independent of evaluation `engine`;
- [x] container execution: preflight and execution both run in the node's
  container, including a worker interpreter that exists only there.

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

Status: done. A dry run resolves nothing and writes no store, but it does
reject malformed selectors and coverage policies (E-M9).

## M10 - MAGNET integration validation

Required MAGNET-side tests (each mapped to a test in E-M10):

- [x] common metric/provenance columns from all three engines;
- [x] agentic results reaching the same evidence interface;
- [x] requested versus accumulated evidence scopes;
- [x] requested cached result behavior;
- [x] execution failure provenance separate from scientific claim truth;
- [x] same-measurement reuse and invalidation;
- [x] no cross-engine cache collision;
- [x] stale/failed attempt handling;
- [x] serial and tmux scheduler behavior;
- [x] existing dashboard/card compatibility (the file contract eval-card-viz
  uploads; the viewer itself was not run);
- [x] HELM legacy regression coverage;
- [x] a dedicated CI job (xcookie source check `aiq-magnet-evals`) that runs
  these with `MAGNET_REQUIRE_AIQ_EVALS=1`, so a missing engine fails rather
  than skips. Reproduced locally; not yet run on hosted CI.

## Migration principle

The migration should shrink MAGNET's engine-specific surface rather than copy it.
At the end, MAGNET should know how to *request and interpret* an evaluation, but
not how OLMo Eval's runner or Inspect's log reader works internally.
