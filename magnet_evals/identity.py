"""Measurement identity construction."""
from __future__ import annotations

import importlib.util
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from magnet_evals.contracts import EvaluationRequest, MeasurementIdentity
from magnet_evals.jsonutil import normalize_json_object, sha256_file, sha256_json

# v2: resolved content digests (``identity_facts``) and adapter source identity
# participate in the digest; v1 hashed neither.
# v3: operational request fields (endpoint URLs, required secret names) no
# longer participate; they change how a measurement is reached, not what it is.
IDENTITY_ALGORITHM = 'aiq-evals-measurement-v3+sha256'


def _without_path(value: Any, path: Sequence[str]) -> Any:
    """``value`` with the key at ``path`` removed (a deep copy along the path)."""
    if not path or not isinstance(value, Mapping) or path[0] not in value:
        return value
    head, rest = path[0], path[1:]
    copied = dict(value)
    if rest:
        copied[head] = _without_path(copied[head], rest)
    else:
        del copied[head]
    return copied


def identity_request(request: EvaluationRequest) -> dict[str, Any]:
    """The request as a measurement input, without its operational fields.

    ``engine_options.required_secrets`` names credentials the run needs, and a
    model binding's ``provider_options.base_url`` says where an endpoint is
    reached. Neither changes what is measured: the model's identity is its
    ``revision``/``cache_token``, which a reusable identity requires anyway.
    """
    data = _without_path(request.to_dict(), ('engine_options', 'required_secrets'))
    data['models'] = [
        _without_path(binding, ('provider_options', 'base_url')) for binding in data['models']
    ]
    return data


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
    operational_native_paths: Sequence[Sequence[str]] = (),
) -> dict[str, Any]:
    """Build the canonical scientific inputs to the measurement.

    Operational context (paths, credentials, worker interpreter, timeout) is
    intentionally absent. MAGNET metric selection/evidence policy is also absent.

    ``resolved_facts`` is informational and may contain machine-specific paths;
    only ``engine_revision`` is taken from it. ``identity_facts`` is the explicit,
    path-free subset of resolution results (content digests, adapter source
    identity) that affects the measurement. ``operational_native_paths`` names
    keys of ``native_config`` that carry operational request fields (e.g. an
    adapter's copy of the endpoint URL); they are left out like the request's.
    """
    for path in operational_native_paths:
        native_config = _without_path(native_config, tuple(path))
    return normalize_json_object(
        {
            'identity_schema': 3,
            'engine': request.engine,
            'adapter_version': adapter_version,
            'engine_version': engine_version,
            'engine_revision': resolved_facts.get('engine_revision'),
            'request': identity_request(request),
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
    operational_native_paths: Sequence[Sequence[str]] = (),
) -> MeasurementIdentity:
    inputs = measurement_inputs(
        request,
        adapter_version=adapter_version,
        engine_version=engine_version,
        native_config=native_config,
        resolved_facts=resolved_facts,
        identity_facts=identity_facts,
        operational_native_paths=operational_native_paths,
    )
    reasons = _unknown_identity_reasons(request, resolved_facts, identity_facts or {})
    return MeasurementIdentity(
        algorithm=IDENTITY_ALGORITHM,
        digest=sha256_json(inputs),
        reusable=not reasons,
        unknown_reasons=reasons,
    )
