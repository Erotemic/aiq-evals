import sys

import pytest

from aiq_evals.backends.helm.adapter import HelmBackend, build_run_entry
from aiq_evals.backends.helm.normalize import normalize_helm_runs
from aiq_evals.contracts import EvaluationRequest, MeasurementIdentity, ModelBinding
from aiq_evals.errors import ArtifactError, RequestValidationError

IDENTITY = MeasurementIdentity(algorithm='t', digest='0' * 64, reusable=False)


def make_request(task='simple_mcqa', **kwargs):
    data = {
        'engine': 'helm',
        'task': task,
        'models': (ModelBinding(role='primary', model='simple/model1'),),
    }
    data.update(kwargs)
    return EvaluationRequest(**data)


def test_static_validation_does_not_import_helm():
    backend = HelmBackend()
    backend.validate_request(make_request(task_options={'max_eval_instances': 3}))
    assert 'helm' not in sys.modules


@pytest.mark.parametrize(
    'kwargs,match',
    [
        ({'task_options': {'limit': 1}}, 'unknown helm task_options'),
        ({'task_options': {'max_eval_instances': 0}}, 'positive integer'),
        ({'generation': {'temperature': 0.0}}, 'belong to the RunSpec'),
        ({'engine_options': {'suite': 'x'}}, 'unknown helm engine_options'),
        ({'engine_options': {'plugins': ['a/b.py']}}, 'module names'),
        ({'task': 'simple_mcqa:model=simple/model1'}, 'must not name model'),
        (
            {'models': (
                ModelBinding(role='primary', model='a'),
                ModelBinding(role='grader', model='b'),
            )},
            'exactly one',
        ),
    ],
)
def test_static_rejections(kwargs, match):
    with pytest.raises(RequestValidationError, match=match):
        HelmBackend().validate_request(make_request(**kwargs))


def test_run_entry_appends_bound_model():
    assert build_run_entry(make_request()) == 'simple_mcqa:model=simple/model1'
    assert build_run_entry(make_request(task='mmlu:subject=philosophy')) == (
        'mmlu:subject=philosophy,model=simple/model1'
    )


def test_run_dir_without_run_spec(tmp_path):
    run = tmp_path / 'aiq_p5_fail:model=simple_model1'
    run.mkdir()
    with pytest.raises(ArtifactError, match='no run_spec.json'):
        normalize_helm_runs([run], identity=IDENTITY)
    result = normalize_helm_runs([run], identity=IDENTITY, forced_status='failed', expected_tasks=True)
    assert result.status == 'failed'
    assert result.records[0].task == run.name
    assert result.records[0].coverage.status == 'unknown'
