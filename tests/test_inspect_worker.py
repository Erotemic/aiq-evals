import asyncio
from pathlib import Path

from aiq_evals.backends.inspect_ai import adapter as inspect_adapter
from aiq_evals.backends.inspect_ai.adapter import InspectAIBackend
from aiq_evals.contracts import EvaluationRequest, ExecutionContext, ModelBinding
from aiq_evals.runner import run_evaluation_async


def _request():
    return EvaluationRequest(
        engine='inspect_ai',
        task='tiny',
        task_revision='task-rev',
        data_revision='data-rev',
        models=(
            ModelBinding(
                role='primary',
                model='model-a',
                provider='mock',
                revision='model-rev',
            ),
        ),
    )


def _write_fake_inspect(root: Path):
    package = root / 'inspect_ai'
    package.mkdir(parents=True)
    (package / '__init__.py').write_text(
        """
from pathlib import Path
__version__ = '0.3.272'

def eval(**kwargs):
    log_dir = Path(kwargs['log_dir'])
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / 'tiny.eval').write_bytes(b'fake-native-inspect')
    return [{
        'status': 'success',
        'eval': {
            'eval_id': 'eval-1',
            'task_id': 'task-1',
            'task': 'tiny',
            'task_args_passed': {},
            'model': kwargs['model'],
        },
        'plan': {},
        'results': {
            'total_samples': 1,
            'completed_samples': 1,
            'logged_samples': 1,
            'scores': [{
                'name': 'answer',
                'scorer': 'exact',
                'reducer': None,
                'scored_samples': 1,
                'metrics': {'accuracy': {'name': 'accuracy', 'value': 1.0}},
            }],
        },
        'stats': {},
        'samples': [{
            'id': 's1',
            'epoch': 1,
            'scores': {'exact': {'value': 1}},
            'messages': [],
            'events': [],
            'model_usage': {},
            'role_usage': {},
        }],
        'reductions': None,
        'error': None,
        'location': str(log_dir / 'tiny.eval'),
    }]
"""
    )
    (package / 'log.py').write_text(
        """
from pathlib import Path

def list_eval_logs(path, recursive=True):
    return list(Path(path).glob('*.eval'))

def read_eval_log(path):
    raise AssertionError('success path should use logs returned by eval()')
"""
    )


def test_inspect_run_uses_owned_worker_process(monkeypatch, tmp_path):
    # Resolve in the test process with a fake API seam, then run through the real
    # worker protocol with an independently importable fake Inspect package.
    monkeypatch.setattr(
        inspect_adapter,
        '_native_symbols',
        lambda: (object(), lambda **kwargs: [], lambda path, recursive=True: [], lambda path: None),
    )
    monkeypatch.setattr(inspect_adapter, '_distribution_version', lambda module=None: '0.3.272')
    resolved = InspectAIBackend().resolve(_request())

    fake_runtime = tmp_path / 'fake-runtime'
    _write_fake_inspect(fake_runtime)
    bundle = asyncio.run(
        run_evaluation_async(
            resolved,
            ExecutionContext(
                output_dir=tmp_path / 'bundle',
                env={'PYTHONPATH': str(fake_runtime)},
            ),
        )
    )
    assert bundle.complete
    assert bundle.result.status == 'succeeded'
    assert bundle.result.records[0].metrics[0].value == 1.0
    assert (bundle.path / 'native' / 'inspect_ai' / 'logs' / 'tiny.eval').is_file()
