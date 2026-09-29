# ADR-0001: Independent evaluation runtime and artifact layer

Status: Accepted

## Context

The original backend-agnostic evaluation plan was written in MAGNET terms and
placed shared evaluation contracts, engine adapters, execution, artifact
publication, and normalized readers under `magnet.backends`. Those facilities
are useful independently of MAGNET. `eval_audit` also contains overlapping
prototype functionality, but its audit/reproduction model should not define the
new package boundary.

## Decision

`aiq-evals` is an independent package whose responsibility is to reproducibly
obtain and describe evaluation results across heterogeneous native evaluation
engines.

It owns:

- serializable evaluation requests and resolved requests;
- backend discovery and capability validation;
- native task/model/provider resolution;
- measurement identity and reuse eligibility facts;
- native execution and native-result import;
- worker/process lifecycle and cancellation of owned resources;
- native artifact retention and checksums;
- run/sample/metric/trajectory access independent of the native engine runtime;
- content-addressed result storage and validation;
- schema/version compatibility for its own run bundle;
- cross-backend conformance tests.

Core `aiq-evals` must not depend on MAGNET or kwdagger.

## Consequences

MAGNET consumes `aiq-evals`; `aiq-evals` does not import MAGNET. A future audit,
reporting, or benchmark service may consume the same package without inheriting
MAGNET claim semantics.

Engine-specific dependency conflicts are handled through lazy imports and, when
necessary, isolated worker environments rather than by weakening the core
package boundary.
