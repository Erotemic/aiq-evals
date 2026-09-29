# Phase-4 implementation evidence: Inspect adapter

Status: IMPLEMENTED, EXPERIMENTAL; phase-1 native acceptance PASSED for the
tested combinations (2026-09-29).

> Update 2026-09-29: `inspect-ai==0.3.272` is verified for the combinations in
> `phase1-capabilities.md`, and every native item listed at the end of this file is
> recorded in `phase1-evidence.md`. Two exceptions remain: CI installation of the
> pin (phase 8) and Docker sandboxes (untested; the `local` sandbox is covered).
> The text below is the pre-acceptance implementation record.

This ledger separates repository implementation evidence from native-runtime
acceptance. The adapter is implemented against the public Inspect APIs documented
for candidate release `inspect-ai==0.3.272`, but the build environment used for
this archive does not have Inspect installed and therefore does not establish a
supported upstream pin.

## Candidate upstream surface

Candidate distribution: `inspect-ai==0.3.272`.

The adapter intentionally uses only these public surfaces:

- `inspect_ai.eval()` for execution;
- `inspect_ai.log.list_eval_logs()` for native log discovery;
- `inspect_ai.log.read_eval_log()` for `.eval`/JSON import;
- public `EvalLog` / `EvalResults` / `EvalScore` / `EvalMetric` / `EvalSample`
  fields through duck-typed normalization.

It does not use `eval_set()` and therefore does not introduce a second campaign
scheduler or automatic eval-set retry loop beneath aiq-evals.

## Implemented behavior

- lazy Inspect imports and candidate-version recording;
- static request validation without importing Inspect;
- native Inspect task strings plus explicit serialized
  `python:package.module:attribute` task factories;
- source hashing for local/importable task code when concrete source is available;
- primary model/provider mapping plus auxiliary model-role bindings;
- primary `model_args`, task arguments, generation options, and protected eval
  option ownership;
- public `eval()` execution in an owned worker process;
- `.eval` or JSON log format selection;
- collection and normalization of every returned log;
- aggregate identity preserving scorer, score name, metric name/group, and reducer;
- total/completed/logged sample coverage accounting;
- per-sample ID + epoch identity;
- structured sample scores;
- message/event/timeline trajectories, including native tool events;
- model and role usage records;
- per-sample epoch reductions as explicit normalized reduction records;
- conservative `success` / `error` / `cancelled` / nonterminal mapping;
- native diagnostics recovery if `eval()` raises after logs were written;
- native `.eval`/JSON import through public Inspect log readers;
- model and passed-task-argument validation on import;
- single-file native import preservation in the published bundle;
- no Inspect dependency required for normalized result reading.

The still-provisional `MetricRecord` gained optional `score` and `group` fields
because Inspect can emit multiple score values from one scorer and grouped metric
values. These fields are omitted from serialization when absent so the phase-2
frozen fixture retains its existing normalized artifact identity.

## Worker ownership

Inspect exposes a synchronous public evaluation entry point at the candidate API
surface. `InspectAIBackend.capabilities()` therefore declares
`requires_worker_process=True`. The shared runner automatically executes the
adapter in an owned subprocess even when the caller did not explicitly supply a
worker interpreter.

Repository tests exercise this path with an independently importable fake Inspect
package. This establishes aiq-evals worker protocol behavior, environment
propagation, native artifact collection, and engine-free publication. It does not
establish real Inspect sandbox/process cleanup.

## Repository validation

The deterministic repository suite covers:

1. request and protected-option validation;
2. primary/auxiliary model-role mapping;
3. importable factory source hashing;
4. multi-log normalization;
5. scorer/score/metric/group/reducer preservation;
6. per-epoch samples and epoch reductions;
7. tool-event trajectory preservation;
8. native error/cancelled/nonterminal status mapping;
9. recovery of diagnostic logs after an execution exception;
10. native directory/file import and model mismatch rejection;
11. owned-worker execution through the real aiq-evals subprocess protocol;
12. backward compatibility of the frozen phase-2 schema fixture.

## Native acceptance still required

Do not mark the Inspect adapter supported until a pinned real environment records:

- deterministic scored local generation;
- at least one actual multi-turn solver/agent task with a real tool invocation;
- model-role use by a scorer/judge or task;
- multi-log or multi-task execution;
- multiple scorers / score values and multi-epoch reducers;
- `.eval` and JSON native import;
- sample-error, eval-error, cancelled, and nonterminal behavior;
- cancellation of a live native worker plus sandbox/process cleanup;
- an opt-in sandbox fixture;
- clean installation of the candidate pin in CI;
- a decision to promote `0.3.272` (or a later tested version) from candidate to
  supported.

These were P1-04/P1-06/P1-07 evidence items; see `phase1-evidence.md` for their records.
