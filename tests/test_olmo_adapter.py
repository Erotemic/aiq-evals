import asyncio
import json
from dataclasses import dataclass

import pytest

from aiq_evals.backends.olmo_eval import adapter as olmo_adapter
from aiq_evals.backends.olmo_eval.adapter import OlmoEvalBackend
from aiq_evals.contracts import EvaluationRequest, ExecutionContext, ModelBinding
from aiq_evals.errors import RequestValidationError
from aiq_evals.runner import run_evaluation_async


@dataclass
class FakeTaskConfig:
    limit: int | None = None


@dataclass
class FakeSamplingParams:
    temperature: float = 0.0
    top_p: float = 1.0


class FakeHarness:
    def __init__(self, data):
        self.data = data

    @classmethod
    def from_dict(cls, data):
        if 'provider' not in data or not data['provider'].get('model'):
            raise ValueError('provider model required')
        return cls(data)

    def to_dict(self):
        return dict(self.data)


class FakeRunner:
    validated = 0

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def validate(self):
        type(self).validated += 1

    async def run_async(self):
        return {
            'model': 'model-a',
            'tasks': {
                'tiny': {
                    'num_instances': 2,
                    'instances_saved': 2,
                    'instances_processed': 2,
                    'instances_failed': 0,
                    'metrics': {'accuracy': {'exact': 1.0}, 'loss': {'mean': 0.25}},
                    'primary_metric': 'accuracy:exact',
                    'config': {'limit': 2},
                    'predictions': [
                        {
                            'id': 's0',
                            'scores': {'exact': 1.0},
                            'outputs': [{'metadata': {'trajectory': {'steps': [{'tool': 'echo'}]}}}],
                        }
                    ],
                }
            },
            'summary': {'tiny': {'metric': 'accuracy:exact', 'score': 1.0}},
            'errors': [],
        }


class FailingRunner(FakeRunner):
    async def run_async(self):
        output = self.kwargs['output_dir']
        from pathlib import Path

        path = Path(output)
        path.mkdir(parents=True, exist_ok=True)
        (path / 'metrics.json').write_text(
            json.dumps(
                {
                    'tasks': [
                        {
                            'task': 'tiny',
                            'num_instances': 1,
                            'instances_saved': 1,
                            'instances_processed': 2,
                            'instances_failed': 1,
                            'metrics': {},
                            'error_summary': 'one hard failure',
                        }
                    ],
                    'errors': [{'task': 'tiny', 'error': 'hard failure budget exceeded'}],
                }
            )
        )
        raise RuntimeError('hard failure gate')


def fake_symbols(runner=FakeRunner):
    return FakeHarness, runner, FakeSamplingParams, FakeTaskConfig, lambda specs: list(specs)


def make_request(**kwargs):
    data = {
        'engine': 'olmo_eval',
        'task': 'tiny',
        'task_revision': 'task-rev',
        'data_revision': 'data-rev',
        'models': (
            ModelBinding(
                role='primary',
                model='model-a',
                provider='mock',
                revision='model-rev',
            ),
        ),
        'generation': {'temperature': 0.0},
        'task_options': {'limit': 2},
        'engine_options': {'upstream_revision': 'eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee'},
    }
    data.update(kwargs)
    return EvaluationRequest(**data)


def patch_runtime(monkeypatch, runner=FakeRunner):
    monkeypatch.setattr(olmo_adapter, '_native_symbols', lambda: fake_symbols(runner))
    monkeypatch.setattr(olmo_adapter, '_distribution_version', lambda: 'test-version')


def test_static_validation_does_not_need_native_runtime():
    backend = OlmoEvalBackend()
    backend.validate_request(make_request())
    with pytest.raises(RequestValidationError, match='unknown olmo_eval engine_options'):
        backend.validate_request(make_request(engine_options={'wat': 1}))


def test_resolve_and_execute_preserve_nested_metrics_and_trajectory(monkeypatch, tmp_path):
    patch_runtime(monkeypatch)
    backend = OlmoEvalBackend()
    resolved = backend.resolve(make_request())
    assert resolved.identity.reusable
    assert resolved.native_config['harness_config']['provider']['model'] == 'model-a'
    result = asyncio.run(
        backend.execute(resolved, ExecutionContext(output_dir=tmp_path / 'work'))
    )
    assert result.status == 'succeeded'
    assert FakeRunner.validated >= 1
    metrics = {(m.metric, m.scorer): m.value for m in result.records[0].metrics}
    assert metrics[('accuracy', 'exact')] == 1.0
    assert metrics[('loss', 'mean')] == 0.25
    assert result.records[0].coverage.status == 'complete'
    assert result.samples[0].trajectory['steps'][0]['tool'] == 'echo'


def test_conflicting_provider_is_rejected(monkeypatch):
    patch_runtime(monkeypatch)
    backend = OlmoEvalBackend()
    request = make_request(
        engine_options={
            'upstream_revision': 'eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
            'harness_config': {'provider': {'model': 'different-model'}},
        }
    )
    with pytest.raises(RequestValidationError, match='conflicting model'):
        backend.resolve(request)


