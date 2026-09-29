# aiq-evals agent guide

## Purpose

`aiq-evals` reproducibly obtains evaluation results across heterogeneous native
evaluation engines. It may reuse/import a valid result or execute the native
engine when computation is required.

## Architectural boundary

This repository owns evaluation facts and execution mechanics. It does **not**
own MAGNET claim semantics.

Keep these here:

- native engine adapters and capability validation;
- request resolution and measurement identity;
- isolated worker/runtime handling;
- execution, cancellation, and native artifact import;
- engine-independent result/run/sample/metric access;
- artifact lineage, coverage facts, and execution status;
- reusable result discovery/storage.

Keep these in `aiq-magnet`:

- kwdagger `EvaluationNode` scheduling and requested-work accounting;
- `metrics.evaluate.*` flattening;
- metric selection for a MAGNET claim;
- evidence eligibility policy and claim verdicts;
- `ClaimResultNamespace`, cards, and dashboard bundles;
- one-artifact/one-evidence-row semantics.

Do not add `kwdagger` or `aiq-magnet` as a core dependency.

## Native-evidence rule

Phases 2 and 3 now contain source-grounded implementations, but that does not
close the native phase-1 acceptance gates. Do not claim an upstream capability
from documentation, fake-native tests, or old code alone. A checkbox that
concerns real runtime behavior requires a native fixture and a record in
`docs/planning/phase1-evidence.md`.

Exact upstream compatibility pins are evidence-backed decisions. Candidate pins
are not supported pins. The OLMo adapter remains experimental until its native
generation, tool, failure, cancellation, and packaging gates are recorded.

## Dependency rule

Core must remain Python >=3.11 and import without any evaluation engine
installed. Heavy/conflicting engines may run in isolated, pinned worker
checkouts/environments.

## Style

- Never use `import *`.
- Prefer explicit small dataclasses/protocols over framework-heavy abstractions.
- Keep engine imports lazy.
- Preserve native artifacts instead of fabricating missing provenance.
