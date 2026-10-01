# OLMo editable worker provenance and reuse

The containerized real-GPU campaign exposed an environment construction defect:
MAGNET's runner mounted a clean OLMo checkout and its Python 3.13 environment into
plain `ubuntu:24.04`, but that image has no `git` executable. The host's Git is
not available inside a container. `verify_engine_revision()` therefore could not
inspect the imported module's tracked membership, HEAD, or tracked cleanliness.

`uv sync --frozen` installs OLMo editable. Its actual PEP 610 metadata in the
reproduction was:

```json
{"url":"file:///tmp/aiq-identity/olmo","dir_info":{"editable":true}}
```

This identifies a mutable directory; it does not attest a VCS commit. The
fallback correctly found no `vcs_info.commit_id`. The caller's requested
`73ade80e24f796af55caeb8fd7b75a7f3fd607fd` could not be treated as observed truth.
The single unknown reason was:

```text
requested olmo-eval upstream_revision could not be verified against the executing source
```

MAGNET correctly assigns `unresolved-*` to a non-reusable preflight identity.
Execution still computes a digest, but it remains non-reusable and is published
only as an `_unkeyed` attempt. The store and MAGNET scheduling contract were
working as designed. The previous null-lease test used a host worker, where Git
was installed, and did not cover this image construction.

## Reproduction and comparison

No GPU or serving lease was used to diagnose the failure. A real pinned OLMo
checkout was synced on Python 3.13 with the `litellm` and `agents` extras, mounted
along with its managed Python and the MAGNET interpreter, and addressed through
`/opt/aiq-olmo-worker/bin/python`. MAGNET's actual `resolve_node` CLI reproduced
`reusable=false`. The public `resolve_evaluation_async(...,
require_secrets=False)` API supplied the detailed resolved facts below.

For `examples/olmo_agent_request.json` and `examples/inspect_tool_request.json`:

| Fact | OLMo, plain Ubuntu | OLMo, provenance image | Inspect, either image |
| --- | --- | --- | --- |
| Digest | `a78039f3ce22811746aea28808e78ee7da8d2a76a54dd8e74ae4ea4a4934dafd` | `9ce4c5dcc1f2f5643db64af58801f1a4a905a38b686978f92ced9f1f77f5dc69` | `d361607e85e9ce5087eff6d0097bd643d3228afaf39ba92c55893f5cb51b3c9e` |
| Reusable | false | true | true |
| Unknown reasons | unverified requested revision | empty | empty |
| Engine version | `1.0.0` | `1.0.0` | `0.3.272` |
| Engine revision | null | `73ade80e24f796af55caeb8fd7b75a7f3fd607fd` | null |
| Revision source | none | `git-checkout` | released distribution version; no requested SHA |

The OLMo adapter source digest was
`12e1bedc42c50a6f2285b74d0e730e6b77db69ac434a7d2c76009446b42fa1bc`;
`magnet_evals.examples.olmo_tasks` hashed to
`ff93e038f1289dbf039f25bca1030521c12e73b05047291d11c4b5b63d197897`.
Both were identical before and after installing Git. Inspect's adapter digest
was `ce95d67cc165193cbae52b803f849b33661911cb543c2819a581ac7cb6eaa3e7`;
its registration/task digest was
`8f3d0c336ff9d728c07201ed1f35ffe8da61b9a66af000f86df33c382573ad55`.
These are reproduction observations, not universal constants or new capability
claims; changing adapter/task content changes the corresponding digest.

OLMo's resolved native config was identical in both images: harness name
`aiq-evals`, provider `litellm`, model `gpt-4o-mini`, model revision
`example-endpoint-v1`, scaffold `openai_agents`, `enable_compaction=false`,
`tool_choice=auto`, tool `aiq_example_double`, task `aiq_example_tool`, no task
overrides, predictions/requests saved, and shuffle seed 42. The native config
retained the example base URL, which existing identity construction excludes.
Inspect's unchanged native config selected
`python:magnet_evals.examples.inspect_tasks:tool_task`, registered that module,
used `aiq_example/local`, enabled sample logging in `eval` format, and had empty
task/model arguments and roles with a null model base URL.

The imported OLMo module was
`/tmp/aiq-identity/olmo/src/olmo_eval/__init__.py`; the verified checkout was
`/tmp/aiq-identity/olmo`. The task module came from the mounted evaluator
checkout. Inspect imported its installed package under
`/tmp/aiq-identity/inspect/lib/python3.13/site-packages/inspect_ai/`.
Paths remain operational diagnostics and do not enter measurement identity.
The new `engine_checkout_probe_error` fact exposed the precise failure:
`[Errno 2] No such file or directory: 'git'`.

## Fix and validation

