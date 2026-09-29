# Phase-6 evidence: reuse/ensure semantics and conformance

Status: IMPLEMENTED; all three engines pass the shared native conformance suite.
The API/schema freeze first recorded here (ADR-0009) is superseded by ADR-0010:
nothing is frozen before a PyPI release. Date 2026-09-29.
Evidence producer: Claude Opus 5.5 (Anthropic, `claude-opus-5-5`, 1M context).

## Implementation

- `magnet_evals.ensure.ensure_evaluation[_async]` follows ADR-0002. It resolves
  (inside `worker_python` when one is given, through the new worker `resolve`
  command, which carries typed errors back), then checks reuse against the
  store. Without a valid canonical run it imports `import_source` or executes
  into a fresh attempt, and promotes a successful, reusable attempt
  atomically. It returns an `EnsureOutcome` with the action (`reused`,
  `executed`, or `imported`), the run, the attempt, and the reuse reason. It
  never retries or schedules (ADR-0006).
- `ResultStore` keeps canonical runs in `runs/`, every terminal attempt in
  `attempts/<digest>/<utc-µs>-<rand>/`, and non-reusable attempts in
  `attempts/_unkeyed/`. A canonical run that fails validation is moved to
  `quarantine/`, never deleted.
  - `check_reuse` accepts a canonical run only when checksums and identities
    validate, `RUN_COMPLETE` is present, status is `succeeded`, and the manifest
    is marked `reusable`.
  - Concurrent publications converge on one canonical run.
- CLI `aiq-evals ensure REQUEST --store DIR [--worker-python] [--import-source]`;
  `aiq-evals resolve` also takes `--worker-python`.

## Requirement to evidence

| Plan requirement | Evidence |
| --- | --- |
| engine/version/config/code changes invalidate reuse | identity v2 hashes RunSpec/native config, engine version and observed revision, `adapter_source_sha256`, and task/plugin digests (`test_contracts_identity.py`, `test_engine_revision.py`); `test_measurement_change_invalidates_reuse`; conformance `changed` request executes anew for every engine |
| changed native imported artifacts get new identities | `test_import_then_reuse_and_changed_artifact_identity`: same measurement, different `normalized_artifact_identity` |
| secrets never enter identities or manifests | `test_operational_context_does_not_change_identity` (env values change, reuse holds, no value in any JSON); result redaction (`test_runner_terminal.py`) |
| mutable aliases need explicit tokens | `test_non_reusable_identity_always_executes` (always executes, stored under `_unkeyed`); unverifiable revisions/unhashable modules become non-reusable |
| retries/attempt lineage do not inflate sample identity | `test_failures_never_become_canonical_and_do_not_block_success`: three attempts stay separate and the canonical run holds one attempt's samples |
| stale success markers cannot hide failed/incomplete attempts | failed attempts never get `RUN_COMPLETE` or the canonical slot; `test_stale_or_tampered_canonical_is_rejected` (tampered canonical rejected, quarantined, re-executed) |
| no engine dependency to read results | conformance reads each engine's canonical bundle with every engine import blocked; the engine-free CPython 3.11 suite |
| all three engines pass the same conformance suite | below |

## Native conformance

`tests/native/test_conformance.py`: the same four checks per engine profile.

| Environment | Command | Result |
| --- | --- | --- |
| Inspect 0.3.272, CPython 3.11.15 | `/tmp/aiq-inspect-p1/bin/python -m pytest -q tests/native/test_conformance.py` | 4 passed (8 other-engine skips) |
| OLMo 73ade80, CPython 3.12.3 | `PYTHONPATH=$PWD /tmp/olmo-eval-p1/.venv/bin/python -m pytest -q tests/native/test_conformance.py` | 4 passed |
| HELM 0.5.14, CPython 3.12.3 | `/tmp/aiq-helm-p1/bin/python -m pytest -q tests/native/test_conformance.py` | 4 passed |

The four checks:

1. Resolution is deterministic; in-process and worker resolution give
   identical identities; the identity is reusable; the changed request
   differs.
2. `ensure` executes, then reuses the same canonical path, then executes the
   changed request. Importing the canonical native artifacts into a fresh
   store reproduces identical metrics. The canonical bundle loads with
   `inspect_ai`/`olmo_eval`/`helm` imports blocked.
3. A native failure (Inspect run-level error; OLMo hard-failure gate against a
   local 500 server; HELM plugin scenario error) is `failed`, not complete, and
   has no canonical run; its single attempt is recorded.
4. Cancelling a slow native task leaves one `cancelled` attempt and no
   canonical run, and the owned child is gone.

The first HELM run failed inside the test's own metric-sorting helper
(`None` vs `str`), not in the adapter; the helper now sorts with a total key.

## Not covered (at the time of this record)

No cross-process lock prevented two callers from executing the same measurement
at once; this record deferred it to the scheduler. That was wrong: kwdagger
cannot see that differently selected nodes share a measurement. It is fixed by
ADR-0011 (single-flight acquisition); see `integration-evidence.md`.

The "changed native imported artifacts get new identities" row above was
tested only across two stores. In one store, a changed import was silently
ignored. ADR-0011 keys imports by native content; see `integration-evidence.md`.
