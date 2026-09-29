# Phase 1 handoff — 2026-09-29

The user asked to stop after a handoff. Resume **Phase 1 only**; do not begin
Phases 2–5 or add a MAGNET integration to force the cardinality spike through.
Read `AGENTS.md`, the accepted ADRs indexed by `docs/adrs/README.md`,
`docs/planning/aiq-evals-plan.md`, and `docs/planning/phase1-evidence.md`
before changing architecture. Commit each logical change with
`Co-authored-by: GPT-6-Sol (OpenAI)` only if that is the actual producing model;
use the next agent's exact self-identification for its own commits.

## Current state

Phase 1 is **not closed**. The strongest evidence is recorded in
`phase1-evidence.md`, the combination-level claims in
`phase1-capabilities.md`, and the EEE decision in ADR-0008. That ledger has
historical OPEN labels from the bootstrap snapshot; its dated later records
supersede them. The plan checkboxes have been updated only for demonstrated
items. All new native files and adapter fixes have been committed. The handoff
commit should leave the working tree clean.

Tested environments:

- Inspect `inspect-ai==0.3.272`, CPython 3.11.15, `/tmp/aiq-inspect-p1`.
- OLMo Eval checkout `73ade80e24f796af55caeb8fd7b75a7f3fd607fd`, CPython
  3.12.3, `/tmp/olmo-eval-p1/.venv`, upstream frozen `uv.lock`.
- HELM `crfm-helm==0.5.14` through MAGNET checkout
  `7bb105ab1c85bfaa01bf68c97ff7523332479ee4`, CPython 3.12.3,
  `/tmp/aiq-helm-p1`. Prepend `/tmp/aiq-helm-p1/bin` to `PATH` for fresh
  MAGNET compute so the wrapper invokes the correct `helm-run`.
- Clean core CPython 3.11.15, `/tmp/aiq-core-p1`, contains no evaluation
  engines. It imported `aiq_evals`, parsed a request, and read saved Inspect
  and OLMo success/failure bundles.

Exact environment build commands, fixture SHA256s, failures, and limitations are
in `phase1-evidence.md`. OLMo delivery is isolated-worker-only; no heavy core
dependency was added. ADR-0008 retains the independent normalized result schema:
EEE converts the fresh scored HELM MCQA fixture but rejects generic HELM
metrics, rejects local Inspect model paths, and lacks an OLMo converter.

Most recent validation, after the multi-task and fresh HELM fixtures:

```sh
python -m pytest -q                       # 48 passed, 3 native skips
python -m compileall -q aiq_evals tests    # passed
ruff check .                              # passed
PYTHONPATH=/home/joncrall/code/aiq-evals /tmp/olmo-eval-p1/.venv/bin/python -m pytest -q tests/native/test_olmo_native.py --basetemp=/tmp/aiq-olmo-final2  # 5 passed
/tmp/aiq-inspect-p1/bin/python -m pytest -q tests/native/test_inspect_native.py --basetemp=/tmp/aiq-inspect-final  # 7 passed
/tmp/aiq-helm-p1/bin/python -m pytest -q tests/native/test_helm_native.py --basetemp=/tmp/aiq-helm-final  # 3 passed, 4 MAGNET deprecation warnings
```

No static type checker is configured in `pyproject.toml`. The repo's
`llm_resource_tally` post-commit hook is already installed. `python3
.llm_resource_tally/tool doctor` confirmed it is armed, the Codex backend is
registered, and the ledger reads cleanly. Publish before the next substantial
handoff, per `AGENTS.md`.

## What changed

- Inspect adapter now handles absolute local task file paths in Python 3.11,
  imports declared registration modules, retains valid relative artifact
  locations, and classifies a logged sample error as partial coverage even
  when Inspect labels the overall log `success`.
- OLMo adapter bootstraps registered task/tool modules into inference workers
  and retains redacted worker diagnostics. A native OpenAI Agents scaffold
  called the local `double` tool over a scripted local HTTP model endpoint.
  A native hard failure wrote metrics but was not published as success.
