import asyncio

import pytest

from aiq_evals.backends.registry import (
    BackendRegistration,
    clear_backend_cache,
    register_backend,
    registrations,
)
from aiq_evals.contracts import EvaluationRequest, ModelBinding
from aiq_evals.ensure import ensure_evaluation, ensure_evaluation_async
from aiq_evals.store import ResultStore
from tests import fake_backend


@pytest.fixture(autouse=True)
def fake_engine():
    if 'fake' not in registrations():
        register_backend(BackendRegistration(key='fake', module='tests.fake_backend', factory='FakeBackend'))
    fake_backend.EXECUTIONS.clear()
    fake_backend.RESOLUTIONS.clear()
    yield
    clear_backend_cache()


def make_request(task='ok', **kwargs):
    data = {
        'engine': 'fake',
        'task': task,
        'task_revision': 'task-rev',
        'data_revision': 'data-rev',
        'models': (ModelBinding(role='primary', model='m', revision='model-rev'),),
    }
    data.update(kwargs)
    return EvaluationRequest(**data)


def test_executes_then_reuses(tmp_path):
    store = ResultStore(tmp_path / 'store')
    first = ensure_evaluation(make_request(), store)
    assert first.action == 'executed' and first.run.result.status == 'succeeded'
    assert first.run.path == store.run_path(first.resolved.identity.digest)
    second = ensure_evaluation(make_request(), store)
    assert second.reused and second.run.path == first.run.path
    assert fake_backend.EXECUTIONS['ok'] == 1


def test_measurement_change_invalidates_reuse(tmp_path):
    store = ResultStore(tmp_path / 'store')
    ensure_evaluation(make_request(), store)
    changed = ensure_evaluation(make_request(generation={'temperature': 0.5}), store)
    assert changed.action == 'executed'
    assert fake_backend.EXECUTIONS['ok'] == 2


def test_operational_context_does_not_change_identity(tmp_path):
    store = ResultStore(tmp_path / 'store')
    ensure_evaluation(make_request(), store, env={'API_KEY': 'secret-value-123'})
    again = ensure_evaluation(make_request(), store, env={'API_KEY': 'other-value-456'}, timeout_seconds=30)
    assert again.reused
    for path in (tmp_path / 'store').rglob('*.json'):
        assert 'secret-value-123' not in path.read_text()


def test_failures_never_become_canonical_and_do_not_block_success(tmp_path):
    store = ResultStore(tmp_path / 'store')
    outcomes = [ensure_evaluation(make_request('flaky'), store) for _ in range(3)]
    assert [o.run.result.status for o in outcomes] == ['failed', 'failed', 'succeeded']
    digest = outcomes[0].resolved.identity.digest
    # Lineage: three separate attempts; the canonical run holds one attempt's samples.
    assert [b.result.status for b in store.attempts(digest)] == ['failed', 'failed', 'succeeded']
    canonical = store.lookup(outcomes[0].resolved)
    assert canonical is not None and len(canonical.result.samples) == 1
    assert ensure_evaluation(make_request('flaky'), store).reused


def test_failed_run_is_inspectable_but_not_reused(tmp_path):
    store = ResultStore(tmp_path / 'store')
    failed = ensure_evaluation(make_request('fail'), store)
    assert failed.run.result.status == 'failed' and not failed.run.complete
    assert not store.run_path(failed.resolved.identity.digest).exists()
    assert ensure_evaluation(make_request('fail'), store).action == 'executed'


def test_non_reusable_identity_always_executes(tmp_path):
    store = ResultStore(tmp_path / 'store')
    one = ensure_evaluation(make_request('unknown'), store)
    two = ensure_evaluation(make_request('unknown'), store)
    assert one.action == two.action == 'executed'
    assert '_unkeyed' in str(one.run.path)
    assert 'mutable alias' in two.reuse_reason


def test_stale_or_tampered_canonical_is_rejected(tmp_path):
    store = ResultStore(tmp_path / 'store')
    first = ensure_evaluation(make_request(), store)
    (first.run.path / 'native' / 'log.txt').write_text('tampered\n')
    again = ensure_evaluation(make_request(), store)
    assert again.action == 'executed'
    assert 'checksum' in again.reuse_reason
    assert again.run.path == first.run.path and again.run.complete
    assert len(list((tmp_path / 'store' / 'quarantine').iterdir())) == 1


