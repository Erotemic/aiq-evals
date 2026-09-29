"""Measurement identity construction."""
from __future__ import annotations

import importlib.util
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from aiq_evals.contracts import EvaluationRequest, MeasurementIdentity
from aiq_evals.jsonutil import normalize_json_object, sha256_file, sha256_json

# v2: resolved content digests (``identity_facts``) and adapter source identity
# participate in the digest; v1 hashed neither.
IDENTITY_ALGORITHM = 'aiq-evals-measurement-v2+sha256'


def adapter_source_digest(package: str | None) -> str:
    """Digest every Python source file of an adapter package.

    Pre-release adapter implementation identity: any change to the adapter or
    its normalizer yields a new measurement identity, so cached results are not
    reused across adapter semantics that a hand-maintained version string might
    fail to capture. This is deliberately conservative (cosmetic edits also
    invalidate reuse).
    """
    if not package:
        raise ValueError('adapter_source_digest needs a package name')
    spec = importlib.util.find_spec(package)
    if spec is None or not spec.submodule_search_locations:
        raise ValueError(f'{package!r} is not an importable package')
    root = Path(next(iter(spec.submodule_search_locations)))
    entries = [
        [path.relative_to(root).as_posix(), sha256_file(path)]
        for path in sorted(root.rglob('*.py'))
    ]
    return sha256_json(entries)


def _unknown_identity_reasons(
    request: EvaluationRequest,
    resolved_facts: Mapping[str, Any],
    identity_facts: Mapping[str, Any],
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not request.task_revision and not identity_facts.get('task_source_sha256'):
        reasons.append('task revision/source content is unknown')
    if not request.data_revision:
        reasons.append('data revision is unknown')
    for model in request.models:
        if not (model.revision or model.cache_token):
            reasons.append(f'model role {model.role!r} has no immutable revision/cache token')
    if not resolved_facts.get('engine_revision') and not resolved_facts.get('engine_version'):
        reasons.append('native engine revision/version is unknown')
    extra = resolved_facts.get('identity_unknown_reasons') or []
    if isinstance(extra, Sequence) and not isinstance(extra, (str, bytes)):
        reasons.extend(str(item) for item in extra)
    return tuple(dict.fromkeys(reasons))


def measurement_inputs(
    request: EvaluationRequest,
    *,
    adapter_version: str,
    engine_version: str | None,
    native_config: Mapping[str, Any],
    resolved_facts: Mapping[str, Any],
    identity_facts: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the canonical scientific inputs to the measurement.

    Operational context (paths, credentials, worker interpreter, timeout) is
    intentionally absent. MAGNET metric selection/evidence policy is also absent.

    ``resolved_facts`` is informational and may contain machine-specific paths;
    only ``engine_revision`` is taken from it. ``identity_facts`` is the explicit,
    path-free subset of resolution results (content digests, adapter source
    identity) that affects the measurement.
    """
    return normalize_json_object(
        {
            'identity_schema': 2,
            'engine': request.engine,
            'adapter_version': adapter_version,
            'engine_version': engine_version,
            'engine_revision': resolved_facts.get('engine_revision'),
            'request': request.to_dict(),
            'native_config': dict(native_config),
            'identity_facts': dict(identity_facts or {}),
        }
    )


def build_measurement_identity(
    request: EvaluationRequest,
    *,
    adapter_version: str,
    engine_version: str | None,
    native_config: Mapping[str, Any],
    resolved_facts: Mapping[str, Any],
    identity_facts: Mapping[str, Any] | None = None,
) -> MeasurementIdentity:
    inputs = measurement_inputs(
        request,
        adapter_version=adapter_version,
        engine_version=engine_version,
        native_config=native_config,
        resolved_facts=resolved_facts,
        identity_facts=identity_facts,
    )
    reasons = _unknown_identity_reasons(request, resolved_facts, identity_facts or {})
    return MeasurementIdentity(
        algorithm=IDENTITY_ALGORITHM,
        digest=sha256_json(inputs),
        reusable=not reasons,
        unknown_reasons=reasons,
    )
