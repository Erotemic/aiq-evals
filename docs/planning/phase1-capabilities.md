# Native capability matrix (phases 1 and 5)

Evidence is limited to the pins, local providers, tasks, and fixtures in
`phase1-evidence.md`. **S** = demonstrated supported combination, **U** =
explicitly unsupported, **T** = untested, **P** = task/provider-specific support.
No general upstream capability follows from a local fixture.

| Capability | HELM 0.5.14 (MAGNET in Phase 1; aiq-evals adapter in Phase 5; local simple model) | OLMo 73ade80 (mock or local LiteLLM/Agents) | Inspect 0.3.272 (local fixture provider) |
| --- | --- | --- | --- |
| Scored generation | S (fresh simple MCQA exact-match) | S | S |
| Log probabilities | T | T | T |
| Multiple scorers/metrics | P (81 fresh MCQA statistics; multiple score names) | T | S (match, includes) |
| Agent and tool execution | T | P (OpenAI Agents scaffold, `double`) | P (`use_tools`, `double`) |
| Trajectories | P (fresh scenario state and per-instance statistics) | S (assistant/tool/assistant turns) | S (messages/events) |
| Sandboxing | T | T | P (`local` sandbox: tool exec inside it; directory removed on completion and on aiq-magnet-evals cancellation. `docker` sandbox with the example compose (digest-pinned `ubuntu:24.04`, `network_mode: none`, no volumes): tool exec inside the container, no host files, loopback only; container removed on completion and on cancellation; see `phase7-evidence.md`) |
| Epochs/repetitions | S (train trials as epochs) | T | S (two epochs, mean/mode reducers) |
| Native import | S (MAGNET reuse; aiq-evals adapter incl. MAGNET symlinked runs) | S | S (`.eval`, JSON, directory) |
| Resume | T | T | T |
| Rescore | T | T | T |
| Failure and partial coverage | S (native scenario failure; missing per-instance/stats files) | S (hard failure after metrics) | S (sample error; run-level `error`; native SIGINT `cancelled` and SIGKILL `started` logs import as non-success with partial coverage) |
| Cancellation and owned process cleanup | S (owned child; SIGINT honored in 2.8 s) | S (owned child; fixture blocks its loop, so cleanup comes via SIGTERM escalation) | S (owned child; SIGINT-first cancellation yields Inspect's own `cancelled` log) |
| Turn/time limits | T | S (`max_turns`) | S (`message_limit`, `time_limit`) |
| Tool/judge error mapping | T (no tools) | P (tool exception becomes text with `is_error=False`; judge untested) | S (`ToolError` model-visible; tool crash or judge failure is a sample failure) |
| External OpenAI-compatible endpoint (local) | T | S (LiteLLM/OpenAI Agents) | S (`openai` provider; needs the `openai` package) |
| Operational endpoint override (`model_endpoints`) | U (registry deployments) | S primary role only | S primary and bound auxiliary roles (a grader reached only through its override, `openai` variant env) |

HELM fresh generation is demonstrated only with its local simple model. Engine-owned
sandbox cleanup is demonstrated only for Inspect's `local` sandbox and for its
`docker` sandbox with the one example compose configuration (2026-09-29). OLMo
sandboxes (SWE-ReX, outside the verified OLMo extras) are untested.
The adapters' generic capability APIs must not be read as broader native proof
than this matrix.
