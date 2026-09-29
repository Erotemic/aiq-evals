# MAGNET integration evidence (plan M1-M10)

Canonical record for `aiq-magnet-integration-plan.md`. Date 2026-09-29.
Evidence producer: Claude Opus 5.5 (Anthropic, `claude-opus-5-5`, 1M context).

This pass followed an integration review. It records what was checked, where,
and with which commands. Hosted CI has not run for either repository: nothing
had been pushed when this was written.

## Revisions and environments

| Item | Value |
| --- | --- |
| aiq-magnet-evals | `main` after `8086431` (ADR-0010, ADR-0011, worker isolation, rename, packaged examples, Docker sandbox), plus this documentation commit |
| aiq-magnet | branch `dev/aiq-evals-integration`: `c0f07a5` (fixes and tests), `40cb99a` (recipes), then the CI/lock commit |
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

Two further defects found and fixed during this pass:

- Workers received the caller's whole `site-packages` on `PYTHONPATH` when
  `magnet_evals` was installed from a wheel. They now see only the package
  (`worker_package_path`). The walkthrough installs the wheel to cover this.
- `run_node` doubled a full `evaluation_fname` path. That broke relative
  output roots, which the old tests never used.

## E-M1 Compatibility

MAGNET's full suite: `PATH=<helm-venv>/bin:$PATH python -m pytest -q magnet tests`.
It gives 448 passed and 24 skipped, with 4 failures that also occur on `main`
when the venv is not on `PATH` (cards run a bare `python`). With the venv on
`PATH`, those 4 pass (`tests/test_llama_cards.py`, `tests/test_theory_cards.py`:
18 passed). The legacy evaluator, HELM loaders/materialization, predictor, and
llama/theory card tests are unchanged and pass.

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
normalized-artifact, and import identities. Values written into
`evaluation.json` are ignored. A changed run reference or identity makes the
node invalid, and a changed payload fails validation. See the finding-4 tests.

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

Run: `python -m pytest -q tests/test_aiq_evals_integration.py` gives 27 passed;
`tests/test_aiq_evals_examples.py` gives 19 passed; the container test gives
1 passed (Docker group).

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
runs the three files with `MAGNET_REQUIRE_AIQ_EVALS=1`: 47 passed, 0 skipped
(27 integration, 19 examples, 1 container), exit 0.

## Open

- **Push and pin.** MAGNET's CI pin (`AIQ_MAGNET_EVALS_REV`) and `uv.lock` need
  these aiq-magnet-evals commits on GitHub; the published `main` still has the
  pre-rename `aiq-evals` package.
- **Hosted CI (G8)** has not run for either repository.
- **M1 migration** of MAGNET's legacy HELM internals onto aiq-magnet-evals is
  deferred (see the plan).
- **Untested capabilities** stay untested: OLMo sandboxes, log probabilities,
  resume/rescore (`phase1-capabilities.md`).
