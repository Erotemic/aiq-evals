# ADR-0009: Freeze the first public API and schemas after cross-engine conformance

Status: Superseded by [ADR-0010](0010-no-freeze-before-release.md) (2026-09-29).
Originally accepted 2026-09-29 under the plan's phase-6 criterion; retained for history.
Nothing below constrains current work.

## Context

ADR-0002 through ADR-0005 left the Python API and schemas provisional until
the three production adapters passed conformance. As of 2026-09-29, HELM
(`crfm-helm==0.5.14`), OLMo Eval (`73ade80e`, isolated worker), and Inspect
(`inspect-ai==0.3.272`) each pass the same native conformance suite,
`tests/native/test_conformance.py`, in their own environments. The suite
checks four things:

1. deterministic, worker-consistent resolution;
2. execute, then reuse, then re-import of identical metrics, then an
   engine-free read with every engine import blocked;
3. failures that stay inspectable but never become canonical;
4. cancellation that leaves a cancelled attempt, no canonical run, and no
   surviving owned child.

Evidence is in `docs/planning/phase6-evidence.md`.

## Decision

The following surface is frozen as version 1. `tests/test_public_api_freeze.py`
pins it:

- the `magnet_evals` package exports (`magnet_evals.__all__`);
- request, result, and run-manifest schemas at `schema_version` 1, including the
  frozen `tests/fixtures/run-v1` bundle;
- the measurement identity algorithm `aiq-evals-measurement-v2+sha256`
  (`identity_schema` 2);
- the result-store layout: `runs/`, `attempts/`, `attempts/_unkeyed/`,
  `quarantine/`;
- the CLI subcommands `validate`, `resolve`, `ensure`, `run`, `import-native`,
  `show`, `backends`, `engines`, and `phase1-*`.

After this point:

- A breaking change to a schema needs a new `schema_version`, explicit migration
  code, and a retained fixture of the previous version. Readers keep rejecting
  unknown future versions.
- Changing the identity algorithm needs a new algorithm string. A store
  never matches identities across algorithms.
- Adding optional fields, exports, or commands is allowed. Removing or renaming
  them needs a superseding ADR.
- Adapter labels remain experimental until the phase-8 release gate. Support
  is limited to the combinations in `docs/planning/phase1-capabilities.md`.

## Consequences

MAGNET integration (M1 onward in `aiq-magnet-integration-plan.md`) may depend on
this surface. The `magnet_evals.backends.*` adapter modules and the worker
protocol are not public API.
