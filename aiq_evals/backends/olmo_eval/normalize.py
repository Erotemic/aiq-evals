"""Normalization of OLMo Eval return values and native output artifacts."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from aiq_evals.contracts import (
    CoverageFacts,
    EvaluationResult,
    MeasurementIdentity,
    MetricRecord,
    ResultRecord,
    SampleRecord,
)
from aiq_evals.errors import ArtifactError


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        value = float(value)
        if value == value and value not in (float('inf'), float('-inf')):
            return value
    return None


def _metric_records(task: str, metrics: Any, *, denominator: int | None) -> tuple[MetricRecord, ...]:
    """Preserve OLMo's metric -> scorer nesting without silent flattening."""
    rows: list[MetricRecord] = []
    if not isinstance(metrics, Mapping):
        return ()
    for metric_name, scorer_values in metrics.items():
        if isinstance(scorer_values, Mapping):
            for scorer_name, raw in scorer_values.items():
                value = _numeric(raw)
                if value is None:
                    continue
                rows.append(
                    MetricRecord(
                        task=task,
                        model_role='primary',
                        metric=str(metric_name),
                        scorer=str(scorer_name),
                        value=value,
                        denominator=denominator,
                    )
                )
        else:
            value = _numeric(scorer_values)
            if value is not None:
                rows.append(
                    MetricRecord(
                        task=task,
                        model_role='primary',
                        metric=str(metric_name),
                        value=value,
                        denominator=denominator,
                    )
                )
    return tuple(rows)


def _coverage(task_data: Mapping[str, Any]) -> CoverageFacts:
    saved = task_data.get('instances_saved', task_data.get('num_instances'))
    processed = task_data.get('instances_processed')
    failed = task_data.get('instances_failed')
    saved_i = int(saved) if isinstance(saved, int) else None
    processed_i = int(processed) if isinstance(processed, int) else None
    failed_i = int(failed) if isinstance(failed, int) else None
    if processed_i is None:
        status = 'unknown'
    elif failed_i is not None and failed_i > 0:
        status = 'partial'
    elif saved_i is not None and saved_i == processed_i:
        status = 'complete'
    elif saved_i is not None and saved_i < processed_i:
        status = 'partial'
    else:
        status = 'unknown'
    return CoverageFacts(
        status=status,
        expected=processed_i,
        processed=processed_i,
        saved=saved_i,
        failed=failed_i,
    )


def _task_items(data: Mapping[str, Any]) -> Iterable[tuple[str, Mapping[str, Any]]]:
    """Accept both AsyncEvalRunner return dicts and serialized metrics.json."""
    tasks = data.get('tasks', {})
    if isinstance(tasks, Mapping):
        for task, task_data in tasks.items():
            if isinstance(task_data, Mapping):
                yield str(task), task_data
        return
    if isinstance(tasks, list):
        for row in tasks:
            if isinstance(row, Mapping) and row.get('task') is not None:
                yield str(row['task']), row


def _native_errors_by_task(data: Mapping[str, Any]) -> dict[str, str]:
    mapped: dict[str, str] = {}
    errors = data.get('errors')
    if not isinstance(errors, list):
        return mapped
    for row in errors:
        if not isinstance(row, Mapping) or row.get('task') is None:
            continue
        message = row.get('error', row.get('message'))
        if message is not None:
            mapped[str(row['task'])] = str(message)
    return mapped


def normalize_olmo_results(
    data: Mapping[str, Any],
    *,
    identity: MeasurementIdentity,
    status: str = 'succeeded',
    failure: str | None = None,
) -> EvaluationResult:
    records: list[ResultRecord] = []
    samples: list[SampleRecord] = []
    error_by_task = _native_errors_by_task(data)
    for task, task_data in _task_items(data):
        coverage = _coverage(task_data)
        error = (
            task_data.get('error')
            or task_data.get('error_summary')
            or error_by_task.get(task)
        )
        metrics = _metric_records(task, task_data.get('metrics', {}), denominator=coverage.saved)
        native_status = 'failed' if error else 'succeeded'
        records.append(
            ResultRecord(
                task=task,
                model_role='primary',
                metrics=metrics,
                coverage=coverage,
                primary_metric=(
                    None if task_data.get('primary_metric') is None else str(task_data['primary_metric'])
                ),
                native_status=native_status,
                error=None if error is None else str(error),
                native_config=dict(task_data.get('config') or {}),
            )
        )
        predictions = task_data.get('predictions')
        if isinstance(predictions, list):
            samples.extend(_prediction_samples(task, predictions))

    errors = data.get('errors')
    diagnostics: dict[str, Any] = {
        'native_errors': errors if isinstance(errors, list) else [],
        'native_summary': data.get('summary') if isinstance(data.get('summary'), Mapping) else {},
        'native_model': data.get('model'),
        'native_model_path': data.get('model_path'),
        'native_provider': data.get('provider'),
        'native_suite_names': sorted(str(key) for key in data.get('suites', {}))
        if isinstance(data.get('suites'), Mapping)
        else [],
    }
    if failure:
        diagnostics['execution_error'] = failure
    normalized_status = status
    if normalized_status == 'succeeded' and any(record.error for record in records):
        normalized_status = 'failed'
    elif normalized_status == 'succeeded' and not records:
        normalized_status = 'incomplete'
    return EvaluationResult(
        engine='olmo_eval',
        identity=identity,
        status=normalized_status,  # type: ignore[arg-type]
        records=tuple(records),
        samples=tuple(samples),
        diagnostics=diagnostics,
    )


