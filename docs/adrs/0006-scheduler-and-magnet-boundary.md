# ADR-0006: One-evaluation runtime below MAGNET/kwdagger orchestration

Status: Accepted

## Context

MAGNET already has campaign scheduling, requested-work accounting, cache/node
semantics, claim evaluation, and dashboard projection. Native engines may also
provide their own campaign/retry mechanisms. Letting `aiq-evals` become another
workflow scheduler would create overlapping authority and ambiguous retry/cache
semantics.

## Decision

`aiq-evals` owns execution *inside one requested evaluation*.

MAGNET/kwdagger owns orchestration *across evaluation nodes*.

The MAGNET integration layer owns:

- generic kwdagger `EvaluationNode` construction/scheduling;
- requested versus accumulated work/evidence accounting;
- claim-facing metric selection and `metrics.evaluate.*` flattening;
- evidence eligibility and coverage policy;
- one completed evaluation artifact -> one evidence-row semantics;
- `ClaimResultNamespace`, cards, dashboards, and claim verdicts;
- MAGNET endpoint leasing/resource integration where relevant.

A native suite or Inspect call may return several task/log/model/epoch records.
`aiq-evals` preserves them. It does not decide how many MAGNET claim votes they
represent. MAGNET must use an explicit selector/projection and must not silently
average unrelated native records or turn epochs into independent evidence rows.

Native within-evaluation concurrency is allowed. Campaign-level automatic retries,
cache policy, and node attempts stay with the outer orchestrator unless an
explicit future ADR changes that authority.

Preventing two callers from computing the same stored measurement is store
integrity, not scheduling: the store makes acquisition single-flight
(ADR-0011). That neither schedules nor retries anything.

## Consequences

Do not add kwdagger as an `aiq-evals` dependency. Do not nest Inspect `eval_set()`
or another engine's campaign scheduler beneath a kwdagger node merely for feature
parity.

MAGNET integration should be testable as a consumer of the public `aiq-evals`
contract rather than through internal imports.
