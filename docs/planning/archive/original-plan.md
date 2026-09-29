NOTE: This is the historical reference plan from which docs/planning was seeded.


# Implementation plan: backend-agnostic evaluation for MAGNET

Status: proposed for review. This document specifies implementation work; no
backend implementation or runtime verification has been completed.
Revision: 2026-09-24, addressing all nine gaps in `PLAN-feedback.MD`.

## Objective and release scope

Provide one MAGNET evaluation interface for **HELM, olmo-eval, and Inspect**.
Add `magnet.backends.olmo_eval` and `magnet.backends.inspect_ai`, and adapt the
existing HELM execution/materialization path to the same contract. Share request
validation, artifact publication, result loading, kwdagger integration, and claim
evidence policy. Retain native task definitions, scoring, and execution semantics.

Release requirements:

- All three engines support execution and native-result import through the same
  Python API, worker CLI, and kwdagger node interface.
- olmo-eval and Inspect each support a local generation task, an external model
  endpoint, and a scored multi-turn task with an actual tool call and trajectory.
- HELM's existing execution, cached-run reuse, loaders, recipes, and legacy
  commands continue to work. Its adapter advertises only demonstrated capabilities.
- Normalized results can be read without installing any evaluation engine.
- Claims and dashboard bundles consume the same result contract across engines.

A consistent interface does not imply portable task code or equal scores across
frameworks. Cross-engine comparisons must specify equivalent datasets, prompts,
sampling, and scoring explicitly. Native local vLLM, OpenHands, Beaker submission,
cloud databases, automatic task translation, and a universal tool/agent runtime
are outside the required first release. Existing HELM-specific predictors remain
supported; converting all their algorithms is a follow-up, not a prerequisite
for backend-neutral execution and evidence access.

## Findings that determine the design

### Existing MAGNET boundaries

- `magnet/evaluation_new.py` consumes backend-independent kwdagger rows. Use
  `magnet evaluate_new`; keep `magnet evaluate` and legacy behavior compatible.
- `magnet/_kwdagger.py` owns campaign scheduling, result discovery, requested-work
  provenance, and evidence scope. Its `backend` means scheduler (`serial`,
  `tmux`, etc.). Use **engine** for `helm`, `olmo_eval`, or `inspect_ai`.
- `magnet/backends/helm/pipeline.py` supplies existing materialization behavior;
  `magnet/examples/llama_consistency/llama_compare.py` demonstrates result loading
  into `metrics.<node>.<field>` columns. The proposed publication contract
  generalizes HELM's existing `DONE`-written-last/primary-output pattern.
- `magnet/predictor.py` and `magnet/instance_predictor.py` directly depend on HELM
  models/columns. Introduce normalized accessors without fabricating HELM objects
  from Inspect or olmo-eval results.
- `magnet/exceptions.py:require_optional` supplies optional-dependency errors.
  Core MAGNET supports Python >=3.11; worker requirements can differ by engine.

### olmo-eval API evidence

Research date: 2026-09-23. Source checkout inspected at commit
`73ade80e24f796af55caeb8fd7b75a7f3fd607fd`. Links below pin the inspected code;
this is a candidate integration revision, not a claim of a tested dependency pin.
The target is `allenai/olmo-eval`, not the separate `oe-eval` project.