`dev/environments/worker-container.Dockerfile` adds Git and CA certificates to
the Ubuntu base. MAGNET's integration and real-GPU runners build this
evaluator-owned recipe and use its image ID. This is the environment layer that
can fix the defect: the adapter cannot attest checkout HEAD and cleanliness
without its verification tool, and trusting the request would violate identity
rules. No MAGNET runtime contract or infer-stack change is needed.

The lease regression now covers both host and mounted-container workers. Its
container variant runs the actual wrapped `resolve_node` command twice before
any lease, requires equal reusable canonical digests with no unknown reasons,
then executes once using infer-stack's null serving backend and the deterministic
example chat server. It checks canonical `runs/<prefix>/<digest>` publication,
rescheduling without another lease, and a distinct MAGNET node that reaches the
reuse gate for the same scientific measurement without entering a leased child.
Using plain `ubuntu:24.04` makes this regression fail at preflight, before serving.

Engine-free source tests still reject missing Git/unverified editable metadata,
dirty checkouts, unrelated repository installs, and mismatched requested SHAs.
The scientific identity algorithm, adapter identity, task hashes, and endpoint
exclusion rules are unchanged. The hardware gate retains its three hardware and
agent behavior checks; reuse is tested only in the cheap regression.

Existing `_unkeyed` attempts are not promoted retrospectively: they did not
prove the full identity. A corrected environment must execute once to populate
a canonical run. Custom images must provide Git, and an editable worker's full
checkout (including Git metadata) must be mounted and clean. Other verification
failures, including unsafe ownership or missing worktree Git metadata, remain
non-reusable and are now visible in structured resolution diagnostics.

## Commands run on the GPU-free VM

From `aiq-magnet-evals`:

```bash
dev/ci/engine_free.sh /tmp/aiq-identity/core
dev/ci/native_inspect.sh /tmp/aiq-identity/inspect-pinned
dev/ci/native_olmo.sh /tmp/aiq-identity/integration/olmo-eval
PYTHONPATH=$PWD /tmp/aiq-identity/olmo/.venv/bin/python -m pytest -q \
    tests/native/test_olmo_native.py tests/native/test_conformance.py tests/native/test_examples_native.py
PYTHONPATH=$PWD /tmp/aiq-identity/inspect/bin/python -m pytest -q \
    tests/native/test_inspect_native.py tests/native/test_examples_native.py tests/native/test_conformance.py
```

The isolated engine-free gate passed lint and **161 tests** (4 skipped, 24 native
tests deselected). The pinned Inspect/Python 3.11 gate passed **24 tests** (15
other-engine/opt-in tests skipped, 1 sandbox test deselected). The pinned
OLMo/Python 3.12 gate passed **17 tests** (14 other-engine tests skipped).
Additional Python 3.13 checks passed **17 OLMo tests** and **29 Inspect tests**;
their other-engine/optional cases were skipped.

From `~/code/aiq-magnet/.worktrees/aiq-evals-integration`:

```bash
AIQ_MAGNET_EVALS_DIR=/home/joncrall/code/aiq-magnet-evals \
    ./dev/ci/aiq_evals_integration.sh /tmp/aiq-identity/integration
```

All **63 tests passed**, with required prerequisites enabled and no skips.
The VM has no `~/code/infer_stack` checkout; the runner installed its declared
`infer-stack==0.7.0` dependency. No infer-stack sources were modified.

The focused Python 3.13 lease regression was also run with the provenance image:

```bash
AIQ_EVALS_OLMO_PYTHON=/tmp/aiq-identity/olmo/.venv/bin/python \
AIQ_EVALS_INSPECT_OPENAI_PYTHON=/tmp/aiq-identity/inspect/bin/python \
MAGNET_TEST_DOCKER=1 \
MAGNET_TEST_CONTAINER_VENV=/tmp/aiq-identity/container \
MAGNET_TEST_CONTAINER_IMAGE=aiq-evals-worker:identity \
MAGNET_REQUIRE_AIQ_EVALS=1 \
PATH=/tmp/aiq-identity/container/bin:$PATH \
    /tmp/aiq-identity/container/bin/python -m pytest -q tests/test_aiq_evals_lease.py
```

**4 tests passed**, including the explicit leased-command entry marker.
The same container case with `MAGNET_TEST_CONTAINER_IMAGE=ubuntu:24.04` failed
at the preflight reusable assertion in 3.82 seconds, before taking a lease.
The passing integration runs emitted existing multiprocessing fork deprecation
warnings. No GPU gate was run on this VM.

On the GPU machine, use the corrected worktree and updated files in both repos:

```bash
cd ~/code/aiq-magnet/.worktrees/aiq-evals-integration
AIQ_MAGNET_EVALS_DIR=~/code/aiq-magnet-evals \
INFER_STACK_DIR=~/code/infer_stack \
MAGNET_REAL_GPU_ALLOWED_GPUS=0 \
    ./dev/ci/aiq_evals_real_gpu.sh \
    ~/.cache/aiq-real-tests/magnet-aiq-evals-real-gpu-agentic
```
