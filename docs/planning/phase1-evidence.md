# Phase-1 evidence ledger

This is the canonical record for phase-1 validation. The repository-bootstrap
snapshot below predates the 2026-09-29 native campaign; later campaign records
supersede its OPEN status labels. A checkbox is not complete
until its evidence is recorded here. Documentation or a historical integration
may motivate a test but does not replace it.

## Record template

For each runtime item record:

```text
ID:
Date:
Implementer/reviewer:
aiq-evals revision:
Upstream engine/revision:
Python/runtime identity:
Dependency lock or container digest:
Command/test ID:
Output artifact path/checksum:
Outcome:
Failure classification (if any):
Notes/limitations:
```

Do not record credentials. Preserve failed/retried attempts rather than replacing
them with only the eventual green attempt.

## Repository bootstrap evidence

### P1-01 - evidence ledger

Status: COMPLETE for repository scaffolding.

Evidence:

- this file defines the canonical record and required fields;
- `aiq_evals.phase1.PHASE1_TASKS` exposes the checklist programmatically;
- `aiq-evals phase1-status` reports the repository snapshot.

No native engine behavior is implied by this completion.

### P1-02 - pins and worker instructions

Status: PARTIAL.

Implemented evidence tooling:

- `aiq-evals phase1-probe` captures Python/host and installed-engine facts;
- repeated `--checkout ENGINE=PATH` captures exact git HEAD, tracked cleanliness,
  origin URL, `requires-python`, and `uv.lock` presence;
- `aiq_evals.probes.isolated.build_locked_uv_command` constructs locked upstream
  `uv run` commands without adding engine dependencies to core;
- `validate_git_revision` rejects mutable branch/tag names when an immutable
  source revision is required.

Candidate/history facts currently known from supplied source material:

- original OLMo Eval plan inspection:
  `73ade80e24f796af55caeb8fd7b75a7f3fd607fd`;
- supplied `eval_audit` OLMo prototype revision:
  `c84828e4af096004c561b668b68e0b126c7f60e9`;
- existing MAGNET dependency declaration: `crfm-helm>=0.5.8`.

None of these is yet the `aiq-evals` supported pin. Selection requires the native
fixture suite below.

## Runtime items

### P1-03 - OLMo Eval generation + tool execution

Status: OPEN.

Required artifacts:

- scored generation fixture;
- tool-calling multi-turn fixture;
- request/prediction/trajectory artifacts;
- failure-after-diagnostics fixture;
- worker registration and cleanup evidence.

### P1-04 - Inspect generation + tool execution

Status: IMPLEMENTATION PRESENT; NATIVE EVIDENCE OPEN.

The phase-4 adapter targets candidate release `inspect-ai==0.3.272` through the
public eval/log APIs. Fake-native and owned-worker contract tests are recorded in
`phase4-evidence.md`; they do not satisfy this native gate.

Required artifacts:

- scored generation fixture;
- solver/agent tool fixture;
- multi-log/sample-error/epoch/reducer fixtures;
- cancellation/nonterminal fixture;
- worker import/cleanup evidence.

### P1-05 - HELM compute/reuse/import

Status: OPEN.

Required artifacts:

- fresh computation;
- cached reuse/materialization;
- native run import;
- aggregate/per-instance records;
- unknown/incomplete coverage fixture.

### P1-06 - async/worker/cleanup

Status: OPEN.

Must be demonstrated with selected native pins.

### P1-07 - capability matrix

Status: PARTIAL.

The matrix categories are defined in `aiq-evals-plan.md`; no runtime capability
is yet marked supported in this new repository.

### P1-08 - EEE normalization decision

Status: OPEN.

The supplied `eval_audit` source demonstrates that EEE was already considered a
normalization substrate, but its `every_eval_ever` submodule contents were not
present in the supplied archive. This repository therefore does not infer the
current EEE schema from that snapshot. Inspect the real current EEE source and
run fixture conversions before deciding.

### P1-09 - OLMo Eval packaging go/no-go

Status: OPEN.

Default hypothesis: prefer an isolated locked upstream worker if co-installation
is not cleanly reproducible. This is not yet a decision.

### P1-10 - acceptance gate

Status: BLOCKED by P1-02 through P1-09 runtime evidence and the separate MAGNET
cardinality experiment.

## Local build-environment observation

At archive creation time the current build interpreter did not have `helm`,
`olmo_eval`, `inspect_ai`, `kwdagger`, or `magnet` installed. Consequently no
native runtime success is claimed by this archive. The dependency-free core test
suite is the only executed validation recorded by the archive builder.

### API-surface probe support

`aiq-evals phase1-probe` also checks the intended public OLMo Eval and Inspect
adapter seams when those packages are installed. These symbol checks are only a
compatibility precondition; a symbol existing is not evidence that execution,
status mapping, or cleanup semantics work.

