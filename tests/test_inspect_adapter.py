import asyncio
from pathlib import Path

import pytest

from aiq_evals.backends.inspect_ai import adapter as inspect_adapter
from aiq_evals.backends.inspect_ai.adapter import InspectAIBackend
from aiq_evals.contracts import EvaluationRequest, ExecutionContext, ModelBinding
from aiq_evals.errors import ArtifactError, RequestValidationError
from aiq_evals.runner import import_evaluation


CALLS = []


def _score(name, scorer, metric, value, *, reducer='mean', group=None, n=4):
    return {
        'name': name,
        'scorer': scorer,
        'reducer': reducer,
        'scored_samples': n,
        'metrics': {
            metric: {
                'name': metric,
                'group': group,
                'value': value,
                'params': {},
            }
        },
    }


def make_log(task='task_a', *, status='success', model='mock/model-a'):
    error = None if status != 'error' else {'message': 'sample failure', 'traceback': 'tb'}
    return {
        'status': status,
        'eval': {
            'eval_id': f'eval-{task}',
            'task_id': f'task-id-{task}',
            'task': task,
            'task_version': 1,
            'task_args_passed': {'subset': 'tiny'},
            'model': model,
            'model_roles': {'grader': {'model': 'mock/grader'}},
            'packages': {'inspect_ai': '0.3.272'},
        },
        'plan': {'steps': [{'solver': 'agent'}]},
        'results': {
            'total_samples': 4,
            'completed_samples': 4 if status == 'success' else 2,
            'logged_samples': 4 if status == 'success' else 3,
            'scores': [
                _score('choice', 'judge', 'accuracy', 0.75, group='main'),
                _score('rationale', 'judge', 'accuracy', 0.50, group='aux'),
            ],
            'headline': {
                'scorer': 'judge',
                'score': 'choice',
                'metric': 'accuracy',
                'reducer': 'mean',
            },
            'metadata': {'source': 'fake'},
        },
        'stats': {
            'model_usage': {'mock/model-a': {'input_tokens': 10, 'output_tokens': 5}},
            'role_usage': {'grader': {'input_tokens': 3, 'output_tokens': 1}},
        },
        'samples': [
            {
                'id': 'sample-1',
                'uuid': 'uuid-1',
                'epoch': 2,
                'scores': {'judge': {'value': 1, 'answer': 'ok'}},
                'messages': [{'role': 'assistant', 'content': 'calling tool'}],
                'events': [
                    {
                        'event': 'tool',
                        'function': 'echo',
                        'arguments': {'text': 'hi'},
                        'result': 'hi',
                    }
                ],
                'timelines': [{'name': 'main'}],
                'model_usage': {'mock/model-a': {'input_tokens': 4, 'output_tokens': 2}},
                'role_usage': {'grader': {'input_tokens': 1, 'output_tokens': 1}},
                'metadata': {'row': 1},
                'output': {'completion': 'ok'},
                'error': None,
            }
        ],
        'reductions': [
            {
                'scorer': 'judge',
                'reducer': 'mean',
                'samples': [{'sample_id': 'sample-1', 'value': 0.5}],
            }
        ],
        'error': error,
        'location': f'file:///logs/{task}.eval',
    }


def fake_eval(**kwargs):
    CALLS.append(kwargs)
    log_dir = Path(kwargs['log_dir'])
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / 'task_a.eval').write_bytes(b'fake-inspect-log-a')
    (log_dir / 'task_b.eval').write_bytes(b'fake-inspect-log-b')
    return [make_log('task_a'), make_log('task_b')]


def fake_list_logs(path, recursive=True):
    del recursive
    return sorted(Path(path).glob('*.eval'))


def fake_read_log(path):
    name = Path(str(path)).stem
    if name == 'task_b':
        return make_log('task_b')
    return make_log('task_a')


def patch_runtime(monkeypatch, *, eval_fn=fake_eval, read_fn=fake_read_log, list_fn=fake_list_logs):
    monkeypatch.setattr(
        inspect_adapter,
        '_native_symbols',
        lambda: (object(), eval_fn, list_fn, read_fn),
    )
    monkeypatch.setattr(inspect_adapter, '_distribution_version', lambda module=None: '0.3.272')


