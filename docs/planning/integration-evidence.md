# MAGNET integration evidence (plan M1-M10)

Canonical record for `aiq-magnet-integration-plan.md`. Date 2026-09-29.
Evidence producer: Claude Opus 5.5 (Anthropic, `claude-opus-5-5`, 1M context).

This pass followed an integration review. It records what was checked, where,
and with which commands. Hosted CI has not run for either repository: nothing
had been pushed when this was written.

## Revisions and environments

| Item | Value |
| --- | --- |
| aiq-magnet-evals | `main` through `ece89b4` (ADR-0010 to ADR-0012, identity v3, worker isolation, rename, packaged examples, Docker sandbox, review fixes, `lock_held`, per-role Inspect endpoints, import snapshots), plus documentation commits |
| aiq-magnet | branch `dev/aiq-evals-integration`: `c0f07a5` (fixes and tests), `40cb99a` (recipes), `ecf1bf6` (CI job), `27d8a51`, `c0a6a5d`, and the container-lease commit (review fixes); `uv.lock` pending |
| HELM worker and MAGNET | CPython 3.12.3; `crfm-helm==0.5.14` with `dev/environments/phase1/helm-py312-constraints.txt`; kwdagger 0.4.1, cmd_queue 0.3.2 |
| Inspect worker | CPython 3.11.15 (uv-managed); `inspect-ai==0.3.272` with `inspect-py311-constraints.txt` |
| OLMo worker | olmo-eval `73ade80e24f796af55caeb8fd7b75a7f3fd607fd`, `uv sync --frozen --extra litellm --extra agents`, CPython 3.12.3 |
| Container side | `ubuntu:24.04` (`sha256:008173c2…3ca3`); MAGNET venv on uv-managed CPython 3.13.2; Docker 29.1.3, Compose 2.40.3 |
| Scheduler | tmux 3.4 for the concurrent test; serial elsewhere |

The MAGNET commands below run from the MAGNET checkout. Set
`AIQ_EVALS_REPO=<aiq-magnet-evals checkout>`,
`AIQ_EVALS_INSPECT_PYTHON`, `AIQ_EVALS_OLMO_PYTHON`, and
`MAGNET_REQUIRE_AIQ_EVALS=1` (any unavailable prerequisite then fails rather
than skips). `dev/ci/aiq_evals_integration.sh` builds all of this from scratch.

## Review findings -> fixes

| Finding | Fix | Evidence |
| --- | --- | --- |
| 1 API frozen too early | ADR-0010 supersedes ADR-0009: no freeze before a PyPI release | `test_public_api_freeze.py` removed |
| 2 duplicate execution under concurrency | ADR-0011: `flock` single-flight per measurement in the store | aiq-magnet-evals `tests/test_single_flight.py` (threads, 3 processes, killed holder, cancellable wait); MAGNET `test_concurrent_selector_nodes_execute_the_native_evaluation_once` (tmux, 3 selector nodes: 1 executed, 2 reused, 1 store attempt) |
| 3 changed import silently ignored | ADR-0011: imports keyed by native content; MAGNET node carries `import_identity` | `test_different_native_content_is_imported_not_reused`, `test_editing_native_content_at_the_same_path_reimports`; MAGNET `test_editing_imported_native_files_in_place_reruns_the_node` (HELM stats edited in place: 0.25 then 0.75) |
| 4 evidence JSON trusted | evaluation.json v2 stores run reference + projection only; rows recomputed from the validated run; done-check pins the scheduled projection | `test_edited_evaluation_json_cannot_change_the_evidence`, `test_edited_run_payload_invalidates_the_node`, `test_done_check_pins_the_scheduled_projection` |
| 5 preflight bypassed containers | preflight runs `cli.resolve_node` through the node's own wrapper | `test_preflight_runs_through_the_node_container`; real Docker: `test_container_only_worker_resolves_and_executes_in_the_container` (worker exists only at `/opt/aiq-inspect-worker` in the container) |
| 6 `measurement_identity` configurable | computed keys rejected in recipes and overwritten by every preflight | `test_measurement_identity_is_computed_never_configured` |
| 7 integration tests could skip in CI; stale lock | `MAGNET_REQUIRE_AIQ_EVALS=1`; xcookie source check `aiq-magnet-evals` running `dev/ci/aiq_evals_integration.sh`; uv git source | local CI reproduction below; `uv.lock` pending a push (see "Open") |
| 8 unfinished examples | recipes use installed `magnet_evals.examples`, ship as package data, have end-to-end tests | `tests/test_aiq_evals_examples.py` |
| 9 rename incomplete | metadata, CLI (`aiq-magnet-evals`, alias `aiq-evals`), docs; identity strings kept | `AGENTS.md` "Names" |