def test_hard_failure_artifacts_never_become_success(monkeypatch, tmp_path):
    patch_runtime(monkeypatch, runner=FailingRunner)
    backend = OlmoEvalBackend()
    resolved = backend.resolve(make_request())
    result = asyncio.run(
        backend.execute(resolved, ExecutionContext(output_dir=tmp_path / 'work'))
    )
    assert result.status == 'failed'
    assert 'hard failure gate' in result.diagnostics['execution_error']
    assert result.records[0].coverage.status == 'partial'


def test_run_facade_publishes_success_only_after_adapter_returns(monkeypatch, tmp_path):
    patch_runtime(monkeypatch)
    resolved = OlmoEvalBackend().resolve(make_request())
    bundle = asyncio.run(
        run_evaluation_async(
            resolved,
            ExecutionContext(output_dir=tmp_path / 'bundle'),
        )
    )
    assert bundle.complete
    assert bundle.result.status == 'succeeded'
    assert bundle.resolved.identity.digest == resolved.identity.digest


def _write_native_metrics(root, payload):
    root.mkdir(parents=True, exist_ok=True)
    (root / 'metrics.json').write_text(json.dumps(payload) + '\n')


def test_import_native_artifact_validates_task_model_provider(monkeypatch, tmp_path):
    from aiq_evals.errors import ArtifactError

    patch_runtime(monkeypatch)
    backend = OlmoEvalBackend()
    resolved = backend.resolve(make_request())
    native = tmp_path / 'native-import'
    payload = {
        'model': 'model-a',
        'model_path': 'model-a',
        'provider': 'mock',
        'tasks': {
            'tiny': {
                'num_instances': 2,
                'instances_saved': 2,
                'instances_processed': 2,
                'instances_failed': 0,
                'metrics': {'accuracy': {'exact': 0.5}},
                'primary_metric': 'accuracy:exact',
                'config': {'limit': 2},
            }
        },
        'errors': [],
    }
    _write_native_metrics(native, payload)
    result = backend.import_results(
        resolved,
        str(native),
        ExecutionContext(output_dir=tmp_path / 'bundle'),
    )
    assert result.status == 'succeeded'
    assert result.diagnostics['import_validation']['model_path_verified'] is True
    assert result.diagnostics['import_validation']['present_tasks'] == ['tiny']

    payload['model_path'] = 'some-other-model'
    _write_native_metrics(native, payload)
    with pytest.raises(ArtifactError, match='model_path does not match'):
        backend.import_results(
            resolved,
            str(native),
            ExecutionContext(output_dir=tmp_path / 'bundle2'),
        )


def test_import_missing_resolved_task_is_incomplete(monkeypatch, tmp_path):
    patch_runtime(monkeypatch)
    backend = OlmoEvalBackend()
    resolved = backend.resolve(make_request())
    native = tmp_path / 'native-import'
    _write_native_metrics(
        native,
        {
            'model_path': 'model-a',
            'provider': 'mock',
            'tasks': {},
            'errors': [],
        },
    )
    result = backend.import_results(
        resolved,
        str(native),
        ExecutionContext(output_dir=tmp_path / 'bundle'),
    )
    assert result.status == 'incomplete'
    assert result.diagnostics['import_validation']['missing_tasks'] == ['tiny']


def test_top_level_native_task_error_is_not_success(monkeypatch, tmp_path):
    patch_runtime(monkeypatch)
    backend = OlmoEvalBackend()
    resolved = backend.resolve(make_request())
    native = tmp_path / 'native-import'
    _write_native_metrics(
        native,
        {
            'model_path': 'model-a',
            'provider': 'mock',
            'tasks': {
                'tiny': {
                    'num_instances': 0,
                    'instances_saved': 0,
                    'instances_processed': 0,
                    'instances_failed': 0,
                    'metrics': {},
                    'config': {},
                }
            },
            'errors': [{'task': 'tiny', 'error': 'task setup failed'}],
        },
    )
    result = backend.import_results(
        resolved,
        str(native),
        ExecutionContext(output_dir=tmp_path / 'bundle'),
    )
    assert result.status == 'failed'
    assert result.records[0].error == 'task setup failed'


class CancellingRunner(FakeRunner):
    cleaned = False

    async def run_async(self):
        try:
            await asyncio.Event().wait()
        finally:
            type(self).cleaned = True


def test_adapter_preserves_cancellation_for_runner_cleanup(monkeypatch, tmp_path):
    patch_runtime(monkeypatch, runner=CancellingRunner)
    CancellingRunner.cleaned = False
    backend = OlmoEvalBackend()
    resolved = backend.resolve(make_request())

    async def scenario():
        task = asyncio.create_task(
            backend.execute(resolved, ExecutionContext(output_dir=tmp_path / 'work'))
        )
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert CancellingRunner.cleaned is True
