"""Dependency-free normalization of native HELM run directories.

A HELM run directory (``benchmark_output/runs/<suite>/<run_spec.name>/``) holds
``run_spec.json``, ``scenario_state.json``, ``stats.json``, and
``per_instance_stats.json``. Reading them never imports ``helm``.

Mapping (the raw files remain authoritative and are retained):

* each ``stats.json`` entry -> one :class:`MetricRecord`, with ``metric`` =
  ``name.name``, ``value`` = ``mean``, ``reducer`` = ``'mean'``, ``group`` =
  split (``split/sub_split`` when present), and ``score`` = a canonical
  perturbation descriptor when present. ``denominator`` stays unset: HELM's
  aggregate ``count`` counts aggregated train-trial means (e.g. 1 for a
  9-instance MMLU run), not samples;
* each ``per_instance_stats.json`` row -> one :class:`SampleRecord` with
  ``sample_id`` = ``instance_id`` and ``epoch`` = ``train_trial_index + 1``
  (HELM train trials are repetitions with different in-context examples);
* coverage: expected = distinct ``(instance_id, train_trial_index)`` pairs among
  ``scenario_state`` requests; processed = the same pairs among per-instance
  stats. Either file missing leaves coverage unknown rather than inferred.
"""
from __future__ import annotations

import json
import math
import os
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
from aiq_evals.errors import ArtifactError
from aiq_evals.jsonutil import normalize_json

RUN_SPEC = 'run_spec.json'
STATS = 'stats.json'
PER_INSTANCE_STATS = 'per_instance_stats.json'
SCENARIO_STATE = 'scenario_state.json'


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as ex:
        raise ArtifactError(f'invalid HELM JSON at {path}: {ex}') from ex


def _perturbation_key(perturbation: Mapping[str, Any] | None) -> str | None:
    if not perturbation:
        return None
    parts = [f'{key}={perturbation[key]}' for key in sorted(perturbation) if key != 'name']
    return f"perturbation:{perturbation.get('name')}" + (f"[{','.join(parts)}]" if parts else '')


def _stat_group(name: Mapping[str, Any]) -> str | None:
    split = name.get('split')
    sub_split = name.get('sub_split')
    if split is None:
        return None
    return f'{split}/{sub_split}' if sub_split else str(split)


def _stat_key(name: Mapping[str, Any]) -> str:
    """Stable per-sample score key: metric plus its split/perturbation qualifiers."""
    key = str(name.get('name'))
    group = _stat_group(name)
    if group:
        key += f'@{group}'
    perturbation = _perturbation_key(name.get('perturbation'))
    if perturbation:
        key += f'#{perturbation}'
    return key


def _metric_records(task: str, stats: Sequence[Mapping[str, Any]]) -> tuple[MetricRecord, ...]:
    records = []
    for stat in stats:
        name = stat.get('name') or {}
        mean = stat.get('mean')
        if isinstance(mean, bool) or not isinstance(mean, (int, float)) or not math.isfinite(mean):
            # HELM omits mean for empty stats; record nothing rather than a 0.
            continue
        records.append(
            MetricRecord(
                task=task,
                model_role='primary',
                metric=str(name.get('name')),
                value=float(mean),
                reducer='mean',
                group=_stat_group(name),
                score=_perturbation_key(name.get('perturbation')),
            )
        )
    return tuple(records)


def _request_state_trajectories(scenario_state: Mapping[str, Any]) -> dict[tuple[str, int], Any]:
    found: dict[tuple[str, int], Any] = {}
    for state in scenario_state.get('request_states') or []:
        instance = state.get('instance') or {}
        key = (str(instance.get('id')), int(state.get('train_trial_index') or 0))
        request = state.get('request') or {}
        result = state.get('result') or {}
        found[key] = {
            'prompt': request.get('prompt'),
            'model': request.get('model'),
            'completions': [
                completion.get('text') for completion in result.get('completions') or []
            ],
            'success': result.get('success'),
            'error': result.get('error'),
        }
    return found