## 2026-09-29 native validation campaign

Evidence producer: GPT-6-Sol (OpenAI). All `aiq-evals` revisions below are
ancestral commits in this campaign; the Inspect partial-coverage correction is
at `b1f64cf`. All tests used deterministic local providers or preserved native
files, with no external model service. Fixture paths are relative to this repo.

### P1-02: tested pins and reproducible environments — PARTIAL

| Engine | Tested version/revision | Python | Reproduction and isolation |
| --- | --- | --- | --- |
| Inspect | `inspect-ai==0.3.272` | CPython 3.11.15, `/tmp/aiq-inspect-p1` | `uv venv --python 3.11 /tmp/aiq-inspect-p1`; `uv pip install --python /tmp/aiq-inspect-p1/bin/python -e '.[inspect,tests]'`. The adapter executes in an owned process; the package's optional extra installs Inspect only when requested. |
| OLMo Eval | checkout `73ade80e24f796af55caeb8fd7b75a7f3fd607fd`; upstream `uv.lock` SHA256 `8c3ac8e85dad2de9d7934df0c6c7cf645648effdc955d0b84bea942f1ab4217e` | CPython 3.12.3, `/tmp/olmo-eval-p1/.venv` | At that checkout: `uv sync --frozen --no-default-groups --extra litellm --extra agents --python 3.12`; `uv pip install --python .venv/bin/python pytest`. Run with `PYTHONPATH=/home/joncrall/code/aiq-evals`. Isolated worker required for the chosen delivery mode. |
| HELM | `crfm-helm==0.5.14`, MAGNET checkout `7bb105ab1c85bfaa01bf68c97ff7523332479ee4` | CPython 3.12.3, `/tmp/aiq-helm-p1` | `uv venv --python 3.12 /tmp/aiq-helm-p1`; `uv pip install --python /tmp/aiq-helm-p1/bin/python -e '/home/joncrall/code/aiq-magnet[helm]' 'crfm-helm==0.5.14' pytest`. This pulls large Torch/CUDA dependencies; keep it isolated from core. Only import/reuse is tested at this pin. |

OLMo checkout was clean. The candidate source revision was selected for the
native local smokes, but no cross-revision compatibility claim is made.
Inspect and OLMo pins are supported for the tested combinations in the matrix;
HELM's pin is an import/reuse pin only until fresh execution succeeds. No
complete lock authority exists for the Inspect/HELM pip environments, so their
reproduction is version-pinned at the engine level, not byte-for-byte locked.

### P1-03: OLMo Eval — native gates demonstrated, broader support open

`aiq-evals` revisions: `225a40a`, `9a06d1a`, `9579d33`.
Upstream: OLMo checkout and Python environment above. Command:
`PYTHONPATH=/home/joncrall/code/aiq-evals /tmp/olmo-eval-p1/.venv/bin/python -m pytest -q tests/native/test_olmo_native.py`
(4 passed). Native registration imports `tests.native.olmo_fixture` in both
owned evaluation and spawned inference workers. The mock-provider task scored
`contains_42=1.0` and wrote request, prediction, and metrics files; native
reimport succeeded. The local HTTP LiteLLM/OpenAI Agents task made two actual
model requests and called `double`, yielding assistant/tool/assistant turns and
`contains_42=1.0`. It also reimported from native artifacts. Source checksums:
`olmo-native/metrics.json` SHA256 `d723ed6575ed0ba9b7bfda407406e12c79c735986ad8e6ad52212662d58fa4ca`;
`olmo-native/tool/metrics.json` `8b2e448cf40780ef8a483535d6c7e971b4ae4a2c80fd240cad7bb48d20f5fbca`;
`olmo-native/tool/predictions.jsonl` `2080fb21c3ab11d08f066e6f356c8bc2784659fbff513a9e61b570b6f52964b5`;
`olmo-native/tool/requests.jsonl` `820b1b5cf392cb59436483ea6220f444495ecd11eb21c37cc7dfc7b320b8c631`.

The forced native `HardFailureRateExceeded` wrote `olmo-native/failure/metrics.json`
(SHA256 `d2f6f63f4fe2bc33add49da33d647809331b47045d9e3703eccd9372f7afe42d`):
processed 1, saved 0, failed 1. The attempt was failed and lacked a successful
run marker. The first agent-tool attempt exposed missing registration in an
inference worker; the adapter was fixed to bootstrap those modules. The worker's
redacted stdout/stderr are retained. Tool capability is confined to this
scaffold/provider; log probabilities, sandboxing, resume, rescore, and
multi-task native runs remain untested.

### P1-04: Inspect — native gates demonstrated for local provider