An independent review of this pass then found, with reproductions, and these
were fixed (regression tests in `tests/test_single_flight.py` and MAGNET's
`test_aiq_evals_integration.py`):

- Imports of different content raced to seed the shared canonical run: a raw
  `OSError` escaped in 81-97 of 200 trials. Seeding now happens under the
  measurement lock, and a lost rename is a `PublicationError`.
- Cancelling the lock holder during promotion released the lock early, so the
  engine ran twice. Promotion now finishes first.
- A failed holder-note write leaked the lock. The note is now best-effort.
- Sibling directory symlink cycles recursed until `ELOOP`.
- Row loading trusted the selector and policy in `evaluation.json`. Rows are
  now pinned to kwdagger's scheduling record for that directory (`invoke.sh`:
  the done-check's `--expected` and the `--request`).
- kwdagger's mtime-keyed row cache could serve a row after its run changed. It
  is bypassed for pipelines with an `EvaluationNode`.
- One invalid node aborted loading of every row. It now yields an ineligible
  row with the reason.
- Preflight required secret values that only a later lease provides.
  Resolution now uses `require_secrets=False`.

A second integration review then found the following, fixed in MAGNET
`c0a6a5d` and aiq-magnet-evals `6429b31`:

| Finding | Fix | Test |
| --- | --- | --- |
| `evaluation.json` could redirect a node to another valid bundle of the same measurement | the run must be the scheduled acquisition slot (canonical run, scheduled import slot, or unkeyed attempt of the scheduled store) | `test_evaluation_json_cannot_redirect_to_another_run_of_the_measurement`, `test_import_nodes_must_load_their_scheduled_import_slot` |
| `comparison.json` chose the compared nodes and mapping | comparison rows take both from the compare node's `invoke.sh` | `test_comparison_rows_follow_the_scheduled_inputs` |
| lease decided at render time (duplicate leases under concurrency; a run that vanished after rendering executed without a lease) | host-side gate under the store lock; leased child runs `ensure(lock_held=True)` | `test_leasing_is_decided_by_a_gate_when_the_node_runs`, `test_concurrent_gates_start_one_leased_child`; live: `tests/test_aiq_evals_lease.py` |
| preflight unbounded | `preflight_timeout_seconds` (default 900 s), process group killed | `test_preflight_is_bounded_and_kills_its_process_group` |
| staleness detected after executing | re-resolve and hash imports before `ensure` | `test_a_stale_schedule_stops_before_any_engine_work` |
| single leased (primary) endpoint | `endpoints: {role: alias}`, one multi-endpoint lease; Inspect per-role overrides | live Inspect primary+grader lease; `test_leased_endpoint_override_for_an_auxiliary_role` (aiq-magnet-evals, `openai` variant) |

Live leases: `tests/test_aiq_evals_lease.py` runs real `infer-stack run`
(0.7.0, null serving backend, private ledger). A PATH shim only adds
`--base_url` to point the lease gateway at the example endpoint. An OLMo agent
run executes inside a lease, and a second selector node reuses it with no new
lease (the ledger holds exactly one). An Inspect primary and a separately
leased grader share one lease claiming both endpoints. Requests name a dead
`base_url`, so success proves the lease supplied the endpoint.

A third review found the following, fixed in aiq-magnet-evals (ADR-0012,
identity v3) and MAGNET:

