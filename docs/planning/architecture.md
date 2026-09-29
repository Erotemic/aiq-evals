# Architecture boundary

> Reviewer note: this document is explanatory planning material. The normative architecture decisions and reviewer invariants live in `../adrs/README.md` and the ADRs it indexes.

## Core idea

`aiq-magnet-evals` reproducibly obtains evaluation results across heterogeneous native
evaluation engines. A requested evaluation may be satisfied by a valid existing
computation/import or by executing the native engine.

The package is closer to a content-addressed build/runtime system for
evaluations than to a leaderboard database.

```text
EvaluationRequest
      |
      v
resolve native task/model/configuration
      |
      v
MeasurementIdentity
      |
      +---- compatible result available? ----+
      |                                      |
     yes                                     no
      |                                      |
      v                                      v
load/import                           native execution
      |                                      |
      +------------------+-------------------+
                         |
                         v
                 EvaluationRun bundle
```

The long-term high-level convenience API may be called `ensure`, but phase 1
must not freeze that name or its contract.

## Three identities

The original MAGNET-oriented plan mixed several identities that should remain
separate.

### Measurement identity

Owned by `aiq-magnet-evals`. It covers facts that can change what the evaluation
actually computes:

- engine and upstream version/revision;
- adapter version;
- resolved task/suite membership and task code/config content;
- dataset/sample revision and selection;
- primary and auxiliary model/provider bindings;
- generation settings;
- seed/shuffle settings;
- epochs/repetitions when they cause native execution;
- native scorers actually executed;
- solver/scaffold/tool configuration and versions;
- sandbox image/content identity when relevant to execution;
- endpoint revision/cache token when a mutable alias would otherwise be used.

If an input cannot be resolved strongly enough to justify reuse, reuse is
disabled rather than hashing a mutable path and pretending it is immutable.

### Normalized artifact identity

Owned by `aiq-magnet-evals`. It adds the native artifact digest, normalizer/converter
version, and normalized schema version to the measurement lineage.

A changed native log or changed converter produces a new normalized artifact.

### Evidence-view identity

Owned by MAGNET, not `aiq-magnet-evals`. It adds interpretation needed for a scientific
claim:

- selected task/model/scorer/metric/reducer;
- coverage requirement;
- partial/unknown-coverage policy;
- claim-facing projection.

Changing the selected metric from an already-computed evaluation must not force
model execution. Changing a MAGNET evidence policy must not force model
execution. Asking the native engine to execute an additional scorer may.

## Execution status versus evidence eligibility

`aiq-magnet-evals` reports facts such as:

```text
execution_status = succeeded
coverage = partial
processed = 997
expected = 1000
metric accuracy = 0.713
```

It must not decide whether those facts are sufficient evidence for a MAGNET
claim.

A reusable run can therefore be terminal and valid even when MAGNET later
rejects it under a strict evidence policy.

## Artifact direction

The target reusable run bundle is approximately:

```text
resolved_request.json
run_manifest.json
attempt.json
native/
normalized/
RUN_COMPLETE          # optional terminal publication marker
```

The exact phase-2 schema is deliberately not frozen in phase 1.

MAGNET may wrap a completed run with its own evidence artifact and stronger
`DONE` semantics.

## Result schema strategy

Do not invent a second ecosystem-wide scientific schema before checking whether
Every Eval Ever can represent the required HELM, OLMo Eval, and Inspect
information without scientific loss.

Phase 1/2 must evaluate EEE for:

- aggregate metrics with scorer and reducer identity;
- instance/sample identity;
- repeated epochs/trials;
- multi-turn messages;
- agent/tool trajectories;
- usage data;
- multiple task/model result records;
- unknown/missing coverage or provenance;
- stable native artifact references.

If EEE is sufficient, use it as the normalized scientific payload and keep
operational run metadata in `aiq-magnet-evals`. If it is not sufficient, document the
gaps before creating an `aiq-magnet-evals` schema. Native source artifacts remain the
source of truth either way.

## Dependency boundary

Core `aiq-magnet-evals`:

- Python >=3.11;
- imports with no native engine installed;
- does not depend on MAGNET or kwdagger;
- uses lazy engine imports;
- can delegate execution to isolated worker interpreters/containers.

An engine worker may have stronger Python/dependency constraints than core.
OLMo Eval is expected to require this isolation at some supported revisions.

## Scheduler boundary

`aiq-magnet-evals` owns execution *inside one evaluation*.

MAGNET/kwdagger owns scheduling *across evaluations/nodes*.

Do not add an internal campaign scheduler merely because Inspect or another
engine has one. Native within-task concurrency is allowed; campaign retries,
cache policy, and node attempts remain external orchestration concerns.
