"""Every packaged example request runs from the installed package (plan P8-03).

``examples/*.json`` use only ``magnet_evals.examples`` modules, never
``tests.native``, so they work from an installed wheel. Run this file in each
engine's environment; examples whose engine is not importable are skipped:

    <inspect-venv>/bin/python -m pytest -q tests/native/test_examples_native.py
    PYTHONPATH=$PWD <olmo-checkout>/.venv/bin/python -m pytest -q tests/native/test_examples_native.py
    <helm-venv>/bin/python -m pytest -q tests/native/test_examples_native.py
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from magnet_evals.contracts import EvaluationRequest
from magnet_evals.ensure import ensure_evaluation
from magnet_evals.examples.chat_server import chat_server
from magnet_evals.outputs import select_metrics
from magnet_evals.store import ResultStore

EXAMPLES = Path(__file__).resolve().parents[2] / 'examples'
ENGINE_MODULE = {'inspect_ai': 'inspect_ai', 'olmo_eval': 'olmo_eval', 'helm': 'helm'}
# Templates with placeholder tasks/models document the request shape only.
TEMPLATES = {'inspect_ai_request.json', 'olmo_eval_request.json'}
# (selector, expected value) for the claim-facing metric of each runnable example.
EXPECTED = {
    'helm_request.json': ({'metric': 'exact_match', 'group': 'test', 'score': None}, None),
    'inspect_generation_request.json': ({'scorer': 'match', 'metric': 'accuracy'}, 1.0),
    'inspect_tool_request.json': ({'scorer': 'match', 'metric': 'accuracy'}, 1.0),
    'inspect_local_sandbox_request.json': ({'scorer': 'match', 'metric': 'accuracy'}, 1.0),
    'inspect_docker_sandbox_request.json': ({'scorer': 'match', 'metric': 'accuracy'}, 1.0),
    'inspect_external_endpoint_request.json': ({'scorer': 'match', 'metric': 'accuracy'}, 1.0),
    'olmo_local_request.json': ({'metric': 'contains_42'}, 1.0),
    'olmo_agent_request.json': ({'metric': 'contains_42'}, 1.0),
}
RUNNABLE = sorted(p for p in EXAMPLES.glob('*.json') if p.name not in TEMPLATES)
# Opt-in: needs a Docker daemon usable by this user.
DOCKER_EXAMPLES = {'inspect_docker_sandbox_request.json'}


def _docker_usable() -> bool:
    return shutil.which('docker') is not None and subprocess.run(
        ['docker', 'info'], capture_output=True).returncode == 0


def test_every_runnable_example_has_an_expectation():
    assert {p.name for p in RUNNABLE} == set(EXPECTED)


def test_examples_do_not_depend_on_test_modules():
    for path in EXAMPLES.glob('*.json'):
        assert 'tests.' not in path.read_text(), path.name


@pytest.mark.parametrize('path', [
    pytest.param(p, marks=pytest.mark.docker_sandbox) if p.name in DOCKER_EXAMPLES else p
    for p in RUNNABLE
], ids=lambda p: p.name)
def test_example_runs_then_reuses(path, tmp_path, monkeypatch):
    data = json.loads(path.read_text())
    if importlib.util.find_spec(ENGINE_MODULE[data['engine']]) is None:
        pytest.skip(f"{data['engine']} is not installed in this environment")
    if path.name in DOCKER_EXAMPLES and not _docker_usable():
        pytest.skip('needs a Docker daemon usable by this user')
    if data['models'][0]['provider'] == 'openai' and importlib.util.find_spec('openai') is None:
        pytest.skip("Inspect's openai provider needs `openai`, outside the verified pin set")
    store = ResultStore(tmp_path / 'store')
    endpoint = 'base_url' in data['models'][0]['provider_options']
    with chat_server() as port:
        if endpoint:
            data['models'][0]['provider_options']['base_url'] = f'http://127.0.0.1:{port}/v1'
            monkeypatch.setenv('OPENAI_API_KEY', 'example-local-key')
        request = EvaluationRequest.from_dict(data)
        first = ensure_evaluation(request, store)
        second = ensure_evaluation(request, store)
    assert first.action == 'executed', first.run.result.diagnostics
    assert first.run.result.status == 'succeeded', first.run.result.diagnostics
    assert first.resolved.identity.reusable, first.resolved.identity.unknown_reasons
    assert second.action == 'reused' and second.run.path == first.run.path
    selector, expected = EXPECTED[path.name]
    # An explicit None requires the field to be unset (HELM's unperturbed statistic).
    metrics = [
        m for m in select_metrics(first.run, **{k: v for k, v in selector.items() if v is not None})
        if all(getattr(m, k) is None for k, v in selector.items() if v is None)
    ]
    assert len(metrics) == 1, [m.to_dict() for m in first.run.result.records[0].metrics]
    if expected is not None:
        assert metrics[0].value == expected
    if endpoint:
        for json_path in store.root.rglob('*.json'):
            assert 'example-local-key' not in json_path.read_text(errors='ignore')
