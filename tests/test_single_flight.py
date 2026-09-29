"""ADR-0011: single-flight acquisition and content-keyed imports."""
import asyncio
import json
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from magnet_evals.artifacts import native_source_identity
from magnet_evals.ensure import ensure_evaluation, ensure_evaluation_async
from magnet_evals.store import ResultStore
from tests import fake_backend
from tests.test_ensure import fake_engine, make_request  # noqa: F401  (autouse fixture)

REPO = Path(__file__).resolve().parents[1]


def _attempt_dirs(store, outcome):
    digest = outcome.resolved.identity.digest
    return sorted((store.root / 'attempts' / digest[:2] / digest).iterdir())


def test_concurrent_ensures_execute_once(tmp_path):
    store = ResultStore(tmp_path / 'store')

    async def many():
        return await asyncio.gather(*(ensure_evaluation_async(make_request('slow'), store) for _ in range(4)))

    outcomes = asyncio.run(many())
    assert sorted(o.action for o in outcomes) == ['executed', 'reused', 'reused', 'reused']
    assert fake_backend.EXECUTIONS['slow'] == 1
    assert len(_attempt_dirs(store, outcomes[0])) == 1
    assert len({o.run.path for o in outcomes}) == 1
    assert sum(o.waited for o in outcomes) == 3


def test_waiter_runs_its_own_attempt_when_the_holder_fails(tmp_path):
    store = ResultStore(tmp_path / 'store')

    async def both():
        return await asyncio.gather(
            ensure_evaluation_async(make_request('flaky'), store),
            ensure_evaluation_async(make_request('flaky'), store),
        )

    first, second = asyncio.run(both())
    # No shared failure: each caller made its own attempt, one after the other.
    assert [o.action for o in (first, second)] == ['executed', 'executed']
    assert fake_backend.EXECUTIONS['flaky'] == 2
    assert len(_attempt_dirs(store, first)) == 2


def test_different_measurements_do_not_serialize(tmp_path):
    store = ResultStore(tmp_path / 'store')

    async def both():
        start = time.monotonic()
        await asyncio.gather(
            ensure_evaluation_async(make_request('slow'), store),
            ensure_evaluation_async(make_request('slow', generation={'temperature': 0.5}), store),
        )
        return time.monotonic() - start

    assert asyncio.run(both()) < 0.9  # two 0.5 s executions overlapped
    assert fake_backend.EXECUTIONS['slow'] == 2


def test_waiting_for_the_lock_is_cancellable(tmp_path):
    store = ResultStore(tmp_path / 'store')
    resolved = fake_backend.FakeBackend().resolve(make_request('slow'))

    async def scenario():
        async with store.acquisition_lock(resolved.identity.digest):
            waiter = asyncio.create_task(ensure_evaluation_async(resolved, store))
            await asyncio.sleep(0.2)
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
        # Released: a later caller acquires immediately.
        async with store.acquisition_lock(resolved.identity.digest) as lock:
            assert not lock.waited

    asyncio.run(scenario())
    assert fake_backend.EXECUTIONS['slow'] == 0


_CHILD = textwrap.dedent('''
    import json, sys
    sys.path.insert(0, {repo!r})
    from magnet_evals.backends.registry import BackendRegistration, register_backend
    register_backend(BackendRegistration(key='fake', module='tests.fake_backend', factory='FakeBackend'))
    from magnet_evals.contracts import EvaluationRequest, ModelBinding
    from magnet_evals.ensure import ensure_evaluation
    request = EvaluationRequest(engine='fake', task='slow', task_revision='task-rev', data_revision='data-rev',
                                models=(ModelBinding(role='primary', model='m', revision='model-rev'),))
    outcome = ensure_evaluation(request, sys.argv[1])
    print(json.dumps({{'action': outcome.action, 'run': str(outcome.run.path)}}))
''')


def test_single_flight_spans_processes(tmp_path):
    script = tmp_path / 'child.py'
    script.write_text(_CHILD.format(repo=str(REPO)))
    store = tmp_path / 'store'
    procs = [
        subprocess.Popen([sys.executable, str(script), str(store)], stdout=subprocess.PIPE, text=True)
        for _ in range(3)
    ]
    results = [json.loads(p.communicate(timeout=60)[0]) for p in procs]
    assert sorted(r['action'] for r in results) == ['executed', 'reused', 'reused']
    assert len({r['run'] for r in results}) == 1
    assert len(list((store / 'attempts').rglob('ATTEMPT_TERMINAL'))) == 1


