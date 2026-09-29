"""Measurement identity construction."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from aiq_evals.contracts import EvaluationRequest, MeasurementIdentity
from aiq_evals.jsonutil import normalize_json, sha256_json

IDENTITY_ALGORITHM = 'aiq-evals-measurement-v1+sha256'


def _unknown_identity_reasons(request: EvaluationRequest, resolved_facts: Mapping[str, Any]) -> tuple[str, ...]:
    reasons: list[str] = []
    if not request.task_revision:
        reasons.append('task revision is unknown')
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
) -> dict[str, Any]:
    """Build the canonical scientific inputs to the measurement.

    Operational context (paths, credentials, worker interpreter, timeout) is
    intentionally absent. MAGNET metric selection/evidence policy is also absent.
    """
    return normalize_json(
        {
            'identity_schema': 1,
            'engine': request.engine,
            'adapter_version': adapter_version,
            'engine_version': engine_version,
            'engine_revision': resolved_facts.get('engine_revision'),
            'request': request.to_dict(),
            'native_config': dict(native_config),
        }
    )  # type: ignore[return-value]


def build_measurement_identity(
    request: EvaluationRequest,
    *,
    adapter_version: str,
    engine_version: str | None,
    native_config: Mapping[str, Any],
    resolved_facts: Mapping[str, Any],
) -> MeasurementIdentity:
    inputs = measurement_inputs(
        request,
        adapter_version=adapter_version,
        engine_version=engine_version,
        native_config=native_config,
        resolved_facts=resolved_facts,
    )
    reasons = _unknown_identity_reasons(request, resolved_facts)
    return MeasurementIdentity(
        algorithm=IDENTITY_ALGORITHM,
        digest=sha256_json(inputs),
        reusable=not reasons,
        unknown_reasons=reasons,
    )