def _usage(stats: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    usage = {}
    for stat in stats:
        name = (stat.get('name') or {}).get('name')
        if name in {'num_prompt_tokens', 'num_completion_tokens', 'num_output_tokens'}:
            usage[str(name)] = stat.get('sum')
    return usage


def _unstarted_record(task: str, run_dir: Path) -> tuple[ResultRecord, list[SampleRecord], dict[str, Any]]:
    present = {name: (run_dir / name).is_file() for name in (RUN_SPEC, STATS, PER_INSTANCE_STATS, SCENARIO_STATE)}
    record = ResultRecord(
        task=task,
        model_role='primary',
        metrics=(),
        coverage=CoverageFacts(status='unknown'),
        native_status='incomplete',
        error=f'{RUN_SPEC} is missing',
        native_config={'files_present': present},
    )
    return record, [], {'task': task, 'location': run_dir.name, 'model': None, 'files_present': present}


def normalize_run_dir(
    run_dir: Path, *, expected_task: str | None = None
) -> tuple[ResultRecord, list[SampleRecord], dict[str, Any]]:
    """Normalize one native HELM run directory.

    ``expected_task`` is given only by execution, which knows the resolved run
    spec name; a directory HELM created but abandoned before writing
    ``run_spec.json`` then becomes an explicit incomplete record. Imports have no
    such knowledge and reject the directory.
    """
    run_spec_path = run_dir / RUN_SPEC
    if not run_spec_path.is_file():
        if expected_task is not None:
            return _unstarted_record(expected_task, run_dir)
        raise ArtifactError(f'HELM run directory has no {RUN_SPEC}: {run_dir}')
    run_spec = _load(run_spec_path)
    task = str(run_spec.get('name') or run_dir.name)
    present = {name: (run_dir / name).is_file() for name in (STATS, PER_INSTANCE_STATS, SCENARIO_STATE)}

    stats = _load(run_dir / STATS) if present[STATS] else []
    per_instance = _load(run_dir / PER_INSTANCE_STATS) if present[PER_INSTANCE_STATS] else None
    scenario_state = _load(run_dir / SCENARIO_STATE) if present[SCENARIO_STATE] else None

    expected = None
    trajectories: dict[tuple[str, int], Any] = {}
    if scenario_state is not None:
        trajectories = _request_state_trajectories(scenario_state)
        expected = len(trajectories)
    processed = None
    samples: list[SampleRecord] = []
    if per_instance is not None:
        pairs = set()
        for row in per_instance:
            instance_id = str(row.get('instance_id'))
            trial = int(row.get('train_trial_index') or 0)
            pairs.add((instance_id, trial))
            row_stats = row.get('stats') or []
            samples.append(
                SampleRecord(
                    task=task,
                    model_role='primary',
                    sample_id=instance_id,
                    epoch=trial + 1,
                    scores={
                        _stat_key(stat.get('name') or {}): stat.get('mean')
                        for stat in row_stats
                    },
                    trajectory=trajectories.get((instance_id, trial)),
                    usage=_usage(row_stats),
                    native={
                        'kind': 'sample',
                        'train_trial_index': trial,
                        'perturbation': row.get('perturbation'),
                    },
                )
            )
        processed = len(pairs)

    if not present[STATS]:
        native_status = 'incomplete'
    else:
        native_status = 'complete'
    if expected is None or processed is None:
        coverage = CoverageFacts(status='unknown', expected=expected, processed=processed, saved=processed)
    else:
        coverage = CoverageFacts(
            status='complete' if processed >= expected else 'partial',
            expected=expected,
            processed=processed,
            saved=processed,
            failed=max(expected - processed, 0),
        )
    adapter_spec = run_spec.get('adapter_spec') or {}
    record = ResultRecord(
        task=task,
        model_role='primary',
        metrics=_metric_records(task, stats),
        coverage=coverage,
        native_status=native_status,
        error=None if present[STATS] else f'{STATS} is missing',
        native_config=normalize_json(
            {
                'run_spec_name': run_spec.get('name'),
                'scenario_spec': run_spec.get('scenario_spec'),
                'adapter_spec': adapter_spec,
                'metric_specs': run_spec.get('metric_specs'),
                'groups': run_spec.get('groups'),
                'files_present': present,
            }
        ),
    )
    summary = {
        'task': task,
        'location': run_dir.name,
        'model': adapter_spec.get('model'),
        'model_deployment': adapter_spec.get('model_deployment'),
        'files_present': present,
    }
    return record, samples, summary


def find_run_dirs(root: Path) -> list[Path]:
    """Run directories (those holding ``run_spec.json``) at or below ``root``."""
    root = Path(root)
    if (root / RUN_SPEC).is_file():
        return [root]
    # Follow directory symlinks: MAGNET materializes reused runs as symlinks,
    # which Path.rglob does not traverse before Python 3.13.
    found = []
    for dirpath, _dirnames, filenames in os.walk(root, followlinks=True):
        if RUN_SPEC in filenames:
            found.append(Path(dirpath))
    return sorted(found)


def normalize_helm_runs(
    run_dirs: Sequence[Path],
    *,
    identity: MeasurementIdentity,
    forced_status: str | None = None,
    failure: str | None = None,
    expected_tasks: bool = False,
) -> EvaluationResult:
    records: list[ResultRecord] = []
    samples: list[SampleRecord] = []
    summaries: list[dict[str, Any]] = []
    for run_dir in run_dirs:
        run_dir = Path(run_dir)
        record, run_samples, summary = normalize_run_dir(
            run_dir, expected_task=run_dir.name if expected_tasks else None
        )
        records.append(record)
        samples.extend(run_samples)
        summaries.append(summary)
    if forced_status is not None:
        status = forced_status
    elif records and all(record.native_status == 'complete' for record in records):
        status = 'succeeded'
    else:
        status = 'incomplete'
    diagnostics: dict[str, Any] = {'native_runs': summaries}
    if failure is not None:
        diagnostics['execution_error'] = failure
    return EvaluationResult(
        engine='helm',
        identity=identity,
        status=status,  # type: ignore[arg-type]
        records=tuple(records),
        samples=tuple(samples),
        diagnostics=normalize_json(diagnostics),
    )