@pytest.mark.skipif(os.name != 'posix', reason='kernel-released flock is POSIX')
def test_lock_of_a_killed_holder_is_released(tmp_path):
    store = ResultStore(tmp_path / 'store')
    digest = 'ab' * 32
    holder = subprocess.Popen(
        [sys.executable, '-c', textwrap.dedent(f'''
            import asyncio, sys, time
            sys.path.insert(0, {str(REPO)!r})
            from magnet_evals.store import ResultStore
            async def main():
                async with ResultStore({str(store.root)!r}).acquisition_lock({digest!r}):
                    print('held', flush=True)
                    time.sleep(120)
            asyncio.run(main())
        ''')],
        stdout=subprocess.PIPE, text=True,
    )
    try:
        assert holder.stdout.readline().strip() == 'held'

        async def contend():
            task = asyncio.create_task(store.acquisition_lock(digest).__aenter__())
            await asyncio.sleep(0.3)
            assert not task.done()  # blocked by the live holder
            holder.send_signal(signal.SIGKILL)
            lock = await asyncio.wait_for(task, timeout=10)
            assert lock.waited

        asyncio.run(contend())
    finally:
        holder.kill()
        holder.wait()


# --- content-keyed imports ----------------------------------------------------

def _native(path, value):
    path.mkdir(parents=True, exist_ok=True)
    (path / 'value.txt').write_text(f'{value}\n')
    return path


def _value(outcome):
    return outcome.run.result.records[0].metrics[0].value


def test_different_native_content_is_imported_not_reused(tmp_path):
    store = ResultStore(tmp_path / 'store')
    a = ensure_evaluation(make_request('imp'), store, import_source=_native(tmp_path / 'a', 0.5))
    b = ensure_evaluation(make_request('imp'), store, import_source=_native(tmp_path / 'b', 0.7))
    assert (a.action, _value(a)) == ('imported', 0.5)
    assert (b.action, _value(b)) == ('imported', 0.7)
    assert a.resolved.identity == b.resolved.identity
    assert a.import_identity != b.import_identity
    # The same content again is reused, each from its own import slot.
    again_a = ensure_evaluation(make_request('imp'), store, import_source=tmp_path / 'a')
    again_b = ensure_evaluation(make_request('imp'), store, import_source=tmp_path / 'b')
    assert (again_a.action, _value(again_a)) == ('reused', 0.5)
    assert (again_b.action, _value(again_b)) == ('reused', 0.7)
    # Imports never become the canonical (executed) result (ADR-0012).
    plain = ensure_evaluation(make_request('imp'), store)
    assert (plain.action, _value(plain)) == ('executed', 1.0)


def test_editing_native_content_at_the_same_path_reimports(tmp_path):
    store = ResultStore(tmp_path / 'store')
    source = _native(tmp_path / 'native', 0.5)
    first = ensure_evaluation(make_request('imp'), store, import_source=source)
    _native(source, 0.7)
    second = ensure_evaluation(make_request('imp'), store, import_source=source)
    assert (second.action, _value(second)) == ('imported', 0.7)
    assert first.import_identity != second.import_identity
    assert first.run.path != second.run.path and first.run.path.is_dir()


def test_import_overrides_an_executed_canonical_run(tmp_path):
    store = ResultStore(tmp_path / 'store')
    executed = ensure_evaluation(make_request('imp'), store)
    imported = ensure_evaluation(make_request('imp'), store, import_source=_native(tmp_path / 'n', 0.25))
    assert executed.action == 'executed' and imported.action == 'imported'
    assert _value(imported) == 0.25
    assert ensure_evaluation(make_request('imp'), store).run.path == executed.run.path


def test_concurrent_imports_of_the_same_content_import_once(tmp_path):
    store = ResultStore(tmp_path / 'store')
    source = _native(tmp_path / 'n', 0.5)

    async def both():
        return await asyncio.gather(*(
            ensure_evaluation_async(make_request('imp'), store, import_source=source) for _ in range(3)
        ))

    outcomes = asyncio.run(both())
    assert sorted(o.action for o in outcomes) == ['imported', 'reused', 'reused']
    assert len({o.run.path for o in outcomes}) == 1


def test_tampered_import_slot_is_quarantined_and_reimported(tmp_path):
    store = ResultStore(tmp_path / 'store')
    source = _native(tmp_path / 'n', 0.5)
    first = ensure_evaluation(make_request('imp'), store, import_source=source)
    (first.run.path / 'native' / 'value.txt').write_text('0.9\n')
    again = ensure_evaluation(make_request('imp'), store, import_source=source)
    assert again.action == 'imported' and _value(again) == 0.5
    assert 'checksum' in again.reuse_reason
    assert any((store.root / 'quarantine').iterdir())