def make_request(**kwargs):
    data = {
        'engine': 'inspect_ai',
        'task': 'suite.py@tiny_suite',
        'task_revision': 'task-rev',
        'data_revision': 'data-rev',
        'models': (
            ModelBinding(
                role='primary',
                model='model-a',
                provider='mock',
                revision='model-rev',
                provider_options={'timeout': 30},
            ),
            ModelBinding(
                role='grader',
                model='grader',
                provider='mock',
                revision='grader-rev',
            ),
        ),
        'task_options': {'subset': 'tiny'},
        'generation': {'temperature': 0.0, 'max_tokens': 128},
        'engine_options': {
            'log_format': 'eval',
            'eval_options': {'epochs': 2, 'turn_limit': 10},
        },
    }
    data.update(kwargs)
    return EvaluationRequest(**data)


def test_static_validation_and_native_mapping_do_not_need_inspect():
    backend = InspectAIBackend()
    backend.validate_request(make_request())
    config = inspect_adapter._merge_native_config(make_request())
    assert config['model'] == 'mock/model-a'
    assert config['model_roles'] == {'grader': 'mock/grader'}
    assert config['model_args'] == {'timeout': 30}
    assert config['eval_options']['temperature'] == 0.0
    assert config['eval_options']['epochs'] == 2
    assert config['eval_options']['log_samples'] is True

    with pytest.raises(RequestValidationError, match='owned by aiq-evals'):
        backend.validate_request(
            make_request(engine_options={'eval_options': {'model': 'other'}})
        )
    with pytest.raises(RequestValidationError, match='unknown inspect_ai engine_options'):
        backend.validate_request(make_request(engine_options={'wat': 1}))


def test_auxiliary_provider_options_are_rejected():
    models = list(make_request().models)
    models[1] = ModelBinding(
        role='grader',
        model='grader',
        provider='mock',
        revision='grader-rev',
        provider_options={'base_url': 'http://example.invalid'},
    )
    with pytest.raises(RequestValidationError, match='auxiliary model roles'):
        InspectAIBackend().validate_request(make_request(models=tuple(models)))


def test_resolve_python_factory_hashes_source(monkeypatch, tmp_path):
    patch_runtime(monkeypatch)
    module = tmp_path / 'my_inspect_task.py'
    module.write_text('def task_factory():\n    return object()\n')
    monkeypatch.syspath_prepend(str(tmp_path))
    request = make_request(
        task='python:my_inspect_task:task_factory',
        task_revision=None,
    )
    resolved = InspectAIBackend().resolve(request)
    assert resolved.engine_version == '0.3.272'
    assert resolved.resolved_facts['task_reference_kind'] == 'python_factory'
    assert len(resolved.resolved_facts['task_source_sha256']) == 64
    assert resolved.identity.reusable


def test_execute_multi_log_preserves_metric_identity_and_trajectories(monkeypatch, tmp_path):
    CALLS.clear()
    patch_runtime(monkeypatch)
    backend = InspectAIBackend()
    resolved = backend.resolve(make_request())
    result = asyncio.run(
        backend.execute(resolved, ExecutionContext(output_dir=tmp_path / 'work'))
    )
    assert result.status == 'succeeded'
    assert [record.task for record in result.records] == ['task_a', 'task_b']
    assert result.records[0].coverage.status == 'complete'
    metrics = result.records[0].metrics
    assert [(m.scorer, m.score, m.metric, m.group, m.reducer) for m in metrics] == [
        ('judge', 'choice', 'accuracy', 'main', 'mean'),
        ('judge', 'rationale', 'accuracy', 'aux', 'mean'),
    ]
    native_sample = next(sample for sample in result.samples if sample.epoch == 2)
    assert native_sample.trajectory['events'][0]['function'] == 'echo'
    reduction = next(sample for sample in result.samples if sample.epoch is None)
    assert reduction.native['kind'] == 'epoch_reduction'
    assert reduction.native['reducer'] == 'mean'

    call = CALLS[-1]
    assert call['tasks'] == 'suite.py@tiny_suite'
    assert call['model'] == 'mock/model-a'
    assert call['model_roles'] == {'grader': 'mock/grader'}
    assert call['task_args'] == {'subset': 'tiny'}
    assert call['temperature'] == 0.0
    assert call['turn_limit'] == 10
    assert call['display'] == 'none'


def test_native_error_cancelled_and_started_status_mapping(monkeypatch, tmp_path):
    patch_runtime(monkeypatch)
    resolved = InspectAIBackend().resolve(make_request())
    backend = InspectAIBackend()

    for native_status, expected in [
        ('error', 'failed'),
        ('cancelled', 'cancelled'),
        ('started', 'incomplete'),
    ]:
        def status_eval(**kwargs):
            del kwargs
            return [make_log(status=native_status)]

        monkeypatch.setattr(
            inspect_adapter,
            '_native_symbols',
            lambda fn=status_eval: (object(), fn, fake_list_logs, fake_read_log),
        )
        result = asyncio.run(
            backend.execute(resolved, ExecutionContext(output_dir=tmp_path / native_status))
        )
        assert result.status == expected
        assert result.records[0].native_status == native_status


