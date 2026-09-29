# Phase-1 evidence ledger

This is the canonical record for phase-1 validation. A checkbox is not complete
until its evidence is recorded here. Documentation or a historical integration
may motivate a test but does not replace it.

## Record template

For each runtime item record:

```text
ID:
Date:
Implementer/reviewer:
aiq-evals revision:
Upstream engine/revision:
Python/runtime identity:
Dependency lock or container digest:
Command/test ID:
Output artifact path/checksum:
Outcome:
Failure classification (if any):
Notes/limitations:
```

Do not record credentials. Preserve failed/retried attempts rather than replacing
them with only the eventual green attempt.

## Repository bootstrap evidence

### P1-01 - evidence ledger

Status: COMPLETE for repository scaffolding.

Evidence:

- this file defines the canonical record and required fields;
- `aiq_evals.phase1.PHASE1_TASKS` exposes the checklist programmatically;
- `aiq-evals phase1-status` reports the repository snapshot.

No native engine behavior is implied by this completion.

### P1-02 - pins and worker instructions

Status: PARTIAL.

Implemented evidence tooling:

- `aiq-evals phase1-probe` captures Python/host and installed-engine facts;
- repeated `--checkout ENGINE=PATH` captures exact git HEAD, tracked cleanliness,
  origin URL, `requires-python`, and `uv.lock` presence;
- `aiq_evals.probes.isolated.build_locked_uv_command` constructs locked upstream
  `uv run` commands without adding engine dependencies to core;
- `validate_git_revision` rejects mutable branch/tag names when an immutable
  source revision is required.

Candidate/history facts currently known from supplied source material:

- original OLMo Eval plan inspection:
  `73ade80e24f796af55caeb8fd7b75a7f3fd607fd`;
- supplied `eval_audit` OLMo prototype revision:
  `c84828e4af096004c561b668b68e0b126c7f60e9`;
- existing MAGNET dependency declaration: `crfm-helm>=0.5.8`.

None of these is yet the `aiq-evals` supported pin. Selection requires the native
fixture suite below.

## Runtime items

### P1-03 - OLMo Eval generation + tool execution

Status: OPEN.

Required artifacts:

- scored generation fixture;
- tool-calling multi-turn fixture;
- request/prediction/trajectory artifacts;
- failure-after-diagnostics fixture;
- worker registration and cleanup evidence.

### P1-04 - Inspect generation + tool execution

Status: OPEN.

Required artifacts:

- scored generation fixture;
- solver/agent tool fixture;
- multi-log/sample-error/epoch/reducer fixtures;
- cancellation/nonterminal fixture;
- worker import/cleanup evidence.

### P1-05 - HELM compute/reuse/import

Status: OPEN.

Required artifacts:

- fresh computation;
- cached reuse/materialization;
- native run import;
- aggregate/per-instance records;
- unknown/incomplete coverage fixture.

### P1-06 - async/worker/cleanup

Status: OPEN.

Must be demonstrated with selected native pins.

### P1-07 - capability matrix

Status: PARTIAL.

The matrix categories are defined in `aiq-evals-plan.md`; no runtime capability
is yet marked supported in this new repository.

### P1-08 - EEE normalization decision

Status: OPEN.

The supplied `eval_audit` source demonstrates that EEE was already considered a
normalization substrate, but its `every_eval_ever` submodule contents were not
present in the supplied archive. This repository therefore does not infer the
current EEE schema from that snapshot. Inspect the real current EEE source and
run fixture conversions before deciding.

### P1-09 - OLMo Eval packaging go/no-go

Status: OPEN.

Default hypothesis: prefer an isolated locked upstream worker if co-installation
is not cleanly reproducible. This is not yet a decision.

### P1-10 - acceptance gate

Status: BLOCKED by P1-02 through P1-09 runtime evidence and the separate MAGNET
cardinality experiment.

## Local build-environment observation

At archive creation time the current build interpreter did not have `helm`,
`olmo_eval`, `inspect_ai`, `kwdagger`, or `magnet` installed. Consequently no
native runtime success is claimed by this archive. The dependency-free core test
suite is the only executed validation recorded by the archive builder.

### API-surface probe support

`aiq-evals phase1-probe` also checks the intended public OLMo Eval and Inspect
adapter seams when those packages are installed. These symbol checks are only a
compatibility precondition; a symbol existing is not evidence that execution,
status mapping, or cleanup semantics work.