def _sample_id(prediction: Mapping[str, Any], index: int) -> str:
    for key in ('sample_id', 'instance_id', 'id', 'index', 'doc_id'):
        value = prediction.get(key)
        if value is not None:
            return str(value)
    instance = prediction.get('instance')
    if isinstance(instance, Mapping):
        for key in ('id', 'sample_id', 'index', 'doc_id'):
            value = instance.get(key)
            if value is not None:
                return str(value)
    return str(index)


def _extract_trajectory(prediction: Mapping[str, Any]) -> Any:
    direct = prediction.get('trajectory')
    if direct is not None:
        return direct
    outputs = prediction.get('outputs')
    if isinstance(outputs, list) and outputs:
        first = outputs[0]
        if isinstance(first, Mapping):
            metadata = first.get('metadata')
            if isinstance(metadata, Mapping) and metadata.get('trajectory') is not None:
                return metadata['trajectory']
    response = prediction.get('response')
    if isinstance(response, Mapping) and response.get('trajectory') is not None:
        return response['trajectory']
    return None


def _prediction_samples(task: str, predictions: list[Any]) -> list[SampleRecord]:
    samples: list[SampleRecord] = []
    for index, raw in enumerate(predictions):
        if not isinstance(raw, Mapping):
            continue
        scores = raw.get('scores')
        if not isinstance(scores, Mapping):
            scores = {}
        usage = raw.get('usage')
        if not isinstance(usage, Mapping):
            usage = {}
        samples.append(
            SampleRecord(
                task=task,
                model_role='primary',
                sample_id=_sample_id(raw, index),
                scores=dict(scores),
                trajectory=_extract_trajectory(raw),
                usage=dict(usage),
                native={
                    'request_trace': raw.get('request_trace'),
                    'error': raw.get('error'),
                },
            )
        )
    return samples


def load_jsonl(path: Path) -> list[Any]:
    rows = []
    for line_no, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as ex:
            raise ArtifactError(f'invalid JSONL at {path}:{line_no}: {ex}') from ex
    return rows


def attach_prediction_files(result: EvaluationResult, native_dir: Path) -> EvaluationResult:
    """Load native ``*-predictions.jsonl`` files and attach normalized samples."""
    existing = list(result.samples)
    seen = {(sample.task, sample.sample_id) for sample in existing}
    added: list[SampleRecord] = []
    for path in sorted(native_dir.rglob('*-predictions.jsonl')):
        filename = path.name[: -len('-predictions.jsonl')]
        rows = load_jsonl(path)
        # Native filenames may include model/task hashes. Use explicit task in
        # records when uniquely identifiable; otherwise retain filename identity.
        task = filename
        matching = [record.task for record in result.records if record.task in filename]
        if len(matching) == 1:
            task = matching[0]
        for sample in _prediction_samples(task, rows):
            key = (sample.task, sample.sample_id)
            if key not in seen:
                added.append(sample)
                seen.add(key)
    if not added:
        return result
    return EvaluationResult(
        engine=result.engine,
        identity=result.identity,
        status=result.status,
        records=result.records,
        samples=tuple(existing + added),
        artifacts=result.artifacts,
        diagnostics=result.diagnostics,
    )


def load_native_metrics(native_dir: str | Path) -> dict[str, Any]:
    root = Path(native_dir)
    metrics = root / 'metrics.json'
    if not metrics.is_file():
        candidates = list(root.rglob('metrics.json'))
        if len(candidates) == 1:
            metrics = candidates[0]
        elif not candidates:
            raise ArtifactError(f'no metrics.json found under {root}')
        else:
            raise ArtifactError(f'ambiguous metrics.json under {root}: {len(candidates)} candidates')
    try:
        data = json.loads(metrics.read_text())
    except json.JSONDecodeError as ex:
        raise ArtifactError(f'invalid OLMo metrics file {metrics}: {ex}') from ex
    if not isinstance(data, dict):
        raise ArtifactError(f'OLMo metrics file must contain a JSON object: {metrics}')
    return data