@pytest.mark.parametrize('kind', ['dir', 'file', 'nested-link'])
def test_source_identity_matches_the_published_inventory(tmp_path, kind):
    from magnet_evals.contracts import ExecutionContext
    from magnet_evals.runner import import_evaluation

    source = tmp_path / 'src'
    source.mkdir()
    (source / 'value.txt').write_text('0.5\n')
    (source / 'a-b.txt').write_text('x\n')           # '-' sorts before '/' as a string
    (source / 'a').mkdir()
    (source / 'a' / 'b.txt').write_text('y\n')
    (source / 'empty').mkdir()
    if kind == 'nested-link':
        (source / 'link.txt').symlink_to(source / 'a' / 'b.txt')
    target = source
    if kind == 'file':
        target = tmp_path / 'single.json'
        target.write_text('{}\n')
    expected = native_source_identity(target)
    if kind == 'file':
        # A single native file (e.g. one .eval log) is published as native/<name>;
        # the fake importer needs a directory, so publish the file directly.
        from magnet_evals.artifacts import publish_run

        resolved = fake_backend.FakeBackend().resolve(make_request('imp'))
        result = fake_backend.FakeBackend().import_results(resolved, source, None)
        bundle = publish_run(tmp_path / 'out', resolved=resolved, result=result,
                             context=ExecutionContext(output_dir=tmp_path / 'out'), native_dir=target)
    else:
        bundle = import_evaluation(make_request('imp'), target, ExecutionContext(output_dir=tmp_path / 'out'))
    assert bundle.manifest['native_artifact_identity'] == expected


def test_external_symlinks_in_an_import_source_are_refused_unless_allowed(tmp_path):
    from magnet_evals.errors import ArtifactError

    outside = tmp_path / 'outside.txt'
    outside.write_text('secret-ish\n')
    source = _native(tmp_path / 'n', 0.5)
    (source / 'link.txt').symlink_to(outside)
    with pytest.raises(ArtifactError, match='outside the source tree'):
        native_source_identity(source)
    assert native_source_identity(source, allow_external_symlinks=True) != native_source_identity(
        _native(tmp_path / 'plain', 0.5)
    )


# --- regressions from the integration review ------------------------------------

def test_cancelling_the_holder_during_promotion_does_not_execute_twice(tmp_path, monkeypatch):
    store = ResultStore(tmp_path / 'store')
    real_promote = ResultStore.promote

    def slow_promote(self, attempt):
        time.sleep(0.5)  # e.g. copying a large native tree
        return real_promote(self, attempt)

    monkeypatch.setattr(ResultStore, 'promote', slow_promote)

    async def scenario():
        first = asyncio.create_task(ensure_evaluation_async(make_request('ok'), store))
        await asyncio.sleep(0.05)
        waiter = asyncio.create_task(ensure_evaluation_async(make_request('ok'), store))
        await asyncio.sleep(0.2)  # the holder is inside the promotion thread
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        return await waiter

    outcome = asyncio.run(scenario())
    assert outcome.action == 'reused'
    assert fake_backend.EXECUTIONS['ok'] == 1


def test_concurrent_imports_of_different_content_all_succeed(tmp_path):
    # Distinct content means distinct import locks; seeding the shared
    # canonical run must still be race-free.
    for trial in range(10):
        store = ResultStore(tmp_path / f'store-{trial}')
        sources = [_native(tmp_path / f'n{trial}-{i}', 0.1 * (i + 1)) for i in range(4)]

        async def many():
            return await asyncio.gather(*(
                ensure_evaluation_async(make_request('imp'), store, import_source=s) for s in sources
            ))

        outcomes = asyncio.run(many())
        assert [o.action for o in outcomes] == ['imported'] * 4
        assert [round(_value(o), 1) for o in outcomes] == [0.1, 0.2, 0.3, 0.4]
        assert store.lookup(outcomes[0].resolved) is None  # imports are never canonical


def test_publication_race_on_one_path_resolves_to_the_winner(tmp_path):
    import threading

    from magnet_evals.contracts import ExecutionContext
    from magnet_evals.runner import import_evaluation

    for trial in range(20):
        store = ResultStore(tmp_path / f's{trial}')
        attempts = [
            import_evaluation(make_request('imp'), _native(tmp_path / f'src{trial}-{i}', 0.5 + i),
                              ExecutionContext(output_dir=tmp_path / f'a{trial}-{i}'))
            for i in range(2)
        ]
        errors, barrier = [], threading.Barrier(2)

        def seed(attempt):
            barrier.wait()
            try:
                store.promote(attempt)
            except Exception as ex:  # pragma: no cover - the regression
                errors.append(ex)

        threads = [threading.Thread(target=seed, args=(a,)) for a in attempts]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert not errors
        assert store.lookup(attempts[0].resolved) is not None