| Finding | Fix | Test |
| --- | --- | --- |
| an import read its live source twice (normalized 0.25, bundled 0.75) | one snapshot feeds identity, normalization, and publication; `expected_import_identity` refuses other content before anything is published | `test_an_import_normalizes_and_preserves_the_same_bytes`, `test_an_import_of_other_content_than_expected_publishes_nothing` (both fail on the old code); MAGNET passes its scheduled `import_identity` |
| an explicit import became the canonical (executed) result | imports never seed the canonical run (ADR-0012) | `test_different_native_content_is_imported_not_reused`, `test_import_then_reuse_and_changed_artifact_identity` |
| container + lease lost the served-model check | `INFER_STACK_ENDPOINT_<ALIAS>` forwarded into the container for each leased alias; a missing variable is an error, never assumed | `test_leasing_is_decided_by_a_gate_when_the_node_runs`; live `test_a_leased_container_verifies_the_served_model` (alias `example-lease` serves `gpt-4o-mini`; fails with forwarding disabled) |
| operational fields in the identity | identity v3 drops `required_secrets` and `provider_options.base_url` (and adapter copies) | `test_operational_request_fields_do_not_change_the_measurement`, `test_endpoint_url_is_not_a_measurement_input` (Inspect, OLMo) |

A fourth review found, and this fixed (aiq-magnet-evals `5d55369`, MAGNET's
following commit):

| Finding | Fix | Test |
| --- | --- | --- |
| MAGNET required raw request equality, so identity-v3 reuse after only an endpoint or credential-name change started a lease or looked invalid | a run pinned by measurement digest is accepted on identity and slot; `evaluation.json` must still record the scheduled request | `test_reuse_across_operational_request_changes_is_valid_evidence`; live: endpoint-only change reuses with no new lease |
| nested `required_secrets` and OLMo's `harness_config.provider.base_url` still changed the digest | all secret-name lists removed at any depth; adapters declare request-level endpoint paths; empty blocks pruned | `test_nested_secret_names_do_not_change_the_measurement`, `test_harness_endpoint_url_is_not_a_measurement_input` |
| reuse required credentials | `ensure` resolves without the secret check; execution checks; imports never need them | `test_reuse_does_not_need_the_credentials_execution_needed` |

A fifth review found, and this fixed (aiq-magnet-evals `23ad474`, MAGNET's
following commit):

| Finding | Fix | Test |
| --- | --- | --- |
| the lease gate reused a cached run without re-resolving, so a task/engine/adapter change after scheduling went unnoticed on the leased path | the gate runs the node's preflight command (same host/container wrapper, no lease) before reusing; a changed identity reschedules | `test_a_gate_does_not_reuse_a_run_whose_identity_changed`; rendering check in `test_leasing_is_decided_by_a_gate_when_the_node_runs` |
| `required_secrets` nested in OLMo's `harness_config` still changed the digest through `native_config` | secret-name lists removed from `native_config` at any depth too | `test_nested_secret_names_in_the_harness_are_not_measurement_inputs` (real OLMo adapter; fails on the old code) |

The review's plan-accounting points are now explicit scope revisions R1-R4 in
`aiq-evals-plan.md`: OLMo sandboxing, OLMo judge errors, release smoke checks
(release gate G10), and the MAGNET M1 migration.

Two further defects found and fixed during this pass:

- Workers received the caller's whole `site-packages` on `PYTHONPATH` when
  `magnet_evals` was installed from a wheel. They now see only the package
  (`worker_package_path`). The walkthrough installs the wheel to cover this.
- `run_node` doubled a full `evaluation_fname` path. That broke relative
  output roots, which the old tests never used.

## E-M1 Compatibility

