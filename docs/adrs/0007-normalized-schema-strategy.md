# ADR-0007: Defer ecosystem normalized-schema choice until fixture evidence

Status: Accepted decision to defer; payload choice itself is Deferred

## Context

A cross-engine result layer needs aggregate metrics, samples, repetitions/epochs,
multi-turn content, tool trajectories, usage, coverage/provenance, and multiple
native result records. Every Eval Ever (EEE) already targets evaluation
normalization, but the required HELM, OLMo Eval, and Inspect fixtures have not yet
been used to prove whether EEE is lossless enough for this project.

Creating another ecosystem-wide schema prematurely would duplicate work and make
later interoperability harder.

## Decision

Before freezing the public normalized scientific payload, run the planned EEE gap
analysis against real HELM, OLMo Eval, and Inspect fixtures.

Regardless of that outcome:

- native artifacts remain retained source material;
- operational run metadata/identity/attempt state remains an `aiq-magnet-evals` concern;
- engine-free readers remain required;
- missing information is represented explicitly rather than synthesized.

If EEE represents the required scientific information without unacceptable loss,
prefer it (possibly with a small upstream extension) for the normalized scientific
payload. If not, document concrete fixture-backed gaps before adopting a distinct
`aiq-magnet-evals` payload schema.

The current `EvaluationResult`/`MetricRecord`/sample structures are therefore a
provisional internal contract, not proof that a permanent ecosystem schema has
been selected.

## Consequences

Reviewers should not reject provisional result-structure changes merely because
they change the unreleased schema (ADR-0010). They should reject changes that erase native
information, make migration impossible, or prematurely declare the normalization
question settled without fixture evidence.
