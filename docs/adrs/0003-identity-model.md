# ADR-0003: Separate measurement, normalized-artifact, and evidence identities

Status: Accepted

## Context

The original MAGNET-oriented design mixed inputs that change native computation
with downstream choices about how a result is interpreted as scientific evidence.
That causes unnecessary recomputation and makes cache semantics difficult to
reason about.

## Decision

Maintain three distinct identity layers.

### Measurement identity — owned by `aiq-evals`

Contains inputs that can change what the native evaluation computes, including
as applicable:

- engine and upstream revision/version;
- adapter semantics/version;
- resolved task/suite membership and task/config content;
- data/sample revision and selection;
- primary and auxiliary model/provider bindings and immutable endpoint token;
- generation/sampling settings and seeds;
- epochs/repetitions when they are native execution inputs;
- scorers actually executed;
- solver/scaffold/tool configuration and versions;
- sandbox/runtime content identity.

Secrets are never identity inputs. Secret *names* or required capabilities may
be persisted where needed; secret values may not.

### Normalized-artifact identity — owned by `aiq-evals`

Adds to measurement lineage the native artifact content digest, normalization
logic/schema version, and related conversion lineage. Editing an imported native
log or changing normalization semantics must create a different normalized
artifact identity.

### Evidence-view identity — owned by MAGNET

Adds downstream interpretation such as:

- selected task/model/scorer/score/metric/reducer;
- coverage requirement;
- partial/unknown coverage policy;
- claim-facing projection.

Selecting another already-produced metric or changing MAGNET's evidence policy
must not force native evaluation execution. Requesting an additional scorer from
the native engine may.

## Consequences

A reviewer should reject implementations that place MAGNET metric selectors or
evidence policy into native measurement identity unless they demonstrably alter
the native computation.

Unresolved mutable references disable reuse until an immutable token/content
identity can be established.
