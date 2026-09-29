# Phase 1 native capability matrix

Evidence is limited to the pins, local providers, tasks, and fixtures in
`phase1-evidence.md`. **S** = demonstrated supported combination, **U** =
explicitly unsupported, **T** = untested, **P** = task/provider-specific support.
No general upstream capability follows from a local fixture.

| Capability | HELM 0.5.14 through MAGNET (local simple model) | OLMo 73ade80 (mock or local LiteLLM/Agents) | Inspect 0.3.272 (local fixture provider) |
| --- | --- | --- | --- |
| Scored generation | S (fresh simple MCQA exact-match) | S | S |
| Log probabilities | T | T | T |
| Multiple scorers/metrics | P (81 fresh MCQA statistics; multiple score names) | T | S (match, includes) |
| Agent and tool execution | T | P (OpenAI Agents scaffold, `double`) | P (`use_tools`, `double`) |
| Trajectories | P (fresh scenario state and per-instance statistics) | S (assistant/tool/assistant turns) | S (messages/events) |
| Sandboxing | T | T | P (`local` sandbox: tool exec inside it; directory removed on completion and on aiq-evals cancellation) |
| Epochs/repetitions | T | T | S (two epochs, mean/mode reducers) |
| Native import | S (MAGNET reuse of HELM directory) | S | S (`.eval`, JSON, directory) |
| Resume | T | T | T |
| Rescore | T | T | T |
| Failure and partial coverage | P (incomplete imported copy) | S (hard failure after metrics) | S (sample error; run-level `error`; native SIGINT `cancelled` and SIGKILL `started` logs import as non-success with partial coverage) |
| Cancellation and owned process cleanup | T | S (owned child; fixture blocks its loop, so cleanup comes via SIGTERM escalation) | S (owned child; SIGINT-first cancellation yields Inspect's own `cancelled` log) |

HELM fresh generation is demonstrated only with its local simple model. Engine-owned
sandbox cleanup is demonstrated only for Inspect's `local` sandbox; Docker (socket
not accessible in the test host) and OLMo sandboxes are untested.
The adapters' generic capability APIs must not be read as broader native proof
than this matrix.
