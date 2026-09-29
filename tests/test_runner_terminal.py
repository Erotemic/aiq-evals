import asyncio

import pytest

from magnet_evals import runner as runner_mod
from magnet_evals.artifacts import ATTEMPT_TERMINAL, RUN_COMPLETE, RunBundle
from magnet_evals.contracts import (
    EvaluationRequest,
    ExecutionContext,
    MeasurementIdentity,
    ModelBinding,
    ResolvedEvaluation,
)
from magnet_evals.errors import ExecutionError


def make_resolved():
    request = EvaluationRequest(
        engine='olmo_eval',
        task='tiny',
        task_revision='task-rev',
        data_revision='data-rev',
        models=(ModelBinding(role='primary', model='m', revision='model-rev'),),
    )
    return ResolvedEvaluation(
        request=request,
        adapter_version='test-adapter',
        engine_version='test-engine',
        native_config={},
        identity=MeasurementIdentity(
            algorithm='test',
            digest='b' * 64,
            reusable=True,
        ),
        resolved_facts={},
    )


def test_execution_error_publishes_failed_terminal_bundle(monkeypatch, tmp_path):
    resolved = make_resolved()

    async def fail(*args, **kwargs):
        raise ExecutionError('worker failed with TOKEN-VALUE')

    monkeypatch.setattr(runner_mod, '_execute_resolved', fail)
    destination = tmp_path / 'failed-run'
    bundle = asyncio.run(
        runner_mod.run_evaluation_async(
            resolved,
            ExecutionContext(output_dir=destination, env={'TOKEN': 'TOKEN-VALUE'}),
        )
    )
    assert bundle.result.status == 'failed'
    assert (destination / ATTEMPT_TERMINAL).is_file()
    assert not (destination / RUN_COMPLETE).exists()
    assert 'TOKEN-VALUE' not in (destination / 'results.json').read_text()
    assert '<redacted:TOKEN>' in bundle.result.diagnostics['runner_error']


def test_adapter_diagnostics_quoting_a_secret_are_redacted(monkeypatch, tmp_path):
    from magnet_evals.contracts import EvaluationResult

    resolved = make_resolved()

    async def failed_result(*args, **kwargs):
        # Mirrors adapters that retain native exception text and tracebacks.
        return EvaluationResult(
            engine='olmo_eval',
            identity=resolved.identity,
            status='failed',
            records=(),
            diagnostics={
                'execution_error': 'HTTP 401 for key sk-SECRET-123',
                'traceback': ['frame', {'sk-SECRET-123': 'header Bearer sk-SECRET-123'}],
            },
        )

    monkeypatch.setattr(runner_mod, '_execute_resolved', failed_result)
    destination = tmp_path / 'failed-run'
    bundle = asyncio.run(
        runner_mod.run_evaluation_async(
            resolved,
            ExecutionContext(output_dir=destination, env={'API_KEY': 'sk-SECRET-123', 'FLAG': '1'}),
        )
    )
    # Short non-credential values must not corrupt structured data.
    assert bundle.result.identity == resolved.identity
    assert bundle.result.diagnostics['env_values_not_redacted_as_too_short'] == ['FLAG']
    assert bundle.result.status == 'failed'
    for path in destination.rglob('*.json'):
        assert 'sk-SECRET-123' not in path.read_text(), path
    assert bundle.result.diagnostics['execution_error'] == 'HTTP 401 for key <redacted:API_KEY>'


def test_cancellation_publishes_cancelled_attempt_and_propagates(monkeypatch, tmp_path):
    resolved = make_resolved()
    entered = asyncio.Event()

    async def block(*args, **kwargs):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(runner_mod, '_execute_resolved', block)
    destination = tmp_path / 'cancelled-run'

    async def scenario():
        task = asyncio.create_task(
            runner_mod.run_evaluation_async(
                resolved,
                ExecutionContext(output_dir=destination),
            )
        )
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    bundle = RunBundle.load(destination)
    assert bundle.result.status == 'cancelled'
    assert not bundle.complete
    assert (destination / ATTEMPT_TERMINAL).is_file()


def test_missing_required_secret_fails_before_execution(monkeypatch, tmp_path):
    from dataclasses import replace

    from magnet_evals.errors import RequestValidationError

    resolved = make_resolved()
    request = replace(
        resolved.request,
        engine_options={'harness_config': {'provider': {'required_secrets': ['AIQ_TEST_TOKEN']}}},
    )
    resolved = replace(resolved, request=request)
    started = []

    async def never(*args, **kwargs):
        started.append(True)

    monkeypatch.setattr(runner_mod, '_execute_resolved', never)
    monkeypatch.delenv('AIQ_TEST_TOKEN', raising=False)
    with pytest.raises(RequestValidationError, match='AIQ_TEST_TOKEN'):
        asyncio.run(runner_mod.run_evaluation_async(resolved, ExecutionContext(output_dir=tmp_path / 'r')))
    assert not started and not (tmp_path / 'r').exists()
    # Supplied through the context: the run proceeds.
    monkeypatch.setattr(runner_mod, '_execute_resolved', failing := _failing_execution())
    bundle = asyncio.run(
        runner_mod.run_evaluation_async(
            resolved, ExecutionContext(output_dir=tmp_path / 'ok', env={'AIQ_TEST_TOKEN': 'x' * 12})
        )
    )
    assert bundle.result.status == 'failed' and failing.calls == 1


def _failing_execution():
    async def run(*args, **kwargs):
        run.calls += 1
        raise ExecutionError('stub')

    run.calls = 0
    return run
