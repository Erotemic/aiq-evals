# Phase-5 evidence: HELM adapter

Status: IMPLEMENTED, EXPERIMENTAL; native acceptance passed at `crfm-helm==0.5.14`
for HELM's local simple model and the imported historical MMLU run (2026-09-29).
Evidence producer: Claude Opus 5.5 (Anthropic, `claude-opus-5-5`, 1M context).

## Design

`aiq_evals.backends.helm` is a MAGNET-independent reimplementation of the
generic HELM compute/import behavior. MAGNET's HELM predictor APIs and its
name-matching reuse stay in MAGNET.

- **Resolve** runs natively in the worker environment. It registers HELM's
  built-in configs and entry-point plugins, imports the declared `plugins`
  (module names only, so they can be hashed), and expands
  `<task>[:args],model=<bound model>` with HELM's own
  `run_entries_to_run_specs`. The canonical `RunSpec` dicts enter
  `native_config` and therefore identity. Plugin source digests and
  `adapter_source_sha256` are identity facts, and `verify_engine_revision`
  records the observed source revision.
- **Execute** calls `python -m helm.benchmark.run` (HELM's CLI module,
  `helm-run` entry point) with the worker's own interpreter; it never uses
  `PATH` (the Phase-1 hazard). Other command details:
  - it uses a fixed suite `aiq-evals`, `--exit-on-error`, and a single thread;
  - it uses a per-run `prod_env` local path, which keeps the request cache and
    credentials hermetic.
  Outputs are located by exact `RunSpec.name` under `runs/aiq-evals/`, with no
  fuzzy matching. A nonzero exit or a missing run directory yields `failed`.
  A directory abandoned before `run_spec.json` becomes an explicit incomplete
  record.
- **Import** reads run directories engine-free, following directory symlinks as
  MAGNET's materialization requires. It rejects run specs outside the resolved
  request and a mismatched `adapter_spec.model`. A missing resolved run spec
  makes the import incomplete.
- **Normalization** (`normalize.py`):
  - each stat maps to `metric=name.name`, `value=mean`, `reducer=mean`,
    `group=split[/sub_split]`, and `score=` a perturbation descriptor.
  - `denominator` stays unset, because HELM's aggregate `count` counts
    train-trial aggregates rather than samples: the 9-instance MMLU test split
    has `count=1`.
  - per-instance rows become samples with `epoch = train_trial_index + 1`,
    prompt/completion trajectories from `scenario_state`, and token usage.
  - coverage compares the distinct `(instance, trial)` pairs requested in
    `scenario_state` with those in per-instance stats. If either file is
    missing, coverage is unknown.
- Unsupported options fail explicitly:
  - request `generation` (encode it in the run entry instead);
  - auxiliary model roles;
  - `provider_options`, and any `provider` other than `helm`;
  - a model named inside the task.

## Native evidence

Environment: `/tmp/aiq-helm-p1` (CPython 3.12.3, `crfm-helm==0.5.14`,
constraints `dev/environments/phase1/helm-py312-constraints.txt`). Command:

`/tmp/aiq-helm-p1/bin/python -m pytest -q tests/native/test_helm_adapter_native.py tests/native/test_helm_native.py`

This gives 12 passed. `test_helm_adapter_native.py` covers:

- **Fresh scored run.** `simple_mcqa` with `max_eval_instances=1` resolved to
  `simple_mcqa:model=simple_model1`. It succeeded through an owned worker,
  complete 1/1, with one unperturbed `exact_match@test`, a prompt trajectory,
  and `RUN_COMPLETE`. Re-import yields identical metrics.
- **Train trials.** `num_train_trials=2` with 2 instances produced epochs {1, 2}
  and 4 processed pairs.
- **Identity.** A different `max_eval_instances` changes the resolved RunSpec
  and the digest.
- **Resolution failures.** An unknown model fails in HELM's own resolution; a
  model named inside the task is rejected.
- **Native failure.** Plugin scenario `aiq_p5_fail` raises inside HELM, which
  exits nonzero under `--exit-on-error`. The result is `failed`, with the HELM
  traceback in `execution_error`, `helm-run.stderr.log` retained, and no
  `RUN_COMPLETE`. The first attempt crashed the worker: HELM had created the
  run directory but not `run_spec.json`. That case is now an explicit
  incomplete record.
- **Cancellation.** Plugin scenario `aiq_p5_slow` spawns `sleep 120` and blocks.
  Cancelling via SIGINT-first stopped HELM in 2.8 s; the child is gone,
  `ATTEMPT_TERMINAL=cancelled`, and there is no `RUN_COMPLETE`.
- **Historical import.** `mmlu:subject=philosophy` with `openai/gpt2` resolves
  (without dataset download) to exactly
  `mmlu:subject=philosophy,method=multiple_choice_joint,model=openai_gpt2`,
  and the historical fixture imports under that name: 10/10 processed.
  - Removing `per_instance_stats.json` gives unknown coverage and no samples.
  - Removing `stats.json` gives an `incomplete` import without `RUN_COMPLETE`.
- **Scope check.** Importing another run spec's directory is rejected.

`test_helm_native.py::test_aiq_evals_imports_magnet_materialized_symlinked_run`
is the MAGNET compatibility seam: a MAGNET `reuse_only` materialization (a
symlinked run directory) imports through the aiq-evals HELM adapter.

Engine-free regression: `tests/fixtures/helm-native/expected-normalized.json`
(regenerated by `dev/regenerate_native_regressions.py helm`) is checked by
`tests/test_native_fixture_regression.py`. `tests/test_helm_adapter.py` covers
static validation without importing HELM.

## Limitations

- Fresh execution is proven only for HELM's local `simple/model1`. External
  providers, HuggingFace models, `model_deployments.yaml` in `prod_env`, and
  `--enable-*-huggingface-models` are not supported through request options yet.
- `num_threads` is fixed at 1. A caller-chosen value would be operational, and
  an option for it would need to stay out of identity; it is deferred.
- Log probabilities, resume, and rescore are untested; HELM has no tools or
  sandboxes.
