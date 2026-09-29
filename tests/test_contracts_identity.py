from dataclasses import replace

import pytest

from aiq_evals.contracts import EvaluationRequest, ModelBinding
from aiq_evals.errors import RequestValidationError
from aiq_evals.identity import build_measurement_identity


def make_request(**kwargs):
    data = {
        'engine': 'olmo_eval',
        'task': 'tiny',
        'task_revision': 'task-sha',
        'data_revision': 'data-sha',
        'models': (
            ModelBinding(
                role='primary',
                model='model-a',
                provider='mock',
                revision='model-sha',
            ),
        ),
        'generation': {'temperature': 0.0},
    }
    data.update(kwargs)
    return EvaluationRequest(**data)


def test_request_roundtrip_and_strict_fields():
    request = make_request()
    assert EvaluationRequest.from_dict(request.to_dict()) == request
    with pytest.raises(RequestValidationError, match='unknown evaluation request fields'):
        EvaluationRequest.from_dict({**request.to_dict(), 'wat': 1})


def test_request_rejects_secrets_and_non_json_values(tmp_path):
    with pytest.raises(RequestValidationError, match='credential-bearing'):
        make_request(engine_options={'api_key': 'nope'})
    with pytest.raises(RequestValidationError, match='Path'):
        make_request(task_options={'path': tmp_path})


def test_measurement_identity_is_stable_and_context_free():
    request = make_request()
    kwargs = {
        'adapter_version': '0.1',
        'engine_version': '1.2.3',
        'native_config': {'task_specs': ['tiny']},
        'resolved_facts': {'engine_version': '1.2.3', 'engine_revision': 'engine-sha'},
    }
    one = build_measurement_identity(request, **kwargs)
    two = build_measurement_identity(EvaluationRequest.from_dict(request.to_dict()), **kwargs)
    assert one == two
    assert one.reusable

    changed = build_measurement_identity(
        replace(request, generation={'temperature': 0.5}),
        **kwargs,
    )
    assert changed.digest != one.digest


def test_unknown_identity_disables_reuse():
    request = make_request(task_revision=None, data_revision=None)
    identity = build_measurement_identity(
        request,
        adapter_version='0.1',
        engine_version=None,
        native_config={},
        resolved_facts={},
    )
    assert not identity.reusable
    assert any('task revision' in reason for reason in identity.unknown_reasons)
    assert any('data revision' in reason for reason in identity.unknown_reasons)


def test_request_allows_required_secret_names_but_not_values():
    request = make_request(
        engine_options={
            'harness_config': {
                'required_secrets': ['SERPER_API_KEY'],
                'provider': {'required_secrets': ['OPENAI_API_KEY']},
            }
        }
    )
    assert request.engine_options['harness_config']['required_secrets'] == ['SERPER_API_KEY']
    with pytest.raises(RequestValidationError, match='credential-bearing'):
        make_request(engine_options={'harness_config': {'api_key': 'secret-value'}})
