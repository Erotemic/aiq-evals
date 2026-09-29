# ADR-0002: Resolve, reuse/import, or execute

Status: Accepted

## Context

A useful evaluation abstraction must do more than index already-computed scores.
Callers need one operation that can satisfy a fully specified evaluation from a
valid existing result when possible and execute the native engine when needed.

## Decision

The conceptual central operation is:

```text
request
  -> statically validate
  -> resolve native meaning
  -> compute reusable measurement identity, or record why identity is unresolved
  -> discover and validate a compatible terminal result
  -> reuse/import that result when valid
  -> otherwise execute the native engine
  -> normalize and publish the run atomically
  -> return an engine-independent EvaluationRun
```

The eventual convenience API may be named `ensure`, but the architecture does
not depend on that spelling.

Static validation must be side-effect free. It must not import arbitrary task
factories, start models, invoke tools, download datasets, or publish results.
Resolution that is required for reusable identity happens separately, in an
appropriate native worker when necessary.

If a mutable input cannot be resolved strongly enough to justify reuse, the
system must disable reuse instead of manufacturing a stable-looking identity.

## Consequences

`aiq-magnet-evals` is closer to a content-addressed build/runtime system for evaluations
than to a leaderboard database. Search/indexing of accumulated runs may be useful,
but it is secondary to reproducibly obtaining a requested evaluation.

A cache hit is accepted only after its manifest/artifacts validate against the
resolved measurement identity and terminal state.
