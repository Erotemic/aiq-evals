# aiq-evals implementation plan

Status: phase-1 foundation implemented; native runtime acceptance remains open.

This is the standalone refinement of the earlier MAGNET backend-agnostic
evaluation plan. It moves generic evaluation execution, import, identity, and
result access into `aiq-evals` and leaves MAGNET evidence/kwdagger semantics in
a separate integration plan.

## Objective

Provide one engine-independent way to obtain evaluation results from HELM,
OLMo Eval, and Inspect while preserving native task definitions, scoring, and
execution semantics.

A caller should eventually be able to:

1. describe an evaluation request;
2. resolve it to a reproducible measurement identity;
3. reuse/import a compatible existing result when justified;
4. execute the native engine when computation is required;
5. load the resulting run without importing the native engine.

The first release must support a local generation task for all three engines and
a scored multi-turn task with a real tool call for OLMo Eval and Inspect.

## Non-goals for the first release

- portable task code between evaluation frameworks;
- score equivalence merely because task labels match;
- automatic translation of HELM tasks into Inspect/OLMo tasks;
- a universal agent/tool runtime;
- a replacement scheduler for kwdagger;
- MAGNET claim/evidence policy;
- cloud database infrastructure;
- mandatory local vLLM support;
- automatic native resume/rescore behavior.

## Repository boundary

The package owns:

- engine request/capability contracts;
- engine registry and lazy dependency handling;
- native task/provider resolution;
- measurement identity;
- execution/import facade;
- isolated workers and cancellation cleanup;
- native artifact retention;
- normalized run/sample/metric access;
- coverage and execution facts;
- schema compatibility and migrations;
- reusable result discovery/storage;
- conformance tests across engines.

See `aiq-magnet-integration-plan.md` for everything deliberately outside this
repository.

## Phase 1 - Verify native APIs and freeze no public runtime contract yet

The purpose of phase 1 is to replace assumptions with captured native evidence.
No engine capability is supported merely because documentation or an older
integration suggests it should work.

### P1-01 Evidence ledger

- [x] Create `docs/planning/phase1-evidence.md` as the canonical phase-1 record.
- [x] Define durable record fields: task ID, date, revision, environment,
  command/test, artifact references, outcome, and notes.
- [x] Keep runtime checks open until actually executed.

### P1-02 Upstream pins and worker environments

- [x] Record candidate/history metadata for HELM, OLMo Eval, and Inspect.
- [x] Add source-checkout probes for exact git HEAD, clean state,
  `requires-python`, and `uv.lock` presence.
- [x] Add a generic locked-`uv` worker command helper.
- [ ] Select an exact tested HELM release/revision.
- [ ] Select an exact tested Inspect release/revision.
- [ ] Select an exact tested OLMo Eval revision after comparing the original
  plan's inspected revision with the later `eval_audit` prototype revision.
- [ ] Record minimal dependency/extras sets and clean build instructions.

### P1-03 OLMo Eval native fixtures

- [ ] Run one deterministic local generation task through the supported runner.
- [ ] Run one multi-turn task that actually invokes a tool.
- [ ] Capture native request/prediction/metric/trajectory artifacts.
- [ ] Trigger a native hard-failure gate after diagnostic artifacts are written.
- [ ] Verify the failed run is distinguishable from successful evidence.
- [ ] Verify custom task/tool registration survives owned worker processes.

Do not treat the supplied older `eval_audit` OLMo smoke as acceptance evidence;
it is design/prototype input that must be reproduced from this repository.

### P1-04 Inspect native fixtures

- [ ] Run one deterministic local generation task through a public API.
- [ ] Run one native solver/agent with a real tool invocation.
- [ ] Capture multiple returned logs, sample errors, usage, traces, epochs, and
  reducers where available.
- [ ] Exercise cancellation/nonterminal/error status.
- [ ] Verify custom task/tool imports in the selected worker environment.

### P1-05 HELM native fixtures

- [ ] Run a small HELM computation compatible with current MAGNET behavior.
- [ ] Exercise cached reuse/materialization.
- [ ] Import an existing native run directory.
- [ ] Capture aggregate and per-instance data.
- [ ] Capture a fixture where aggregate statistics exist but complete sample
  coverage cannot be proved.

### P1-06 Worker/async/cleanup behavior

For OLMo Eval and Inspect:

- [ ] verify public sync/async entry points at the selected pins;
- [ ] prove no synchronous `asyncio.run` wrapper is called inside an active
  event loop;
- [ ] prove owned child workers are terminated on cancellation;
- [ ] prove engine-owned sandboxes/resources are cleaned up;
- [ ] document which process owns each lifecycle boundary.

### P1-07 Initial capability matrix

For each tested engine/task/provider combination, record demonstrated support
for:

- generation;
- log probabilities;
- multiple scorers;
- agentic/multi-turn execution;
- tools;
- trajectory access;
- sandboxing;
- epochs/repetitions;
- native import;
- native resume/rescore.

Capabilities are combination-level facts, not broad engine marketing flags.
Unsupported combinations fail explicitly.

### P1-08 EEE normalization gap analysis

Before freezing an `EvaluationResult` schema:

- [ ] map the HELM fixture into current EEE representations;
- [ ] map the Inspect generation and agentic fixtures;
- [ ] map OLMo Eval generation and trajectory fixtures;
- [ ] record every scientific field that would be lost or ambiguously mapped;
- [ ] decide whether EEE is the normalized scientific payload, requires a small
  extension, or is unsuitable for the first `aiq-evals` contract.

This replaces the earlier assumption that MAGNET should create its own complete
cross-engine result schema immediately.