`aiq-evals` revisions: `07d361f`, `9a06d1a`, `b1f64cf`.
Command: `/tmp/aiq-inspect-p1/bin/python -m pytest -q tests/native/test_inspect_native.py`
(7 passed). Native generation scored `match` and `includes`; native tool
execution produced a tool message with result `4`. The three-log fixture
contains generation, tool, and auxiliary-role tasks; the auxiliary `grader`
model and primary model both appear in native events. Two epochs and explicit
`mean`/`mode` reductions were observed. `.eval`, JSON, and a directory of
multiple logs imported successfully. `partial/partial.eval` records one failed
sample and one completed sample; native log status is `success`, while normalized
coverage is correctly `partial` (expected 2, processed 2, failed 1).

Artifacts/checksums: `inspect-native/generation.eval`
`2a4e6767749575dc18667ebebbd93455b1174836d8936fba1a4d3b6808df0adf`;
`generation.json` `b796f1379db77164acdcf3deaeb1eaf2d5f15d7a43b6debcb273af844f38893b`;
`tool.eval` `47b086e66f452ba0d7cf721005af9733af20afba229f3cb73c9492f769c5131c`;
`multi/{generation,tool,role}.eval` respectively
`8b7c96bba0984c853c1ad689f5b37b6581a86025cbcb8c0064008b04bb8443a8`,
`0e3fe54264e247967caf6c578d00aecceab1fcc5df94f892538e3b67a65f1640`,
`cd899d986ff7a5101bffd0ded36b718f7b44244c6963a283fa397bdc8f7edff1`;
`reducers/reducers.eval` `77337ad4ea6b7d75d293433aefc57b00143f7913a2fd9a3122cab59c0234df5f`;
`partial/partial.eval` `08649630fb96aff7784121776d5c097a1b5a967a76a6742bfa9f5b01b966f552`.

A failed initial partial-coverage assertion caught an adapter error: counting
logged samples as complete ignored `completed_samples`. Fixed at `b1f64cf`.
Absolute local task file paths also failed under Inspect's Python 3.11
`Path.glob`; the adapter now passes a relative path and imports declared
registration modules. Native top-level error/cancelled log import, engine-owned
sandbox cleanup, resume/rescore, and log probabilities remain untested.

### P1-05: HELM — import/reuse evidence, fresh execution blocked

`aiq-evals` revision `e895107`; MAGNET and HELM pins/environment above. Command:
`/tmp/aiq-helm-p1/bin/python -m pytest -q tests/native/test_helm_native.py`
(1 passed). Historical native run from EEE revision
`1eb9d39aed34505e15db637153de72318bd946d4` is in
`tests/fixtures/helm-native/mmlu-philosophy-gpt2/`; its original HELM
version/Python are unknown. `stats.json` SHA256
`2ef96498f2464c6830e252f8aaf9261e163105f5c39ab474b1acfccb1a0565b2`
and `per_instance_stats.json` SHA256
`6b444efb07af4d1bb9496e177a57d9708aacd5a9c5592c506dbfe2179da35deb`.
MAGNET materialized the directory in `reuse_only` mode and read 162 aggregate
statistics and 10 per-instance entries. A derived copy without
`per_instance_stats.json` reused only with
`--require-per-instance-stats false`; complete sample coverage cannot be
inferred from its aggregates. Initial reuse of the unwrapped EEE directory
failed because MAGNET requires `benchmark_output/runs/<suite>/<run>` layout;
the fixture test wraps it in that layout. Fresh HELM computation is still open,
so the P1-05 and P1-10 gates remain open. No Phase-5 adapter was added.

### P1-06: cancellation and lifecycle — owned process proof, sandbox open

`aiq-evals` revision `9a06d1a`. Native tests above cancel asynchronous
runs after a child PID is emitted. Both OLMo and Inspect tests show their owned
child gone or reaped as a zombie, `ATTEMPT_TERMINAL=cancelled`, and no
`RUN_COMPLETE`. The `aiq-evals` runner owns the adapter worker process group;
OLMo owns its inference worker and Inspect owns its local provider invocation.
This proves cleanup of the tested child processes, not arbitrary
engine-managed sandboxes or remote resources. A prior cancellation test using
an uninstrumented fast task could finish before cancellation; a slow child
fixture was used for deterministic observation.

### P1-07: matrix — PARTIAL

The combination-level matrix is `docs/planning/phase1-capabilities.md`.
Unknown claims remain explicitly untested rather than inferred from upstream
source or marketing.

### P1-08: EEE schema — DECIDED, see ADR-0008