MAGNET's full suite, with every integration prerequisite required
(`PATH=<helm-venv>/bin:$PATH MAGNET_REQUIRE_AIQ_EVALS=1 MAGNET_TEST_DOCKER=1 ... python -m pytest -q magnet tests`,
Docker group): 472 passed, 16 skipped (MAGNET's own optional skips), 0 failed.
The legacy evaluator, HELM loaders/materialization, predictor, and llama/theory
card tests are unchanged and pass. (Card nodes run a bare `python`, so the venv
must be on `PATH`; without it, 4 card tests fail on `main` too.)

`ty check ./magnet ./tests` reports the same 12 diagnostics as `main`, none in
the integration code.

## E-M3 Identity

| Requirement | Test (`tests/test_aiq_evals_integration.py`) |
| --- | --- |
| preflight before identity, in the node's environment | `test_preflight_runs_through_the_node_container`; container test |
| identities computed, never configured | `test_measurement_identity_is_computed_never_configured` |
| unresolved input disables reuse | `test_non_reusable_identity_always_executes` |
| task code change -> new node | `test_task_code_change_reruns_the_node` (Inspect task file edited) |
| imported content change -> new node | `test_editing_imported_native_files_in_place_reruns_the_node` |
| stale marker cannot hide a broken run | `test_reuse_selector_change_and_stale_marker` (tampered canonical run -> new attempt) |
| selector change reuses the native run | same test: `['executed', 'reused']`, one store attempt |

## E-M4 Evidence projection

The view (`projection.evidence_view`) is computed on every load from a run that
passed full checksum validation and matches the recorded measurement,
normalized-artifact, and import identities. The recorded selector, coverage
policy, identities, and request must also match the directory's scheduling
record, the `invoke.sh` that kwdagger rendered. Values written into
`evaluation.json` are ignored. A changed run, projection, or request yields an
ineligible row with the reason, and the done-check reruns the node.
Tests: `test_edited_evaluation_json_cannot_change_the_evidence`,
`test_edited_projection_is_rejected_when_rows_load`,
`test_a_run_of_another_request_is_rejected_when_rows_load`,
`test_edited_run_payload_invalidates_the_node`,
`test_done_check_pins_the_scheduled_projection`, and
`test_rows_are_never_served_from_a_stale_cache` (HELM).

Residual: `invoke.sh`, `evaluation.json`, and the run are local files. Someone
who can rewrite all of them consistently can still substitute evidence. These
are integrity checks, not authentication.

## E-M6 Cardinality (production adapters)

`test_cardinality_inspect_multi_log_epochs` (three task logs x two epochs, an
auxiliary role) and `test_cardinality_olmo_suite_prefix_overlapping_tasks`
import the committed native fixtures through real workers. The rows are loaded
by kwdagger `build_tables` / `KWDaggerProcessor.load_available_result_rows` and
judged by `evaluate_new` (`ClaimResultNamespace`). There is one row and one
verdict per artifact, and one import reused by the other projections. Nothing
is averaged: a rejected selection has no `score`. Duplicate sample IDs and
epochs stay inside the run.

Flat columns, captured from the Inspect fixture with two selectors (run paths
elided):

```text
select {"metric":"accuracy","scorer":"match"}                  select {"task":"role_task","scorer":"match","metric":"accuracy"}
metrics.evaluate.action            reused                      imported
metrics.evaluate.candidates        3                           1
metrics.evaluate.eligible          false                       true
metrics.evaluate.ineligible_reasons  selector ... is ambiguous: 3 metrics match; ...   ""
metrics.evaluate.selected.task     null                        role_task
metrics.evaluate.selected.scorer   null                        match
metrics.evaluate.selected.metric   null                        accuracy
metrics.evaluate.selected.value    (absent)                    1.0
metrics.evaluate.score             (absent)                    1.0
metrics.evaluate.denominator       (absent)                    1.0
metrics.evaluate.coverage.status   null                        complete   (expected 2, processed 2, failed 0)
metrics.evaluate.engine            inspect_ai                  inspect_ai
metrics.evaluate.measurement_identity  82c9ac49…be90c          82c9ac49…be90c
metrics.evaluate.import_identity   be742613…752c               be742613…752c
metrics.evaluate.normalized_artifact_identity 311d881c…d669    311d881c…d669
```

Verdicts: the ambiguous row is `INCONCLUSIVE` and the unique row is `VERIFIED`.

## E-M7 Recipes

`tests/test_aiq_evals_examples.py`: all six recipes are packaged, reference no
test modules, and compile in an engine-free dry run. End to end through
`evaluate_new` with real workers, all six give `VERIFIED`: HELM, Inspect, and
OLMo generation; Inspect's local-sandbox tool; OLMo OpenAI Agents against the
example endpoint (no key value in any JSON); and the HELM-vs-Inspect
comparison (two distinct measurement identities, `comparable: true`).
19 passed.

## E-M8 Scheduling and resources

- Leasing: `test_lease_runtime_maps_lease_env_and_refuses_mismatch`,
  `test_lease_wraps_only_when_native_work_is_needed` (no lease for a stored run
  or an import).
- Cancellation: `test_sigterm_cancels_the_engine_worker` (the HELM child is
  reaped; the attempt is `cancelled`).
- Containers: `tests/test_aiq_evals_container.py`, real Docker. Preflight and
  execution both run in `ubuntu:24.04`, with a worker interpreter mounted only
  inside the container. Preflight and executed digests agree. A second
  schedule re-resolves in the container and reuses the node.
- Scheduler independence: serial throughout, and tmux in the concurrency test.
- Real GPU serving: MAGNET's `dev/ci/aiq_evals_real_gpu.sh` and
  `tests/test_aiq_evals_real_gpu.py` cover Inspect one-shot evaluation,
  Inspect agentic tool execution, and OLMo agentic tool execution against a
  GPU-served infer-stack endpoint. Canonical OLMo publication and reuse without
  another leased command are covered separately by the mounted-worker/null-serving
  regression in `tests/test_aiq_evals_lease.py`.

## E-M9 Dry run

`test_dry_run_resolves_nothing` (preflight patched to fail; no store, no
evaluation, `NOT_EVALUATED`), `test_static_errors_surface_in_a_dry_run`, and
`test_recipes_compile_in_a_dry_run_without_engines`.

## E-M10 Validation matrix

| Plan line | Test |
| --- | --- |
| common columns from all three engines | M7 recipes; `test_one_helm_evaluation_becomes_one_claim_row` |
| agentic results | `test_inspect_recipes[inspect_agent]`, `test_olmo_agent_recipe_against_the_example_endpoint` |
| requested vs accumulated scopes | `test_requested_versus_accumulated_evidence` |
| requested cached results | `test_reuse_selector_change_and_stale_marker` |
| failure provenance vs claim truth | `test_native_failure_is_provenance_not_a_verdict` (no row, not FALSIFIED, `attempt_status: failed`) |
| same-measurement reuse/invalidation | E-M3 |
| no cross-engine collision | `test_mixed_engine_comparison_recipe` |
| stale/failed attempts | E-M3; the failure test |
| serial and tmux | all tests; the tmux concurrency test |
| dashboard/card compatibility | `test_one_helm_evaluation_becomes_one_claim_row`: `card.yaml`, log, `results/*/verdict.json` with concrete symbols, `verdict.json` (the eval-card-viz upload contract; the viewer itself was not run) |
| HELM legacy regression | E-M1 |

Run: `python -m pytest -q tests/test_aiq_evals_integration.py` gives 39 passed;
`tests/test_aiq_evals_examples.py` gives 19 passed; the container test gives
1 passed (Docker group); `tests/test_aiq_evals_lease.py` gives 3 passed.

## CI

The xcookie-generated `.github/workflows/checks.yml` job `aiq-magnet-evals` runs
`dev/ci/aiq_evals_integration.sh`. The script clones aiq-magnet-evals at
`AIQ_MAGNET_EVALS_REV`, builds the MAGNET/HELM, Inspect, OLMo, and container
environments, and runs the three test files with `MAGNET_REQUIRE_AIQ_EVALS=1`.
It was reproduced locally from fresh environments, using the local evaluator
checkout (`AIQ_MAGNET_EVALS_DIR`); the result is recorded under "Local CI
reproduction".

### Local CI reproduction

`AIQ_MAGNET_EVALS_DIR=<aiq-magnet-evals checkout> dev/ci/aiq_evals_integration.sh <fresh dir>`
(run with Docker group access) builds all four environments from scratch and
runs the four files with `MAGNET_REQUIRE_AIQ_EVALS=1`: 62 passed, 0 skipped
(39 integration, 19 examples, 1 container, 3 live leases), exit 0, with
aiq-magnet-evals `23ad474`.

## Open

- **Push and pin.** MAGNET's CI pin (`AIQ_MAGNET_EVALS_REV`) and `uv.lock` need
  these aiq-magnet-evals commits on GitHub; the published `main` still has the
  pre-rename `aiq-evals` package.
- **Hosted CI (G8)** has not run for either repository.
- **M1 migration** of MAGNET's legacy HELM internals onto aiq-magnet-evals is
  deferred (see the plan).
- **Per-role endpoints** reach OLMo Eval's primary role only (it rejects
  auxiliary role bindings) and are unsupported for HELM (registry deployments).
- **Untested capabilities** stay untested: OLMo sandboxes, log probabilities,
  resume/rescore (`phase1-capabilities.md`).