- [Runner API](https://github.com/allenai/olmo-eval/blob/73ade80e24f796af55caeb8fd7b75a7f3fd607fd/src/olmo_eval/runners/asynq/runner.py):
  `AsyncEvalRunner` accepts `harness_config`, `task_specs`, `task_overrides`,
  `output_dir`, prediction/request persistence flags, and `shuffle_seed`.
  Call `validate()` explicitly, followed by `run()` or `await run_async()`.
  The synchronous method wraps `asyncio.run`; it must not run inside an active
  event loop. The runner owns worker processes and resource cleanup.
- [Harness configuration](https://github.com/allenai/olmo-eval/blob/73ade80e24f796af55caeb8fd7b75a7f3fd607fd/src/olmo_eval/harness/config.py)
  supports deserialization with `HarnessConfig.from_dict`, primary and auxiliary
  providers, registered tools, scaffolds, sandboxes, and execution limits.
- [Harness execution](https://github.com/allenai/olmo-eval/blob/73ade80e24f796af55caeb8fd7b75a7f3fd607fd/src/olmo_eval/harness/harness.py)
  distinguishes generation/log-probability requests from scaffolded multi-turn
  execution. Benchmark integration should use the runner so task scoring and
  lifecycle management are retained.
- [TaskResult](https://github.com/allenai/olmo-eval/blob/73ade80e24f796af55caeb8fd7b75a7f3fd607fd/src/olmo_eval/runners/common/types.py)
  stores nested metric/scorer values, a primary metric identifier, and separate
  processed/saved/failed counts.
  [Prediction serialization](https://github.com/allenai/olmo-eval/blob/73ade80e24f796af55caeb8fd7b75a7f3fd607fd/src/olmo_eval/runners/io/builders.py)
  retains trajectories when present. The runner can write diagnostic artifacts
  before raising its hard-failure gate: `metrics.json` alone is not proof of success.
- [Dependency metadata](https://github.com/allenai/olmo-eval/blob/73ade80e24f796af55caeb8fd7b75a7f3fd607fd/pyproject.toml)
  requires Python >=3.12, separates provider/agent/sandbox extras, and includes
  Git dependencies. OpenHands conflicts with several other extras. Package
  publication and resolver compatibility must be checked before adding a
  distributable MAGNET extra.

### Inspect API evidence

Reviewed the official documentation on 2026-09-23; an exact tested release/commit
must be selected in phase 1. Documentation references are not a dependency pin.

- [Tasks](https://inspect.aisi.org.uk/tasks.html) compose datasets, solvers/agents,
  and scorers. Preserve task factories and their parameters as native definitions.
- [Evaluation API](https://inspect.aisi.org.uk/reference/inspect_ai.html) provides
  evaluation and retry entry points; `eval()` returns a list of `EvalLog` objects.
  The adapter must account for every returned task/model log and explicitly
  inspect status, rather than assuming a returned call implies success.
- [Log API and format](https://inspect.aisi.org.uk/eval-logs.html) retain aggregate
  metrics, sample scores, events, usage, and multi-epoch reductions. Use Inspect's
  readers for native `.eval`/JSON logs; export normalized MAGNET artifacts while
  the Inspect runtime is available.
- [Evaluation sets](https://inspect.aisi.org.uk/eval-sets.html) offer campaign
  retry/recovery features. Initially let kwdagger own campaign scheduling and
  node attempts; do not nest an automatic Inspect eval-set retry loop inside it.
- [Package metadata](https://github.com/UKGovernmentBEIS/inspect_ai/blob/main/pyproject.toml)
  is the source for worker Python/dependency requirements at the chosen pin.
  Verify compatibility rather than inheriting olmo-eval's Python restrictions.

## Shared architecture and API

```text
MAGNET recipe / kwdagger campaign
  -> EvaluationNode(engine=...) -> shared worker CLI / Python API
  -> HELM adapter | olmo-eval adapter | Inspect adapter
  -> native engine execution or native artifact import
  -> shared normalized results, eligibility policy, atomic publication
  -> common result loader -> claim evidence -> existing dashboard artifacts
```

The registry and shared contracts replace the earlier backend-specific-node
proposal. Keep engine imports lazy and isolate upstream API changes inside each
adapter. Start with explicit built-in registrations; third-party package entry
points can be added later without changing the protocol.

| Proposed location | Responsibility |
| --- | --- |
| `magnet/backends/contracts.py` | Request, resolved request, result, capability and context types |
| `magnet/backends/registry.py` | Lazy engine lookup and metadata |
| `magnet/backends/runner.py` | Shared sync/async execution and import facade |
| `magnet/backends/artifacts.py` | Identity, schema validation, eligibility and publication |
| `magnet/backends/outputs.py` | Dependency-light run/sample/metric accessors |
| `magnet/backends/pipeline.py` | Generic `EvaluationNode`, factory and result loader |
| `magnet/backends/cli/run.py` | Common worker CLI with execution/import modes |
| `magnet/backends/{olmo_eval,inspect_ai}/` | Native configuration, compatibility and adapter code |
| `magnet/backends/helm/adapter.py` | Wrapper over existing HELM paths |
| `magnet/examples/backends/` | Generation recipes for all engines, agentic recipes for both new engines |
| `tests/test_backend_*.py` | Shared contracts and integration tests |
| `tests/test_{olmo_eval,inspect_ai,helm_adapter}_*.py` | Engine-specific contracts |

### Stability and compatibility policy

Mark the new adapters and shared API experimental in package docstrings, registry
metadata, and user documentation until the phase 8 release gate passes. Existing
HELM public APIs retain their compatibility guarantees throughout implementation.
Phase 2 establishes a provisional contract exercised by stubs; it is not an API
freeze. Phases 3 and 4 may revise it based on native-engine findings, updating
both adapters, schemas, tests, and this plan together. Freeze the initial public
API and schema only at the joint integration gate at the end of phase 6, after
all three real adapters and the cardinality experiment pass. Later breaking changes
must explicitly reopen that gate and rerun affected checks. Remove experimental
markings only after the phase 8 release gate and its recorded review pass.

Version manifests and normalized results explicitly. Before first release, create
frozen version-1 fixtures. Each later reader must either read previously supported
schemas through an explicit compatibility/migration path without changing metric
meaning, or fail with an actionable error naming the source version, supported
versions, and migration instructions. Never silently reinterpret an old artifact
as the current schema. Unknown future versions fail conservatively. Migrations
write new artifacts with source lineage and leave originals intact. Engine-free
reading and migration errors must not require upstream packages.

### Requests, resolution and capabilities

Define a serializable, versioned `EvaluationRequest` with engine, task reference
and parameters, model-role bindings, supported common generation settings,
metric selector, evidence policy, retention policy, and typed `backend_options`.
Keep output paths, worker interpreter/container, credentials, cancellation, and
resource allocations in `ExecutionContext`. Output locations and credentials do
not define measurement identity. Explicitly record settings affecting measurements.

Task references are engine-qualified strings or importable factories in scheduled
requests. Do not serialize live Task, Solver, Harness, or tool objects between
workers. Common settings and native overrides must have documented precedence;
reject conflicting duplicates, unknown fields, and unsupported requested features.
Native options remain validated by the selected adapter/upstream parser.

Proposed protocol (names and signatures to finalize in phase 2):

```python
class EvaluationBackend(Protocol):
    def capabilities(self) -> BackendCapabilities: ...
    def resolve(self, request: EvaluationRequest) -> ResolvedEvaluation: ...
    async def execute(self, resolved: ResolvedEvaluation,
                      context: ExecutionContext) -> EvaluationResult: ...
    def import_results(self, source: ArtifactReference,
                       context: ImportContext) -> EvaluationResult: ...
```

Capabilities describe generation, agentic execution, log probabilities, sandboxing,
trajectory availability, and optional native resume/rescoring. Engine-level flags
are insufficient: validate the actual task/provider/scaffold combination. Unsupported
features fail explicitly; capability flags must not promise feature parity.

The shared `run_evaluation` / `run_evaluation_async` and `import_evaluation`
facades handle registry selection and publication. Cancellation must terminate
owned subprocesses/resources, not merely cancel an awaiting coroutine. Execute
blocking engines in owned workers; do not call a synchronous `asyncio.run` wrapper
inside an active event loop. The CLI needs a multiprocessing-safe main guard and
nonzero exits for execution, normalization, or evidence-policy rejection.

Separate static compilation from runtime resolution. Dry-run validates the
serializable request without importing arbitrary task factories, starting models,
executing tools, downloading datasets, or writing verdicts. Resolve identity in a
preflight worker before scheduling reusable computations. If a task expansion or
revision cannot be resolved without execution, require an explicit immutable
manifest/cache token or disable reusable caching; do not hash an unresolved path
and later silently treat it as a fully resolved computation.

### Native adapter responsibilities

| Boundary | HELM | olmo-eval | Inspect |
| --- | --- | --- | --- |
| Task selection | Run entry/spec and scenario | Task/variant/suite spec | Task reference/factory and arguments |
| Execution | Existing materialization/execution path | `AsyncEvalRunner` | Public evaluation API at selected pin |
| Agent execution | Only if demonstrated and declared | Harness/scaffold/tools | Native solver/agent/tools |
| Scoring | Native statistics/per-instance scores | Native scorers and suite metrics | Native scorers, metrics and epoch reductions |
| Import | Existing run directories | Native metrics and prediction artifacts | Native logs read through Inspect APIs |

olmo-eval must call validation explicitly, retain registered-task behavior in
spawned workers, pass provider/judge/scaffold/sandbox configuration through, and
handle upstream failure gates even when metrics were already written.

Inspect must resolve task code/parameters, bind default and auxiliary model roles,
retain solver/agent/scorer configuration, and collect all returned logs. Map log
and sample errors, cancellation, and unknown/nonterminal statuses conservatively.
Preserve epochs and reducers, and retain the original log for Inspect tooling.
Verify the supported public async API at the pin, or run the public synchronous
API in an owned worker. Native retry/rescore can be future capability extensions;
initial node retries are fresh attempts with no automatic tool replay policy.

HELM's adapter must support both compute and reuse/import using existing code,
normalize aggregate/per-instance artifacts, and preserve old entry points. No
HELM-wide rewrite is needed. Never infer complete sample coverage from aggregate
statistics alone; import missing provenance/coverage as unknown and apply policy.

### Results, artifacts and claim eligibility

Use a versioned `EvaluationResult` containing one or more task/model result records.
Keep native identity, engine/upstream/adapter version, effective configuration,
dataset/task code revisions, sample selection, and native artifact references.
Metric records include scorer, metric, task/model scope, value, aggregation/reducer,
and denominator when known. Preserve structured native sample scores; select only
valid numeric aggregate metrics for scalar claims.

Sample keys include task, model binding, native sample ID, and epoch/repetition.
Retain attempt lineage separately to avoid double-counting retries as samples.
Store transcripts/trajectories as optional per-sample artifacts with native events
preserved; normalized views may be partial and must say so. Absent tokens, costs,
traces, or coverage remain unknown, never zero or fabricated.

```text
resolved_config.json       # redacted effective request/configuration
adapter_manifest.json      # schema, engine, identity, artifact checksums/lineage
native/                    # original engine logs/results, preserved for tooling
samples.jsonl              # optional normalized sample records / trace references
results.json               # normalized task/model records and eligibility
attempt.json               # terminal/nonterminal execution state and diagnostics
DONE                       # eligible evidence published successfully; written last
```

Distinguish execution status (`succeeded`, `failed`, `cancelled`, `incomplete`),
coverage (`complete`, `partial`, `unknown`), and evidence eligibility with reasons.
An attempt may finish successfully yet lack the selected score. Strict default
eligibility requires successful selected tasks, complete required sample coverage,
and valid selected metrics. Explicit partial/unknown-coverage policies must record
limitations, denominator, and policy in provenance and identity. An execution error
is not a false scientific claim. Native status remains available alongside mapping.

The shared publisher writes atomically and publishes `DONE` only after schema,
identity, required-artifact, and eligibility checks. Loaders never treat a native
metrics file or log's existence as successful evidence. Preserve failed diagnostics
without `DONE`; terminal attempt records prevent failure from being hidden.

Use one task or native suite/task collection and one primary model binding per
node initially. The schema still supports multiple returned task/model records.
A selector must identify task/model/scorer/metric when ambiguous. Do not average
unrelated results or count Inspect epochs as independent MAGNET evidence rows.
Use a stable node name such as `evaluate` and expose `metrics.evaluate.score` only
for an unambiguous selection, plus coverage and provenance. Suites retain native
aggregation; any additional cross-task reduction is an explicit downstream node.

#### Multi-result to evidence-row mapping

Keep the existing one-row-per-completed-node-artifact contract. A multi-log Inspect
run or olmo-eval suite remains one normalized artifact containing all native result
records. Its loader returns one flat mapping, not a list of rows. A required
selector identifies exactly one task/model/scorer/metric (and reducer where
applicable) for `metrics.evaluate.score`; an explicitly selected native suite
aggregate is also valid. The manifest preserves the selector-to-native-record
mapping. Nonselected records remain available through shared readers and do not
silently create claim votes. Coverage policy applies to the declared selected task
set, which is recorded explicitly, rather than inferred from whichever logs exist.

For example, two task logs, each with three epochs, yield one evidence row when
the request selects task A's reduced accuracy: `metrics.evaluate.score = 0.75`
(illustrative), with task B's results and all epochs in the artifact. There must be
one claim evaluation, not two or six. To obtain separate task claims, schedule
separate task nodes; to compare multiple results, add an explicit downstream node
that reads the normalized records and emits its own single result artifact.

Phase 1 must prove this using captured multi-log/suite fixtures through real
kwdagger `build_tables`, `KWDaggerProcessor.load_available_result_rows`, and
`ClaimResultNamespace`. Record flat column examples, row counts, selectors,
ambiguous-selector errors, epoch reductions and verdict counts in the canonical
evidence ledger. Phase 6 repeats this experiment with production adapters; any
required generic evaluator changes must be justified by that evidence.

Normalized readers import no engine dependencies. Native import requires its
adapter runtime, verifies artifact identity and completeness, and labels unknown
provenance. Provide shared run/sample/metric accessors and a consumer example for
all three engines; retain HELM-only predictor APIs until separately migrated.

### Reproducibility, scheduling and resource ownership

Hash engine, adapter/schema/upstream versions, resolved task/suite membership,
task code/config file contents, data/model revisions, model roles, sampling/seeds,
epochs/reducers, solver/scaffold/tool versions, sandbox image digest, metric
selection, and evidence policy. Engine changes must invalidate reuse even if task
labels and selected scores match. Hash actual content rather than mutable paths.
External endpoint aliases require a revision/cache token for dependable reuse.
Record unknown identity explicitly and disable reuse where it cannot be justified.

kwdagger owns campaign scheduling and node-level cache/attempt policy; engines
own execution within a node. Bound engine concurrency by allocated resources.
If using `magnet/leasing.py`, pass leased endpoints to providers and avoid duplicate
model startup. Propagate cancellation through the engine to child workers and
sandboxes. Do not place secret values in arguments, hashes, or manifests; use
runtime environment bindings and redact credential-bearing native configuration.

Keep retries isolated and ensure a stale success marker cannot mask failure.
Import identity includes artifact content/version and lineage; re-importing an
edited Inspect log produces a new result identity. Native sample resume or
rescoring is not silently enabled by enabling MAGNET cache reuse.

## Dependency and Python strategy

Keep core MAGNET at Python >=3.11 and normalized readers/compilation engine-free.
Use lazy optional extras for HELM and Inspect; choose a tested olmo-eval packaging
strategy after checking its Git dependencies and publication constraints. Support
separate pinned worker environments/containers via MAGNET's existing mechanisms.
A shared environment is convenient where resolvable, never required for all engines.

olmo-eval requires a supported Python >=3.12 worker at the inspected revision.
Determine Inspect and HELM worker constraints from their selected versions. Python
markers must not silently imply unavailable execution works on 3.11. Missing extras,
unsupported Python, and incompatible upstream versions need actionable errors.
Do not add GPU/agent stacks automatically to core or `all`; install only supported
extras for the requested capability. Update locks after validating packaging.

### olmo-eval packaging go/no-go decision

At the end of phase 1, test installation from a clean CI worker at the selected
pin. Offer a co-installed optional extra only if resolution, distribution metadata,
and native generation/tool smoke tests succeed reproducibly. If Git dependencies,
resolver conflicts, or publishing constraints remain, choose the named fallback
**isolated-worker-only olmo-eval**: ship no olmo-eval runtime extra; provide a
pinned, reproducibly built worker environment/container with immutable dependency
references and an image digest or equivalent lock record. MAGNET communicates
through the same worker CLI and normalized artifact contract. Do not weaken core
constraints or pull conflicting agent stacks into core to force co-installation.

The fallback is supported delivery, not deferral of the olmo-eval adapter. It must
pass generation, tool-execution, cancellation, import and engine-free reader tests.
If neither installation mode works in clean CI, phase 1 is no-go for the full
three-engine release. Shared/other-adapter development can continue experimentally,
but the olmo-eval gate stays unchecked until a compatible pin or worker build is
validated; omitting that engine requires an explicit scope revision. Record the
choice and resolver evidence in the ledger rather than leaving packaging open.

### Security review of tool and sandbox boundaries

Before phase 7 closes, a designated reviewer must assess both new engines' task
loading, tool execution, sandbox isolation, host mounts/network access, secret
forwarding and logging, cancellation cleanup, and artifact import/path handling.
Use a `security-review` skill if it is available at implementation time; that skill
is mentioned in the feedback but is not available in this session's skill catalog.
Its absence must not waive the review: perform and record a manual review against
these boundaries. This is a future implementation gate, not a claim of review now.

Record reviewer, implementation revision, threat assumptions, findings, fixes,
and targeted test evidence in the ledger. Blocking findings must be fixed and
retested before phase 7 passes. Record nonblocking residual risks with rationale
and reviewer acceptance. A worker container alone is not a guarantee of tool
isolation; document what executes on the host and the privileges it receives.

### External-test reliability policy

Keep external endpoint/sandbox tests separate from routine deterministic CI.
Capture the first failure and classify it as a product defect, infrastructure
failure, or unresolved. Allow at most two retries after the initial attempt for
identified transient infrastructure failures, with backoff and isolated output
paths. Retry only test fixtures whose operations are safe to replay; never
blindly replay arbitrary agent tools. Preserve every attempt, not just a green one.

Product failures and unresolved failures block the relevant release capability.
Quarantine a flaky test only with a named owner, issue, reason and expiry/review
date recorded in the ledger. Quarantine is not a passing check and cannot waive
required endpoint or sandbox acceptance. A quarantined required test must be
repaired and pass, or an equivalent reviewed check must pass against the same
release candidate/configuration. Otherwise the release gate stays open. Optional
deferred features may remain unchecked and unsupported as already specified.

## Implementation sequence and acceptance gates

Every implementation task starts unchecked. Phase 2's gate is provisional, not
contract finality. Phases 3 and 4 depend on phase 2 and may proceed concurrently;
phase 5's adapter work can also proceed once those contracts exist. Coordinate
shared-contract edits across tracks. Phase 6's joint gate requires phases 3–5,
and freezes the contract only after production integration passes. Phase 7's
operational review and phase 8's release review remain mandatory.

### Evidence ledger and checkbox rules

Create `docs/backend-integration-evidence.md` in phase 1 as the single canonical
record for all implementation tasks, validation checks, design decisions and gates.
Checkbox IDs below are stable references; preserve them when moving tasks and
assign new IDs rather than renumbering completed work. For each checked item,
record its ID, date, implementer/reviewer, MAGNET revision, upstream pins, Python/
dependency or container identity, exact command/test IDs, outcome, and links to
relevant artifacts. For documentation/design tasks, link the reviewed deliverable
and record test execution as not applicable with a reason.

CI may store large logs, but the ledger must contain durable summaries and retained
artifact references/checksums, with no credentials. Failed/retried/quarantined and
blocked checks keep their history and remain unchecked until resolved. A gate entry
links its prerequisite records and reviewer decision. PR descriptions and CI job
pages link back to this ledger rather than serving as competing evidence stores.
Create the ledger during implementation; this planning revision does not assert
any runtime checks have been executed.

### 1. Verify native APIs and select supported versions

- [ ] **P1-01** Create the canonical evidence ledger and task/gate record template.
- [ ] **P1-02** Select and record upstream pins, Python requirements, minimal dependency
  sets, and reproducible worker installation instructions for all three engines.
- [ ] **P1-03** Run a tiny local olmo-eval generation task and real scaffold/tool task;
  capture native success, failure-gate, and trajectory fixtures.
- [ ] **P1-04** Run a tiny local Inspect generation task and real solver/agent tool task;
  capture returned logs, sample errors, epochs/reductions, and cancellation fixtures.
- [ ] **P1-05** Exercise HELM compute and cached materialization/import on local fixtures;
  capture aggregate/per-instance records and missing-coverage behavior.
- [ ] **P1-06** Verify custom task/tool imports across workers, public async entry points,
  cleanup behavior, and supported model/scaffold combinations for both new engines.
- [ ] **P1-07** Record the initial capability matrix and settle optional extras versus
  isolated worker installation, including conflicting dependencies.
- [ ] **P1-08** Spike multi-log Inspect and olmo-eval suite fixtures through real kwdagger
  aggregation and `ClaimResultNamespace`; record the one-artifact/one-row design
  note, sample columns, selector errors, epoch reductions and claim counts.
- [ ] **P1-09** Record the olmo-eval packaging go/no-go decision from clean CI, including
  isolated-worker-only fallback evidence or a blocking no-go outcome.
- [ ] **P1-10** **Acceptance gate:** packaging has a reproducible supported path and the
  cardinality spike preserves one claim per artifact; demonstrate scored native
  generation in all engines,
  actual multi-turn tool execution in both new engines, and diagnosed failure
  fixtures at documented pins, without claiming unsupported capabilities.

### 2. Implement shared contracts, registry and artifacts

- [ ] **P2-01** Define versioned request/context/resolved-result/sample/metric/capability
  schemas, including multi-result cardinality, epoch identity and eligibility.
- [ ] **P2-02** Mark new adapter/shared API surfaces experimental in docstrings, registry
  metadata and docs; preserve existing HELM compatibility guarantees.
- [ ] **P2-03** Define schema evolution/migration policy and candidate v1 fixtures, including
  a test-only next-reader harness for compatibility and migration-error checks.
- [ ] **P2-04** Implement lazy registration for `helm`, `olmo_eval`, and `inspect_ai` with
  useful unknown-engine, missing-dependency, and version errors.
- [ ] **P2-05** Implement static request validation, native-option validation boundaries,
  conflict rules, and runtime task/provider capability validation.
- [ ] **P2-06** Implement preflight resolution and canonical content identity, including
  the no-cache behavior for unresolved mutable inputs.
- [ ] **P2-07** Implement shared sync/async execution/import facades and worker CLI with
  cancellation, nonzero failure exits, and a multiprocessing-safe main guard.
- [ ] **P2-08** Implement normalized result publication, metric selection, secret
  redaction, attempt records, eligibility checks and atomic `DONE` handling.
- [ ] **P2-09** Implement engine-free output readers and run/sample/metric accessors with
  schema and artifact validation.
- [ ] **P2-10** **Acceptance gate:** shared contract tests pass without engines installed;
  stub adapters verify multi-result handling, sync/async calls, import, failures,
  publication and schema compatibility behavior before production adapters rely
  on these provisional contracts; record that API freeze is deferred to phase 6.

### 3. Implement olmo-eval adapter

- [ ] **P3-01** Translate resolved requests into task specs/overrides and harness/provider
  configuration; call `AsyncEvalRunner.validate()` and supported execution APIs.
- [ ] **P3-02** Support native task variants/suites and importable custom registrations,
  preserving native scoring and suite aggregation.
- [ ] **P3-03** Normalize all task results and samples, retain native predictions/requests
  and trajectories, and map saved/processed/failed counts and failure gates.
- [ ] **P3-04** Implement native artifact import with identity/coverage verification and
  optional-runtime errors isolated from normalized readers.
- [ ] **P3-05** **Acceptance gate:** shared facade executes and reloads scored generation
  and tool tasks, imports equivalent native artifacts, and rejects failed output
  as eligible evidence using the common policy.

### 4. Implement Inspect adapter

- [ ] **P4-01** Resolve task references/factories and task parameters; map model-role
  bindings, generation options, limits, and typed native evaluation options.
- [ ] **P4-02** Invoke the public evaluation API in the supported async/worker mode;
  collect every returned log and inspect native task/sample status explicitly.
- [ ] **P4-03** Normalize scorer-qualified metrics, sample scores, epochs/reductions,
  usage and trace references without flattening away result identities.
- [ ] **P4-04** Preserve native `.eval`/JSON logs and implement import through Inspect log
  readers, including changed-log identity and incomplete/error/cancelled status.
- [ ] **P4-05** Integrate native solver/agent/tool execution and cleanup without adding
  a competing eval-set scheduler or automatic native retry loop.
- [ ] **P4-06** **Acceptance gate:** the same shared facade handles Inspect generation,
  tool execution, multi-log results, epochs and native import; error/cancelled
  logs cannot become eligible evidence merely because an API call returned.

### 5. Adapt HELM and preserve compatibility

- [ ] **P5-01** Wrap existing HELM execution/materialization for compute and cache reuse
  behind the shared protocol without changing existing CLI/import contracts.
- [ ] **P5-02** Normalize HELM aggregate/per-instance results and import existing run
  directories with explicit unknown coverage/provenance handling.
- [ ] **P5-03** Advertise verified capabilities and reject unsupported agentic/options
  combinations before expensive execution.
- [ ] **P5-04** Add a shared-reader consumer example that reads results from all engines
  without HELM-specific columns; retain existing HELM predictor APIs.
- [ ] **P5-05** **Acceptance gate:** HELM computes and imports through the shared facade,
  equivalent native data retains its metrics, and existing HELM recipes/loaders
  and legacy evaluator regressions pass unchanged.

### 6. Integrate generic kwdagger execution and claims

- [ ] **P6-01** Add generic `EvaluationNode`, pipeline factory and common result loader
  with stable `metrics.evaluate.*` columns and engine provenance.
- [ ] **P6-02** Integrate resolved identity before cache assignment and validate completion
  markers/artifacts on reuse; avoid cross-engine cache collisions.
- [ ] **P6-03** Add generation recipes for all engines using `result_node: evaluate`,
  requested evidence scope, symbol metadata, and selected-metric claims.
- [ ] **P6-04** Add a mixed-engine pipeline with explicit task/metric mapping and an
  explicit downstream comparison; do not assume scores are interchangeable.
- [ ] **P6-05** Implement side-effect-free dry-run and separate preflight worker resolution
  while preserving scheduler `--backend` semantics.
- [ ] **P6-06** Repeat the cardinality spike with production adapters and explicitly
  reconcile any provisional-contract changes across all adapters and fixtures.
- [ ] **P6-07** Review and record the initial API/schema freeze after all three adapter
  gates and production integration tests pass; freeze the v1 fixtures and leave
  experimental labels in place.
- [ ] **P6-08** **Acceptance gate:** the joint API/schema freeze is recorded and all three
  recipes run through `magnet evaluate_new`
  with serial scheduling and existing dashboard bundles; mixed-engine execution,
  evidence scopes, cache invalidation, and dry-run behavior pass end to end.

### 7. Complete agentic and operational behavior

- [ ] **P7-01** Package deterministic multi-turn/custom-tool recipes for both new engines
  and verify their task scores reach the same MAGNET claim interface.
- [ ] **P7-02** Expose native trace references and normalized trajectory accessors with
  explicit availability and loss-of-detail metadata.
- [ ] **P7-03** Enforce configured capability, secret, turn/time/concurrency limits and
  map tool/judge errors consistently through shared evidence policy.
- [ ] **P7-04** Implement cancellation cleanup and isolated node retries; document which
  native resume/rescore features are intentionally unsupported initially.
- [ ] **P7-05** Integrate external and leased endpoints plus worker containers with
  resource limits and no duplicate model startup.
- [ ] **P7-06** Add an opt-in sandbox example for each new engine at its supported pin.
- [ ] **P7-07** Complete the security review for both new tool/sandbox boundaries using
  the available skill or documented manual fallback; fix and retest blocking
  findings and record accepted residual risks in the ledger.
- [ ] **P7-08** **Acceptance gate:** the security review is recorded with no unresolved
  blocking findings; both agentic recipes execute real tools and preserve
  traces; terminated runs leave no owned workers/sandboxes or eligible partial
  artifacts, and leased endpoints are reused within allocated resources.

### 8. Documentation, packaging and release verification

- [ ] **P8-01** Document shared API/CLI/recipe contracts, backend options, capability
  matrix, native import, result schema, cache identity and failure semantics.
- [ ] **P8-02** Document task portability limits, epoch/suite aggregation, cross-engine
  comparison requirements, and the remaining HELM-only predictor boundary.
- [ ] **P8-03** Package all examples and validate chosen extras, worker environments,
  dependency locks and generated dependency files.
- [ ] **P8-04** Add engine-free, per-engine and compatible-combination CI jobs; keep
  paid/GPU/sandbox tests separately gated.
- [ ] **P8-05** Implement external-test failure classification, bounded safe retry and
  quarantine tracking; required quarantined tests must not turn gates green.
- [ ] **P8-06** Audit ledger coverage for checked tasks and gates, including schema
  compatibility, packaging fallback, API freeze and security-review evidence.
- [ ] **P8-07** Run clean-environment walkthroughs for three generation recipes, two
  agentic recipes and the mixed-engine comparison, recording results.
- [ ] **P8-08** **Release gate:** all required conformance, native contract, regression
  and end-to-end tests below pass. External endpoint and sandbox smoke checks
  pass for supported release configurations; deferred capabilities remain
  explicitly unsupported, with unexecuted checks left unchecked. Required smoke
  checks comply with the reliability policy; quarantine does not waive a failure.
- [ ] **P8-09** After the release gate passes, remove experimental labels from supported
  API/adapters and publish their frozen contract and compatibility policy.

## Validation plan

Each checkbox requires adding or selecting meaningful tests and running them
successfully. Record environment, upstream pin and outcome under the checkbox ID
in `docs/backend-integration-evidence.md`; unavailable opt-in
checks remain unchecked. Mock/stub unit tests do not replace native API contracts.

### Engine-free schemas, registry and artifacts

- [ ] **V-001** Test request serialization, unknown engines/fields, option precedence,
  conflicting duplicates and unsupported capability errors.
- [ ] **V-002** Test lazy registry/import behavior and actionable missing-extra/version
  errors with every engine absent.
- [ ] **V-003** Test canonical hashes across engine/version changes, config/task code
  edits, task/model/data revisions, roles, seeds, epochs/reducers and policy.
- [ ] **V-004** Test unresolved identity disables reuse and secret values are excluded
  from hashes, commands, manifests and redacted configurations.
- [ ] **V-005** Test multi-result selectors, metric-key collisions, structured sample
  scores and missing/ambiguous/non-finite scalar metrics.
- [ ] **V-006** Test sample identity across epochs, tasks, models and retry lineage;
  unknown counts remain unknown and retries do not inflate denominators.
- [ ] **V-007** Test schema rejection, corrupt/missing artifacts, interrupted publication,
  eligibility reasons and stale completion markers after a failed attempt.
- [ ] **V-008** Read frozen schema-N artifacts with a schema-N+1 reader/compatibility
  harness without engine packages; verify preserved metrics and sample identity,
  or actionable migration errors for explicitly unsupported versions. Test unknown
  future versions and migration lineage without mutating original artifacts.
- [ ] **V-009** Verify experimental flags are exposed consistently and remain set until
  the release gate; regression-test existing HELM API availability throughout.

### Shared adapter conformance (parameterized over all three engines)

- [ ] **V-010** Execute a tiny local generation task, normalize/load its output, and
  verify selected metrics, coverage, status, provenance and native references.
- [ ] **V-011** Import the matching native fixture and verify metric/identity preservation
  without claiming provenance or coverage absent from the source.
- [ ] **V-012** Verify sync and async facade behavior, including an already-active event
  loop and worker cancellation/cleanup for blocking runtimes.
- [ ] **V-013** Exercise strict and explicitly permitted partial/unknown coverage policies;
  verify failed/incomplete outputs never gain eligibility by file existence.
- [ ] **V-014** Verify unsupported features fail explicitly and normalized results remain
  readable after the native engine is removed from the reader environment.

### olmo-eval native contracts

- [ ] **V-015** Test real task registration with local data/mock inference across spawned
  workers, task overrides, variants and native suite aggregation.
- [ ] **V-016** Verify nested metric/scorer values, prediction/request serialization,
  processed/saved/failed counts and native import fixtures at the pin.
- [ ] **V-017** Trigger upstream failure gates after artifacts are written and verify
  diagnostics survive without an eligible completion marker.

### Inspect native contracts

- [ ] **V-018** Test native task factory/parameter resolution, model roles and generation
  settings with local data and a deterministic provider.
- [ ] **V-019** Test multiple returned logs and duplicate sample IDs across tasks/models;
  every native result must map to a distinct normalized record.
- [ ] **V-020** Verify multiple scorers, structured sample scores, epochs and reducers
  preserve native aggregates and the correct sample/repetition denominator.
- [ ] **V-021** Test `.eval` and JSON log imports via native readers, trace preservation,
  changed-log identity, and normalized reading without Inspect installed.
- [ ] **V-022** Test returned error/cancelled/nonterminal logs, sample failures and success
  with insufficient coverage; verify conservative eligibility and CLI exits.

### HELM compatibility contracts

- [ ] **V-023** Test compute, reuse-only, compute-if-missing and native import paths
  against the existing materialization behavior and result fixtures.
- [ ] **V-024** Verify aggregate/per-instance normalization, absent per-instance coverage,
  and shared-reader access without synthesizing HELM records for other engines.
- [ ] **V-025** Run existing HELM loader/materialization, predictor-related and legacy/new
  evaluator regressions; verify old imports and commands remain compatible.

### Agentic contracts (olmo-eval and Inspect separately)

- [ ] **V-026** Execute each real native scaffold/solver with a scripted provider or stub
  endpoint; assert actual tool invocation and ordered multiple turns.
- [ ] **V-027** Verify final score, native transcript and normalized trajectory access,
  tool arguments/results, termination details and missing usage behavior.
- [ ] **V-028** Exercise max-turn/time limits, missing secrets, tool failures and judge
  failures; verify policy results and retained diagnostic artifacts.
- [ ] **V-029** Cancel active workers and sandbox runs; verify cleanup and absence of
  eligible artifacts or orphaned owned resources.

- [ ] **V-030** Run targeted security regression checks for forbidden host access/mounts,
  secret leakage in logs/tool errors, malicious artifact paths and cancellation
  cleanup; map each review finding to a test or documented manual verification.

### MAGNET pipelines and evidence

- [ ] **V-031** Run serial generation recipes for all engines and verify common metric
  columns, symbol metadata, claims and dashboard artifact compatibility.
- [ ] **V-032** Run both agentic recipes and verify their scores/trace references reach
  the same evidence contract as generation results.
- [ ] **V-033** Run a mixed-engine pipeline with explicit task mapping and downstream
  aggregation; verify isolated identities and retained engine provenance.
- [ ] **V-034** Feed multi-task/multi-model Inspect logs with repeated epochs and olmo-eval
  suite results through `build_tables`, `load_available_result_rows` and claim
  evaluation; assert exactly one row/verdict per artifact, correct selected
  reduced metric, no silent averaging and rejection of ambiguous selectors.
- [ ] **V-035** Test requested versus accumulated evidence, requested cached results,
  and failure provenance independently of scientific claim truth.
- [ ] **V-036** Test same-engine reuse and invalidation after engine/config/code/policy
  changes; failed attempts and stale markers cannot mask incomplete outputs.
- [ ] **V-037** Test dry-run with no engine installed: no task-factory execution, model
  startup, tool calls, dataset download, evidence publication or verdict.
- [ ] **V-038** Verify scheduler `backend` remains independent of engine selection and
  worker/container/lease settings reach each engine without duplicate startup.

### Dependency matrix and external smoke tests

- [ ] **V-039** Run Python 3.11 base-only import, compilation and normalized-reader tests.
- [ ] **V-040** Run each engine's contracts in its supported pinned Python/dependency
  environment, including olmo-eval's Python 3.12+ worker.
- [ ] **V-041** Test compatible pair/all-engine installations where resolvable; document
  incompatible combinations and verify isolated workers for those combinations.
- [ ] **V-042** Verify isolated-worker-only olmo-eval from a clean CI build when selected:
  no olmo-eval runtime extra in core, pinned worker generation/tool/import tests,
  cancellation cleanup and normalized reading outside the worker.
- [ ] **V-043** Exercise schema upgrade compatibility using frozen release fixtures in
  engine-free CI; retain fixtures across subsequent releases.
- [ ] **V-044** Inject transient infrastructure failures, product errors and unsafe-to-replay
  operations into the smoke-test harness; verify retry limits/backoff, attempt
  retention, quarantine owner/expiry tracking and release blocking behavior.
- [ ] **V-045** Run small external-endpoint generation smoke tests for both new engines.
- [ ] **V-046** Run each new engine's opt-in sandbox example and verify output and cleanup.
- [ ] **V-047** Run native local vLLM smoke tests only if that capability is added; otherwise
  leave this deferred capability unchecked and outside release claims.
- [ ] **V-048** Verify routine CI excludes external-resource tests and requires no paid
  APIs, downloaded models, GPUs, network datasets or sandbox daemon.

## Decisions and remaining uncertainties

The shared interface, three adapters, generic node, normalized accessors and
conformance suite are required scope. Preserve existing HELM APIs; defer wholesale
predictor migration and framework-specific resume/rescore operations. One real
agent/tool path in each new engine is required, not merely a capability flag.

The initial probes must settle supported upstream pins, installability, native
async/worker behavior, custom registration, status mapping, and precise result
schemas. Gate upstream upgrades with native fixtures and adapter conformance tests.
Task factories may do arbitrary work; static dry-run must never invoke them.
Deterministic configuration records do not guarantee identical responses from
stochastic models or mutable external tools. Document these limits and require
explicit mappings for substantive cross-engine comparisons.
