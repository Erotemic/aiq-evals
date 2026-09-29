# ADR-0005: Thin native adapters with explicit worker ownership

Status: Accepted; public protocol signatures remain Provisional

## Context

HELM, OLMo Eval, and Inspect differ in task representation, execution APIs,
Python/dependency constraints, failure behavior, result cardinality, and agentic
features. A shared layer must not erase those semantics or require every engine
to coexist in one Python environment.

## Decision

Each backend implements a small conceptual contract:

```text
capabilities()
resolve(request) -> ResolvedEvaluation
execute(resolved, context) -> EvaluationResult
import_results(source, context) -> EvaluationResult
```

Names/signatures may evolve until a PyPI release freezes them (ADR-0010), but
these responsibility boundaries should remain.

Adapters must:

- keep native imports lazy;
- validate actual task/provider/solver combinations, not only engine-wide flags;
- preserve native scoring and aggregation rather than silently reimplementing it;
- normalize every native result record needed for faithful downstream access;
- retain native artifacts/references;
- map native failures/cancellation conservatively;
- reject unsupported requested features explicitly.

Blocking/synchronous runtimes may execute in an owned subprocess or isolated
worker interpreter/container. Cancellation must terminate resources owned by
that execution boundary and allow native cleanup paths to run.

Core `aiq-evals` remains Python >=3.11 and importable with no engine installed.
A backend worker may require a newer Python or incompatible dependency set.

## Backend-specific constraints

- OLMo Eval: use its supported runner lifecycle, explicit validation, and preserve
  failure-gate diagnostics and trajectories.
- Inspect: use public evaluation/log-reader APIs; do not introduce `eval_set()` as
  a nested campaign scheduler; preserve multi-log, scorer, score, metric, reducer,
  epoch, event, and tool information.
- HELM: preserve existing compute/materialization/import behavior and represent
  unknown per-instance coverage honestly.

## Consequences

Capability declarations are evidence-backed and combination-specific. A candidate
upstream version is not considered supported until native fixtures demonstrate
its claimed behavior.
