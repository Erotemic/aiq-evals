# Security review (plan phase 7)

Date: 2026-09-29. Reviewer: Claude Opus 5.5 (Anthropic, `claude-opus-5-5`, 1M context).
Scope: `aiq_evals` at the phase-7 commits, and the three adapters at their verified
pins. This is a design and code review with targeted tests, not a penetration test.

**Trust model.** A request names task code, plugins, tools, and model endpoints.
Resolving or executing a request runs that code as the invoking user, and can
reach whatever that user can reach on the host. aiq-evals is not a sandbox. As the
plan says, a worker process or container is not a security guarantee on its own.

## Findings fixed in this review

| # | Area | Finding | Fix / test |
| --- | --- | --- | --- |
| S1 | Artifact paths | `publish_run` used `shutil.copytree`, which follows symlinks. A native directory with a file or directory link to a host file (demonstrated with a fake `~/.ssh/id_rsa`) copied that file into the published bundle. Bundles are meant to be shared, so any untrusted import source could exfiltrate files. | `copy_native_tree` copies in-tree links as content and never copies FIFOs, devices, or dangling links. Links that leave the tree are excluded for executed runs and refused for imports unless the caller passes `allow_external_symlinks=True`. Every decision is recorded in the manifest. `tests/test_artifacts_store.py::test_external_symlinks_are_never_silently_copied`; HELM native seam test. |
| S2 | Secrets | Worker stdout/stderr were scrubbed of env values, but returned adapter diagnostics (native exception text and tracebacks) were published verbatim. | Every key and string of the returned result is scrubbed of env values of 8 characters or more before publication (`test_adapter_diagnostics_quoting_a_secret_are_redacted`). Shorter values are named in `env_values_not_redacted_as_too_short`, because scrubbing them corrupted a digest in a native test. |
| S3 | Secrets | `required_secrets` names were accepted but never checked, so a missing credential surfaced deep inside a native provider. | `check_required_secrets` fails before any worker starts (`test_missing_required_secret_fails_before_execution`). `engine_options.required_secrets` is accepted by every adapter and must hold environment-variable names. |
| S4 | Cancellation | Owned-process cleanup was SIGTERM-first, which killed Inspect before its sandbox cleanup and leaked the local sandbox directory. | SIGINT-first, then a bounded escalation (see `phase1-evidence.md`, P1-06). |
| S5 | Provenance | A caller-supplied `upstream_revision` was recorded as engine provenance without checking it. | `verify_engine_revision`: the revision is observed from the executing checkout; a contradicting request is rejected, and an unverifiable one is non-reusable. |
| S6 | Endpoints | The Inspect adapter sent `base_url` inside `model_args`, which made every endpoint request crash. | `base_url` now maps to `eval(model_base_url=)`, with a native test against a local OpenAI-compatible server. |

## Review by area

### Task loading
- Static validation (`validate_request`) imports no task, plugin, or engine code
  (`test_static_validation_*`, `test_examples_validate_without_engines`).
- Resolution imports task factories (Inspect `python:` references and
  `registration_modules`), OLMo `task_modules`, and HELM `plugins`, and runs them.
  It does so in the worker interpreter when one is given (`resolve_evaluation_async`).
  This is arbitrary code execution by design; only resolve requests you trust.
- Loaded source is hashed into identity, so a changed task is never reused
  silently. Code with no hashable source makes identity non-reusable. HELM
  plugins must be module names rather than paths, so that they can be hashed.
- Residual risk: only the directly referenced module file is hashed. Helper
  modules it imports are covered only through `task_revision` or the engine
  revision.

### Tool execution
- Tools run inside the engine process (OLMo, Inspect) or inside the engine's
  sandbox (Inspect `sandbox()` calls), with the worker user's privileges.
- Error mapping is native and recorded, never invented:
  - an Inspect `ToolError` is shown to the model;
  - an uncaught Inspect tool exception is a sample failure;
  - an OLMo tool exception becomes model-visible text with `is_error=False`
    at the pin.

### Sandbox boundaries
- Inspect's `local` sandbox is only a temporary working directory. It gives no
  filesystem, network, or process isolation. It is cleaned up on completion and
  on aiq-evals cancellation (native test).
- Docker sandboxes are untested: the review host denies access to the Docker
  socket. Nothing here should be read as a claim that containers isolate tasks.
  Containers an engine starts leave the worker's process group, so aiq-evals
  cancellation cannot reach them. Their cleanup is the engine's job (SIGINT
  gives the engine that chance), and it is unverified.
- OLMo and HELM sandboxes are not exercised.

### Host mounts and network
- Workers inherit the parent process environment plus `ExecutionContext.env`,
  the host network, and the host filesystem. The HELM adapter uses a per-run
  `prod_env`, so HELM's cache and credentials files stay hermetic.
- Residual risk: the whole parent environment, including unrelated credentials,
  reaches task code. To limit what task code sees, launch the aiq-evals caller
  with a minimal environment (for example with `env -i`, keeping `PATH` and
  `HOME`), and pass required secrets through `ExecutionContext.env`.

### Secrets
- Credential-bearing keys are rejected in requests. Only secret names may be
  persisted (`required_secrets`). Values never enter identities or manifests
  (`test_operational_context_does_not_change_identity`).
- Values of 8 characters or more are scrubbed from worker logs and published
  results. Native engine artifacts are kept unmodified: an engine that writes a
  credential into its own log will publish it. This is the ADR-0004 trade-off
  (native artifacts are authoritative and never rewritten).

### Cancellation
- The runner owns the worker process group. On cancellation or timeout it
  sends SIGINT, waits a 15 s grace period, then sends SIGTERM, waits 5 s, then
  sends SIGKILL, followed by a final group SIGKILL.
- Processes that call `setsid()` or daemonize escape the group and are not
  cleaned up. Native tests cover owned children for all three engines and the
  Inspect sandbox.

### Artifact path handling
- `ArtifactReference` rejects absolute paths and `..`, so a crafted manifest
  cannot make `RunBundle.load` read outside the bundle during verification.
- Publication is atomic (staging directory, fsync, rename). The store
  quarantines, rather than deletes, a canonical run that fails validation.
- S1 closed the symlink exfiltration path.