def test_a_failed_holder_note_does_not_leak_the_lock(tmp_path, monkeypatch):
    import magnet_evals.store as store_mod

    store = ResultStore(tmp_path / 'store')
    real_write = os.write
    calls = []

    def failing_write(fd, data):
        calls.append(fd)
        if len(calls) == 1:
            raise OSError(28, 'No space left on device')
        return real_write(fd, data)

    monkeypatch.setattr(store_mod.os, 'write', failing_write)
    digest = 'cd' * 32

    async def twice():
        async with store.acquisition_lock(digest):
            pass
        async with store.acquisition_lock(digest) as lock:
            return lock.waited

    assert asyncio.run(asyncio.wait_for(twice(), timeout=5)) is False
    assert not store_mod._HELD_LOCKS


def test_symlink_cycles_between_siblings_are_not_followed(tmp_path):
    source = _native(tmp_path / 'n', 0.5)
    (source / 'a').mkdir()
    (source / 'b').mkdir()
    (source / 'a' / 'x.txt').write_text('x\n')
    (source / 'a' / 'sib').symlink_to(source / 'b')
    (source / 'b' / 'back').symlink_to(source / 'a')
    identity = native_source_identity(source)
    outcome = ensure_evaluation(make_request('imp'), ResultStore(tmp_path / 'store'), import_source=source)
    assert outcome.run.manifest['native_artifact_identity'] == identity


def test_resolution_can_skip_the_secret_check(tmp_path, monkeypatch):
    from magnet_evals.contracts import ExecutionContext
    from magnet_evals.errors import RequestValidationError
    from magnet_evals.runner import resolve_evaluation_async

    monkeypatch.delenv('AIQ_DECLARED_TOKEN', raising=False)
    request = make_request('ok', engine_options={'required_secrets': ['AIQ_DECLARED_TOKEN']})
    context = ExecutionContext(output_dir=tmp_path)
    with pytest.raises(RequestValidationError):
        asyncio.run(resolve_evaluation_async(request, context))
    resolved = asyncio.run(resolve_evaluation_async(request, context, require_secrets=False))
    assert resolved.identity.reusable


def test_lock_held_lets_the_lock_holders_delegate_execute(tmp_path):
    # A scheduler gate holds the acquisition lock and runs ensure() in a child
    # (e.g. inside an endpoint lease); the child must not wait for itself.
    store = ResultStore(tmp_path / 'store')
    resolved = fake_backend.FakeBackend().resolve(make_request('ok'))

    async def scenario():
        async with store.acquisition_lock(resolved.identity.digest):
            return await asyncio.wait_for(ensure_evaluation_async(resolved, store, lock_held=True), 5)

    outcome = asyncio.run(scenario())
    assert outcome.action == 'executed' and not outcome.waited
    assert ensure_evaluation(resolved, store).reused
    with pytest.raises(ValueError, match='lock_held applies to execution'):
        ensure_evaluation(resolved, store, lock_held=True, import_source=_native(tmp_path / 'n', 0.5))


def test_an_import_normalizes_and_preserves_the_same_bytes(tmp_path, monkeypatch):
    # The reviewer's race: the source changes while it is being imported. The
    # import reads one snapshot, so the normalized value and the bundled native
    # file agree (and identify the content that was actually imported).
    store = ResultStore(tmp_path / 'store')
    source = _native(tmp_path / 'n', 0.25)
    real_import = fake_backend.FakeBackend.import_results

    def racing_import(self, resolved, snapshot, context):
        result = real_import(self, resolved, snapshot, context)
        (source / 'value.txt').write_text('0.75\n')  # changes after reading, before publishing
        return result

    monkeypatch.setattr(fake_backend.FakeBackend, 'import_results', racing_import)
    outcome = ensure_evaluation(make_request('imp'), store, import_source=source)
    assert _value(outcome) == 0.25
    assert (outcome.run.path / 'native' / 'value.txt').read_text() == '0.25\n'
    assert outcome.run.manifest['native_artifact_identity'] == outcome.import_identity


def test_an_import_of_other_content_than_expected_publishes_nothing(tmp_path):
    from magnet_evals.errors import ImportIdentityMismatch

    store = ResultStore(tmp_path / 'store')
    source = _native(tmp_path / 'n', 0.5)
    with pytest.raises(ImportIdentityMismatch, match='changed since'):
        ensure_evaluation(make_request('imp'), store, import_source=source, expected_import_identity='0' * 64)
    assert not (store.root / 'imports').exists()
    ok = ensure_evaluation(make_request('imp'), store, import_source=source,
                           expected_import_identity=native_source_identity(source))
    assert ok.action == 'imported'