### P1-09 OLMo Eval packaging go/no-go

- [ ] Test a clean co-installed optional extra only if dependency resolution and
  both native smokes are reproducible.
- [ ] If co-installation is fragile/conflicting, select isolated-worker-only
  support with an immutable checkout/container and committed lock authority.
- [ ] Verify generation, tool execution, import, cancellation, and engine-free
  result reading in the selected delivery mode.
- [ ] If neither path works, leave the OLMo release capability blocked rather
  than weakening core dependencies.

### P1-10 Acceptance gate

Phase 1 closes only when:

- exact supported pins/environments are recorded for all three engines;
- native scored generation works in all three;
- real multi-turn tool execution works in OLMo Eval and Inspect;
- failure/cancellation fixtures are captured;
- worker cleanup is demonstrated;
- the EEE normalization decision is recorded;
- OLMo packaging has a supported path;
- MAGNET's separate cardinality spike has passed for representative native
  multi-result fixtures.

The last item is an external integration gate; it does not make MAGNET a core
dependency of this repository.

## Phase 2 - Shared contracts, identity, store, and engine-free artifacts

After phase 1 supplies native evidence:

- define a versioned `EvaluationRequest` and resolved request;
- define `ExecutionContext` separately from measurement inputs;
- define task/model/provider roles and typed engine options;
- implement static validation without importing task factories;
- implement preflight resolution before reusable cache assignment;
- implement canonical measurement identity;
- implement unknown-identity/no-reuse behavior;
- implement a lazy engine registry;
- implement sync/async/import facades;
- implement a filesystem content-addressed result store;
- implement atomic terminal run publication;
- implement native artifact references/checksums/lineage;
- implement engine-free normalized readers;
- implement schema versioning and frozen compatibility fixtures;
- keep selected MAGNET metrics and evidence policies out of measurement identity.

The phase-2 API is provisional until all three production adapters pass.

## Phase 3 - OLMo Eval adapter

- translate resolved requests to task specs/overrides and harness/provider
  configuration;
- call native validation explicitly;
- preserve registered tasks, providers, judges, scaffolds, tools, and sandboxes;
- use runner-owned lifecycle behavior;
- normalize all task results/samples without flattening nested scorer identity;
- retain predictions, requests, trajectories, and native diagnostics;
- map processed/saved/failed counts;
- implement native artifact import;
- ensure failure gates never publish a successful terminal computation merely
  because `metrics.json` exists.

## Phase 4 - Inspect adapter

- resolve native task references/factories and arguments;
- bind primary/auxiliary model roles;
- use supported public evaluation APIs at the selected pin;
- collect every returned log;
- preserve scorer-qualified metrics, structured sample scores, epochs/reducers,
  usage, and trace references;
- preserve native `.eval`/JSON logs for Inspect tooling;
- import native logs via Inspect readers while the runtime is available;
- conservatively map error/cancelled/nonterminal states;
- support native solver/agent/tool execution without nesting a competing
  campaign retry scheduler.

## Phase 5 - HELM adapter

- move/wrap generic HELM compute and import behavior behind the `aiq-evals`
  adapter contract;
- preserve native aggregate/per-instance records;
- preserve unknown coverage when native artifacts cannot establish it;
- keep existing MAGNET-specific predictor APIs in MAGNET;
- provide a compatibility seam so current MAGNET HELM recipes continue working
  during migration.

## Phase 6 - Reuse/ensure semantics and conformance

Once real adapters exist, finalize the central reusable operation:

```text
resolve request
-> compute measurement identity
-> discover a compatible terminal result
-> validate artifact identity/completeness
-> reuse/import if valid
-> otherwise execute native engine
-> normalize/publish atomically
-> return engine-independent run
```

Requirements:

- engine/version/config/code changes invalidate reuse;
- changed native imported artifacts get new identities;
- secrets never enter identities or manifests;
- mutable endpoint aliases need explicit revision/cache tokens;
- retries/attempt lineage do not inflate sample identity;
- stale success markers cannot hide failed/incomplete attempts;
- no engine dependency is required to read a normalized result.

Freeze the first public API/schema only after HELM, OLMo Eval, and Inspect all
pass the same conformance suite.

## Phase 7 - Agentic operational/security behavior

- deterministic multi-turn/tool fixtures for both new engines;
- normalized trajectory access with explicit loss-of-detail metadata;
- turn/time/concurrency limits;
- secret handling/redaction;
- tool/judge error mapping;
- cancellation cleanup;
- isolated attempt retries;
- external endpoint support;
- optional sandbox examples;
- security review of task loading, tool execution, sandbox boundaries, host
  mounts/network, secrets, cancellation, and artifact path handling.

A worker container alone is not a security guarantee.

## Phase 8 - Packaging and release verification

- document API/CLI/contracts and capability matrix;
- publish engine-free and per-engine CI;
- retain frozen schema fixtures across releases;
- keep paid/GPU/sandbox/external tests separate from deterministic CI;
- classify external failures and bound retries;
- never let quarantine turn a required release gate green;
- run clean-environment walkthroughs for generation and agentic examples;
- remove experimental labels only after the release gate passes.

## Validation groups

The original validation plan is retained conceptually but repartitioned:

1. engine-free contracts/identity/artifact tests;
2. shared adapter conformance parameterized over all engines;
3. OLMo-native contracts;
4. Inspect-native contracts;
5. HELM-native compatibility contracts;
6. agentic/tool/cancellation/security contracts;
7. dependency/environment matrix;
8. result-store reuse/invalidation/migration contracts.

MAGNET pipeline/evidence tests are intentionally moved to the MAGNET integration
plan rather than duplicated here.
