# Architecture decision records

This directory is the reviewer-facing architecture contract for `aiq-evals`.

The planning documents under `docs/planning/` describe implementation sequence,
current status, evidence, and open gates. They may change as work progresses.
The ADRs here describe the intended architecture and the constraints that should
remain true across those phases.

A reviewer should use the ADRs first when deciding whether an implementation is
architecturally correct. A roadmap checkbox or existing implementation does not
override an accepted ADR.

## Review target

The package should provide a reusable way to obtain a native evaluation result:

```text
EvaluationRequest
      |
      v
resolve native meaning and measurement identity
      |
      +---- compatible terminal result exists? ----+
      |                                            |
     yes                                           no
      |                                            |
      v                                            v
validate and reuse                          execute native engine
      |                                            |
      +----------------------+---------------------+
                             |
                             v
                    EvaluationRun bundle
```

The result is a record of what the evaluation engine did. `aiq-evals` does not
turn that record into a MAGNET claim or verdict.

## Accepted decisions

- [ADR-0001](0001-package-boundary.md): `aiq-evals` is an independent evaluation runtime and artifact layer.
- [ADR-0002](0002-resolve-reuse-execute.md): the central operation is resolve -> reuse/import or execute -> publish.
- [ADR-0003](0003-identity-model.md): measurement, normalized-artifact, and MAGNET evidence identities are distinct.
- [ADR-0004](0004-run-artifacts-and-status.md): execution status, coverage, and evidence eligibility are distinct; native artifacts are retained.
- [ADR-0005](0005-backend-contract-and-workers.md): adapters preserve native semantics behind a small contract and may run in isolated workers.
- [ADR-0006](0006-scheduler-and-magnet-boundary.md): `aiq-evals` owns one evaluation; MAGNET/kwdagger owns campaign scheduling and claim projection.
- [ADR-0007](0007-normalized-schema-strategy.md): retain native truth and decide EEE from fixture evidence.
- [ADR-0008](0008-normalized-schema-fixture-decision.md): fixture gaps require the independent normalized result schema for Phase 1.
- [ADR-0009](0009-phase6-api-schema-freeze.md): the first public API/schema is frozen after all three engines pass the shared conformance suite.

## Reviewer invariants

A change is architecturally suspect if it does any of the following without an
explicit replacement ADR:

1. adds a core dependency on MAGNET or kwdagger;
2. makes selecting a MAGNET claim metric alter the native measurement identity;
3. treats a failed, cancelled, or incomplete native attempt as a successful run
   because a metrics/log file exists;
4. treats MAGNET evidence eligibility as an `aiq-evals` execution fact;
5. imports heavy native engine packages merely to read normalized run metadata;
6. hashes secrets into identities or persists secret values in run metadata;
7. hashes unresolved mutable aliases/paths and then reuses them as if immutable;
8. hides native artifacts or fabricates missing provenance/coverage;
9. adds a second campaign scheduler or nested retry policy beneath kwdagger;
10. claims backend capability without a corresponding native acceptance fixture.

## Decision status vocabulary

- **Accepted**: part of the target architecture. Change through a superseding ADR.
- **Provisional**: the direction is intentional but the public API/schema may still change before the phase-6 freeze.
- **Deferred**: intentionally unresolved until named evidence exists.
- **Superseded**: retained for history; a newer ADR is authoritative.

The phase-6 freeze is recorded in ADR-0009: the `aiq_evals` exports and the
v1 request/result/manifest schemas are now stable. Adapter internals are not
public API.