EEE revision `1eb9d39aed34505e15db637153de72318bd946d4`, schema 0.3.0;
aggregate schema SHA256 `c9c6195aec8a9dfa0b2aba4924ac1aa8a184c9d8ca97cee778cb531088e39b48`,
instance schema SHA256 `b16b7fa7f0aa32763444179d94ffb2336ddb12c3fd2903835fe491666c1ff3e6`.
In Python 3.12 with EEE 0.3.0, the HELM converter command equivalent to
`HELMAdapter().transform_from_directory(fixture, metadata_args={'file_uuid':
'12345678-1234-4234-8234-123456789abc'}, output_path='/tmp/aiq-eee-helm-converted')`
produced one aggregate log, 48 evaluation results, and 80 instance rows over
10 sample IDs. The first attempt omitted `file_uuid` and failed with
`file_uuids[0] is required`. In `/tmp/aiq-eee-inspect-p1` (Python 3.12,
EEE 0.3.0, Inspect 0.3.272), conversion of both `.eval` and JSON generation
fixtures failed with `Cannot determine model developer from model path
'fixture/local'`. No OLMo converter exists. Schema inspection found required
Boolean correctness, string-only tool arguments and metadata, and no unambiguous
first-class epoch/reducer/scorer/status/coverage fields. ADR-0008 keeps the
independent normalized result schema; native files remain authoritative.

### P1-09: OLMo packaging — ISOLATED WORKER SELECTED

The locked upstream Python 3.12 environment passes generation, tool execution,
import, hard failure, and cancellation; core supports Python 3.11 and has no
OLMo dependency. Therefore OLMo is delivered through the isolated pinned
worker checkout above. A reproducibly co-installed optional extra was not
established and is not advertised. The local HTTP fixture avoids external
credentials but only proves that tested scaffold/provider combination.

### MAGNET cardinality spike — BLOCKED BY MISSING PROJECTION

MAGNET revision `7bb105ab1c85bfaa01bf68c97ff7523332479ee4`.
The actual Inspect `multi/` logs show three result records and two epochs;
OLMo fixtures currently show one task each. Inspecting MAGNET's existing
`build_tables`, `KWDaggerProcessor.load_available_result_rows`, and
`ClaimResultNamespace` shows that they consume already flattened DAG result
rows. There is no current projection from an `aiq-evals` multi-result run into
one MAGNET evidence row, nor a native multi-result OLMo fixture. Passing these
fixtures through those paths would require the later MAGNET integration, which
is outside Phase 1. No claim-vote cardinality result is asserted. The P1-10
acceptance gate remains open.

### Final local validation — 2026-09-29

At `b1f64cf` plus import-only lint commit `b2e008e` and the documentation
commit that contains this record:

- `python -m pytest -q`: 48 passed, 3 native skips (base interpreter has no engines).
- `python -m compileall -q aiq_evals tests`: passed.
- `ruff check .`: passed after clearing 10 import/unused-import lint findings;
  the first check failed with 9 findings before the new native fixture added one.
- `/tmp/aiq-inspect-p1/bin/python -m pytest -q tests/native/test_inspect_native.py`: 7 passed.
- `PYTHONPATH=/home/joncrall/code/aiq-evals /tmp/olmo-eval-p1/.venv/bin/python -m pytest -q tests/native/test_olmo_native.py --basetemp=/tmp/aiq-olmo-final`: 4 passed.
- `/tmp/aiq-helm-p1/bin/python -m pytest -q tests/native/test_helm_native.py`: 1 passed, 2 upstream MAGNET deprecation warnings.
- A clean `/tmp/aiq-core-p1` CPython 3.11.15 environment built with
  `uv venv --python 3.11 /tmp/aiq-core-p1` and
  `uv pip install --python /tmp/aiq-core-p1/bin/python -e .` imported
  `aiq_evals`, parsed an `EvaluationRequest`, and loaded
  `tests/fixtures/run-v1`. `find_spec` returned no Inspect, OLMo, or HELM.
  `RunBundle.load` then read the native OLMo success (1 result, 1 sample),
  native OLMo failed bundle (1 result, 0 samples), and native Inspect
  multi-log bundle (3 results, 11 sample/reduction records) with that same
  engine-free interpreter.
- No static type checker is configured in `pyproject.toml`; Ruff is the
  configured lint check.

For the MAGNET blocker, the source inspection commands were
`rg -n 'build_tables' /home/joncrall/code/aiq-magnet` and
`rg -n 'aiq_evals|inspect_ai|olmo_eval' /home/joncrall/code/aiq-magnet/magnet -g '*.py'`.
The latter returned no projection. `build_tables` is imported from kwdagger
inside `magnet/_kwdagger.py`, and its rows are handed to
`ClaimResultNamespace` by MAGNET. The native multi-log/epoch fixtures cannot
be presented to these paths as one claim row without implementing the future
MAGNET projection.
