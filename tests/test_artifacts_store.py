
import pytest

from magnet_evals.artifacts import (
    ATTEMPT_TERMINAL,
    RUN_COMPLETE,
    RunBundle,
    publish_run,
)
from magnet_evals.contracts import (
    EvaluationRequest,
    EvaluationResult,
    ExecutionContext,
    MeasurementIdentity,
    MetricRecord,
    ModelBinding,
    ResolvedEvaluation,
    ResultRecord,
)
from magnet_evals.errors import ArtifactError
from magnet_evals.store import ResultStore


def make_resolved(*, reusable=True):
    request = EvaluationRequest(
        engine='olmo_eval',
        task='tiny',
        task_revision='t',
        data_revision='d',
        models=(ModelBinding(role='primary', model='m', revision='mr'),),
    )
    identity = MeasurementIdentity(
        algorithm='test',
        digest='a' * 64,
        reusable=reusable,
        unknown_reasons=() if reusable else ('unknown data',),
    )
    return ResolvedEvaluation(
        request=request,
        adapter_version='test',
        engine_version='test',
        native_config={'x': 1},
        identity=identity,
        resolved_facts={},
    )


def make_result(identity, status='succeeded'):
    metric = MetricRecord(task='tiny', model_role='primary', metric='accuracy', scorer='exact', value=1.0)
    record = ResultRecord(task='tiny', model_role='primary', metrics=(metric,))
    return EvaluationResult(engine='olmo_eval', identity=identity, status=status, records=(record,))


def test_atomic_bundle_and_engine_free_read(tmp_path):
    resolved = make_resolved()
    native = tmp_path / 'native-source'
    native.mkdir()
    (native / 'metrics.json').write_text('{"ok": true}\n')
    destination = tmp_path / 'run'
    context = ExecutionContext(output_dir=destination, env={'TOKEN': 'secret-value'})
    bundle = publish_run(
        destination,
        resolved=resolved,
        result=make_result(resolved.identity),
        context=context,
        native_dir=native,
    )
    assert bundle.complete
    assert (destination / RUN_COMPLETE).is_file()
    assert (destination / ATTEMPT_TERMINAL).is_file()
    assert 'secret-value' not in (destination / 'attempt.json').read_text()
    assert RunBundle.load(destination).result.records[0].metrics[0].value == 1.0


def test_failed_attempt_has_no_success_marker(tmp_path):
    resolved = make_resolved()
    destination = tmp_path / 'failed'
    bundle = publish_run(
        destination,
        resolved=resolved,
        result=make_result(resolved.identity, status='failed'),
        context=ExecutionContext(output_dir=destination),
    )
    assert not bundle.complete
    assert not (destination / RUN_COMPLETE).exists()
    # Failed terminal bundles remain inspectable.
    assert RunBundle.load(destination).result.status == 'failed'


def test_checksum_failure_is_detected(tmp_path):
    resolved = make_resolved()
    native = tmp_path / 'native'
    native.mkdir()
    (native / 'x.txt').write_text('original')
    destination = tmp_path / 'run'
    publish_run(
        destination,
        resolved=resolved,
        result=make_result(resolved.identity),
        context=ExecutionContext(output_dir=destination),
        native_dir=native,
    )
    (destination / 'native' / 'x.txt').write_text('changed')
    with pytest.raises(ArtifactError, match='checksum mismatch'):
        RunBundle.load(destination)


def test_content_addressed_store(tmp_path):
    resolved = make_resolved()
    store = ResultStore(tmp_path / 'store')
    context = ExecutionContext(output_dir=tmp_path / 'ignored')
    bundle = store.publish(
        resolved=resolved,
        result=make_result(resolved.identity),
        context=context,
    )
    assert bundle.path == store.run_path('a' * 64)
    assert store.lookup(resolved) is not None

    nonreusable = make_resolved(reusable=False)
    with pytest.raises(ValueError, match='non-reusable'):
        store.publish(
            resolved=nonreusable,
            result=make_result(nonreusable.identity),
            context=context,
        )


def _symlink_tree(tmp_path):
    native = tmp_path / 'native'
    outside = tmp_path / 'outside'
    (native / 'sub').mkdir(parents=True)
    outside.mkdir()
    (outside / 'id_rsa').write_text('PRIVATE-KEY-MATERIAL\n')
    (native / 'log.txt').write_text('native log\n')
    (native / 'innocent.log').symlink_to(outside / 'id_rsa')
    (native / 'dirlink').symlink_to(outside, target_is_directory=True)
    (native / 'sub' / 'internal.txt').symlink_to(native / 'log.txt')
    (native / 'loop').symlink_to(native, target_is_directory=True)
    return native


@pytest.mark.parametrize('mode', ['exclude', 'raise', 'follow'])
def test_external_symlinks_are_never_silently_copied(tmp_path, mode):
    from magnet_evals.artifacts import copy_native_tree
    from magnet_evals.errors import ArtifactError

    native = _symlink_tree(tmp_path)
    dest = tmp_path / 'dest'
    if mode == 'raise':
        with pytest.raises(ArtifactError, match='outside the source tree'):
            copy_native_tree(native, dest, external_symlinks=mode)
        return
    notes = copy_native_tree(native, dest, external_symlinks=mode)
    copied = {p.relative_to(dest).as_posix() for p in dest.rglob('*') if p.is_file()}
    assert {'log.txt', 'sub/internal.txt'} <= copied
    leaked = any('PRIVATE-KEY' in (dest / p).read_text() for p in copied)
    if mode == 'exclude':
        assert not leaked
        assert sorted(notes['excluded_external_symlinks']) == ['dirlink', 'innocent.log']
    else:
        assert leaked
        assert sorted(notes['followed_external_symlinks']) == ['dirlink', 'innocent.log']
    assert not any(p.is_symlink() for p in dest.rglob('*'))
