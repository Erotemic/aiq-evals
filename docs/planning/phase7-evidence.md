# Phase-7 evidence: agentic operational and security behavior

Date 2026-09-29. Evidence producer: Claude Opus 5.5 (Anthropic, `claude-opus-5-5`, 1M context).
The security review is `docs/security-review.md`.

| Plan item | Status | Evidence |
| --- | --- | --- |
| deterministic multi-turn/tool fixtures for both new engines | done | Phase-1 records; the shared local OpenAI-compatible server `tests/native/chat_server.py` |
| normalized trajectory access with explicit loss-of-detail metadata | done | `native.trajectory_detail` on every sample (source, plus non-empty native fields not retained), read with `magnet_evals.outputs.trajectory_detail`. Examples: Inspect omits `input`/`target`/`turn_count`/timestamps; HELM omits token logprobs, request parameters, and timings; OLMo retains all prediction fields. |
| turn/time/concurrency limits | done (native limits); concurrency is a native option | Inspect `message_limit`/`time_limit` end samples with a recorded `limit`; they are not failures (`test_native_message_and_time_limits_are_not_errors`). OLMo `max_turns=1` enters identity and stops the scaffold after the tool round (`test_max_turns_limit_changes_native_trajectory`). The run-level wall clock is `ExecutionContext.timeout_seconds` (operational, SIGINT-first). Concurrency options (Inspect `max_samples`, OLMo `max_concurrency`) are native options and are hashed conservatively. |
| secret handling/redaction | done | S2 and S3 in the security review |
| tool/judge error mapping | done | Inspect: a `ToolError` is model-visible and the sample is complete; an uncaught tool exception or a failing grader-role model is a sample failure, so coverage is partial with `failed=1` while the native log says `success` (`test_tool_and_judge_error_mapping`). OLMo at the pin: a tool exception becomes a model-visible tool result with `is_error=False`, i.e. only text records the failure (`test_crashing_tool_is_reported_to_the_model`). OLMo judge errors are untested. |
| cancellation cleanup | done | P1-06 and phase-5 records; conformance check 4 for all three engines |
| isolated attempt retries | done | every `ensure` attempt is a separate bundle under `attempts/`; retry policy is the caller's (ADR-0006) |
| external endpoint support | done (local OpenAI-compatible endpoint) | OLMo LiteLLM/OpenAI Agents (Phase 1). Inspect's real `openai` provider: 2 HTTP calls, tool round trip, key absent from the bundle (`test_openai_compatible_external_endpoint`). That test needs `openai`, which the verified pin set lacks; it ran in a variant environment, see below. The endpoint identity comes from the binding's `revision`/`cache_token`: without one, identity is non-reusable. |
| optional sandbox examples | done | `examples/inspect_local_sandbox_request.json`; native sandbox tests. Added 2026-09-29: `examples/inspect_docker_sandbox_request.json` (Docker, opt-in) and `tests/native/test_inspect_docker_sandbox.py` (isolation and cleanup on completion and cancellation; see below). OLMo sandboxes stay untested. |
| security review | done | `docs/security-review.md` (S1–S6 fixed; residual risks listed) |

## Commands

- Inspect verified pin: `/tmp/aiq-inspect-p1/bin/python -m pytest -q tests/native/test_inspect_native.py tests/native/test_conformance.py`
  gives 19 passed, 9 skipped (the other engines' conformance profiles, and
  `openai`).
- Inspect with `openai`: build `/tmp/aiq-inspect-openai` with
  `uv venv --python 3.11 /tmp/aiq-inspect-openai`, then
  `uv pip install --python /tmp/aiq-inspect-openai/bin/python -c dev/environments/phase1/inspect-py311-constraints.txt -e '.[inspect,tests]' openai`
  (this resolved `openai==3.20.0`). Running `test_inspect_native.py` there
  gives 16 passed.
- OLMo: `PYTHONPATH=$PWD /tmp/olmo-eval-p1/.venv/bin/python -m pytest -q tests/native/test_olmo_native.py tests/native/test_conformance.py`
  gives 12 passed, 8 skipped.

## Docker sandbox (added 2026-09-29)

Environment: Inspect `0.3.272` (verified pin set, CPython 3.11.15), Docker
client 29.1.3, Docker Compose 2.40.3, image
`ubuntu:24.04@sha256:008173c23f95b170204355c12626cb5a965d779a7e1283b09e9cffbb1bf33ca3`.
Command: `<inspect-venv>/bin/python -m pytest -q tests/native/test_inspect_docker_sandbox.py tests/native/test_examples_native.py`
(run with the Docker group) gives 8 passed, 4 skipped (the other engines' and
the `openai` examples). `docker ps -a` is empty afterwards.

- The tool executes inside the container: a host marker file is absent there,
  and `/sys/class/net` lists only `lo`.
- The container is gone after completion, and after aiq-magnet-evals cancels the
  run while the sandboxed tool is blocked in `sleep 120`. The attempt is
  published as `cancelled`.
- The compose configuration is defined in the task module's source, so its
  pinned image digest is part of the measurement identity.

## Observations recorded without a capability claim

- HELM `scenario_state` completions carry `logprob` and per-token logprobs, but
  every observed value is `0` (historical GPT-2 and fresh simple-model runs).
  Log probabilities therefore stay untested (T).
- OLMo mock-provider predictions carry `sum_logits`/`logits_per_token`. They
  come from a mock provider and are not evidence of log-probability support.
