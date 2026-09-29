"""Dependency-light public result readers."""
from __future__ import annotations

from pathlib import Path

from aiq_evals.artifacts import RunBundle
from aiq_evals.contracts import ArtifactReference, MetricRecord, ResultRecord, SampleRecord


def load_run(path: str | Path, *, verify_checksums: bool = True) -> RunBundle:
    """Load a published run without importing any native evaluation engine."""
    return RunBundle.load(path, verify_checksums=verify_checksums)


def iter_metrics(run: RunBundle):
    for record in run.result.records:
        yield from record.metrics


def select_metrics(
    run: RunBundle,
    *,
    task: str | None = None,
    model_role: str | None = None,
    metric: str | None = None,
    scorer: str | None = None,
    score: str | None = None,
    group: str | None = None,
    reducer: str | None = None,
) -> list[MetricRecord]:
    rows = []
    for row in iter_metrics(run):
        if task is not None and row.task != task:
            continue
        if model_role is not None and row.model_role != model_role:
            continue
        if metric is not None and row.metric != metric:
            continue
        if scorer is not None and row.scorer != scorer:
            continue
        if score is not None and row.score != score:
            continue
        if group is not None and row.group != group:
            continue
        if reducer is not None and row.reducer != reducer:
            continue
        rows.append(row)
    return rows


def result_records(run: RunBundle) -> tuple[ResultRecord, ...]:
    return run.result.records


def sample_records(run: RunBundle) -> tuple[SampleRecord, ...]:
    return run.result.samples


def native_artifacts(run: RunBundle) -> tuple[ArtifactReference, ...]:
    return tuple(
        ArtifactReference.from_dict(row)
        for row in run.manifest.get('native_artifacts', [])
    )


def normalized_artifact_identity(run: RunBundle) -> str:
    value = run.manifest.get('normalized_artifact_identity')
    if not isinstance(value, str):
        raise ValueError('run manifest has no normalized artifact identity')
    return value