def test_import_then_reuse_and_changed_artifact_identity(tmp_path):
    store = ResultStore(tmp_path / 'store')
    source = tmp_path / 'native-a'
    source.mkdir()
    (source / 'value.txt').write_text('0.5\n')
    imported = ensure_evaluation(make_request('imp'), store, import_source=source)
    assert imported.action == 'imported' and imported.run.result.records[0].metrics[0].value == 0.5
    assert ensure_evaluation(make_request('imp'), store).reused
    other = tmp_path / 'native-b'
    other.mkdir()
    (other / 'value.txt').write_text('0.7\n')
    import_b = ensure_evaluation(
        make_request('imp'), ResultStore(tmp_path / 'store-b'), import_source=other
    )
    # Same measurement identity, different native content -> different normalized identity.
    assert import_b.resolved.identity == imported.resolved.identity
    assert (
        import_b.run.manifest['normalized_artifact_identity']
        != imported.run.manifest['normalized_artifact_identity']
    )


def test_concurrent_ensures_converge_on_one_canonical_run(tmp_path):
    store = ResultStore(tmp_path / 'store')

    async def both():
        return await asyncio.gather(
            ensure_evaluation_async(make_request(), store),
            ensure_evaluation_async(make_request(), store),
        )

    one, two = asyncio.run(both())
    assert one.run.path == two.run.path
    assert store.lookup(one.resolved) is not None


def test_declared_secret_inherited_from_environment_is_redacted(tmp_path, monkeypatch):
    monkeypatch.setenv('AIQ_DECLARED_TOKEN', 'inherited-secret-value')
    store = ResultStore(tmp_path / 'store')
    outcome = ensure_evaluation(
        make_request('leak', engine_options={'required_secrets': ['AIQ_DECLARED_TOKEN']}), store
    )
    assert outcome.run.result.diagnostics['native_error'] == '401 for token <redacted:AIQ_DECLARED_TOKEN>'
    for path in (tmp_path / 'store').rglob('*'):
        if path.is_file():
            assert 'inherited-secret-value' not in path.read_text(errors='ignore'), path


def test_secret_preflight_runs_before_resolution(tmp_path, monkeypatch):
    from aiq_evals.errors import RequestValidationError

    monkeypatch.delenv('AIQ_DECLARED_TOKEN', raising=False)
    request = make_request('ok', engine_options={'required_secrets': ['AIQ_DECLARED_TOKEN']})
    with pytest.raises(RequestValidationError, match='AIQ_DECLARED_TOKEN'):
        ensure_evaluation(request, ResultStore(tmp_path / 'store'))
    assert fake_backend.RESOLUTIONS['ok'] == 0


def test_in_process_timeout_is_enforced(tmp_path):
    outcome = ensure_evaluation(make_request('slow'), ResultStore(tmp_path / 'store'), timeout_seconds=0.01)
    assert outcome.run.result.status == 'failed'
    assert 'TimeoutError' in outcome.run.result.diagnostics['runner_error']


def test_run_and_import_resolve_through_the_worker_when_given(tmp_path, monkeypatch):
    from aiq_evals import runner
    from aiq_evals.contracts import ExecutionContext

    seen = []

    async def fake_resolve(request, context=None):
        seen.append(context.worker_python if context else None)
        return fake_backend.FakeBackend().resolve(request)

    async def fake_worker_import(resolved, source, context, secrets):
        seen.append(('import-worker', context.worker_python))
        return fake_backend.FakeBackend().import_results(resolved, source, context)

    async def fake_execute(resolved, context, work_dir):
        return await fake_backend.FakeBackend().execute(resolved, ExecutionContext(output_dir=work_dir))

    monkeypatch.setattr(runner, 'resolve_evaluation_async', fake_resolve)
    monkeypatch.setattr(runner, '_import_in_worker', fake_worker_import)
    monkeypatch.setattr(runner, '_execute_resolved', fake_execute)
    runner.run_evaluation(make_request(), ExecutionContext(output_dir=tmp_path / 'run', worker_python='/engine/python'))
    source = tmp_path / 'native'
    source.mkdir()
    (source / 'value.txt').write_text('0.5\n')
    runner.import_evaluation(
        make_request('imp'), source, ExecutionContext(output_dir=tmp_path / 'imp', worker_python='/engine/python')
    )
    assert seen == ['/engine/python', '/engine/python', ('import-worker', '/engine/python')]
