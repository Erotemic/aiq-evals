# ADR-0008: Retain the independent normalized result schema for Phase 1

Status: Accepted; resolves the payload choice deferred by ADR-0007

## Context

We tested current Every Eval Ever (EEE) at revision
`1eb9d39aed34505e15db637153de72318bd946d4` (schema 0.3.0)
against native HELM, Inspect, and OLMo Eval fixtures. The exact fixture checksums,
commands, and failed conversions are in `docs/planning/phase1-evidence.md`.

| Information | EEE 0.3.0 finding |
| --- | --- |
| HELM aggregate metrics and per-instance results | Represented through EEE's HELM converter; the historical MMLU fixture yielded 1 aggregate log, 48 evaluation results, and 80 instance rows for 10 sample IDs. A fresh scored MCQA fixture yielded 1 log and 24 results. A fresh generic-generation fixture failed conversion because its metrics are not recognized as benchmark scores. |
| Inspect scored generation and tool traces | EEE's Inspect converter rejected both `.eval` and JSON fixtures because `fixture/local` is outside its closed model-developer mapping. The schema has tool calls, but typed argument values become strings. |
| OLMo Eval scored generation and tool trajectory | No OLMo converter is present. Import would require a new adapter and mapping. |
| Epoch, reducer, scorer identity, multiple result records | No unambiguous first-class representation for all of these in the inspected schema. These need more than a small field extension and converter changes. |
| Unknown correctness and partial coverage | `instance_level_eval` requires a Boolean `is_correct`; unknown cannot be represented losslessly. Execution status, expected/processed/saved/failed counts and native artifact lineage belong outside the EEE scientific payload. |
| Arbitrary metadata and typed tool arguments | String-only metadata and tool argument values are lossy for these fixtures. |

The HELM conversion required a supplied `file_uuid`; an initial conversion without
it failed. EEE's converter support therefore varies by engine and calling
context. A successful HELM conversion alone does not establish a lossless common
scientific payload.

## Decision

Keep `aiq-evals`' independent `EvaluationResult`, result, metric, and sample
structures as the Phase 1 normalized contract. Retain original native files and
explicit status, coverage, and lineage alongside them. Readers must remain usable
without any evaluation engine installed. EEE interoperability may be added later
as a converter, after its model mapping and scientific-field gaps are addressed;
it is not a core dependency.

This decision does not freeze the schema API before the later planned contract
review. It only resolves the Phase 1 EEE choice from tested evidence.