- Both Inspect and OLMo owned process trees were cancelled with child PID
  observation. Inspect has native multi-log, auxiliary-role, epoch/reducer, and
  sample-error fixtures. OLMo now has a native two-task suite fixture.
- MAGNET reuse/import of a historical HELM directory, a derived incomplete
  copy, and fresh HELM `simple1` plus scored `simple_mcqa` runs were tested.
  The scored local MCQA run made one native request and produced `exact_match`
  with count 1 and value 0.0. The generic `simple1` run produced 30 requests
  over three train trials. Its `--max-eval-instances 1` argument did not reduce
  the observed ten test IDs; see the ledger.
- `ruff check .` was brought to green by import-only cleanup.

## Remaining Phase 1 work

1. **MAGNET cardinality is the acceptance blocker.** The real Inspect
   `tests/fixtures/inspect-native/multi/` and OLMo
   `tests/fixtures/olmo-native/multi/` inputs now exist. Current MAGNET
   `KWDaggerProcessor.load_available_result_rows` calls kwdagger
   `build_tables` over already materialized DAG rows; `ClaimResultNamespace`
   takes one flattened row. MAGNET has no projection from an `aiq-evals`
   multi-result bundle to one evidence row. The experiment therefore cannot
   verify one claim vote without a future MAGNET projection. Keep this as a
   blocker rather than implementing Phase 5 or manufacturing a green test.
2. Inspect top-level native error/cancelled log import and partial coverage
   after a run-level error are untested. A sample-error log and cancellation
   of the owned process tree are tested; these are distinct gates.
3. Engine-owned sandbox/resource cleanup is untested. The tests prove owned
   child-process cleanup only; do not generalize it to remote or sandbox
   resources. Log probabilities and native resume/rescore are also untested
   across the relevant combinations, as the matrix states.
4. Reproducibility is strongest for OLMo's frozen upstream lock. Inspect and
   HELM have exact engine pins, but the temporary pip environments are not
   byte-for-byte locked. If a stronger environment artifact is needed,
   capture a constraints/lock file without introducing engines into core.
5. Update the ledger/matrix if any new native gates are demonstrated. Do not
   check off P1-10 until its explicit acceptance conditions, including the
   MAGNET cardinality gate, actually pass.

The latest implementation commits are `b1f64cf` (Inspect multi-log and coverage),
`b2e008e` (Ruff cleanup), `3a74691` (ADR and evidence), `05a665f` (fresh HELM
generic), `5ed0483` (OLMo multi-task), and `ad6b69a` (fresh scored HELM).
Earlier commits `07d361f`, `225a40a`, `9a06d1a`, `e895107`, and `9579d33`
contain the first native probes, cancellation, historical HELM import, and
OLMo agent/failure evidence. All have model attribution trailers.

## Update — 2026-09-29, later session (Claude Opus 5.5)

- Item 2 closed: Inspect native run-level `error`, native SIGINT `cancelled`,
  and SIGKILL `started` logs are captured and import as non-success. Coverage
  for these `results=None` logs is now derived from native samples (`10d1c9b`).
  P1-04 is checked.
- Item 4 closed as far as pip allows: exact-version constraints for the Inspect
  and HELM worker environments are in `dev/environments/phase1/`. Each file
  rebuilds an environment whose freeze is identical, and the native suites
  pass in those rebuilt environments. They are not hash locks.
- Still open: item 1 (MAGNET cardinality projection, the P1-10 blocker) and item
  3 (engine-owned sandbox cleanup, log probabilities, resume/rescore). Also
  open: P1-06's sync/async entry-point and no-nested-`asyncio.run` checks, and
  P1-08 Inspect/OLMo EEE mapping, which is blocked upstream.
- Current validation: base 49 passed/3 skipped; Inspect native 10; OLMo native
  5; HELM native 3. See the ledger's "follow-up 2" section.