def test_execution_exception_recovers_native_error_log(monkeypatch, tmp_path):
    error_log = make_log(status='error')

    def failing_eval(**kwargs):
        log_dir = Path(kwargs['log_dir'])
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / 'failed.eval').write_bytes(b'failed-log')
        raise RuntimeError('native inspect failure')

    def list_failed(path, recursive=True):
        del recursive
        return [Path(path) / 'failed.eval']

    patch_runtime(
        monkeypatch,
        eval_fn=failing_eval,
        list_fn=list_failed,
        read_fn=lambda path: error_log,
    )
    resolved = InspectAIBackend().resolve(make_request())
    result = asyncio.run(
        InspectAIBackend().execute(
            resolved,
            ExecutionContext(output_dir=tmp_path / 'work'),
        )
    )
    assert result.status == 'failed'
    assert result.records[0].error == 'sample failure'
    assert 'native inspect failure' in result.diagnostics['execution_error']
    assert 'RuntimeError' in result.diagnostics['traceback']


def test_import_directory_and_validate_native_model(monkeypatch, tmp_path):
    patch_runtime(monkeypatch)
    backend = InspectAIBackend()
    resolved = backend.resolve(make_request())
    source = tmp_path / 'native'
    source.mkdir()
    (source / 'task_a.eval').write_bytes(b'a')
    (source / 'task_b.eval').write_bytes(b'b')
    result = backend.import_results(
        resolved,
        str(source),
        ExecutionContext(output_dir=tmp_path / 'unused'),
    )
    assert result.status == 'succeeded'
    assert result.diagnostics['import_validation']['model_verified'] is True
    assert result.diagnostics['import_validation']['native_tasks'] == ['task_a', 'task_b']

    patch_runtime(
        monkeypatch,
        read_fn=lambda path: make_log(model='other/model'),
    )
    with pytest.raises(ArtifactError, match='model does not match'):
        backend.import_results(
            resolved,
            str(source),
            ExecutionContext(output_dir=tmp_path / 'unused2'),
        )


def test_import_single_native_file_is_preserved_in_bundle(monkeypatch, tmp_path):
    patch_runtime(monkeypatch, read_fn=lambda path: make_log('task_a'))
    resolved = InspectAIBackend().resolve(make_request())
    source = tmp_path / 'one.eval'
    source.write_bytes(b'native-inspect-log')
    bundle = import_evaluation(
        resolved,
        source,
        ExecutionContext(output_dir=tmp_path / 'bundle'),
    )
    assert bundle.complete
    assert (bundle.path / 'native' / 'one.eval').read_bytes() == b'native-inspect-log'


def test_metric_score_dimension_roundtrips_and_filters(tmp_path):
    from aiq_evals.artifacts import publish_run
    from aiq_evals.outputs import select_metrics

    request = make_request(models=(make_request().models[0],))
    identity = inspect_adapter.build_measurement_identity(
        request,
        adapter_version='test',
        engine_version='0.3.272',
        native_config={'test': True},
        resolved_facts={'engine_version': '0.3.272'},
    )
    from aiq_evals.contracts import (
        CoverageFacts,
        EvaluationResult,
        MetricRecord,
        ResolvedEvaluation,
        ResultRecord,
    )

    resolved = ResolvedEvaluation(
        request=request,
        adapter_version='test',
        engine_version='0.3.272',
        native_config={'test': True},
        identity=identity,
        resolved_facts={'engine_version': '0.3.272'},
    )
    rows = (
        MetricRecord(
            task='task_a', model_role='primary', metric='accuracy', value=1.0,
            scorer='judge', score='choice', group='main', reducer='mean',
        ),
        MetricRecord(
            task='task_a', model_role='primary', metric='accuracy', value=0.5,
            scorer='judge', score='rationale', group='aux', reducer='mean',
        ),
    )
    result = EvaluationResult(
        engine='inspect_ai',
        identity=identity,
        status='succeeded',
        records=(
            ResultRecord(
                task='task_a', model_role='primary', metrics=rows,
                coverage=CoverageFacts(status='complete', expected=1, processed=1),
            ),
        ),
    )
    bundle = publish_run(
        tmp_path / 'bundle',
        resolved=resolved,
        result=result,
        context=ExecutionContext(output_dir=tmp_path / 'bundle'),
    )
    selected = select_metrics(bundle, scorer='judge', score='rationale', group='aux')
    assert len(selected) == 1
    assert selected[0].value == 0.5
