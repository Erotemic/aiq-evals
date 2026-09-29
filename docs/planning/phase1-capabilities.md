# Phase 1 native capability matrix

Evidence is limited to the pins, local providers, tasks, and fixtures in
`phase1-evidence.md`. **S** = demonstrated supported combination, **U** =
explicitly unsupported, **T** = untested, **P** = task/provider-specific support.
No general upstream capability follows from a local fixture.

| Capability | HELM 0.5.14 through MAGNET | OLMo 73ade80 (mock or local LiteLLM/Agents) | Inspect 0.3.272 (local fixture provider) |
| --- | --- | --- | --- |
| Scored generation | T (historical output only) | S | S |
| Log probabilities | T | T | T |
| Multiple scorers/metrics | P (162 aggregate statistics in imported fixture) | T | S (match, includes) |
| Agent and tool execution | T | P (OpenAI Agents scaffold, `double`) | P (`use_tools`, `double`) |
| Trajectories | P (historical per-instance data; no live run) | S (assistant/tool/assistant turns) | S (messages/events) |
| Sandboxing | T | T | T |
| Epochs/repetitions | T | T | S (two epochs, mean/mode reducers) |
| Native import | P (MAGNET reuse of HELM directory) | S | S (`.eval`, JSON, directory) |
| Resume | T | T | T |
| Rescore | T | T | T |
| Failure and partial coverage | P (incomplete imported copy) | S (hard failure after metrics) | S (one sample error, partial coverage) |
| Cancellation and owned process cleanup | T | S (owned child) | S (owned child) |

HELM fresh computation remains open. Engine-owned sandbox cleanup is untested.
The adapters' generic capability APIs must not be read as broader native proof
than this matrix.
