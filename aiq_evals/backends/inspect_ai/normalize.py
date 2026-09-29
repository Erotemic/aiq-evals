"""Dependency-free normalization for Inspect ``EvalLog`` objects.

The functions in this module deliberately duck-type the public Inspect log
models. Importing or reading normalized :mod:`aiq_evals` results never imports
``inspect_ai``.
"""
from __future__ import annotations

import math
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence

from aiq_evals.contracts import (
    CoverageFacts,
    EvaluationResult,
    MeasurementIdentity,
    MetricRecord,
    ResultRecord,
    SampleRecord,
)
from aiq_evals.jsonutil import normalize_json


def _get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _jsonable(value: Any, *, _seen: set[int] | None = None) -> Any:
    """Convert native Pydantic/dataclass values into stable JSON-shaped data."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Enum):
        return _jsonable(value.value, _seen=_seen)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return {'encoding': 'hex', 'data': value.hex()}
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item, _seen=_seen) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_jsonable(item, _seen=_seen) for item in value]
    model_dump = getattr(value, 'model_dump', None)
    if callable(model_dump):
        try:
            return _jsonable(model_dump(mode='json'), _seen=_seen)
        except TypeError:
            return _jsonable(model_dump(), _seen=_seen)
    if is_dataclass(value):
        return _jsonable(asdict(value), _seen=_seen)

    if _seen is None:
        _seen = set()
    identity = id(value)
    if identity in _seen:
        return '<recursive-reference>'
    attrs = getattr(value, '__dict__', None)
    if isinstance(attrs, dict):
        _seen.add(identity)
        try:
            return {
                str(key): _jsonable(item, _seen=_seen)
                for key, item in attrs.items()
                if not str(key).startswith('_')
            }
        finally:
            _seen.remove(identity)
    return str(value)


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result >= 0 else None


def _error_text(log: Any) -> str | None:
    error = _get(log, 'error')
    if error is None:
        return None
    message = _get(error, 'message')
    return str(message if message is not None else error)


def _task_name(log: Any, fallback: str) -> str:
    eval_spec = _get(log, 'eval')
    task = _get(eval_spec, 'task')
    return str(task if task not in (None, '') else fallback)


def _coverage(log: Any) -> CoverageFacts:
    results = _get(log, 'results')
    if results is None:
        return CoverageFacts(status='unknown')
    expected = _int_or_none(_get(results, 'total_samples'))
    completed = _int_or_none(_get(results, 'completed_samples'))
    logged = _int_or_none(_get(results, 'logged_samples'))
    samples = _get(log, 'samples')
    sample_count = len(samples) if isinstance(samples, Sequence) else None

    processed = logged
    if processed is None:
        processed = sample_count
    if processed is None and str(_get(log, 'status', '')) == 'success':
        processed = expected
    if processed is None:
        processed = completed

    failed = None
    if processed is not None and completed is not None:
        failed = max(processed - completed, 0)

    if expected is None or processed is None:
        status = 'unknown'
    elif processed >= expected:
        status = 'complete'
    else:
        status = 'partial'
    return CoverageFacts(
        status=status,
        expected=expected,
        processed=processed,
        saved=processed,
        failed=failed,
    )


def _metric_records(log: Any, task: str) -> tuple[tuple[MetricRecord, ...], list[str]]:
    results = _get(log, 'results')
    scores = _get(results, 'scores', ()) if results is not None else ()
    rows: list[MetricRecord] = []
    warnings: list[str] = []
    for score in scores or ():
        scorer = _get(score, 'scorer')
        score_name = _get(score, 'name')
        reducer = _get(score, 'reducer')
        denominator = _int_or_none(_get(score, 'scored_samples'))
        metrics = _get(score, 'metrics', {}) or {}
        if not isinstance(metrics, Mapping):
            warnings.append(
                f'task {task!r} score {score_name!r} has non-mapping metrics; preserved only in native config'
            )
            continue
        for key, metric in metrics.items():
            raw_value = _get(metric, 'value')
            if (
                isinstance(raw_value, bool)
                or not isinstance(raw_value, (int, float))
                or not math.isfinite(float(raw_value))
            ):
                warnings.append(
                    f'task {task!r} scorer {scorer!r} metric {key!r} is not a finite scalar'
                )
                continue
            rows.append(
                MetricRecord(
                    task=task,
                    model_role='primary',
                    metric=str(key),
                    value=float(raw_value),
                    scorer=None if scorer is None else str(scorer),
                    score=None if score_name is None else str(score_name),
                    group=(
                        None
                        if _get(metric, 'group') is None
                        else str(_get(metric, 'group'))
                    ),
                    reducer=None if reducer is None else str(reducer),
                    denominator=denominator,
                )
            )
    return tuple(rows), warnings


def _primary_metric(log: Any, metrics: tuple[MetricRecord, ...]) -> str | None:
    results = _get(log, 'results')
    headline = _get(results, 'headline') if results is not None else None
    metric = _get(headline, 'metric') if headline is not None else None
    if metric:
        return str(metric)
    if len(metrics) == 1:
        return metrics[0].metric
    return None


def _sample_records(log: Any, task: str, location: str | None = None) -> list[SampleRecord]:
    eval_spec = _get(log, 'eval')
    eval_id = _get(eval_spec, 'eval_id')
    task_id = _get(eval_spec, 'task_id')
    if location is None:
        location = _get(log, 'location')
    out: list[SampleRecord] = []
    for sample in _get(log, 'samples', ()) or ():
        sample_id = _get(sample, 'id')
        if sample_id is None:
            sample_id = _get(sample, 'uuid')
        if sample_id is None:
            continue
        epoch = _int_or_none(_get(sample, 'epoch'))
        scores = _jsonable(_get(sample, 'scores') or {})
        if not isinstance(scores, Mapping):
            scores = {'value': scores}
        trajectory = {
            'messages': _jsonable(_get(sample, 'messages') or []),
            'events': _jsonable(_get(sample, 'events') or []),
            'timelines': _jsonable(_get(sample, 'timelines')),
        }
        usage = {
            'model_usage': _jsonable(_get(sample, 'model_usage') or {}),
            'role_usage': _jsonable(_get(sample, 'role_usage') or {}),
        }
        native = {
            'kind': 'sample',
            'uuid': _get(sample, 'uuid'),
            'error': _jsonable(_get(sample, 'error')),
            'output': _jsonable(_get(sample, 'output')),
            'metadata': _jsonable(_get(sample, 'metadata') or {}),
            'eval_id': eval_id,
            'task_id': task_id,
            'log_location': location,
        }
        out.append(
            SampleRecord(
                task=task,
                model_role='primary',
                sample_id=str(sample_id),
                epoch=epoch,
                scores=dict(scores),
                trajectory=trajectory,
                usage=usage,
                native=native,
            )
        )
    return out


def _reduction_records(log: Any, task: str) -> list[SampleRecord]:
    results = _get(log, 'results')
    reductions = _get(log, 'reductions')
    if reductions is None and results is not None:
        reductions = _get(results, 'sample_reductions')
    out: list[SampleRecord] = []
    for reduction in reductions or ():
        scorer = _get(reduction, 'scorer')
        reducer = _get(reduction, 'reducer')
        for sample_score in _get(reduction, 'samples', ()) or ():
            sample_id = _get(sample_score, 'sample_id')
            if sample_id is None:
                continue
            score_payload = _jsonable(sample_score)
            out.append(
                SampleRecord(
                    task=task,
                    model_role='primary',
                    sample_id=str(sample_id),
                    epoch=None,
                    scores={
                        str(scorer if scorer is not None else 'score'): score_payload
                    },
                    native={
                        'kind': 'epoch_reduction',
                        'scorer': scorer,
                        'reducer': reducer,
                    },
                )
            )
    return out


def _record_native_config(log: Any) -> dict[str, Any]:
    results = _get(log, 'results')
    return {
        'eval': _jsonable(_get(log, 'eval')),
        'plan': _jsonable(_get(log, 'plan')),
        'stats': _jsonable(_get(log, 'stats')),
        'results_metadata': _jsonable(_get(results, 'metadata')) if results is not None else None,
        'reductions': _jsonable(_get(log, 'reductions')),
    }


def _overall_status(logs: Sequence[Any]) -> str:
    native_statuses = [str(_get(log, 'status', 'started')) for log in logs]
    if any(status == 'error' for status in native_statuses):
        return 'failed'
    if any(status == 'cancelled' for status in native_statuses):
        return 'cancelled'
    if native_statuses and all(status == 'success' for status in native_statuses):
        return 'succeeded'
    return 'incomplete'


def normalize_inspect_logs(
    logs: Sequence[Any],
    *,
    identity: MeasurementIdentity,
    fallback_task: str,
    forced_status: str | None = None,
    failure: str | None = None,
    location_root: Path | None = None,
    location_prefix: str = 'native',
) -> EvaluationResult:
    """Normalize one or more public Inspect ``EvalLog`` objects."""
    records: list[ResultRecord] = []
    samples: list[SampleRecord] = []
    warnings: list[str] = []
    log_summaries: list[dict[str, Any]] = []
    for log in logs:
        location = _get(log, 'location')
        if location_root is not None and location:
            try:
                relative = Path(location).resolve().relative_to(location_root.resolve())
            except ValueError:
                pass
            else:
                location = str(Path(location_prefix) / relative)
        task = _task_name(log, fallback_task)
        metrics, metric_warnings = _metric_records(log, task)
        warnings.extend(metric_warnings)
        coverage = _coverage(log)
        native_status = str(_get(log, 'status', 'started'))
        records.append(
            ResultRecord(
                task=task,
                model_role='primary',
                metrics=metrics,
                coverage=coverage,
                primary_metric=_primary_metric(log, metrics),
                native_status=native_status,
                error=_error_text(log),
                native_config=_record_native_config(log),
            )
        )
        samples.extend(_sample_records(log, task, location))
        samples.extend(_reduction_records(log, task))
        eval_spec = _get(log, 'eval')
        log_summaries.append(
            {
                'task': task,
                'status': native_status,
                'location': location,
                'eval_id': _get(eval_spec, 'eval_id'),
                'task_id': _get(eval_spec, 'task_id'),
                'model': _get(eval_spec, 'model'),
            }
        )

    status = forced_status or _overall_status(logs)
    diagnostics: dict[str, Any] = {
        'native_logs': log_summaries,
        'normalization_warnings': warnings,
    }
    if failure is not None:
        diagnostics['execution_error'] = failure
    return EvaluationResult(
        engine='inspect_ai',
        identity=identity,
        status=status,  # type: ignore[arg-type]
        records=tuple(records),
        samples=tuple(samples),
        diagnostics=normalize_json(diagnostics),
    )


def native_log_model(log: Any) -> str | None:
    eval_spec = _get(log, 'eval')
    model = _get(eval_spec, 'model')
    return None if model is None else str(model)


def native_log_task_args(log: Any) -> Mapping[str, Any] | None:
    eval_spec = _get(log, 'eval')
    values = _get(eval_spec, 'task_args_passed')
    if values is None:
        values = _get(eval_spec, 'task_args')
    return values if isinstance(values, Mapping) else None


def native_log_task(log: Any) -> str | None:
    eval_spec = _get(log, 'eval')
    value = _get(eval_spec, 'task')
    return None if value is None else str(value)


def jsonable_native(value: Any) -> Any:
    """Public helper for adapter diagnostics/tests."""
    return normalize_json(_jsonable(value))
