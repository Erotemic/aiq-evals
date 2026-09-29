# ADR-0010: No API or schema freeze before a PyPI release

Status: Accepted (2026-09-29). Supersedes ADR-0009.

## Context

ADR-0009 froze the `magnet_evals` exports, the v1 request/result/manifest
schemas, the store layout, and the CLI once all three engines passed the shared
conformance suite. The original plan scheduled that freeze for the *joint*
integration gate: after MAGNET consumed the contract through real recipes,
mixed-engine runs, and end-to-end cache and dry-run checks. ADR-0009 applied it
before any consumer existed.

MAGNET integration then exposed deficiencies in exactly the frozen surface:
concurrent acquisition of one measurement, the reuse semantics of explicit
native imports, and what a claim-facing consumer needs to verify. A freeze at
that point made correcting them harder without protecting anyone. Nothing has
been published, so there are no external users to break.

## Decision

`aiq-magnet-evals` has no frozen public API or schema until a release is
published on PyPI. The maintainers decide when that happens and record the
frozen surface in a new ADR at that time.

Until then:

- exports, signatures, CLI commands, schemas, and the store layout may change
  whenever the MAGNET integration or a native finding shows they should;
- a schema change does not need a new `schema_version` or migration code, and
  the regression fixtures (`tests/fixtures/run-v1`, native regression outputs)
  are regenerated in the same change and reviewed as a diff;
- MAGNET remains the reference consumer: a change here lands together with
  the matching change in the MAGNET integration, so MAGNET keeps working.

These data-safety rules are unchanged, because they protect results rather
than freeze an interface:

- readers reject an unknown `schema_version` rather than reinterpreting it;
- a store never matches identities computed by different identity algorithms
  (the algorithm string changes whenever the identity inputs change meaning);
- a changed artifact must never be accepted as the artifact it replaced
  (checksums, identities, and quarantine stay mandatory).

## Consequences

`tests/test_public_api_freeze.py` is removed, and "frozen" is no longer a
release-gate requirement. `docs/release-gate.md` records the freeze as a step
*of* the first PyPI release rather than a precondition that constrains work
before it. Adapter labels stay `experimental` until that release.
