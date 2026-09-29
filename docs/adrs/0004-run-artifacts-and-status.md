# ADR-0004: Preserve native truth and separate execution facts from evidence policy

Status: Accepted

## Context

Evaluation engines can write useful metrics or logs before failing. Aggregate
statistics can exist without complete sample coverage. A run may complete
successfully while still being unsuitable for a particular scientific claim.
Conflating those cases creates false successes and makes later auditing harder.

## Decision

An `aiq-magnet-evals` run bundle records execution facts, native artifacts, normalized
views, lineage, and integrity metadata. Its target shape is approximately:

```text
resolved_request.json
run_manifest.json
attempt.json
native/
normalized/
RUN_COMPLETE          # terminal successful publication marker, if used
```

Exact filenames remain a versioned implementation detail until a PyPI release
freezes them (ADR-0010), but the semantic separation is mandatory.

Track at least these concepts independently:

- execution status: succeeded / failed / cancelled / incomplete;
- coverage: complete / partial / unknown plus available counts;
- normalized scientific outputs;
- native artifact inventory/checksums;
- attempt/retry lineage.

Native source artifacts are retained whenever practical and remain the strongest
record of native-engine behavior. Missing provenance, usage, coverage, traces,
or denominators are represented as unknown rather than zero or fabricated.

A native metrics/log file existing is never sufficient proof of success. Failed
or cancelled attempts may retain diagnostics without receiving the successful
terminal marker.

MAGNET evidence eligibility is not stored as an `aiq-magnet-evals` execution truth.
MAGNET may wrap a completed run with a stronger evidence artifact and its own
`DONE` semantics.

## Consequences

Importing a changed native artifact changes normalized-artifact identity. Readers
validate schema and integrity without requiring the native engine package.

Retries remain attempts in lineage; they do not silently become extra scientific
samples.
